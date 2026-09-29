"""Initial states, valid transitions, refused transitions and terminal lockdown."""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    AssessmentStatus,
    CaseloadStatus,
    ComplianceStatus,
    ConsentEventType,
    ExclusionStatus,
    MeetingStatus,
    OrderStatus,
    PsychologistStatus,
    ReferralStatus,
    api_client,
    assert_evaluation,
    assert_protocol_order,
    assert_timeline_exclusion,
    consent_event_payload,
    decision_payload,
    fixtures,
    make_school_psychologist_headers,
    report_draft_payload,
    scores_payload,
    start_testing_payload,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["district_admin_headers"]
SUPERVISOR = TEST_USERS["psych_services_supervisor_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]


def test_a_consent_event_mints_an_evaluation_at_both_initial_states():
    """The new evaluation opens PENDING_ASSIGNMENT and ON_TRACK with a fresh clock.

    "It then creates exactly one evaluation: `referral_id` pointing back at the referral, `assessment_status` `PENDING_ASSIGNMENT`, `compliance_status` `ON_TRACK`, `clock_start_date` set to the UTC calendar date of `effective_at` — day zero of the statutory clock — and `evaluation_domains`, `interpreter_required` and `referral_type` all copied from the referral, along with `prior_evaluation_id` copied from the referral's own."

    Design: Corner/state_machines/consent_event_creates_evaluation_in_initial_states
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Larchmont Elementary",
        building_code="LM31",
        grade_band="ELEMENTARY",
        concurrent_meeting_capacity=2,
        enrollment_count=410,
    )
    referral, evaluation = fixtures.consented_referral(
        school["id"],
        student_local_id="STU-12",
        requested_domains=["COGNITIVE", "ACADEMIC"],
    )

    assert referral["status"] == ReferralStatus.CONSENTED.value
    assert referral["consent_received_at"].startswith("2026-08-01")
    assert referral["last_consent_event_type"] == ConsentEventType.CONSENT_RECEIVED.value
    assert referral["parent_signature_reference"] == "SIG-1"

    assert_evaluation(evaluation)
    assert evaluation["assessment_status"] == AssessmentStatus.PENDING_ASSIGNMENT.value
    assert evaluation["compliance_status"] == ComplianceStatus.ON_TRACK.value
    assert evaluation["clock_start_date"] == "2026-08-01"
    assert evaluation["base_due_date"] == "2026-09-30"
    assert evaluation["statutory_due_date"] == "2026-09-30"
    assert evaluation["credited_exclusion_days"] == 0
    assert evaluation["elapsed_statutory_days"] == 0
    assert evaluation["days_remaining"] == 60
    # 3 base + 1 extra domain + 0 interpreter + 2 for an INITIAL evaluation.
    assert evaluation["caseload_points"] == 6
    assert evaluation["psychologist_id"] is None
    assert evaluation["reassignment_count"] == 0
    assert evaluation["protocol_units_consumed"] == 0
    assert evaluation["version"] == 1


def test_an_order_above_the_threshold_needs_approval_before_receipt_credits_stock():
    """The manual branch runs SUBMITTED to APPROVED to RECEIVED, then the shelf moves.

    "A valid receipt moves the order `APPROVED → RECEIVED`, stores `received_quantity`, and credits the instrument's `protocol_stock_count` by exactly that number."

    Design: Corner/state_machines/protocol_order_approve_then_receive_credits_stock
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    instrument = fixtures.create_instrument(
        name="WIAT-4",
        instrument_code="WIAT4",
        protocol_stock_count=0,
        protocol_units_per_administration=1,
        protocol_unit_cost_cents=1799,
        license_seat_total=1,
        license_expires_on="2027-06-30",
        supported_language_editions=["en"],
    )
    order = fixtures.order_protocols(instrument["id"], 30, rush_flag=False)

    assert_protocol_order(order)
    assert order["total_cost_cents"] == 47681
    assert order["auto_approved"] is False
    assert order["status"] == OrderStatus.SUBMITTED.value

    approved = fixtures.decide_order(order["id"], "APPROVE")
    assert approved["status"] == OrderStatus.APPROVED.value
    assert approved["decided_by_user_id"] == ADMIN["X-User-ID"]

    received = fixtures.receive_order(order["id"], 30)

    assert_protocol_order(received)
    assert received["status"] == OrderStatus.RECEIVED.value
    assert received["received_quantity"] == 30
    assert fixtures.get_instrument(instrument["id"])["protocol_stock_count"] == 30

    rows, _ = validate_paginated(
        api_client.list_instrument_protocol_orders(instrument["id"], SUPERVISOR)
    )
    assert [row["status"] for row in rows] == [OrderStatus.RECEIVED.value]


def test_testing_cannot_start_on_an_interpreter_case_with_no_session_booked():
    """Every other gate is satisfied, so the interpreter gate is the one that reports.

    "The interpreter gate comes second: when the evaluation's `interpreter_required` flag is true, at least one interpreter session of that evaluation must already exist in `SCHEDULED` or `COMPLETED` status, otherwise the request is rejected with `ERR_INTERPRETER_SESSION_MISSING`."

    Design: Corner/state_machines/testing_start_without_interpreter_session_rejected
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Moreland Middle",
        building_code="ML32",
        grade_band="MIDDLE",
        concurrent_meeting_capacity=2,
        enrollment_count=540,
    )
    psychologist = fixtures.create_psychologist(
        [school["id"]],
        full_name="Yara Bell",
        employee_number="E-2006",
        credential_type="SSP",
    )
    instrument = fixtures.create_instrument(
        name="CELF-5",
        instrument_code="CELF5",
        protocol_stock_count=4,
        protocol_units_per_administration=1,
        protocol_unit_cost_cents=1400,
        license_seat_total=1,
        license_expires_on="2027-06-30",
        supported_language_editions=["en", "es"],
    )
    fixtures.assign_license_seat(instrument["id"], psychologist["id"], ADMIN)
    _, evaluation = fixtures.consented_referral(
        school["id"],
        student_local_id="STU-13",
        primary_language="es",
        interpreter_required=True,
        requested_domains=["ACADEMIC"],
    )
    fixtures.assign_evaluator(evaluation["id"], psychologist["id"])

    owner_headers = make_school_psychologist_headers(psychologist["id"])
    refused = api_client.start_testing(
        evaluation["id"], start_testing_payload(instrument["id"]), owner_headers
    )

    validate_error(refused, ApiErrorId.ERR_INTERPRETER_SESSION_MISSING.value, 409)
    unchanged = fixtures.get_evaluation(evaluation["id"])
    assert unchanged["assessment_status"] == AssessmentStatus.ASSIGNED.value
    assert unchanged["testing_instrument_id"] is None
    assert unchanged["protocol_units_consumed"] == 0
    assert fixtures.get_instrument(instrument["id"])["protocol_stock_count"] == 4

    fixtures.book_session(
        evaluation["id"], "2026-09-10T09:00:00Z", "2026-09-10T10:00:00Z"
    )
    accepted = api_client.start_testing(
        evaluation["id"], start_testing_payload(instrument["id"]), owner_headers
    )

    in_testing = validate_success(accepted)
    assert in_testing["assessment_status"] == AssessmentStatus.IN_TESTING.value
    assert fixtures.get_instrument(instrument["id"])["protocol_stock_count"] == 3


def test_scores_and_drafts_are_unreachable_from_the_assigned_posture():
    """The rightful owner still cannot skip testing to score or draft.

    "Both steps are restricted to the evaluation's own `psychologist_id` and both require consent still on file; performing either from the wrong assessment posture is rejected with `ERR_EVALUATION_STATE_INVALID`."

    Design: Corner/state_machines/scores_from_assigned_state_rejected
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Norwood Elementary",
        building_code="NW33",
        grade_band="ELEMENTARY",
        concurrent_meeting_capacity=2,
        enrollment_count=360,
    )
    psychologist = fixtures.create_psychologist(
        [school["id"]],
        full_name="Zev Rios",
        employee_number="E-2007",
        credential_type="SSP",
    )
    _, evaluation = fixtures.consented_referral(
        school["id"], student_local_id="STU-14", requested_domains=["COGNITIVE"]
    )
    fixtures.assign_evaluator(evaluation["id"], psychologist["id"])
    owner_headers = make_school_psychologist_headers(psychologist["id"])

    validate_error(
        api_client.record_scores(
            evaluation["id"], scores_payload("premature scores"), owner_headers
        ),
        ApiErrorId.ERR_EVALUATION_STATE_INVALID.value,
        409,
    )
    validate_error(
        api_client.submit_report_draft(
            evaluation["id"], report_draft_payload("premature draft"), owner_headers
        ),
        ApiErrorId.ERR_EVALUATION_STATE_INVALID.value,
        409,
    )

    unchanged = fixtures.get_evaluation(evaluation["id"])
    assert unchanged["assessment_status"] == AssessmentStatus.ASSIGNED.value
    assert unchanged["score_summary"] is None
    assert unchanged["report_narrative"] is None
    assert fixtures.get_psychologist(psychologist["id"])["open_case_points"] == 5


def test_an_approved_exclusion_cannot_be_decided_a_second_time():
    """The opposite decision is refused and the credited days are neither doubled nor reversed.

    "A decision against a claim that has already been decided — one already `APPROVED` or `REJECTED`, both of which are terminal — is rejected with `ERR_EXCLUSION_ALREADY_DECIDED`."

    Design: Corner/state_machines/decided_exclusion_cannot_be_decided_again
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Oakmont Middle",
        building_code="OM34",
        grade_band="MIDDLE",
        concurrent_meeting_capacity=2,
        enrollment_count=590,
    )
    psychologist = fixtures.create_psychologist(
        [school["id"]],
        full_name="Ada Nkemelu",
        employee_number="E-2008",
        credential_type="SSP",
    )
    _, evaluation = fixtures.consented_referral(
        school["id"], student_local_id="STU-15", requested_domains=["COGNITIVE"]
    )
    fixtures.assign_evaluator(evaluation["id"], psychologist["id"])
    approved = fixtures.approved_exclusion(
        evaluation["id"],
        psychologist["id"],
        "BREAK_CLOSURE",
        "2026-08-10",
        "2026-08-24",
        claim_note="District summer closure",
    )

    assert_timeline_exclusion(approved)
    assert approved["status"] == ExclusionStatus.APPROVED.value
    assert approved["days_credited"] == 14

    response = api_client.decide_timeline_exclusion(
        approved["id"], decision_payload("REJECT"), SUPERVISOR
    )

    validate_error(response, ApiErrorId.ERR_EXCLUSION_ALREADY_DECIDED.value, 409)
    still_approved = fixtures.evaluation_exclusions(evaluation["id"])[0]
    assert still_approved["status"] == ExclusionStatus.APPROVED.value
    assert still_approved["days_credited"] == 14
    assert still_approved["decided_at"] == approved["decided_at"]

    after = fixtures.get_evaluation(evaluation["id"])
    assert after["credited_exclusion_days"] == 14
    assert after["statutory_due_date"] == "2026-10-14"


def test_a_second_leave_is_refused_without_replaying_the_cascade():
    """The replayed trigger fails on state, so the reassignment count stays at one.

    "A `DistrictAdmin` may place an `ACTIVE` psychologist on leave, moving `status` from `ACTIVE` to `ON_LEAVE`; attempting it on someone already `ON_LEAVE` is rejected with `ERR_PSYCHOLOGIST_STATE_INVALID`."

    Design: Corner/state_machines/second_leave_on_psychologist_rejected_without_recascade
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Pemberton High",
        building_code="PB35",
        grade_band="HIGH",
        concurrent_meeting_capacity=2,
        enrollment_count=780,
    )
    psychologist = fixtures.create_psychologist(
        [school["id"]],
        full_name="Bo Frayne",
        employee_number="E-2009",
        credential_type="SSP",
    )
    _, evaluation = fixtures.consented_referral(
        school["id"], student_local_id="STU-16", requested_domains=["COGNITIVE"]
    )
    fixtures.assign_evaluator(evaluation["id"], psychologist["id"])
    fixtures.place_on_leave(psychologist["id"])

    response = api_client.place_psychologist_on_leave(psychologist["id"], ADMIN)

    validate_error(response, ApiErrorId.ERR_PSYCHOLOGIST_STATE_INVALID.value, 409)
    still_on_leave = fixtures.get_psychologist(psychologist["id"])
    assert still_on_leave["status"] == PsychologistStatus.ON_LEAVE.value
    assert still_on_leave["open_case_points"] == 0

    after = fixtures.get_evaluation(evaluation["id"])
    assert after["reassignment_count"] == 1
    assert after["assessment_status"] == AssessmentStatus.PENDING_ASSIGNMENT.value
    assert after["psychologist_id"] is None


def test_a_replayed_consent_received_event_mints_no_second_evaluation():
    """The transition is only valid from INTAKE_RECEIVED and the linkage never moves.

    "A consent event that the referral's current status does not permit — a second `CONSENT_RECEIVED`, or any event at all once the referral has reached `CONSENT_WITHDRAWN` or `COMPLETED`, both of which are terminal — is rejected with `ERR_REFERRAL_STATE_INVALID`."

    Design: Corner/state_machines/duplicate_consent_received_event_rejected
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Quarry Ridge Middle",
        building_code="QR36",
        grade_band="MIDDLE",
        concurrent_meeting_capacity=2,
        enrollment_count=500,
    )
    referral, evaluation = fixtures.consented_referral(
        school["id"], student_local_id="STU-17", requested_domains=["COGNITIVE"]
    )

    response = api_client.create_consent_event(
        referral["id"],
        consent_event_payload(
            event_type="CONSENT_RECEIVED",
            effective_at="2026-08-01T00:00:00Z",
            parent_signature_reference="SIG-17-DUP",
        ),
        INTAKE,
    )

    validate_error(response, ApiErrorId.ERR_REFERRAL_STATE_INVALID.value, 409)
    unchanged = fixtures.get_referral(referral["id"])
    assert unchanged["consent_received_at"] == referral["consent_received_at"]
    assert unchanged["parent_signature_reference"] == referral["parent_signature_reference"]
    assert unchanged["active_evaluation_id"] == evaluation["id"]

    _, meta = validate_paginated(
        api_client.list_evaluations(SUPERVISOR, {"referral_id": referral["id"]})
    )
    assert meta["total_count"] == 1


def test_a_returned_review_clears_the_draft_and_reopens_the_revision_cycle():
    """RETURN wipes both draft fields, keeps the scores, and the cycle can repeat.

    "A `RETURN` decision sends the draft back — `REPORT_DRAFTED → SCORED` — and clears both `report_narrative` and `report_drafted_by_psychologist_id`, because the draft must be re-authored from scratch."

    Design: Corner/state_machines/report_review_return_clears_draft_and_cycles_to_scored
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    context = fixtures.drafted_evaluation(
        report_narrative="First draft, missing observation section.",
        score_summary="WRAT-5 word reading 82",
        school_overrides={
            "name": "Rockvale Elementary",
            "building_code": "RV37",
            "grade_band": "ELEMENTARY",
            "concurrent_meeting_capacity": 2,
            "enrollment_count": 420,
        },
        psychologist_overrides={
            "full_name": "Cleo Hart",
            "employee_number": "E-2010",
            "credential_type": "SSP",
        },
        referral_overrides={
            "student_local_id": "STU-18",
            "requested_domains": ["ACADEMIC"],
        },
        instrument_overrides={
            "name": "WRAT-5",
            "instrument_code": "WRAT5",
            "protocol_stock_count": 4,
            "protocol_unit_cost_cents": 1300,
            "license_seat_total": 1,
        },
    )
    author = context["psychologist"]
    reviewer = fixtures.create_psychologist(
        [context["school"]["id"]],
        full_name="Dev Rao",
        employee_number="E-2011",
        credential_type="PHD",
    )
    drafted = context["evaluation"]
    assert drafted["assessment_status"] == AssessmentStatus.REPORT_DRAFTED.value
    assert drafted["report_drafted_by_psychologist_id"] == author["id"]

    returned = fixtures.review_report(
        context["evaluation"]["id"], "RETURN", reviewer_psychologist_id=reviewer["id"]
    )

    assert_evaluation(returned)
    assert returned["assessment_status"] == AssessmentStatus.SCORED.value
    assert returned["report_narrative"] is None
    assert returned["report_drafted_by_psychologist_id"] is None
    # Only the draft is cleared; the scores survive the return.
    assert returned["score_summary"] == "WRAT-5 word reading 82"

    author_now = fixtures.get_psychologist(author["id"])
    assert author_now["open_case_points"] == 5
    assert author_now["caseload_status"] == CaseloadStatus.BALANCED.value

    # The SCORED -> REPORT_DRAFTED -> SCORED cycle repeats without limit.
    again = fixtures.submit_report_draft(
        context["evaluation"]["id"], author["id"], "Second draft, observation added."
    )
    assert again["assessment_status"] == AssessmentStatus.REPORT_DRAFTED.value
    # A revision cycle never re-consumes protocol booklets.
    assert fixtures.get_instrument(context["instrument"]["id"])["protocol_stock_count"] == 3


def test_holding_the_meeting_closes_the_clock_and_completes_the_referral():
    """One call moves the meeting, the evaluation's posture and the referral.

    "If the evaluation's `days_remaining` is zero or greater at that moment, its `compliance_status` moves to the terminal `COMPLIANT_CLOSED` — from either `ON_TRACK` or `AT_RISK`."

    Design: Corner/state_machines/meeting_hold_closes_compliance_and_completes_referral
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    context = fixtures.final_report_evaluation(
        school_overrides={
            "name": "Stonebridge Middle",
            "building_code": "SB38",
            "grade_band": "MIDDLE",
            "concurrent_meeting_capacity": 2,
            "enrollment_count": 620,
        },
        psychologist_overrides={
            "full_name": "Esme Cole",
            "employee_number": "E-2012",
            "credential_type": "SSP",
        },
        referral_overrides={
            "student_local_id": "STU-19",
            "requested_domains": ["COGNITIVE"],
        },
        instrument_overrides={
            "name": "KABC-II",
            "instrument_code": "KABC2",
            "protocol_stock_count": 4,
            "protocol_unit_cost_cents": 1550,
            "license_seat_total": 1,
        },
    )
    evaluation_id = context["evaluation"]["id"]
    meeting = fixtures.create_meeting(
        evaluation_id,
        context["school"]["id"],
        "2026-09-20T15:00:00Z",
        "2026-09-20T16:00:00Z",
    )
    fixtures.set_clock("2026-09-10T00:00:00Z")
    meeting = fixtures.send_notice(meeting["id"])
    fixtures.set_clock("2026-09-20T15:00:00Z")

    before = fixtures.get_evaluation(evaluation_id)
    assert before["assessment_status"] == AssessmentStatus.REPORT_FINAL.value
    assert before["compliance_status"] == ComplianceStatus.ON_TRACK.value
    assert before["days_remaining"] == 10
    assert meeting["status"] == MeetingStatus.NOTICED.value
    assert meeting["notice_lead_days"] == 10

    held = fixtures.hold_meeting(meeting["id"])

    assert held["status"] == MeetingStatus.HELD.value
    assert held["held_at"].startswith("2026-09-20T15:00")

    closed = fixtures.get_evaluation(evaluation_id)
    assert closed["compliance_status"] == ComplianceStatus.COMPLIANT_CLOSED.value
    assert (
        fixtures.get_referral(context["referral"]["id"])["status"]
        == ReferralStatus.COMPLETED.value
    )
    author = fixtures.get_psychologist(context["psychologist"]["id"])
    assert author["open_case_points"] == 0
    assert author["pressure_index_clock_weighted"] == 0.00

    # COMPLETED is terminal on the consent stream.
    validate_error(
        api_client.create_consent_event(
            context["referral"]["id"],
            consent_event_payload(
                event_type="CONSENT_WITHDRAWN", effective_at="2026-09-20T15:00:00Z"
            ),
            INTAKE,
        ),
        ApiErrorId.ERR_REFERRAL_STATE_INVALID.value,
        409,
    )
