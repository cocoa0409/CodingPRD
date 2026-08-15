"""Membership intake, leave, and the join/leave/rejoin headcount invariant."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_members,
    create_active_group,
    create_group_draft,
    create_membership_payload,
    create_open_program,
    create_sponsor,
    make_employee_headers,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import DEI_HEADERS


class TestMemberCount:
    def test_membership_computed_count_on_group(self, api):
        """PRD §3.3: "Either way the group's `active_member_count` — the count of that group's memberships in `ACTIVE` status — rises by 1."

        Design: Corner/entities/membership_computed_count_on_group
        """
        program = create_open_program(100000)
        group = create_group_draft(program["id"], "Counted", "AFFINITY", "emp_l22")
        add_members(group["id"], ["emp_k1", "emp_k2", "emp_k3"])
        data = validate_success(api.get_group(group["id"], DEI_HEADERS), 200)
        assert data["active_member_count"] == 3

    def test_duplicate_active_membership_rejected(self, api):
        """PRD §3.3: "If an `ACTIVE` row already exists for the pair, the join is rejected with `ERR_ALREADY_MEMBER`."

        Design: Corner/validations/duplicate_active_membership_rejected
        """
        program = create_open_program(100000)
        group = create_group_draft(program["id"], "Dup Member", "AFFINITY", "emp_l38")
        resp = api.create_membership(
            create_membership_payload(group["id"]), make_employee_headers("emp_x")
        )
        validate_success(resp, 201)
        resp = api.create_membership(
            create_membership_payload(group["id"]), make_employee_headers("emp_x")
        )
        validate_error(resp, ApiErrorId.ERR_ALREADY_MEMBER.value, 409)


class TestLeave:
    def test_double_leave_returns_invalid_state(self, api):
        """PRD §3.3: "Leaving a row that is not `ACTIVE` is rejected with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/double_leave_returns_invalid_state
        """
        program = create_open_program(100000)
        group = create_group_draft(program["id"], "Leave Twice", "AFFINITY", "emp_l28")
        resp = api.create_membership(
            create_membership_payload(group["id"]), make_employee_headers("emp_x")
        )
        membership = validate_success(resp, 201)

        resp = api.leave_membership(membership["id"], make_employee_headers("emp_x"))
        data = validate_success(resp, 200)
        assert data["status"] == "INACTIVE"

        # The same leave trigger a second time finds no ACTIVE row.
        resp = api.leave_membership(membership["id"], make_employee_headers("emp_x"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)


class TestJoinGates:
    def test_join_suspended_group_rejected(self, api):
        """PRD §3.3: "The group must be in one of `CHARTER_DRAFT`, `SUBMITTED`, `SPONSOR_ENDORSED`, `CHANGES_REQUESTED`, or `ACTIVE` — a group in any other status rejects joins with `ERR_GROUP_NOT_ACCEPTING_MEMBERS`."

        Design: Corner/validations/join_suspended_group_rejected
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp28", max_groups=3, max_mentees=2)
        group = create_active_group(
            program["id"], sponsor["id"], "Suspend Join", "AFFINITY", "emp_l43"
        )
        resp = api.set_group_status(group["id"], {"to_status": "SUSPENDED"}, DEI_HEADERS)
        validate_success(resp, 200)

        resp = api.create_membership(
            create_membership_payload(group["id"], employee_id="emp_late"), DEI_HEADERS
        )
        validate_error(resp, ApiErrorId.ERR_GROUP_NOT_ACCEPTING_MEMBERS.value, 409)


class TestJoinLeaveRejoinConservation:
    def test_join_leave_returns_count_to_baseline(self, api):
        """PRD §3.3: "Either way the group's `active_member_count` — the count of that group's memberships in `ACTIVE` status — rises by 1."
        PRD §3.3: "Leaving moves a membership `ACTIVE` → `INACTIVE`, stamps `left_at` with the current logical time, and drops `active_member_count` by 1."

        Design: Difficulty/compensating_invariant/membership_join_leave_rejoin_conservation
        """
        program = create_open_program(100000)
        group = create_group_draft(program["id"], "Headcount", "AFFINITY", "emp_l18")

        resp = api.create_membership(
            create_membership_payload(group["id"]), make_employee_headers("emp_x")
        )
        membership = validate_success(resp, 201)
        data = validate_success(api.get_group(group["id"], DEI_HEADERS), 200)
        assert data["active_member_count"] == 1, "join is +1"

        resp = api.leave_membership(membership["id"], make_employee_headers("emp_x"))
        validate_success(resp, 200)
        data = validate_success(api.get_group(group["id"], DEI_HEADERS), 200)
        assert data["active_member_count"] == 0, "leave is -1: back to baseline"

    def test_rejoin_reactivates_same_row_in_place(self, api):
        """PRD §3.3: "Joining is an upsert keyed on the (group, employee) pair: if an `INACTIVE` row already exists for the pair it is reactivated in place (status back to `ACTIVE`, `joined_at` set to the current logical time, `left_at` cleared to null); otherwise a new row is created in `ACTIVE` status with `joined_at` set and `left_at` null."

        Design: Difficulty/compensating_invariant/membership_join_leave_rejoin_conservation
        """
        program = create_open_program(100000)
        group = create_group_draft(program["id"], "Headcount", "AFFINITY", "emp_l18")

        first = validate_success(
            api.create_membership(
                create_membership_payload(group["id"]), make_employee_headers("emp_x")
            ),
            201,
        )
        validate_success(api.leave_membership(first["id"], make_employee_headers("emp_x")), 200)

        second = validate_success(
            api.create_membership(
                create_membership_payload(group["id"]), make_employee_headers("emp_x")
            ),
            201,
        )
        assert second["id"] == first["id"], "rejoin reactivates the same row in place"

        row = validate_success(api.get_membership(first["id"], DEI_HEADERS), 200)
        assert row["status"] == "ACTIVE"
        assert row["left_at"] is None

        group_data = validate_success(api.get_group(group["id"], DEI_HEADERS), 200)
        assert group_data["active_member_count"] == 1
