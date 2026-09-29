"""Retrofit scoring: the simple-payback and risk-adjusted priority variants."""
import pytest

from prd_bench_local_runner.testing import get_success_data
from test_helpers import fixtures as fx
from test_helpers.test_users import make_energy_manager_headers

PROJECT_COST = {"capex_usd": 240240.00, "projected_annual_savings_kwh": 520000.00}
PROJECT = {"measure_type": "LED_RETROFIT", **PROJECT_COST}


def _express_store_with_project(api):
    """A MIXED / EXPRESS store on the default blended rate, one proposed project
    and no fault diagnostics at all, so the risk-adjusted bonus is zero."""
    ctx = fx.setup_commissioned_store(
        api, code="STR-DV2", store_format="EXPRESS", floor_area_sqft=18000,
    )
    ctx["project_proposed"] = fx.create_retrofit(
        api, ctx["store_id"], proposer_user_id="u_analyst_r1", **PROJECT
    )
    ctx["project_id"] = ctx["project_proposed"]["id"]
    return ctx


class TestPriorityBasisVariantDivergence:
    def test_proposal_scores_the_project_on_simple_payback(self, api):
        """Proposal prices savings at the store's blended rate with no haircut.

        The PRD states: "A project costing 240240.00 dollars against 520000.00
        projected kilowatt-hours at the default blended rate therefore shows
        annual savings of 57200.00 dollars, a payback of 4.20 years and a
        priority score of 58.0."

        Design: Difficulty/dual_variant_calc/retrofit_priority_basis_variant_divergence_on_capital_project
        """
        ctx = _express_store_with_project(api)
        proposed = ctx["project_proposed"]

        assert proposed["state"] == "PROPOSED"
        assert proposed["priority_basis"] == "SIMPLE_PAYBACK"
        assert proposed["annual_savings_usd"] == pytest.approx(57200.00, abs=0.01)
        assert proposed["payback_years"] == pytest.approx(4.20, abs=0.01)
        assert proposed["priority_score"] == pytest.approx(58.0, abs=0.01)
        assert proposed["proposed_by_user_id"] == "u_analyst_r1"
        assert proposed["approved_by_user_id"] is None

    def test_approval_reselects_the_risk_adjusted_variant(self, api):
        """Approval haircuts savings by 0.85 and rewrites all three fields.

        The PRD states: "An approval moves the project `PROPOSED → APPROVED`,
        switches `priority_basis` to `RISK_ADJUSTED`, and rewrites all three
        scoring fields under the risk-adjusted variant."

        Design: Difficulty/dual_variant_calc/retrofit_priority_basis_variant_divergence_on_capital_project
        """
        ctx = _express_store_with_project(api)

        approved = get_success_data(
            api.approve_retrofit_project(
                ctx["project_id"], {"decision": "APPROVE"},
                make_energy_manager_headers("u_manager_r2"),
            )
        )

        assert approved["state"] == "APPROVED"
        assert approved["priority_basis"] == "RISK_ADJUSTED"
        assert approved["annual_savings_usd"] == pytest.approx(48620.00, abs=0.01)
        assert approved["payback_years"] == pytest.approx(4.94, abs=0.01)
        assert approved["priority_score"] == pytest.approx(50.6, abs=0.01)
        assert approved["approved_by_user_id"] == "u_manager_r2"

    def test_the_variant_switch_moves_the_score_by_a_fixed_haircut(self, api):
        """The same capex and projection score 58.0 then 50.6.

        The PRD states: "The project above, approved with no refrigeration faults
        outstanding, drops to 48620.00 dollars of annual savings, a 4.94-year
        payback and a score of 50.6 — a deliberate seven-and-a-half-point haircut
        against its proposal score".

        Design: Difficulty/dual_variant_calc/retrofit_priority_basis_variant_divergence_on_capital_project
        """
        ctx = _express_store_with_project(api)
        proposal_score = ctx["project_proposed"]["priority_score"]

        approved = get_success_data(
            api.approve_retrofit_project(
                ctx["project_id"], {"decision": "APPROVE"},
                make_energy_manager_headers("u_manager_r2"),
            )
        )

        assert proposal_score == pytest.approx(58.0, abs=0.01)
        assert approved["capex_usd"] == pytest.approx(240240.00, abs=0.01)
        assert approved["projected_annual_savings_kwh"] == pytest.approx(520000.00, abs=0.01)
        assert proposal_score - approved["priority_score"] == pytest.approx(7.4, abs=0.01)


MEASUREMENT = {
    "install_completed_iso": "2026-05-01T00:00:00Z",
    "baseline_period_kwh": 300000.00,
    "post_period_kwh": 220000.00,
    "mv_period_days": 90,
}


def _verified_project_on_a_hot_humid_store(api):
    """A HOT_HUMID store whose single project has been approved and verified."""
    ctx = fx.setup_commissioned_store(
        api, code="STR-CI2", climate_zone="HOT_HUMID", floor_area_sqft=128000,
    )
    ctx["store_at_creation"] = ctx["store"]
    project = fx.create_retrofit(
        api, ctx["store_id"], proposer_user_id="u_analyst_ci2",
        measure_type="HVAC_RTU_REPLACEMENT", **PROJECT_COST,
    )
    ctx["project_id"] = project["id"]
    ctx["score_proposed"] = project["priority_score"]
    approved = fx.decide_retrofit(
        api, project["id"], "APPROVE", approver_user_id="u_manager_ci2"
    )
    ctx["approved"] = approved
    return ctx


class TestVerifiedSavingsLedgerConservedOnRevocation:
    def test_verification_credits_the_savings_ledger_in_kilowatt_hours(self, api):
        """A realization rate at or above the floor credits exactly the measured savings.

        The PRD states: "When `realization_rate` is at or above 0.8000 the project
        moves to `VERIFIED` and the store's `verified_savings_kwh_ytd` is credited
        by exactly `measured_savings_kwh`; a rate of precisely 0.8000 verifies,
        because the floor is inclusive."

        Design: Difficulty/compensating_invariant/verified_savings_ledger_conserved_on_verification_revocation
        """
        ctx = _verified_project_on_a_hot_humid_store(api)
        assert ctx["store_at_creation"]["verified_savings_kwh_ytd"] == pytest.approx(0.00, abs=0.01)
        assert ctx["store_at_creation"]["portfolio_realization_rate"] == pytest.approx(
            0.85, abs=0.0001
        )
        assert ctx["score_proposed"] == pytest.approx(58.0, abs=0.01)
        assert ctx["approved"]["priority_score"] == pytest.approx(50.6, abs=0.01)
        assert ctx["approved"]["priority_basis"] == "RISK_ADJUSTED"

        measured = fx.submit_measurement(api, ctx["project_id"], **MEASUREMENT)
        store = fx.read_store(api, ctx["store_id"])

        assert measured["state"] == "VERIFIED"
        assert measured["adjusted_baseline_kwh"] == pytest.approx(324000.00, abs=0.01)
        assert measured["measured_savings_kwh"] == pytest.approx(104000.00, abs=0.01)
        assert measured["realization_rate"] == pytest.approx(0.8111, abs=0.0001)
        assert store["verified_savings_kwh_ytd"] == pytest.approx(104000.00, abs=0.01)
        assert store["portfolio_realization_rate"] == pytest.approx(0.8111, abs=0.0001)

    def test_revocation_debits_exactly_the_credited_kilowatt_hours(self, api):
        """The ledger returns to 0.00 while the measurement evidence survives.

        The PRD states: "Revocation is legal only from `VERIFIED` — anything else
        is `ERR_RETROFIT_STATE_INVALID` — and moves the project `VERIFIED →
        SHORTFALL_REVIEW`, debits the store's `verified_savings_kwh_ytd` by exactly
        that project's `measured_savings_kwh` so the ledger identity holds again,
        stores the reason, and recomputes `portfolio_realization_rate`."

        Design: Difficulty/compensating_invariant/verified_savings_ledger_conserved_on_verification_revocation
        """
        ctx = _verified_project_on_a_hot_humid_store(api)
        fx.submit_measurement(api, ctx["project_id"], **MEASUREMENT)

        revoked = get_success_data(
            api.revoke_retrofit_verification(
                ctx["project_id"],
                make_energy_manager_headers("u_manager_ci2"),
                {"revocation_reason": "sub-metering error found in the post period"},
            )
        )
        store = fx.read_store(api, ctx["store_id"])

        assert revoked["state"] == "SHORTFALL_REVIEW"
        assert revoked["measured_savings_kwh"] == pytest.approx(104000.00, abs=0.01)
        assert revoked["realization_rate"] == pytest.approx(0.8111, abs=0.0001)
        assert revoked["revocation_reason"] == "sub-metering error found in the post period"
        assert store["verified_savings_kwh_ytd"] == pytest.approx(0.00, abs=0.001)
        assert store["verified_savings_kwh_ytd"] >= 0.0

    def test_portfolio_rate_still_counts_the_project_under_shortfall_review(self, api):
        """Revocation does not disturb the portfolio mean.

        The PRD states: "both branches recompute the store's
        `portfolio_realization_rate` as the arithmetic mean of `realization_rate`
        across that store's projects whose `state` is `VERIFIED` or
        `SHORTFALL_REVIEW`, rounded half up to four decimal places — falling back
        to the portfolio default of 0.85 when that set is empty."

        Design: Difficulty/compensating_invariant/verified_savings_ledger_conserved_on_verification_revocation
        """
        ctx = _verified_project_on_a_hot_humid_store(api)
        fx.submit_measurement(api, ctx["project_id"], **MEASUREMENT)
        after_verify = fx.read_store(api, ctx["store_id"])

        get_success_data(
            api.revoke_retrofit_verification(
                ctx["project_id"],
                make_energy_manager_headers("u_manager_ci2"),
                {"revocation_reason": "sub-metering error found in the post period"},
            )
        )
        after_revoke = fx.read_store(api, ctx["store_id"])

        assert after_verify["portfolio_realization_rate"] == pytest.approx(0.8111, abs=0.0001)
        assert after_revoke["portfolio_realization_rate"] == pytest.approx(0.8111, abs=0.0001)
