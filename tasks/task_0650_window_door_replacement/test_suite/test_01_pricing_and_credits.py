"""Pricing engine: per-opening list price, tiered discount, 25C rebate,
financing amortization, manufacturing lead time, referral reward.

Each test creates its own entities from scratch via test_helpers fixtures.
"""
from test_helpers import (
    validate_success,
    get_success_data,
    factories as F,
    fixtures as FX,
    TEST_USERS,
    make_homeowner_headers,
)

SALES = TEST_USERS["sales_consultant_headers"]
OPS = TEST_USERS["operations_coordinator_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ---------------------------------------------------------------------------
# Quote estimate: round-then-sum and lead-time max-select
# ---------------------------------------------------------------------------

def test_quote_estimate_round_then_sum_single_casement(api):
    """PRD §2.7: "per-opening prices are each rounded once at the moment they
    are computed, and downstream totals sum those already-rounded values rather
    than re-rounding a running sum."
    PRD §3.3: "The `openings_subtotal_cents` is the sum of `unit_price_cents`
    over every opening on the quote's measured consultation — a sum of values
    that were each already rounded once at opening time, never a re-rounded
    running total."
    PRD §3.3: "An install fee is a flat 35,000 cents plus 1,500 cents for each
    opening, using the consultation's `total_opening_count`."

    Design: Difficulty/combinatorial_formula/quote_estimate_round_then_sum_order_pinned_mode_b
    """
    base = FX.setup_draft_quote(api, openings=[
        {"product_type": "CASEMENT", "width_in": 30, "height_in": 40, "glass_package": "LOWE_DUAL"},
    ])
    resp = api.send_quote(base["project"]["id"], base["quote"]["id"], SALES)
    quote = validate_success(resp, 200)
    assert quote["openings_subtotal_cents"] == 47500, quote["openings_subtotal_cents"]
    assert quote["discount_tier"] == "NONE", quote["discount_tier"]
    # subtotal 47500, discount 0, install fee 35000 + 1500*1 = 36500 -> 84000
    assert quote["estimate_total_cents"] == 84000, quote["estimate_total_cents"]


def test_quote_estimate_subtotal_is_sum_of_already_rounded_prices(api):
    """PRD §3.3: "The `openings_subtotal_cents` is the sum of `unit_price_cents`
    over every opening on the quote's measured consultation — a sum of values
    that were each already rounded once at opening time, never a re-rounded
    running total."
    PRD §2.7: "per-opening prices are each rounded once at the moment they are
    computed, and downstream totals sum those already-rounded values rather than
    re-rounding a running sum."

    Design: Difficulty/combinatorial_formula/quote_estimate_round_then_sum_order_pinned_mode_b
    """
    # Three PICTURE 80x100 STANDARD openings: each area 8000/144, raw 200000.0,
    # unit_price 200000; subtotal = 200000*3 = 600000, tier NONE, install
    # 35000 + 1500*3 = 39500 -> estimate 639500.
    base = FX.setup_draft_quote(api, openings=[
        {"product_type": "PICTURE", "width_in": 80, "height_in": 100, "glass_package": "STANDARD"},
        {"product_type": "PICTURE", "width_in": 80, "height_in": 100, "glass_package": "STANDARD"},
        {"product_type": "PICTURE", "width_in": 80, "height_in": 100, "glass_package": "STANDARD"},
    ])
    quote = validate_success(api.send_quote(base["project"]["id"], base["quote"]["id"], SALES), 200)
    assert quote["openings_subtotal_cents"] == 600000, quote["openings_subtotal_cents"]
    assert quote["discount_tier"] == "NONE", quote["discount_tier"]
    assert quote["estimate_total_cents"] == 639500, quote["estimate_total_cents"]


def test_lead_time_max_select_plus_triple_surcharge(api):
    """PRD §3.6: "The lead time keys off the slowest product among the accepted
    quote's openings."
    PRD §3.6: "the system takes the maximum of these over all openings on the
    consultation."
    PRD §3.6: "If any opening on the order carries the `LOWE_TRIPLE` glass
    package, a rush surcharge of 14 logical days is added to that maximum;
    otherwise no surcharge applies."

    Design: Difficulty/combinatorial_formula/lead_time_max_select_plus_triple_surcharge_mode_a
    """
    # SLIDING_PATIO_DOOR (49) + ENTRY_DOOR (42) + CASEMENT (35); all LOWE_TRIPLE.
    # max base = 49, + 14 surcharge = 63.
    openings = [
        {"product_type": "SLIDING_PATIO_DOOR", "width_in": 72, "height_in": 80, "glass_package": "LOWE_TRIPLE"},
        {"product_type": "ENTRY_DOOR", "width_in": 36, "height_in": 96, "glass_package": "LOWE_TRIPLE"},
    ] + [{"product_type": "CASEMENT", "width_in": 48, "height_in": 72, "glass_package": "LOWE_TRIPLE"} for _ in range(10)]
    base = FX.setup_accepted_quote(api, openings=openings)
    mo = base["manufacture"]
    assert mo is not None, "ManufactureOrder should be auto-created on accept"
    assert mo["lead_time_days"] == 63, mo["lead_time_days"]


def test_lead_time_max_base_no_surcharge_when_no_triple(api):
    """PRD §3.6: "the system takes the maximum of these over all openings on the
    consultation."
    PRD §3.6: "If any opening on the order carries the `LOWE_TRIPLE` glass
    package, a rush surcharge of 14 logical days is added to that maximum;
    otherwise no surcharge applies."

    Design: Difficulty/combinatorial_formula/lead_time_max_select_plus_triple_surcharge_mode_a
    """
    # CASEMENT (35) + PICTURE (21), no LOWE_TRIPLE -> max 35, no surcharge.
    base = FX.setup_accepted_quote(api, openings=[
        {"product_type": "CASEMENT", "width_in": 30, "height_in": 40, "glass_package": "LOWE_DUAL"},
        {"product_type": "PICTURE", "width_in": 40, "height_in": 40, "glass_package": "STANDARD"},
    ])
    mo = base["manufacture"]
    assert mo is not None
    assert mo["lead_time_days"] == 35, mo["lead_time_days"]


# ---------------------------------------------------------------------------
# 25C rebate and financing payment variants
# ---------------------------------------------------------------------------

def test_provisional_rebate_computed_regardless_of_agi_band(api):
    """PRD §3.3: "The window credit is 30 percent of the summed `unit_price_cents`
    of qualified windows, rounded half-up to whole cents, then capped so it
    cannot exceed 60,000 cents (the $600 aggregate annual exterior-window cap)."
    PRD §3.3: "The provisional figure, stored as `provisional_rebate_cents`,
    sums the capped window credit and the capped door credit over all
    energy-qualified openings present at send time, regardless of the
    homeowner's AGI band."

    Note: the final-confirmed credit reported at accept is NOT asserted — the
    PRD names no response field for it nor a HIGH phase-out rule, so it is not
    uniquely derivable from PRD prose.

    Design: Difficulty/dual_variant_calc/rebate_25c_provisional_vs_final_high_agi_zeroed
    """
    # HIGH-agi homeowner; one CASEMENT 30x40 LOWE_DUAL (window, energy-qualified,
    # unit_price 47500). Provisional window credit = round(47500*0.30) = 14250.
    base = FX.setup_sent_quote(api, openings=[
        {"product_type": "CASEMENT", "width_in": 30, "height_in": 40, "glass_package": "LOWE_DUAL"},
    ], homeowner_overrides={"agi_band": "HIGH"})
    quote = base["quote"]
    open_id = base["opening_ids"][0]
    opening = validate_success(api.get_opening(open_id, SALES), 200)
    assert opening["unit_price_cents"] == 47500, opening["unit_price_cents"]
    assert quote["provisional_rebate_cents"] == 14250, quote["provisional_rebate_cents"]


def test_accept_high_agi_quote_succeeds(api):
    """PRD §3.4: "A successful acceptance increments the quote's `version` by
    one, moves the quote to `ACCEPTED`, and then fans out a four-hop cascade."

    Design: Difficulty/dual_variant_calc/rebate_25c_provisional_vs_final_high_agi_zeroed
    """
    base = FX.setup_accepted_quote(api, openings=[
        {"product_type": "CASEMENT", "width_in": 30, "height_in": 40, "glass_package": "LOWE_DUAL"},
    ], homeowner_overrides={"agi_band": "HIGH"})
    assert base["quote"]["status"] == "ACCEPTED", base["quote"]["status"]


def test_financing_zero_promo_ceil_division(api):
    """PRD §3.5: "For the `STANDARD` band they are 0 at 12 months, 499 at 24,
    899 at 36, and 1,299 at 60."
    PRD §3.5: "When the looked-up APR is 0 basis points — a promotional
    zero-interest plan — the monthly payment is the financed principal
    `requested_amount_cents` divided by the number of months and rounded up to
    the next whole cent, so that the payments sum to at least the principal."

    Design: Difficulty/dual_variant_calc/financing_monthly_payment_zero_promo_vs_interest_bearing
    """
    # STANDARD homeowner, quote estimate >= 1,000,000 (3x PICTURE 80x100 STANDARD
    # -> subtotal 600000; need bigger). Use larger openings: PICTURE 100x100
    # area 10000/144 -> raw 250000.0 each; 5 of them -> subtotal 1,250,000.
    base = FX.setup_sent_quote(api, openings=[
        {"product_type": "PICTURE", "width_in": 100, "height_in": 100, "glass_package": "STANDARD"} for _ in range(5)
    ])
    pid, qid, ho_id = base["project"]["id"], base["quote"]["id"], base["homeowner"]["id"]
    fin = get_success_data(api.create_financing(pid, qid, F.create_financing_payload(qid, requested_amount_cents=1_000_000, term_months=12), make_homeowner_headers(ho_id)))
    decided = validate_success(api.decide_financing(pid, qid, fin["id"], F.decide_financing_payload("APPROVE"), OPS), 200)
    assert decided["approved_apr_bps"] == 0, decided["approved_apr_bps"]
    assert decided["monthly_payment_cents"] == 83334, decided["monthly_payment_cents"]


def test_financing_interest_bearing_amortization(api):
    """PRD §3.5: "For the `STANDARD` band they are 0 at 12 months, 499 at 24,
    899 at 36, and 1,299 at 60."
    PRD §3.5: "the monthly payment is the principal multiplied by that factor,
    rounded half-up to whole cents exactly once at the end."

    Design: Difficulty/dual_variant_calc/financing_monthly_payment_zero_promo_vs_interest_bearing
    """
    base = FX.setup_sent_quote(api, openings=[
        {"product_type": "PICTURE", "width_in": 100, "height_in": 100, "glass_package": "STANDARD"} for _ in range(5)
    ])
    pid, qid, ho_id = base["project"]["id"], base["quote"]["id"], base["homeowner"]["id"]
    fin = get_success_data(api.create_financing(pid, qid, F.create_financing_payload(qid, requested_amount_cents=1_000_000, term_months=24), make_homeowner_headers(ho_id)))
    decided = validate_success(api.decide_financing(pid, qid, fin["id"], F.decide_financing_payload("APPROVE"), OPS), 200)
    assert decided["approved_apr_bps"] == 499, decided["approved_apr_bps"]
    assert decided["monthly_payment_cents"] == 43867, decided["monthly_payment_cents"]


# ---------------------------------------------------------------------------
# Discount-tier threshold boundary
# ---------------------------------------------------------------------------

def test_discount_tier_at_exactly_2000000_is_tier1(api):
    """PRD §3.3: "a subtotal from 2,000,000 cents up to but not including
    4,000,000 cents earns `TIER1` at 5 percent."
    PRD §3.3: "The discount in cents is the subtotal multiplied by the tier's
    percentage, rounded half-up exactly once."

    Design: Difficulty/boundary_precision_check/discount_tier_at_exactly_2000000_is_tier1_ge
    """
    # 10 x PICTURE 80x100 STANDARD: each unit_price 200000; subtotal exactly
    # 2,000,000 -> TIER1 (>=). discount = round(2000000*0.05)=100000.
    # install fee = 35000 + 1500*10 = 50000. estimate = 2000000-100000+50000 = 1950000.
    base = FX.setup_draft_quote(api, openings=[
        {"product_type": "PICTURE", "width_in": 80, "height_in": 100, "glass_package": "STANDARD"} for _ in range(10)
    ])
    quote = validate_success(api.send_quote(base["project"]["id"], base["quote"]["id"], SALES), 200)
    assert quote["openings_subtotal_cents"] == 2000000, quote["openings_subtotal_cents"]
    assert quote["discount_tier"] == "TIER1", quote["discount_tier"]
    assert quote["estimate_total_cents"] == 1950000, quote["estimate_total_cents"]


def test_discount_tier_below_threshold_is_none(api):
    """PRD §3.3: "a subtotal below 2,000,000 cents earns `NONE` at 0 percent."

    Design: Difficulty/boundary_precision_check/discount_tier_at_exactly_2000000_is_tier1_ge
    """
    # 9 x PICTURE 80x100 STANDARD: subtotal 1,800,000 < 2,000,000 -> NONE.
    base = FX.setup_draft_quote(api, openings=[
        {"product_type": "PICTURE", "width_in": 80, "height_in": 100, "glass_package": "STANDARD"} for _ in range(9)
    ])
    quote = validate_success(api.send_quote(base["project"]["id"], base["quote"]["id"], SALES), 200)
    assert quote["openings_subtotal_cents"] == 1800000, quote["openings_subtotal_cents"]
    assert quote["discount_tier"] == "NONE", quote["discount_tier"]


# ---------------------------------------------------------------------------
# Rebate caps and service charge
# ---------------------------------------------------------------------------

def test_rebate_door_credit_capped_at_door_total_cap(api):
    """PRD §3.3: "The door credit is 30 percent of the summed `unit_price_cents`
    of qualified doors, rounded half-up to whole cents, then capped so it cannot
    exceed 50,000 cents (the $500 total-doors cap)."
    PRD §3.3: "The window credit is 30 percent of the summed `unit_price_cents`
    of qualified windows, rounded half-up to whole cents, then capped so it
    cannot exceed 60,000 cents (the $600 aggregate annual exterior-window cap)."

    Design: Corner/calculations/rebate_door_credit_capped_at_door_total_cap
    """
    openings = [
        {"product_type": "SLIDING_PATIO_DOOR", "width_in": 72, "height_in": 80, "glass_package": "LOWE_TRIPLE"},
        {"product_type": "ENTRY_DOOR", "width_in": 36, "height_in": 96, "glass_package": "LOWE_TRIPLE"},
    ] + [{"product_type": "CASEMENT", "width_in": 48, "height_in": 72, "glass_package": "LOWE_TRIPLE"} for _ in range(10)]
    base = FX.setup_draft_quote(api, openings=openings)
    quote = validate_success(api.send_quote(base["project"]["id"], base["quote"]["id"], SALES), 200)
    assert quote["openings_subtotal_cents"] == 2051200, quote["openings_subtotal_cents"]
    assert quote["discount_tier"] == "TIER1", quote["discount_tier"]
    assert quote["estimate_total_cents"] == 2001640, quote["estimate_total_cents"]
    assert quote["provisional_rebate_cents"] == 110000, quote["provisional_rebate_cents"]


def test_service_charge_billable_in_warranty_window(api):
    """PRD §3.9: "A `BILLABLE` ticket carries a base trip charge of 9,500 cents;
    if it is resolved out of warranty ... an additional 5,000-cent surcharge is
    added, making the charge 14,500 cents, otherwise the charge is just the
    9,500-cent base."

    Design: Corner/calculations/service_charge_billable_in_warranty_base_trip
    """
    base = FX.setup_dispatched_ticket(api, category="BILLABLE")
    resolved = validate_success(
        api.resolve_service_ticket(base["project"]["id"], base["ticket"]["id"], TEST_USERS["service_tech_headers"]),
        200,
    )
    assert resolved["charge_cents"] == 9500, resolved["charge_cents"]
    assert resolved["status"] == "RESOLVED", resolved["status"]
