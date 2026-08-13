"""Compliance assignments: registration/completion-driven transitions,
escalation cascade into standing, waiver segregation, and OCC extension."""
from datetime import datetime

import pytest

from test_helpers import (
    TEST_USERS, api_client, complete_registration,
    make_assignment, make_building, make_course, make_teacher,
    prepare_completable_registration, register_teacher, run_ops, set_clock,
    setup_catalog_scenario, validate_error, validate_paginated, validate_success,
    make_coordinator_headers,
)


def _iso(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant regardless of fractional-digit rendering."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


COMPLETION_INSTANT = _iso("2026-08-16T00:00:00Z")


class TestComplianceEscalationStanding:
    def _escalated_employee(self):
        """Teacher with one compliance assignment due 2026-08-10; two ops-runs
        walk it ASSIGNED -> OVERDUE (clock 08-15) -> ESCALATED (clock 09-20)."""
        set_clock()
        building = make_building(name="B Three", building_code="B3")
        teacher = make_teacher(building["id"], lane="MA", email="tc@x.com")
        course = make_course(course_code="SAFE-1", title="Safety Training",
                             delivery_mode="VIRTUAL", clock_hours=2, fee_cents=0,
                             compliance_tag="SAFETY")
        assignment = make_assignment(teacher["id"], course["id"],
                                     due_date="2026-08-10T00:00:00Z")
        assert assignment["status"] == "ASSIGNED"
        set_clock("2026-08-15T00:00:00Z")
        run_ops()
        mid = validate_success(api_client.get_assignment(
            assignment["id"], TEST_USERS["coordinator_headers"]), 200)
        assert mid["status"] == "OVERDUE"
        set_clock("2026-09-20T00:00:00Z")  # more than thirty days past due
        run_ops()
        return teacher, assignment

    def test_escalation_flips_compliance_standing(self, api):
        """PRD §3.7: "The ops checkpoint moves an `ASSIGNED` or `IN_PROGRESS`
        assignment past its `due_date` to `OVERDUE`, and an `OVERDUE` assignment
        more than thirty days past its due date to `ESCALATED`; the escalation
        recomputes the employee's `compliance_standing` to `NON_COMPLIANT`".

        Design: Difficulty/transitive_cascade/cascade_compliance_escalation_standing
        """
        teacher, assignment = self._escalated_employee()
        final = validate_success(api.get_assignment(
            assignment["id"], TEST_USERS["coordinator_headers"]), 200)
        assert final["status"] == "ESCALATED"  # link 1
        employee = validate_success(api.get_employee(
            teacher["id"], TEST_USERS["coordinator_headers"]), 200)
        assert employee["compliance_standing"] == "NON_COMPLIANT", (
            "link 2: standing recompute caused by the escalation")

    def test_compliance_hold_blocks_lane_advancement(self, api):
        """PRD §3.9: "Lane advancement is a coordinator action gated by six
        checks, evaluated in order: the employee must be `ACTIVE`
        (`ERR_EMPLOYEE_NOT_ACTIVE`); their `compliance_standing` must be
        `COMPLIANT` (`ERR_COMPLIANCE_HOLD`); ... and their
        `lane_credit_balance` must be at least 12.0 credits
        (`ERR_LANE_CREDITS_INSUFFICIENT`)."

        Design: Difficulty/transitive_cascade/cascade_compliance_escalation_standing
        """
        teacher, _assignment = self._escalated_employee()
        # Clock is 2026-09-20 — September, inside the advancement window; the
        # balance is 0.0, so only the standing gate can fire first.
        res = api.advance_lane(teacher["id"], TEST_USERS["coordinator_headers"])
        validate_error(res, "ERR_COMPLIANCE_HOLD", expected_status=400)


class TestAssignmentSatisfiedByCompletion:
    def _completed_compliance_course(self):
        """Teacher assigned a recurring compliance course; registers (flips the
        assignment IN_PROGRESS) and completes (satisfies + spawns successor)."""
        sc = setup_catalog_scenario(
            course_overrides={"course_code": "CPR-1", "title": "CPR Training",
                              "clock_hours": 3, "fee_cents": 0,
                              "compliance_tag": "CPR", "recurrence_months": 12})
        teacher = make_teacher(sc.building["id"], email="tl@x.com")
        assignment = make_assignment(teacher["id"], sc.course["id"],
                                     due_date="2027-06-01T00:00:00Z")
        registration = register_teacher(teacher["id"], sc.section["id"])
        mid = validate_success(api_client.get_assignment(
            assignment["id"], TEST_USERS["coordinator_headers"]), 200)
        prepare_completable_registration(registration["id"], sc.instructor["id"],
                                         sc.meetings, survey="waive")
        completed = complete_registration(registration["id"])
        return sc, teacher, assignment, mid, completed

    def test_registration_flips_assignment_in_progress_then_satisfied(self, api):
        """PRD §3.7: "When the assignee becomes `REGISTERED` in a section of the
        assigned course — by direct registration or by waitlist promotion — the
        assignment moves `ASSIGNED` → `IN_PROGRESS`." PRD §3.5: "any of the
        teacher's assignments for this course standing in `ASSIGNED`,
        `IN_PROGRESS`, `OVERDUE`, or `ESCALATED` become `SATISFIED` with
        `satisfied_at` set to the completion instant".

        Design: Difficulty/cross_entity_state_dependency/cross_entity_assignment_satisfied_by_completion
        """
        _sc, _teacher, assignment, mid, completed = self._completed_compliance_course()
        assert mid["status"] == "IN_PROGRESS", "cross-entity flip on REGISTERED"
        assert completed["status"] == "COMPLETED"
        assert _iso(completed["completed_at"]) == COMPLETION_INSTANT, (
            "completed_at is the logical now")
        final = validate_success(api.get_assignment(
            assignment["id"], TEST_USERS["coordinator_headers"]), 200)
        assert final["status"] == "SATISFIED"
        assert _iso(final["satisfied_at"]) == _iso(completed["completed_at"]), (
            "satisfied_at is the completion instant")

    def test_recurrence_successor_and_no_lane_credit(self, api):
        """PRD §3.5: "if the course's `recurrence_months` is set, a successor
        assignment is spawned in `ASSIGNED` with `due_date` at `completed_at`
        plus that many months, same employee and course". PRD §3.5: "its
        `counts_toward_lane` is `false` when the source course carries a
        `compliance_tag`". PRD §3.9: the balance is "the sum of `district_credit`
        over the employee's `AWARDED` transcript entries that count toward the
        lane".

        Design: Difficulty/cross_entity_state_dependency/cross_entity_assignment_satisfied_by_completion
        """
        sc, teacher, assignment, _mid, completed = self._completed_compliance_course()
        data, _meta = validate_paginated(api.list_assignments(
            TEST_USERS["coordinator_headers"],
            params={"employee_id": teacher["id"]}))
        successors = [a for a in data
                      if a["status"] == "ASSIGNED" and a["id"] != assignment["id"]]
        assert len(successors) == 1, "recurrence spawns exactly one successor"
        assert successors[0]["course_id"] == sc.course["id"]
        assert _iso(successors[0]["due_date"]) == _iso("2027-08-16T00:00:00Z"), (
            "completed_at 2026-08-16 + 12 months")
        employee = validate_success(api.get_employee(
            teacher["id"], TEST_USERS["coordinator_headers"]), 200)
        assert employee["lane_credit_balance"] == pytest.approx(0.0), (
            "compliance-tagged completion does not count toward the lane")


def test_waive_assignment_by_creator_rejected(api):
    """PRD §2.1: "a `PDCoordinator` attempting to waive a compliance assignment
    whose `assigned_by_user_id` equals their own `X-User-ID` receives the same
    `ERR_SEGREGATION_OF_DUTIES`." PRD §3.7: "A coordinator may instead waive an
    assignment from any of those four states into terminal `WAIVED`, supplying a
    `reason` — but only if the coordinator's `X-User-ID` differs from the
    assignment's `assigned_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`".

    Design: Corner/rbac/waive_assignment_by_creator_rejected
    """
    set_clock()
    building = make_building(name="WV Bldg", building_code="WV1")
    teacher = make_teacher(building["id"], email="twv@x.com")
    course = make_course(course_code="WV-SAFE", title="Safety",
                         delivery_mode="VIRTUAL", clock_hours=2, fee_cents=0,
                         compliance_tag="SAFETY")
    assignment = make_assignment(teacher["id"], course["id"],
                                 due_date="2026-09-01T00:00:00Z",
                                 coordinator_id="coord-1")
    assert assignment["assigned_by_user_id"] == "coord-1"

    res = api.waive_assignment(assignment["id"], {"reason": "self waive"},
                               make_coordinator_headers("coord-1"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)

    waived = validate_success(api.waive_assignment(
        assignment["id"], {"reason": "documented waiver"},
        make_coordinator_headers("coord-2")), 200)
    assert waived["status"] == "WAIVED"


def test_extend_assignment_occ_stale_rejected(api):
    """PRD §2.8: "Extending a compliance assignment's due date carries
    `expected_assignment_version`, which must equal the assignment's current
    `version`. ... the extension is rejected as a stale write with
    `ERR_STALE_ASSIGNMENT_VERSION` (HTTP 412)." PRD §3.7: "A successful extension
    moves the due date, resets the status to `ASSIGNED`, increments both
    `extension_count` and the assignment's `version`, and recomputes standing."

    Design: Corner/cross_cutting_layers/extend_assignment_occ_stale_rejected
    """
    set_clock()
    building = make_building(name="OC Bldg", building_code="OC1")
    teacher = make_teacher(building["id"], email="toc@x.com")
    course = make_course(course_code="OC-SAFE", title="Safety OC",
                         delivery_mode="VIRTUAL", clock_hours=2, fee_cents=0,
                         compliance_tag="SAFETY")
    assignment = make_assignment(teacher["id"], course["id"],
                                 due_date="2026-09-01T00:00:00Z")
    created_version = assignment["version"]

    extended = validate_success(api.extend_assignment(
        assignment["id"],
        {"new_due_date": "2026-10-01T00:00:00Z",
         "expected_assignment_version": created_version},
        TEST_USERS["coordinator_headers"]), 200)
    assert extended["version"] == created_version + 1
    assert extended["status"] == "ASSIGNED", "extension resets the status"
    assert extended["extension_count"] == 1
    assert _iso(extended["due_date"]) == _iso("2026-10-01T00:00:00Z")

    res = api.extend_assignment(
        assignment["id"],
        {"new_due_date": "2026-11-01T00:00:00Z",
         "expected_assignment_version": created_version},
        TEST_USERS["coordinator_headers"])
    validate_error(res, "ERR_STALE_ASSIGNMENT_VERSION", expected_status=412)
