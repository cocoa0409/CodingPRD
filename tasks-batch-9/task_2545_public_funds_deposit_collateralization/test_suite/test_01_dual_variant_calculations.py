"""Paired-variant calculations: insured amount, runoff projection and risk grading."""

from test_helpers import assertions, fixtures, get_success_data
from test_helpers.constants import DEFAULT_CLOCK_UTC, TEST_DEFAULTS
from test_helpers.fixtures import OFFICER


def _open_two_demand_accounts(client, depository_id, public_unit_id):
    """Open two DEMAND accounts in the same insurance group and fund only the first."""
    first = fixtures.create_deposit_account(
        client,
        depository_id,
        public_unit_id,
        deposit_class="DEMAND",
        pledging_mode="DEDICATED",
    )
    fixtures.deposit(client, first["id"], public_unit_id, 20_000_000)
    second = fixtures.create_deposit_account(
        client,
        depository_id,
        public_unit_id,
        deposit_class="DEMAND",
        pledging_mode="DEDICATED",
    )
    return first, second


def test_aggregated_basis_shares_one_bucket_across_the_insurance_group(client):
    """Two accounts of one county at an AGGREGATED_BY_UNIT bank share a single bucket.

    The first account funded with 20,000,000 cents absorbs 20,000,000 of coverage, so the
    second funded with 30,000,000 receives only the 5,000,000 that remains and carries
    25,000,000 uninsured — a requirement of 26,250,000 cents at 10500 basis points.

    PRD: "Under `AGGREGATED_BY_UNIT`, the default, one single coverage bucket of
    25,000,000 cents is shared by the whole insurance group and consumed in ascending
    `group_sequence` order."
    PRD: "Starting with the full bucket as the remaining coverage, each account in turn
    takes as its `insured_amount_cents` the lesser of the coverage still remaining and its
    own `ledger_balance_cents`; that amount is then deducted from the remaining coverage
    before the next account is considered."
    PRD: "a `WELL_CAPITALIZED` depository requires 10500 basis points of the uninsured
    balance, an `ADEQUATELY_CAPITALIZED` one requires 11000, and an `UNDERCAPITALIZED` one
    requires 12500."

    Design: Difficulty/dual_variant_calc/insured_amount_aggregated_vs_per_account_basis
    """
    fixtures.set_clock(client, DEFAULT_CLOCK_UTC)
    public_unit = fixtures.create_public_unit(
        client,
        name="Ridge County",
        unit_type="COUNTY",
        statutory_max_deposit_cents=TEST_DEFAULTS["STATUTORY_MAX_DEPOSIT_CENTS"],
        collateral_program_preference="DEDICATED",
    )
    depository = fixtures.create_approved_depository(
        client,
        name="Aggregate National Bank",
        capital_ratio_bps=1200,
        insurance_determination_basis="AGGREGATED_BY_UNIT",
    )
    first, second = _open_two_demand_accounts(
        client, depository["id"], public_unit["id"]
    )

    second = fixtures.deposit(client, second["id"], public_unit["id"], 30_000_000)

    assert first["group_sequence"] == 1
    assert second["group_sequence"] == 2
    assert second["insured_amount_cents"] == 5_000_000
    assert second["uninsured_amount_cents"] == 25_000_000
    assert second["required_collateral_pct_bps"] == 10500
    assert second["required_collateral_cents"] == 26_250_000
    assertions.assert_insured_plus_uninsured_reconciles(second)

    reread_first = get_success_data(
        client.get_deposit_account(first["id"], OFFICER), 200
    )
    assert reread_first["insured_amount_cents"] == 20_000_000
    assert reread_first["uninsured_amount_cents"] == 0
    assertions.assert_insured_plus_uninsured_reconciles(reread_first)


def test_per_account_basis_gives_every_account_its_own_bucket(client):
    """The identical two balances at a PER_ACCOUNT bank leave the second account with a
    full 25,000,000-cent bucket, so only 5,000,000 is uninsured and the requirement is
    5,250,000 cents — 21,000,000 less than the aggregated variant demands.

    PRD: "Under `PER_ACCOUNT`, every account receives its own 25,000,000-cent bucket and
    the processing order is irrelevant because nothing is shared: each account's
    `insured_amount_cents` is simply the lesser of 25,000,000 cents and its own
    `ledger_balance_cents`."
    PRD: "Whenever a group holds more than one funded account, this variant produces
    strictly smaller uninsured totals than the aggregated variant."

    Design: Difficulty/dual_variant_calc/insured_amount_aggregated_vs_per_account_basis
    """
    fixtures.set_clock(client, DEFAULT_CLOCK_UTC)
    public_unit = fixtures.create_public_unit(
        client,
        name="Ridge County",
        unit_type="COUNTY",
        statutory_max_deposit_cents=TEST_DEFAULTS["STATUTORY_MAX_DEPOSIT_CENTS"],
        collateral_program_preference="DEDICATED",
    )
    depository = fixtures.create_approved_depository(
        client,
        name="Per Account National Bank",
        capital_ratio_bps=1200,
        insurance_determination_basis="PER_ACCOUNT",
    )
    first, second = _open_two_demand_accounts(
        client, depository["id"], public_unit["id"]
    )

    second = fixtures.deposit(client, second["id"], public_unit["id"], 30_000_000)

    assert second["group_sequence"] == 2
    assert second["insured_amount_cents"] == 25_000_000
    assert second["uninsured_amount_cents"] == 5_000_000
    assert second["required_collateral_pct_bps"] == 10500
    assert second["required_collateral_cents"] == 5_250_000
    assertions.assert_insured_plus_uninsured_reconciles(second)

    reread_first = get_success_data(
        client.get_deposit_account(first["id"], OFFICER), 200
    )
    assert reread_first["insured_amount_cents"] == 20_000_000
    assert reread_first["uninsured_amount_cents"] == 0


TAX_CYCLE_BOUNDARIES = [
    "2026-08-01T00:00:00Z",
    "2026-08-11T00:00:00Z",
    "2026-08-21T00:00:00Z",
    "2026-08-31T00:00:00Z",
]
TAX_CYCLE_BALANCES = [120_000_000, 200_000_000, 60_000_000]


def _forecastable_account(client):
    """An approved bank with one funded account and 100,000,000 cents of free treasury."""
    fixtures.set_clock(client, DEFAULT_CLOCK_UTC)
    custodian = fixtures.create_approved_custodian(
        client, tri_party_capable=True, concentration_limit_bps=10000
    )
    public_unit = fixtures.create_public_unit(
        client, unit_type="COUNTY", collateral_program_preference="DEDICATED"
    )
    depository = fixtures.create_approved_depository(client, capital_ratio_bps=1200)
    account = fixtures.create_funded_account(
        client,
        depository["id"],
        public_unit["id"],
        100_000_000,
        deposit_class="DEMAND",
        pledging_mode="DEDICATED",
    )
    asset = fixtures.create_collateral_asset(
        client,
        depository["id"],
        custodian["id"],
        asset_type="US_TREASURY",
        par_value_cents=100_000_000,
        market_price_bps=10000,
    )
    return public_unit, depository, account, asset


def test_peak_window_basis_projects_the_mid_horizon_spike(client):
    """A three-window tax cycle of 120,000,000 / 200,000,000 / 60,000,000 cents projects
    per-window requirements of 99,750,000 / 183,750,000 / 36,750,000 at the account's
    frozen 10500 basis points, and PEAK_WINDOW keeps the largest — 183,750,000 — leaving a
    capacity gap of 85,750,000 against 98,000,000 cents of free collateral.

    PRD: "Under `PEAK_WINDOW` the forecast takes the largest per-window projected
    requirement in the horizon, on the theory that the treasury must be collateralised for
    its worst moment, so a mid-horizon tax-collection spike sets the plan."
    PRD: "For each window the projected uninsured amount is `projected_balance_cents` less
    the 25,000,000-cent insurance coverage limit, floored at zero; the window's projected
    requirement is that uninsured figure multiplied by the frozen percentage, divided by
    10000, rounded half up to whole cents."
    PRD: "`pledge_capacity_gap_cents` is then the projected requirement less that capacity,
    floored at zero, and it is the number a treasurer takes to the bank: if it is positive,
    the bank does not currently own enough free collateral to cover the forecast cycle."

    Design: Difficulty/dual_variant_calc/runoff_projection_peak_window_vs_period_end
    """
    public_unit, _depository, account, _asset = _forecastable_account(client)

    forecast = fixtures.file_forecast(
        client,
        account["id"],
        public_unit["id"],
        TAX_CYCLE_BOUNDARIES[0],
        TAX_CYCLE_BOUNDARIES[-1],
        fixtures.contiguous_windows(TAX_CYCLE_BOUNDARIES, TAX_CYCLE_BALANCES),
        cycle_label="TAX_COLLECTION",
        basis="PEAK_WINDOW",
    )

    assertions.assert_runoff_forecast(forecast)
    assert forecast["projected_peak_balance_cents"] == 200_000_000
    assert forecast["projected_required_collateral_cents"] == 183_750_000
    assert forecast["unpledged_capacity_cents"] == 98_000_000
    assert forecast["pledge_capacity_gap_cents"] == 85_750_000
    assert forecast["status"] == "OPEN"
    assert forecast["requires_reforecast"] is False


def test_period_end_basis_projects_the_closing_window_only(client):
    """The identical three-window cycle under PERIOD_END takes the last window's
    36,750,000-cent requirement instead of the 183,750,000-cent spike, so the free
    collateral of 98,000,000 cents covers the plan and the capacity gap floors at zero.

    PRD: "Under `PERIOD_END` the forecast takes the projected requirement of the
    chronologically last window — the one with the greatest `window_start`, and among ties
    the one with the greatest `window_end` — on the theory that the treasury plans to its
    closing position; a spike that has already run off by the end of the horizon is
    therefore invisible, and this variant's projected requirement is never higher than the
    peak variant's."
    PRD: "The forecast's `projected_peak_balance_cents` is the largest
    `projected_balance_cents` across the windows."

    Design: Difficulty/dual_variant_calc/runoff_projection_peak_window_vs_period_end
    """
    public_unit, _depository, account, _asset = _forecastable_account(client)

    forecast = fixtures.file_forecast(
        client,
        account["id"],
        public_unit["id"],
        TAX_CYCLE_BOUNDARIES[0],
        TAX_CYCLE_BOUNDARIES[-1],
        fixtures.contiguous_windows(TAX_CYCLE_BOUNDARIES, TAX_CYCLE_BALANCES),
        cycle_label="DISBURSEMENT",
        basis="PERIOD_END",
    )

    assert forecast["projected_peak_balance_cents"] == 200_000_000
    assert forecast["projected_required_collateral_cents"] == 36_750_000
    assert forecast["unpledged_capacity_cents"] == 98_000_000
    assert forecast["pledge_capacity_gap_cents"] == 0
    assert forecast["status"] == "OPEN"


def _bank_with_one_clean_and_one_deficient_run(client):
    """Run a first, fully uncollateralised run, then pledge enough par to reach 120 percent
    coverage, so a second run scores every component at its ceiling."""
    fixtures.set_clock(client, DEFAULT_CLOCK_UTC)
    custodian = fixtures.create_approved_custodian(
        client, tri_party_capable=True, concentration_limit_bps=10000
    )
    public_unit = fixtures.create_public_unit(
        client, unit_type="COUNTY", collateral_program_preference="DEDICATED"
    )
    depository = fixtures.create_approved_depository(client, capital_ratio_bps=1200)
    account = fixtures.create_funded_account(
        client,
        depository["id"],
        public_unit["id"],
        100_000_000,
        deposit_class="DEMAND",
        pledging_mode="DEDICATED",
    )

    first_run = fixtures.create_mtm_run(
        client,
        depository["id"],
        "2026-07-30T00:00:00Z",
        "2026-07-30T06:00:00Z",
        basis="SUPERVISORY",
    )

    agreement = fixtures.create_executed_dedicated_agreement(
        client, depository["id"], custodian["id"], account["id"], public_unit["id"]
    )
    asset = fixtures.create_collateral_asset(
        client,
        depository["id"],
        custodian["id"],
        asset_type="US_TREASURY",
        par_value_cents=96_428_571,
        market_price_bps=10000,
    )
    allocation = fixtures.create_allocation(
        client, agreement["id"], asset["id"], 96_428_571
    )
    return depository, first_run, allocation


def test_supervisory_basis_scores_the_current_run_alone(client):
    """The first run, with no collateral and no executed paperwork, scores coverage 0,
    volatility 7500 and documentation 0 for a supervisory 2250 and grade D. A second
    supervisory run over a later window, now backed by 94,500,000 cents of collateral
    against a 78,750,000-cent requirement, scores all three components at 10000 and lands
    on 10000 and grade A immediately.

    PRD: "Under `SUPERVISORY`, the regulator's view, the three components of this run alone
    are used, so one bad run moves the grade immediately."
    PRD: "`risk_score_bps` is the coverage figure multiplied by 0.50, plus the volatility
    figure multiplied by 0.30, plus the documentation figure multiplied by 0.20, with the
    sum rounded half up to whole basis points."
    PRD: "From that score `risk_grade_assigned` follows with inclusive lower bounds: `A` at
    8500 or above, `B` at 7000 or above, `C` at 5000 or above, and `D` below 5000."

    Design: Difficulty/dual_variant_calc/risk_grade_supervisory_single_run_vs_internal_trailing_average
    """
    depository, first_run, allocation = _bank_with_one_clean_and_one_deficient_run(client)

    assertions.assert_mtm_run(first_run)
    assert first_run["coverage_component_bps"] == 0
    assert first_run["volatility_component_bps"] == 7500
    assert first_run["documentation_component_bps"] == 0
    assert first_run["risk_score_bps"] == 2250
    assert first_run["risk_grade_assigned"] == "D"
    assert allocation["allocated_collateral_value_cents"] == 94_500_000

    second_run = fixtures.create_mtm_run(
        client,
        depository["id"],
        "2026-07-30T12:00:00Z",
        "2026-07-30T18:00:00Z",
        basis="SUPERVISORY",
    )

    assert second_run["total_required_collateral_cents"] == 78_750_000
    assert second_run["total_collateral_value_cents"] == 94_500_000
    assert second_run["outcome"] == "SUFFICIENT"
    assert second_run["coverage_component_bps"] == 10000
    assert second_run["volatility_component_bps"] == 10000
    assert second_run["documentation_component_bps"] == 10000
    assert second_run["risk_score_bps"] == 10000
    assert second_run["risk_grade_assigned"] == "A"


def test_internal_basis_averages_components_over_the_trailing_three_runs(client):
    """A third run on the INTERNAL basis sees exactly the components of the second run —
    coverage 10000, volatility 10000, documentation 10000 — yet averages each over itself
    and the two earlier runs (6667, 9167, 6667) before weighting, so it scores 7417 and
    grade B where the supervisory view scored 10000 and grade A. The smoothed grade is
    copied onto the depository.

    PRD: "Under `INTERNAL`, the bank's view, each component is instead averaged over a
    trailing window consisting of this run plus the previous two runs of the same
    depository, taken in descending `run_index` order; where the depository has fewer than
    three runs in total, the average is taken over however many exist."
    PRD: "Each of the three component averages is rounded half up to whole basis points
    **before** weighting — averaging first, then weighting, is the pinned order — so the
    same current-run inputs yield a higher, smoothed score whenever the earlier runs were
    stronger."
    PRD: "Both the score and the grade are copied onto the depository as `risk_score_bps`
    and `risk_grade`, which is how a bank that lets its collateral rot eventually finds
    itself unable to open new deposit accounts at all."

    Design: Difficulty/dual_variant_calc/risk_grade_supervisory_single_run_vs_internal_trailing_average
    """
    depository, _first_run, _allocation = _bank_with_one_clean_and_one_deficient_run(client)

    fixtures.create_mtm_run(
        client,
        depository["id"],
        "2026-07-30T12:00:00Z",
        "2026-07-30T18:00:00Z",
        basis="SUPERVISORY",
    )
    third_run = fixtures.create_mtm_run(
        client,
        depository["id"],
        "2026-07-31T00:00:00Z",
        "2026-07-31T06:00:00Z",
        basis="INTERNAL",
    )

    assert third_run["run_index"] == 3
    assert third_run["coverage_component_bps"] == 10000
    assert third_run["volatility_component_bps"] == 10000
    assert third_run["documentation_component_bps"] == 10000
    assert third_run["risk_score_bps"] == 7417
    assert third_run["risk_grade_assigned"] == "B"

    reread = get_success_data(client.get_depository(depository["id"], OFFICER), 200)
    assert reread["risk_score_bps"] == 7417
    assert reread["risk_grade"] == "B"
