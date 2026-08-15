"""Staffing rules: role mapping, activity flag, window copying, start gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assign_staff,
    assert_instant_equals,
    create_cardiologist,
    create_circulating_nurse,
    create_scrub_technologist,
    make_interventional_cardiologist_headers,
    setup_case_workspace,
    staff_case,
    staff_assignment_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

SCHEDULER = TEST_USERS["scheduler_headers"]


class TestRoleMapping:
    def test_assign_cardiologist_as_scrub_returns_role_mismatch(self, api):
        """PRD §3.4: "the role in the case must agree with the staff member's own
        `staff_role`: `PRIMARY_OPERATOR` requires an `INTERVENTIONAL_CARDIOLOGIST`,
        `SCRUB` requires a `SCRUB_TECHNOLOGIST`, and `CIRCULATOR` requires a
        `CIRCULATING_NURSE`. A mismatch is rejected with `ERR_STAFF_ROLE_MISMATCH`"

        Design: Corner/validations/assign_cardiologist_as_scrub_returns_role_mismatch
        """
        workspace = setup_case_workspace()
        other_cardiologist = create_cardiologist(full_name="Dr Second")
        resp = api.create_staff_assignment(
            workspace["case"]["id"],
            staff_assignment_payload(other_cardiologist["id"], "SCRUB"),
            SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_STAFF_ROLE_MISMATCH,
                       expected_status=422)
        _, meta = validate_paginated(
            api.list_case_staff_assignments(workspace["case"]["id"], SCHEDULER))
        assert meta["total_count"] == 0, "no assignment persisted"

    def test_performing_physician_must_be_cardiologist_returns_mismatch(self, api):
        """PRD §3.2: "The referenced performing physician must be a staff member
        whose `staff_role` is `INTERVENTIONAL_CARDIOLOGIST`; any other reference is
        rejected with `ERR_STAFF_ROLE_MISMATCH`."

        Design: Corner/validations/performing_physician_must_be_cardiologist_returns_mismatch
        """
        tech = create_scrub_technologist()
        resp = api.create_case(
            {"patient_mrn": "MRN-1", "procedure_type": "PCI", "priority": "URGENT",
             "performing_physician_id": tech["id"], "weight_kg": 70,
             "serum_creatinine": 1.0},
            SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_STAFF_ROLE_MISMATCH,
                       expected_status=422)
        _, meta = validate_paginated(api.list_cases(SCHEDULER))
        assert meta["total_count"] == 0


class TestStaffActivityGate:
    def test_assignment_of_inactive_staff_rejected(self, api):
        """PRD §3.4: "A mismatch is rejected with `ERR_STAFF_ROLE_MISMATCH`, and a
        member whose `is_active` flag is false is rejected with
        `ERR_STAFF_INACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/assignment_requires_staff_active
        """
        workspace = setup_case_workspace()
        tech = create_scrub_technologist()
        patched = validate_success(
            api.patch_staff(tech["id"], {"is_active": False}, SCHEDULER))
        assert patched["is_active"] is False
        resp = api.create_staff_assignment(
            workspace["case"]["id"],
            staff_assignment_payload(tech["id"], "SCRUB"), SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_STAFF_INACTIVE, expected_status=409)
        _, meta = validate_paginated(
            api.list_case_staff_assignments(workspace["case"]["id"], SCHEDULER))
        assert meta["total_count"] == 0, "no assignment persisted"

    def test_assignment_after_reactivation_succeeds(self, api):
        """PRD §3.1: "Activation and deactivation are scheduler operations on
        `is_active`; deactivation is refused with `ERR_RESOURCE_IN_USE` while the
        member still holds `ASSIGNED` assignments on cases that have not reached a
        terminal state."
        PRD §3.4: "A mismatch is rejected with `ERR_STAFF_ROLE_MISMATCH`, and a
        member whose `is_active` flag is false is rejected with
        `ERR_STAFF_INACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/assignment_requires_staff_active
        """
        workspace = setup_case_workspace()
        tech = create_scrub_technologist()
        validate_success(api.patch_staff(tech["id"], {"is_active": False},
                                         SCHEDULER))
        validate_success(api.patch_staff(tech["id"], {"is_active": True},
                                         SCHEDULER))
        asg = assign_staff(workspace["case"]["id"], tech["id"], "SCRUB")
        assert asg["status"] == "ASSIGNED"
        assert asg["staff_id"] == tech["id"]
        assert asg["case_id"] == workspace["case"]["id"]


class TestAssignmentWindowsAndRelease:
    def test_computed_read_case_lists_reverse_reachability(self, api):
        """PRD §3.4: "A case's team is listed through the case's assignment
        collection, and a staff member's commitments through the member's own
        assignment collection."
        PRD §3.4: "A created assignment records the staffed case as its `case_id`,
        copies its `window_start` and `window_end` from the case's
        `scheduled_start` and `scheduled_end` at that moment, and starts in
        `ASSIGNED`."

        Design: Corner/endpoints/computed_read_case_lists_reverse_reachability
        """
        workspace = setup_case_workspace()
        tech = create_scrub_technologist()
        asg = assign_staff(workspace["case"]["id"], tech["id"], "SCRUB")
        assert_instant_equals(asg["window_start"], "2026-08-10T09:00:00Z")
        assert_instant_equals(asg["window_end"], "2026-08-10T10:30:00Z")

        via_case, meta_case = validate_paginated(
            api.list_case_staff_assignments(workspace["case"]["id"], SCHEDULER))
        via_staff, meta_staff = validate_paginated(
            api.list_staff_assignments(tech["id"], SCHEDULER))
        assert meta_case["total_count"] == 1 and meta_staff["total_count"] == 1
        assert via_case[0]["id"] == asg["id"] == via_staff[0]["id"]

    def test_double_release_assignment_returns_invalid_state(self, api):
        """PRD §3.4: "The scheduler can release an assignment manually; releasing
        one that is not `ASSIGNED` is refused with
        `ERR_ASSIGNMENT_INVALID_STATE`."

        Design: Corner/state_machines/double_release_assignment_returns_invalid_state
        """
        workspace = setup_case_workspace()
        tech = create_scrub_technologist()
        asg = assign_staff(workspace["case"]["id"], tech["id"], "SCRUB")
        released = validate_success(
            api.release_staff_assignment(asg["id"], SCHEDULER))
        assert released["status"] == "RELEASED"
        resp = api.release_staff_assignment(asg["id"], SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_INVALID_STATE,
                       expected_status=409)
        current, _ = validate_paginated(
            api.list_case_staff_assignments(workspace["case"]["id"], SCHEDULER))
        assert current[0]["status"] == "RELEASED", "the second release is no no-op"

    def test_staff_deactivation_blocked_by_active_assignment(self, api):
        """PRD §3.1: "Activation and deactivation are scheduler operations on
        `is_active`; deactivation is refused with `ERR_RESOURCE_IN_USE` while the
        member still holds `ASSIGNED` assignments on cases that have not reached a
        terminal state."

        Design: Corner/state_machines/staff_deactivation_blocked_by_active_assignment
        """
        workspace = setup_case_workspace()
        tech = create_scrub_technologist()
        asg = assign_staff(workspace["case"]["id"], tech["id"], "SCRUB")
        resp = api.patch_staff(tech["id"], {"is_active": False}, SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_RESOURCE_IN_USE, expected_status=409)
        validate_success(api.release_staff_assignment(asg["id"], SCHEDULER))
        patched = validate_success(
            api.patch_staff(tech["id"], {"is_active": False}, SCHEDULER))
        assert patched["is_active"] is False


class TestStartGates:
    def test_start_without_staffing_returns_staffing_incomplete(self, api):
        """PRD §3.7: "the assigned room must still be `ACTIVE`
        (`ERR_ROOM_NOT_ACTIVE`), and staffing must be complete, meaning at least
        one `ASSIGNED` assignment with `role_in_case` `SCRUB` and at least one
        `ASSIGNED` assignment with `CIRCULATOR` (`ERR_STAFFING_INCOMPLETE`)."
        PRD §3.7: "A successful start moves the case `SCHEDULED` → `IN_PROGRESS`,
        stamps `actual_start` from the logical clock — it stays null until this
        moment — and increments the case `version` by one."

        Design: Corner/state_machines/start_without_staffing_returns_staffing_incomplete
        """
        workspace = setup_case_workspace()
        case = workspace["case"]
        resp = api.start_case(
            case["id"],
            make_interventional_cardiologist_headers(
                workspace["physician"]["id"]))
        validate_error(resp, ApiErrorId.ERR_STAFFING_INCOMPLETE,
                       expected_status=422)
        current = validate_success(api.get_case(case["id"], SCHEDULER))
        assert current["status"] == "SCHEDULED"
        assert current["actual_start"] is None

    def test_start_by_non_performing_cardiologist_returns_forbidden(self, api):
        """PRD §3.7: "The performing cardiologist starts the case, and no one else
        can: the acting `X-User-ID` must equal the case's
        `performing_physician_id`, otherwise the start is refused with
        `ERR_NOT_PERFORMING_PHYSICIAN`."

        Design: Corner/state_machines/start_by_non_performing_cardiologist_returns_forbidden
        """
        workspace = setup_case_workspace()
        case = workspace["case"]
        scrub_tech = create_scrub_technologist()
        nurse = create_circulating_nurse()
        staff_case(case["id"], scrub_tech["id"], nurse["id"])
        other = create_cardiologist(full_name="Dr Other")
        resp = api.start_case(
            case["id"], make_interventional_cardiologist_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_PERFORMING_PHYSICIAN,
                       expected_status=403)
        current = validate_success(api.get_case(case["id"], SCHEDULER))
        assert current["status"] == "SCHEDULED"
