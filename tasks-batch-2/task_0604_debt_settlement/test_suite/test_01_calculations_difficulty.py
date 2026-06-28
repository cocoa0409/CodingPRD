"""Difficulty-queue tests for the dual-variant savings/reserve calculations and
combinatorial offer-quote / portfolio rounding formulas."""
import pytest
from test_helpers import (
    TEST_USERS, make_client_headers,
    validate_success, get_success_data,
    create_offer_payload, accept_offer_payload, create_lawsuit_payload,
    set_clock, create_client, create_program, create_debt,
    create_offer, accept_offer, fund_settlement, complete_settlement,
    get_account_for_program,
)

ADMIN = TEST_USERS["program_admin_headers"]
AGENT = TEST_USERS["negotiation_agent_headers"]


# =========================================================================
# Difficulty/dual_variant_calc
# =========================================================================
class TestDualVariantSavings:

    def test_estimated_and_realized_savings_diverge(self, api):
        """PRD §3.12: "The **estimated** figure, `estimated_total_savings`, is a
        forward-looking projection over the still-open debts — those in `ENROLLED`,
        `IN_NEGOTIATION`, or `LAWSUIT` status (withdrawn and already-settled debts are
        excluded)."
        PRD §3.12: "The **realized** figure, `realized_total_savings`, tallies only debts
        that have actually reached `SETTLED`. For each settled debt the contribution is
        its `original_balance` minus its actual `settled_amount` minus the fee accrued on
        its settlement."

        Design: Difficulty/dual_variant_calc/portfolio_estimated_vs_realized_savings_diverge
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Dana Debtor", email="dana@x.com", state_code="CA")
        program = create_program(client["id"], monthly_deposit_amount=600,
                                 target_settlement_pct=0.50, reserve_floor=0)
        debt_a = create_debt(program["id"], creditor_name="Cred A",
                             account_number="AA-1", original_balance=4000)
        debt_b = create_debt(program["id"], creditor_name="Cred B",
                             account_number="BB-2", original_balance=5000)
        activated = get_success_data(api.activate_program(program["id"], ADMIN))
        v = activated["version"]
        for m in range(1, 7):
            api.create_deposit(
                {"program_id": program["id"], "scheduled_for": f"2026-{m:02d}-15T00:00:00Z",
                 "amount": 600}, make_client_headers(client["id"]))
        offer_b = create_offer(program["id"], debt_b["id"], offer_pct=0.40,
                              due_date="2026-09-01T00:00:00Z")
        accept_offer(offer_b["id"], v)
        settle_b = fund_settlement(program["id"], offer_b["id"])
        complete_settlement(settle_b["id"])

        prog = get_success_data(api.get_program(program["id"], ADMIN))
        # open debt 4000 only: 4000 - 2000 - 500
        assert prog["estimated_total_savings"] == pytest.approx(1500.00, abs=0.01)
        # settled debt 5000: 5000 - 2000 - 500
        assert prog["realized_total_savings"] == pytest.approx(2500.00, abs=0.01)
        assert prog["estimated_total_savings"] != prog["realized_total_savings"]

    def test_realized_counts_only_settled_debt(self, api):
        """PRD §3.12: "The **realized** figure, `realized_total_savings`, tallies only debts
        that have actually reached `SETTLED`. For each settled debt the contribution is
        its `original_balance` minus its actual `settled_amount` minus the fee accrued on
        its settlement."

        Design: Difficulty/dual_variant_calc/portfolio_estimated_vs_realized_savings_diverge
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Dana Two", email="dana2@x.com", state_code="CA")
        program = create_program(client["id"], monthly_deposit_amount=600,
                                 target_settlement_pct=0.50, reserve_floor=0)
        debt_a = create_debt(program["id"], creditor_name="Cred A",
                             account_number="AA-1", original_balance=4000)
        debt_b = create_debt(program["id"], creditor_name="Cred B",
                             account_number="BB-2", original_balance=5000)
        activated = get_success_data(api.activate_program(program["id"], ADMIN))
        v = activated["version"]
        for m in range(1, 7):
            api.create_deposit(
                {"program_id": program["id"], "scheduled_for": f"2026-{m:02d}-15T00:00:00Z",
                 "amount": 600}, make_client_headers(client["id"]))
        offer_b = create_offer(program["id"], debt_b["id"], offer_pct=0.40,
                              due_date="2026-09-01T00:00:00Z")
        accept_offer(offer_b["id"], v)
        settle_b = fund_settlement(program["id"], offer_b["id"])
        complete_settlement(settle_b["id"])

        prog = get_success_data(api.get_program(program["id"], ADMIN))
        # only the SETTLED 5000 debt contributes to realized: 5000 - 2000 - 500
        assert prog["realized_total_savings"] == pytest.approx(2500.00, abs=0.01)

    def test_instantaneous_balance_vs_projected_reserve_diverge(self, api):
        """PRD §3.6: "The projected balance is the dedicated account's current `balance` plus the program's `monthly_deposit_amount` for each scheduled deposit day that falls strictly after the current logical clock and on or before the offer's `due_date` (the projection window is open at the lower end and closed at the `due_date`)."
        PRD §3.6: "Acceptance passes only when that projected balance is at least the sum of the offer's `settlement_amount`, its `projected_fee`, and the account's `reserve_floor`; otherwise it is the projected shortfall described above."

        Design: Difficulty/dual_variant_calc/account_balance_instantaneous_vs_projected_diverge
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Pat Proj", email="pat@x.com", state_code="TX")
        program = create_program(client["id"], monthly_deposit_amount=600,
                                 deposit_day_of_month=15, reserve_floor=0)
        debt = create_debt(program["id"], creditor_name="Cred",
                          account_number="C-1", original_balance=5000)
        activated = get_success_data(api.activate_program(program["id"], ADMIN))
        v1 = activated["version"]
        for m in (3, 4):
            api.create_deposit(
                {"program_id": program["id"], "scheduled_for": f"2026-{m:02d}-15T00:00:00Z",
                 "amount": 600}, make_client_headers(client["id"]))
        offer = create_offer(program["id"], debt["id"], offer_pct=0.40,
                            due_date="2026-08-20T00:00:00Z")

        acct = get_account_for_program(program["id"])
        assert acct["balance"] == pytest.approx(1200.00, abs=0.01), \
            "instantaneous balance is two CLEARED deposits"

        accept_res = api.accept_offer(offer["id"], accept_offer_payload(v1), AGENT)
        accepted = validate_success(accept_res, 200)
        # projected 1200 + 3*600 (Jun15,Jul15,Aug15) = 3000 >= 2000 + 500 + 0
        assert accepted["status"] == "ACCEPTED"

    def test_acceptance_requires_forward_looking_projection_not_instantaneous(self, api):
        """PRD §3.6: "The **forward-looking reserve check** asks whether the account is
        projected to cover this settlement by the offer's `due_date` without breaching the
        protective floor."
        PRD §3.6: "Acceptance passes only when that projected balance is at least the sum of the offer's `settlement_amount`, its `projected_fee`, and the account's `reserve_floor`; otherwise it is the projected shortfall described above."

        Design: Difficulty/dual_variant_calc/account_balance_instantaneous_vs_projected_diverge
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Proj Two", email="proj2@x.com", state_code="TX")
        program = create_program(client["id"], monthly_deposit_amount=600,
                                 deposit_day_of_month=15, reserve_floor=0)
        debt = create_debt(program["id"], creditor_name="Cred",
                          account_number="C-2", original_balance=5000)
        activated = get_success_data(api.activate_program(program["id"], ADMIN))
        v1 = activated["version"]
        for m in (3, 4):
            api.create_deposit(
                {"program_id": program["id"], "scheduled_for": f"2026-{m:02d}-15T00:00:00Z",
                 "amount": 600}, make_client_headers(client["id"]))
        offer = create_offer(program["id"], debt["id"], offer_pct=0.40,
                            due_date="2026-08-20T00:00:00Z")
        acct = get_account_for_program(program["id"])
        # instantaneous 1200 is strictly below the 2500 requirement
        assert acct["balance"] < 2500.00
        accept_res = api.accept_offer(offer["id"], accept_offer_payload(v1), AGENT)
        accepted = validate_success(accept_res, 200)
        assert accepted["status"] == "ACCEPTED"


# =========================================================================
# Difficulty/combinatorial_formula
# =========================================================================
class TestOfferQuoteAndRounding:

    def test_litigated_offer_quote_surcharge_capped(self, api):
        """PRD §3.5: "The `projected_fee` is then computed on that rounded principal: `settlement_amount` multiplied by the effective fee rate, again rounded half-up to two decimal places."
        PRD §3.5: "for a litigated debt the effective rate is the smaller of (the frozen rate plus 0.03) and 0.25, while for an `ENROLLED` or `IN_NEGOTIATION` debt no surcharge applies and the effective rate is exactly the frozen rate."

        Design: Difficulty/combinatorial_formula/offer_quote_conditional_surcharge_tier_min_cap
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Lee Litig", email="lee@x.com", state_code="NY")
        program = create_program(client["id"], monthly_deposit_amount=800)
        debt_big = create_debt(program["id"], creditor_name="Big Cred",
                              account_number="BIG-1", original_balance=6000)
        create_debt(program["id"], creditor_name="Small Cred",
                   account_number="SM-2", original_balance=4000)
        get_success_data(api.activate_program(program["id"], ADMIN))
        get_success_data(api.create_lawsuit(
            create_lawsuit_payload(program["id"], debt_big["id"],
                                  court_reference="CASE-99", filed_at="2026-05-01T00:00:00Z"),
            ADMIN))
        offer = get_success_data(api.create_offer(
            create_offer_payload(program["id"], debt_big["id"], offer_pct=0.50,
                                due_date="2026-12-01T00:00:00Z"), AGENT))
        assert offer["settlement_amount"] == pytest.approx(3000.00, abs=0.01)
        # 3000 * min(0.22 + 0.03, 0.25) = 3000 * 0.25
        assert offer["projected_fee"] == pytest.approx(750.00, abs=0.01)

    def test_litigation_surcharge_does_not_mutate_frozen_rate(self, api):
        """PRD §3.2: "At the instant a debt is enrolled, the system snapshots that debt's settlement-fee rate, `fee_rate_pct`, and freezes it for the life of the debt."
        PRD §3.5: "when the debt is in `LAWSUIT` status, the effective rate carries a litigation surcharge of 0.03 added to the base rate, with the result capped so it never exceeds 0.25."

        Design: Difficulty/combinatorial_formula/offer_quote_conditional_surcharge_tier_min_cap
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Lee Two", email="lee2@x.com", state_code="NY")
        program = create_program(client["id"], monthly_deposit_amount=800)
        # Enroll the small debt first so the litigated debt is snapshotted when the
        # program's running total reaches 10000 (PRD §3.2 freezes the band from the
        # running total at the instant of enrollment): 4000 then +6000 = 10000 -> 0.22.
        create_debt(program["id"], creditor_name="Small Cred",
                   account_number="SM-2", original_balance=4000)
        debt_big = create_debt(program["id"], creditor_name="Big Cred",
                              account_number="BIG-1", original_balance=6000)
        get_success_data(api.activate_program(program["id"], ADMIN))
        get_success_data(api.create_lawsuit(
            create_lawsuit_payload(program["id"], debt_big["id"],
                                  court_reference="CASE-99", filed_at="2026-05-01T00:00:00Z"),
            ADMIN))
        debt = get_success_data(api.get_debt(debt_big["id"], ADMIN))
        # frozen tier from total 10000 -> 0.22; surcharge applies only to the offer's
        # effective rate, not the snapshot.
        assert debt["fee_rate_pct"] == pytest.approx(0.22, abs=0.0001)

    def test_portfolio_estimate_rounds_per_debt_then_sums(self, api):
        """PRD §3.12: "For each such debt the system computes an estimated settlement equal to the debt's `original_balance` multiplied by the program's `target_settlement_pct`, rounded half-up to two decimal places; ... and an estimated fee equal to the estimated settlement multiplied by the estimated rate, rounded half-up to two decimal places."
        PRD §3.12: "Both figures use per-debt rounding before summation; withdrawn debts appear in neither."

        Design: Difficulty/combinatorial_formula/portfolio_savings_round_per_debt_then_sum
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Rou Nd", email="rnd@x.com", state_code="CA")
        program = create_program(client["id"], monthly_deposit_amount=100,
                                 target_settlement_pct=0.50)
        create_debt(program["id"], creditor_name="C1", account_number="R-1",
                   original_balance=333)
        create_debt(program["id"], creditor_name="C2", account_number="R-2",
                   original_balance=777)
        get_success_data(api.activate_program(program["id"], ADMIN))
        prog = get_success_data(api.get_program(program["id"], ADMIN))
        # debt 333: s=166.50 f=41.63 sav=124.87; debt 777: s=388.50 f=97.13 sav=291.37
        assert prog["estimated_total_savings"] == pytest.approx(416.24, abs=0.01)

    def test_portfolio_estimate_includes_both_open_debts(self, api):
        """PRD §3.12: "The debt's contribution to the estimate is its `original_balance` minus the estimated settlement minus the estimated fee, and the program total is the sum of those per-debt contributions."

        Design: Difficulty/combinatorial_formula/portfolio_savings_round_per_debt_then_sum
        """
        set_clock("2026-06-01T00:00:00Z")
        client = create_client(full_name="Rnd Two", email="rnd2@x.com", state_code="CA")
        program = create_program(client["id"], monthly_deposit_amount=100,
                                 target_settlement_pct=0.50)
        create_debt(program["id"], creditor_name="C1", account_number="R-1",
                   original_balance=333)
        create_debt(program["id"], creditor_name="C2", account_number="R-2",
                   original_balance=777)
        get_success_data(api.activate_program(program["id"], ADMIN))
        prog = get_success_data(api.get_program(program["id"], ADMIN))
        # 124.87 + 291.37 == 416.24 (both ENROLLED debts feed the estimate)
        assert prog["estimated_total_savings"] == pytest.approx(416.24, abs=0.01)
