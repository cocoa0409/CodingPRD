"""Supply portfolio: termination fees and reserve clamping; load-forecast
variants, coverage-gap window semantics, and the RA planning margin."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_epoch,
    assert_load_forecast,
    assert_reserve_never_negative,
    create_account_spec,
    create_executed_contract,
    create_forecast,
    get_authority,
    set_clock,
    setup_accepted_extract,
    setup_active_authority,
    setup_enrolled_accounts,
    setup_settled_extract,
    validate_success,
)

PM = TEST_USERS["portfolio_manager_headers"]


def test_termination_fee_remaining_window_fraction(api):
    """PRD §3.5: "First, the remaining fraction of the delivery window is found: the number of whole days from the logical clock to `delivery_end` (never below zero) divided by the total window length in whole days. Second, that fraction is applied to `total_mwh` to get the undelivered energy. Third, the fee in dollars is that remaining energy times the contract price times a fixed termination charge of twenty percent, and `termination_fee_cents` is that dollar figure converted to cents and rounded half up — the only rounding in the computation."

    Design: Difficulty/combinatorial_formula/termination_fee_remaining_window_fraction
    """
    setup_active_authority()
    contract = create_executed_contract(
        contract_type="PPA",
        delivery_start="2027-01-01T00:00:00Z",
        delivery_end="2028-01-01T00:00:00Z",
        capacity_mw=20.0,
        total_mwh=87600,
        price_dollars_per_mwh=50.0,
        rps_eligible_pct=1.0,
    )

    # Cross into the delivery window, then terminate mid-delivery.
    set_clock("2027-07-02T00:00:00Z")
    advance_epoch()
    delivering = validate_success(
        api.get_supply_contract(contract["id"], PM), 200
    )
    assert delivering["status"] == "DELIVERING"

    terminated = validate_success(
        api.terminate_supply_contract(contract["id"], {}, PM), 200
    )
    assert terminated["status"] == "TERMINATED"
    # 365-day window; 183 days remain -> remaining_mwh = 87600 * 183/365 = 43920
    # fee = 43920 MWh * 50 USD/MWh * 0.20 = 439200 USD = 43920000 cents
    assert terminated["termination_fee_cents"] == 43920000


def test_termination_reserve_debit_clamped_and_version_bumped(api):
    """PRD §2.7: "Every reserve debit is **clamped**: the debit taken is the smaller of the computed amount and the current reserve balance, so the balance can never be driven below zero."
    PRD §3.5: "Then the cascade: the Authority's `climate_reserve_balance_cents` is debited by the smaller of the fee and the current balance, per the clamping rule in §2.7, with any uncovered remainder expensed and discarded; and that reserve debit refreshes the Authority's `updated_at` and increments its `version` by 1."

    Design: Difficulty/combinatorial_formula/termination_fee_remaining_window_fraction
    """
    setup_active_authority()
    contract = create_executed_contract(
        contract_type="PPA",
        delivery_start="2027-01-01T00:00:00Z",
        delivery_end="2028-01-01T00:00:00Z",
        capacity_mw=20.0,
        total_mwh=87600,
        price_dollars_per_mwh=50.0,
        rps_eligible_pct=1.0,
    )
    set_clock("2027-07-02T00:00:00Z")
    advance_epoch()

    before = get_authority()
    assert before["climate_reserve_balance_cents"] == 0, "reserve never credited"

    validate_success(api.terminate_supply_contract(contract["id"], {}, PM), 200)

    after = get_authority()
    assert after["climate_reserve_balance_cents"] == 0, (
        "debit clamped at the zero reserve floor — the whole fee falls to expense"
    )
    assert_reserve_never_negative(after)
    assert after["version"] == before["version"] + 1, (
        "the reserve touch increments Authority.version by exactly 1"
    )


def test_contract_terminate_fee_exceeds_reserve(api):
    """PRD §3.5: "Third, the fee in dollars is that remaining energy times the contract price times a fixed termination charge of twenty percent, and `termination_fee_cents` is that dollar figure converted to cents and rounded half up — the only rounding in the computation."
    PRD §3.7: "Any remainder after every eligible balance is zeroed is not rejected; it is credited to the Authority's `climate_reserve_balance_cents` as the overpayment reserve credit described in §2.7, which is why the same file can produce different reserve balances depending on account balance state."

    Design: Difficulty/compensating_invariant/contract_terminate_reserve_clamp_conserves_reserve_floor
    """
    setup_active_authority()
    enrolled = setup_enrolled_accounts(
        specs=[create_account_spec(utility_account_number="U-9101")]
    )
    account_id = enrolled["account_ids"][0]

    # Seed the reserve with an overpayment: 1000 kWh billed = 11400 cents open;
    # net remittance 10011400 books the 10000000-cent remainder to the reserve.
    setup_settled_extract(
        "2026-04", [(account_id, 1000)], gross_remittance_cents=10011400
    )
    assert get_authority()["climate_reserve_balance_cents"] == 10000000

    contract = create_executed_contract(
        counterparty="WindPeak LLC",
        contract_type="PPA",
        delivery_start="2026-06-01T00:00:00Z",
        delivery_end="2027-06-01T00:00:00Z",
        capacity_mw=10.0,
        total_mwh=50000,
        price_dollars_per_mwh=40.0,
        rps_eligible_pct=1.0,
    )
    set_clock("2026-12-01T00:00:00Z")

    terminated = validate_success(
        api.terminate_supply_contract(contract["id"], {}, PM), 200
    )
    # 365-day window; 182 days remain -> remaining_mwh = 50000 * 182/365
    # fee = remaining_mwh * 40 * 0.20 USD -> 19945205 cents (round half up)
    assert terminated["termination_fee_cents"] == 19945205


def test_contract_terminate_reserve_floor_conserved(api):
    """PRD §2.7: "Every reserve debit is **clamped**: the debit taken is the smaller of the computed amount and the current reserve balance, so the balance can never be driven below zero. The uncovered remainder of a clamped debit is expensed — recorded, where the workflow provides one, in a dedicated field — and is otherwise discarded from the reserve's perspective. A debit against the reserve is a mutation of the Authority itself: it refreshes the Authority's `updated_at` and increments its `version` by 1."

    Design: Difficulty/compensating_invariant/contract_terminate_reserve_clamp_conserves_reserve_floor
    """
    setup_active_authority()
    enrolled = setup_enrolled_accounts(
        specs=[create_account_spec(utility_account_number="U-9101")]
    )
    setup_settled_extract(
        "2026-04",
        [(enrolled["account_ids"][0], 1000)],
        gross_remittance_cents=10011400,
    )
    contract = create_executed_contract(
        counterparty="WindPeak LLC",
        contract_type="PPA",
        delivery_start="2026-06-01T00:00:00Z",
        delivery_end="2027-06-01T00:00:00Z",
        capacity_mw=10.0,
        total_mwh=50000,
        price_dollars_per_mwh=40.0,
        rps_eligible_pct=1.0,
    )
    set_clock("2026-12-01T00:00:00Z")

    before = get_authority()
    assert before["climate_reserve_balance_cents"] == 10000000

    terminated = validate_success(
        api.terminate_supply_contract(contract["id"], {}, PM), 200
    )
    fee = terminated["termination_fee_cents"]

    after = get_authority()
    # Invariant: reserve_new == max(0, reserve_old - fee) — the 9945205-cent
    # deficit is expelled to expense, never driving the reserve negative.
    assert after["climate_reserve_balance_cents"] == max(0, 10000000 - fee) == 0
    assert after["version"] == before["version"] + 1


def test_coverage_gap_counts_any_overlap_contract(api):
    """PRD §3.5: "The in-scope account set is every account whose `enrollment_state` is `NOTICED` or `ENROLLED`. The snapshot's `total_energy_mwh` is the sum of the in-scope accounts' effective annual energy, converted from kWh to MWh at a thousand kWh per MWh and rounded to 0.001. Its `coincident_peak_mw` is the sum of the accounts' `annual_peak_kw`, converted kW to MW and likewise rounded to 0.001."

    Design: Difficulty/resource_temporal_overlap/supply_contract_window_coverage_gap_semantics
    """
    setup_active_authority()
    setup_enrolled_accounts(
        specs=[
            create_account_spec(
                utility_account_number="U-8001", annual_kwh_estimate=24000
            )
        ]
    )

    # Overlaps 2027 only through December — still counts its full total_mwh.
    create_executed_contract(
        contract_type="ENERGY_BLOCK",
        delivery_start="2027-12-01T00:00:00Z",
        delivery_end="2028-01-01T00:00:00Z",
        capacity_mw=5.0,
        total_mwh=30,
        price_dollars_per_mwh=60.0,
        rps_eligible_pct=0.0,
    )
    # Ends exactly at the 2027 boundary (exclusive delivery_end) — excluded.
    create_executed_contract(
        counterparty="HydroWest Inc",
        contract_type="ENERGY_BLOCK",
        delivery_start="2026-01-01T00:00:00Z",
        delivery_end="2027-01-01T00:00:00Z",
        capacity_mw=5.0,
        total_mwh=100,
        price_dollars_per_mwh=55.0,
        rps_eligible_pct=0.0,
        vintage_year=2025,
    )

    snapshot = create_forecast("COV-2027", "ADOPTED_PLAN", 2027)
    assert_load_forecast(snapshot)
    assert snapshot["total_energy_mwh"] == pytest.approx(24.0)
    assert snapshot["coincident_peak_mw"] == pytest.approx(0.004)


def test_coverage_gap_excludes_half_open_boundary_contract(api):
    """PRD §3.5: "And `coverage_gap_mwh` — negative meaning short — is the total energy rounded to whole MWh, minus the sum of `total_mwh` over every `EXECUTED` or `DELIVERING` contract whose delivery window overlaps any part of the forecast year."
    PRD §3.5: "A `PortfolioManager` creates a contract in `NEGOTIATING` with a `counterparty` name, a `contract_type` of `ENERGY_BLOCK` (energy only), `RA_CAPACITY` (resource-adequacy capacity), `REC_ONLY` (unbundled renewable credits), or `PPA` (bundled energy plus RECs); an inclusive `delivery_start` and exclusive `delivery_end`; a `capacity_mw` strictly positive; a `total_mwh` at least zero (zero is the norm for pure `RA_CAPACITY` contracts); a `price_dollars_per_mwh` at least zero; an `rps_eligible_pct` between 0 and 1.0 inclusive giving the fraction of delivered energy carrying RPS-eligible attributes; and a `vintage_year` capturing the PCIA-relevant commitment vintage — contracts committed in or before an account's vintage year raise that vintage's exit fee."

    Design: Difficulty/resource_temporal_overlap/supply_contract_window_coverage_gap_semantics
    """
    setup_active_authority()
    setup_enrolled_accounts(
        specs=[
            create_account_spec(
                utility_account_number="U-8001", annual_kwh_estimate=24000
            )
        ]
    )
    create_executed_contract(
        contract_type="ENERGY_BLOCK",
        delivery_start="2027-12-01T00:00:00Z",
        delivery_end="2028-01-01T00:00:00Z",
        capacity_mw=5.0,
        total_mwh=30,
        price_dollars_per_mwh=60.0,
        rps_eligible_pct=0.0,
    )
    create_executed_contract(
        counterparty="HydroWest Inc",
        contract_type="ENERGY_BLOCK",
        delivery_start="2026-01-01T00:00:00Z",
        delivery_end="2027-01-01T00:00:00Z",
        capacity_mw=5.0,
        total_mwh=100,
        price_dollars_per_mwh=55.0,
        rps_eligible_pct=0.0,
        vintage_year=2025,
    )

    snapshot = create_forecast("COV-2027", "ADOPTED_PLAN", 2027)
    # round(24.0) - 30 = -6: the December-only contract counts in full; the
    # contract ending at 2027-01-01 contributes nothing to year 2027.
    assert snapshot["coverage_gap_mwh"] == -6


def test_load_forecast_adopted_plan_variant(api):
    """PRD §3.5: "Under `ADOPTED_PLAN`, every in-scope account contributes its `annual_kwh_estimate` verbatim."
    PRD §3.5: "And `coverage_gap_mwh` — negative meaning short — is the total energy rounded to whole MWh, minus the sum of `total_mwh` over every `EXECUTED` or `DELIVERING` contract whose delivery window overlaps any part of the forecast year."

    Design: Difficulty/dual_variant_calc/load_forecast_adopted_vs_actual_trued_gap
    """
    setup_active_authority(rate_setting_policy="DISCOUNT_TO_INCUMBENT", discount_floor_bps=100)
    enrolled = setup_enrolled_accounts(
        specs=[create_account_spec(utility_account_number="U-1001")]
    )
    account_id = enrolled["account_ids"][0]

    # One settled billing month of 1500 kWh gives the account trailing actuals.
    setup_settled_extract("2026-05", [(account_id, 1500)])

    plan = create_forecast("PLAN-2027", "ADOPTED_PLAN", 2027)
    assert plan["total_energy_mwh"] == pytest.approx(12.0), (
        "12000 kWh estimate / 1000 = 12.0 MWh, estimate used verbatim"
    )
    assert plan["coverage_gap_mwh"] == 12, (
        "no executed contracts overlap 2027, so the gap equals the rounded total"
    )


def test_load_forecast_actual_trued_variant_diverges(api):
    """PRD §3.5: "Under `ACTUAL_TRUED`, an account that has at least one billing line in a settled extract instead contributes its trailing actuals — the sum of `usage_kwh` over its settled lines, annualized by multiplying by twelve and dividing by the count of distinct billed months — while accounts without settled billing history fall back to the estimate. Identical accounts can therefore produce divergent totals and coverage gaps across the two variants, which is the point: the adopted-plan variant measures the filed program, the actual-trued variant measures the lived one."

    Design: Difficulty/dual_variant_calc/load_forecast_adopted_vs_actual_trued_gap
    """
    setup_active_authority(rate_setting_policy="DISCOUNT_TO_INCUMBENT", discount_floor_bps=100)
    enrolled = setup_enrolled_accounts(
        specs=[create_account_spec(utility_account_number="U-1001")]
    )
    account_id = enrolled["account_ids"][0]
    setup_settled_extract("2026-05", [(account_id, 1500)])

    plan = create_forecast("PLAN-2027", "ADOPTED_PLAN", 2027)
    trued = create_forecast("TRUEUP-2027", "ACTUAL_TRUED", 2027)

    # Trailing actuals: 1500 kWh over 1 distinct billed month, annualized
    # * 12 / 1 = 18000 kWh -> 18.0 MWh.
    assert trued["total_energy_mwh"] == pytest.approx(18.0)
    assert trued["coverage_gap_mwh"] == 18
    assert plan["total_energy_mwh"] != trued["total_energy_mwh"], (
        "the two variants must diverge for identical accounts and contracts"
    )
    assert plan["coverage_gap_mwh"] != trued["coverage_gap_mwh"]


def test_ra_requirement_planning_reserve_margin_constant(api):
    """PRD §3.5: "The `ra_requirement_mw` is the coincident peak grossed up by a fifteen-percent planning reserve margin and rounded up to the nearest 0.1 MW."

    Design: Corner/calculations/ra_requirement_planning_reserve_margin_constant
    """
    setup_active_authority()
    setup_enrolled_accounts(
        specs=[
            create_account_spec(utility_account_number="U-6301", annual_peak_kw=4.0),
            create_account_spec(
                utility_account_number="U-6302",
                annual_kwh_estimate=10000,
                annual_peak_kw=3.5,
            ),
        ]
    )

    snapshot = create_forecast("RA-2027", "ADOPTED_PLAN", 2027)
    # coincident peak 7.5 kW = 0.0075 MW; 0.0075 * 1.15 = 0.008625 -> ceil to 0.1
    assert snapshot["ra_requirement_mw"] == pytest.approx(0.1), (
        "the fifteen-percent planning reserve margin is applied before the "
        "upward rounding to the nearest 0.1 MW"
    )
