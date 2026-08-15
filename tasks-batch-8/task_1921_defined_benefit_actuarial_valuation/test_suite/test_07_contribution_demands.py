"""Contribution-demand computation, election offsets, delinquency, and invariants."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    create_plan,
    register_prep_and_review_actuaries,
    create_locked_census,
    create_locked_assumption_set,
    create_asset_statement,
    create_asset_valuation,
    create_valuation_run,
    compute_run,
    certify_run,
    get_plan,
    get_plan_version,
    list_demands,
    get_demand,
    get_ledger,
    create_election,
    create_payment,
    list_elections_for_demand,
    set_clock,
    setup_certified_plan,
    api_client,
)

PLAN_ADMIN = TEST_USERS["plan_admin_headers"]

FAMILY_A_ROWS = [
    {"external_ref": "A1", "date_of_birth": "1966-03-10", "status": "ACTIVE",
     "years_of_service": 10, "annual_compensation": 100000},
    {"external_ref": "A2", "date_of_birth": "1968-11-20", "status": "ACTIVE",
     "years_of_service": 5, "annual_compensation": 60000},
    {"external_ref": "R1", "date_of_birth": "1965-01-30", "status": "RETIREE",
     "current_annual_benefit": 50000},
]


def _family_a_certified(sponsor, carryover=None, prefunding=None):
    """Certified Family A plan: FT 67172.20, NC 1958.24, AVA 61000.00.
    shortfall 6172.20, installment 881.74, tentative_minimum 2839.98."""
    return setup_certified_plan(
        sponsor_name=sponsor,
        participant_rows=FAMILY_A_ROWS,
        market_value_begin=60000, contributions_received=0,
        benefits_paid=2000, investment_return=3000,
        initial_carryover_balance=carryover,
        initial_prefunding_balance=prefunding,
        prior_aftap_pct=84.00,
    )


class TestMinimumRequiredEvaluationOrder:
    def test_credit_capped_by_tentative_minimum(self, api):
        """PRD §3.7: "Fifth, `credit_applied` is the total credit pool drawn by
        `EFFECTIVE` elections in waterfall order, capped at `tentative_minimum`.
        Sixth, `minimum_due` is `tentative_minimum` minus `credit_applied`."
        PRD §3.7: "`tentative_minimum` is the normal-cost component plus the
        installment."

        Design: Difficulty/combinatorial_formula/minimum_required_evaluation_order_pinned
        """
        fx = _family_a_certified("Order Co", carryover=2000, prefunding=3000)
        demand = fx["demand"]
        # tentative = NC 1958.24 + installment 881.74 = 2839.98
        assert demand["tentative_minimum"] == 2839.98

        # Election of exactly tentative_minimum is accepted; pool of 5000 offsets only 2839.98
        election = create_election(fx["plan"]["id"], demand["id"], 2839.98)
        d = get_demand(demand["id"])
        assert d["credit_applied"] == 2839.98
        assert d["minimum_due"] == 0.00
        assert d["outstanding_amount"] == 0.00
        assert d["status"] == "SATISFIED"
        # Waterfall: carryover 2000 drawn first, then 839.98 from prefunding
        ledger = get_ledger(fx["plan"]["id"])
        assert ledger["carryover_balance"] == 0.00
        assert ledger["prefunding_balance"] == 2160.02

    def test_tentative_minimum_pinned_components(self, api):
        """PRD §3.7: "the shortfall is `funding_target` minus the asset valuation's
        `smoothed_value`, floored at zero. Third, the shortfall amortization
        installment is one-seventh of the shortfall, rounded half-up to cents...
        Fourth, `tentative_minimum` is the normal-cost component plus the
        installment."

        Design: Difficulty/combinatorial_formula/minimum_required_evaluation_order_pinned
        """
        fx = _family_a_certified("Order 2 Co")
        demand = fx["demand"]
        # shortfall = 67172.20 - 61000.00 = 6172.20; installment = 881.74
        # tentative = 1958.24 + 881.74
        assert demand["tentative_minimum"] == 2839.98
        assert demand["minimum_due"] == 2839.98
        assert demand["outstanding_amount"] == 2839.98


class TestElectionSatisfiesDemand:
    def test_election_application_satisfies_demand_depth2(self, api):
        """PRD §3.8: "Creation draws the ledger down in waterfall order. The
        `carryover_balance` absorbs the election first, up to the full amount; the
        `prefunding_balance` then covers any remainder... `total_applied_to_date`
        increases by the election amount ... and the demand's `credit_applied`,
        `minimum_due`, and `outstanding_amount` are recomputed with the
        auto-transitions of §3.7."
        PRD §3.7: "one that leaves the outstanding amount at exactly zero moves it
        straight to `SATISFIED`".

        Design: Difficulty/transitive_cascade/election_application_satisfies_demand_depth2
        """
        fx = _family_a_certified("Cascade Co", carryover=2000, prefunding=3000)
        demand = fx["demand"]
        assert demand["status"] == "OPEN"

        election = create_election(fx["plan"]["id"], demand["id"], 2839.98)
        assert election["status"] == "EFFECTIVE"
        d = get_demand(demand["id"])
        assert d["credit_applied"] == 2839.98
        assert d["minimum_due"] == 0.00
        assert d["outstanding_amount"] == 0.00
        assert d["status"] == "SATISFIED"

    def test_partial_election_moves_demand_to_partially_satisfied(self, api):
        """PRD §3.7: "A payment or election that leaves `outstanding_amount`
        positive but below `minimum_due` moves it to `PARTIALLY_SATISFIED`".

        Design: Difficulty/transitive_cascade/election_application_satisfies_demand_depth2
        """
        fx = _family_a_certified("Cascade 2 Co", carryover=2000, prefunding=3000)
        demand = fx["demand"]
        create_election(fx["plan"]["id"], demand["id"], 1000.00)
        d = get_demand(demand["id"])
        assert d["credit_applied"] == 1000.00
        assert d["minimum_due"] == 1839.98
        assert d["outstanding_amount"] == 1839.98
        assert d["status"] == "PARTIALLY_SATISFIED"


class TestPriorityPairs:
    def test_state_beats_fiscal_on_satisfied_demand_payment(self, api):
        """PRD §3.7: "Recall from §2.8 that the generic state gate fires before
        fiscal checks: posting a payment to an already `SATISFIED` demand is an
        `ERR_INVALID_STATE` rejection, not an overpayment."
        PRD §2.8: from-state validity is checked before business rules.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_satisfied_demand_payment
        """
        fx = _family_a_certified("Priority Co", carryover=2000, prefunding=3000)
        demand = fx["demand"]
        create_election(fx["plan"]["id"], demand["id"], 2839.98)
        assert get_demand(demand["id"])["status"] == "SATISFIED"

        # 50000 payment on SATISFIED demand: would also exceed outstanding 0.00,
        # but the state gate (priority 4) beats the fiscal check (priority 21).
        resp = api.create_contribution_payment(
            demand["id"], {"amount": 50000, "paid_on": "2028-06-01"}, PLAN_ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        assert get_demand(demand["id"])["paid_to_date"] == 0.00

    def test_overpayment_rejected_on_open_demand(self, api):
        """PRD §3.7: "must not exceed the demand's `outstanding_amount`, with an
        excess rejected as `ERR_OVERPAYMENT` (HTTP 422)."

        Design: Corner/validations/overpayment_rejected
        """
        # Single ACTIVE participant; assets == FT so tentative == NC 1476.20
        fx = setup_certified_plan(
            sponsor_name="Overpay Co",
            participant_rows=[
                {"external_ref": "A1", "date_of_birth": "1966-03-10", "status": "ACTIVE",
                 "years_of_service": 10, "annual_compensation": 100000},
            ],
            market_value_begin=14762.00, contributions_received=0,
            benefits_paid=738.10, investment_return=738.10,
            prior_aftap_pct=90.00,
        )
        demand = fx["demand"]
        assert demand["outstanding_amount"] == 1476.20
        resp = api.create_contribution_payment(
            demand["id"], {"amount": 2000.00, "paid_on": "2028-05-01"}, PLAN_ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_OVERPAYMENT, 422)


class TestCreditBalanceExceeded:
    def test_credit_balance_exceeded_rejected(self, api):
        """PRD §3.8: "must not exceed the sum of `carryover_balance` and
        `prefunding_balance`... breaching either ceiling is rejected with
        `ERR_CREDIT_BALANCE_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/credit_balance_exceeded_rejected
        """
        # Single-active plan (tentative 1476.20) with pool of only 500
        fx = setup_certified_plan(
            sponsor_name="PoolShort Co",
            participant_rows=[
                {"external_ref": "A1", "date_of_birth": "1966-03-10", "status": "ACTIVE",
                 "years_of_service": 10, "annual_compensation": 100000},
            ],
            market_value_begin=14762.00, contributions_received=0,
            benefits_paid=738.10, investment_return=738.10,
            initial_carryover_balance=500,
            prior_aftap_pct=90.00,
        )
        demand = fx["demand"]
        plan_v = get_plan_version(fx["plan"]["id"])
        resp = api.create_credit_balance_election(
            fx["plan"]["id"],
            {"contribution_demand_id": demand["id"], "amount": 600.00,
             "expected_plan_version": plan_v},
            PLAN_ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_BALANCE_EXCEEDED, 422)


class TestPriorityPairsNoSideEffects:
    def test_state_beats_fiscal_no_payment_recorded(self, api):
        """PRD §3.7: "posting a payment to an already `SATISFIED` demand is an
        `ERR_INVALID_STATE` rejection, not an overpayment."
        PRD §2.8: "the first identifier that does not correspond to an existing
        resource rejects the request" — and a rejected request leaves no side
        effects; the payments list stays empty.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_satisfied_demand_payment
        """
        fx = _family_a_certified("Priority 2 Co", carryover=2000, prefunding=3000)
        demand = fx["demand"]
        create_election(fx["plan"]["id"], demand["id"], 2839.98)
        assert get_demand(demand["id"])["status"] == "SATISFIED"

        resp = api.create_contribution_payment(
            demand["id"], {"amount": 1.00, "paid_on": "2028-06-01"}, PLAN_ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        payments, _ = validate_paginated(
            api.list_contribution_payments(demand["id"], PLAN_ADMIN)
        )
        assert payments == []


class TestDelinquencyAndExcise:
    def test_excise_tax_assessed_once_on_delinquency(self, api):
        """PRD §3.7: "When the logical clock moves strictly past the due date while
        `outstanding_amount` remains positive, the system itself moves an `OPEN` or
        `PARTIALLY_SATISFIED` demand to `DELINQUENT` and assesses `excise_accrued`
        exactly once at that transition: ten percent of the outstanding amount,
        rounded half-up to cents."
        PRD §3.7: "The demand's `due_date` is September 15 of the plan year at
        midnight UTC — the minimum-funding deadline."

        Design: Corner/calculations/excise_tax_assessed_once_on_delinquency
        """
        fx = _family_a_certified("Late Co")
        demand = fx["demand"]
        assert demand["status"] == "OPEN"
        assert demand["outstanding_amount"] == 2839.98

        set_clock("2028-09-16T00:00:00Z")
        d = get_demand(demand["id"])
        assert d["status"] == "DELINQUENT"
        # excise = round_half_up(0.10 * 2839.98, 2) = 284.00
        assert d["excise_accrued"] == 284.00

    def test_excise_not_reversed_by_later_satisfaction(self, api):
        """PRD §3.7: "A delinquent demand later paid or offset down to zero moves
        `DELINQUENT` → `SATISFIED`, but the accrued excise remains due and is never
        reversed."

        Design: Corner/calculations/excise_tax_assessed_once_on_delinquency
        """
        fx = _family_a_certified("Late 2 Co")
        demand = fx["demand"]
        set_clock("2028-09-16T00:00:00Z")
        d = get_demand(demand["id"])
        assert d["status"] == "DELINQUENT"
        assert d["excise_accrued"] == 284.00

        # Pay the full outstanding amount
        create_payment(demand["id"], 2839.98, paid_on="2028-09-16")
        d2 = get_demand(demand["id"])
        assert d2["status"] == "SATISFIED"
        assert d2["excise_accrued"] == 284.00


class TestPlanTermination:
    def test_plan_terminate_with_outstanding_demand_rejected(self, api):
        """PRD §3.1: "Terminating a plan — `ACTIVE` → `TERMINATED`, the terminal
        state — is a `PlanAdmin` action permitted only while no contribution
        demand of the plan carries a positive `outstanding_amount`; termination is
        refused while any demand remains outstanding."

        Design: Corner/errors/plan_terminate_with_outstanding_demand_rejected
        """
        fx = _family_a_certified("Term Co")
        assert fx["demand"]["outstanding_amount"] == 2839.98
        resp = api.terminate_plan(fx["plan"]["id"], PLAN_ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        assert get_plan(fx["plan"]["id"])["status"] == "ACTIVE"
