"""The rejection ladder: when a single request breaks several rules at once, which one of them
the service is obliged to name, and where the state of the program is left afterwards."""
import pytest

from test_helpers import (
    ApiErrorId,
    CYCLE_END,
    CYCLE_START,
    MILESTONE_DUE,
    WINDOW_END,
    WINDOW_START,
    WORK_DATE,
    add_scoped_request,
    api_client,
    availability_window_payload,
    build_user_headers,
    counter_payload,
    create_cycle,
    create_partner,
    create_skill_profile,
    create_vetted_volunteer,
    create_volunteer,
    deliverable_payload,
    deliverable_scores_payload,
    handoff_payload,
    make_partner_contact_headers,
    make_program_manager_headers,
    make_volunteer_headers,
    milestone_payload,
    project_request_payload,
    read_agreement,
    read_cycle,
    read_engagement,
    read_milestone,
    read_offer,
    read_partner,
    read_request,
    read_scope,
    read_volunteer,
    read_window,
    scope_change_request_payload,
    scope_definition_payload,
    set_clock,
    setup_accepted_engagement,
    setup_engagement,
    setup_held_milestone_engagement,
    setup_in_progress_engagement,
    setup_offer,
    setup_scoped_request,
    setup_scoping_request,
    setup_sent_agreement,
    setup_submitted_engagement,
    skill_profile_payload,
    time_log_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

NONEXISTENT_ID = "00000000-0000-4000-8000-000000000000"

MICRO_BUDGET = 90000.00

OFFER_EXPIRY_INSTANT = "2026-08-06T00:00:00Z"


# ---------------------------------------------------------------------------
# The top of the ladder: headers, role, ownership
# ---------------------------------------------------------------------------
def test_01_a_blank_user_id_header_is_named_before_any_row_is_looked_up(api):
    """PRD §2.12: "`X-User-Role` and `X-User-ID` are both present and non-blank, on every
    endpoint — otherwise `ERR_MISSING_AUTH_HEADERS` (401)."
    PRD §2.12: "The `PartnerOrg` named by a path segment exists — checked on
    `GET /partner-orgs/{id}`, `GET /partner-orgs/{id}/summary`,
    `GET /partner-orgs/{id}/satisfaction-surveys` and `PATCH /partner-orgs/{id}/status` —
    otherwise `ERR_PARTNER_ORG_NOT_FOUND` (404)."

    Design: Corner/validations/val_blank_user_id_header_rejected_before_any_lookup
    """
    blank_identity = build_user_headers("", "ProgramManager")

    response = api_client.get_partner_org(NONEXISTENT_ID, blank_identity)

    validate_error(response, ApiErrorId.ERR_MISSING_AUTH_HEADERS, expected_status=401)


def test_02_an_unauthorized_role_is_named_before_the_missing_partner_is(api):
    """PRD §2.12: "`X-User-Role` is one of the five named roles and is listed among the target
    endpoint's authorized roles, on every endpoint — otherwise `ERR_ROLE_NOT_PERMITTED` (403)."
    PRD §2.12: "The ordering is global: a check with a lower number always wins over a check
    with a higher number on the same endpoint."

    Design: Corner/validations/val_role_check_beats_existence_check_rejected
    """
    volunteer = create_volunteer()

    response = api_client.get_partner_org(
        NONEXISTENT_ID, make_volunteer_headers(volunteer["id"])
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)


def test_03_a_stranger_volunteer_is_refused_ownership_before_her_credentials_are_read(api):
    """PRD §2.12: "For the entity-backed roles, the caller owns the target resource —
    `ERR_NOT_RESOURCE_OWNER` (403) — on `POST /project-requests/{id}/submit-for-scoping`,
    `POST /scope-definitions/{id}/approve`, `POST /match-offers/{id}/accept`,
    `POST /match-offers/{id}/decline`, `POST /engagements/{id}/start`,
    `POST /engagements/{id}/submit`, `POST /engagements/{id}/time-logs`,
    `POST /engagements/{id}/scope-change-requests`,
    `POST /engagements/{id}/satisfaction-surveys`, `POST /agreements/{id}/counter`,
    `POST /agreements/{id}/execute`, `POST /volunteers/{id}/skill-profiles` and
    `POST /volunteers/{id}/availability-windows`."
    PRD §2.12: "The volunteer's `credential_verified_at` is not null — on
    `POST /volunteers/{id}/availability-windows` and `POST /match-offers/{id}/accept` —
    otherwise `ERR_CREDENTIAL_NOT_VERIFIED` (422)."

    Design: Corner/validations/val_other_volunteer_cannot_accept_offer_not_resource_owner
    """
    w = setup_offer()
    intruder = create_volunteer()

    response = api_client.accept_match_offer(
        w["offer"]["id"], make_volunteer_headers(intruder["id"])
    )

    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)
    offer = read_offer(w)
    assert offer["status"] == "OFFERED", (
        f"Expected the offer to stay OFFERED after a stranger's attempt, got {offer['status']}"
    )
    cycle = read_cycle(w)
    assert cycle["slots_reserved"] == 1, (
        f"Expected slots_reserved to stay 1, got {cycle['slots_reserved']}"
    )
    assert cycle["slots_committed"] == 0, (
        f"Expected slots_committed to stay 0, got {cycle['slots_committed']}"
    )


# ---------------------------------------------------------------------------
# Strict positivity and lifecycle from-sets
# ---------------------------------------------------------------------------
def test_04_a_zero_hour_time_log_is_refused_before_any_capacity_arithmetic(api):
    """PRD §2.12: "Quantities that must be strictly positive are strictly positive — a time
    log's `hours`, a revision's `estimated_hours`, a window's `hours_offered` and a
    deliverable's `weight_pct` — on `POST /engagements/{id}/time-logs`,
    `POST /project-requests/{id}/scope-definitions`,
    `POST /volunteers/{id}/availability-windows` and
    `POST /scope-definitions/{id}/deliverables`. A value of exactly 0 is refused here with
    `ERR_ZERO_HOURS_NOT_ALLOWED` (422), before any capacity arithmetic runs."

    Design: Corner/validations/val_zero_hour_time_log_rejected_before_capacity_math
    """
    w = setup_in_progress_engagement()

    response = api_client.create_time_log(
        w["engagement"]["id"],
        time_log_payload(work_date=WORK_DATE, hours=0.00),
        w["volunteer_headers"],
    )

    validate_error(response, ApiErrorId.ERR_ZERO_HOURS_NOT_ALLOWED, expected_status=422)
    _, meta = validate_paginated(
        api_client.list_time_logs(w["engagement"]["id"], w["pm_headers"])
    )
    assert meta["total_count"] == 0, (
        f"Expected no time log to have been written, got {meta['total_count']}"
    )
    engagement = read_engagement(w)
    assert engagement["approved_hours"] == pytest.approx(0.00, abs=0.01), (
        f"Expected approved_hours to stay 0.00, got {engagement['approved_hours']}"
    )


def test_05_a_deliverable_cannot_be_added_to_an_approved_revision(api):
    """PRD §2.12: "The scope revision's `status` is `DRAFT` — on
    `POST /scope-definitions/{id}/approve` and `POST /scope-definitions/{id}/deliverables` —
    otherwise `ERR_INVALID_SCOPE_STATE` (409)."
    PRD §2.12: "A deliverable's `sequence_no` is unique within its revision, and at approval
    time the revision's `deliverable_weight_total_pct` equals exactly 100.00 over
    non-`WAIVED` deliverables with `deliverable_count` of at least 1 — on
    `POST /scope-definitions/{id}/deliverables` and `POST /scope-definitions/{id}/approve` —
    otherwise `ERR_DELIVERABLE_WEIGHT_TOTAL_INVALID` (422)."

    Design: Corner/validations/val_deliverable_cannot_be_added_to_approved_scope_revision
    """
    w = setup_scoped_request()

    response = api_client.create_deliverable(
        w["scope"]["id"],
        deliverable_payload(
            title="Late addition", sequence_no=3, weight_pct=10.00, hours_estimate=4.00
        ),
        w["spec_headers"],
    )

    validate_error(response, ApiErrorId.ERR_INVALID_SCOPE_STATE, expected_status=409)
    scope = read_scope(w)
    assert scope["status"] == "APPROVED", (
        f"Expected the revision to stay APPROVED, got {scope['status']}"
    )
    assert scope["deliverable_count"] == 2, (
        f"Expected deliverable_count to stay 2, got {scope['deliverable_count']}"
    )
    assert scope["deliverable_weight_total_pct"] == pytest.approx(100.00, abs=0.01), (
        f"Expected the weight total to stay 100.00, got "
        f"{scope['deliverable_weight_total_pct']}"
    )


def test_06_an_agreement_already_out_for_signature_cannot_be_sent_again(api):
    """PRD §2.12: "The agreement's `status` is in the from-set of the requested transition —
    send requires `DRAFTED` or `COUNTERED`, counter requires `SENT`, execute requires `SENT`,
    void requires `DRAFTED`, `SENT` or `COUNTERED` — on `POST /agreements/{id}/send`,
    `POST /agreements/{id}/counter`, `POST /agreements/{id}/execute` and
    `POST /agreements/{id}/void`, otherwise `ERR_INVALID_AGREEMENT_STATE` (409)."

    Design: Corner/validations/val_agreement_cannot_be_sent_twice_invalid_agreement_state
    """
    w = setup_sent_agreement()

    response = api_client.send_agreement(w["agreement"]["id"], w["pm_headers"])

    validate_error(response, ApiErrorId.ERR_INVALID_AGREEMENT_STATE, expected_status=409)
    agreement = read_agreement(w)
    assert agreement["status"] == "SENT", (
        f"Expected the agreement to stay SENT, got {agreement['status']}"
    )
    assert agreement["terms_revision_no"] == 1, (
        f"Expected terms_revision_no to stay 1 after the refused resend, got "
        f"{agreement['terms_revision_no']}"
    )
    assert agreement["counter_round"] == 0, (
        f"Expected counter_round to stay 0, got {agreement['counter_round']}"
    )
    assert agreement["volunteer_signed_at"] is None, (
        f"Expected volunteer_signed_at to stay null, got {agreement['volunteer_signed_at']}"
    )


def test_07_a_check_in_already_held_cannot_be_held_a_second_time(api):
    """PRD §2.12: "The milestone's `checkin_status` is `SCHEDULED` — on
    `POST /milestones/{id}/hold` — otherwise `ERR_MILESTONE_NOT_SCHEDULED` (409)."

    Design: Corner/validations/val_milestone_cannot_be_held_twice
    """
    w = setup_held_milestone_engagement()

    response = api_client.hold_milestone(
        w["milestone"]["id"], {"reported_cumulative_hours": 44.00}, w["pm_headers"]
    )

    validate_error(response, ApiErrorId.ERR_MILESTONE_NOT_SCHEDULED, expected_status=409)
    milestone = read_milestone(w)
    assert milestone["checkin_status"] == "HELD", (
        f"Expected the milestone to stay HELD, got {milestone['checkin_status']}"
    )
    assert milestone["reported_cumulative_hours"] == pytest.approx(40.00, abs=0.01), (
        f"Expected the first hold's reported figure of 40.00 to stand, got "
        f"{milestone['reported_cumulative_hours']}"
    )
    assert milestone["variance_hours"] == pytest.approx(0.00, abs=0.01), (
        f"Expected variance_hours to stay 0.00, got {milestone['variance_hours']}"
    )
    engagement = read_engagement(w)
    assert engagement["approved_hours"] == pytest.approx(40.00, abs=0.01), (
        f"Expected approved_hours to stay 40.00, got {engagement['approved_hours']}"
    )


def test_08_an_unscored_review_round_cannot_be_decided(api):
    """PRD §2.12: "The quality review's `status` is `OPEN` for scoring and `SCORED` for
    deciding — on `POST /quality-reviews/{id}/score` and `POST /quality-reviews/{id}/decide` —
    otherwise `ERR_REVIEW_NOT_SCORED` (409)."
    PRD §3.8: "The new review is created in `status` `OPEN` with a `round_no` one greater than
    the highest among its siblings on that engagement, a `reviewer_user_id` recording the
    opening operator's `X-User-ID`, a `scored_deliverable_count` of 0, a null
    `weighted_score`, an `outcome` of `PENDING`, and null `rework_deadline_at` and
    `decided_at`."

    Design: Corner/validations/val_review_cannot_be_decided_before_scoring
    """
    w = setup_submitted_engagement()
    review = validate_success(
        api_client.create_quality_review(w["engagement"]["id"], w["reviewer_headers"]), 201
    )

    response = api_client.decide_quality_review(review["id"], w["reviewer_headers"])

    validate_error(response, ApiErrorId.ERR_REVIEW_NOT_SCORED, expected_status=409)
    assert review["status"] == "OPEN", (
        f"Expected the round to have opened OPEN, got {review['status']}"
    )
    assert review["outcome"] == "PENDING", (
        f"Expected the round to carry a PENDING outcome, got {review['outcome']}"
    )
    engagement = read_engagement(w)
    assert engagement["work_status"] == "SUBMITTED", (
        f"Expected the engagement to stay SUBMITTED, got {engagement['work_status']}"
    )
    assert engagement["quality_gate"] == "PENDING", (
        f"Expected the quality gate to stay PENDING, got {engagement['quality_gate']}"
    )


def test_09_a_change_request_applied_on_arrival_cannot_be_decided_afterwards(api):
    """PRD §2.12: "The scope change request's `status` is `PENDING` — on
    `POST /scope-change-requests/{id}/decide` — otherwise `ERR_SCOPE_CHANGE_NOT_PENDING`
    (409)."
    PRD §3.7: "An `AUTO_APPROVABLE` change is applied at once, moving `PENDING → APPROVED` in
    the same operation: the engagement's `committed_hours` rises by `additional_hours` and the
    holding window's `hours_committed` rises by the same amount, after which the creep
    calculation reruns against the *new* baseline and therefore normally reads a lower
    `creep_escalation_level` than before."

    Design: Corner/validations/val_auto_approved_scope_change_cannot_be_decided
    """
    w = setup_in_progress_engagement()
    change = validate_success(
        api_client.create_scope_change_request(
            w["engagement"]["id"],
            scope_change_request_payload(additional_hours=4.00, additional_deliverable_count=0),
            w["volunteer_headers"],
        ),
        201,
    )
    assert change["decision_tier"] == "AUTO_APPROVABLE", (
        f"Expected a 4.00-hour ask against a 40.00-hour baseline to be AUTO_APPROVABLE, got "
        f"{change['decision_tier']}"
    )

    response = api_client.decide_scope_change_request(
        change["id"], {"decision": "APPROVE"}, w["pm_headers"]
    )

    validate_error(response, ApiErrorId.ERR_SCOPE_CHANGE_NOT_PENDING, expected_status=409)
    engagement = read_engagement(w)
    assert engagement["committed_hours"] == pytest.approx(44.00, abs=0.01), (
        f"Expected committed_hours to stay at the once-applied 44.00, got "
        f"{engagement['committed_hours']}"
    )
    window = read_window(w)
    assert window["hours_committed"] == pytest.approx(44.00, abs=0.01), (
        f"Expected the window to hold 44.00 committed hours and no more, got "
        f"{window['hours_committed']}"
    )


def test_10_a_scope_revision_drafted_against_a_superseded_version_is_refused(api):
    """PRD §2.12: "`expected_project_request_version` equals the request's current `version` —
    on `POST /project-requests/{id}/scope-definitions` — otherwise
    `ERR_STALE_PROJECT_REQUEST_VERSION` (412)."
    PRD §3.3: "Any sibling revision still sitting in `DRAFT` moves to `WITHDRAWN` at once, and
    the parent request's `version` advances by one."

    Design: Corner/validations/val_stale_expected_project_request_version_rejected
    """
    w = setup_scoping_request()
    stale_version = w["request"]["version"]

    response = api_client.create_scope_definition(
        w["request"]["id"],
        scope_definition_payload(stale_version, estimated_hours=50.00),
        w["spec_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_STALE_PROJECT_REQUEST_VERSION, expected_status=412
    )
    rows, meta = validate_paginated(
        api_client.list_scope_definitions(
            w["pm_headers"], params={"project_request_id": w["request"]["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"Expected the request to still carry exactly one revision, got {meta['total_count']}"
    )
    assert rows[0]["revision_no"] == 1, (
        f"Expected the surviving revision to be revision_no 1, got {rows[0]['revision_no']}"
    )
    request = read_request(w)
    assert request["status"] == "SCOPING", (
        f"Expected the request to stay SCOPING, got {request['status']}"
    )
    assert request["active_scope_revision_no"] == 0, (
        f"Expected active_scope_revision_no to read 0 while no revision is APPROVED, got "
        f"{request['active_scope_revision_no']}"
    )


# ---------------------------------------------------------------------------
# Standing of the parties: partner suspension, volunteer credentials and status
# ---------------------------------------------------------------------------
def test_11_a_suspended_partner_cannot_open_a_new_request(api):
    """PRD §2.12: "The owning partner's `status` is not `SUSPENDED` — on
    `POST /project-requests`, `POST /project-requests/{id}/submit-for-scoping`,
    `POST /scope-definitions/{id}/approve`, `POST /project-requests/{id}/match` and
    `POST /engagements/{id}/satisfaction-surveys` — otherwise `ERR_PARTNER_SUSPENDED` (403)."

    Design: Corner/validations/val_suspended_partner_cannot_open_new_request
    """
    pm = make_program_manager_headers()
    cycle = create_cycle(pm)
    partner = create_partner(pm)
    partner_headers = make_partner_contact_headers(partner["id"])
    validate_success(
        api_client.patch_partner_org_status(partner["id"], {"to_status": "SUSPENDED"}, pm)
    )

    response = api_client.create_project_request(
        project_request_payload(partner["id"], cycle["id"]), partner_headers
    )

    validate_error(response, ApiErrorId.ERR_PARTNER_SUSPENDED, expected_status=403)
    _, meta = validate_paginated(
        api_client.list_project_requests(pm, params={"partner_org_id": partner["id"]})
    )
    assert meta["total_count"] == 0, (
        f"Expected no request to have been filed for the suspended partner, got "
        f"{meta['total_count']}"
    )
    reread = validate_success(api_client.get_partner_org(partner["id"], pm))
    assert reread["status"] == "SUSPENDED", (
        f"Expected the partner to stay SUSPENDED, got {reread['status']}"
    )
    assert reread["open_engagement_count"] == 0, (
        f"Expected open_engagement_count to stay 0, got {reread['open_engagement_count']}"
    )


def test_12_an_unvetted_volunteer_cannot_publish_availability(api):
    """PRD §2.12: "The volunteer's `credential_verified_at` is not null — on
    `POST /volunteers/{id}/availability-windows` and `POST /match-offers/{id}/accept` —
    otherwise `ERR_CREDENTIAL_NOT_VERIFIED` (422)."

    Design: Corner/validations/val_unvetted_volunteer_cannot_declare_availability
    """
    pm = make_program_manager_headers()
    create_cycle(pm)
    volunteer = create_volunteer(pm)
    volunteer_headers = make_volunteer_headers(volunteer["id"])

    response = api_client.create_availability_window(
        volunteer["id"],
        availability_window_payload(starts_at=WINDOW_START, ends_at=WINDOW_END),
        volunteer_headers,
    )

    validate_error(response, ApiErrorId.ERR_CREDENTIAL_NOT_VERIFIED, expected_status=422)
    _, meta = validate_paginated(
        api_client.list_availability_windows(volunteer["id"], pm)
    )
    assert meta["total_count"] == 0, (
        f"Expected no window to have been published, got {meta['total_count']}"
    )
    reread = validate_success(api_client.get_volunteer(volunteer["id"], pm))
    assert reread["status"] == "PENDING_VETTING", (
        f"Expected the volunteer to stay PENDING_VETTING, got {reread['status']}"
    )
    assert reread["credential_verified_at"] is None, (
        f"Expected credential_verified_at to stay null, got "
        f"{reread['credential_verified_at']}"
    )


def test_13_a_paused_volunteer_cannot_log_hours(api):
    """PRD §2.12: "The volunteer's `status` is `ACTIVE` — on `POST /match-offers/{id}/accept`,
    `POST /engagements/{id}/start`, `POST /engagements/{id}/time-logs` and
    `POST /engagements/{id}/submit` — otherwise `ERR_VOLUNTEER_NOT_ACTIVE` (409)."

    Design: Corner/validations/val_paused_volunteer_cannot_log_time
    """
    w = setup_in_progress_engagement()
    validate_success(
        api_client.patch_volunteer_status(
            w["volunteer"]["id"],
            {"to_status": "PAUSED", "pause_reason": "ADMIN"},
            w["pm_headers"],
        )
    )

    response = api_client.create_time_log(
        w["engagement"]["id"],
        time_log_payload(work_date=WORK_DATE, hours=6.00),
        w["volunteer_headers"],
    )

    validate_error(response, ApiErrorId.ERR_VOLUNTEER_NOT_ACTIVE, expected_status=409)
    _, meta = validate_paginated(
        api_client.list_time_logs(w["engagement"]["id"], w["pm_headers"])
    )
    assert meta["total_count"] == 0, (
        f"Expected no hour to have been recorded, got {meta['total_count']}"
    )
    volunteer = read_volunteer(w)
    assert volunteer["status"] == "PAUSED", (
        f"Expected the volunteer to be PAUSED, got {volunteer['status']}"
    )
    engagement = read_engagement(w)
    assert engagement["work_status"] == "IN_PROGRESS", (
        f"Expected the engagement to stay IN_PROGRESS, got {engagement['work_status']}"
    )
    assert engagement["committed_hours"] == pytest.approx(40.00, abs=0.01), (
        f"Expected committed_hours to stay 40.00, got {engagement['committed_hours']}"
    )


# ---------------------------------------------------------------------------
# Terms of the deal: attestation, IP alignment, execution
# ---------------------------------------------------------------------------
def test_14_a_handoff_without_a_confidentiality_attestation_is_refused(api):
    """PRD §2.12: "The handoff payload carries `confidentiality_attested` set to true and, when
    the pinned revision's `confidentiality_tier` is `RESTRICTED`, also a non-empty
    `destruction_certificate_ref` — on `POST /engagements/{id}/handoff` — otherwise
    `ERR_CONFIDENTIALITY_ATTESTATION_MISSING` (422)."

    Design: Corner/validations/val_handoff_without_confidentiality_attestation_rejected
    """
    w = setup_accepted_engagement(cycle_slots=4)

    response = api_client.handoff_engagement(
        w["engagement"]["id"],
        handoff_payload(confidentiality_attested=False, handoff_artifact_count=3),
        w["pm_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_CONFIDENTIALITY_ATTESTATION_MISSING, expected_status=422
    )
    engagement = read_engagement(w)
    assert engagement["work_status"] == "ACCEPTED", (
        f"Expected the engagement to stay ACCEPTED, got {engagement['work_status']}"
    )
    request = read_request(w)
    assert request["status"] == "IN_DELIVERY", (
        f"Expected the parent request to stay IN_DELIVERY, got {request['status']}"
    )
    cycle = read_cycle(w)
    assert cycle["slots_committed"] == 1, (
        f"Expected the engagement to keep holding its slot, got "
        f"{cycle['slots_committed']}"
    )
    assert cycle["utilization_ratio"] == pytest.approx(0.2500, abs=0.0001), (
        f"Expected utilization_ratio 0.2500 with one of four slots held, got "
        f"{cycle['utilization_ratio']}"
    )


def test_15_an_agreement_whose_ip_terms_diverge_cannot_be_executed(api):
    """PRD §2.12: "The agreement's `ip_disposition` equals the pinned revision's
    `ip_disposition`, and the agreement's `confidentiality_tier` is not weaker than the pinned
    revision's, under the ordering where `STANDARD` is weakest, `ELEVATED` sits above it and
    `RESTRICTED` is strongest — on `POST /agreements/{id}/execute` and
    `POST /engagements/{id}/handoff` — otherwise `ERR_IP_TERMS_MISMATCH` (409)."

    Design: Corner/validations/val_ip_terms_mismatch_blocks_agreement_execution
    """
    w = setup_sent_agreement(
        ip_disposition="ASSIGN_TO_PARTNER",
        agreement_ip_disposition="RETAINED_BY_VOLUNTEER",
    )

    response = api_client.execute_agreement(w["agreement"]["id"], w["volunteer_headers"])

    validate_error(response, ApiErrorId.ERR_IP_TERMS_MISMATCH, expected_status=409)
    agreement = read_agreement(w)
    assert agreement["status"] == "SENT", (
        f"Expected the agreement to stay SENT, got {agreement['status']}"
    )
    assert agreement["volunteer_signed_at"] is None, (
        f"Expected volunteer_signed_at to stay null, got {agreement['volunteer_signed_at']}"
    )
    engagement = read_engagement(w)
    assert engagement["work_status"] == "NOT_STARTED", (
        f"Expected the engagement to stay NOT_STARTED, got {engagement['work_status']}"
    )


def test_16_work_cannot_start_before_the_agreement_is_executed(api):
    """PRD §2.12: "The engagement's agreement has `status` `EXECUTED` — on
    `POST /engagements/{id}/start` and `POST /engagements/{id}/time-logs` — otherwise
    `ERR_AGREEMENT_NOT_EXECUTED` (409)."

    Design: Corner/validations/val_start_without_executed_agreement_rejected
    """
    w = setup_sent_agreement()

    response = api_client.start_engagement(w["engagement"]["id"], w["volunteer_headers"])

    validate_error(response, ApiErrorId.ERR_AGREEMENT_NOT_EXECUTED, expected_status=409)
    engagement = read_engagement(w)
    assert engagement["work_status"] == "NOT_STARTED", (
        f"Expected the engagement to stay NOT_STARTED, got {engagement['work_status']}"
    )
    request = read_request(w)
    assert request["status"] == "ENGAGED", (
        f"Expected the parent request to stay ENGAGED, got {request['status']}"
    )
    agreement = read_agreement(w)
    assert agreement["status"] == "SENT", (
        f"Expected the agreement to stay SENT before either party signs, got "
        f"{agreement['status']}"
    )


def test_17_the_same_side_cannot_counter_two_revisions_in_a_row(api):
    """PRD §3.6: "Two conditions guard it: `counter_round` must be below 3, and the countering
    party must differ from `last_countered_by`, so the same side cannot counter twice in a row.
    A violation of either is refused with `ERR_COUNTER_LIMIT_EXCEEDED`."

    Design: Corner/validations/val_same_party_cannot_counter_twice_in_a_row
    """
    w = setup_sent_agreement()
    validate_success(
        api_client.counter_agreement(
            w["agreement"]["id"],
            counter_payload(confidentiality_tier="ELEVATED", indemnity_cap_usd=5000.00),
            w["volunteer_headers"],
        )
    )
    validate_success(api_client.send_agreement(w["agreement"]["id"], w["pm_headers"]))

    response = api_client.counter_agreement(
        w["agreement"]["id"],
        counter_payload(confidentiality_tier="RESTRICTED", indemnity_cap_usd=2500.00),
        w["volunteer_headers"],
    )

    validate_error(response, ApiErrorId.ERR_COUNTER_LIMIT_EXCEEDED, expected_status=409)
    agreement = read_agreement(w)
    assert agreement["status"] == "SENT", (
        f"Expected the agreement to stay SENT after the refused second counter, got "
        f"{agreement['status']}"
    )
    assert agreement["counter_round"] == 1, (
        f"Expected counter_round to stay 1, got {agreement['counter_round']}"
    )
    assert agreement["terms_revision_no"] == 2, (
        f"Expected terms_revision_no to stay 2, got {agreement['terms_revision_no']}"
    )
    assert agreement["last_countered_by"] == "VOLUNTEER", (
        f"Expected last_countered_by to stay VOLUNTEER, got "
        f"{agreement['last_countered_by']}"
    )
    assert agreement["confidentiality_tier"] == "ELEVATED", (
        f"Expected the first counter's ELEVATED tier to stand, got "
        f"{agreement['confidentiality_tier']}"
    )


# ---------------------------------------------------------------------------
# Closed and half-open geometry: expiry instants, intervals, buffers
# ---------------------------------------------------------------------------
def test_18_an_offer_cannot_be_accepted_at_the_very_instant_it_expires(api):
    """PRD §2.12: "The logical clock is strictly before the offer's `expires_at` — on
    `POST /match-offers/{id}/accept` and `POST /match-offers/{id}/decline` — otherwise
    `ERR_OFFER_EXPIRED` (409)."
    PRD §3.4: "Its `reserved_hours` is the required-hours figure computed above, its
    `offered_at` is the logical clock, and its `expires_at` is `offered_at` plus a
    time-to-live chosen by the request's `urgency`: five days for a `ROUTINE` request, three
    days for an `ELEVATED` one, and a single day for a `CRITICAL` one."

    Design: Corner/validations/val_offer_cannot_be_accepted_at_the_expiry_instant
    """
    w = setup_offer(urgency="ROUTINE")
    assert w["offer"]["expires_at"].startswith("2026-08-06T00:00:00"), (
        f"Expected a ROUTINE offer opened at 2026-08-01T00:00:00Z to expire at "
        f"2026-08-06T00:00:00Z, got {w['offer']['expires_at']}"
    )
    set_clock(OFFER_EXPIRY_INSTANT, w["pm_headers"])

    response = api_client.accept_match_offer(w["offer"]["id"], w["volunteer_headers"])

    validate_error(response, ApiErrorId.ERR_OFFER_EXPIRED, expected_status=409)
    offer = read_offer(w)
    assert offer["responded_at"] is None, (
        f"Expected responded_at to stay null, got {offer['responded_at']}"
    )
    cycle = read_cycle(w)
    assert cycle["slots_committed"] == 0, (
        f"Expected slots_committed to stay 0, got {cycle['slots_committed']}"
    )


def test_19_a_window_reaching_past_the_last_cycle_is_refused(api):
    """PRD §2.12: "A new availability window has `ends_at` strictly after `starts_at` and its
    whole half-open interval lies inside some program cycle's half-open interval — on
    `POST /volunteers/{id}/availability-windows` — otherwise `ERR_WINDOW_OUTSIDE_CYCLE` (422)."

    Design: Corner/validations/val_window_extending_past_cycle_end_rejected
    """
    pm = make_program_manager_headers()
    create_cycle(pm, starts_at=CYCLE_START, ends_at=CYCLE_END)
    volunteer, _, _ = create_vetted_volunteer(window=False)

    response = api_client.create_availability_window(
        volunteer["id"],
        availability_window_payload(
            starts_at=CYCLE_START, ends_at="2026-12-02T00:00:00Z", hours_offered=100.00
        ),
        make_volunteer_headers(volunteer["id"]),
    )

    validate_error(response, ApiErrorId.ERR_WINDOW_OUTSIDE_CYCLE, expected_status=422)
    _, meta = validate_paginated(api_client.list_availability_windows(volunteer["id"], pm))
    assert meta["total_count"] == 0, (
        f"Expected no window to have been published, got {meta['total_count']}"
    )


def test_20_the_clock_refuses_to_regress_but_accepts_its_own_instant(api):
    """PRD §2.5: "The clock only moves forward: an instant strictly earlier than the current
    clock reading is rejected with `ERR_CLOCK_REGRESSION` (HTTP 422), while an instant exactly
    equal to the current reading is accepted and leaves the clock where it is."

    Design: Corner/validations/val_clock_cannot_move_backwards
    """
    pm = make_program_manager_headers()
    set_clock("2026-08-05T00:00:00Z", pm)

    response = api_client.set_clock({"to_iso8601": "2026-08-04T23:59:59Z"}, pm)

    validate_error(response, ApiErrorId.ERR_CLOCK_REGRESSION, expected_status=422)
    validate_success(api_client.set_clock({"to_iso8601": "2026-08-05T00:00:00Z"}, pm))


def test_21_a_window_starting_the_instant_another_ends_is_accepted(api):
    """PRD §3.2: "Exact adjacency — a new window starting at the precise instant an existing
    one ends — is permitted, and no buffer and no aggregate cap on total offered hours
    participate in this check."

    Design: Corner/validations/val_exactly_adjacent_availability_windows_accepted
    """
    pm = make_program_manager_headers()
    create_cycle(pm, starts_at=CYCLE_START, ends_at=CYCLE_END)
    volunteer, _, first = create_vetted_volunteer(
        window_overrides={
            "starts_at": CYCLE_START,
            "ends_at": "2026-09-01T00:00:00Z",
            "window_kind": "HARD",
            "hours_offered": 120.00,
        }
    )

    second = validate_success(
        api_client.create_availability_window(
            volunteer["id"],
            availability_window_payload(
                starts_at="2026-09-01T00:00:00Z",
                ends_at="2026-10-01T00:00:00Z",
                window_kind="SOFT",
                hours_offered=60.00,
            ),
            make_volunteer_headers(volunteer["id"]),
        ),
        201,
    )

    assert second["window_kind"] == "SOFT", (
        f"Expected the adjacent window to be SOFT, got {second['window_kind']}"
    )
    assert second["hours_committed"] == pytest.approx(0.00, abs=0.01), (
        f"Expected hours_committed to start at 0.00, got {second['hours_committed']}"
    )
    assert second["hours_remaining"] == pytest.approx(60.00, abs=0.01), (
        f"Expected hours_remaining to start at the full 60.00, got "
        f"{second['hours_remaining']}"
    )
    rows, meta = validate_paginated(
        api_client.list_availability_windows(volunteer["id"], pm)
    )
    assert meta["total_count"] == 2, (
        f"Expected both windows to coexist, got {meta['total_count']}"
    )
    earlier = next(row for row in rows if row["id"] == first["id"])
    assert earlier["hours_remaining"] == pytest.approx(120.00, abs=0.01), (
        f"Expected the earlier window's 120.00 hours to be untouched, got "
        f"{earlier['hours_remaining']}"
    )


def test_22_a_check_in_seventy_one_hours_from_a_sibling_is_refused(api):
    """PRD §3.7: "It must sit at least three days away from the `due_at` of every sibling
    milestone whose `checkin_status` is `SCHEDULED` or `HELD` — the buffer is 72 hours and its
    geometry is closed, so a separation of exactly 72 hours is accepted while anything strictly
    closer is refused with `ERR_MILESTONE_SPACING_VIOLATION`."

    Design: Corner/validations/val_milestone_seventy_one_hours_apart_rejected
    """
    w = setup_in_progress_engagement()
    validate_success(
        api_client.create_milestone(
            w["engagement"]["id"], milestone_payload(due_at=MILESTONE_DUE), w["pm_headers"]
        ),
        201,
    )

    response = api_client.create_milestone(
        w["engagement"]["id"],
        milestone_payload(due_at="2026-08-22T23:00:00Z"),
        w["pm_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_MILESTONE_SPACING_VIOLATION, expected_status=409
    )
    rows, meta = validate_paginated(
        api_client.list_milestones(w["engagement"]["id"], w["pm_headers"])
    )
    assert meta["total_count"] == 1, (
        f"Expected the engagement to carry exactly one check-in, got {meta['total_count']}"
    )
    assert rows[0]["sequence_no"] == 1, (
        f"Expected the surviving check-in to be sequence_no 1, got {rows[0]['sequence_no']}"
    )


def test_23_a_third_check_in_inside_a_fortnight_saturates_the_volunteer(api):
    """PRD §3.7: "And the volunteer must not be saturated across her whole portfolio: counting
    milestones with `checkin_status` `SCHEDULED` across *all* engagements of that volunteer
    whose `due_at` falls within the closed fortnight running from seven days before the new
    `due_at` to seven days after it, at most two may already exist before the new row is added,
    so the third such check-in in any rolling fourteen-day span is refused with
    `ERR_VOLUNTEER_CHECKIN_SATURATED`."

    Design: Corner/validations/val_third_milestone_in_fourteen_day_window_saturated
    """
    w = setup_in_progress_engagement()
    for due_at in ("2026-08-20T00:00:00Z", "2026-08-23T00:00:00Z"):
        validate_success(
            api_client.create_milestone(
                w["engagement"]["id"], milestone_payload(due_at=due_at), w["pm_headers"]
            ),
            201,
        )

    response = api_client.create_milestone(
        w["engagement"]["id"],
        milestone_payload(due_at="2026-08-26T00:00:00Z"),
        w["pm_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_VOLUNTEER_CHECKIN_SATURATED, expected_status=409
    )
    rows, meta = validate_paginated(
        api_client.list_milestones(w["engagement"]["id"], w["pm_headers"])
    )
    assert meta["total_count"] == 2, (
        f"Expected the two scheduled check-ins to stand alone, got {meta['total_count']}"
    )
    assert sorted(row["sequence_no"] for row in rows) == [1, 2], (
        f"Expected sequence numbers 1 and 2 only, got "
        f"{sorted(row['sequence_no'] for row in rows)}"
    )


# ---------------------------------------------------------------------------
# Uniqueness and set arithmetic
# ---------------------------------------------------------------------------
def test_24_a_volunteer_cannot_claim_the_same_skill_code_twice(api):
    """PRD §2.12: "The pair of `volunteer_id` and `skill_code` is unique across skill profiles —
    on `POST /volunteers/{id}/skill-profiles` — otherwise `ERR_DUPLICATE_SKILL_PROFILE` (409)."

    Design: Corner/validations/val_duplicate_skill_code_on_same_volunteer_rejected
    """
    pm = make_program_manager_headers()
    volunteer = create_volunteer(pm)
    create_skill_profile(
        volunteer["id"], skill_code="TAX_LAW", proficiency=4, years_experience=9.0
    )

    response = api_client.create_skill_profile(
        volunteer["id"],
        skill_profile_payload(skill_code="TAX_LAW", proficiency=5, years_experience=12.0),
        make_volunteer_headers(volunteer["id"]),
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_SKILL_PROFILE, expected_status=409)
    rows, meta = validate_paginated(api_client.list_skill_profiles(volunteer["id"], pm))
    assert meta["total_count"] == 1, (
        f"Expected the volunteer to keep exactly one skill claim, got {meta['total_count']}"
    )
    assert rows[0]["proficiency"] == 4, (
        f"Expected the first claim's proficiency 4 to stand, got {rows[0]['proficiency']}"
    )
    assert rows[0]["years_experience"] == pytest.approx(9.0, abs=0.05), (
        f"Expected the first claim's 9.0 years to stand, got {rows[0]['years_experience']}"
    )


def test_25_a_revision_weighted_to_sixty_percent_cannot_be_approved(api):
    """PRD §3.3: "A weight total that is not exactly 100.00 at this moment is refused with
    `ERR_DELIVERABLE_WEIGHT_TOTAL_INVALID`; approving a revision that is not in `DRAFT` is
    refused with `ERR_INVALID_SCOPE_STATE`."

    Design: Corner/validations/val_scope_approve_with_weight_total_below_100_rejected
    """
    w = setup_scoping_request(
        deliverables=[
            {
                "title": "Findings memo",
                "sequence_no": 1,
                "weight_pct": 60.00,
                "hours_estimate": 24.00,
                "acceptance_criteria": "Board-ready memo with cited findings.",
            }
        ]
    )

    response = api_client.approve_scope_definition(
        w["scope"]["id"], w["partner_headers"]
    )

    validate_error(
        response, ApiErrorId.ERR_DELIVERABLE_WEIGHT_TOTAL_INVALID, expected_status=422
    )
    scope = read_scope(w)
    assert scope["status"] == "DRAFT", (
        f"Expected the revision to stay DRAFT, got {scope['status']}"
    )
    assert scope["deliverable_count"] == 1, (
        f"Expected deliverable_count 1, got {scope['deliverable_count']}"
    )
    assert scope["deliverable_weight_total_pct"] == pytest.approx(60.00, abs=0.01), (
        f"Expected the weight total to read 60.00, got "
        f"{scope['deliverable_weight_total_pct']}"
    )
    assert scope["approved_at"] is None, (
        f"Expected approved_at to stay null, got {scope['approved_at']}"
    )
    request = read_request(w)
    assert request["status"] == "SCOPING", (
        f"Expected the request to stay SCOPING, got {request['status']}"
    )
    assert request["active_scope_revision_no"] == 0, (
        f"Expected active_scope_revision_no to stay 0, got "
        f"{request['active_scope_revision_no']}"
    )


def test_26_a_score_that_omits_one_deliverable_is_refused(api):
    """PRD §2.12: "The `deliverable_scores` set is exactly the set of non-`WAIVED` deliverables
    on the pinned revision, non-empty, with no extras and no omissions — on
    `POST /quality-reviews/{id}/score` — otherwise `ERR_DELIVERABLE_SET_MISMATCH` (422)."
    PRD §3.8: "The new review is created in `status` `OPEN` with a `round_no` one greater than
    the highest among its siblings on that engagement, a `reviewer_user_id` recording the
    opening operator's `X-User-ID`, a `scored_deliverable_count` of 0, a null
    `weighted_score`, an `outcome` of `PENDING`, and null `rework_deadline_at` and
    `decided_at`."

    Design: Corner/validations/val_score_omitting_one_deliverable_rejected
    """
    w = setup_submitted_engagement()
    review = validate_success(
        api_client.create_quality_review(w["engagement"]["id"], w["reviewer_headers"]), 201
    )

    response = api_client.score_quality_review(
        review["id"],
        deliverable_scores_payload({w["deliverables"][0]["id"]: 5}),
        w["reviewer_headers"],
    )

    validate_error(response, ApiErrorId.ERR_DELIVERABLE_SET_MISMATCH, expected_status=422)
    rows, _ = validate_paginated(
        api_client.list_quality_reviews(w["engagement"]["id"], w["pm_headers"])
    )
    stored = next(row for row in rows if row["id"] == review["id"])
    assert stored["status"] == "OPEN", (
        f"Expected the round to stay OPEN, got {stored['status']}"
    )
    assert stored["scored_deliverable_count"] == 0, (
        f"Expected scored_deliverable_count to stay 0, got "
        f"{stored['scored_deliverable_count']}"
    )
    assert stored["weighted_score"] is None, (
        f"Expected weighted_score to stay null, got {stored['weighted_score']}"
    )
    assert stored["outcome"] == "PENDING", (
        f"Expected the outcome to stay PENDING, got {stored['outcome']}"
    )
    engagement = read_engagement(w)
    assert engagement["work_status"] == "SUBMITTED", (
        f"Expected the engagement to stay SUBMITTED, got {engagement['work_status']}"
    )


# ---------------------------------------------------------------------------
# Capacity gates: cycle posture, partner ceiling, volunteer concurrency, hours
# ---------------------------------------------------------------------------
def test_27_a_frozen_cycle_shuts_matching_entirely(api):
    """PRD §2.12: "The cycle's `posture` is not `FROZEN` — on
    `POST /project-requests/{id}/match` and `POST /match-offers/{id}/accept` — otherwise
    `ERR_CYCLE_CAPACITY_FROZEN` (409)."
    PRD §3.1: "`posture` is `OPEN` while utilization is below 0.8000, `RESTRICTED` from 0.8000
    up to but not including 1.0000, and `FROZEN` at 1.0000 and above; both band floors are
    inclusive, so a utilization of exactly 0.8000 is `RESTRICTED` and exactly 1.0000 is
    `FROZEN`."

    Design: Corner/validations/val_frozen_cycle_blocks_second_match
    """
    w = setup_offer(cycle_slots=1)
    second = add_scoped_request(w, title="Grant compliance review")

    response = api_client.match_project_request(second["request"]["id"], w["spec_headers"])

    validate_error(response, ApiErrorId.ERR_CYCLE_CAPACITY_FROZEN, expected_status=409)
    cycle = read_cycle(w)
    assert cycle["posture"] == "FROZEN", (
        f"Expected the one-slot cycle to be FROZEN once its slot is reserved, got "
        f"{cycle['posture']}"
    )
    assert cycle["utilization_ratio"] == pytest.approx(1.0000, abs=0.0001), (
        f"Expected utilization_ratio 1.0000, got {cycle['utilization_ratio']}"
    )
    assert cycle["slots_reserved"] == 1, (
        f"Expected slots_reserved to stay 1, got {cycle['slots_reserved']}"
    )
    assert cycle["slots_available"] == 0, (
        f"Expected slots_available 0, got {cycle['slots_available']}"
    )
    _, meta = validate_paginated(
        api_client.list_match_offers(
            w["pm_headers"], params={"project_request_id": second["request"]["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"Expected no offer against the second request, got {meta['total_count']}"
    )
    blocked = read_request(w, second["request"]["id"])
    assert blocked["status"] == "SCOPED", (
        f"Expected the second request to stay SCOPED, got {blocked['status']}"
    )
    assert blocked["failed_match_rounds"] == 0, (
        f"Expected failed_match_rounds to stay 0 for a gate refusal, got "
        f"{blocked['failed_match_rounds']}"
    )


def test_28_a_restricted_cycle_turns_away_a_routine_request(api):
    """PRD §2.12: "When the cycle's `posture` is `RESTRICTED`, the request's `urgency` is
    `ELEVATED` or `CRITICAL` — on `POST /project-requests/{id}/match` — otherwise
    `ERR_CYCLE_RESTRICTED_URGENCY` (409)."
    PRD §3.1: "`RESTRICTED` narrows the gate rather than shutting it: only requests of
    `ELEVATED` or `CRITICAL` urgency may take a slot, while a `ROUTINE` request attempting to
    match is refused with `ERR_CYCLE_RESTRICTED_URGENCY`."

    Design: Corner/validations/val_restricted_cycle_blocks_routine_urgency_match
    """
    w = setup_offer(cycle_slots=5, window_hours=200.00)
    for title in ("Grant compliance review", "Payroll audit", "Endowment policy"):
        filler = add_scoped_request(w, title=title)
        validate_success(
            api_client.match_project_request(filler["request"]["id"], w["spec_headers"]), 201
        )
    routine = add_scoped_request(w, title="Board training", urgency="ROUTINE")

    response = api_client.match_project_request(routine["request"]["id"], w["spec_headers"])

    validate_error(response, ApiErrorId.ERR_CYCLE_RESTRICTED_URGENCY, expected_status=409)
    cycle = read_cycle(w)
    assert cycle["utilization_ratio"] == pytest.approx(0.8000, abs=0.0001), (
        f"Expected utilization_ratio 0.8000 with four of five slots reserved, got "
        f"{cycle['utilization_ratio']}"
    )
    assert cycle["posture"] == "RESTRICTED", (
        f"Expected posture RESTRICTED at exactly 0.8000, got {cycle['posture']}"
    )
    assert cycle["slots_reserved"] == 4, (
        f"Expected slots_reserved 4, got {cycle['slots_reserved']}"
    )
    assert cycle["slots_available"] == 1, (
        f"Expected slots_available 1, got {cycle['slots_available']}"
    )
    blocked = read_request(w, routine["request"]["id"])
    assert blocked["status"] == "SCOPED", (
        f"Expected the ROUTINE request to stay SCOPED, got {blocked['status']}"
    )
    assert blocked["failed_match_rounds"] == 0, (
        f"Expected failed_match_rounds to stay 0 for a gate refusal, got "
        f"{blocked['failed_match_rounds']}"
    )
    window = read_window(w)
    assert window["hours_committed"] == pytest.approx(160.00, abs=0.01), (
        f"Expected the window to hold 160.00 hours across four offers, got "
        f"{window['hours_committed']}"
    )


def test_29_a_micro_partner_cannot_take_a_second_concurrent_engagement(api):
    """PRD §3.4: "the partner's `open_engagement_count` must be strictly below its
    `max_concurrent_engagements` — a partner already at its ceiling is refused with
    `ERR_PARTNER_ENGAGEMENT_LIMIT`."
    PRD §3.1: "The class implies the partner's `max_concurrent_engagements` ceiling directly:
    one for `MICRO`, two for `SMALL`, four for `MID` and six for `LARGE`."

    Design: Corner/validations/val_micro_partner_second_concurrent_match_rejected
    """
    w = setup_engagement(partner_budget=MICRO_BUDGET, cycle_slots=4)
    second = add_scoped_request(w, title="Grant compliance review")

    response = api_client.match_project_request(second["request"]["id"], w["spec_headers"])

    validate_error(response, ApiErrorId.ERR_PARTNER_ENGAGEMENT_LIMIT, expected_status=409)
    partner = read_partner(w)
    assert partner["capacity_class"] == "MICRO", (
        f"Expected a 90000.00 budget to read MICRO, got {partner['capacity_class']}"
    )
    assert partner["max_concurrent_engagements"] == 1, (
        f"Expected a MICRO ceiling of 1, got {partner['max_concurrent_engagements']}"
    )
    assert partner["open_engagement_count"] == 1, (
        f"Expected open_engagement_count to sit at its ceiling of 1, got "
        f"{partner['open_engagement_count']}"
    )
    cycle = read_cycle(w)
    assert cycle["slots_committed"] == 1, (
        f"Expected slots_committed 1, got {cycle['slots_committed']}"
    )
    assert cycle["slots_reserved"] == 0, (
        f"Expected no slot to have been reserved by the refused match, got "
        f"{cycle['slots_reserved']}"
    )
    blocked = read_request(w, second["request"]["id"])
    assert blocked["status"] == "SCOPED", (
        f"Expected the second request to stay SCOPED, got {blocked['status']}"
    )


def test_30_a_volunteer_cannot_accept_a_third_concurrent_engagement(api):
    """PRD §2.12: "The volunteer's `open_engagement_count` is below 2 — on
    `POST /match-offers/{id}/accept` — otherwise `ERR_VOLUNTEER_CONCURRENCY_LIMIT` (409)."

    Design: Corner/validations/val_third_concurrent_accept_by_same_volunteer_rejected
    """
    w = setup_offer(cycle_slots=4)
    offers = [w["offer"]]
    for title in ("Grant compliance review", "Payroll audit"):
        extra = add_scoped_request(w, title=title)
        offers.append(
            validate_success(
                api_client.match_project_request(extra["request"]["id"], w["spec_headers"]),
                201,
            )
        )
    for offer in offers[:2]:
        validate_success(
            api_client.accept_match_offer(offer["id"], w["volunteer_headers"]), 201
        )

    response = api_client.accept_match_offer(offers[2]["id"], w["volunteer_headers"])

    validate_error(
        response, ApiErrorId.ERR_VOLUNTEER_CONCURRENCY_LIMIT, expected_status=409
    )
    volunteer = read_volunteer(w)
    assert volunteer["open_engagement_count"] == 2, (
        f"Expected open_engagement_count to stay at the ceiling of 2, got "
        f"{volunteer['open_engagement_count']}"
    )
    third = read_offer(w, offers[2]["id"])
    assert third["status"] == "OFFERED", (
        f"Expected the third offer to stay OFFERED, got {third['status']}"
    )
    assert third["responded_at"] is None, (
        f"Expected responded_at on the refused offer to stay null, got "
        f"{third['responded_at']}"
    )
    cycle = read_cycle(w)
    assert cycle["slots_committed"] == 2, (
        f"Expected slots_committed 2, got {cycle['slots_committed']}"
    )
    assert cycle["slots_reserved"] == 1, (
        f"Expected the third offer to keep holding its reserved slot, got "
        f"{cycle['slots_reserved']}"
    )


def test_31_a_match_needing_more_hours_than_the_window_holds_is_refused(api):
    """PRD §2.12: "The pinned availability window's `hours_remaining` is greater than or equal to
    the hours being held or logged — `reserved_hours` at match time, `additional_hours` at
    scope-change approval, and a log's `hours` measured against `hours_offered` less the hours
    already approved on that window — on `POST /project-requests/{id}/match`,
    `POST /engagements/{id}/time-logs` and `POST /scope-change-requests/{id}/decide`, otherwise
    `ERR_AVAILABILITY_HOURS_EXCEEDED` (422)."
    PRD §3.4: "A window whose `hours_remaining` cannot cover the reservation is refused with
    `ERR_AVAILABILITY_HOURS_EXCEEDED`."

    Design: Corner/validations/val_match_reserving_more_hours_than_window_remaining_rejected
    """
    w = setup_scoped_request(
        window_hours=30.00, estimated_hours=40.00, complexity_factor=1.00
    )

    response = api_client.match_project_request(w["request"]["id"], w["spec_headers"])

    validate_error(
        response, ApiErrorId.ERR_AVAILABILITY_HOURS_EXCEEDED, expected_status=422
    )
    window = read_window(w)
    assert window["hours_committed"] == pytest.approx(0.00, abs=0.01), (
        f"Expected the window to hold no committed hours, got {window['hours_committed']}"
    )
    assert window["hours_remaining"] == pytest.approx(30.00, abs=0.01), (
        f"Expected hours_remaining to stay 30.00, got {window['hours_remaining']}"
    )
    request = read_request(w)
    assert request["status"] == "SCOPED", (
        f"Expected the request to stay SCOPED, got {request['status']}"
    )
    cycle = read_cycle(w)
    assert cycle["slots_reserved"] == 0, (
        f"Expected no slot to have been reserved, got {cycle['slots_reserved']}"
    )
    assert cycle["posture"] == "OPEN", (
        f"Expected the cycle to stay OPEN, got {cycle['posture']}"
    )


def test_32_an_unresolved_change_request_blocks_submission(api):
    """PRD §2.12: "The engagement's `creep_escalation_level` is not `BREACH` and no child scope
    change request sits in `PENDING` or `ESCALATED` — on `POST /engagements/{id}/time-logs` and
    `POST /engagements/{id}/submit` — otherwise `ERR_SCOPE_BREACH_THRESHOLD` (409)."
    PRD §3.7: "A `MANAGER_REVIEW` change is stored in `PENDING` with a null
    `decided_by_user_id` and a null `decided_at`, and its pending hours immediately raise the
    engagement's `scope_creep_pct` even though no work has been done against them."

    Design: Corner/validations/val_pending_scope_change_blocks_submit
    """
    w = setup_held_milestone_engagement()
    change = validate_success(
        api_client.create_scope_change_request(
            w["engagement"]["id"],
            scope_change_request_payload(additional_hours=8.00, additional_deliverable_count=0),
            w["volunteer_headers"],
        ),
        201,
    )
    assert change["decision_tier"] == "MANAGER_REVIEW", (
        f"Expected a 0.2000 projection with no extra deliverable to be MANAGER_REVIEW, got "
        f"{change['decision_tier']}"
    )
    assert change["status"] == "PENDING", (
        f"Expected the change to sit in PENDING, got {change['status']}"
    )
    assert change["projected_creep_pct"] == pytest.approx(0.2000, abs=0.0001), (
        f"Expected projected_creep_pct 0.2000, got {change['projected_creep_pct']}"
    )

    response = api_client.submit_engagement(w["engagement"]["id"], w["volunteer_headers"])

    validate_error(response, ApiErrorId.ERR_SCOPE_BREACH_THRESHOLD, expected_status=409)
    engagement = read_engagement(w)
    assert engagement["work_status"] == "IN_PROGRESS", (
        f"Expected the engagement to stay IN_PROGRESS, got {engagement['work_status']}"
    )
    assert engagement["approved_hours"] == pytest.approx(40.00, abs=0.01), (
        f"Expected approved_hours to stay 40.00, got {engagement['approved_hours']}"
    )
    assert engagement["scope_creep_pct"] == pytest.approx(0.2000, abs=0.0001), (
        f"Expected the pending eight hours to raise scope_creep_pct to 0.2000, got "
        f"{engagement['scope_creep_pct']}"
    )
    assert engagement["creep_escalation_level"] == "WATCH", (
        f"Expected creep_escalation_level WATCH at 0.2000, got "
        f"{engagement['creep_escalation_level']}"
    )


# ---------------------------------------------------------------------------
# The three named collisions
# ---------------------------------------------------------------------------
def test_33_a_log_against_a_submitted_engagement_answers_the_work_state_first(api):
    """PRD §2.12: "A 30.00-hour time log posted to an engagement already in `SUBMITTED` fails
    both the work-state check at position 23 and the window-hours check at position 55; the
    response must be `ERR_INVALID_WORK_STATE`."

    Design: Corner/validations/conflict_work_state_beats_availability_hours_on_time_log
    """
    w = setup_submitted_engagement(window_hours=40.00)

    response = api_client.create_time_log(
        w["engagement"]["id"],
        time_log_payload(work_date=WORK_DATE, hours=10.00),
        w["volunteer_headers"],
    )

    validate_error(response, ApiErrorId.ERR_INVALID_WORK_STATE, expected_status=409)
    rows, meta = validate_paginated(
        api_client.list_time_logs(w["engagement"]["id"], w["pm_headers"])
    )
    assert meta["total_count"] == 4, (
        f"Expected the four logged lines to stand alone, got {meta['total_count']}"
    )
    assert all(row["approved"] for row in rows), (
        "Expected every line approved by the held check-in to remain approved"
    )
    engagement = read_engagement(w)
    assert engagement["work_status"] == "SUBMITTED", (
        f"Expected the engagement to stay SUBMITTED, got {engagement['work_status']}"
    )
    assert engagement["approved_hours"] == pytest.approx(40.00, abs=0.01), (
        f"Expected approved_hours to stay 40.00, got {engagement['approved_hours']}"
    )
    window = read_window(w)
    assert window["hours_remaining"] == pytest.approx(0.00, abs=0.01), (
        f"Expected the window to be fully committed at 0.00 remaining, got "
        f"{window['hours_remaining']}"
    )


def test_34_a_handoff_answers_the_missing_attestation_before_the_pinned_revision(api):
    """PRD §2.12: "A handoff posted with `confidentiality_attested` false against an engagement
    whose pinned revision has moved to `SUPERSEDED` fails both the attestation check at position
    34 and the pinned-revision check at position 49; the response must be
    `ERR_CONFIDENTIALITY_ATTESTATION_MISSING`."

    Design: Corner/validations/conflict_confidentiality_attestation_beats_pinned_revision_check
    """
    w = setup_accepted_engagement()

    response = api_client.handoff_engagement(
        w["engagement"]["id"],
        handoff_payload(confidentiality_attested=False, handoff_artifact_count=4),
        w["pm_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_CONFIDENTIALITY_ATTESTATION_MISSING, expected_status=422
    )
    scope = read_scope(w)
    assert scope["status"] == "APPROVED", (
        f"Expected the pinned revision to still be APPROVED, got {scope['status']}"
    )
    engagement = read_engagement(w)
    assert engagement["confidentiality_attested"] is False, (
        f"Expected confidentiality_attested to stay false, got "
        f"{engagement['confidentiality_attested']}"
    )
    assert engagement["handoff_artifact_count"] == 0, (
        f"Expected handoff_artifact_count to stay 0, got "
        f"{engagement['handoff_artifact_count']}"
    )
    assert engagement["handoff_at"] is None, (
        f"Expected handoff_at to stay null, got {engagement['handoff_at']}"
    )
    assert engagement["work_status"] == "ACCEPTED", (
        f"Expected the engagement to stay ACCEPTED, got {engagement['work_status']}"
    )


def test_35_a_window_that_escapes_every_cycle_and_overlaps_answers_containment(api):
    """PRD §2.12: "And an availability window that both extends past every cycle's `ends_at` and
    overlaps an existing window of the same volunteer fails both the containment check at
    position 39 and the overlap check at position 43; the response must be
    `ERR_WINDOW_OUTSIDE_CYCLE`."

    Design: Corner/validations/conflict_window_outside_cycle_beats_window_overlap
    """
    pm = make_program_manager_headers()
    create_cycle(pm, starts_at=CYCLE_START, ends_at=CYCLE_END)
    volunteer, _, existing = create_vetted_volunteer(
        window_overrides={
            "starts_at": WINDOW_START,
            "ends_at": WINDOW_END,
            "window_kind": "HARD",
            "hours_offered": 200.00,
        }
    )

    response = api_client.create_availability_window(
        volunteer["id"],
        availability_window_payload(
            starts_at="2026-10-01T00:00:00Z",
            ends_at="2027-01-01T00:00:00Z",
            hours_offered=100.00,
        ),
        make_volunteer_headers(volunteer["id"]),
    )

    validate_error(response, ApiErrorId.ERR_WINDOW_OUTSIDE_CYCLE, expected_status=422)
    rows, meta = validate_paginated(api_client.list_availability_windows(volunteer["id"], pm))
    assert meta["total_count"] == 1, (
        f"Expected the volunteer to keep exactly one window, got {meta['total_count']}"
    )
    assert rows[0]["id"] == existing["id"], (
        "Expected the surviving window to be the one published before the refusal"
    )
    assert rows[0]["hours_offered"] == pytest.approx(200.00, abs=0.01), (
        f"Expected the surviving window's 200.00 offered hours to be untouched, got "
        f"{rows[0]['hours_offered']}"
    )
    assert rows[0]["ends_at"].startswith("2026-11-01T00:00:00"), (
        f"Expected the surviving window to still end at 2026-11-01T00:00:00Z, got "
        f"{rows[0]['ends_at']}"
    )
