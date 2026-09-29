"""The access-control matrix: which role may drive which operation, which entity-backed caller
owns which resource, and where the segregation-of-duties barrier sits on top of both."""
import pytest

from test_helpers import (
    ApiErrorId,
    PM_USER_ID,
    QR_USER_ID,
    SPEC_USER_ID,
    add_second_volunteer,
    agreement_payload,
    api_client,
    availability_window_payload,
    counter_payload,
    create_cycle,
    create_partner,
    create_skill_profile,
    create_vetted_volunteer,
    create_volunteer,
    current_engagement_version,
    deliverable_payload,
    deliverable_scores_payload,
    drive_review_to_outcome,
    make_partner_contact_headers,
    make_program_manager_headers,
    make_quality_reviewer_headers,
    make_scoping_specialist_headers,
    make_volunteer_headers,
    partner_org_payload,
    program_cycle_payload,
    project_request_payload,
    read_agreement,
    read_cycle,
    read_deliverables,
    read_engagement,
    read_offer,
    read_request,
    read_scope,
    read_window,
    scope_definition_payload,
    setup_draft_request,
    setup_engagement,
    setup_executed_agreement,
    setup_in_progress_engagement,
    setup_offer,
    setup_scoped_request,
    setup_scoping_request,
    setup_sent_agreement,
    setup_submitted_engagement,
    skill_profile_payload,
    time_log_payload,
    valuation_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

MID_BUDGET = 3000000.00
SECOND_PARTNER_BUDGET = 400000.00


def _headers_without_role(user_id: str) -> dict:
    """Auth headers carrying X-User-ID but no X-User-Role at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def _review_row(world: dict, review_id: str) -> dict:
    """Re-read one review round from the engagement's review list."""
    rows, _meta = validate_paginated(
        api_client.list_quality_reviews(world["engagement"]["id"], world["pm_headers"])
    )
    for row in rows:
        if row["id"] == review_id:
            return row
    raise AssertionError(f"Review {review_id} is missing from the engagement's rounds")


def _scoping_request_without_revision() -> dict:
    """A request moved DRAFT -> SCOPING against which no revision has been drafted."""
    world = setup_draft_request()
    world["request"] = validate_success(
        api_client.submit_for_scoping(world["request"]["id"], world["partner_headers"])
    )
    return world


def _draft_revision_without_deliverables() -> dict:
    """A SCOPING request carrying one DRAFT revision that has no deliverable yet."""
    world = _scoping_request_without_revision()
    world["scope"] = validate_success(
        api_client.create_scope_definition(
            world["request"]["id"],
            scope_definition_payload(world["request"]["version"]),
            world["spec_headers"],
        ),
        201,
    )
    return world


# ---------------------------------------------------------------------------
# The header gate runs before the role gate
# ---------------------------------------------------------------------------
def test_01_omitting_the_role_header_answers_missing_auth_headers_not_a_role_denial(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the caller, and
    `X-User-Role`, naming the caller's role. If either header is absent or blank, the request is
    rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401) — this check runs before any other, on
    every endpoint including reads."
    PRD §3.2: "Enrolment lands the volunteer in `status` `PENDING_VETTING` with
    `credential_verified_at` null, both `reliability_score` and `reliability_score_lifetime`
    seeded at the 0.7500 baseline, `lifetime_valued_usd` at 0.00, and
    `terminal_engagement_count` and `open_engagement_count` at 0."

    Design: Corner/rbac/rbac_missing_role_header_rejected_before_role_lookup
    """
    pm = make_program_manager_headers()
    volunteer = create_volunteer(pm)
    create_skill_profile(volunteer["id"], skill_code="TAX_LAW")

    response = api_client.vet_volunteer(
        volunteer["id"], {"verify_skill_codes": ["TAX_LAW"]},
        _headers_without_role(PM_USER_ID),
    )

    validate_error(
        response, ApiErrorId.ERR_MISSING_AUTH_HEADERS, expected_status=401
    )
    body = response.json()
    assert body["response_type"] == "error", (
        f"Expected response_type error on the envelope, got {body['response_type']}"
    )
    assert str(body["meta"]["api_request_id"]).startswith("req_"), (
        f"Expected an api_request_id starting with req_, got "
        f"{body['meta']['api_request_id']}"
    )

    after = validate_success(api_client.get_volunteer(volunteer["id"], pm))
    assert after["status"] == "PENDING_VETTING", (
        f"Expected the refused vetting to leave status PENDING_VETTING, got "
        f"{after['status']}"
    )
    assert after["credential_verified_at"] is None, (
        f"Expected credential_verified_at to stay null, got "
        f"{after['credential_verified_at']}"
    )


# ---------------------------------------------------------------------------
# Program-office operations refused to every other role
# ---------------------------------------------------------------------------
def test_02_a_volunteer_cannot_register_a_partner_org(api):
    """PRD §2.1: "A role value outside that set, or a role that is not listed among the target
    endpoint's authorized roles in §4, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "| POST | `/partner-orgs` | Register a nonprofit partner. Capacity class and the
    concurrent-engagement ceiling are derived immediately. | ProgramManager |"

    Design: Corner/rbac/rbac_volunteer_cannot_register_partner_org
    """
    pm = make_program_manager_headers()
    partner = create_partner(pm, annual_budget_usd=MID_BUDGET)
    volunteer = create_volunteer(pm)

    response = api_client.create_partner_org(
        partner_org_payload(
            name="Volunteer Side Project", sector="CIVIC", annual_budget_usd=100000.00
        ),
        make_volunteer_headers(volunteer["id"]),
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)
    still_there = validate_success(api_client.get_partner_org(partner["id"], pm))
    assert still_there["name"] != "Volunteer Side Project", (
        "The refused registration must not have overwritten the existing partner"
    )


def test_03_a_partner_contact_cannot_open_a_program_cycle(api):
    """PRD §2.1: "A role value outside that set, or a role that is not listed among the target
    endpoint's authorized roles in §4, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "| POST | `/program-cycles` | Open a program cycle with a fixed slot capacity.
    Posture starts open with zero committed and zero reserved slots. | ProgramManager |"

    Design: Corner/rbac/rbac_partner_contact_cannot_open_program_cycle
    """
    pm = make_program_manager_headers()
    partner = create_partner(pm, annual_budget_usd=MID_BUDGET)

    response = api_client.create_program_cycle(
        program_cycle_payload(capacity_slot_total=4),
        make_partner_contact_headers(partner["id"]),
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)


def test_04_a_partner_contact_cannot_enrol_a_volunteer(api):
    """PRD §2.1: "A role value outside that set, or a role that is not listed among the target
    endpoint's authorized roles in §4, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "| POST | `/volunteers` | Enrol a volunteer pending vetting. Reliability fields
    start at the 0.7500 baseline. | ProgramManager |"

    Design: Corner/rbac/rbac_partner_contact_cannot_enrol_volunteer
    """
    pm = make_program_manager_headers()
    partner = create_partner(pm, annual_budget_usd=MID_BUDGET)

    response = api_client.create_volunteer(
        {
            "full_name": "Preferred Expert",
            "email": "pref@vol.example",
            "professional_rate_usd_per_hour": 400.00,
            "seniority": "PRINCIPAL",
            "weekly_hours_cap": 30,
        },
        make_partner_contact_headers(partner["id"]),
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)


def test_05_a_volunteer_cannot_suspend_a_partner_org(api):
    """PRD §2.1: "A role value outside that set, or a role that is not listed among the target
    endpoint's authorized roles in §4, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "| PATCH | `/partner-orgs/{id}/status` | Move a partner between active, probation
    and suspended standing. Suspension runs the full abandon and terminate cascade. |
    ProgramManager |"
    PRD §3.1: "A newly registered partner starts with `status` `ACTIVE`, a null
    `probation_reason`, a null `suspended_at`, a null `satisfaction_index`, a
    `satisfaction_sample_size` of 0 and an `open_engagement_count` of 0."

    Design: Corner/rbac/rbac_volunteer_cannot_suspend_partner_org
    """
    pm = make_program_manager_headers()
    partner = create_partner(pm, annual_budget_usd=MID_BUDGET)
    volunteer = create_volunteer(pm)

    response = api_client.patch_partner_org_status(
        partner["id"],
        {"to_status": "SUSPENDED"},
        make_volunteer_headers(volunteer["id"]),
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)
    after = validate_success(api_client.get_partner_org(partner["id"], pm))
    assert after["status"] == "ACTIVE", (
        f"Expected the partner to stay ACTIVE after the refusal, got {after['status']}"
    )
    assert after["probation_reason"] is None, (
        f"Expected probation_reason to stay null, got {after['probation_reason']}"
    )
    assert after["suspended_at"] is None, (
        f"Expected suspended_at to stay null, got {after['suspended_at']}"
    )


def test_06_a_scoping_specialist_cannot_run_the_cycle_checkpoint(api):
    """PRD §2.1: "A role value outside that set, or a role that is not listed among the target
    endpoint's authorized roles in §4, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "| POST | `/program-cycles/{id}/recalculate` | Ops-run checkpoint for one cycle:
    sweeps expired offers, marks overdue check-ins missed, then recomputes capacity and posture.
    Advances the recalculation epoch by one. | ProgramManager |"
    PRD §3.1: "Finally it recomputes the capacity figures and `posture`, stamps
    `last_recalculated_at` from the clock, and advances `recalc_epoch` by exactly one — the epoch
    counter starts at 0 and exists so operators can tell one checkpoint's output from the next."

    Design: Corner/rbac/rbac_scoping_specialist_cannot_run_cycle_recalculate
    """
    pm = make_program_manager_headers()
    spec = make_scoping_specialist_headers()
    cycle = create_cycle(pm, capacity_slot_total=4)

    response = api_client.recalculate_program_cycle(cycle["id"], spec)

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)
    readable = validate_success(api_client.get_program_cycle(cycle["id"], spec))
    assert readable["recalc_epoch"] == 0, (
        f"Expected recalc_epoch to stay at its starting 0, got {readable['recalc_epoch']}"
    )


def test_07_a_quality_reviewer_cannot_advance_the_logical_clock(api):
    """PRD §2.1: "A role value outside that set, or a role that is not listed among the target
    endpoint's authorized roles in §4, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "| POST | `/_clock/set_current_utc` | Set the server's logical clock, which every
    expiry, window, buffer and deadline rule reads. The clock may only move forward and performs
    no sweep of its own. | ProgramManager |"
    PRD §2.5: "The clock only moves forward: an instant strictly earlier than the current clock
    reading is rejected with `ERR_CLOCK_REGRESSION` (HTTP 422), while an instant exactly equal to
    the current reading is accepted and leaves the clock where it is."

    Design: Corner/rbac/rbac_quality_reviewer_cannot_advance_the_logical_clock
    """
    response = api_client.set_clock(
        {"to_iso8601": "2026-09-01T00:00:00Z"}, make_quality_reviewer_headers()
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)

    # If the refused jump had landed, this earlier instant would regress the clock.
    validate_success(
        api_client.set_clock(
            {"to_iso8601": "2026-08-01T12:00:00Z"}, make_program_manager_headers()
        )
    )


def test_08_a_scoping_specialist_cannot_vet_volunteer_credentials(api):
    """PRD §2.1: "A role value outside that set, or a role that is not listed among the target
    endpoint's authorized roles in §4, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "| POST | `/volunteers/{id}/vet` | Complete vetting: stamps credential verification,
    activates the volunteer and marks the named skill claims verified. | ProgramManager |"
    PRD §3.2: "Vetting is a single `ProgramManager` action that stamps `credential_verified_at`
    from the logical clock, flips `status` from `PENDING_VETTING` to `ACTIVE`, and optionally
    accepts a `verify_skill_codes` list; each skill claim whose `skill_code` appears on that list
    has its `verified` flag set to true and its `verified_at` stamped, which is what later earns
    that claim a bonus in the matching score."

    Design: Corner/rbac/rbac_scoping_specialist_cannot_vet_volunteer_credentials
    """
    pm = make_program_manager_headers()
    volunteer = create_volunteer(pm)
    create_skill_profile(volunteer["id"], skill_code="TAX_LAW")

    response = api_client.vet_volunteer(
        volunteer["id"],
        {"verify_skill_codes": ["TAX_LAW"]},
        make_scoping_specialist_headers(),
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)
    after = validate_success(api_client.get_volunteer(volunteer["id"], pm))
    assert after["status"] == "PENDING_VETTING", (
        f"Expected status to stay PENDING_VETTING, got {after['status']}"
    )
    assert after["credential_verified_at"] is None, (
        f"Expected credential_verified_at to stay null, got "
        f"{after['credential_verified_at']}"
    )
    claims, _meta = validate_paginated(
        api_client.list_skill_profiles(volunteer["id"], pm)
    )
    assert len(claims) == 1, f"Expected the one declared claim, got {len(claims)}"
    assert claims[0]["verified"] is False, (
        f"Expected the TAX_LAW claim to stay unverified, got {claims[0]['verified']}"
    )


def test_09_a_scoping_specialist_cannot_move_a_volunteer_between_standings(api):
    """PRD §2.1: "A role value outside that set, or a role that is not listed among the target
    endpoint's authorized roles in §4, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "| PATCH | `/volunteers/{id}/status` | Pause, resume or deactivate a volunteer.
    Pausing withdraws every open offer held by that volunteer. | ProgramManager |"
    PRD §3.2: "Enrolment lands the volunteer in `status` `PENDING_VETTING` with
    `credential_verified_at` null, both `reliability_score` and `reliability_score_lifetime`
    seeded at the 0.7500 baseline, `lifetime_valued_usd` at 0.00, and
    `terminal_engagement_count` and `open_engagement_count` at 0."

    Design: Corner/rbac/rbac_scoping_specialist_cannot_change_volunteer_status
    """
    pm = make_program_manager_headers()
    create_cycle(pm, capacity_slot_total=4)
    create_partner(pm, annual_budget_usd=MID_BUDGET)
    volunteer = create_volunteer(pm)

    response = api_client.patch_volunteer_status(
        volunteer["id"], {"to_status": "ACTIVE"}, make_scoping_specialist_headers()
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)
    after = validate_success(api_client.get_volunteer(volunteer["id"], pm))
    assert after["status"] == "PENDING_VETTING", (
        f"Expected the volunteer to stay PENDING_VETTING, got {after['status']}"
    )
    assert after["credential_verified_at"] is None, (
        f"Expected credential_verified_at to stay null, got "
        f"{after['credential_verified_at']}"
    )


def test_10_a_scoping_specialist_cannot_abandon_a_request(api):
    """PRD §2.1: "A role value outside that set, or a role that is not listed among the target
    endpoint's authorized roles in §4, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "| POST | `/project-requests/{id}/abandon` | Close a request without delivery,
    releasing every hold it owns. | ProgramManager |"
    PRD §3.3: "In every case the request moves to `ABANDONED` and `closed_at` is stamped from the
    logical clock."

    Design: Corner/rbac/rbac_scoping_specialist_cannot_abandon_request
    """
    world = _scoping_request_without_revision()

    response = api_client.abandon_project_request(
        world["request"]["id"], world["spec_headers"]
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)
    after = validate_success(
        api_client.get_project_request(world["request"]["id"], world["pm_headers"])
    )
    assert after["status"] == "SCOPING", (
        f"Expected the request to stay SCOPING after the refusal, got {after['status']}"
    )
    assert after["closed_at"] is None, (
        f"Expected closed_at to stay null, got {after['closed_at']}"
    )


def test_11_a_volunteer_cannot_issue_the_engagement_agreement(api):
    """PRD §2.1: "A role value outside that set, or a role that is not listed among the target
    endpoint's authorized roles in §4, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "| POST | `/engagements/{id}/agreements` | Issue the engagement agreement carrying
    the intellectual-property and confidentiality terms, voiding any prior non-executed
    agreement. Guarded against stale engagement versions. | ProgramManager |"

    Design: Corner/rbac/rbac_volunteer_cannot_issue_engagement_agreement
    """
    world = setup_engagement()

    response = api_client.create_agreement(
        world["engagement"]["id"],
        agreement_payload(world["engagement"]["version"]),
        world["volunteer_headers"],
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)
    rows, meta = validate_paginated(
        api_client.list_agreements(world["engagement"]["id"], world["pm_headers"])
    )
    assert meta["total_count"] == 0, (
        f"Expected no agreement to exist after the refusal, got {meta['total_count']}"
    )
    assert rows == [], f"Expected an empty agreement list, got {rows}"


def test_12_a_scoping_specialist_cannot_terminate_a_live_engagement(api):
    """PRD §2.1: "A role value outside that set, or a role that is not listed among the target
    endpoint's authorized roles in §4, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "| POST | `/engagements/{id}/terminate` | Terminate a live engagement, releasing the
    slot and hours and restating any posted valuation. | ProgramManager |"
    PRD §2.3: "`slots_committed` counts the engagements attributed to the cycle whose
    `work_status` is `NOT_STARTED`, `IN_PROGRESS`, `SUBMITTED` or `ACCEPTED`"

    Design: Corner/rbac/rbac_scoping_specialist_cannot_terminate_engagement
    """
    world = setup_in_progress_engagement(cycle_slots=4, window_hours=200.00)

    response = api_client.terminate_engagement(
        world["engagement"]["id"], world["spec_headers"]
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)
    engagement = read_engagement(world)
    assert engagement["work_status"] == "IN_PROGRESS", (
        f"Expected the engagement to stay IN_PROGRESS, got {engagement['work_status']}"
    )
    assert engagement["terminated_at"] is None, (
        f"Expected terminated_at to stay null, got {engagement['terminated_at']}"
    )
    assert engagement["termination_reason"] is None, (
        f"Expected termination_reason to stay null, got "
        f"{engagement['termination_reason']}"
    )

    cycle = read_cycle(world)
    assert cycle["slots_committed"] == 1, (
        f"Expected the slot to stay committed, got {cycle['slots_committed']}"
    )
    assert cycle["slots_available"] == 3, (
        f"Expected 3 of 4 slots to stay available, got {cycle['slots_available']}"
    )

    window = read_window(world)
    assert window["hours_committed"] == pytest.approx(40.00, abs=0.01), (
        f"Expected the 40.00 committed hours to stay held, got "
        f"{window['hours_committed']}"
    )
    assert window["hours_remaining"] == pytest.approx(160.00, abs=0.01), (
        f"Expected 160.00 hours to stay remaining of the 200.00 offered, got "
        f"{window['hours_remaining']}"
    )


def test_13_a_quality_reviewer_cannot_post_a_valuation_record(api):
    """PRD §2.1: "A role value outside that set, or a role that is not listed among the target
    endpoint's authorized roles in §4, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "| POST | `/engagements/{id}/valuations` | Post a valuation record for one method,
    superseding the prior record of that method. Guarded against stale engagement versions. |
    ProgramManager |"
    PRD §3.5: "the new engagement is written with `work_status` `NOT_STARTED` and
    `valuation_status` `UNVALUED`"

    Design: Corner/rbac/rbac_quality_reviewer_cannot_post_valuation
    """
    world = setup_in_progress_engagement()
    version = current_engagement_version(world)

    response = api_client.create_valuation(
        world["engagement"]["id"],
        valuation_payload(version, method="INDEPENDENT_SECTOR"),
        world["reviewer_headers"],
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)
    engagement = read_engagement(world)
    assert engagement["valuation_status"] == "UNVALUED", (
        f"Expected valuation_status to stay UNVALUED, got "
        f"{engagement['valuation_status']}"
    )
    _rows, meta = validate_paginated(
        api_client.list_valuation_records(world["engagement"]["id"], world["pm_headers"])
    )
    assert meta["total_count"] == 0, (
        f"Expected no valuation record to exist, got {meta['total_count']}"
    )


# ---------------------------------------------------------------------------
# First-person volunteer operations refused to the program office and reviewers
# ---------------------------------------------------------------------------
def test_14_a_partner_contact_cannot_declare_a_skill_on_a_volunteer(api):
    """PRD §2.1: "A role value outside that set, or a role that is not listed among the target
    endpoint's authorized roles in §4, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "| POST | `/volunteers/{id}/skill-profiles` | Volunteer declares a skill at a
    proficiency level. Unique per volunteer and skill code. | Volunteer |"

    Design: Corner/rbac/rbac_partner_contact_cannot_declare_volunteer_skill
    """
    pm = make_program_manager_headers()
    partner = create_partner(pm, annual_budget_usd=MID_BUDGET)
    volunteer = create_volunteer(pm)

    response = api_client.create_skill_profile(
        volunteer["id"],
        skill_profile_payload(skill_code="TAX_LAW", proficiency=5),
        make_partner_contact_headers(partner["id"]),
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)
    _rows, meta = validate_paginated(
        api_client.list_skill_profiles(volunteer["id"], pm)
    )
    assert meta["total_count"] == 0, (
        f"Expected the volunteer to carry no skill claim, got {meta['total_count']}"
    )


def test_15_a_program_manager_cannot_publish_an_availability_window(api):
    """PRD §2.1: "A role value outside that set, or a role that is not listed among the target
    endpoint's authorized roles in §4, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "| POST | `/volunteers/{id}/availability-windows` | Volunteer publishes a half-open
    availability window with an hour budget. Windows of one volunteer may touch but never
    overlap. | Volunteer |"

    Design: Corner/rbac/rbac_program_manager_cannot_publish_availability_window
    """
    pm = make_program_manager_headers()
    create_cycle(pm, capacity_slot_total=4)
    volunteer, _skill, _window = create_vetted_volunteer(window=False)

    response = api_client.create_availability_window(
        volunteer["id"], availability_window_payload(hours_offered=200.00), pm
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)
    _rows, meta = validate_paginated(
        api_client.list_availability_windows(volunteer["id"], pm)
    )
    assert meta["total_count"] == 0, (
        f"Expected the volunteer to carry no window, got {meta['total_count']}"
    )
    after = validate_success(api_client.get_volunteer(volunteer["id"], pm))
    assert after["status"] == "ACTIVE", (
        f"Expected the vetted volunteer to stay ACTIVE, got {after['status']}"
    )


def test_16_a_program_manager_cannot_log_hours_for_the_volunteer(api):
    """PRD §2.1: "A role value outside that set, or a role that is not listed among the target
    endpoint's authorized roles in §4, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "| POST | `/engagements/{id}/time-logs` | Volunteer records hours worked. Logs stay
    unapproved until a check-in hold or submission approves them. | Volunteer |"
    PRD §3.5: "The remaining engagement fields start at their defaults: `approved_hours` 0.00,
    `scope_creep_pct` 0, `creep_escalation_level` `NONE`, `quality_gate` `PENDING`,
    `confidentiality_attested` false, `handoff_artifact_count` 0, `missed_checkin_count` 0, and
    null `handoff_at`, `terminated_at` and `termination_reason`."

    Design: Corner/rbac/rbac_program_manager_cannot_log_volunteer_hours
    """
    world = setup_in_progress_engagement()

    response = api_client.create_time_log(
        world["engagement"]["id"],
        time_log_payload(hours=6.00),
        world["pm_headers"],
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)
    _rows, meta = validate_paginated(
        api_client.list_time_logs(world["engagement"]["id"], world["pm_headers"])
    )
    assert meta["total_count"] == 0, (
        f"Expected no time log to exist after the refusal, got {meta['total_count']}"
    )
    engagement = read_engagement(world)
    assert engagement["approved_hours"] == pytest.approx(0.00, abs=0.01), (
        f"Expected approved_hours to stay 0.00, got {engagement['approved_hours']}"
    )


def test_17_a_quality_reviewer_cannot_start_the_delivery_work(api):
    """PRD §2.1: "A role value outside that set, or a role that is not listed among the target
    endpoint's authorized roles in §4, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "| POST | `/engagements/{id}/start` | Volunteer begins work. Requires an executed
    agreement. | Volunteer |"
    PRD §3.5: "the new engagement is written with `work_status` `NOT_STARTED` and
    `valuation_status` `UNVALUED`"

    Design: Corner/rbac/rbac_quality_reviewer_cannot_start_delivery
    """
    world = setup_executed_agreement()

    response = api_client.start_engagement(
        world["engagement"]["id"], world["reviewer_headers"]
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)
    engagement = read_engagement(world)
    assert engagement["work_status"] == "NOT_STARTED", (
        f"Expected the engagement to stay NOT_STARTED, got "
        f"{engagement['work_status']}"
    )


def test_18_a_program_manager_cannot_accept_an_offer_for_the_volunteer(api):
    """PRD §2.1: "A role value outside that set, or a role that is not listed among the target
    endpoint's authorized roles in §4, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "| POST | `/match-offers/{id}/accept` | Volunteer accepts an open offer, creating the
    engagement and migrating the reserved hours into a committed hold. | Volunteer |"
    PRD §2.3: "`slots_reserved` counts the match offers still in `OFFERED` status whose project
    request belongs to the cycle"

    Design: Corner/rbac/rbac_program_manager_cannot_accept_offer_on_behalf_of_volunteer
    """
    world = setup_offer(cycle_slots=4, window_hours=200.00)

    response = api_client.accept_match_offer(world["offer"]["id"], world["pm_headers"])

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)
    offer = read_offer(world)
    assert offer["status"] == "OFFERED", (
        f"Expected the offer to stay OFFERED, got {offer['status']}"
    )
    assert offer["responded_at"] is None, (
        f"Expected responded_at to stay null, got {offer['responded_at']}"
    )
    request = read_request(world)
    assert request["status"] == "MATCHING", (
        f"Expected the request to stay MATCHING, got {request['status']}"
    )
    cycle = read_cycle(world)
    assert cycle["slots_reserved"] == 1, (
        f"Expected the offer's slot to stay reserved, got {cycle['slots_reserved']}"
    )
    assert cycle["slots_committed"] == 0, (
        f"Expected no slot to be committed, got {cycle['slots_committed']}"
    )
    assert cycle["slots_available"] == 3, (
        f"Expected 3 of 4 slots available, got {cycle['slots_available']}"
    )


# ---------------------------------------------------------------------------
# Partner-side operations refused to the program office and the volunteer
# ---------------------------------------------------------------------------
def test_19_a_volunteer_cannot_file_a_project_request(api):
    """PRD §2.1: "A role value outside that set, or a role that is not listed among the target
    endpoint's authorized roles in §4, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "| POST | `/project-requests` | Partner files a pro bono project request in draft
    against a program cycle. | PartnerContact |"

    Design: Corner/rbac/rbac_volunteer_cannot_file_project_request
    """
    pm = make_program_manager_headers()
    cycle = create_cycle(pm, capacity_slot_total=4)
    partner = create_partner(pm, annual_budget_usd=MID_BUDGET)
    volunteer = create_volunteer(pm)

    response = api_client.create_project_request(
        project_request_payload(partner["id"], cycle["id"]),
        make_volunteer_headers(volunteer["id"]),
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)
    _rows, meta = validate_paginated(api_client.list_project_requests(pm))
    assert meta["total_count"] == 0, (
        f"Expected no project request to exist, got {meta['total_count']}"
    )


def test_20_a_program_manager_cannot_submit_a_request_for_scoping(api):
    """PRD §2.1: "A role value outside that set, or a role that is not listed among the target
    endpoint's authorized roles in §4, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "| POST | `/project-requests/{id}/submit-for-scoping` | Partner hands the request to
    the scoping team. | PartnerContact |"

    Design: Corner/rbac/rbac_program_manager_cannot_submit_request_for_scoping
    """
    world = setup_draft_request()

    response = api_client.submit_for_scoping(
        world["request"]["id"], world["pm_headers"]
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)
    request = read_request(world)
    assert request["status"] == "DRAFT", (
        f"Expected the request to stay DRAFT, got {request['status']}"
    )
    assert request["version"] == world["request"]["version"], (
        f"Expected the refusal to leave version at "
        f"{world['request']['version']}, got {request['version']}"
    )


def test_21_the_scope_author_cannot_approve_its_own_revision(api):
    """PRD §2.1: "A role value outside that set, or a role that is not listed among the target
    endpoint's authorized roles in §4, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "| POST | `/scope-definitions/{id}/approve` | Partner approves a scope revision,
    advancing the request to scoped and superseding any prior approved revision. |
    PartnerContact |"

    Design: Corner/rbac/rbac_scope_author_cannot_approve_own_revision
    """
    world = setup_scoping_request()

    response = api_client.approve_scope_definition(
        world["scope"]["id"], world["spec_headers"]
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)
    scope = read_scope(world)
    assert scope["status"] == "DRAFT", (
        f"Expected the revision to stay DRAFT, got {scope['status']}"
    )
    assert scope["deliverable_weight_total_pct"] == pytest.approx(100.00, abs=0.01), (
        f"Expected the complete 100.00 weight total to be untouched, got "
        f"{scope['deliverable_weight_total_pct']}"
    )
    request = read_request(world)
    assert request["status"] == "SCOPING", (
        f"Expected the request to stay SCOPING, got {request['status']}"
    )


# ---------------------------------------------------------------------------
# Scoping-desk operations refused to the partner and the program office
# ---------------------------------------------------------------------------
def test_22_a_partner_contact_cannot_author_a_scope_revision(api):
    """PRD §2.1: "A role value outside that set, or a role that is not listed among the target
    endpoint's authorized roles in §4, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "| POST | `/project-requests/{id}/scope-definitions` | Scoping specialist drafts a
    new scope revision, superseding any prior draft revision. Guarded against stale parent
    versions. | ScopingSpecialist |"
    PRD §3.4: "Any sibling revision still sitting in `DRAFT` moves to `WITHDRAWN` at once, and the
    parent request's `version` advances by one."

    Design: Corner/rbac/rbac_partner_contact_cannot_author_scope_revision
    """
    world = _scoping_request_without_revision()

    response = api_client.create_scope_definition(
        world["request"]["id"],
        scope_definition_payload(world["request"]["version"]),
        world["partner_headers"],
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)
    request = read_request(world)
    assert request["status"] == "SCOPING", (
        f"Expected the request to stay SCOPING, got {request['status']}"
    )
    assert request["version"] == world["request"]["version"], (
        f"Expected no revision to have advanced the request version past "
        f"{world['request']['version']}, got {request['version']}"
    )


def test_23_a_partner_contact_cannot_add_a_deliverable_to_the_revision(api):
    """PRD §2.1: "A role value outside that set, or a role that is not listed among the target
    endpoint's authorized roles in §4, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "| POST | `/scope-definitions/{id}/deliverables` | Add a deliverable to a draft scope
    revision. Weights must total exactly 100.00 before the revision can be approved. |
    ScopingSpecialist |"
    PRD §3.4: "its `deliverable_count` and `deliverable_weight_total_pct` both start at 0"

    Design: Corner/rbac/rbac_partner_contact_cannot_add_deliverable_to_its_scope
    """
    world = _draft_revision_without_deliverables()

    response = api_client.create_deliverable(
        world["scope"]["id"], deliverable_payload(), world["partner_headers"]
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)
    _rows, meta = validate_paginated(
        api_client.list_deliverables(world["scope"]["id"], world["pm_headers"])
    )
    assert meta["total_count"] == 0, (
        f"Expected the revision to carry no deliverable, got {meta['total_count']}"
    )
    scope = read_scope(world)
    assert scope["deliverable_count"] == 0, (
        f"Expected deliverable_count to stay 0, got {scope['deliverable_count']}"
    )
    assert scope["deliverable_weight_total_pct"] == pytest.approx(0, abs=0.01), (
        f"Expected deliverable_weight_total_pct to stay 0, got "
        f"{scope['deliverable_weight_total_pct']}"
    )


def test_24_a_partner_contact_cannot_run_the_matching_selector(api):
    """PRD §2.1: "A role value outside that set, or a role that is not listed among the target
    endpoint's authorized roles in §4, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "| POST | `/project-requests/{id}/match` | Run the matching selector and create one
    offer for the top-ranked eligible volunteer. | ScopingSpecialist |"

    Design: Corner/rbac/rbac_partner_contact_cannot_run_the_matcher
    """
    world = setup_scoped_request()

    response = api_client.match_project_request(
        world["request"]["id"], world["partner_headers"]
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)
    _rows, meta = validate_paginated(api_client.list_match_offers(world["pm_headers"]))
    assert meta["total_count"] == 0, (
        f"Expected no match offer to exist, got {meta['total_count']}"
    )
    request = read_request(world)
    assert request["status"] == "SCOPED", (
        f"Expected the request to stay SCOPED, got {request['status']}"
    )
    assert request["failed_match_rounds"] == 0, (
        f"Expected failed_match_rounds to stay 0, got "
        f"{request['failed_match_rounds']}"
    )


def test_25_a_program_manager_cannot_withdraw_a_match_offer(api):
    """PRD §2.1: "A role value outside that set, or a role that is not listed among the target
    endpoint's authorized roles in §4, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "| POST | `/match-offers/{id}/withdraw` | Scoping specialist pulls back an open
    offer. | ScopingSpecialist |"
    PRD §3.5: "`responded_at`, `decline_reason` and `withdraw_reason` all start null."

    Design: Corner/rbac/rbac_program_manager_cannot_withdraw_match_offer
    """
    world = setup_offer(cycle_slots=4, window_hours=200.00)

    response = api_client.withdraw_match_offer(
        world["offer"]["id"], world["pm_headers"]
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)
    offer = read_offer(world)
    assert offer["status"] == "OFFERED", (
        f"Expected the offer to stay OFFERED, got {offer['status']}"
    )
    assert offer["withdraw_reason"] is None, (
        f"Expected withdraw_reason to stay null, got {offer['withdraw_reason']}"
    )
    cycle = read_cycle(world)
    assert cycle["slots_reserved"] == 1, (
        f"Expected the reservation to survive, got {cycle['slots_reserved']}"
    )
    window = read_window(world)
    assert window["hours_committed"] == pytest.approx(40.00, abs=0.01), (
        f"Expected the 40.00 reserved hours to stay held, got "
        f"{window['hours_committed']}"
    )
    assert window["hours_remaining"] == pytest.approx(160.00, abs=0.01), (
        f"Expected 160.00 hours remaining of the 200.00 offered, got "
        f"{window['hours_remaining']}"
    )


# ---------------------------------------------------------------------------
# Review-desk operations refused to the program office
# ---------------------------------------------------------------------------
def test_26_a_program_manager_cannot_score_the_deliverable_set(api):
    """PRD §2.1: "A role value outside that set, or a role that is not listed among the target
    endpoint's authorized roles in §4, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "| POST | `/quality-reviews/{id}/score` | Score every non-waived deliverable of the
    pinned scope revision, producing the weighted score and the outcome. | QualityReviewer |"
    PRD §3.8: "The new review is created in `status` `OPEN` with a `round_no` one greater than the
    highest among its siblings on that engagement, a `reviewer_user_id` recording the opening
    operator's `X-User-ID`, a `scored_deliverable_count` of 0, a null `weighted_score`, an
    `outcome` of `PENDING`, and null `rework_deadline_at` and `decided_at`."

    Design: Corner/rbac/rbac_program_manager_cannot_score_deliverables
    """
    world = setup_submitted_engagement()
    review = validate_success(
        api_client.create_quality_review(
            world["engagement"]["id"], world["reviewer_headers"]
        ),
        201,
    )
    deliverables = read_deliverables(world)
    scores = {row["id"]: 5 for row in deliverables}

    response = api_client.score_quality_review(
        review["id"], deliverable_scores_payload(scores), world["pm_headers"]
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)
    after = _review_row(world, review["id"])
    assert after["status"] == "OPEN", (
        f"Expected the round to stay OPEN, got {after['status']}"
    )
    assert after["outcome"] == "PENDING", (
        f"Expected the outcome to stay PENDING, got {after['outcome']}"
    )
    assert after["weighted_score"] is None, (
        f"Expected weighted_score to stay null, got {after['weighted_score']}"
    )
    assert after["scored_deliverable_count"] == 0, (
        f"Expected scored_deliverable_count to stay 0, got "
        f"{after['scored_deliverable_count']}"
    )


# ---------------------------------------------------------------------------
# The two-party agreement acts belong to the parties, not to the issuer
# ---------------------------------------------------------------------------
def test_27_the_issuing_program_manager_cannot_sign_the_agreement(api):
    """PRD §2.1: "A role value outside that set, or a role that is not listed among the target
    endpoint's authorized roles in §4, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "| POST | `/agreements/{id}/execute` | Sign the current terms revision. The first call
    stamps one slot; the countersign by the other party completes execution. | Volunteer,
    PartnerContact |"
    PRD §3.6: "The document is created with `status` `DRAFTED`, `counter_round` 0,
    `terms_revision_no` 1, a null `last_countered_by`, and null `volunteer_signed_at` and
    `partner_signed_at`."

    Design: Corner/rbac/rbac_program_manager_cannot_sign_the_agreement_it_issued
    """
    world = setup_sent_agreement()

    response = api_client.execute_agreement(
        world["agreement"]["id"], world["pm_headers"]
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)
    agreement = read_agreement(world)
    assert agreement["status"] == "SENT", (
        f"Expected the agreement to stay SENT, got {agreement['status']}"
    )
    assert agreement["volunteer_signed_at"] is None, (
        f"Expected volunteer_signed_at to stay null, got "
        f"{agreement['volunteer_signed_at']}"
    )
    assert agreement["partner_signed_at"] is None, (
        f"Expected partner_signed_at to stay null, got "
        f"{agreement['partner_signed_at']}"
    )


def test_28_the_sending_program_manager_cannot_counter_its_own_terms(api):
    """PRD §2.1: "A role value outside that set, or a role that is not listed among the target
    endpoint's authorized roles in §4, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "| POST | `/agreements/{id}/counter` | Either party counters the terms, opening a new
    negotiation round. A fourth round is refused and voids the agreement. | Volunteer,
    PartnerContact |"
    PRD §3.6: "A counter moves the agreement `SENT → COUNTERED`, raises `counter_round` by one,
    sets `terms_revision_no` to `counter_round` plus one, overwrites the three negotiated fields
    with the countered values, clears both signature timestamps to null so that nothing signed
    against the old revision survives, and records `last_countered_by` as `VOLUNTEER` or
    `PARTNER` according to who countered."

    Design: Corner/rbac/rbac_program_manager_cannot_counter_the_terms_it_sent
    """
    world = setup_sent_agreement(indemnity_cap_usd=25000.00)

    response = api_client.counter_agreement(
        world["agreement"]["id"],
        counter_payload(indemnity_cap_usd=5000.00),
        world["pm_headers"],
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)
    agreement = read_agreement(world)
    assert agreement["status"] == "SENT", (
        f"Expected the agreement to stay SENT, got {agreement['status']}"
    )
    assert agreement["counter_round"] == 0, (
        f"Expected counter_round to stay 0, got {agreement['counter_round']}"
    )
    assert agreement["terms_revision_no"] == 1, (
        f"Expected terms_revision_no to stay 1, got {agreement['terms_revision_no']}"
    )
    assert agreement["last_countered_by"] is None, (
        f"Expected last_countered_by to stay null, got "
        f"{agreement['last_countered_by']}"
    )
    assert agreement["indemnity_cap_usd"] == pytest.approx(25000.00, abs=0.01), (
        f"Expected the issued 25000.00 cap to survive, got "
        f"{agreement['indemnity_cap_usd']}"
    )


# ---------------------------------------------------------------------------
# Reads are role-gated too
# ---------------------------------------------------------------------------
def test_29_a_volunteer_cannot_read_the_partner_summary(api):
    """PRD §2.1: "A role value outside that set, or a role that is not listed among the target
    endpoint's authorized roles in §4, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "| GET | `/partner-orgs/{id}/summary` | Computed read: capacity class, engagement
    ceiling, open engagement count, satisfaction index, sample size, and the per-survey composite
    scores that produced the index. | ProgramManager, PartnerContact |"

    Design: Corner/rbac/rbac_volunteer_cannot_read_partner_summary
    """
    pm = make_program_manager_headers()
    partner = create_partner(pm, annual_budget_usd=MID_BUDGET)
    volunteer = create_volunteer(pm)

    response = api_client.get_partner_org_summary(
        partner["id"], make_volunteer_headers(volunteer["id"])
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)

    # The same read is open to the roles §4 lists for it.
    for headers in (pm, make_partner_contact_headers(partner["id"])):
        validate_success(api_client.get_partner_org_summary(partner["id"], headers))


def test_30_a_partner_contact_cannot_read_the_cycle_engagement_roll(api):
    """PRD §2.1: "A role value outside that set, or a role that is not listed among the target
    endpoint's authorized roles in §4, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "| GET | `/program-cycles/{id}/engagements` | Every engagement occupying a slot in
    this cycle, including terminal ones. | ProgramManager, ScopingSpecialist |"
    PRD §4: "| GET | `/program-cycles/{id}` | Read one program cycle including committed, reserved
    and available slots, the utilization ratio and the posture. | ProgramManager,
    ScopingSpecialist, PartnerContact |"

    Design: Corner/rbac/rbac_partner_contact_cannot_read_cycle_engagements
    """
    pm = make_program_manager_headers()
    cycle = create_cycle(pm, capacity_slot_total=4)
    partner = create_partner(pm, annual_budget_usd=MID_BUDGET)
    partner_headers = make_partner_contact_headers(partner["id"])

    response = api_client.list_cycle_engagements(cycle["id"], partner_headers)

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)

    # The cycle itself stays readable to the same caller — only the roll is closed.
    readable = validate_success(
        api_client.get_program_cycle(cycle["id"], partner_headers)
    )
    assert readable["id"] == cycle["id"], (
        f"Expected the cycle {cycle['id']}, got {readable['id']}"
    )


def test_31_a_partner_contact_cannot_read_a_volunteer_record(api):
    """PRD §2.1: "A role value outside that set, or a role that is not listed among the target
    endpoint's authorized roles in §4, is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."
    PRD §4: "| GET | `/volunteers/{id}` | Read one volunteer including both reliability variants,
    open and terminal engagement counts and lifetime valued dollars. | ProgramManager,
    ScopingSpecialist, Volunteer, QualityReviewer |"

    Design: Corner/rbac/rbac_partner_contact_cannot_read_volunteer_record
    """
    pm = make_program_manager_headers()
    partner = create_partner(pm, annual_budget_usd=MID_BUDGET)
    volunteer = create_volunteer(pm)

    response = api_client.get_volunteer(
        volunteer["id"], make_partner_contact_headers(partner["id"])
    )

    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED, expected_status=403)

    # The same row is readable to the roles §4 lists for it.
    readable = validate_success(api_client.get_volunteer(volunteer["id"], pm))
    assert readable["id"] == volunteer["id"], (
        f"Expected volunteer {volunteer['id']}, got {readable['id']}"
    )


# ---------------------------------------------------------------------------
# Ownership: an entity-backed caller reaches only its own resources
# ---------------------------------------------------------------------------
def test_32_a_second_partner_cannot_submit_another_partners_request(api):
    """PRD §2.1: "When `X-User-Role` is `PartnerContact`, `X-User-ID` is the `id` of the acting
    `PartnerOrg`; ownership checks compare the `partner_org_id` reached through the resource chain
    — directly on a project request, and transitively through the request for a scope approval, an
    engagement or a satisfaction survey — to `X-User-ID`. An entity-backed caller reaching for a
    resource that does not resolve to its own identifier is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)"
    PRD §2.12: "For the entity-backed roles, the caller owns the target resource —
    `ERR_NOT_RESOURCE_OWNER` (403) — on `POST /project-requests/{id}/submit-for-scoping`"

    Design: Corner/rbac/rbac_other_partner_contact_cannot_submit_foreign_request
    """
    world = setup_draft_request()
    stranger = create_partner(
        world["pm_headers"], annual_budget_usd=SECOND_PARTNER_BUDGET
    )

    response = api_client.submit_for_scoping(
        world["request"]["id"], make_partner_contact_headers(stranger["id"])
    )

    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)
    assert read_request(world)["status"] == "DRAFT", (
        "Expected the foreign submission to leave the request in DRAFT"
    )

    # The owning contact still gets through.
    moved = validate_success(
        api_client.submit_for_scoping(
            world["request"]["id"], world["partner_headers"]
        )
    )
    assert moved["status"] == "SCOPING", (
        f"Expected the owner's submission to reach SCOPING, got {moved['status']}"
    )


def test_33_a_second_partner_cannot_approve_another_partners_revision(api):
    """PRD §2.1: "When `X-User-Role` is `PartnerContact`, `X-User-ID` is the `id` of the acting
    `PartnerOrg`; ownership checks compare the `partner_org_id` reached through the resource chain
    — directly on a project request, and transitively through the request for a scope approval, an
    engagement or a satisfaction survey — to `X-User-ID`. An entity-backed caller reaching for a
    resource that does not resolve to its own identifier is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)"
    PRD §2.12: "For the entity-backed roles, the caller owns the target resource —
    `ERR_NOT_RESOURCE_OWNER` (403) — on `POST /project-requests/{id}/submit-for-scoping`, `POST
    /scope-definitions/{id}/approve`"

    Design: Corner/rbac/rbac_other_partner_contact_cannot_approve_foreign_scope
    """
    world = setup_scoping_request()
    stranger = create_partner(
        world["pm_headers"], annual_budget_usd=SECOND_PARTNER_BUDGET
    )

    response = api_client.approve_scope_definition(
        world["scope"]["id"], make_partner_contact_headers(stranger["id"])
    )

    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)
    assert read_scope(world)["status"] == "DRAFT", (
        "Expected the foreign approval to leave the revision in DRAFT"
    )
    assert read_request(world)["status"] == "SCOPING", (
        "Expected the foreign approval to leave the request in SCOPING"
    )

    # The owning contact still gets through.
    validate_success(
        api_client.approve_scope_definition(
            world["scope"]["id"], world["partner_headers"]
        )
    )
    assert read_scope(world)["status"] == "APPROVED", (
        "Expected the owner's approval to move the revision to APPROVED"
    )
    assert read_request(world)["status"] == "SCOPED", (
        "Expected the owner's approval to move the request to SCOPED"
    )


def test_34_a_second_volunteer_cannot_publish_a_window_on_a_foreign_profile(api):
    """PRD §2.1: "When `X-User-Role` is `Volunteer`, `X-User-ID` is the `id` of the acting
    `Volunteer` row; ownership checks on any resource that references a volunteer compare that
    resource's volunteer reference to `X-User-ID` — the `volunteer_id` of a skill claim,
    availability window or match offer, and the `volunteer_id` of an engagement whose work is
    being started, logged against or submitted."
    PRD §2.1: "An entity-backed caller reaching for a resource that does not resolve to its own
    identifier is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)"
    PRD §2.12: "`POST /volunteers/{id}/skill-profiles` and
    `POST /volunteers/{id}/availability-windows`."

    Design: Corner/rbac/rbac_other_volunteer_cannot_publish_window_on_foreign_profile
    """
    pm = make_program_manager_headers()
    create_cycle(pm, capacity_slot_total=4)
    owner, _skill, _window = create_vetted_volunteer()
    stranger, _skill2, _none = create_vetted_volunteer(window=False)

    response = api_client.create_availability_window(
        owner["id"],
        availability_window_payload(
            starts_at="2026-11-01T00:00:00Z",
            ends_at="2026-11-15T00:00:00Z",
            hours_offered=100.00,
        ),
        make_volunteer_headers(stranger["id"]),
    )

    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)
    _owner_rows, owner_meta = validate_paginated(
        api_client.list_availability_windows(owner["id"], pm)
    )
    assert owner_meta["total_count"] == 1, (
        f"Expected the owner to keep exactly its own one window, got "
        f"{owner_meta['total_count']}"
    )
    _stranger_rows, stranger_meta = validate_paginated(
        api_client.list_availability_windows(stranger["id"], pm)
    )
    assert stranger_meta["total_count"] == 0, (
        f"Expected the refused caller to hold no window, got "
        f"{stranger_meta['total_count']}"
    )


def test_35_a_second_volunteer_cannot_accept_another_volunteers_offer(api):
    """PRD §2.1: "When `X-User-Role` is `Volunteer`, `X-User-ID` is the `id` of the acting
    `Volunteer` row; ownership checks on any resource that references a volunteer compare that
    resource's volunteer reference to `X-User-ID` — the `volunteer_id` of a skill claim,
    availability window or match offer, and the `volunteer_id` of an engagement whose work is
    being started, logged against or submitted."
    PRD §2.1: "An entity-backed caller reaching for a resource that does not resolve to its own
    identifier is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)"
    PRD §2.12: "For the entity-backed roles, the caller owns the target resource —
    `ERR_NOT_RESOURCE_OWNER` (403) — on `POST /project-requests/{id}/submit-for-scoping`, `POST
    /scope-definitions/{id}/approve`, `POST /match-offers/{id}/accept`"

    Design: Corner/rbac/rbac_other_volunteer_cannot_accept_foreign_offer
    """
    world = setup_offer(cycle_slots=4, window_hours=200.00)
    stranger = add_second_volunteer(world)

    response = api_client.accept_match_offer(
        world["offer"]["id"], stranger["volunteer_headers"]
    )

    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)
    offer = read_offer(world)
    assert offer["status"] == "OFFERED", (
        f"Expected the offer to stay OFFERED, got {offer['status']}"
    )
    assert offer["responded_at"] is None, (
        f"Expected responded_at to stay null, got {offer['responded_at']}"
    )

    # The volunteer the offer was written for still gets through.
    validate_success(
        api_client.accept_match_offer(
            world["offer"]["id"], world["volunteer_headers"]
        ),
        201,
    )
    assert read_offer(world)["status"] == "ACCEPTED", (
        "Expected the holder's acceptance to move the offer to ACCEPTED"
    )


def test_36_a_second_volunteer_cannot_log_hours_on_a_foreign_engagement(api):
    """PRD §2.1: "When `X-User-Role` is `Volunteer`, `X-User-ID` is the `id` of the acting
    `Volunteer` row; ownership checks on any resource that references a volunteer compare that
    resource's volunteer reference to `X-User-ID` — the `volunteer_id` of a skill claim,
    availability window or match offer, and the `volunteer_id` of an engagement whose work is
    being started, logged against or submitted."
    PRD §2.1: "the `logged_by_user_id` stamped on a time log is always the submitting volunteer's
    own identifier, so the field is never a way around the ownership check."
    PRD §2.12: "`POST /engagements/{id}/start`, `POST /engagements/{id}/submit`, `POST
    /engagements/{id}/time-logs`"

    Design: Corner/rbac/rbac_other_volunteer_cannot_log_hours_on_foreign_engagement
    """
    world = setup_in_progress_engagement()
    stranger = add_second_volunteer(world)

    response = api_client.create_time_log(
        world["engagement"]["id"],
        time_log_payload(hours=5.00),
        stranger["volunteer_headers"],
    )

    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)
    _rows, meta = validate_paginated(
        api_client.list_time_logs(world["engagement"]["id"], world["pm_headers"])
    )
    assert meta["total_count"] == 0, (
        f"Expected no time log to exist after the refusal, got {meta['total_count']}"
    )

    # The engaged volunteer still gets through.
    validate_success(
        api_client.create_time_log(
            world["engagement"]["id"],
            time_log_payload(hours=5.00),
            world["volunteer_headers"],
        ),
        201,
    )


# ---------------------------------------------------------------------------
# Segregation of duties reads the operator identifier, not the role header
# ---------------------------------------------------------------------------
def test_37_the_scope_author_operator_cannot_open_the_review_round(api):
    """PRD §2.1: "Segregation of duties is an additional, independent barrier layered on top of
    role and ownership. A `QualityReviewer` may not decide a review whose pinned scope revision
    carries that same operator identifier in `authored_by_user_id`, and may not score or decide a
    round whose `reviewer_user_id` belongs to a different operator; opening a new review round on
    an engagement is likewise barred to an operator who authored the pinned scope or who owned a
    prior round on that engagement. Any such attempt is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.5: "The remaining engagement fields start at their defaults: `approved_hours` 0.00,
    `scope_creep_pct` 0, `creep_escalation_level` `NONE`, `quality_gate` `PENDING`"

    Design: Corner/rbac/rbac_scope_author_operator_cannot_open_the_review
    """
    world = setup_submitted_engagement(spec_user_id=QR_USER_ID)
    assert read_scope(world)["authored_by_user_id"] == QR_USER_ID, (
        "Setup expected the pinned revision to be authored by the operator that will "
        "present the QualityReviewer role"
    )

    response = api_client.create_quality_review(
        world["engagement"]["id"], make_quality_reviewer_headers(QR_USER_ID)
    )

    validate_error(
        response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403
    )
    _rows, meta = validate_paginated(
        api_client.list_quality_reviews(
            world["engagement"]["id"], world["pm_headers"]
        )
    )
    assert meta["total_count"] == 0, (
        f"Expected no review round to have been created, got {meta['total_count']}"
    )
    engagement = read_engagement(world)
    assert engagement["work_status"] == "SUBMITTED", (
        f"Expected the engagement to stay SUBMITTED, got {engagement['work_status']}"
    )
    assert engagement["quality_gate"] == "PENDING", (
        f"Expected quality_gate to stay PENDING, got {engagement['quality_gate']}"
    )


def test_38_the_scope_author_operator_cannot_decide_the_scored_round(api):
    """PRD §2.1: "Segregation of duties is an additional, independent barrier layered on top of
    role and ownership. A `QualityReviewer` may not decide a review whose pinned scope revision
    carries that same operator identifier in `authored_by_user_id`, and may not score or decide a
    round whose `reviewer_user_id` belongs to a different operator; opening a new review round on
    an engagement is likewise barred to an operator who authored the pinned scope or who owned a
    prior round on that engagement. Any such attempt is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.8: "The `outcome` follows from the score: `PASS` at 78.00 and above, `CONDITIONAL` from
    60.00 up to but not including 78.00, and `FAIL` below 60.00."

    Design: Corner/rbac/rbac_scope_author_operator_cannot_decide_the_review
    """
    world = setup_submitted_engagement()
    deliverables = read_deliverables(world)
    review = drive_review_to_outcome(world, {row["id"]: 5 for row in deliverables})

    response = api_client.decide_quality_review(
        review["id"], make_quality_reviewer_headers(SPEC_USER_ID)
    )

    validate_error(
        response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403
    )
    after = _review_row(world, review["id"])
    assert after["status"] == "SCORED", (
        f"Expected the round to stay SCORED, got {after['status']}"
    )
    assert after["weighted_score"] == pytest.approx(100.00, abs=0.01), (
        f"Expected the straight-5 score of 100.00 to stand, got "
        f"{after['weighted_score']}"
    )
    assert after["outcome"] == "PASS", (
        f"Expected the scored outcome PASS to stand undecided, got {after['outcome']}"
    )
    assert after["decided_at"] is None, (
        f"Expected decided_at to stay null, got {after['decided_at']}"
    )
    engagement = read_engagement(world)
    assert engagement["work_status"] == "SUBMITTED", (
        f"Expected the engagement to stay SUBMITTED, got {engagement['work_status']}"
    )
    assert engagement["quality_gate"] == "PENDING", (
        f"Expected quality_gate to stay PENDING, got {engagement['quality_gate']}"
    )
