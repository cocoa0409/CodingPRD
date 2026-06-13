"""Charge-stack pricing: tiered water, sewer ratio/cap, fixed/assistance,
leak credit, and the cycle-window inclusion rule.

Translates Difficulty queue: dual_variant_calc (sewer), combinatorial_formula
(tiered water), boundary_precision_check (tier ceiling), resource_temporal_overlap
(cycle window), and Corner queue: calculations section + meter-read computed field.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    setup_canonical_draft_bill, setup_sewer_variant_bills,
    setup_single_potable_bill, setup_pending_leak_on_posted,
    setup_account_with_meters, TEST_USERS, make_customer_headers,
    assert_bill, ApiErrorId,
)
from test_helpers import fixtures, factories

CLERK = TEST_USERS["billing_clerk_headers"]
CASEWORKER = TEST_USERS["caseworker_headers"]


# ===========================================================================
# Tiered marginal water volumetric (combinatorial_formula)
# ===========================================================================
def test_tiered_water_three_tier_marginal_charge(api):
    """PRD §3.4: "Walking the tiers from lowest to highest, each tier prices the
    slice of consumption that falls within its band: the span priced at a tier is
    the consumption remaining when that tier is reached, but no more than the
    difference between that tier's ceiling and the previous tier's ceiling (the
    terminal null-ceiling tier absorbs whatever remains). Each tier's span in
    gallons is multiplied by that tier's `rate_cents_per_kgal`, and these per-tier
    products are accumulated without rounding."
    PRD §3.4: "The tiered water charge is computed over the combined consumption —
    potable plus irrigation gallons together."

    Design: Difficulty/combinatorial_formula/tiered_marginal_water_three_tiers_mode_a
    """
    account, bill, rs, cycle, _, _ = setup_canonical_draft_bill(potable=12000, irrigation=8000)
    data = validate_success(api.get_bill(bill["id"], CLERK))
    assert data["potable_consumption_gallons"] == 12000
    assert data["irrigation_consumption_gallons"] == 8000
    # 5000@300 + 10000@500 + 5000@800 = 10,500,000 cents*gal /1000 = 10500
    assert data["water_volumetric_cents"] == 10500
    assert_bill(data)


def test_tiered_water_rounds_once_at_end(api):
    """PRD §3.4: "After all consumption has been allocated, the accumulated total —
    which is in units of cents times gallons — is divided by 1000 and rounded half
    up exactly once to yield `water_volumetric_cents`. Rounding happens only at the
    very end, never per tier."

    Design: Difficulty/combinatorial_formula/tiered_marginal_water_three_tiers_mode_a
    """
    # 12000 potable only over the three-tier canonical schedule:
    # 5000@300 + 7000@500 = 1,500,000 + 3,500,000 = 5,000,000 /1000 = 5000
    account, bill = setup_single_potable_bill(12000)
    data = validate_success(api.get_bill(bill["id"], CLERK))
    assert data["potable_consumption_gallons"] == 12000
    assert data["water_volumetric_cents"] == 5000


# ===========================================================================
# Sewer ratio: uncapped vs winter-capped (dual_variant_calc)
# ===========================================================================
def test_sewer_uncapped_variant_full_ratio_volume(api):
    """PRD §3.4: "if the schedule leaves the cap null, the `billable_sewer_gallons`
    is the ratio volume unchanged (the uncapped variant). The `sewer_volumetric_cents`
    is then `billable_sewer_gallons` multiplied by `sewer_rate_cents_per_kgal`,
    divided by 1000, rounded half up."

    Design: Difficulty/dual_variant_calc/sewer_ratio_uncapped_vs_winter_capped
    """
    bill_u, bill_c = setup_sewer_variant_bills(potable=12000)
    data = validate_success(api.get_bill(bill_u["id"], CLERK))
    # ratio_volume = round_half_up(12000*90/100) = 10800 ; *600/1000 = 6480
    assert data["billable_sewer_gallons"] == 10800
    assert data["sewer_volumetric_cents"] == 6480


def test_sewer_winter_capped_variant_caps_billable_gallons(api):
    """PRD §3.4: "If the schedule supplies a `sewer_cap_gallons`, the
    `billable_sewer_gallons` is the lesser of that ratio volume and the cap (the
    winter-capped variant)"

    Design: Difficulty/dual_variant_calc/sewer_ratio_uncapped_vs_winter_capped
    """
    bill_u, bill_c = setup_sewer_variant_bills(potable=12000)
    data = validate_success(api.get_bill(bill_c["id"], CLERK))
    # ratio 10800 capped at 8000 ; 8000*600/1000 = 4800
    assert data["billable_sewer_gallons"] == 8000
    assert data["sewer_volumetric_cents"] == 4800


def test_irrigation_excluded_from_sewer_volume(api):
    """PRD §3.4: "Sewer is derived from potable consumption alone; irrigation never
    contributes. First, a ratio volume is computed as `potable_consumption_gallons`
    multiplied by `sewer_ratio_pct`, divided by 100, rounded half up to whole gallons."

    Design: Corner/calculations/irrigation_excluded_from_sewer_volume
    """
    account, bill, rs, cycle, _, _ = setup_canonical_draft_bill(potable=12000, irrigation=8000)
    data = validate_success(api.get_bill(bill["id"], CLERK))
    assert data["irrigation_consumption_gallons"] == 8000
    # sewer billable uses potable only: round_half_up(12000*90/100) = 10800, not 18000
    assert data["billable_sewer_gallons"] == 10800
    assert data["water_volumetric_cents"] == 10500


# ===========================================================================
# Fixed charge + assistance discount (calculations)
# ===========================================================================
def test_assistance_discount_reduces_fixed_charge(api):
    """PRD §3.4: "If the account is enrolled in assistance, the fixed charge is
    reduced by the schedule's `assistance_discount_pct`: the combined fixed charge
    is multiplied by one minus that percentage (equivalently, the discount
    percentage of the combined fixed charge is subtracted), rounded half up to
    whole cents."

    Design: Corner/calculations/assistance_discount_reduces_fixed_charge
    """
    ctx = setup_account_with_meters(rate_overrides={"assistance_discount_pct": 25})
    account = ctx["account"]
    api_client.create_assistance_enrollment(
        account["id"],
        factories.assistance_enrollment_payload(grants_shutoff_protection=False),
        CASEWORKER)
    cycle = fixtures.create_cycle()
    fixtures.add_read(ctx["potable_meter"]["id"], 0, "2026-01-01T00:00:00Z")
    fixtures.add_read(ctx["potable_meter"]["id"], 12000, "2026-01-31T00:00:00Z")
    fixtures.add_read(ctx["irrigation_meter"]["id"], 0, "2026-01-01T00:00:00Z")
    fixtures.add_read(ctx["irrigation_meter"]["id"], 8000, "2026-01-31T00:00:00Z")
    bill = fixtures.generate_bill(account["id"], cycle["id"])
    data = validate_success(api.get_bill(bill["id"], CLERK))
    # fixed 2000 - round_half_up(2000*25/100)=500 -> 1500 ; amount 1500+10500+6480
    assert data["fixed_charge_cents"] == 1500
    assert data["amount_billed_cents"] == 18480


# ===========================================================================
# Leak credit computation (leak_credit calculation)
# ===========================================================================
def test_leak_approve_computes_credit_and_reduces_balance(api):
    """PRD §3.8: "multiply the over-baseline gallons by the lowest tier rate and by
    the leak-adjustment percentage divided by 100, divide by 1000, and round half up
    to whole cents."
    PRD §3.8: "The computed credit is written to the adjustment's `credit_cents` and
    onto the bill's `leak_credit_cents`, and the bill's `amount_billed_cents` is
    recomputed as a cascade. If the bill is not on a budget plan, the bill's
    `total_cents` is recomputed as well and the account's `balance_due_cents` is
    decreased by the credit, compensating against the original posting."

    Design: Corner/state_machines/leak_approve_computes_credit_and_reduces_balance
    """
    account, bill, leak = setup_pending_leak_on_posted(baseline_gallons=4000,
                                                       potable=12000, irrigation=8000)
    approved = validate_success(api.approve_leak_adjustment(leak["id"], CASEWORKER))
    assert approved["status"] == "APPROVED"
    # over_baseline 8000 * lowest tier 300 * 50/100 /1000 = 1200
    assert approved["credit_cents"] == 1200
    bill_after = validate_success(api.get_bill(bill["id"], CLERK))
    assert bill_after["leak_credit_cents"] == 1200
    assert bill_after["amount_billed_cents"] == 17780
    acct_after = validate_success(api.get_account(account["id"], CLERK))
    assert acct_after["balance_due_cents"] == 17780


# ===========================================================================
# Water tier ceiling boundary (boundary_precision_check)
# ===========================================================================
def test_water_tier_ceiling_exact_value(api):
    """PRD §3.4: "the span priced at a tier is the consumption remaining when that
    tier is reached, but no more than the difference between that tier's ceiling and
    the previous tier's ceiling (the terminal null-ceiling tier absorbs whatever
    remains). Each tier's span in gallons is multiplied by that tier's
    `rate_cents_per_kgal`"

    Design: Difficulty/boundary_precision_check/water_tier_ceiling_exact_vs_plus_one
    """
    # exactly 5000 gal: all in tier 1 @300 -> 5000*300/1000 = 1500
    account, bill = setup_single_potable_bill(5000)
    data = validate_success(api.get_bill(bill["id"], CLERK))
    assert data["water_volumetric_cents"] == 1500


def test_water_tier_ceiling_plus_one_crosses_into_next_tier(api):
    """PRD §3.4: "the span priced at a tier is the consumption remaining when that
    tier is reached, but no more than the difference between that tier's ceiling and
    the previous tier's ceiling (the terminal null-ceiling tier absorbs whatever
    remains). Each tier's span in gallons is multiplied by that tier's
    `rate_cents_per_kgal`"

    Design: Difficulty/boundary_precision_check/water_tier_ceiling_exact_vs_plus_one
    """
    # 5001 gal: 5000@300 + 1@500 = 1,500,000 + 500 = 1,500,500 /1000 = 1501 (rhu)
    account, bill = setup_single_potable_bill(5001)
    data = validate_success(api.get_bill(bill["id"], CLERK))
    assert data["water_volumetric_cents"] == 1501


# ===========================================================================
# Cycle window half-open inclusion (resource_temporal_overlap)
# ===========================================================================
def test_bill_window_excludes_period_end_read(api):
    """PRD §3.4: "The consumption inputs are summed from the account's `ACTIVE`
    meters whose reads fall within the half-open cycle window — at or after
    `period_start` and strictly before `period_end`."

    Design: Difficulty/resource_temporal_overlap/bill_cycle_window_excludes_period_end_read
    """
    rs = fixtures.create_rate_schedule()
    account = fixtures.create_account(rs["id"])
    meter = fixtures.create_meter(account["id"], "POTABLE", "P1")
    cycle = fixtures.create_cycle()  # period_end 2026-02-01
    fixtures.add_read(meter["id"], 0, "2026-01-01T00:00:00Z")
    fixtures.add_read(meter["id"], 10000, "2026-01-20T00:00:00Z")
    # read exactly at period_end (exclusive boundary) -> excluded
    fixtures.add_read(meter["id"], 15000, "2026-02-01T00:00:00Z")
    bill = fixtures.generate_bill(account["id"], cycle["id"])
    data = validate_success(api.get_bill(bill["id"], CLERK))
    assert data["potable_consumption_gallons"] == 10000
    # 5000@300 + 5000@500 = 1,500,000 + 2,500,000 = 4,000,000 /1000 = 4000
    assert data["water_volumetric_cents"] == 4000


def test_bill_window_includes_reads_after_period_start(api):
    """PRD §3.4: "The consumption inputs are summed from the account's `ACTIVE`
    meters whose reads fall within the half-open cycle window — at or after
    `period_start` and strictly before `period_end`."

    Design: Difficulty/resource_temporal_overlap/bill_cycle_window_excludes_period_end_read
    """
    rs = fixtures.create_rate_schedule()
    account = fixtures.create_account(rs["id"])
    meter = fixtures.create_meter(account["id"], "POTABLE", "P1")
    cycle = fixtures.create_cycle()  # [2026-01-01, 2026-02-01)
    # read AT period_start (inclusive) and a later read strictly inside the window
    fixtures.add_read(meter["id"], 0, "2026-01-01T00:00:00Z")
    fixtures.add_read(meter["id"], 10000, "2026-01-31T23:00:00Z")
    bill = fixtures.generate_bill(account["id"], cycle["id"])
    data = validate_success(api.get_bill(bill["id"], CLERK))
    # both in-window reads counted -> 10000 gal consumption
    assert data["potable_consumption_gallons"] == 10000
    assert data["water_volumetric_cents"] == 4000


# ===========================================================================
# Computed consumption from prior read (entities / computed field)
# ===========================================================================
def test_meter_read_consumption_computed_from_prior(api):
    """PRD §3.2: "On import the system computes `consumption_gallons` for the read:
    the difference between this read's `reading_gallons` and the prior chronological
    read for the same meter. The very first read for a meter has a
    `consumption_gallons` of zero"
    PRD §3.2: "Importing a read also refreshes the owning meter's `last_reading_gallons`."

    Design: Corner/entities/meter_read_consumption_computed_from_prior_read
    """
    rs = fixtures.create_rate_schedule()
    account = fixtures.create_account(rs["id"])
    meter = fixtures.create_meter(account["id"], "POTABLE", "P1")
    r1 = validate_success(
        api.create_read(meter["id"], factories.read_payload(5000, "2026-01-01T00:00:00Z"), CLERK), 201)
    assert r1["consumption_gallons"] == 0
    r2 = validate_success(
        api.create_read(meter["id"], factories.read_payload(12000, "2026-01-15T00:00:00Z"), CLERK), 201)
    assert r2["consumption_gallons"] == 7000
    meter_after = validate_success(api.get_meter(meter["id"], CLERK))
    assert meter_after["last_reading_gallons"] == 12000


# ===========================================================================
# Bill generation with no reads (calculations / empty-set boundary)
# ===========================================================================
def test_bill_generation_no_reads_returns_422(api):
    """PRD §3.4: "If the account has no meter reads within the cycle window,
    generation is rejected with `ERR_NO_CONSUMPTION_DATA`."

    Design: Corner/calculations/bill_generation_no_reads_returns_422
    """
    rs = fixtures.create_rate_schedule()
    account = fixtures.create_account(rs["id"])
    fixtures.create_meter(account["id"], "POTABLE", "P1")
    cycle = fixtures.create_cycle()
    resp = api.create_bill(factories.bill_payload(account["id"], cycle["id"]), CLERK)
    validate_error(resp, ApiErrorId.ERR_NO_CONSUMPTION_DATA.value)
