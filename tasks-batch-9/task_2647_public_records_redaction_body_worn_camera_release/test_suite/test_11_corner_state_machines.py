"""State-machine corners: initial states, refused transitions and terminal lockdown.

Every scenario here pins where a row is born, which edges it may not take twice,
and exactly how far a cascade reaches when a claim is overruled, withdrawn or
reversed on appeal.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import (
    ERR_ASSET_STATE_INVALID,
    ERR_CLAIM_ALREADY_ADJUDICATED,
    ERR_HOLD_STATE_INVALID,
    ERR_PURGE_NOT_DUE,
    ERR_TASK_STATE_INVALID,
)
from test_helpers.assertions import (
    assert_created,
    assert_fields,
    assert_ledger_conservation,
    assert_list_response,
    assert_modified,
    assert_money_is_integer_cents,
)
from test_helpers.factories import (
    adjudication_payload,
    appeal_decision_payload,
    appeal_payload,
    denial_letter_payload,
    hold_release_payload,
    objection_payload,
    purge_payload,
    qa_outcome_payload,
    request_payload,
)
from test_helpers.fixtures import (
    adjudicate,
    assert_claim,
    attach_record,
    clarify_scope,
    create_asset,
    create_depicted_individual,
    create_request,
    create_requester,
    create_staff,
    get_asset,
    get_claim,
    get_hold,
    get_individual,
    get_letter,
    get_record,
    get_request,
    get_requester,
    get_staff,
    get_task,
    issue_notice,
    open_task,
    place_hold,
    rule_inclusion,
    set_clock,
)
from test_helpers.test_users import (
    CLERK_HEADERS,
    SUPERVISOR_HEADERS,
    make_counsel_headers,
    make_requester_headers,
    make_reviewer_headers,
)


def _intake_general_public(api):
    """Register one GENERAL_PUBLIC filer and intake a single request for them."""
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    request = assert_created(
        api.create_request(
            request_payload(
                requester["id"],
                received_at="2026-08-01T00:00:00Z",
                subject_incident_number="INC-2026-0613",
                requested_date_from="2026-07-01T00:00:00Z",
                requested_date_to="2026-07-02T00:00:00Z",
                scope_narrative="All BWC video for INC-2026-0613",
            ),
            CLERK_HEADERS,
        )
    )
    return {"requester_id": requester["id"], "request": request}


def test_a_new_request_is_born_in_intake_with_its_fee_dimension_not_assessed(api):
    """Both parallel dimensions start at their declared initial values on one row.

    PRD: "A successful intake creates the request at `processing_status` `INTAKE`, `fee_status` `NOT_ASSESSED` and `version` 1, increments the filer's `open_request_count` by 1, and strikes the first `statutory_deadline_at`."

    Design: Corner/state_machines/request_starts_in_intake_with_fee_not_assessed
    """
    scenario = _intake_general_public(api)

    assert_fields(
        scenario["request"],
        processing_status="INTAKE",
        fee_status="NOT_ASSESSED",
        version=1,
        scope_clarification_count=0,
        extension_days_granted=0,
        responsive_record_count=0,
        unadjudicated_claim_count=0,
        open_notification_count=0,
    )
    assert get_requester(api, scenario["requester_id"])["open_request_count"] == 1


def test_the_first_statutory_deadline_is_received_at_plus_twenty_days(api):
    """With no responsive record the anchor is received_at and the budget is twenty days.

    PRD: "**Step three applies a floor guard**: `statutory_deadline_at` is the later of the anchor advanced by the budget in whole days, and `received_at` advanced by twenty whole days."

    Design: Corner/state_machines/request_starts_in_intake_with_fee_not_assessed
    """
    scenario = _intake_general_public(api)

    assert_fields(
        scenario["request"],
        statutory_deadline_at="2026-08-21T00:00:00Z",
        tolled_days=0,
        is_critical_incident=False,
    )
    assert_fields(
        get_request(api, scenario["request"]["id"]),
        statutory_deadline_at="2026-08-21T00:00:00Z",
        tolled_days=0,
    )


def test_every_money_figure_on_a_fresh_request_reads_zero(api):
    """No estimate and no ledger line means every cent field is an integer zero.

    PRD: "The request's `estimated_total_cents` and `deposit_required_cents` mirror the new estimate's corresponding figures — and are 0 whenever no `ACTIVE` estimate exists — and the request's `version` increases by 1."

    Design: Corner/state_machines/request_starts_in_intake_with_fee_not_assessed
    """
    scenario = _intake_general_public(api)

    request = get_request(api, scenario["request"]["id"])
    assert_fields(
        request,
        estimated_total_cents=0,
        deposit_required_cents=0,
        deposit_paid_cents=0,
        deposit_balance_cents=0,
        waiver_credit_total_cents=0,
        fee_recognized_cents=0,
        billable_labor_minutes=0,
        deposit_due_at=None,
    )
    assert_money_is_integer_cents(
        request,
        "estimated_total_cents",
        "deposit_required_cents",
        "deposit_paid_cents",
        "deposit_balance_cents",
        "waiver_credit_total_cents",
        "fee_recognized_cents",
    )
    assert_ledger_conservation(request)


def _four_depicted_individuals(api):
    """One ten-minute recording carrying one row of each of four relationships."""
    asset = create_asset(
        api,
        incident_number="INC-2026-0614",
        device_serial="AXON-0614",
        officer_badge="B-1114",
        recorded_start_at="2026-07-31T13:00:00Z",
        duration_ms=600000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-31T00:00:00Z",
    )
    bystander = create_depicted_individual(api, asset["id"], "Bystander 1", "BYSTANDER")
    officer = create_depicted_individual(api, asset["id"], "Officer 1", "OFFICER")
    suspect = create_depicted_individual(api, asset["id"], "Suspect 1", "SUSPECT")
    juvenile = create_depicted_individual(api, asset["id"], "Juvenile 1", "JUVENILE")
    return {
        "asset_id": asset["id"],
        "bystander_id": bystander["id"],
        "officer_id": officer["id"],
        "suspect_id": suspect["id"],
        "juvenile_id": juvenile["id"],
    }


def test_bystander_officer_and_suspect_rows_are_born_terminal_in_not_required(api):
    """None of the three unprotected relationships needs a notice, so all three skip PENDING.

    PRD: "Whether the law requires telling this person before their footage is published is derived, never supplied: `notification_required` is true exactly when `relationship` is `VICTIM`, `JUVENILE` or `WITNESS`."

    Design: Corner/state_machines/depicted_individual_initialises_in_not_required_for_non_protected_roles
    """
    scenario = _four_depicted_individuals(api)

    for key in ("bystander_id", "officer_id", "suspect_id"):
        assert_fields(
            get_individual(api, scenario[key]),
            notification_status="NOT_REQUIRED",
            notification_required=False,
        )
    assert get_asset(api, scenario["asset_id"])["depicted_individual_count"] == 4


def test_a_juvenile_row_is_born_pending_with_no_notice_yet_issued(api):
    """The juvenile is the only one of the four created awaiting a notice.

    PRD: "That derivation picks the individual's initial position directly — a row that requires notification is created at `notification_status` `PENDING`, and a row that does not is created at `notification_status` `NOT_REQUIRED`, which is terminal and never gates a release."

    Design: Corner/state_machines/depicted_individual_initialises_in_not_required_for_non_protected_roles
    """
    scenario = _four_depicted_individuals(api)

    assert_fields(
        get_individual(api, scenario["juvenile_id"]),
        notification_status="PENDING",
        notification_required=True,
        notice_method=None,
        notified_at=None,
        objection_deadline_at=None,
        objection_basis=None,
    )


def _sustained_privacy_claim(api):
    """A 20-minute recording whose PERSONAL_PRIVACY partial claim is already SUSTAINED."""
    counsel_a = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    counsel_b = create_staff(api, "Rex Counsel", "COUNSEL", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0615",
        device_serial="AXON-0615",
        officer_badge="B-1115",
        recorded_start_at="2026-07-31T14:00:00Z",
        duration_ms=1200000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-31T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        received_at="2026-08-01T00:00:00Z",
        subject_incident_number="INC-2026-0615",
        requested_date_from="2026-07-31T00:00:00Z",
        requested_date_to="2026-08-01T00:00:00Z",
        scope_narrative="All BWC video for INC-2026-0615",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Lobby camera only",
        requested_date_from="2026-07-31T00:00:00Z",
        requested_date_to="2026-07-31T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    claim = assert_claim(
        api, record["id"], counsel_a["id"], "PERSONAL_PRIVACY", "PARTIAL_REDACT"
    )
    adjudicate(
        api,
        claim["id"],
        counsel_b["id"],
        "SUSTAINED",
        adjudication_note="Privacy interest outweighs disclosure",
    )
    return {
        "request_id": request["id"],
        "record_id": record["id"],
        "claim_id": claim["id"],
        "counsel_b_id": counsel_b["id"],
    }


def test_a_second_adjudication_of_a_decided_claim_is_refused(api):
    """The already-sustained claim keeps its first decision byte for byte.

    PRD: "The claim must still be at `ASSERTED`; a second attempt on an already-decided claim is refused with `ERR_CLAIM_ALREADY_ADJUDICATED`."

    Design: Corner/state_machines/adjudicating_a_sustained_claim_twice_returns_already_adjudicated
    """
    scenario = _sustained_privacy_claim(api)
    before = get_claim(api, scenario["claim_id"])

    response = api.adjudicate_claim(
        scenario["claim_id"],
        adjudication_payload("OVERRULED", "Second bite"),
        make_counsel_headers(scenario["counsel_b_id"]),
    )

    validate_error(response, ERR_CLAIM_ALREADY_ADJUDICATED, 409)
    after = get_claim(api, scenario["claim_id"])
    assert_fields(
        after,
        status="SUSTAINED",
        adjudication_note="Privacy interest outweighs disclosure",
        adjudicated_by_staff_id=scenario["counsel_b_id"],
        adjudicated_at="2026-08-01T00:00:00Z",
        version=before["version"],
    )


def test_the_refused_second_adjudication_leaves_the_record_posture_untouched(api):
    """Burdens stay at 13 and 13 and the request stays in the production phase.

    PRD: "The record's two burden figures are re-derived from the baseline obscuration plus a sum over claims: `presumptive_burden_minutes` is the baseline plus the total `estimated_redaction_minutes` of every claim on the record whose `status` is `ASSERTED` or `SUSTAINED`, while `adjudicated_burden_minutes` is the baseline plus the total over claims whose `status` is `SUSTAINED` only."

    Design: Corner/state_machines/adjudicating_a_sustained_claim_twice_returns_already_adjudicated
    """
    scenario = _sustained_privacy_claim(api)

    response = api.adjudicate_claim(
        scenario["claim_id"],
        adjudication_payload("OVERRULED", "Second bite"),
        make_counsel_headers(scenario["counsel_b_id"]),
    )

    validate_error(response, ERR_CLAIM_ALREADY_ADJUDICATED, 409)
    assert_fields(
        get_record(api, scenario["record_id"]),
        inclusion_status="RESPONSIVE",
        release_posture="RESTRICTED",
        presumptive_burden_minutes=13,
        adjudicated_burden_minutes=13,
        unadjudicated_claim_count=0,
    )
    assert_fields(
        get_request(api, scenario["request_id"]),
        processing_status="REDACTION",
        unadjudicated_claim_count=0,
    )


def _draft_face_task(api):
    """A single DRAFT FACE task on a responsive record, never submitted for review."""
    tech = create_staff(api, "Tess Tech", "TECHNICIAN", 2)
    reviewer = create_staff(api, "Quinn Review", "REVIEWER", 2)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0616",
        device_serial="AXON-0616",
        officer_badge="B-1116",
        recorded_start_at="2026-07-31T15:00:00Z",
        duration_ms=1200000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-31T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        received_at="2026-08-01T00:00:00Z",
        subject_incident_number="INC-2026-0616",
        requested_date_from="2026-07-31T00:00:00Z",
        requested_date_to="2026-08-01T00:00:00Z",
        scope_narrative="All BWC video for INC-2026-0616",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Front camera only",
        requested_date_from="2026-07-31T00:00:00Z",
        requested_date_to="2026-07-31T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    task = open_task(api, record["id"], tech["id"], "FACE", 0, 120000)
    return {
        "request_id": request["id"],
        "record_id": record["id"],
        "task_id": task["id"],
        "reviewer_id": reviewer["id"],
    }


def test_a_quality_verdict_on_a_draft_task_is_refused(api):
    """qa-outcome exists only out of QA_PENDING, so the DRAFT task may not jump to APPROVED.

    PRD: "The task must be at `QA_PENDING`, so a verdict on a `DRAFT` task is refused with `ERR_TASK_STATE_INVALID`."

    Design: Corner/state_machines/qa_outcome_on_draft_task_returns_task_state_invalid
    """
    scenario = _draft_face_task(api)

    response = api.record_qa_outcome(
        scenario["task_id"],
        qa_outcome_payload("PASS"),
        make_reviewer_headers(scenario["reviewer_id"]),
    )

    validate_error(response, ERR_TASK_STATE_INVALID, 409)
    assert_fields(
        get_task(api, scenario["task_id"]),
        status="DRAFT",
        qa_reviewer_id=None,
        qa_window_start_at=None,
        qa_window_end_at=None,
        approved_labor_minutes=0,
        rework_count=0,
    )


def test_the_refused_verdict_invents_no_reviewer_booking_and_no_labour(api):
    """The reviewer's calendar and every labour rollup stay at zero.

    PRD: "A newly registered staff member begins with `open_qa_assignment_count` at 0; that counter tracks how many redaction tasks currently name this person as their booked quality reviewer and sit awaiting a verdict, and it is maintained by the review workflow of §3.6."

    Design: Corner/state_machines/qa_outcome_on_draft_task_returns_task_state_invalid
    """
    scenario = _draft_face_task(api)

    response = api.record_qa_outcome(
        scenario["task_id"],
        qa_outcome_payload("PASS"),
        make_reviewer_headers(scenario["reviewer_id"]),
    )

    validate_error(response, ERR_TASK_STATE_INVALID, 409)
    assert get_staff(api, scenario["reviewer_id"])["open_qa_assignment_count"] == 0
    assert_fields(
        get_record(api, scenario["record_id"]),
        approved_labor_minutes=0,
        redacted_segment_ms=0,
    )
    assert_fields(
        get_request(api, scenario["request_id"]),
        processing_status="REDACTION",
        billable_labor_minutes=0,
    )


def _asset_one_second_before_its_purge_date(api):
    """An unlocked recording due for destruction at 2026-09-01, with the clock a second short."""
    set_clock(api, "2026-08-31T23:59:59Z")
    asset = create_asset(
        api,
        incident_number="INC-2026-0617",
        device_serial="AXON-0617",
        officer_badge="B-1117",
        recorded_start_at="2026-03-05T09:00:00Z",
        duration_ms=600000,
        classification="ROUTINE",
        retention_category="NON_EVIDENTIARY_180D",
        scheduled_purge_at="2026-09-01T00:00:00Z",
    )
    return asset["id"]


def test_destruction_one_second_before_the_purge_date_is_refused(api):
    """The recording is unlocked and SCHEDULED, but the retention date has not arrived.

    PRD: "A recording that is `SUSPENDED` or already `PURGED` is refused with `ERR_ASSET_STATE_INVALID`; one that is still locked — whether by an `ACTIVE` matching hold or by an open request — is refused with `ERR_RETENTION_HOLD_ACTIVE`; and one whose purge date has not yet arrived is refused with `ERR_PURGE_NOT_DUE`."

    Design: Corner/state_machines/purge_is_refused_before_due_then_locks_the_asset_terminal
    """
    asset_id = _asset_one_second_before_its_purge_date(api)

    response = api.purge_video_asset(
        asset_id, purge_payload("One second early"), SUPERVISOR_HEADERS
    )

    validate_error(response, ERR_PURGE_NOT_DUE, 409)
    assert_fields(
        get_asset(api, asset_id),
        disposition_state="SCHEDULED",
        retention_locked=False,
    )


def test_destruction_at_the_purge_instant_itself_succeeds(api):
    """The comparison is inclusive, so the boundary instant is already due.

    PRD: "It accepts an optional `destruction_note` and demands three things simultaneously: the recording's `disposition_state` must be `SCHEDULED`, its `retention_locked` must be false, and the logical clock must have reached or passed `scheduled_purge_at`."

    Design: Corner/state_machines/purge_is_refused_before_due_then_locks_the_asset_terminal
    """
    asset_id = _asset_one_second_before_its_purge_date(api)
    set_clock(api, "2026-09-01T00:00:00Z")

    response = api.purge_video_asset(
        asset_id, purge_payload("Retention schedule executed"), SUPERVISOR_HEADERS
    )

    assert_modified(response)
    assert_fields(
        get_asset(api, asset_id),
        disposition_state="PURGED",
        retention_locked=False,
        suspended_by_hold_id=None,
    )


def test_a_second_destruction_of_a_purged_recording_is_refused(api):
    """PURGED is terminal, so the repeat attempt is a state failure rather than a no-op success.

    PRD: "A recording that is `SUSPENDED` or already `PURGED` is refused with `ERR_ASSET_STATE_INVALID`; one that is still locked — whether by an `ACTIVE` matching hold or by an open request — is refused with `ERR_RETENTION_HOLD_ACTIVE`; and one whose purge date has not yet arrived is refused with `ERR_PURGE_NOT_DUE`."

    Design: Corner/state_machines/purge_is_refused_before_due_then_locks_the_asset_terminal
    """
    asset_id = _asset_one_second_before_its_purge_date(api)
    set_clock(api, "2026-09-01T00:00:00Z")
    assert_modified(
        api.purge_video_asset(
            asset_id, purge_payload("Retention schedule executed"), SUPERVISOR_HEADERS
        )
    )

    response = api.purge_video_asset(
        asset_id, purge_payload("Second attempt"), SUPERVISOR_HEADERS
    )

    validate_error(response, ERR_ASSET_STATE_INVALID, 409)
    assert get_asset(api, asset_id)["disposition_state"] == "PURGED"


def _two_claims_and_three_draft_tasks(api):
    """One record carrying two asserted claims and three DRAFT tasks, one per link."""
    counsel_a = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    counsel_b = create_staff(api, "Rex Counsel", "COUNSEL", 3)
    tech = create_staff(api, "Tess Tech", "TECHNICIAN", 2)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0618",
        device_serial="AXON-0618",
        officer_badge="B-1118",
        recorded_start_at="2026-07-31T16:00:00Z",
        duration_ms=1200000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-31T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        received_at="2026-08-01T00:00:00Z",
        subject_incident_number="INC-2026-0618",
        requested_date_from="2026-07-31T00:00:00Z",
        requested_date_to="2026-08-01T00:00:00Z",
        scope_narrative="All BWC video for INC-2026-0618",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Interview room only",
        requested_date_from="2026-07-31T00:00:00Z",
        requested_date_to="2026-07-31T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    claim_one = assert_claim(
        api, record["id"], counsel_a["id"], "PERSONAL_PRIVACY", "PARTIAL_REDACT"
    )
    claim_two = assert_claim(
        api, record["id"], counsel_a["id"], "VICTIM_PROTECTION", "PARTIAL_REDACT"
    )
    task_one = open_task(api, record["id"], tech["id"], "FACE", 0, 60000, claim_one["id"])
    task_two = open_task(
        api, record["id"], tech["id"], "FACE", 60000, 120000, claim_two["id"]
    )
    task_three = open_task(api, record["id"], tech["id"], "LICENSE_PLATE", 0, 60000)
    return {
        "request_id": request["id"],
        "record_id": record["id"],
        "claim_one_id": claim_one["id"],
        "claim_two_id": claim_two["id"],
        "task_one_id": task_one["id"],
        "task_two_id": task_two["id"],
        "task_three_id": task_three["id"],
        "counsel_b_id": counsel_b["id"],
    }


def test_an_overrule_cancels_only_the_task_that_implemented_that_claim(api):
    """Of three DRAFT tasks only the one naming the overruled claim is CANCELLED.

    PRD: "But an overruled claim cancels only the redaction work that implemented **that specific claim**: every redaction task on the record whose `exemption_claim_id` names this claim and whose `status` is `DRAFT`, `QA_PENDING` or `QA_REJECTED` moves to `CANCELLED`, because the obscuration it performed is no longer authorised, while tasks on the same record tied to other claims or to the baseline pass are untouched."

    Design: Corner/state_machines/overruled_claim_cancels_only_the_tasks_tied_to_that_claim
    """
    scenario = _two_claims_and_three_draft_tasks(api)

    assert_modified(
        api.adjudicate_claim(
            scenario["claim_one_id"],
            adjudication_payload("OVERRULED", "No privacy interest in a public lobby"),
            make_counsel_headers(scenario["counsel_b_id"]),
        )
    )

    assert get_claim(api, scenario["claim_one_id"])["status"] == "OVERRULED"
    assert get_claim(api, scenario["claim_two_id"])["status"] == "ASSERTED"
    assert_fields(
        get_task(api, scenario["task_one_id"]),
        status="CANCELLED",
        approved_labor_minutes=0,
    )
    assert get_task(api, scenario["task_two_id"])["status"] == "DRAFT"
    assert get_task(api, scenario["task_three_id"])["status"] == "DRAFT"


def test_an_overrule_leaves_the_surviving_claim_in_both_burden_figures(api):
    """Presumptive falls to 17 for the still-asserted claim while adjudicated stays at the baseline 5.

    PRD: "The parent record re-derives `release_posture` and `adjudicated_burden_minutes`, and `unadjudicated_claim_count` decrements on both the record and the request, exactly as with a sustain."

    Design: Corner/state_machines/overruled_claim_cancels_only_the_tasks_tied_to_that_claim
    """
    scenario = _two_claims_and_three_draft_tasks(api)

    assert_modified(
        api.adjudicate_claim(
            scenario["claim_one_id"],
            adjudication_payload("OVERRULED", "No privacy interest in a public lobby"),
            make_counsel_headers(scenario["counsel_b_id"]),
        )
    )

    assert_fields(
        get_record(api, scenario["record_id"]),
        inclusion_status="RESPONSIVE",
        release_posture="RESTRICTED",
        unadjudicated_claim_count=1,
        presumptive_burden_minutes=17,
        adjudicated_burden_minutes=5,
        approved_labor_minutes=0,
    )
    assert_fields(
        get_request(api, scenario["request_id"]),
        unadjudicated_claim_count=1,
        processing_status="REDACTION",
        billable_labor_minutes=0,
    )


def _asserted_privacy_claim_awaiting_disposition(api):
    """A 20-minute recording carrying one asserted privacy claim: presumptive 13, adjudicated 5."""
    counsel_a = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    counsel_b = create_staff(api, "Rex Counsel", "COUNSEL", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0619",
        device_serial="AXON-0619",
        officer_badge="B-1119",
        recorded_start_at="2026-07-31T17:00:00Z",
        duration_ms=1200000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-31T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        received_at="2026-08-01T00:00:00Z",
        subject_incident_number="INC-2026-0619",
        requested_date_from="2026-07-31T00:00:00Z",
        requested_date_to="2026-08-01T00:00:00Z",
        scope_narrative="All BWC video for INC-2026-0619",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Booking area only",
        requested_date_from="2026-07-31T00:00:00Z",
        requested_date_to="2026-07-31T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    claim = assert_claim(
        api,
        record["id"],
        counsel_a["id"],
        "PERSONAL_PRIVACY",
        "PARTIAL_REDACT",
        statutory_citation="119.071(4)(d)",
    )
    return {
        "request_id": request["id"],
        "record_id": record["id"],
        "claim_id": claim["id"],
        "counsel_b_id": counsel_b["id"],
    }


def test_a_withdrawal_is_the_only_disposition_that_lowers_presumptive_burden(api):
    """Presumptive falls 13 to 5 while the adjudicated figure never moved off the baseline.

    PRD: "Because a withdrawn claim leaves the presumptive set as well as the adjudicated one, the record's `presumptive_burden_minutes` actually falls — something neither of the other two dispositions does, since a sustained claim was already in the presumptive set and an overruled one leaves both sets by the same amount the adjudicated figure never gained."

    Design: Corner/state_machines/withdrawn_claim_alone_lowers_presumptive_burden
    """
    scenario = _asserted_privacy_claim_awaiting_disposition(api)
    assert_fields(
        get_record(api, scenario["record_id"]),
        presumptive_burden_minutes=13,
        adjudicated_burden_minutes=5,
        release_posture="RESTRICTED",
    )

    adjudicate(
        api,
        scenario["claim_id"],
        scenario["counsel_b_id"],
        "WITHDRAWN",
        adjudication_note="Claim withdrawn by the asserting attorney",
    )

    assert get_claim(api, scenario["claim_id"])["status"] == "WITHDRAWN"
    assert_fields(
        get_record(api, scenario["record_id"]),
        inclusion_status="RESPONSIVE",
        release_posture="OPEN",
        presumptive_burden_minutes=5,
        adjudicated_burden_minutes=5,
        unadjudicated_claim_count=0,
    )


def test_a_withdrawal_lets_the_request_skip_redaction_entirely(api):
    """With no restricted record and no live task left, review jumps straight to RELEASE_READY.

    PRD: "If instead no claim remains `ASSERTED`, no `RESPONSIVE` record has `release_posture` `RESTRICTED`, no redaction task on the request sits at `DRAFT`, `QA_PENDING` or `QA_REJECTED`, and at least one record is `RESPONSIVE`, the request skips straight to `EXEMPTION_REVIEW → RELEASE_READY`."

    Design: Corner/state_machines/withdrawn_claim_alone_lowers_presumptive_burden
    """
    scenario = _asserted_privacy_claim_awaiting_disposition(api)
    assert get_request(api, scenario["request_id"])["processing_status"] == "EXEMPTION_REVIEW"

    adjudicate(
        api,
        scenario["claim_id"],
        scenario["counsel_b_id"],
        "WITHDRAWN",
        adjudication_note="Claim withdrawn by the asserting attorney",
    )

    assert_fields(
        get_request(api, scenario["request_id"]),
        processing_status="RELEASE_READY",
        unadjudicated_claim_count=0,
    )


def _appealed_full_denial(
    api,
    incident_number="INC-2026-0620",
    device_serial="AXON-0620",
    officer_badge="B-1120",
    recorded_start_at="2026-07-31T18:00:00Z",
    scope_narrative="Undercover operation footage",
):
    """A FULL denial over one wholly withheld record, appealed at clock 2026-08-10."""
    counsel_a = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    counsel_b = create_staff(api, "Rex Counsel", "COUNSEL", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number=incident_number,
        device_serial=device_serial,
        officer_badge=officer_badge,
        recorded_start_at=recorded_start_at,
        duration_ms=1200000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-31T00:00:00Z",
    )
    request = create_request(
        api,
        requester["id"],
        received_at="2026-08-01T00:00:00Z",
        subject_incident_number=incident_number,
        requested_date_from="2026-07-31T00:00:00Z",
        requested_date_to="2026-08-01T00:00:00Z",
        scope_narrative="All BWC video for " + incident_number,
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative=scope_narrative,
        requested_date_from="2026-07-31T00:00:00Z",
        requested_date_to="2026-07-31T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    claim = assert_claim(
        api,
        record["id"],
        counsel_a["id"],
        "ONGOING_INVESTIGATION",
        "FULL_WITHHOLD",
        statutory_citation="119.071(2)(c)",
    )
    adjudicate(
        api,
        claim["id"],
        counsel_b["id"],
        "SUSTAINED",
        adjudication_note="Active criminal investigation",
    )
    letter = assert_created(
        api.issue_denial_letter(
            request["id"],
            denial_letter_payload("FULL", "Circuit court review under 119.11"),
            make_counsel_headers(counsel_b["id"]),
        )
    )
    set_clock(api, "2026-08-10T00:00:00Z")
    assert_modified(
        api.file_appeal(
            letter["id"],
            appeal_payload("The investigation has concluded"),
            make_requester_headers(requester["id"]),
        )
    )
    return {
        "request_id": request["id"],
        "record_id": record["id"],
        "claim_id": claim["id"],
        "letter_id": letter["id"],
        "requester_id": requester["id"],
        "counsel_a_id": counsel_a["id"],
    }


def test_upholding_the_appeal_reopens_nothing_on_the_claim_or_the_record(api):
    """The inert arm leaves the sustained claim and the wholly withheld record exactly as they were.

    PRD: "The letter moves `APPEALED → UPHELD`, and **no** exemption claim, responsive record or redaction task is touched."

    Design: Corner/state_machines/appeal_upheld_closes_the_request_and_touches_nothing_else
    """
    scenario = _appealed_full_denial(api)

    assert_modified(
        api.decide_appeal(
            scenario["letter_id"],
            appeal_decision_payload("UPHELD"),
            make_counsel_headers(scenario["counsel_a_id"]),
        )
    )

    assert_fields(
        get_letter(api, scenario["letter_id"]),
        status="UPHELD",
        appeal_filed_at="2026-08-10T00:00:00Z",
        appeal_decided_at="2026-08-10T00:00:00Z",
    )
    assert get_claim(api, scenario["claim_id"])["status"] == "SUSTAINED"
    assert_fields(
        get_record(api, scenario["record_id"]),
        inclusion_status="WITHHELD_IN_FULL",
        release_posture="BLOCKED",
    )


def test_upholding_a_full_denial_settles_the_request_in_closed(api):
    """The denial stands, so the request retires from DENIED to CLOSED with the filer's slate clear.

    PRD: "Where the letter's `denial_type` is `FULL` and the request sits at `DENIED`, the request advances `DENIED → CLOSED`."

    Design: Corner/state_machines/appeal_upheld_closes_the_request_and_touches_nothing_else
    """
    scenario = _appealed_full_denial(api)
    assert get_request(api, scenario["request_id"])["processing_status"] == "DENIED"

    assert_modified(
        api.decide_appeal(
            scenario["letter_id"],
            appeal_decision_payload("UPHELD"),
            make_counsel_headers(scenario["counsel_a_id"]),
        )
    )

    assert get_request(api, scenario["request_id"])["processing_status"] == "CLOSED"
    assert get_requester(api, scenario["requester_id"])["open_request_count"] == 0


def test_the_letter_carries_a_thirty_day_window_and_the_denial_paperwork(api):
    """Issued on 1 August, appealable through 31 August, and citing the one sustained exemption.

    PRD: "The letter is created at `status` `ISSUED` with `issued_at` from the logical clock and `appeal_deadline_at` thirty whole days later, that final instant inclusive, and with `appeal_grounds`, `appeal_filed_at` and `appeal_decided_at` all null."

    Design: Corner/state_machines/appeal_upheld_closes_the_request_and_touches_nothing_else
    """
    scenario = _appealed_full_denial(api)

    assert_modified(
        api.decide_appeal(
            scenario["letter_id"],
            appeal_decision_payload("UPHELD"),
            make_counsel_headers(scenario["counsel_a_id"]),
        )
    )

    letter = get_letter(api, scenario["letter_id"])
    assert_fields(
        letter,
        denial_type="FULL",
        issued_at="2026-08-01T00:00:00Z",
        appeal_deadline_at="2026-08-31T00:00:00Z",
        appeal_authority="SUPERIOR_COURT",
        withheld_record_count=1,
    )
    assert letter["statutory_citations"] == ["119.071(2)(c)"]


def test_reversing_the_appeal_withdraws_the_sustained_claim_and_frees_the_record(api):
    """One call rolls the claim and the record back to their pre-denial values.

    PRD: "Every exemption claim on the request's records whose `status` is `SUSTAINED` moves `SUSTAINED → WITHDRAWN`."

    Design: Corner/state_machines/appeal_reversed_withdraws_sustained_claims_and_reopens_review
    """
    scenario = _appealed_full_denial(
        api,
        incident_number="INC-2026-0621",
        device_serial="AXON-0621",
        officer_badge="B-1121",
        recorded_start_at="2026-07-31T19:00:00Z",
        scope_narrative="Surveillance footage",
    )

    assert_modified(
        api.decide_appeal(
            scenario["letter_id"],
            appeal_decision_payload("REVERSED"),
            make_counsel_headers(scenario["counsel_a_id"]),
        )
    )

    assert get_claim(api, scenario["claim_id"])["status"] == "WITHDRAWN"
    assert_fields(
        get_record(api, scenario["record_id"]),
        inclusion_status="RESPONSIVE",
        release_posture="OPEN",
        presumptive_burden_minutes=5,
        adjudicated_burden_minutes=5,
        unadjudicated_claim_count=0,
    )


def test_reversing_a_full_denial_reopens_review_and_restores_the_filers_counter(api):
    """The request returns to EXEMPTION_REVIEW and the filer is once again carrying one open request.

    PRD: "Where the letter's `denial_type` is `FULL`, the request returns `DENIED → EXEMPTION_REVIEW` and the filer's `open_request_count` increases by 1 again."

    Design: Corner/state_machines/appeal_reversed_withdraws_sustained_claims_and_reopens_review
    """
    scenario = _appealed_full_denial(
        api,
        incident_number="INC-2026-0621",
        device_serial="AXON-0621",
        officer_badge="B-1121",
        recorded_start_at="2026-07-31T19:00:00Z",
        scope_narrative="Surveillance footage",
    )
    assert get_requester(api, scenario["requester_id"])["open_request_count"] == 0

    assert_modified(
        api.decide_appeal(
            scenario["letter_id"],
            appeal_decision_payload("REVERSED"),
            make_counsel_headers(scenario["counsel_a_id"]),
        )
    )

    assert_fields(
        get_request(api, scenario["request_id"]),
        processing_status="EXEMPTION_REVIEW",
        unadjudicated_claim_count=0,
        responsive_record_count=1,
    )
    assert get_requester(api, scenario["requester_id"])["open_request_count"] == 1
    assert_fields(
        get_letter(api, scenario["letter_id"]),
        status="REVERSED",
        appeal_decided_at="2026-08-10T00:00:00Z",
    )


def test_the_reversal_leaves_the_letters_frozen_history_alone(api):
    """The withheld count and citations were fixed at issuance and survive the record's release.

    PRD: "Its `withheld_record_count` is the number of the request's records at `inclusion_status` `WITHHELD_IN_FULL` at the moment of issuance."

    Design: Corner/state_machines/appeal_reversed_withdraws_sustained_claims_and_reopens_review
    """
    scenario = _appealed_full_denial(
        api,
        incident_number="INC-2026-0621",
        device_serial="AXON-0621",
        officer_badge="B-1121",
        recorded_start_at="2026-07-31T19:00:00Z",
        scope_narrative="Surveillance footage",
    )

    assert_modified(
        api.decide_appeal(
            scenario["letter_id"],
            appeal_decision_payload("REVERSED"),
            make_counsel_headers(scenario["counsel_a_id"]),
        )
    )

    letter = get_letter(api, scenario["letter_id"])
    assert letter["withheld_record_count"] == 1
    assert letter["statutory_citations"] == ["119.071(2)(c)"]
    assert get_record(api, scenario["record_id"])["inclusion_status"] == "RESPONSIVE"


def _two_active_holds_over_one_recording(api):
    """One recording on INC-2026-0622 suspended by hold H1 with H2 queued behind it."""
    counsel = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    asset = create_asset(
        api,
        incident_number="INC-2026-0622",
        device_serial="AXON-0622",
        officer_badge="B-1122",
        recorded_start_at="2026-07-31T20:00:00Z",
        duration_ms=600000,
        classification="ROUTINE",
        retention_category="NON_EVIDENTIARY_180D",
        scheduled_purge_at="2027-01-27T00:00:00Z",
    )
    hold_one = place_hold(
        api,
        counsel["id"],
        matter_number="M-2026-01",
        scope_incident_number="INC-2026-0622",
        hold_type="LITIGATION",
    )
    hold_two = place_hold(
        api,
        counsel["id"],
        matter_number="M-2026-02",
        scope_incident_number="INC-2026-0622",
        hold_type="SUBPOENA",
    )
    return {
        "counsel_id": counsel["id"],
        "asset_id": asset["id"],
        "hold_one_id": hold_one["id"],
        "hold_two_id": hold_two["id"],
    }


def test_releasing_the_first_of_two_holds_repoints_rather_than_frees_the_recording(api):
    """A second ACTIVE hold still matches the incident, so the recording stays SUSPENDED under H2.

    PRD: "Every recording whose `suspended_by_hold_id` pointed at the lifted hold is then re-examined: if another hold with `status` `ACTIVE` still carries a matching `scope_incident_number`, `suspended_by_hold_id` is repointed to that hold — again the matching `ACTIVE` hold with the smallest `created_at` — and `disposition_state` stays `SUSPENDED`; only when no `ACTIVE` hold matches does the recording move `SUSPENDED → SCHEDULED` with `suspended_by_hold_id` cleared to null."

    Design: Corner/state_machines/hold_release_repoints_asset_to_the_remaining_active_hold
    """
    scenario = _two_active_holds_over_one_recording(api)
    assert_fields(
        get_asset(api, scenario["asset_id"]),
        disposition_state="SUSPENDED",
        suspended_by_hold_id=scenario["hold_one_id"],
        retention_locked=True,
    )
    assert get_hold(api, scenario["hold_one_id"])["suspended_asset_count"] == 1
    assert get_hold(api, scenario["hold_two_id"])["suspended_asset_count"] == 0

    assert_modified(
        api.release_litigation_hold(
            scenario["hold_one_id"],
            hold_release_payload("Matter M-2026-01 settled"),
            make_counsel_headers(scenario["counsel_id"]),
        )
    )

    assert_fields(
        get_asset(api, scenario["asset_id"]),
        disposition_state="SUSPENDED",
        suspended_by_hold_id=scenario["hold_two_id"],
        retention_locked=True,
    )
    assert_fields(
        get_hold(api, scenario["hold_one_id"]),
        status="RELEASED",
        released_at="2026-08-01T00:00:00Z",
        suspended_asset_count=0,
    )
    assert get_hold(api, scenario["hold_two_id"])["suspended_asset_count"] == 1


def test_releasing_the_last_hold_returns_the_recording_to_its_retention_schedule(api):
    """With no ACTIVE hold left the recording is SCHEDULED again and both counters read zero.

    PRD: "The release accepts an optional `release_note`, moves the hold `ACTIVE → RELEASED`, stamps `released_at` with the logical clock, and resets the hold's `suspended_asset_count` to 0."

    Design: Corner/state_machines/hold_release_repoints_asset_to_the_remaining_active_hold
    """
    scenario = _two_active_holds_over_one_recording(api)
    assert_modified(
        api.release_litigation_hold(
            scenario["hold_one_id"],
            hold_release_payload("Matter M-2026-01 settled"),
            make_counsel_headers(scenario["counsel_id"]),
        )
    )

    assert_modified(
        api.release_litigation_hold(
            scenario["hold_two_id"],
            hold_release_payload("Subpoena quashed"),
            make_counsel_headers(scenario["counsel_id"]),
        )
    )

    assert_fields(
        get_asset(api, scenario["asset_id"]),
        disposition_state="SCHEDULED",
        suspended_by_hold_id=None,
        retention_locked=False,
    )
    assert_fields(
        get_hold(api, scenario["hold_two_id"]),
        status="RELEASED",
        released_at="2026-08-01T00:00:00Z",
        suspended_asset_count=0,
    )


def test_releasing_an_already_released_hold_is_refused(api):
    """RELEASED is terminal, so the duplicate lift is a state failure and nothing moves.

    PRD: "Lifting a hold that already carries `status` `RELEASED` is rejected with `ERR_HOLD_STATE_INVALID`."

    Design: Corner/state_machines/hold_release_repoints_asset_to_the_remaining_active_hold
    """
    scenario = _two_active_holds_over_one_recording(api)
    assert_modified(
        api.release_litigation_hold(
            scenario["hold_one_id"],
            hold_release_payload("Matter M-2026-01 settled"),
            make_counsel_headers(scenario["counsel_id"]),
        )
    )
    assert_modified(
        api.release_litigation_hold(
            scenario["hold_two_id"],
            hold_release_payload("Subpoena quashed"),
            make_counsel_headers(scenario["counsel_id"]),
        )
    )

    response = api.release_litigation_hold(
        scenario["hold_two_id"],
        hold_release_payload("Duplicate release"),
        make_counsel_headers(scenario["counsel_id"]),
    )

    validate_error(response, ERR_HOLD_STATE_INVALID, 409)
    assert get_hold(api, scenario["hold_two_id"])["status"] == "RELEASED"
    assert get_asset(api, scenario["asset_id"])["disposition_state"] == "SCHEDULED"


def _objecting_victim(api):
    """A notified VICTIM who objected on 10 August, minting a derived exemption claim."""
    counsel = create_staff(api, "Dana Counsel", "COUNSEL", 3)
    requester = create_requester(api, "Pat Public", "pat@example.org", "GENERAL_PUBLIC")
    asset = create_asset(
        api,
        incident_number="INC-2026-0623",
        device_serial="AXON-0623",
        officer_badge="B-1123",
        recorded_start_at="2026-07-31T21:00:00Z",
        duration_ms=1200000,
        classification="ROUTINE",
        retention_category="INVESTIGATIVE_3Y",
        scheduled_purge_at="2029-07-31T00:00:00Z",
    )
    individual = create_depicted_individual(api, asset["id"], "Victim V1", "VICTIM")
    request = create_request(
        api,
        requester["id"],
        received_at="2026-08-01T00:00:00Z",
        subject_incident_number="INC-2026-0623",
        requested_date_from="2026-07-31T00:00:00Z",
        requested_date_to="2026-08-01T00:00:00Z",
        scope_narrative="All BWC video for INC-2026-0623",
    )
    clarify_scope(
        api,
        request["id"],
        scope_narrative="Victim interview excluded from scope narrative",
        requested_date_from="2026-07-31T00:00:00Z",
        requested_date_to="2026-07-31T23:59:59Z",
    )
    record = attach_record(api, request["id"], asset["id"])
    rule_inclusion(api, record["id"], "RESPONSIVE")
    set_clock(api, "2026-08-05T00:00:00Z")
    issue_notice(api, individual["id"], "FIRST_CLASS_MAIL")
    set_clock(api, "2026-08-10T00:00:00Z")
    assert_created(
        api.record_objection(
            individual["id"],
            objection_payload(record["id"], "VICTIM_STATUS"),
            CLERK_HEADERS,
        )
    )
    claims, _meta = assert_list_response(
        api.list_exemption_claims(
            CLERK_HEADERS, params={"responsive_record_id": record["id"]}
        )
    )
    assert len(claims) == 1
    return {
        "request_id": request["id"],
        "record_id": record["id"],
        "individual_id": individual["id"],
        "claim_id": claims[0]["id"],
        "claim": claims[0],
        "counsel_id": counsel["id"],
    }


def test_the_objection_mints_a_claim_no_staff_member_asserted(api):
    """The derived claim names the objector, carries no asserting attorney, and starts ASSERTED.

    PRD: "That claim is created with `claim_source` `DEPICTED_OBJECTION`, `depicted_individual_id` pointing back at the objector, `asserted_by_staff_id` null — no staff member asserted it, which is why any attorney may later decide it — `status` `ASSERTED` and `asserted_scope` `PARTIAL_REDACT`."

    Design: Corner/state_machines/objection_sustained_clears_the_notification_counter
    """
    scenario = _objecting_victim(api)

    assert_fields(
        scenario["claim"],
        claim_source="DEPICTED_OBJECTION",
        exemption_code="VICTIM_PROTECTION",
        statutory_citation="119.071(2)(j)",
        asserted_scope="PARTIAL_REDACT",
        status="ASSERTED",
        asserted_by_staff_id=None,
        depicted_individual_id=scenario["individual_id"],
    )
    assert_fields(
        get_individual(api, scenario["individual_id"]),
        notification_status="OBJECTED",
        notified_at="2026-08-05T00:00:00Z",
        objection_deadline_at="2026-08-15T00:00:00Z",
        objection_basis="VICTIM_STATUS",
    )
    assert get_request(api, scenario["request_id"])["open_notification_count"] == 1


def test_sustaining_the_objection_retires_the_objector_from_the_notification_counter(api):
    """The individual reaches the terminal OBJECTION_SUSTAINED and open_notification_count falls to 0.

    PRD: "And when the sustained claim's `claim_source` is `DEPICTED_OBJECTION`, the linked depicted individual moves `OBJECTED → OBJECTION_SUSTAINED`, which is terminal and removes them from the request's `open_notification_count`."

    Design: Corner/state_machines/objection_sustained_clears_the_notification_counter
    """
    scenario = _objecting_victim(api)

    adjudicate(
        api,
        scenario["claim_id"],
        scenario["counsel_id"],
        "SUSTAINED",
        adjudication_note="Victim protection applies",
    )

    assert_fields(
        get_claim(api, scenario["claim_id"]),
        status="SUSTAINED",
        adjudicated_by_staff_id=scenario["counsel_id"],
    )
    assert (
        get_individual(api, scenario["individual_id"])["notification_status"]
        == "OBJECTION_SUSTAINED"
    )
    assert_fields(
        get_request(api, scenario["request_id"]),
        open_notification_count=0,
        unadjudicated_claim_count=0,
    )


def test_the_derived_claim_is_weighted_like_any_partial_redaction(api):
    """Twenty whole minutes at the victim-protection partial weight freeze twelve minutes of work.

    PRD: "The claim's `estimated_redaction_minutes` is frozen by the same weighting rule as a staff-asserted claim, using the derived code's partial-redaction weight."

    Design: Corner/state_machines/objection_sustained_clears_the_notification_counter
    """
    scenario = _objecting_victim(api)
    assert scenario["claim"]["estimated_redaction_minutes"] == 12

    adjudicate(
        api,
        scenario["claim_id"],
        scenario["counsel_id"],
        "SUSTAINED",
        adjudication_note="Victim protection applies",
    )

    assert get_claim(api, scenario["claim_id"])["estimated_redaction_minutes"] == 12
    assert_fields(
        get_record(api, scenario["record_id"]),
        release_posture="RESTRICTED",
        presumptive_burden_minutes=17,
        adjudicated_burden_minutes=17,
    )
    assert get_request(api, scenario["request_id"])["processing_status"] == "REDACTION"
