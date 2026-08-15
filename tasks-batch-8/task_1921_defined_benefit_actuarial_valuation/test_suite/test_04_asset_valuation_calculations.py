"""Asset roll-forward, smoothing corridor, and smoothed-vs-market dual-variant tests."""
import pytest

from test_helpers import (
    validate_success,
    ApiErrorId,
    TEST_USERS,
    create_plan,
    register_prep_and_review_actuaries,
    create_asset_statement,
    create_asset_valuation,
    create_locked_census,
    create_locked_assumption_set,
    create_valuation_run,
    compute_run,
    certify_run,
    get_plan_version,
    get_ledger,
    create_pbgc_filing,
    setup_certified_plan,
    api_client,
)

PLAN_ADMIN = TEST_USERS["plan_admin_headers"]


class TestAssetRollforwardAndCorridor:
    def test_asset_rollforward_invariant_and_corridor_floor(self, api):
        """PRD §3.4: "The server computes `market_value_end` by the roll-forward
        invariant: beginning market value, plus contributions received, minus
        benefits paid, plus investment return."
        PRD §3.4: "The expected return is five percent of `market_value_begin` ...
        `unrecognized_gain` — the deferred portion — is two-thirds of the gain,
        rounded half-up to cents. The pre-corridor smoothed value is
        `market_value_end` minus `unrecognized_gain`. A corridor then clamps it:
        `corridor_floor` is eighty percent of `market_value_end` ... The resulting
        `smoothed_value` is the pre-corridor value raised to the floor when it falls
        below the floor ... `corridor_applied` records `FLOOR`, `CEILING`, or `NONE`
        accordingly."

        Design: Corner/calculations/asset_rollforward_invariant_and_corridor_floor
        """
        plan = create_plan(sponsor_name="Floor Co")
        prep, _ = register_prep_and_review_actuaries()
        stmt = create_asset_statement(
            plan["id"],
            market_value_begin=50000, contributions_received=10000,
            benefits_paid=3000, investment_return=43000,
        )
        # roll-forward: 50000 + 10000 - 3000 + 43000 = 100000
        assert stmt["market_value_end"] == 100000.00

        ava = create_asset_valuation(plan["id"], prep["id"])
        # expected 2500; gain 40500; unrecognized = 2/3 * 40500 = 27000.00
        assert ava["unrecognized_gain"] == 27000.00
        # pre-corridor 100000 - 27000 = 73000; floor 0.80*100000 = 80000 -> FLOOR
        assert ava["smoothed_value"] == 80000.00
        assert ava["corridor_applied"] == "FLOOR"
        assert ava["corridor_floor"] == 80000.00
        assert ava["corridor_ceiling"] == 120000.00


class TestSmoothedVsMarketDualVariant:
    def test_pbgc_filing_uses_market_not_smoothed(self, api):
        """PRD §3.4: "PBGC premium and financial-statement disclosure contexts use
        the unsmoothed `market_value`."
        PRD §3.9: "`market_assets` at the market value from the run's asset
        valuation, never the smoothed value"; "`uvb`, the unfunded vested benefits,
        as the premium target minus market assets, floored at zero".

        Design: Difficulty/dual_variant_calc/asset_value_smoothed_vs_market_for_pbgc
        """
        plan = create_plan(sponsor_name="Loss Co", prior_aftap_pct=84.00)
        plan_id = plan["id"]
        prep, rev = register_prep_and_review_actuaries()
        batch = create_locked_census(plan_id, [
            {"external_ref": "R1", "date_of_birth": "1965-06-15", "status": "RETIREE",
             "current_annual_benefit": 100000},
        ])
        aset = create_locked_assumption_set(plan_id, prep["id"], rev["id"])
        # loss year: mv_begin 100000, return -50000 -> market 50000
        create_asset_statement(
            plan_id, market_value_begin=100000, contributions_received=0,
            benefits_paid=0, investment_return=-50000,
        )
        ava = create_asset_valuation(plan_id, prep["id"])
        # gain = -50000 - 5000 = -55000; unrecognized = 2/3 * -55000 = -36666.67
        # pre-corridor = 50000 - (-36666.67) = 86666.67; ceiling = 1.20*50000 = 60000
        assert ava["market_value"] == 50000.00
        assert ava["smoothed_value"] == 60000.00
        assert ava["corridor_applied"] == "CEILING"

        run = create_valuation_run(plan_id, prep["id"], batch["id"], aset["id"], ava["id"])
        compute_run(run["id"], prep["id"])
        plan_v = get_plan_version(plan_id)
        certify_run(run["id"], rev["id"], plan_v)

        filing = create_pbgc_filing(plan_id, run["id"], premium_method="STANDARD")
        # PBGC uses market 50000, not smoothed 60000
        assert filing["market_assets"] == 50000.00
        # FT = 100000 * AF(63)=1.0000 = 100000.00; UVB = 100000 - 50000 = 50000
        assert filing["uvb"] == 50000.00
        # uncapped variable = 50000 * 50/1000 = 2500; cap = 1 * 600 = 600 -> binds
        assert filing["variable_rate_premium"] == 600.00
        assert filing["cap_applied"] is True

    def test_smoothed_value_differs_from_market_when_corridor_binds(self, api):
        """PRD §3.4: "Two variants of the same valuation serve different purposes,
        sharing identical inputs. Funding contexts ... use the corridor-clamped
        `smoothed_value`. PBGC premium and financial-statement disclosure contexts
        use the unsmoothed `market_value`. The outputs differ whenever the
        unrecognized gain is nonzero or a corridor bound clamps."

        Design: Difficulty/dual_variant_calc/asset_value_smoothed_vs_market_for_pbgc
        """
        plan = create_plan(sponsor_name="Loss 2 Co", prior_aftap_pct=84.00)
        prep, _ = register_prep_and_review_actuaries()
        create_asset_statement(
            plan["id"], market_value_begin=100000, contributions_received=0,
            benefits_paid=0, investment_return=-50000,
        )
        ava = create_asset_valuation(plan["id"], prep["id"])
        # Same inputs, two valid algorithmic outputs on one entity
        assert ava["market_value"] == 50000.00
        assert ava["smoothed_value"] == 60000.00
        assert ava["smoothed_value"] != ava["market_value"]
