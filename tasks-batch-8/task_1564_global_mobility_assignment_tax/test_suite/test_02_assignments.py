"""Assignment creation and window semantics: request shape, existence, the
closed-interval overlap rule, cancellation, and first approval-step state
eligibility (PRD §2.10, §3.2)."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_assignment_payload,
    create_draft_assignment,
    create_employee,
    create_policy,
    create_program,
    get_assignment,
    validate_error,
    validate_success,
)


def _base_parents():
    program = create_program()
    employee = create_employee()
    policy = create_policy()
    return program, employee, policy


def test_assignment_create_invalid_enum_and_date_range_rejected(api, admin_headers):
    """PRD §2.10: "Required fields must be present; enums must lie in their declared
    sets; integers must satisfy their field constraints (percentages between 0 and 100
    inclusive, amounts non-negative, `period_month` between 1 and 12 inclusive);
    `effective_to` must be strictly after `effective_from`; `valid_until` strictly
    after `valid_from`; `planned_end_date` on or after `start_date` — else
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/assignment_create_invalid_enum_and_date_range_rejected
    """
    program, employee, policy = _base_parents()

    bad_enum = create_assignment_payload(
        program["id"], employee["id"], policy["id"], assignment_type="SIDEWAYS")
    res = api.create_assignment(bad_enum, admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    bad_dates = create_assignment_payload(
        program["id"], employee["id"], policy["id"],
        start_date="2027-08-31", planned_end_date="2026-09-01")
    res = api.create_assignment(bad_dates, admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_assignment_with_unknown_id_returns_not_found(api, admin_headers):
    """PRD §2.10: "Every path identifier must resolve to an existing resource,
    validated left to right; body foreign-key fields (`program_id`, `employee_id`,
    `policy_id`, `assignment_id`) must reference existing rows, else `ERR_NOT_FOUND`
    (404)."

    Design: Corner/entities/get_assignment_with_unknown_id_returns_not_found
    """
    res = api.get_assignment("11111111-2222-3333-4444-555555555555", admin_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_assignment_touching_window_conflicts_but_next_day_succeeds(api, admin_headers):
    """PRD §2.5: "Assignment windows are closed intervals: `start_date` and
    `planned_end_date` are both inclusive, so two same-employee assignments whose
    windows merely touch at a single shared date are in conflict."
    PRD §3.2: "only then does the server check whether the same employee already holds
    an assignment in `DRAFT`, `PENDING_BU_APPROVAL`, `PENDING_MOBILITY_APPROVAL`,
    `ACTIVE`, or `REPATRIATION_PENDING` whose closed interval intersects the new one —
    touching endpoints count as a conflict — rejecting with `ERR_ASSIGNMENT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/assignment_window_closed_interval_touch_conflicts
    """
    program = create_program()
    employee = create_employee()
    policy = create_policy(effective_to="2028-12-31")
    create_draft_assignment(program["id"], employee["id"], policy["id"],
                            totalization_applies=True)

    touching = create_assignment_payload(
        program["id"], employee["id"], policy["id"],
        assignment_type="SHORT_TERM", totalization_applies=True,
        start_date="2027-08-31", planned_end_date="2028-02-29")
    res = api.create_assignment(touching, admin_headers)
    validate_error(res, ApiErrorId.ERR_ASSIGNMENT_OVERLAP)

    next_day = create_assignment_payload(
        program["id"], employee["id"], policy["id"],
        assignment_type="SHORT_TERM", totalization_applies=True,
        start_date="2027-09-01", planned_end_date="2028-03-31")
    successor = validate_success(api.create_assignment(next_day, admin_headers), 201)
    assert successor["status"] == "DRAFT"


def test_assignment_cancel_frees_date_window(api, admin_headers):
    """PRD §3.2: "Finally, a `MobilityAdmin` may cancel an assignment while it is in
    `DRAFT`, `PENDING_BU_APPROVAL`, or `PENDING_MOBILITY_APPROVAL`, moving it to the
    terminal `CANCELLED` state; cancellation frees the employee's date window, because
    `CANCELLED` rows no longer participate in the `ERR_ASSIGNMENT_OVERLAP` check."

    Design: Difficulty/resource_temporal_overlap/assignment_window_closed_interval_touch_conflicts
    """
    program = create_program()
    employee = create_employee()
    policy = create_policy(effective_to="2028-12-31")
    first = create_draft_assignment(program["id"], employee["id"], policy["id"],
                                    totalization_applies=True)

    cancelled = validate_success(api.cancel_assignment(first["id"], admin_headers), 200)
    assert cancelled["status"] == "CANCELLED"

    rebooked = validate_success(api.create_assignment(
        create_assignment_payload(program["id"], employee["id"], policy["id"],
                                  totalization_applies=True),
        admin_headers), 201)
    assert rebooked["start_date"] == "2026-09-01"
    assert rebooked["planned_end_date"] == "2027-08-31"


def test_approve_bu_from_draft_returns_invalid_state(api, admin_headers, bu_approver_headers):
    """PRD §2.10: "The target must be in a from-state of the invoked transition, and
    terminal states accept no further transitions; state-gated creations require their
    parent state — a shadow payroll record requires an `ACTIVE` assignment, a
    settlement requires an assignment that is `ACTIVE`, `REPATRIATION_PENDING`, or
    `REPATRIATED`, and an extension request requires an `ACTIVE` assignment — else
    `ERR_INVALID_STATE` (409)."
    PRD §3.2: "A `BusinessUnitApprover` then approves — `PENDING_BU_APPROVAL` →
    `PENDING_MOBILITY_APPROVAL`, recording `bu_approved_by_user_id`"

    Design: Corner/state_machines/approve_bu_from_draft_returns_invalid_state
    """
    program, employee, policy = _base_parents()
    assignment = create_draft_assignment(program["id"], employee["id"], policy["id"])

    res = api.approve_bu(assignment["id"], bu_approver_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert get_assignment(assignment["id"])["status"] == "DRAFT"


def test_terminal_states_reject_all_transitions(api, admin_headers, bu_approver_headers):
    """PRD §2.10: "The target must be in a from-state of the invoked transition, and
    terminal states accept no further transitions; state-gated creations require their
    parent state — a shadow payroll record requires an `ACTIVE` assignment, a
    settlement requires an assignment that is `ACTIVE`, `REPATRIATION_PENDING`, or
    `REPATRIATED`, and an extension request requires an `ACTIVE` assignment — else
    `ERR_INVALID_STATE` (409)."
    PRD §3.7: "Declining requires the request to be `PENDING` and the assignment
    `ACTIVE`; it moves the request to `DECLINED` and records `decided_by_user_id`."

    Design: Corner/state_machines/terminal_states_reject_all_transitions
    """
    from test_helpers import create_pending_extension, setup_active_assignment

    program = create_program()
    employee = create_employee(employee_ref="E1001", full_name="A One")
    policy = create_policy()
    cancelled = create_draft_assignment(program["id"], employee["id"], policy["id"])
    validate_success(api.cancel_assignment(cancelled["id"], admin_headers), 200)

    res = api.submit_assignment(cancelled["id"], admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    ctx = setup_active_assignment(
        employee_overrides={"employee_ref": "E1002", "full_name": "B Two"},
        policy_overrides={"effective_from": "2028-01-01", "effective_to": "2029-12-31"})
    active_id = ctx["assignment"]["id"]
    extension = create_pending_extension(active_id, "2027-10-31")
    declined = validate_success(api.decline_extension(extension["id"], bu_approver_headers), 200)
    assert declined["status"] == "DECLINED"

    res = api.approve_extension(extension["id"], bu_approver_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
