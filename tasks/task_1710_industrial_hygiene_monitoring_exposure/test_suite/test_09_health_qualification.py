"""Medical clearances and respirator fit tests: decision gates, cross-entity
currency, and the clock sweeps (PRD §2.5, §2.8, §3.8)."""
from test_helpers import (
    ApiErrorId,
    create_fit_test_payload,
    record_fit_result_payload,
    validate_error,
)
from test_helpers import fixtures as fx
from test_helpers.test_users import TEST_USERS

CIH = TEST_USERS["cih_headers"]
SSM = TEST_USERS["ssm_headers"]
TECH = TEST_USERS["tech_headers"]


def test_clearance_decide_twice_rejected(api):
    """PRD §3.8: "A `CIHDirector` decides it by supplying a `decision` of
    `CLEARED` or `DENIED`; deciding a clearance no longer in `REQUESTED` is
    rejected with `ERR_CLEARANCE_INVALID_STATE` (409). Either decision stamps
    `decided_at` and `decided_by_user_id` and increments the clearance's
    `version`; a `CLEARED` decision additionally sets `expiry_date` to the
    calendar date one year — 365 days — after the decision date, while
    `DENIED` is terminal with no expiry."

    Design: Corner/state_machines/clearance_decide_twice_rejected
    """
    ctx = fx.setup_site_seg(member_count=1)
    clearance = fx.request_clearance(ctx.employees[0]["id"])
    denied = fx.decide_clearance(clearance["id"], "DENIED")
    assert denied["status"] == "DENIED"
    assert denied["decided_at"] is not None
    assert denied["decided_by_user_id"] == "u_cih_1"
    assert denied["expiry_date"] is None

    res = api.decide_clearance(clearance["id"], {"decision": "CLEARED"}, CIH)
    validate_error(res, ApiErrorId.ERR_CLEARANCE_INVALID_STATE, 409)
    assert fx.get_clearance(clearance["id"])["status"] == "DENIED"


def test_clearance_employee_mismatch_rejected(api):
    """PRD §3.8: "A `SiteSafetyManager` schedules a test with the
    `employee_id`, the `medical_clearance_id`, the `respirator_model` tested,
    and the `test_date`; the referenced clearance must belong to that same
    employee, else `ERR_CLEARANCE_EMPLOYEE_MISMATCH` (422)."

    Design: Corner/validations/clearance_employee_mismatch_rejected
    """
    ctx = fx.setup_site_seg(member_count=2)
    e1, e2 = ctx.employees
    clearance_of_e2 = fx.request_clearance(e2["id"])

    res = api.create_fit_test(
        create_fit_test_payload(e1["id"], clearance_of_e2["id"]), SSM
    )
    validate_error(res, ApiErrorId.ERR_CLEARANCE_EMPLOYEE_MISMATCH, 422)


def test_fit_test_result_requires_current_clearance(api):
    """PRD §3.8: "Both outcomes are gated on medical currency: the linked
    clearance must stand at `CLEARED` with the current date on or before its
    `expiry_date`, else `ERR_MEDICAL_CLEARANCE_NOT_CURRENT` (422)".
    PRD §2.5: "Setting the clock triggers three time-based sweeps, each
    governed by a strictly-greater comparison: every medical clearance in
    `CLEARED` status whose `expiry_date` is before the new current date
    transitions to `EXPIRED`, and every respirator fit test in `PASSED` status
    tied to such a clearance expires along with it".
    PRD §3.8: "a `CLEARED` decision additionally sets `expiry_date` to the
    calendar date one year — 365 days — after the decision date".

    The clearance is decided at the 2026-08-01 startup clock (expiry
    2027-08-01); at 2027-08-02 it is swept to EXPIRED and takes the PASSED
    fit test with it.

    Design: Difficulty/cross_entity_state_dependency/fit_test_result_requires_current_clearance
    """
    ctx = fx.setup_site_seg(member_count=1)
    employee = ctx.employees[0]
    clearance = fx.decide_clearance(fx.request_clearance(employee["id"])["id"], "CLEARED")
    assert clearance["expiry_date"] == "2027-08-01"

    ft1 = fx.schedule_fit_test(employee["id"], clearance["id"], test_date="2026-08-03")
    ft2 = fx.schedule_fit_test(employee["id"], clearance["id"], test_date="2026-08-04")

    ft1 = fx.record_fit_result(ft1["id"], "PASS")
    assert ft1["status"] == "PASSED"
    assert ft1["expiry_date"] == "2027-08-03"

    fx.set_clock("2027-08-02T00:00:00Z")
    assert fx.get_clearance(clearance["id"])["status"] == "EXPIRED"
    assert fx.get_fit_test(ft1["id"])["status"] == "EXPIRED", (
        "the clearance expiry cascades to its PASSED fit tests"
    )

    res = api.record_fit_test_result(
        ft2["id"], record_fit_result_payload("PASS"), TECH
    )
    validate_error(res, ApiErrorId.ERR_MEDICAL_CLEARANCE_NOT_CURRENT, 422)
    assert fx.get_fit_test(ft2["id"])["status"] == "SCHEDULED"


def test_fit_test_fail_result_also_gated_on_clearance(api):
    """PRD §3.8: "Both outcomes are gated on medical currency: the linked
    clearance must stand at `CLEARED` with the current date on or before its
    `expiry_date`, else `ERR_MEDICAL_CLEARANCE_NOT_CURRENT` (422) — the gate
    applies equally to a failing result."

    Design: Difficulty/cross_entity_state_dependency/fit_test_result_requires_current_clearance
    """
    ctx = fx.setup_site_seg(member_count=1)
    employee = ctx.employees[0]
    clearance = fx.decide_clearance(fx.request_clearance(employee["id"])["id"], "CLEARED")
    fit_test = fx.schedule_fit_test(employee["id"], clearance["id"])

    fx.set_clock("2027-08-02T00:00:00Z")  # past the clearance's 2027-08-01
    res = api.record_fit_test_result(
        fit_test["id"], record_fit_result_payload("FAIL"), TECH
    )
    validate_error(res, ApiErrorId.ERR_MEDICAL_CLEARANCE_NOT_CURRENT, 422)
    assert fx.get_fit_test(fit_test["id"])["status"] == "SCHEDULED"


def test_fit_result_state_beats_clearance_safety(api):
    """PRD §2.8: "Every request is evaluated against a fixed validation
    pipeline, and the first failing stage determines the error returned —
    later stages are never consulted for that request."
    PRD §2.8: "Sixth, state preconditions: the target entity must be in a
    status that permits the requested operation, else the operation's state
    error (`ERR_PLAN_INVALID_STATE`, `ERR_PLAN_NOT_OPEN_FOR_SAMPLING`,
    `ERR_PLAN_NOT_READY_FOR_ASSESSMENT`, `ERR_SAMPLE_INVALID_STATE`,
    `ERR_CALIBRATION_ALREADY_RECORDED`, `ERR_ASSESSMENT_INVALID_STATE`,
    `ERR_CONTROL_INVALID_STATE`, `ERR_CLEARANCE_INVALID_STATE`,
    `ERR_FIT_TEST_NOT_RECORDABLE`, or `ERR_NOTIFICATION_INVALID_STATE`)."
    PRD §2.8: "Eighth, segregation-of-duties and safety gates (§2.9)."
    PRD §3.8: "recording from any other status is rejected with
    `ERR_FIT_TEST_NOT_RECORDABLE` (409)."

    The fit test is already FAILED (state stage) and its clearance has expired
    (safety stage); the earlier stage's error is reported.

    Design: Difficulty/priority_pair_validation_conflict/fit_result_state_beats_clearance_safety
    """
    ctx = fx.setup_site_seg(member_count=1)
    employee = ctx.employees[0]
    clearance = fx.decide_clearance(fx.request_clearance(employee["id"])["id"], "CLEARED")
    fit_test = fx.schedule_fit_test(employee["id"], clearance["id"], test_date="2026-08-03")
    failed = fx.record_fit_result(fit_test["id"], "FAIL")
    assert failed["status"] == "FAILED"

    fx.set_clock("2027-08-02T00:00:00Z")
    assert fx.get_clearance(clearance["id"])["status"] == "EXPIRED"

    res = api.record_fit_test_result(
        fit_test["id"], record_fit_result_payload("PASS"), TECH
    )
    validate_error(res, ApiErrorId.ERR_FIT_TEST_NOT_RECORDABLE, 409)
    assert fx.get_fit_test(fit_test["id"])["status"] == "FAILED"


def test_fit_result_state_error_at_clearance_expiry_boundary(api):
    """PRD §2.5: "On an expiry date or due date itself, nothing transitions —
    the date must be strictly in the past."
    PRD §2.8: "Sixth, state preconditions: the target entity must be in a
    status that permits the requested operation, else the operation's state
    error (`ERR_PLAN_INVALID_STATE`, `ERR_PLAN_NOT_OPEN_FOR_SAMPLING`,
    `ERR_PLAN_NOT_READY_FOR_ASSESSMENT`, `ERR_SAMPLE_INVALID_STATE`,
    `ERR_CALIBRATION_ALREADY_RECORDED`, `ERR_ASSESSMENT_INVALID_STATE`,
    `ERR_CONTROL_INVALID_STATE`, `ERR_CLEARANCE_INVALID_STATE`,
    `ERR_FIT_TEST_NOT_RECORDABLE`, or `ERR_NOTIFICATION_INVALID_STATE`)."
    PRD §2.8: "Eighth, segregation-of-duties and safety gates (§2.9)."
    PRD §3.8: "recording from any other status is rejected with
    `ERR_FIT_TEST_NOT_RECORDABLE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/fit_result_state_beats_clearance_safety
    """
    ctx = fx.setup_site_seg(member_count=1)
    employee = ctx.employees[0]
    clearance = fx.decide_clearance(fx.request_clearance(employee["id"])["id"], "CLEARED")
    fit_test = fx.schedule_fit_test(employee["id"], clearance["id"], test_date="2026-08-03")
    fx.record_fit_result(fit_test["id"], "FAIL")

    # On the expiry date itself the clearance has NOT swept yet.
    fx.set_clock("2027-08-01T00:00:00Z")
    assert fx.get_clearance(clearance["id"])["status"] == "CLEARED"

    fx.set_clock("2027-08-02T00:00:00Z")
    assert fx.get_clearance(clearance["id"])["status"] == "EXPIRED"

    res = api.record_fit_test_result(
        fit_test["id"], record_fit_result_payload("PASS"), TECH
    )
    validate_error(res, ApiErrorId.ERR_FIT_TEST_NOT_RECORDABLE, 409)


def test_fit_test_expiry_sweep_on_own_expiry(api):
    """PRD §3.8: "The test is born `SCHEDULED`, its `expiry_date` derived at
    scheduling as the `test_date` plus 365 days".
    PRD §3.8: "A `PASSED` test later moves to `EXPIRED` when the current date
    passes its own `expiry_date`, or immediately when its linked clearance
    expires; `FAILED` and `EXPIRED` are terminal."
    PRD §2.5: "every fit test in `PASSED` status whose own `expiry_date` is
    before the new current date transitions to `EXPIRED`".

    The fit test (test_date 2026-07-01) expires 2027-07-01 while its
    clearance (decided 2026-08-01) lives until 2027-08-01: at 2027-07-02 only
    the fit test has swept.

    Design: Corner/validations/fit_test_expiry_sweep_on_own_expiry
    """
    ctx = fx.setup_site_seg(member_count=1)
    employee = ctx.employees[0]
    clearance = fx.decide_clearance(fx.request_clearance(employee["id"])["id"], "CLEARED")
    assert clearance["expiry_date"] == "2027-08-01"

    fit_test = fx.schedule_fit_test(
        employee["id"], clearance["id"], test_date="2026-07-01"
    )
    assert fit_test["expiry_date"] == "2027-07-01"
    fx.record_fit_result(fit_test["id"], "PASS")

    fx.set_clock("2027-07-02T00:00:00Z")
    assert fx.get_fit_test(fit_test["id"])["status"] == "EXPIRED"
    assert fx.get_clearance(clearance["id"])["status"] == "CLEARED", (
        "the two expiry sweeps are independent"
    )
