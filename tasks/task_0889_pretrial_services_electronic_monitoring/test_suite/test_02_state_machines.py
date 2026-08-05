"""State-machine transitions: invalid transitions, terminal lockdown, valid transitions,
time-gated preconditions, cyclic enrollment, cascades.

Translates SCAFFOLD_CORNER_DESIGN.yaml section `state_machines`.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, make_intake_headers, make_judicial_headers,
    create_defendant, create_draft_assessment, create_approved_assessment,
    create_release_order_payload, create_check_in_payload, create_court_event_payload,
    setup_active_enrollment, activate_defendant, api_client,
)

INTAKE = TEST_USERS["intake_headers"]
SUPERVISING = TEST_USERS["supervising_headers"]
JUDICIAL = TEST_USERS["judicial_headers"]
ADMIN = TEST_USERS["admin_headers"]


def test_approve_draft_assessment_skipping_submitted_rejected(api):
    """PRD §3.1: "Any transition attempted from a status that does not permit it is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/assessment_invalid_transition_draft_to_approved
    """
    defendant = create_defendant()
    assessment = create_draft_assessment(defendant["id"])
    resp = api.transition_assessment(assessment["id"], "APPROVED", JUDICIAL)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_terminal_approved_assessment_cannot_be_rejected(api):
    """PRD §3.1: "Any transition attempted from a status that does not permit it is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/assessment_terminal_lockdown_rejected
    """
    defendant = create_defendant()
    assessment = create_approved_assessment(defendant["id"])
    assert assessment["status"] == "APPROVED"
    resp = api.transition_assessment(assessment["id"], "REJECTED", JUDICIAL)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_complete_checkin_stamps_completed_at(api):
    """PRD §3.4: "It requires the check-in to be in `SCHEDULED`, and on success stamps
    `completed_at` with the current clock."

    Design: Corner/state_machines/checkin_complete_sets_completed_at
    """
    defendant = create_defendant()
    ci = validate_success(
        api.create_check_in(create_check_in_payload(defendant["id"]), SUPERVISING), 201)
    data = validate_success(api.transition_check_in(ci["id"], "COMPLETED", SUPERVISING), 200)
    assert data["status"] == "COMPLETED"
    assert data["completed_at"] is not None, "completed_at must be stamped on completion"


def test_mark_checkin_missed_before_due_time_not_reached(api):
    """PRD §3.4: "Marking missed ... requires the current clock to be strictly after
    `due_at` (otherwise `ERR_PRECONDITION_TIME_NOT_REACHED`)."

    Design: Corner/state_machines/checkin_mark_missed_before_due_time_not_reached
    """
    defendant = create_defendant()
    ci = validate_success(api.create_check_in(
        create_check_in_payload(defendant["id"], due_at="2026-06-10T12:00:00Z"),
        SUPERVISING), 201)
    resp = api.transition_check_in(ci["id"], "MISSED", SUPERVISING)
    validate_error(resp, ApiErrorId.ERR_PRECONDITION_TIME_NOT_REACHED, 409)


def test_mark_courtevent_fta_before_grace_time_not_reached(api):
    """PRD §3.6: "Recording a **failure-to-appear** ... requires the current clock to be
    strictly after the hearing instant plus a failure-to-appear grace period of 2 hours;
    before that grace period elapses the transition is rejected with
    `ERR_PRECONDITION_TIME_NOT_REACHED`."

    Design: Corner/state_machines/courtevent_fta_before_grace_time_not_reached
    """
    defendant = create_defendant()
    ce = validate_success(api.create_court_event(
        create_court_event_payload(defendant["id"], hearing_at="2026-06-20T09:00:00Z"),
        SUPERVISING), 201)
    resp = api.transition_court_event(ce["id"], "FTA", SUPERVISING)
    validate_error(resp, ApiErrorId.ERR_PRECONDITION_TIME_NOT_REACHED, 409)


def test_enrollment_suspend_resume_keeps_unit_assigned(api):
    """PRD §3.5: "**Suspension** (`ACTIVE → SUSPENDED`) ... leaves the assigned unit in
    place. **Resumption** (`SUSPENDED → ACTIVE`) ... assigns no new unit."
    PRD §2.11: "a suspended enrollment continues to hold its unit."

    Design: Corner/state_machines/em_suspend_resume_cycle_keeps_unit_assigned
    """
    ctx = setup_active_enrollment(ordered_conditions=["GPS_MONITORING"], total_units=1)
    enr_id, dev_id = ctx["enrollment"]["id"], ctx["device"]["id"]
    validate_success(api.transition_em_enrollment(enr_id, "SUSPENDED", SUPERVISING), 200)
    resumed = validate_success(
        api.transition_em_enrollment(enr_id, "ACTIVE", SUPERVISING), 200)
    assert resumed["status"] == "ACTIVE"
    device = validate_success(api.get_em_device(dev_id, SUPERVISING), 200)
    assert device["available_units"] == 0, "unit stays assigned across suspend/resume"


def test_positive_drug_result_cascades_violation(api):
    """PRD §3.8: "Recording a **positive result** ... cascades the automatic creation of a
    `ViolationEvent` with `violation_type` `POSITIVE_TEST` and `severity` `MODERATE`, in
    `REPORTED` status, recording the drug test's `id` as its `source_ref`."

    Design: Corner/state_machines/drugtest_positive_cascades_violation
    """
    from test_helpers import setup_drug_testing_defendant, schedule_drug_test
    ctx = setup_drug_testing_defendant(slot_capacity=5)
    def_id = ctx["defendant"]["id"]
    dt = schedule_drug_test(def_id, ctx["site"]["id"], slot_start="2026-06-05T10:00:00Z")
    validate_success(api.transition_drug_test(dt["id"], "COLLECTED", SUPERVISING), 200)
    result = validate_success(
        api.transition_drug_test(dt["id"], "RESULT_POSITIVE", SUPERVISING), 200)
    assert result["status"] == "RESULT_POSITIVE"

    data, _ = _list(api.list_defendant_violations(def_id, JUDICIAL))
    match = [v for v in data
             if v["violation_type"] == "POSITIVE_TEST" and v["status"] == "REPORTED"
             and v["source_ref"] == dt["id"]]
    assert len(match) >= 1, "a POSITIVE_TEST violation must be auto-created referencing the test"


def test_denied_release_order_cannot_be_vacated(api):
    """PRD §3.3: "`DENIED` and `VACATED` are terminal." plus §3.1-style state legality:
    "Any transition attempted from a status that does not permit it is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/release_order_denied_then_vacate_invalid_state
    """
    defendant = create_defendant()
    assessment = create_approved_assessment(defendant["id"])
    order = validate_success(api.create_release_order(
        create_release_order_payload(defendant["id"], assessment["id"],
                                     decision="DETAIN", ordered_conditions=[]),
        JUDICIAL), 201)
    validate_success(api.transition_release_order(order["id"], "DENIED", JUDICIAL), 200)
    resp = api.transition_release_order(order["id"], "VACATED", JUDICIAL)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def _list(response):
    from test_helpers import validate_paginated
    return validate_paginated(response)
