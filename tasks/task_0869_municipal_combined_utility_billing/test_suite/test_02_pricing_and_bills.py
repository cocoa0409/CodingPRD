"""Consolidated bill pricing engine: tiered rates, rounding order, assistance,
tier boundaries, estimated-vs-actual variants, and period-overlap rules."""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS,
    create_water_schedule, create_sewer_schedule, open_account, add_meter, add_reading,
    generate_bill, enroll_assistance, setup_account_with_water_bill,
)

BS = TEST_USERS["billing_specialist_headers"]


# ---------------------------------------------------------------------------
# combinatorial_formula / water_tiered_marginal_rate_with_assistance
# ---------------------------------------------------------------------------
def test_water_tiered_marginal_pricing_pre_discount_total(api):
    """PRD §3.3: "Under the test water schedule, the first 6,000 gallons are priced at 315
    cents per 1,000 gallons, the next block up to 12,000 gallons (the 6,000 gallons above
    6,000) at 500 cents per 1,000 gallons, and every gallon beyond 12,000 at 800 cents per
    1,000 gallons."

    Design: Difficulty/combinatorial_formula/water_tiered_marginal_rate_with_assistance
    """
    create_water_schedule(api)
    account = open_account(api, account_holder_name="Liheap Lou")
    enroll_assistance(api, account["id"], "LIHEAP", 0.20)
    meter = add_meter(api, account["id"], "WATER")
    add_reading(api, meter["id"], 9500, "ACTUAL")
    bill = generate_bill(api, account["id"])
    assert bill["pre_discount_total_cents"] == 4640


def test_assistance_discount_reduces_actual_and_total(api):
    """PRD §3.3: "An assistance discount, if the account carries one, produces
    `assistance_credit_cents` equal to the account's `assistance_discount_pct` multiplied
    by `pre_discount_total_cents`, rounded half up; with no assistance this credit is 0.
    The bill's `actual_charges_cents` is `pre_discount_total_cents` minus
    `assistance_credit_cents` — the true metered cost regardless of budget billing. For an
    ordinary bill, `total_due_cents` equals `actual_charges_cents`."

    Design: Difficulty/combinatorial_formula/water_tiered_marginal_rate_with_assistance
    """
    create_water_schedule(api)
    account = open_account(api, account_holder_name="Liheap Lou")
    enroll_assistance(api, account["id"], "LIHEAP", 0.20)
    meter = add_meter(api, account["id"], "WATER")
    add_reading(api, meter["id"], 9500, "ACTUAL")
    bill = generate_bill(api, account["id"])
    assert bill["assistance_credit_cents"] == 928
    assert bill["actual_charges_cents"] == 3712
    assert bill["total_due_cents"] == 3712


# ---------------------------------------------------------------------------
# combinatorial_formula / consolidated_bill_round_per_line_then_sum
# ---------------------------------------------------------------------------
def _setup_water_sewer_bill(api, water_reading=5234):
    create_water_schedule(api)
    create_sewer_schedule(api)
    account = open_account(api, account_holder_name="Round Rita")
    wm = add_meter(api, account["id"], "WATER")
    add_meter(api, account["id"], "SEWER")
    add_reading(api, wm["id"], water_reading, "ACTUAL")
    return generate_bill(api, account["id"])


def test_round_per_line_then_sum_yields_4758(api):
    """PRD §2.5: "each per-service line charge is rounded to whole cents **first**, and only
    then are the rounded line charges summed."
    PRD §3.3: "The bill's `pre_discount_total_cents` is the sum of those already-rounded line
    charges — round each line, then sum."

    Design: Difficulty/combinatorial_formula/consolidated_bill_round_per_line_then_sum
    """
    bill = _setup_water_sewer_bill(api)
    assert bill["pre_discount_total_cents"] == 4758
    assert bill["total_due_cents"] == 4758


def test_round_per_line_then_sum_line_charges_rounded_individually(api):
    """PRD §3.3: "Each per-service result is recorded in the bill's `line_charges` array as
    an entry naming the `service_type`, the `consumption_units` billed, and the rounded
    `charge_cents`. The bill's `pre_discount_total_cents` is the sum of those already-rounded
    line charges — round each line, then sum."

    Design: Difficulty/combinatorial_formula/consolidated_bill_round_per_line_then_sum
    """
    bill = _setup_water_sewer_bill(api)
    charges = {line["service_type"]: line["charge_cents"] for line in bill["line_charges"]}
    assert charges["WATER"] == 2649, "water line 2648.71 rounds half up to 2649"
    assert charges["SEWER"] == 2109, "sewer line 2108.5 rounds half up to 2109"


# ---------------------------------------------------------------------------
# boundary_precision_check / water_tier1_boundary_at_6000_gallons
# ---------------------------------------------------------------------------
def test_consumption_exactly_6000_is_tier1_only(api):
    """PRD §3.3: "Under the test water schedule, the first 6,000 gallons are priced at 315
    cents per 1,000 gallons, the next block up to 12,000 gallons (the 6,000 gallons above
    6,000) at 500 cents per 1,000 gallons".

    Design: Difficulty/boundary_precision_check/water_tier1_boundary_at_6000_gallons
    """
    ctx = setup_account_with_water_bill(api, reading_value=6000)
    assert ctx["bill"]["total_due_cents"] == 2890


def test_consumption_6001_spills_one_gallon_into_tier2(api):
    """PRD §3.3: "the next block up to 12,000 gallons (the 6,000 gallons above 6,000) at 500
    cents per 1,000 gallons".
    PRD §2.5: "a value exactly halfway between two integers rounds to the larger magnitude".

    Design: Difficulty/boundary_precision_check/water_tier1_boundary_at_6000_gallons
    """
    ctx = setup_account_with_water_bill(api, reading_value=6001)
    assert ctx["bill"]["total_due_cents"] == 2891


# ---------------------------------------------------------------------------
# dual_variant_calc / bill_estimated_vs_actual_read
# ---------------------------------------------------------------------------
def _setup_estimated_then_actual_bills(api):
    create_water_schedule(api)
    account = open_account(api, account_holder_name="Ada Water")
    meter = add_meter(api, account["id"], "WATER", estimated_monthly_units=6000)
    add_reading(api, meter["id"], 6000, "ESTIMATED", "2026-01-31T00:00:00Z")
    bill1 = generate_bill(api, account["id"], "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z")
    add_reading(api, meter["id"], 15500, "ACTUAL", "2026-02-28T00:00:00Z")
    bill2 = generate_bill(api, account["id"], "2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z")
    return bill1, bill2


def test_estimated_read_variant_bills_the_estimate(api):
    """PRD §3.3: "If the latest reading is `ESTIMATED`, or if the meter has no readings at
    all, the line falls back to the meter's `estimated_monthly_units` and the line is
    flagged estimated; this is the **estimated-read variant**."
    PRD §3.3: "The bill's `read_basis` is `ESTIMATED` if any metered line fell back to its
    estimate and `ACTUAL` only when every metered line used an actual delta."

    Design: Difficulty/dual_variant_calc/bill_estimated_vs_actual_read
    """
    bill1, _ = _setup_estimated_then_actual_bills(api)
    assert bill1["read_basis"] == "ESTIMATED"
    assert bill1["total_due_cents"] == 2890


def test_actual_read_variant_bills_the_delta_and_differs(api):
    """PRD §3.3: "Otherwise the latest reading is `ACTUAL`, and consumption is that latest
    `reading_value` minus the immediately prior reading's value (or minus 0 when there is
    only one reading); this is the **actual-read variant**. The two variants generally yield
    different totals because the estimated variant ignores the dial entirely and bills the
    flat monthly estimate."

    Design: Difficulty/dual_variant_calc/bill_estimated_vs_actual_read
    """
    bill1, bill2 = _setup_estimated_then_actual_bills(api)
    assert bill2["read_basis"] == "ACTUAL"
    assert bill2["total_due_cents"] == 4640
    assert bill1["total_due_cents"] != bill2["total_due_cents"]


# ---------------------------------------------------------------------------
# resource_temporal_overlap / bill_period_overlap_half_open_on_account
# ---------------------------------------------------------------------------
def test_overlapping_bill_period_rejected(api):
    """PRD §3.3: "the half-open interval from `period_start` up to `period_end` must not
    overlap any existing bill on the account. Because the interval is half-open, a new
    period may begin exactly where a prior period ended without conflict, but any true
    overlap is rejected with `ERR_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/bill_period_overlap_half_open_on_account
    """
    ctx = setup_account_with_water_bill(
        api, reading_value=9500, read_date="2026-01-10T00:00:00Z",
        period_start="2026-01-01T00:00:00Z", period_end="2026-02-01T00:00:00Z",
    )
    resp = api.create_bill(
        ctx["account"]["id"],
        {"period_start": "2026-01-15T00:00:00Z", "period_end": "2026-02-15T00:00:00Z"},
        BS,
    )
    validate_error(resp, "ERR_PERIOD_OVERLAP")


def test_adjacent_bill_period_accepted(api):
    """PRD §3.3: "Because the interval is half-open, a new period may begin exactly where a
    prior period ended without conflict, but any true overlap is rejected with
    `ERR_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/bill_period_overlap_half_open_on_account
    """
    ctx = setup_account_with_water_bill(
        api, reading_value=9500, read_date="2026-01-10T00:00:00Z",
        period_start="2026-01-01T00:00:00Z", period_end="2026-02-01T00:00:00Z",
    )
    resp = api.create_bill(
        ctx["account"]["id"],
        {"period_start": "2026-02-01T00:00:00Z", "period_end": "2026-03-01T00:00:00Z"},
        BS,
    )
    validate_success(resp, 201)


# ---------------------------------------------------------------------------
# state_machines / initial_state_new_bill_is_unpaid_current (corner)
# ---------------------------------------------------------------------------
def test_new_bill_starts_unpaid_and_current(api):
    """PRD §3.3: "A newly generated bill starts with `amount_paid_cents` 0, `payment_status`
    `UNPAID`, and `collection_status` `CURRENT`, and generating it recomputes the account's
    balances."

    Design: Corner/state_machines/initial_state_new_bill_is_unpaid_current
    """
    ctx = setup_account_with_water_bill(api, reading_value=9500)
    assert ctx["bill"]["payment_status"] == "UNPAID"
    assert ctx["bill"]["collection_status"] == "CURRENT"
    assert ctx["bill"]["amount_paid_cents"] == 0
