"""Case investigation: assignment workload, the QA return cycle, SAR-decision
gating, LE-inquiry hold, segregation of duties (PRD §3.4, §3.7)."""
from test_helpers import (
    ApiErrorId,
    assert_case,
    assert_same_instant,
    assign_case,
    assign_case_payload,
    create_case,
    create_customer,
    create_le_inquiry,
    create_sar_payload,
    create_staff,
    drive_case_to_closed_no_sar,
    drive_case_to_investigating,
    drive_case_to_pending_qa,
    drive_case_to_sar_in_progress,
    link_inquiry_to_case,
    make_qa_reviewer_headers,
    qa_review_case,
    record_sar_decision,
    respond_and_close_inquiry,
    sar_decision_payload,
    start_investigation,
    validate_error,
    validate_success,
)


def test_assignment_moves_workload_counters(api):
    """PRD §3.4: "Assignment stamps `assigned_analyst_id`, increments that
    analyst's open-case counter, and bumps the case `version`."
    PRD §3.4: "Reassignment follows the same path — whether from `ASSIGNED` or
    from `INVESTIGATING` — and requires a different `analyst_id` than the
    current assignee; it decrements the prior analyst's counter, increments the
    new analyst's counter, returns the case to `ASSIGNED` (restarting the
    investigation), and bumps the version."

    Design: Difficulty/compensating_invariant/analyst_assignment_workload_conservation
    """
    staff = create_staff(analyst_capacity=5)
    bob = validate_success(api.create_analyst(
        {"full_name": "Bob Backup", "capacity_max_cases": 5}, staff.admin), 201)
    case1 = create_case(staff, create_customer(staff)["id"])
    case2 = create_case(staff, create_customer(staff)["id"])

    assign_case(staff, case1["id"])
    assign_case(staff, case2["id"])
    analyst = validate_success(api.get_analyst(staff.analyst_id, staff.manager), 200)
    assert analyst["assigned_open_cases"] == 2, "two open cases assigned to A"

    reassign = validate_success(api.assign_case(
        case1["id"], assign_case_payload(bob["id"]), staff.manager), 200)
    assert reassign["assigned_analyst_id"] == bob["id"]
    analyst = validate_success(api.get_analyst(staff.analyst_id, staff.manager), 200)
    backup = validate_success(api.get_analyst(bob["id"], staff.manager), 200)
    assert analyst["assigned_open_cases"] == 1, "reassignment decrements the prior analyst"
    assert backup["assigned_open_cases"] == 1, "and increments the new analyst"
    assert analyst["assigned_open_cases"] + backup["assigned_open_cases"] == 2, (
        "the total across analysts is conserved by the move"
    )


def test_closing_case_decrements_workload_total(api):
    """PRD §3.4: "On close, `closed_reason` is `NO_SAR_CONFIRMED` when the
    decision was `NO_SAR` and `SAR_FILED` when a SAR was filed, `closed_at` is
    set, the assigned analyst's open-case counter decrements by 1, and the
    version increments."

    Design: Difficulty/compensating_invariant/analyst_assignment_workload_conservation
    """
    staff = create_staff(analyst_capacity=5)
    bob = validate_success(api.create_analyst(
        {"full_name": "Bob Backup", "capacity_max_cases": 5}, staff.admin), 201)
    customer = create_customer(staff)
    case1 = create_case(staff, customer["id"])
    case2 = create_case(staff, customer["id"])
    assign_case(staff, case1["id"])
    assign_case(staff, case2["id"])
    validate_success(api.assign_case(
        case1["id"], assign_case_payload(bob["id"]), staff.manager), 200)

    case2 = start_investigation(staff, case2["id"])
    case2 = record_sar_decision(staff, case2, "NO_SAR",
                                rationale="Documented legitimate activity")
    closed = qa_review_case(staff, case2["id"], "PASS")
    assert_case(closed)
    assert closed["status"] == "CLOSED"
    assert closed["closed_reason"] == "NO_SAR_CONFIRMED"

    analyst = validate_success(api.get_analyst(staff.analyst_id, staff.manager), 200)
    backup = validate_success(api.get_analyst(bob["id"], staff.manager), 200)
    assert analyst["assigned_open_cases"] == 0, "close decremented A exactly once"
    assert backup["assigned_open_cases"] == 1, "the single remaining open case k1"
    assert analyst["assigned_open_cases"] + backup["assigned_open_cases"] == 1


def test_case_qa_fail_returns_to_investigating_and_preserves_decision(api):
    """PRD §3.4: "An `outcome` of `FAIL` sends the case back to `INVESTIGATING`
    and stamps `qa_reviewed_by`."
    PRD §3.4: "On `SAR_REQUIRED` the case transitions to `SAR_IN_PROGRESS`; on
    `NO_SAR` it transitions to `PENDING_QA`."

    The case machine is cyclic: after the FAIL revert the case traverses
    INVESTIGATING -> PENDING_QA a second time, and the recorded NO_SAR decision
    survives the revert.

    Design: Difficulty/non_linear_state_machine/case_qa_return_cycle
    """
    staff = create_staff()
    case = drive_case_to_investigating(staff, create_customer(staff)["id"])
    case = record_sar_decision(staff, case, "NO_SAR",
                               rationale="Legitimate business activity documented")
    assert case["status"] == "PENDING_QA"

    failed = validate_success(api.review_case_qa(
        case["id"], {"outcome": "FAIL",
                     "notes": "Rationale does not address the cash pattern"},
        staff.qa), 200)
    assert failed["status"] == "INVESTIGATING", "PENDING_QA -> INVESTIGATING on FAIL"
    assert failed["decision"] == "NO_SAR", "the revert does not reset the decision"
    assert failed["qa_reviewed_by"] == staff.qa_id

    case2 = record_sar_decision(staff, failed, "NO_SAR",
                                rationale="Reworked: added payroll records analysis")
    assert case2["status"] == "PENDING_QA", "loop iteration 2 reaches PENDING_QA"
    closed = qa_review_case(staff, case2["id"], "PASS", notes="Adequate after rework")
    assert closed["status"] == "CLOSED"
    assert closed["closed_reason"] == "NO_SAR_CONFIRMED"
    assert closed["decision"] == "NO_SAR"
    assert closed["closed_at"] is not None


def test_case_close_after_rework_decrements_counter_once(api):
    """PRD §3.4: "On close, `closed_reason` is `NO_SAR_CONFIRMED` when the
    decision was `NO_SAR` and `SAR_FILED` when a SAR was filed, `closed_at` is
    set, the assigned analyst's open-case counter decrements by 1, and the
    version increments."

    Two traversals through PENDING_QA still produce exactly one decrement, at
    the final close.

    Design: Difficulty/non_linear_state_machine/case_qa_return_cycle
    """
    staff = create_staff()
    case = drive_case_to_investigating(staff, create_customer(staff)["id"])
    case = record_sar_decision(staff, case, "NO_SAR")
    failed = validate_success(api.review_case_qa(
        case["id"], {"outcome": "FAIL"}, staff.qa), 200)
    mid = validate_success(api.get_analyst(staff.analyst_id, staff.manager), 200)
    assert mid["assigned_open_cases"] == 1, "the FAIL revert is not a close"

    case = record_sar_decision(staff, failed, "NO_SAR")
    qa_review_case(staff, case["id"], "PASS")
    end = validate_success(api.get_analyst(staff.analyst_id, staff.manager), 200)
    assert end["assigned_open_cases"] == 0, "decremented exactly once, at close"


def test_sar_create_rejected_while_case_investigating(api):
    """PRD §3.5: "Once a case reaches `SAR_IN_PROGRESS`, the assigned analyst
    creates the initial SAR draft under the case, supplying the
    `activity_start_date` and `activity_end_date` of the suspicious activity
    window and an optional `subject_unidentified` flag."
    PRD §2.10: "then state-machine legality (`ERR_INVALID_STATE`)".

    Design: Difficulty/cross_entity_state_dependency/sar_create_gated_by_case_state
    """
    staff = create_staff()
    case = drive_case_to_investigating(staff, create_customer(staff)["id"])
    assert case["status"] == "INVESTIGATING"
    assert case["decision"] == "NONE"

    res = api.create_sar_report(case["id"], create_sar_payload(), staff.analyst)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert res.status_code == 409, (
        "the SARReport transition is gated by the parent case's state"
    )


def test_sar_create_succeeds_once_case_sar_in_progress(api):
    """PRD §3.5: "Once a case reaches `SAR_IN_PROGRESS`, the assigned analyst
    creates the initial SAR draft under the case".
    PRD §2.8: "For an initial SAR (one with no `prior_sar_id`), the deadline
    starts from the parent case's `initial_detection_at` — the `created_at` of
    the earliest alert linked to the case, or the case's own `created_at` if no
    alert is linked — and adds 30 days."

    The case was created at the default clock 2026-05-01 with no linked alerts,
    so the draft's deadline is 2026-05-31T00:00:00Z.

    Design: Difficulty/cross_entity_state_dependency/sar_create_gated_by_case_state
    """
    staff = create_staff()
    case = drive_case_to_sar_in_progress(staff, create_customer(staff)["id"])
    assert case["status"] == "SAR_IN_PROGRESS"

    sar = validate_success(api.create_sar_report(
        case["id"], create_sar_payload(), staff.analyst), 201)
    assert sar["status"] == "DRAFT"
    assert_same_instant(sar["deadline_at"], "2026-05-31T00:00:00Z")


def test_case_created_open_with_no_decision(api):
    """PRD §3.4: "The case starts in `OPEN` with `decision` `NONE`."
    PRD §2.4: "an integer `version` that starts at 1 and increments by exactly
    1 on every mutation."

    Design: Corner/state_machines/case_created_initial_state_open
    """
    staff = create_staff()
    case = create_case(staff, create_customer(staff)["id"])
    assert_case(case)
    assert case["status"] == "OPEN"
    assert case["decision"] == "NONE"
    assert case["assigned_analyst_id"] is None
    assert case["version"] == 1


def test_assign_beyond_capacity_rejected(api):
    """PRD §3.4: "the assignment is rejected with `ERR_ANALYST_AT_CAPACITY`
    when the target analyst's `assigned_open_cases` is already at
    `capacity_max_cases` (the rule is strictly below)."

    Design: Corner/errors/analyst_capacity_exceeded_rejected
    """
    staff = create_staff(analyst_capacity=1)
    customer = create_customer(staff)
    case1 = create_case(staff, customer["id"], as_manager=True)
    case2 = create_case(staff, customer["id"], as_manager=True)
    assign_case(staff, case1["id"])

    res = api.assign_case(case2["id"], assign_case_payload(staff.analyst_id),
                          staff.manager)
    validate_error(res, ApiErrorId.ERR_ANALYST_AT_CAPACITY)
    assert res.status_code == 409
    case2_after = validate_success(api.get_case(case2["id"], staff.manager), 200)
    assert case2_after["status"] == "OPEN"
    assert case2_after["assigned_analyst_id"] is None
    analyst = validate_success(api.get_analyst(staff.analyst_id, staff.manager), 200)
    assert analyst["assigned_open_cases"] == 1, "no partial mutation"


def test_sar_decision_on_closed_case_rejected(api):
    """PRD §3.4: "`CLOSED` is not terminal for a case: a continuing review that
    concludes `FILE_CONTINUING_SAR` reopens it into `SAR_IN_PROGRESS`, clearing
    `closed_reason` and `closed_at` and reasserting `decision` `SAR_REQUIRED`
    (§3.6)."
    PRD §2.10: "then state-machine legality (`ERR_INVALID_STATE`)".

    Only the system reopen leaves CLOSED; the decision endpoint does not.

    Design: Corner/state_machines/closed_case_decision_rejected
    """
    staff = create_staff()
    case = drive_case_to_closed_no_sar(staff, create_customer(staff)["id"])
    assert case["status"] == "CLOSED"

    res = api.record_sar_decision(
        case["id"],
        sar_decision_payload("SAR_REQUIRED", case["version"],
                             decision_rationale="Second thoughts"),
        staff.analyst)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert res.status_code == 409, (
        "the OCC version is fresh, so the rejection is purely the state gate"
    )
    after = validate_success(api.get_case(case["id"], staff.analyst), 200)
    assert after["status"] == "CLOSED"
    assert after["decision"] == "NO_SAR"


def test_case_close_blocked_while_inquiry_open(api):
    """PRD §3.4: "An `outcome` of `PASS` closes the case — but only if no
    law-enforcement inquiry linked to the case is still open (`RECEIVED`,
    `UNDER_REVIEW`, or `RESPONDED`); an open inquiry blocks the close with
    `ERR_LE_INQUIRY_OPEN`."
    PRD §3.7: "Closing the inquiry moves it to `CLOSED`, decrements
    `open_le_inquiry_count` on the customer, triggers the risk recompute
    again".

    Design: Corner/errors/case_close_blocked_by_open_inquiry
    """
    staff = create_staff()
    customer = create_customer(staff)
    case = drive_case_to_pending_qa(staff, customer["id"])
    inquiry = create_le_inquiry(staff, customer["id"], inquiry_reference="LE-7001")
    link_inquiry_to_case(staff, inquiry["id"], case["id"])

    res = api.review_case_qa(case["id"], {"outcome": "PASS"}, staff.qa)
    validate_error(res, ApiErrorId.ERR_LE_INQUIRY_OPEN)
    assert res.status_code == 409
    mid = validate_success(api.get_case(case["id"], staff.analyst), 200)
    assert mid["status"] == "PENDING_QA"

    closed_inquiry = respond_and_close_inquiry(staff, inquiry["id"])
    assert closed_inquiry["status"] == "CLOSED"
    closed_case = qa_review_case(staff, case["id"], "PASS")
    assert closed_case["status"] == "CLOSED"
    assert closed_case["closed_reason"] == "NO_SAR_CONFIRMED"
    customer_after = validate_success(api.get_customer(customer["id"], staff.analyst), 200)
    assert customer_after["open_le_inquiry_count"] == 0


def test_assign_reflects_immediately(api):
    """PRD §3.4: "Assignment stamps `assigned_analyst_id`, increments that
    analyst's open-case counter, and bumps the case `version`."

    The assign response itself shows the new state, and a same-instant read of
    the analyst already reflects the incremented counter.

    Design: Corner/consistency_model/immediate_consistency_on_assign
    """
    staff = create_staff()
    case = create_case(staff, create_customer(staff)["id"])
    assigned = validate_success(api.assign_case(
        case["id"], assign_case_payload(staff.analyst_id), staff.manager), 200)
    assert assigned["status"] == "ASSIGNED"
    assert assigned["assigned_analyst_id"] == staff.analyst_id
    assert assigned["version"] == 2, "create 1 + assign 1"
    analyst = validate_success(api.get_analyst(staff.analyst_id, staff.manager), 200)
    assert analyst["assigned_open_cases"] == 1, "no lag between write and read"


def test_compliance_admin_cannot_qa_review_case(api, admin_headers):
    """PRD §4: POST /cases/{id}/qa-review is authorized for `QAReviewer` only.
    PRD §2.1: "A request whose role is not listed among the endpoint's
    permitted roles is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)".

    Design: Corner/rbac/compliance_admin_cannot_qa_review_case_returns_403
    """
    staff = create_staff()
    case = drive_case_to_pending_qa(staff, create_customer(staff)["id"])
    res = api.review_case_qa(case["id"], {"outcome": "PASS"}, admin_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert res.status_code == 403
    after = validate_success(api.get_case(case["id"], staff.analyst), 200)
    assert after["status"] == "PENDING_QA"


def test_case_qa_by_assigned_analyst_rejected(api):
    """PRD §3.4: "The reviewer must differ from the assigned analyst
    (segregation of duties)."
    PRD §2.1: "On each, the caller's `X-User-ID` must differ from the actor who
    performed the prior step (the proposer, the drafter, or the assigned
    analyst as applicable), or the request is rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/sod_case_qa_by_assigned_analyst_rejected
    """
    staff = create_staff()
    case = drive_case_to_pending_qa(staff, create_customer(staff)["id"])
    assignee_as_qa = make_qa_reviewer_headers(staff.analyst_id)
    res = api.review_case_qa(case["id"], {"outcome": "PASS"}, assignee_as_qa)
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert res.status_code == 403
    after = validate_success(api.get_case(case["id"], staff.analyst), 200)
    assert after["status"] == "PENDING_QA"


def test_sar_decision_missing_field_returns_400(api):
    """PRD §2.10: "Priority order, from highest to lowest, is:
    malformed-request checks (missing fields, bad enums, non-positive amounts,
    incoherent date windows, a QA review lacking exactly one target, or a
    duplicate active QA sample on the same target — all `ERR_INVALID_REQUEST`);
    then authentication (`ERR_UNAUTHENTICATED`); then role authorization
    (`ERR_FORBIDDEN_ROLE`); then segregation-of-duties
    (`ERR_SEGREGATION_OF_DUTIES`); then existence of every referenced id
    (`ERR_NOT_FOUND`); then state-machine legality (`ERR_INVALID_STATE`); then
    OCC stale-version (`ERR_STALE_VERSION`); then the law-enforcement-inquiry
    safety hold (`ERR_LE_INQUIRY_OPEN`); then the customer-prohibited gate
    (`ERR_CUSTOMER_PROHIBITED`); then the threshold-window overlap check
    (`ERR_THRESHOLD_WINDOW_OVERLAP`); then the SAR activity-window overlap
    check (`ERR_ACTIVITY_WINDOW_OVERLAP`); then the 314(b) duplicate-window
    check (`ERR_314B_DUPLICATE_WINDOW`); then narrative length
    (`ERR_NARRATIVE_INSUFFICIENT`); then analyst capacity
    (`ERR_ANALYST_AT_CAPACITY`); then scenario retirement blocked by open
    alerts (`ERR_SCENARIO_HAS_OPEN_ALERTS`); then QA quota
    (`ERR_QA_QUOTA_EXCEEDED`); then filing deadline
    (`ERR_FILING_DEADLINE_PASSED`); then 314(b) certification expiry
    (`ERR_CERTIFICATION_EXPIRED`); then subject mismatch across a link
    (`ERR_SUBJECT_MISMATCH`); then the no-active-threshold check
    (`ERR_NO_ACTIVE_THRESHOLD`); and finally the scenario-not-active check
    (`ERR_SCENARIO_NOT_ACTIVE`)."

    A sar-decision call missing `decision` is malformed even though the
    ASSIGNED case is also in the wrong state.

    Design: Corner/validations/sar_decision_missing_field_beats_state_error
    """
    staff = create_staff()
    case = create_case(staff, create_customer(staff)["id"])
    assign_case(staff, case["id"])  # ASSIGNED, never started
    res = api.record_sar_decision(
        case["id"],
        {"decision_rationale": "Missing decision field",
         "expected_case_version": case["version"]},
        staff.analyst)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
    assert res.status_code == 400
