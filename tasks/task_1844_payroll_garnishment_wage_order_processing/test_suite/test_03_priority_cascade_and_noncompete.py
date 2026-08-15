"""Waterfall priority: satisfaction cascade, creditor non-compete, and the
fixed validation firing order between state checks and business rules."""
from test_helpers import (
    ApiErrorId,
    add_statement,
    api_client,
    drive_order_to_active,
    get_order,
    get_statement,
    get_success_data,
    make_authority,
    make_employer,
    make_employee,
    make_open_run,
    make_state_rule,
    pay_run_fresh,
    receive_order,
    reject_order_payload,
    set_clock,
    setup_employer_with_employee,
    setup_paid_two_orders,
    terminate_order_payload,
    validate_error,
)
from test_helpers.fixtures import SPECIALIST, MANAGER


class TestSatisfactionFreesPool:
    def test_satisfied_order_frees_pool_within_same_pass(self, api):
        """PRD §3.6: "When an award equals the order's remaining balance before
        the award, the order is satisfied on the spot: its `processing_status`
        becomes `SATISFIED`, its `remit_posture` closes, its final event carries
        the basis `FINAL_PARTIAL`, sibling orders on the same employee absorb
        the freed pool within the same waterfall pass without any re-run, and
        an audit entry (action `order.satisfy`) is appended."
        Order A (FIXED 5000, balance 5000) satisfies; sibling B then takes its
        full 10000 from the freed pool in the same pay pass.

        Design: Difficulty/transitive_cascade/pay_waterfall_cascade_to_satisfy_and_freed_pool
        """
        base = setup_paid_two_orders(
            order_a_overrides={
                "case_number": "CS-A",
                "amount_model": "FIXED_AMOUNT_PER_PERIOD",
                "amount_value": 5000,
                "total_balance_cents": 5000,
                "effective_date": "2026-08-01",
            },
            order_b_overrides={
                "case_number": "CS-B",
                "amount_model": "FIXED_AMOUNT_PER_PERIOD",
                "amount_value": 10000,
                "total_balance_cents": 100000,
                "effective_date": "2026-08-01",
            },
            statement_overrides={
                "gross_earnings_cents": 92500,
                "mandatory_deductions_cents": 30000,
            },
        )
        order_a = base["order_a"]
        order_b = base["order_b"]
        assert order_a["processing_status"] == "SATISFIED"
        assert order_a["remit_posture"] == "CLOSED"
        assert order_a["remaining_balance_cents"] == 0
        assert order_b["withheld_cents"] == 10000

    def test_freed_pool_statement_totals(self, api):
        """PRD §3.6: "The statement's `net_pay_cents`, `total_withheld_cents`
        (the sum of its withholding events, refunds excluded), and
        `total_admin_fee_cents` are finalized here"
        DE 62500, floor 47126, pool 15374; A takes 5000 (satisfies), B takes
        10000: total withheld 15000, net pay 47500 under fee policy NONE.

        Design: Difficulty/transitive_cascade/pay_waterfall_cascade_to_satisfy_and_freed_pool
        """
        base = setup_paid_two_orders(
            order_a_overrides={
                "case_number": "CS-A",
                "amount_model": "FIXED_AMOUNT_PER_PERIOD",
                "amount_value": 5000,
                "total_balance_cents": 5000,
                "effective_date": "2026-08-01",
            },
            order_b_overrides={
                "case_number": "CS-B",
                "amount_model": "FIXED_AMOUNT_PER_PERIOD",
                "amount_value": 10000,
                "total_balance_cents": 100000,
                "effective_date": "2026-08-01",
            },
            statement_overrides={
                "gross_earnings_cents": 92500,
                "mandatory_deductions_cents": 30000,
            },
        )
        stmt = base["statement"]
        assert stmt["total_withheld_cents"] == 15000
        assert stmt["net_pay_cents"] == 47500


class TestStateBeatsDuplicateBusinessSafety:
    def _setup_terminal_order_with_live_duplicate(self):
        """ord_a REJECTED (terminal); ord_b same (order_type, case_number)
        RECEIVED (non-terminal). Intake accepts ord_b because the duplicate
        check only looks at non-terminal orders."""
        base = setup_employer_with_employee()
        ee_id = base["employee"]["id"]
        auth_id = base["authority"]["id"]
        ord_a = receive_order(
            ee_id, auth_id, case_number="CS-DUP", amount_value=1000
        )
        get_success_data(
            api_client.reject_order(ord_a["id"], reject_order_payload(), SPECIALIST)
        )
        ord_b = receive_order(
            ee_id, auth_id, case_number="CS-DUP", amount_value=2000
        )
        return base, ord_a, ord_b

    def test_validate_on_terminal_order_reports_state_not_duplicate(self, api):
        """PRD §2.9: "When several checks could reject the same request, they
        fire in a fixed, system-wide order. Authentication comes first, then
        role authorization (including the segregation-of-duties comparison),
        then existence and parent-chain scoping, then state legality — a
        transition attempted from an illegal state, including any mutation
        aimed at a terminal-state resource, is rejected with
        `ERR_INVALID_STATE` (HTTP 409). Only then do the business rules engage,
        and they too are ordered: period-window and pay-calendar temporal
        checks first, then intake referential checks (authority, case-number
        pattern, state rule), then duplicate-order safety, then the
        stale-version rejection of §2.7, then fiscal amount checks (empty runs,
        deduction bounds), then terminated-employee ineligibility, then refund
        limits, then the posted-event void guard, then remittance emptiness,
        and finally remittable-event availability."
        Validating a REJECTED order that also duplicates a live sibling must
        surface ERR_INVALID_STATE, not ERR_DUPLICATE_ACTIVE_ORDER.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_duplicate_business_safety
        """
        base, ord_a, ord_b = self._setup_terminal_order_with_live_duplicate()
        resp = api_client.validate_order(ord_a["id"], SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_DUPLICATE_ACTIVE_ORDER
        assert get_order(ord_a["id"])["processing_status"] == "REJECTED"

    def test_terminate_on_terminal_order_reports_state_not_duplicate(self, api):
        """PRD §2.9: "then state legality — a transition attempted from an
        illegal state, including any mutation aimed at a terminal-state
        resource, is rejected with `ERR_INVALID_STATE` (HTTP 409). Only then do
        the business rules engage, and they too are ordered: period-window and
        pay-calendar temporal checks first, then intake referential checks
        (authority, case-number pattern, state rule), then duplicate-order
        safety, then the stale-version rejection of §2.7"
        Terminating a REJECTED order while a later non-terminal sibling shares
        its (order_type, case_number) must surface ERR_INVALID_STATE before the
        duplicate-safety check.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_duplicate_business_safety
        """
        base, ord_a, ord_b = self._setup_terminal_order_with_live_duplicate()
        resp = api_client.terminate_order(ord_a["id"], terminate_order_payload(), MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_DUPLICATE_ACTIVE_ORDER
        assert get_order(ord_a["id"])["processing_status"] == "REJECTED"


class TestCreditorNonCompete:
    def test_creditor_blocked_by_support(self, api):
        """PRD §3.6: "One non-compete rule overrides the mechanics: if any
        `CHILD_SUPPORT` order received a positive award in this pass, every
        `CREDITOR` order is skipped outright with an award of zero and a basis
        of `BLOCKED_BY_SUPPORT`."
        CHILD_SUPPORT FIXED 10000 is awarded 10000 (pool 15374 left 5374); the
        CREDITOR FIXED 5000 is skipped entirely despite pool remaining.

        Design: Corner/calculations/creditor_blocked_by_support_noncompete
        """
        set_clock()
        make_state_rule("CA")
        auth_cs = make_authority()
        auth_ct = make_authority(
            name="County Court",
            authority_type="COURT",
            accepted_case_number_pattern="^CV-",
        )
        emp = make_employer()
        ee = make_employee(emp["id"])
        ord_cs = receive_order(
            ee["id"], auth_cs["id"], case_number="CS-P",
            order_type="CHILD_SUPPORT", amount_value=10000,
        )
        ord_cr = receive_order(
            ee["id"], auth_ct["id"], case_number="CV-P",
            order_type="CREDITOR", amount_value=5000,
        )
        drive_order_to_active(ord_cs["id"])
        drive_order_to_active(ord_cr["id"])
        run = make_open_run(emp["id"])
        stmt = add_statement(
            run["id"], ee["id"],
            gross_earnings_cents=92500, mandatory_deductions_cents=30000,
        )
        pay_run_fresh(emp["id"], run["id"])

        assert get_order(ord_cs["id"])["withheld_cents"] == 10000
        assert get_order(ord_cr["id"])["withheld_cents"] == 0
        stmt = get_statement(stmt["id"])
        assert stmt["total_withheld_cents"] == 10000
        line = [b for b in stmt["computation_breakdown"]
                if b["order_id"] == ord_cr["id"]]
        assert len(line) == 1
        assert line[0]["awarded_cents"] == 0
        assert line[0]["basis"] == "BLOCKED_BY_SUPPORT"


class TestAuthorityMismatch:
    def test_creditor_order_from_child_support_agency_rejected(self, api):
        """PRD §3.3: "Compatibility is exact: a `CHILD_SUPPORT` order must come
        from a `CHILD_SUPPORT_AGENCY`; a `FEDERAL_TAX_LEVY` must come from a
        `FEDERAL_AGENCY`; a `CREDITOR` order must come from a `COURT`; a
        `STUDENT_LOAN` order may come from either a `FEDERAL_AGENCY` or a
        `STATE_AGENCY`. Any incompatibility is rejected with
        `ERR_AUTHORITY_MISMATCH` (HTTP 422); a successful validation moves the
        order from `RECEIVED` to `VALIDATED` and appends an audit entry (action
        `order.validate`)."

        Design: Corner/validations/authority_mismatch_at_validate
        """
        base = setup_employer_with_employee(
            authority_overrides={"accepted_case_number_pattern": "^CV-"}
        )
        ord_id = receive_order(
            base["employee"]["id"], base["authority"]["id"],
            case_number="CV-1", order_type="CREDITOR", amount_value=1000,
        )["id"]
        resp = api_client.validate_order(ord_id, SPECIALIST)
        validate_error(resp, ApiErrorId.ERR_AUTHORITY_MISMATCH)
        assert get_order(ord_id)["processing_status"] == "RECEIVED"
