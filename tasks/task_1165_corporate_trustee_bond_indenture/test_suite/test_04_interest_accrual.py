"""Interest accrual: day-count conventions, per-position rounding, gross
recomputation at execute (PRD §3.4)."""
import pytest

from test_helpers import (
    api_client, validate_success, ApiErrorId,
    CLOCK_START, set_clock,
    create_active_indenture_with_tranche, setup_indenture_with_positions,
    create_interest_run, fund_run, execute_run, create_redemption_run,
    list_run_records, run_records_by_position, get_payment_run,
    assert_payment_run, assert_distribution_record,
)

# Canonical half-open window [2026-06-15, 2026-12-15): 183 calendar days.
# ACT_360: fraction 183/360; ACT_365: fraction 183/365 (PRD §3.4).
WINDOW_START = "2026-06-15"
WINDOW_END = "2026-12-15"
PAY_DATE = "2026-12-15"


def _setup_dual_day_count_scenario(api):
    """Two active indentures, identical except day_count_convention
    (ACT_360 vs ACT_365); each with positions 400000000/350000000/250000000
    and a fully funded INTEREST run over the canonical window."""
    set_clock(CLOCK_START)
    scenarios = {}
    shared_accounts = None
    for convention, tag in (("ACT_360", "360"), ("ACT_365", "365")):
        ctx = setup_indenture_with_positions(
            amounts=(400000000, 350000000, 250000000),
            holder_prefixes=(f"H-{tag}A", f"H-{tag}B", f"H-{tag}C"),
            indenture_overrides={"name": f"I{tag}"},
            tranche_overrides={"series_code": f"T{tag}",
                               "original_principal_cents": 1000000000,
                               "day_count_convention": convention},
            reset_clock=False,
        )
        scenarios[tag] = ctx
    run360 = create_interest_run(scenarios["360"]["tranche"]["id"])
    run365 = create_interest_run(scenarios["365"]["tranche"]["id"])
    fund_run(run360["id"], 25416667, issuer_ref="issuer-1")
    fund_run(run365["id"], 25068493, issuer_ref="issuer-1")
    scenarios["360"]["run"] = run360
    scenarios["365"]["run"] = run365
    return scenarios


class TestDayCountBasisDivergence:
    def test_act360_positions_and_gross(self, api):
        """PRD §3.4: "the day count is the number of calendar days in the
        half-open accrual window, converted to a year fraction by dividing by
        360 under `ACT_360` or by 365 under `ACT_365` — so identical inputs
        accrue more under `ACT_360` than under `ACT_365`"
        PRD §3.4: "Each position's interest is its current
        `principal_amount_cents` times the tranche's `interest_rate_bps`
        divided by ten thousand, times the year fraction, rounded half-up to a
        whole cent **per position before any summation**, and the run's
        `gross_amount_cents` is the sum of those per-position amounts."

        Design: Difficulty/dual_variant_calc/interest_day_count_basis_divergence
        """
        scenarios = _setup_dual_day_count_scenario(api)
        ctx = scenarios["360"]
        run = execute_run(ctx["run"]["id"])
        assert run["gross_amount_cents"] == 25416667, (
            f"ACT_360 gross: expected 25416667, got {run['gross_amount_cents']}")
        assert_payment_run(run)

        by_position = run_records_by_position(run["id"], ctx["positions"])
        expected = [10166667, 8895833, 6354167]
        for position, want in zip(ctx["positions"], expected):
            record = by_position[position["id"]]
            assert record is not None, "one record per ACTIVE position"
            assert_distribution_record(record)
            assert record["allocated_cents"] == want, (
                f"ACT_360 allocation for principal "
                f"{position['principal_amount_cents']}: expected {want}, "
                f"got {record['allocated_cents']}")

    def test_act365_positions_diverge_from_act360(self, api):
        """PRD §3.4: "converted to a year fraction by dividing by 360 under
        `ACT_360` or by 365 under `ACT_365` — so identical inputs accrue more
        under `ACT_360` than under `ACT_365`"
        PRD §3.4: "rounded half-up to a whole cent **per position before any
        summation**, and the run's `gross_amount_cents` is the sum of those
        per-position amounts."

        Design: Difficulty/dual_variant_calc/interest_day_count_basis_divergence
        """
        scenarios = _setup_dual_day_count_scenario(api)
        run365 = execute_run(scenarios["365"]["run"]["id"])
        run360 = execute_run(scenarios["360"]["run"]["id"])

        assert run365["gross_amount_cents"] == 25068493, (
            f"ACT_365 gross: expected 25068493, got {run365['gross_amount_cents']}")
        by_position = run_records_by_position(run365["id"], scenarios["365"]["positions"])
        expected = [10027397, 8773973, 6267123]
        for position, want in zip(scenarios["365"]["positions"], expected):
            record = by_position[position["id"]]
            assert record["allocated_cents"] == want, (
                f"ACT_365 allocation for principal "
                f"{position['principal_amount_cents']}: expected {want}, "
                f"got {record['allocated_cents']}")

        assert run360["gross_amount_cents"] != run365["gross_amount_cents"], (
            "identical inputs diverge solely by day_count_convention")
        assert run360["gross_amount_cents"] > run365["gross_amount_cents"], (
            "ACT_360 accrues more than ACT_365 for identical inputs")


class TestThirty360:
    def test_thirty_360_interest_correct_result(self, api):
        """PRD §3.4: "under `THIRTY_360` the day count is 360 times the year
        difference plus 30 times the month difference plus the difference of
        the day-of-month components each capped at 30, over a 360-day year,
        ignoring actual month lengths."
        PRD §3.4: "rounded half-up to a whole cent **per position before any
        summation**, and the run's `gross_amount_cents` is the sum of those
        per-position amounts."

        Window [2026-06-15, 2026-12-15): 360*0 + 30*6 + (15-15) = 180 days.

        Design: Corner/calculations/thirty_360_interest_correct_result
        """
        set_clock(CLOCK_START)
        ctx = setup_indenture_with_positions(
            amounts=(300000000, 200000000),
            holder_prefixes=("H-D", "H-E"),
            tranche_overrides={"series_code": "T2", "original_principal_cents": 500000000,
                               "interest_rate_bps": 600,
                               "day_count_convention": "THIRTY_360"},
            reset_clock=False,
        )
        run = create_interest_run(ctx["tranche"]["id"])
        fund_run(run["id"], 15000000, issuer_ref="issuer-1")
        run = execute_run(run["id"])

        assert run["gross_amount_cents"] == 15000000
        by_position = run_records_by_position(run["id"], ctx["positions"])
        expected = [9000000, 6000000]
        for position, want in zip(ctx["positions"], expected):
            record = by_position[position["id"]]
            assert record["allocated_cents"] == want, (
                f"THIRTY_360 allocation: expected {want}, got {record['allocated_cents']}")


class TestGrossRecomputedAtExecute:
    def test_interest_gross_recomputed_at_execute(self, api):
        """PRD §3.4: "For `INTEREST` runs the `gross_amount_cents` is
        provisionally computed at creation and authoritatively recomputed at
        execution from the then-current positions, because redemptions between
        scheduling and execution may shrink the position set."

        Design: Corner/complexity_layers/interest_gross_recomputed_at_execute_from_current_positions
        """
        set_clock(CLOCK_START)
        ctx = setup_indenture_with_positions(
            amounts=(400000000, 350000000, 250000000),
            holder_prefixes=("H-A", "H-B", "H-C"),
            tranche_overrides={"series_code": "T1", "original_principal_cents": 1000000000,
                               "notice_period_days": 30},
            reset_clock=False,
        )
        tranche = ctx["tranche"]
        interest_run = create_interest_run(tranche["id"])
        provisional = interest_run["gross_amount_cents"]
        assert provisional == 25416667, "provisional gross at creation"

        # Interim redemption: cuts principals to 360000001/315000000/225000000.
        redemption = create_redemption_run(tranche["id"], 99999999,
                                           scheduled_payment_date="2026-06-15")
        fund_run(redemption["id"], 99999999, issuer_ref="issuer-1")
        execute_run(redemption["id"])

        # Fund to the recomputed gross and execute.
        fund_run(interest_run["id"], 22875000, issuer_ref="issuer-1")
        interest_run = execute_run(interest_run["id"])

        assert interest_run["gross_amount_cents"] == 22875000, (
            f"gross recomputed at execute: expected 22875000, "
            f"got {interest_run['gross_amount_cents']}")
        assert interest_run["gross_amount_cents"] != provisional, (
            "executed gross differs from the creation-time provisional figure")
        by_position = run_records_by_position(interest_run["id"], ctx["positions"])
        expected = [9150000, 8006250, 5718750]
        for position, want in zip(ctx["positions"], expected):
            record = by_position[position["id"]]
            assert record["allocated_cents"] == want, (
                f"post-redemption interest allocation: expected {want}, "
                f"got {record['allocated_cents']}")
