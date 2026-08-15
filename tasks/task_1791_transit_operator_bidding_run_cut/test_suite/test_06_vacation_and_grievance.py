"""Vacation-week allocation order/boundaries and grievance outcomes."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_grievance,
    create_operator,
    create_period,
    create_vacation_slot,
    get_operator,
    get_vacation_slot,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

SO = TEST_USERS["scheduling_officer_headers"]
UR = TEST_USERS["union_rep_headers"]


class TestVacationGrantOrdering:
    def test_insufficient_balance_beats_full_slot(self, api):
        """PRD §3.9: "Granting a week to an operator enforces two checks in
        order: first the operator's `vacation_hours_balance` must cover a full
        forty-hour vacation week — a smaller balance is rejected with
        `ERR_INSUFFICIENT_VACATION_BALANCE` — and then the slot must still have
        room, `allocated_count` below `capacity`, with a full slot rejected as
        `ERR_VACATION_SLOT_FULL`."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_vacation_grant
        """
        period = create_period(name="V")
        opx = create_operator(employee_number="EX", full_name="Op X",
                              hire_date="2000-01-01", vacation_hours_balance=200)
        opy = create_operator(employee_number="EY", full_name="Op Y",
                              hire_date="2001-01-01", vacation_hours_balance=0)
        slot = create_vacation_slot(period["id"], week_start_date="2026-10-05", capacity=1)
        validate_success(api.grant_vacation_slot(slot["id"], {"operator_id": opx["id"]}, SO))
        assert get_vacation_slot(period["id"], slot["id"])["status"] == "FULLY_ALLOCATED"
        # opy has insufficient balance AND the slot is full: balance check first.
        resp = api.grant_vacation_slot(slot["id"], {"operator_id": opy["id"]}, SO)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_VACATION_BALANCE)

    def test_rejected_grant_leaves_allocated_count_unchanged(self, api):
        """PRD §3.9: "Granting a week to an operator enforces two checks in
        order: first the operator's `vacation_hours_balance` must cover a full
        forty-hour vacation week — a smaller balance is rejected with
        `ERR_INSUFFICIENT_VACATION_BALANCE` — and then the slot must still have
        room, `allocated_count` below `capacity`, with a full slot rejected as
        `ERR_VACATION_SLOT_FULL`."

        Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_vacation_grant
        """
        period = create_period(name="V2")
        opx = create_operator(employee_number="EX", full_name="Op X",
                              hire_date="2000-01-01", vacation_hours_balance=200)
        opy = create_operator(employee_number="EY", full_name="Op Y",
                              hire_date="2001-01-01", vacation_hours_balance=0)
        slot = create_vacation_slot(period["id"], capacity=1)
        validate_success(api.grant_vacation_slot(slot["id"], {"operator_id": opx["id"]}, SO))
        resp = api.grant_vacation_slot(slot["id"], {"operator_id": opy["id"]}, SO)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_VACATION_BALANCE)
        assert get_vacation_slot(period["id"], slot["id"])["allocated_count"] == 1


class TestVacationCapacityBoundary:
    def _full_slot(self, api):
        period = create_period(name="VB")
        opx = create_operator(employee_number="EX", full_name="Op X",
                              hire_date="2000-01-01", vacation_hours_balance=200)
        opy = create_operator(employee_number="EY", full_name="Op Y",
                              hire_date="2001-01-01", vacation_hours_balance=200)
        slot = create_vacation_slot(period["id"], capacity=1)
        validate_success(api.grant_vacation_slot(slot["id"], {"operator_id": opx["id"]}, SO))
        return period, opx, opy, slot

    def test_grant_at_capacity_rejected_slot_full(self, api):
        """PRD §3.9: "and then the slot must still have room, `allocated_count`
        below `capacity`, with a full slot rejected as `ERR_VACATION_SLOT_FULL`"
        PRD §3.9: "when the count reaches capacity the slot moves from `OPEN`
        to `FULLY_ALLOCATED`"

        Design: Difficulty/boundary_precision_check/vacation_slot_capacity_full_boundary
        """
        period, opx, opy, slot = self._full_slot(api)
        resp = api.grant_vacation_slot(slot["id"], {"operator_id": opy["id"]}, SO)
        validate_error(resp, ApiErrorId.ERR_VACATION_SLOT_FULL)
        assert get_vacation_slot(period["id"], slot["id"])["status"] == "FULLY_ALLOCATED"

    def test_rejected_grant_does_not_debit_balance(self, api):
        """PRD §3.9: "A successful grant increments `allocated_count` by one,
        debits 40 hours from the operator's balance, and records the grant on
        the slot's `operator_id`"

        Design: Difficulty/boundary_precision_check/vacation_slot_capacity_full_boundary
        """
        period, opx, opy, slot = self._full_slot(api)
        resp = api.grant_vacation_slot(slot["id"], {"operator_id": opy["id"]}, SO)
        validate_error(resp, ApiErrorId.ERR_VACATION_SLOT_FULL)
        assert get_operator(opy["id"])["vacation_hours_balance"] == 200

    def test_nth_grant_succeeds_n_plus_one_fails(self, api):
        """PRD §3.9: "Competing grant requests are adjudicated in request
        order, first come first served until capacity fills."
        PRD §3.9: "and then the slot must still have room, `allocated_count`
        below `capacity`, with a full slot rejected as `ERR_VACATION_SLOT_FULL`"

        Design: Difficulty/resource_temporal_overlap/vacation_slot_capacity_exclusion_window
        """
        period = create_period(name="VC")
        ops = [
            create_operator(employee_number=f"E{c}", full_name=f"Op {c}",
                            hire_date=f"200{i}-01-01", vacation_hours_balance=200)
            for i, c in enumerate("ABC")
        ]
        slot = create_vacation_slot(period["id"], capacity=2)
        validate_success(api.grant_vacation_slot(slot["id"], {"operator_id": ops[0]["id"]}, SO))
        validate_success(api.grant_vacation_slot(slot["id"], {"operator_id": ops[1]["id"]}, SO))
        assert get_vacation_slot(period["id"], slot["id"])["allocated_count"] == 2
        resp = api.grant_vacation_slot(slot["id"], {"operator_id": ops[2]["id"]}, SO)
        validate_error(resp, ApiErrorId.ERR_VACATION_SLOT_FULL)

    def test_slot_fully_allocated_at_capacity(self, api):
        """PRD §3.9: "when the count reaches capacity the slot moves from
        `OPEN` to `FULLY_ALLOCATED`"

        Design: Difficulty/resource_temporal_overlap/vacation_slot_capacity_exclusion_window
        """
        period = create_period(name="VC2")
        ops = [
            create_operator(employee_number=f"E{c}", full_name=f"Op {c}",
                            hire_date=f"200{i}-01-01", vacation_hours_balance=200)
            for i, c in enumerate("ABC")
        ]
        slot = create_vacation_slot(period["id"], capacity=2)
        validate_success(api.grant_vacation_slot(slot["id"], {"operator_id": ops[0]["id"]}, SO))
        validate_success(api.grant_vacation_slot(slot["id"], {"operator_id": ops[1]["id"]}, SO))
        assert get_vacation_slot(period["id"], slot["id"])["status"] == "FULLY_ALLOCATED"
        resp = api.grant_vacation_slot(slot["id"], {"operator_id": ops[2]["id"]}, SO)
        validate_error(resp, ApiErrorId.ERR_VACATION_SLOT_FULL)


class TestVacationBalanceConservation:
    def _setup(self, api):
        period = create_period(name="VI")
        operator = create_operator(employee_number="E1", full_name="Op One",
                                   hire_date="2000-01-01", vacation_hours_balance=200)
        slot = create_vacation_slot(period["id"], capacity=1)
        return period, operator, slot

    def test_successful_grant_debits_40_and_increments_count(self, api):
        """PRD §3.9: "A successful grant increments `allocated_count` by one,
        debits 40 hours from the operator's balance, and records the grant on
        the slot's `operator_id`; when the count reaches capacity the slot
        moves from `OPEN` to `FULLY_ALLOCATED`."

        Design: Difficulty/compensating_invariant/vacation_balance_conservation
        """
        period, operator, slot = self._setup(api)
        validate_success(api.grant_vacation_slot(slot["id"], {"operator_id": operator["id"]}, SO))
        assert get_operator(operator["id"])["vacation_hours_balance"] == 160
        assert get_vacation_slot(period["id"], slot["id"])["allocated_count"] == 1

    def test_rejected_second_grant_conserves_balance_and_count(self, api):
        """PRD §3.9: "A successful grant increments `allocated_count` by one,
        debits 40 hours from the operator's balance, and records the grant on
        the slot's `operator_id`"
        PRD §3.9: "and then the slot must still have room, `allocated_count`
        below `capacity`, with a full slot rejected as `ERR_VACATION_SLOT_FULL`"

        Design: Difficulty/compensating_invariant/vacation_balance_conservation
        """
        period, operator, slot = self._setup(api)
        validate_success(api.grant_vacation_slot(slot["id"], {"operator_id": operator["id"]}, SO))
        # Slot is now FULLY_ALLOCATED; the operator's balance is 160 (>= 40),
        # so the capacity check is the one that fails.
        resp = api.grant_vacation_slot(slot["id"], {"operator_id": operator["id"]}, SO)
        validate_error(resp, ApiErrorId.ERR_VACATION_SLOT_FULL)
        assert get_operator(operator["id"])["vacation_hours_balance"] == 160
        assert get_vacation_slot(period["id"], slot["id"])["allocated_count"] == 1


class TestGrievanceRemedyConservation:
    def _filed_ot_grievance(self, api):
        period = create_period(name="GR")
        opg = create_operator(employee_number="EG", full_name="Op G",
                              hire_date="2000-01-01", vacation_hours_balance=0)
        oph = create_operator(employee_number="EH", full_name="Op H",
                              hire_date="2001-01-01", vacation_hours_balance=0)
        case = create_grievance(
            opg["id"], period["id"],
            category="OT_EQUALIZATION",
            detail="junior got OT while I sat",
        )
        return period, opg, oph, case

    def test_dismiss_leaves_ot_accumulators_unchanged(self, api):
        """PRD §3.9: "A `UnionRep` may instead dismiss the case, moving it from
        `FILED` to `DISMISSED`, and the filing operator — only that operator —
        may withdraw it, moving it from `FILED` to `WITHDRAWN`."
        PRD §3.9: "A `UnionRep` may uphold a case — optionally supplying
        `remedy_minutes` — moving it from `FILED` to `UPHELD` and crediting
        those remedy minutes to the filing operator's `weekly_ot_minutes_accum`
        as the compensating make-whole."

        Design: Difficulty/compensating_invariant/ot_remedy_minutes_conservation
        """
        _period, opg, oph, case = self._filed_ot_grievance(api)
        resp = api.dismiss_grievance_case(case["id"], UR)
        dismissed = validate_success(resp)
        assert dismissed["status"] == "DISMISSED"
        assert get_operator(opg["id"])["weekly_ot_minutes_accum"] == 0
        assert get_operator(oph["id"])["weekly_ot_minutes_accum"] == 0

    def test_dismiss_terminal_and_no_remedy_credited(self, api):
        """PRD §3.9: "A `UnionRep` may instead dismiss the case, moving it from
        `FILED` to `DISMISSED`, and the filing operator — only that operator —
        may withdraw it, moving it from `FILED` to `WITHDRAWN`."
        PRD §3.9: "All three outcomes are terminal."
        PRD §3.9: "the case enters `FILED` with `remedy_minutes` at 0"

        Design: Difficulty/compensating_invariant/ot_remedy_minutes_conservation
        """
        _period, opg, _oph, case = self._filed_ot_grievance(api)
        validate_success(api.dismiss_grievance_case(case["id"], UR))
        # remedy_minutes stays 0 on the dismissed case.
        fetched = validate_success(api.get_grievance_case(case["id"], UR))
        assert fetched["status"] == "DISMISSED"
        assert fetched["remedy_minutes"] == 0
        assert get_operator(opg["id"])["weekly_ot_minutes_accum"] == 0
