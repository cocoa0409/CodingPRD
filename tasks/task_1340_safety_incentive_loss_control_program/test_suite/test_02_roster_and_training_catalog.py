"""Workforce roster and training catalog: auto-assignment, derived pending
counts, default-clock behavior, pagination, and deactivation cascade."""
from test_helpers import (
    TEST_USERS,
    assert_employee,
    assert_iso_instant_equal,
    assert_training_assignment,
    complete_assignment,
    create_course,
    create_employee_record,
    create_job_role,
    get_employee,
    get_success_data,
    list_assignments,
    set_clock,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["ehs_admin_headers"]


class TestCourseCatalog:
    def test_course_list_pagination_envelope(self, api):
        """PRD §2.3: "Paginated list responses include the following fields in
        the `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."
        PRD §2.3: "Unless otherwise specified, all list endpoints return
        resources sorted by their creation timestamp in ascending order."

        Design: Corner/entities/course_list_pagination_envelope
        """
        set_clock("2026-06-01T00:00:00Z")
        create_course(title="C1", hazard_class="LOW", validity_months=12)
        create_course(title="C2", hazard_class="MODERATE", validity_months=12)
        create_course(title="C3", hazard_class="HIGH", validity_months=24)

        page1, meta1 = validate_paginated(
            api.list_training_courses(ADMIN, params={"limit": 2}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert [row["title"] for row in page1] == ["C1", "C2"], \
            "creation-time ascending order"

        page2, meta2 = validate_paginated(
            api.list_training_courses(ADMIN, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert page2[0]["title"] == "C3"


class TestAutoRequiredTraining:
    def test_employee_auto_required_training_on_create(self, api):
        """PRD §3.2: "Creation has an immediate side effect: for every course in
        the new employee's job role `required_course_ids`, the system
        auto-creates a TrainingAssignment whose `source` is `SYSTEM_JOB_HAZARD`
        and whose `due_date` falls 30 days after the logical now. The employee's
        `pending_required_training_count` — the count of that employee's
        assignments flagged `required` whose status is `ASSIGNED` or `EXPIRED` —
        is initialized accordingly."

        Design: Corner/entities/employee_auto_required_training_on_create
        """
        set_clock("2026-06-01T00:00:00Z")
        course = create_course(title="LOTO", hazard_class="HIGH", validity_months=12,
                               renewal_window_days=30)
        role = create_job_role(title="Electrician", hazard_class="HIGH",
                               required_course_ids=[course["id"]])
        employee = validate_success(api.create_employee(
            {"full_name": "Ann A", "job_role_id": role["id"], "hired_on": "2026-06-01"},
            ADMIN), expected_status=201)
        assert_employee(employee)
        assert employee["pending_required_training_count"] == 1

        assignments = list_assignments(employee_id=employee["id"])
        assert len(assignments) == 1
        assignment = assignments[0]
        assert_training_assignment(assignment)
        assert assignment["source"] == "SYSTEM_JOB_HAZARD"
        assert assignment["required"] is True
        assert assignment["status"] == "ASSIGNED"
        assert assignment["course_id"] == course["id"]
        assert_iso_instant_equal(assignment["due_date"], "2026-07-01T00:00:00Z")

    def test_default_clock_drives_auto_assignment_due(self, api):
        """PRD §2.5: "Before any client call, the logical clock reads exactly
        `2026-08-01T00:00:00Z`."
        PRD §3.2: "for every course in the new employee's job role
        `required_course_ids`, the system auto-creates a TrainingAssignment
        whose `source` is `SYSTEM_JOB_HAZARD` and whose `due_date` falls 30 days
        after the logical now."

        Design: Corner/endpoints/default_clock_drives_auto_assignment_due
        """
        # Deliberately no set_clock call: the server starts at its documented
        # default logical time.
        course = create_course(title="LOTO", hazard_class="HIGH", validity_months=12)
        role = create_job_role(title="Electrician", hazard_class="HIGH",
                               required_course_ids=[course["id"]])
        employee = create_employee_record(role["id"], full_name="Eli E",
                                          hired_on="2026-08-01")
        assignments = list_assignments(employee_id=employee["id"])
        assert len(assignments) == 1
        assert_iso_instant_equal(assignments[0]["due_date"], "2026-08-31T00:00:00Z")


class TestPendingRequiredTrainingCount:
    def test_derived_pending_training_count_reconciles(self, api):
        """PRD §3.2: "The employee's `pending_required_training_count` — the
        count of that employee's assignments flagged `required` whose status is
        `ASSIGNED` or `EXPIRED` — is initialized accordingly."
        PRD §3.2: "On completion the system computes `cert_valid_until` — null
        until the assignment is `COMPLETED` — as `completed_at` plus the
        course's `validity_months`, and recomputes the employee's
        `pending_required_training_count`."

        Design: Corner/cross_cutting_complexity_layers/derived_pending_training_count_reconciles
        """
        set_clock("2026-06-01T00:00:00Z")
        loto = create_course(title="LOTO", hazard_class="HIGH", validity_months=12)
        ppe = create_course(title="PPE", hazard_class="HIGH", validity_months=6)
        role = create_job_role(title="Electrician", hazard_class="HIGH",
                               required_course_ids=[loto["id"], ppe["id"]])
        employee = create_employee_record(role["id"], full_name="Eli E")
        assert employee["pending_required_training_count"] == 2, \
            "both required courses auto-assign at creation"

        loto_assignment = list_assignments(employee_id=employee["id"],
                                           course_id=loto["id"])[0]
        complete_assignment(loto_assignment["id"], employee["id"], role="Supervisor")
        assert get_employee(employee["id"])["pending_required_training_count"] == 1, \
            "completing one required course drops the pending count to one"

    def test_employee_deactivate_cancels_open_training(self, api):
        """PRD §3.2: "Deactivating an employee moves them `ACTIVE → INACTIVE`
        and cancels every one of their assignments still in `ASSIGNED` or
        `EXPIRED`, moving each to `CANCELLED`; the pending-required count is
        recomputed and falls to zero."

        Design: Corner/state_machines/employee_deactivate_cancels_open_training
        """
        set_clock("2026-06-01T00:00:00Z")
        course = create_course(title="LOTO", hazard_class="HIGH", validity_months=12)
        role = create_job_role(title="Electrician", hazard_class="HIGH",
                               required_course_ids=[course["id"]])
        employee = create_employee_record(role["id"], full_name="Eli E")
        assert employee["pending_required_training_count"] == 1

        deactivated = validate_success(api.deactivate_employee(employee["id"], ADMIN))
        assert deactivated["status"] == "INACTIVE"
        assert deactivated["pending_required_training_count"] == 0

        assignments = list_assignments(employee_id=employee["id"])
        assert len(assignments) == 1
        assert assignments[0]["status"] == "CANCELLED", \
            "the open auto-assignment is cancelled by deactivation"
