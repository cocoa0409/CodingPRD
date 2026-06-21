"""Pricing-engine compliance: inclining-block tiers, TOU weighting, demand
charge, net-metering credit, LIHEAP assistance, budget levelizing, and the
empty-period floor. Every figure is uniquely derived by the PRD §3.3 pricing
sequence and §2.6 rounding rules.
"""
import pytest
from test_helpers import (
    validate_success,
    get_success_data,
    assert_bill,
    assert_bill_charge_decomposition,
)
from test_helpers.fixtures import (
    OPERATOR,
    create_active_tariff,
    open_account,
    add_meter,
    import_reads,
    create_draft_bill,
    issue_bill_with_occ,
    issue_bill_with_occ_data,
    setup_issued_bill,
    setup_budget_billed_issued_bill,
    setup_assisted_issued_bill,
    reads_for_2756,
    _iso,
)



# ===========================================================================
# Queue A — combinatorial_formula
# ===========================================================================
def test_tiered_tou_demand_nonlinear_energy_charge(api):
    """PRD §3.3: "Walking the tiers from the lowest, it fills each block up to
    its breakpoint width — the first block spans from zero up to the first
    breakpoint, each subsequent block spans from the previous breakpoint to the
    next, and the final block extends without upper bound — placing as much of
    the remaining imported energy as fits into each block and pricing that
    block's energy at that block's per-kWh rate."
    PRD §3.3: "For each of the three periods, it computes that period's share of
    total imported energy as the sum of `import_kwh` over billed reads in that
    period divided by `total_import_kwh` ... multiplies the tiered subtotal by
    that share and by the period's multiplier from `tou_multipliers`, and sums
    the three weighted contributions."

    1200 kWh straddles all three tiers (6000+9000+5000=20000), TOU-weighted at
    0.5 ON-peak (x1.5) + 0.5 mid-peak (x1.0) -> 25000.

    Design: Difficulty/combinatorial_formula/tiered_plus_tou_plus_demand_nonlinear_energy
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    meter = add_meter(account["id"])
    import_reads(meter["id"], [
        (_iso("2026-01-05", 16), _iso("2026-01-05", 17), 600.0, 0.0),
        (_iso("2026-01-05", 7), _iso("2026-01-05", 8), 600.0, 0.0),
    ])
    bill = create_draft_bill(
        account["id"], "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z",
        "2026-02-20T00:00:00Z")
    issued = validate_success(issue_bill_with_occ(bill["id"], account["id"]), 200)
    assert_bill(issued)
    assert issued["energy_charge_cents"] == 25000, issued["energy_charge_cents"]
    assert issued["demand_charge_cents"] == 480000, issued["demand_charge_cents"]
    assert issued["billed_peak_demand_kw"] == 600.0, issued["billed_peak_demand_kw"]
    # gross = fixed(1000) + energy(25000) + demand(480000); no credit/assistance.
    assert_bill_charge_decomposition(issued, fixed_charge_cents=1000)
    assert issued["actual_cost_cents"] == 506000, issued["actual_cost_cents"]


def test_energy_rounding_happens_once_after_tou_sum(api):
    """PRD §2.6: "The energy charge is rounded exactly once, after the
    time-of-use-weighted sum is fully accumulated across all periods — never per
    period."
    PRD §3.3: "The final `energy_charge_cents` is this TOU-weighted sum rounded
    half-up to whole cents exactly once, after the three contributions have been
    summed — not rounded per period."

    Single-tier rate 10c, tier_cost = 3.0kWh*10 = 30c; ON share 1/3 (x1.5) +
    MID share 2/3 (x1.0) = round(15 + 20) = 35.

    Design: Difficulty/combinatorial_formula/energy_rounding_order_pinned_after_tou_sum
    """
    tariff = create_active_tariff(
        fixed_charge_cents=0,
        tier_breakpoints_kwh=[],
        tier_rates_cents_per_kwh=[10],
        tou_multipliers={"ON_PEAK": 1.5, "MID_PEAK": 1.0, "OFF_PEAK": 0.8},
        demand_charge_cents_per_kw=0,
        net_metering_credit_cents_per_kwh=0,
    )
    account = open_account(tariff["id"])
    meter = add_meter(account["id"])
    import_reads(meter["id"], [
        (_iso("2026-03-05", 16), _iso("2026-03-05", 17), 1.0, 0.0),
        (_iso("2026-03-05", 7), _iso("2026-03-05", 8), 1.0, 0.0),
        (_iso("2026-03-05", 8), _iso("2026-03-05", 9), 1.0, 0.0),
    ])
    bill = create_draft_bill(
        account["id"], "2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z",
        "2026-04-20T00:00:00Z")
    issued = validate_success(issue_bill_with_occ(bill["id"], account["id"]), 200)
    assert issued["energy_charge_cents"] == 35, issued["energy_charge_cents"]
    assert issued["total_due_cents"] == 35, issued["total_due_cents"]


# ===========================================================================
# Queue A — dual_variant_calc (budget levelized vs standard actual)
# ===========================================================================
def test_budget_billed_total_due_levelized_while_actual_is_real_cost(api):
    """PRD §3.3: "When the account has an `ACTIVE` budget plan at issuance, the
    bill is flagged `is_budget_billed` true and its `total_due_cents` is set to
    the plan's levelized installment rather than the real cost ... otherwise
    `is_budget_billed` is false and `total_due_cents` equals `actual_cost_cents`."
    PRD §3.7: "the bill's `total_due_cents` is set to the plan's
    `levelized_amount_cents` regardless of that month's real cost, while the
    bill's `actual_cost_cents` still holds the true computed amount."

    Same 2756 read set: levelized total_due 1500 diverges from actual 2756.

    Design: Difficulty/dual_variant_calc/budget_levelized_vs_standard_actual_on_bill
    """
    scene = setup_budget_billed_issued_bill(levelized_amount_cents=1500)
    bill = scene["bill"]
    assert bill["is_budget_billed"] is True, bill["is_budget_billed"]
    assert bill["total_due_cents"] == 1500, bill["total_due_cents"]
    assert bill["actual_cost_cents"] == 2756, bill["actual_cost_cents"]
    assert bill["energy_charge_cents"] == 156, bill["energy_charge_cents"]
    assert bill["demand_charge_cents"] == 1600, bill["demand_charge_cents"]


def test_standard_billed_total_due_equals_actual_cost(api):
    """PRD §3.3: "otherwise `is_budget_billed` is false and `total_due_cents`
    equals `actual_cost_cents`."

    With no budget plan, the same 2756 read set produces total_due == actual ==
    2756 — the standard variant of the dual calculation.

    Design: Difficulty/dual_variant_calc/budget_levelized_vs_standard_actual_on_bill
    """
    scene = setup_issued_bill(read_tuples=reads_for_2756())
    bill = scene["bill"]
    assert bill["is_budget_billed"] is False, bill["is_budget_billed"]
    assert bill["total_due_cents"] == 2756, bill["total_due_cents"]
    assert bill["actual_cost_cents"] == 2756, bill["actual_cost_cents"]


# ===========================================================================
# Queue A — boundary_precision_check (empty-period floor)
# ===========================================================================
def test_empty_period_bill_floors_to_fixed_charge(api):
    """PRD §3.3: "The `billed_peak_demand_kw` is the maximum `avg_demand_kw`
    among only those billed reads whose `tou_period` is `ON_PEAK`; if there are
    no `ON_PEAK` reads in the period, `billed_peak_demand_kw` is zero."
    PRD §3.3: "it computes that period's share of total imported energy as the
    sum of `import_kwh` over billed reads in that period divided by
    `total_import_kwh` (a share of zero when there is no imported energy at all)"
    PRD §3.3: "Fifth, it forms the gross charge before credits as the tariff's
    `fixed_charge_cents` plus `energy_charge_cents` plus `demand_charge_cents`."

    A period with zero reads: total_import 0, energy 0, demand 0, total_due ==
    fixed_charge 1000 (the div-by-zero share guard holds).

    Design: Difficulty/boundary_precision_check/empty_period_bill_zero_consumption_floors_to_fixed
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    add_meter(account["id"])  # meter exists but no reads in window
    bill = create_draft_bill(
        account["id"], "2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z",
        "2026-06-20T00:00:00Z")
    issued = validate_success(issue_bill_with_occ(bill["id"], account["id"]), 200)
    assert issued["total_import_kwh"] == 0, issued["total_import_kwh"]
    assert issued["energy_charge_cents"] == 0, issued["energy_charge_cents"]
    assert issued["demand_charge_cents"] == 0, issued["demand_charge_cents"]
    assert issued["total_due_cents"] == 1000, issued["total_due_cents"]


# ===========================================================================
# Queue A — second-coverage tests
# ===========================================================================
def test_tier_straddle_two_blocks_with_tou_reweight(api):
    """PRD §3.3: "the first block spans from zero up to the first breakpoint,
    each subsequent block spans from the previous breakpoint to the next ...
    placing as much of the remaining imported energy as fits into each block and
    pricing that block's energy at that block's per-kWh rate."
    PRD §3.3: "multiplies the tiered subtotal by that share and by the period's
    multiplier from `tou_multipliers`, and sums the three weighted contributions."

    A second non-linear straddle: 700 ON-peak + 100 mid-peak = 800 kWh fills
    block0 (500@12=6000) and part of block1 (300@18=5400) for tier_cost 11400,
    TOU-weighted to round(11400*(0.875*1.5 + 0.125*1.0)) = 16388; demand
    700kW*800 = 560000.

    Design: Difficulty/combinatorial_formula/tiered_plus_tou_plus_demand_nonlinear_energy
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    meter = add_meter(account["id"])
    import_reads(meter["id"], [
        (_iso("2026-01-05", 16), _iso("2026-01-05", 17), 700.0, 0.0),
        (_iso("2026-01-05", 7), _iso("2026-01-05", 8), 100.0, 0.0),
    ])
    bill = create_draft_bill(
        account["id"], "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z",
        "2026-02-20T00:00:00Z")
    issued = validate_success(issue_bill_with_occ(bill["id"], account["id"]), 200)
    assert issued["energy_charge_cents"] == 16388, issued["energy_charge_cents"]
    assert issued["demand_charge_cents"] == 560000, issued["demand_charge_cents"]
    assert issued["billed_peak_demand_kw"] == 700.0, issued["billed_peak_demand_kw"]


def test_energy_round_once_diverges_from_per_period_rounding(api):
    """PRD §2.6: "The energy charge is rounded exactly once, after the
    time-of-use-weighted sum is fully accumulated across all periods — never per
    period."

    A fractional case (single rate 7c; one read in each TOU period, import 1.0
    each) where round-once differs from per-period rounding: the three weighted
    contributions are 10.5 + 7.0 + 5.6 = 23.1, rounded once to 23. Per-period
    rounding would give round(10.5)+round(7.0)+round(5.6) = 11+7+6 = 24, which
    the PRD forbids.

    Design: Difficulty/combinatorial_formula/energy_rounding_order_pinned_after_tou_sum
    """
    tariff = create_active_tariff(
        fixed_charge_cents=0,
        tier_breakpoints_kwh=[],
        tier_rates_cents_per_kwh=[7],
        tou_multipliers={"ON_PEAK": 1.5, "MID_PEAK": 1.0, "OFF_PEAK": 0.8},
        demand_charge_cents_per_kw=0,
        net_metering_credit_cents_per_kwh=0,
    )
    account = open_account(tariff["id"])
    meter = add_meter(account["id"])
    import_reads(meter["id"], [
        (_iso("2026-03-05", 16), _iso("2026-03-05", 17), 1.0, 0.0),  # ON_PEAK
        (_iso("2026-03-05", 7), _iso("2026-03-05", 8), 1.0, 0.0),    # MID_PEAK
        (_iso("2026-03-05", 0), _iso("2026-03-05", 1), 1.0, 0.0),    # OFF_PEAK
    ])
    bill = create_draft_bill(
        account["id"], "2026-03-01T00:00:00Z", "2026-04-01T00:00:00Z",
        "2026-04-20T00:00:00Z")
    issued = validate_success(issue_bill_with_occ(bill["id"], account["id"]), 200)
    assert issued["energy_charge_cents"] == 23, issued["energy_charge_cents"]


def test_empty_period_with_budget_plan_still_floors_to_fixed_actual(api):
    """PRD §3.3: "Fifth, it forms the gross charge before credits as the tariff's
    `fixed_charge_cents` plus `energy_charge_cents` plus `demand_charge_cents`."
    PRD §3.3: "the bill's `actual_cost_cents` still holds the true computed
    amount."

    A zero-read period still prices to a fixed-charge floor: actual_cost_cents is
    the fixed 1000 even though the levelized total_due is charged separately.

    Design: Difficulty/boundary_precision_check/empty_period_bill_zero_consumption_floors_to_fixed
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    add_meter(account["id"])  # no reads in the window
    get_success_data(api.create_budget_plan(
        {"account_id": account["id"], "levelized_amount_cents": 5000}, OPERATOR))
    bill = create_draft_bill(
        account["id"], "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z",
        "2026-08-20T00:00:00Z")
    issued = validate_success(issue_bill_with_occ(bill["id"], account["id"]), 200)
    assert issued["energy_charge_cents"] == 0, issued["energy_charge_cents"]
    assert issued["demand_charge_cents"] == 0, issued["demand_charge_cents"]
    assert issued["actual_cost_cents"] == 1000, issued["actual_cost_cents"]


# ===========================================================================
# Queue B — calculations
# ===========================================================================
def test_liheap_assistance_applied_after_credit(api):
    """PRD §3.3: "Seventh, it applies assistance after net-metering credit. The
    pre-assistance amount is the gross charge minus
    `net_metering_credit_applied_cents`. If the account has assistance
    available, the `assistance_applied_cents` is the smaller of the grant's
    `remaining_cents` and that pre-assistance amount; with no grant it is zero."
    PRD §3.8: "When a bill consumes the last of the remaining balance so that
    `remaining_cents` reaches zero, the grant moves to `EXHAUSTED`: ... directly
    `PLEDGED → EXHAUSTED` when a single bill consumes the entire grant in one
    step."

    Gross 2756 with a 2000 grant: assistance 2000 applied, total_due 756, grant
    remaining 0 and EXHAUSTED.

    Design: Corner/calculations/liheap_assistance_applied_after_credit
    """
    scene = setup_assisted_issued_bill(pledged_cents=2000)
    bill = scene["bill"]
    assert bill["assistance_applied_cents"] == 2000, bill["assistance_applied_cents"]
    assert bill["total_due_cents"] == 756, bill["total_due_cents"]
    grant = get_success_data(api.get_assistance_grant(scene["grant"]["id"], OPERATOR))
    assert grant["remaining_cents"] == 0, grant["remaining_cents"]
    assert grant["status"] == "EXHAUSTED", grant["status"]


def test_net_metering_carryover_rolls_to_next_bill(api):
    """PRD §3.3: "the maximum creditable amount is the greater of zero and the
    gross charge minus that floor. The `net_metering_credit_applied_cents` is
    the smaller of the credit pool and that maximum creditable amount, and
    whatever remains of the pool after applying credit becomes the carryover
    that rolls forward — that is, the account's `net_metering_credit_balance_cents`
    is debited by `net_metering_credit_applied_cents` at issuance, leaving the
    unused remainder banked for next month."

    Bill1 exports 2000 kWh (credit 20000) but only 96 is creditable above the
    1000 floor, leaving carryover 19904. Bill2 (gross 2756, floor 2600) consumes
    156, leaving 19748.

    Design: Corner/calculations/net_metering_carryover_rolls_to_next_bill
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    meter = add_meter(account["id"])
    # Period 1: OFF_PEAK read import 10 export 2000 (hour 00).
    import_reads(meter["id"], [
        (_iso("2026-01-05", 0), _iso("2026-01-05", 1), 10.0, 2000.0),
    ])
    bill1 = create_draft_bill(
        account["id"], "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z",
        "2026-02-20T00:00:00Z")
    issue_bill_with_occ_data(bill1["id"], account["id"])
    acct_after_1 = get_success_data(api.get_account(account["id"], OPERATOR))
    assert acct_after_1["net_metering_credit_balance_cents"] == 19904, \
        acct_after_1["net_metering_credit_balance_cents"]
    # Period 2: standard 2756 read set, no export.
    import_reads(meter["id"], reads_for_2756("2026-02-05"))
    bill2 = create_draft_bill(
        account["id"], "2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z",
        "2026-03-20T00:00:00Z")
    issued2 = issue_bill_with_occ_data(bill2["id"], account["id"])
    assert issued2["net_metering_credit_applied_cents"] == 156, \
        issued2["net_metering_credit_applied_cents"]
    assert issued2["total_due_cents"] == 2600, issued2["total_due_cents"]
    acct_after_2 = get_success_data(api.get_account(account["id"], OPERATOR))
    assert acct_after_2["net_metering_credit_balance_cents"] == 19748, \
        acct_after_2["net_metering_credit_balance_cents"]


def test_budget_true_up_actual_minus_levelized(api):
    """PRD §3.7: "True-up computes the plan's `true_up_balance_cents` as
    `accumulated_actual_cents` minus `accumulated_levelized_cents` — a positive
    figure means the customer underpaid through the levelized stream and owes a
    catch-up ... and adjusts the account's `balance_cents` by that delta."
    PRD §3.7: "Each such bill accumulates the plan's two running counters —
    `accumulated_actual_cents`, the running sum of the budget-billed bills'
    `actual_cost_cents`, and `accumulated_levelized_cents`, the running sum of
    the levelized installments charged"

    Two budget-billed bills (actual 2756 each, levelized 1500 each): true-up =
    5512 - 3000 = 2512, and the plan reaches TRUED_UP.

    Design: Corner/calculations/budget_true_up_actual_minus_levelized
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    meter = add_meter(account["id"])
    import_reads(meter["id"], reads_for_2756("2026-01-05"))
    import_reads(meter["id"], reads_for_2756("2026-02-05"))
    plan = get_success_data(api.create_budget_plan(
        {"account_id": account["id"], "levelized_amount_cents": 1500}, OPERATOR))
    bill1 = create_draft_bill(
        account["id"], "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z",
        "2026-02-20T00:00:00Z")
    issue_bill_with_occ_data(bill1["id"], account["id"])
    bill2 = create_draft_bill(
        account["id"], "2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z",
        "2026-03-20T00:00:00Z")
    issue_bill_with_occ_data(bill2["id"], account["id"])
    acct = get_success_data(api.get_account(account["id"], OPERATOR))
    trued = validate_success(api.true_up_budget_plan(
        plan["id"], {"expected_account_version": acct["version"]}, OPERATOR), 200)
    assert trued["accumulated_actual_cents"] == 5512, trued["accumulated_actual_cents"]
    assert trued["accumulated_levelized_cents"] == 3000, trued["accumulated_levelized_cents"]
    assert trued["true_up_balance_cents"] == 2512, trued["true_up_balance_cents"]
    assert trued["status"] == "TRUED_UP", trued["status"]


def test_account_balance_computed_from_bills_and_payments(api):
    """PRD §2.7: "Each account maintains a running `balance_cents`: a net amount
    owed, equal to the sum of issued bills' `total_due_cents` less the sum of
    applied payment amounts less applied assistance ... Issuing a bill increases
    `balance_cents` by that bill's `total_due_cents`"

    After issuing one standard 2756 bill the account balance is 2756.

    Design: Corner/entities/account_balance_computed_from_bills_and_payments
    """
    scene = setup_issued_bill(read_tuples=reads_for_2756())
    acct = get_success_data(api.get_account(scene["account"]["id"], OPERATOR))
    assert acct["balance_cents"] == 2756, acct["balance_cents"]


def test_meter_read_computes_tou_period_and_demand(api):
    """PRD §3.2: "It computes `tou_period` from the hour-of-day of
    `interval_start` in UTC under a fixed schedule: hours sixteen through twenty
    (that is, 16:00 up to but not including 21:00) are `ON_PEAK`"
    PRD §3.2: "It also computes `avg_demand_kw` as the interval's `import_kwh`
    divided by one hour — numerically equal to `import_kwh`, since each interval
    spans exactly one hour."

    An hour-16 read with import 5.0 derives tou_period ON_PEAK and avg_demand_kw
    5.0 server-side.

    Design: Corner/entities/meter_read_computed_tou_period_and_demand_ignore_client_input
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    meter = add_meter(account["id"], meter_type="BIDIRECTIONAL")
    read = validate_success(api.create_meter_read({
        "meter_id": meter["id"],
        "interval_start": "2026-01-05T16:00:00Z",
        "interval_end": "2026-01-05T17:00:00Z",
        "import_kwh": 5.0,
        "export_kwh": 0.0,
    }, OPERATOR), 201)
    assert read["tou_period"] == "ON_PEAK", read["tou_period"]
    assert read["avg_demand_kw"] == 5.0, read["avg_demand_kw"]


def test_meter_read_is_lean_resource_no_version(api):
    """PRD §2.4: "A `MeterRead` and the `SystemClock` carry only `id` and
    `created_at`; they expose neither `updated_at` nor `version`, because an
    imported AMI interval read is immutable once accepted and the clock is a
    singleton control surface."

    Design: Corner/entities/meter_read_immutable_no_version_field
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    meter = add_meter(account["id"], meter_type="BIDIRECTIONAL")
    read = validate_success(api.create_meter_read({
        "meter_id": meter["id"],
        "interval_start": "2026-01-05T16:00:00Z",
        "interval_end": "2026-01-05T17:00:00Z",
        "import_kwh": 5.0,
        "export_kwh": 0.0,
    }, OPERATOR), 201)
    assert "id" in read and "created_at" in read
    assert "version" not in read, "MeterRead must not expose version"
    assert "updated_at" not in read, "MeterRead must not expose updated_at"


# ===========================================================================
# Queue B — consistency_model
# ===========================================================================
def test_issue_returns_fully_computed_charges_immediately(api):
    """PRD §3.3: "Issuing a bill is the heart of the engine. A `BillingOperator`
    issues a `DRAFT` bill, which transitions it `DRAFT → ISSUED`, snapshots the
    account's current tariff onto the bill's `tariff_id`, and runs the full
    pricing calculation described below."
    PRD §3.3: "Fifth, it forms the gross charge before credits as the tariff's
    `fixed_charge_cents` plus `energy_charge_cents` plus `demand_charge_cents`."

    The issue response itself carries energy 156, demand 1600, total_due 2756 —
    immediate consistency, no read-after-write lag.

    Design: Corner/consistency_model/issued_bill_charges_visible_in_same_response
    """
    scene = setup_issued_bill(read_tuples=reads_for_2756())
    bill = scene["bill"]
    assert bill["energy_charge_cents"] == 156, bill["energy_charge_cents"]
    assert bill["demand_charge_cents"] == 1600, bill["demand_charge_cents"]
    assert bill["total_due_cents"] == 2756, bill["total_due_cents"]
