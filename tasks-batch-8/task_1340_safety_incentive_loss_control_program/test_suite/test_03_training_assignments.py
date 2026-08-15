"""Training assignment rules: duplicate guard, certification suppression
window, employee-active gate, and the expire/reassign/complete cycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_iso_instant_equal,
    complete_assignment,
    create_active_program,
    create_assignment_record,
    create_course,
    create_employee_record,
    create_job_role,
    get_success_data,
    list_assignments,
    make_supervisor_headers,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["ehs_admin_headers"]


class TestDuplicateGuard:
    def test_duplicate_assigned_training_rejected(self, api):
        """PRD §3.2: "Manual assignment is guarded by three business rules,
        evaluated in this order: the employee must not already hold an
        `ASSIGNED` assignment for the same course (`ERR_DUPLICATE_ASSIGNMENT`)"

        Design: Corner/validations/duplicate_assigned_training_rejected
        """
        set_clock("2026-06-01T00:00:00Z")
        role = create_job_role(title="Laborer", hazard_class="LOW")
        course = create_course(title="HAZCOM", hazard_class="LOW", validity_months=12)
        employee = create_employee_record(role["id"], full_name="Eli E")
        first = create_assignment_record(employee["id"], course["id"], employee["id"],
                                         due_date="2026-06-20T00:00:00Z")
        assert first["status"] == "ASSIGNED"

        resp = api.create_training_assignment(
            {"employee_id": employee["id"], "course_id": course["id"],
             "due_date": "2026-07-01T00:00:00Z"},
            make_supervisor_headers(employee["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ASSIGNMENT)
        open_rows = list_assignments(employee_id=employee["id"], course_id=course["id"],
                                     status="ASSIGNED")
        assert len(open_rows) == 1, "no second ASSIGNED assignment may be persisted"


class TestCertificationSuppressionWindow:
    def _employee_with_live_cert(self, api, validity_months=2,
                                 renewal_window_days=30):
        """Employee Eli E with a COMPLETED HAZCOM assignment (completed
        2026-06-01); cert_valid_until = 2026-08-01 for a 2-month validity."""
        role = create_job_role(title="Laborer", hazard_class="LOW")
        course = create_course(title="HAZCOM", hazard_class="LOW",
                               validity_months=validity_months,
                               renewal_window_days=renewal_window_days)
        employee = create_employee_record(role["id"], full_name="Eli E")
        assignment = create_assignment_record(employee["id"], course["id"],
                                              employee["id"],
                                              due_date="2026-06-20T00:00:00Z")
        completed = complete_assignment(assignment["id"], employee["id"],
                                        role="Supervisor",
                                        completed_at="2026-06-01T00:00:00Z")
        return employee, course, completed

    def test_certification_window_blocks_at_31_days_remaining(self, api):
        """PRD §3.2: "the certification suppression window must be clear — if
        the employee holds a `COMPLETED` assignment for the same course whose
        remaining validity (the gap between `cert_valid_until` and the logical
        now, measured in days) strictly exceeds the course's
        `renewal_window_days`, the new assignment is rejected with
        `ERR_CERTIFICATION_ACTIVE`, while remaining validity exactly equal to
        the window passes"

        Design: Difficulty/resource_temporal_overlap/certification_renewal_window_suppression
        """
        set_clock("2026-06-01T00:00:00Z")
        employee, course, completed = self._employee_with_live_cert(api)
        assert_iso_instant_equal(completed["cert_valid_until"],
                                 "2026-08-01T00:00:00Z")

        set_clock("2026-07-01T00:00:00Z")  # 31 days of validity remain
        resp = api.create_training_assignment(
            {"employee_id": employee["id"], "course_id": course["id"],
             "due_date": "2026-07-15T00:00:00Z"},
            make_supervisor_headers(employee["id"]))
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_ACTIVE)


class TestEmployeeActiveGate:
    def test_training_assignment_create_rejected_for_inactive_employee(self, api):
        """PRD §3.2: "and the employee must be `ACTIVE`, else
        `ERR_EMPLOYEE_INACTIVE`."
        PRD §3.2: "Deactivating an employee moves them `ACTIVE → INACTIVE` and
        cancels every one of their assignments still in `ASSIGNED` or `EXPIRED`"

        Design: Difficulty/cross_entity_state_dependency/training_assignment_gated_by_employee_active
        """
        set_clock("2026-06-01T00:00:00Z")
        role = create_job_role(title="Laborer", hazard_class="LOW")
        course = create_course(title="HAZCOM", hazard_class="LOW", validity_months=12,
                               renewal_window_days=30)
        employee = create_employee_record(role["id"], full_name="Eli E")
        get_success_data(api.deactivate_employee(employee["id"], ADMIN))

        resp = api.create_training_assignment(
            {"employee_id": employee["id"], "course_id": course["id"],
             "due_date": "2026-07-01T00:00:00Z"},
            make_supervisor_headers(employee["id"]))
        validate_error(resp, ApiErrorId.ERR_EMPLOYEE_INACTIVE)
        assert list_assignments(employee_id=employee["id"]) == [], \
            "no assignment row may exist for the inactive employee"


class TestConstraintOrderOnCreate:
    def test_certification_window_conflict_creates_no_assignment(self, api):
        """PRD §2.6: "on training-assignment creation, for example, the
        duplicate-assignment check fires before the certification-window check,
        which fires before the employee-active check"
        PRD §3.2: "the new assignment is rejected with
        `ERR_CERTIFICATION_ACTIVE`"

        Design: Difficulty/priority_pair_validation_conflict/training_create_constraint_beats_referential
        """
        set_clock("2026-06-01T00:00:00Z")
        role = create_job_role(title="Laborer", hazard_class="LOW")
        course = create_course(title="HAZCOM", hazard_class="LOW", validity_months=12,
                               renewal_window_days=30)
        employee = create_employee_record(role["id"], full_name="Eli E")
        assignment = create_assignment_record(employee["id"], course["id"],
                                              employee["id"],
                                              due_date="2026-06-20T00:00:00Z")
        complete_assignment(assignment["id"], employee["id"], role="Supervisor")
        get_success_data(api.deactivate_employee(employee["id"], ADMIN))

        resp = api.create_training_assignment(
            {"employee_id": employee["id"], "course_id": course["id"],
             "due_date": "2026-07-01T00:00:00Z"},
            make_supervisor_headers(employee["id"]))
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_ACTIVE)
        rows = list_assignments(employee_id=employee["id"], course_id=course["id"])
        assert len(rows) == 1 and rows[0]["status"] == "COMPLETED", \
            "the rejected create leaves only the pre-existing COMPLETED assignment"


class TestExpireReassignCompleteCycle:
    def test_training_expire_reassign_complete_cycle(self, api):
        """PRD §3.2: "An assignment still `ASSIGNED` when its `due_date` falls
        behind the logical now is flipped to `EXPIRED` by the operations sweep
        (§3.7) — and an `EXPIRED` required assignment still counts as pending.
        Reassigning moves `EXPIRED → ASSIGNED` with a new, required `due_date`."
        PRD §3.2: "On completion the system computes `cert_valid_until` — null
        until the assignment is `COMPLETED` — as `completed_at` plus the
        course's `validity_months`"

        Design: Corner/state_machines/training_expire_reassign_complete_cycle
        """
        set_clock("2026-06-01T00:00:00Z")
        program = create_active_program()
        role = create_job_role(title="Laborer", hazard_class="LOW")
        course = create_course(title="HAZCOM", hazard_class="LOW", validity_months=3,
                               renewal_window_days=30)
        employee = create_employee_record(role["id"], full_name="Eli E")
        assignment = create_assignment_record(employee["id"], course["id"],
                                              employee["id"],
                                              due_date="2026-06-10T00:00:00Z")

        set_clock("2026-06-15T00:00:00Z")
        sweep = validate_success(api.sweep_program(program["id"], {}, ADMIN))
        assert sweep["expired_assignments"] == 1, "ASSIGNED past due flips to EXPIRED"

        reassigned = validate_success(api.reassign_training_assignment(
            assignment["id"], {"due_date": "2026-06-25T00:00:00Z"},
            make_supervisor_headers(employee["id"])))
        assert reassigned["status"] == "ASSIGNED"
        assert_iso_instant_equal(reassigned["due_date"], "2026-06-25T00:00:00Z")

        set_clock("2026-06-20T00:00:00Z")
        completed = validate_success(api.complete_training_assignment(
            assignment["id"], {}, make_supervisor_headers(employee["id"])))
        assert completed["status"] == "COMPLETED"
        assert_iso_instant_equal(completed["cert_valid_until"],
                                 "2026-09-20T00:00:00Z")
