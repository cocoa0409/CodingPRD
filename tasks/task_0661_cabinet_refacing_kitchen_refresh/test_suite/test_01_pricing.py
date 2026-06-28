"""Pricing tests: provisional estimate vs firm quote, the firm-total formula,
add-on rounding, volume-discount boundaries, base lead time, and financing.

Queue A: dual_variant_calc, combinatorial_formula, boundary_precision_check.
Queue B: calculations corner instances.
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
    make_customer_headers,
    fixtures as fx,
)

_SALES = TEST_USERS["sales_rep_headers"]
_SCHED = TEST_USERS["scheduler_headers"]
_ADMIN = TEST_USERS["platform_admin_headers"]


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================

def test_provisional_estimate_uses_blended_per_foot_rate(api):
    """PRD §3.3: "a single blended per-linear-foot rate for the chosen scope is
    multiplied by the measure's `linear_feet`, and the product is rounded half-up
    to whole cents. The blended rate is 12,000 cents per linear foot for `PAINT`,
    28,000 cents per linear foot for `REFACE`, and 45,000 cents per linear foot
    for `REDOOR`."

    Design: Difficulty/dual_variant_calc/quote_provisional_estimate_vs_firm_total_diverge
    """
    cust, proj, meas, quote = fx.setup_draft_quote(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER")
    # REFACE: 28000 * 25 = 700000.
    assert quote["estimate_total_cents"] == 700000, \
        f"expected provisional estimate 700000, got {quote['estimate_total_cents']}"


def test_firm_total_diverges_from_provisional_on_identical_measure(api):
    """PRD §3.4: "Because the firm computation brings in the door term, the finish
    multiplier, the tiered discount, and approved add-ons, it will generally
    diverge from the provisional estimate even on identical measure data."

    Design: Difficulty/dual_variant_calc/quote_provisional_estimate_vs_firm_total_diverge
    """
    cust, proj, meas, quote = fx.setup_draft_quote(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER")
    est = quote["estimate_total_cents"]
    issued = validate_success(api.issue_quote(quote["id"], _SALES))
    # Firm: labor 20000*25=500000 + door 4000*18=72000 = 572000;
    # materials rhu(572000*0.25)=143000; subtotal 715000; discount 0; firm 715000.
    assert est == 700000, f"expected estimate 700000, got {est}"
    assert issued["firm_total_cents"] == 715000, \
        f"expected firm 715000, got {issued['firm_total_cents']}"
    assert est != issued["firm_total_cents"], "estimate and firm must diverge"


def test_change_order_standard_lead_and_price_delta(api):
    """PRD §3.7: "Every positive linear-foot increment adds 2 days per foot, taking
    the larger of `delta_linear_feet` and zero, rounding that foot count up to a
    whole number, and multiplying by 2; a door-only change adds a flat 3 days when
    `delta_door_count` is greater than zero, and 0 otherwise."
    PRD §3.7: "a foot-delta amount is the per-foot labor rate for the quote's scope
    multiplied by `delta_linear_feet`; a door-delta amount is the per-door labor
    rate for the quote's scope multiplied by `delta_door_count`; those two are
    summed into a raw delta; the finish multiplier for the measure's `finish_code`
    is then applied to the raw delta; and `price_delta_cents` is that product
    rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/change_order_lead_days_rush_vs_standard_diverge
    """
    cust, proj, meas, quote, co = fx.setup_approved_quote_with_pending_change_order(
        delta_linear_feet=4, delta_door_count=2, rush=False,
        scope="REFACE", finish_code="WOOD_VENEER")
    accepted = validate_success(
        api.accept_change_order(co["id"], {"expected_quote_version": quote["version"]},
                                make_customer_headers(cust["id"])))
    co_read = validate_success(api.get_change_order(co["id"], _SALES))
    # Standard lead: foot 4*2=8 + door flat 3 = 11. Price: (20000*4 + 4000*2)*1.25 = 110000.
    assert co_read["lead_time_delta_days"] == 11, \
        f"expected lead delta 11, got {co_read['lead_time_delta_days']}"
    assert co_read["price_delta_cents"] == 110000, \
        f"expected price delta 110000, got {co_read['price_delta_cents']}"
    assert accepted["status"] == "ACCEPTED"


def test_change_order_rush_compresses_lead_but_not_price(api):
    """PRD §3.7: "When `rush` is true, the added lead time is the base lead amount
    multiplied by the rush factor of 0.5 and then rounded up to a whole number of
    days, compressing the schedule impact at a rush surcharge; when `rush` is false,
    the added lead time is the base lead amount unchanged."
    PRD §3.7: "Rush affects only the lead time, never the price delta."

    Design: Difficulty/dual_variant_calc/change_order_lead_days_rush_vs_standard_diverge
    """
    cust, proj, meas, quote, co = fx.setup_approved_quote_with_pending_change_order(
        delta_linear_feet=4, delta_door_count=2, rush=True,
        scope="REFACE", finish_code="WOOD_VENEER")
    validate_success(
        api.accept_change_order(co["id"], {"expected_quote_version": quote["version"]},
                                make_customer_headers(cust["id"])))
    co_read = validate_success(api.get_change_order(co["id"], _SALES))
    # Rush lead: base 11 -> ceil(11*0.5) = ceil(5.5) = 6. Price unchanged at 110000.
    assert co_read["lead_time_delta_days"] == 6, \
        f"expected rush lead delta 6, got {co_read['lead_time_delta_days']}"
    assert co_read["price_delta_cents"] == 110000, \
        f"expected price delta 110000 (rush must not change price), got {co_read['price_delta_cents']}"


# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================

def test_firm_total_nonlinear_finish_and_volume_tier(api):
    """PRD §3.4: "Fifth, a materials charge is computed as the pre-finish subtotal
    multiplied by the finish multiplier minus one, rounded half-up to whole cents.
    Sixth, the subtotal is the pre-finish amount plus that materials charge.
    Seventh, a volume-discount percentage is selected from the subtotal tier.
    Eighth, the discount is the subtotal multiplied by that percentage, rounded
    half-up to whole cents. Ninth, `firm_total_cents` is the subtotal minus the
    discount, plus the quote's `addons_total_cents`."

    Design: Difficulty/combinatorial_formula/firm_total_nonlinear_finish_and_tier_interaction
    """
    cust, proj, meas, quote = fx.setup_draft_quote(
        scope="REDOOR", linear_feet=32, door_count=24, finish_code="SOLID_WOOD")
    issued = validate_success(api.issue_quote(quote["id"], _SALES))
    # labor 30000*32=960000 + door 7000*24=168000 = 1128000;
    # materials rhu(1128000*0.40)=451200; subtotal 1579200; 5% tier disc rhu(78960)=78960;
    # firm 1579200-78960 = 1500240.
    assert issued["firm_total_cents"] == 1500240, \
        f"expected firm 1500240, got {issued['firm_total_cents']}"


def test_firm_total_finish_multiplier_changes_discount_tier(api):
    """PRD §3.4: "Fourth, the finish multiplier for the measure's `finish_code` is
    selected. Fifth, a materials charge is computed as the pre-finish subtotal
    multiplied by the finish multiplier minus one, rounded half-up to whole cents."
    PRD §3.4: "it is 5 percent when the subtotal is at least 1,500,000 cents but
    below 3,000,000 cents".

    Design: Difficulty/combinatorial_formula/firm_total_nonlinear_finish_and_tier_interaction
    """
    # Same REDOOR 32lf/24d job but PAINT finish (multiplier 1.00) keeps the subtotal
    # below the 1.5M tier, so no discount applies — the finish multiplier is what
    # pushes SOLID_WOOD over the tier boundary in the companion test.
    cust, proj, meas, quote = fx.setup_draft_quote(
        scope="REDOOR", linear_feet=32, door_count=24, finish_code="PAINT")
    issued = validate_success(api.issue_quote(quote["id"], _SALES))
    # labor 30000*32=960000 + door 7000*24=168000 = 1128000; finish 1.00 -> materials 0;
    # subtotal 1128000 (< 1.5M) -> discount 0; firm 1128000.
    assert issued["firm_total_cents"] == 1128000, \
        f"expected firm 1128000 (PAINT finish, no tier discount), got {issued['firm_total_cents']}"


def test_addons_total_round_per_component_then_sum(api):
    """PRD §3.6: "its extended `price_cents` computed immediately as the
    `unit_price_cents` multiplied by the `quantity`, rounded half-up to whole cents".
    PRD §3.6: "the quote's `addons_total_cents` is the already-rounded sum of the
    per-add-on extended prices".

    Design: Difficulty/combinatorial_formula/addons_total_round_per_component_then_sum
    """
    cust, proj, meas, quote = fx.setup_draft_quote(
        scope="REFACE", linear_feet=12, door_count=6, finish_code="LAMINATE")
    ad1 = validate_success(api.create_addon(
        quote["id"], {"kind": "COUNTERTOP", "unit_price_cents": 6533, "quantity": 10.5}, _SALES),
        expected_status=201)
    ad2 = validate_success(api.create_addon(
        quote["id"], {"kind": "COUNTERTOP", "unit_price_cents": 4567, "quantity": 20.5}, _SALES),
        expected_status=201)
    validate_success(api.approve_addon(ad1["id"], _SALES))
    validate_success(api.approve_addon(ad2["id"], _SALES))
    issued = validate_success(api.issue_quote(quote["id"], _SALES))
    # rhu(6533*10.5)=rhu(68596.5)=68597; rhu(4567*20.5)=rhu(93623.5)=93624; sum 162221.
    assert ad1["price_cents"] == 68597, f"expected ad1 price 68597, got {ad1['price_cents']}"
    assert ad2["price_cents"] == 93624, f"expected ad2 price 93624, got {ad2['price_cents']}"
    assert issued["addons_total_cents"] == 162221, \
        f"expected addons_total 162221 (round-per-component then sum), got {issued['addons_total_cents']}"
    # Firm base: labor 20000*12=240000 + door 4000*6=24000 = 264000;
    # materials rhu(264000*0.10)=26400; subtotal 290400; disc 0; + addons 162221 = 452621.
    assert issued["firm_total_cents"] == 452621, \
        f"expected firm 452621, got {issued['firm_total_cents']}"


def test_single_approved_addon_folds_into_addons_total_and_firm(api):
    """PRD §3.6: "an approved add-on's `price_cents` is folded into the quote's
    `addons_total_cents` the next time the quote is issued."
    PRD §3.4: "Ninth, `firm_total_cents` is the subtotal minus the discount, plus
    the quote's `addons_total_cents`."

    Design: Difficulty/combinatorial_formula/addons_total_round_per_component_then_sum
    """
    cust, proj, meas, quote = fx.setup_draft_quote(
        scope="REFACE", linear_feet=12, door_count=6, finish_code="LAMINATE")
    ad = validate_success(api.create_addon(
        quote["id"], {"kind": "COUNTERTOP", "unit_price_cents": 6533, "quantity": 10.5}, _SALES),
        expected_status=201)
    validate_success(api.approve_addon(ad["id"], _SALES))
    issued = validate_success(api.issue_quote(quote["id"], _SALES))
    # rhu(6533*10.5)=68597; addons_total equals that single rounded extended price.
    assert ad["price_cents"] == 68597, f"expected addon price 68597, got {ad['price_cents']}"
    assert issued["addons_total_cents"] == 68597, \
        f"expected addons_total 68597, got {issued['addons_total_cents']}"
    # base subtotal 290400 (no discount) + 68597 = 358997.
    assert issued["firm_total_cents"] == 358997, \
        f"expected firm 358997, got {issued['firm_total_cents']}"


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================

def test_volume_discount_engages_at_exactly_1_5m_subtotal(api):
    """PRD §3.4: "The volume discount is zero when the subtotal is below 1,500,000
    cents; it is 5 percent when the subtotal is at least 1,500,000 cents but below
    3,000,000 cents; and it is 10 percent when the subtotal is at least 3,000,000
    cents."

    Design: Difficulty/boundary_precision_check/volume_discount_tier_at_exactly_1_5m_subtotal
    """
    cust, proj, meas, quote = fx.setup_draft_quote(
        scope="PAINT", linear_feet=160, door_count=40, finish_code="PAINT")
    issued = validate_success(api.issue_quote(quote["id"], _SALES))
    # labor 9000*160=1440000 + door 1500*40=60000 = 1500000; finish 1.00 -> materials 0;
    # subtotal exactly 1500000 -> 5% tier; disc rhu(75000)=75000; firm 1425000.
    assert issued["firm_total_cents"] == 1425000, \
        f"expected firm 1425000 at >=1.5M boundary, got {issued['firm_total_cents']}"


def test_volume_discount_absent_just_below_1_5m_subtotal(api):
    """PRD §3.4: "The volume discount is zero when the subtotal is below 1,500,000
    cents; it is 5 percent when the subtotal is at least 1,500,000 cents but below
    3,000,000 cents".

    Design: Difficulty/boundary_precision_check/volume_discount_tier_at_exactly_1_5m_subtotal
    """
    cust, proj, meas, quote = fx.setup_draft_quote(
        scope="PAINT", linear_feet=160, door_count=39, finish_code="PAINT")
    issued = validate_success(api.issue_quote(quote["id"], _SALES))
    # labor 9000*160=1440000 + door 1500*39=58500 = 1498500 (< 1.5M); disc 0; firm 1498500.
    assert issued["firm_total_cents"] == 1498500, \
        f"expected firm 1498500 just below boundary (no discount), got {issued['firm_total_cents']}"


def test_empty_approved_addons_total_is_zero_on_issue(api):
    """PRD §3.5: "the quote's `addons_total_cents` is frozen at the sum of the
    `APPROVED` add-ons currently attached to it".
    PRD §3.6: "an approved add-on's `price_cents` is folded into the quote's
    `addons_total_cents` the next time the quote is issued."

    Design: Difficulty/boundary_precision_check/empty_addons_total_is_zero_on_issue
    """
    cust, proj, meas, quote = fx.setup_draft_quote(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER")
    ad = validate_success(api.create_addon(
        quote["id"], {"kind": "HARDWARE", "unit_price_cents": 850, "quantity": 24}, _SALES),
        expected_status=201)
    validate_success(api.remove_addon(ad["id"], _SALES))
    issued = validate_success(api.issue_quote(quote["id"], _SALES))
    # No APPROVED add-on -> addons_total_cents 0; firm equals discounted subtotal 715000.
    assert issued["addons_total_cents"] == 0, \
        f"expected addons_total 0 with no APPROVED add-ons, got {issued['addons_total_cents']}"
    assert issued["firm_total_cents"] == 715000, \
        f"expected firm 715000, got {issued['firm_total_cents']}"


def test_proposed_but_unapproved_addon_excluded_from_total(api):
    """PRD §3.6: "an approved add-on's `price_cents` is folded into the quote's
    `addons_total_cents` the next time the quote is issued."
    PRD §3.5: "the quote's `addons_total_cents` is frozen at the sum of the
    `APPROVED` add-ons currently attached to it".

    Design: Difficulty/boundary_precision_check/empty_addons_total_is_zero_on_issue
    """
    cust, proj, meas, quote = fx.setup_draft_quote(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER")
    # Add-on is left PROPOSED (never approved): it must not enter the firm total.
    validate_success(api.create_addon(
        quote["id"], {"kind": "HARDWARE", "unit_price_cents": 850, "quantity": 24}, _SALES),
        expected_status=201)
    issued = validate_success(api.issue_quote(quote["id"], _SALES))
    assert issued["addons_total_cents"] == 0, \
        f"expected addons_total 0 with only a PROPOSED add-on, got {issued['addons_total_cents']}"
    assert issued["firm_total_cents"] == 715000, \
        f"expected firm 715000, got {issued['firm_total_cents']}"


# ===========================================================================
# Queue B — calculations corner instances
# ===========================================================================

def test_base_lead_time_volume_step_at_30_feet(api):
    """PRD §3.8: "The base is keyed on the measure's `finish_code`: 7 days for
    `PAINT`, 14 days for `LAMINATE`, 21 days for `THERMOFOIL`, 28 days for
    `WOOD_VENEER`, and 42 days for `SOLID_WOOD`. A scope surcharge is added on top:
    0 days for `PAINT`, 5 days for `REFACE`, and 10 days for `REDOOR`. Finally, a
    volume step of 7 days is added when the measure's `linear_feet` is at least 30
    (large jobs ship in two batches), and 0 otherwise".

    Design: Corner/calculations/base_lead_time_volume_step_at_30_feet_boundary
    """
    fx.reset_clock()
    cust, proj, meas, quote = fx.setup_approved_quote(
        scope="REFACE", linear_feet=30, door_count=18, finish_code="WOOD_VENEER")
    mo = validate_success(
        api.create_material_order(proj["id"], {"quote_id": quote["id"]}, _SCHED),
        expected_status=201)
    # WOOD_VENEER 28 + REFACE 5 + volume 7 (>=30) = 40.
    assert mo["base_lead_time_days"] == 40, \
        f"expected base_lead_time_days 40 at 30ft, got {mo['base_lead_time_days']}"
    # ready_at = 2026-04-01 + 40 days = 2026-05-11.
    assert mo["ready_at"].startswith("2026-05-11"), \
        f"expected ready_at 2026-05-11, got {mo['ready_at']}"


def test_provisional_estimate_excludes_door_count_and_finish(api):
    """PRD §3.3: "This **provisional estimate** is forward-looking and intentionally
    ignores both `door_count` and the finish multiplier — those enter only the firm
    quote. It is computed from the linked completed measure alone: a single blended
    per-linear-foot rate for the chosen scope is multiplied by the measure's
    `linear_feet`".

    Design: Corner/calculations/provisional_estimate_excludes_doors_and_finish
    """
    cust, proj, meas = fx.setup_project_with_completed_measure(
        linear_feet=32, door_count=24, finish_code="SOLID_WOOD", door_style="RAISED")
    quote = validate_success(
        api.create_quote(proj["id"], {"measure_id": meas["id"], "scope": "REDOOR"}, _SALES),
        expected_status=201)
    # REDOOR 45000 * 32 = 1440000, regardless of door_count=24 or SOLID_WOOD.
    assert quote["estimate_total_cents"] == 1440000, \
        f"expected estimate 1440000 (doors/finish excluded), got {quote['estimate_total_cents']}"


def test_single_addon_price_cents_rounds_half_up(api):
    """PRD §3.6: "its extended `price_cents` computed immediately as the
    `unit_price_cents` multiplied by the `quantity`, rounded half-up to whole cents;
    this value is always zero or greater."

    Design: Corner/calculations/addon_price_cents_round_half_up
    """
    cust, proj, meas, quote = fx.setup_draft_quote(
        scope="REFACE", linear_feet=25, door_count=18, finish_code="WOOD_VENEER")
    ad = validate_success(api.create_addon(
        quote["id"], {"kind": "COUNTERTOP", "unit_price_cents": 6533, "quantity": 30.5}, _SALES),
        expected_status=201)
    # rhu(6533 * 30.5) = rhu(199256.5) = 199257.
    assert ad["price_cents"] == 199257, \
        f"expected price_cents 199257, got {ad['price_cents']}"


def test_financing_monthly_payment_and_dti(api):
    """PRD §3.12: "the standard amortization factor is computed — the monthly rate
    multiplied by one plus the monthly rate raised to the power of the term, divided
    by the quantity one plus the monthly rate raised to the power of the term minus
    one — and `monthly_payment_cents` is the `amount_cents` multiplied by that
    factor, rounded half-up to whole cents".
    PRD §3.12: "The `dti_ratio` is the `monthly_payment_cents` multiplied by twelve
    and divided by the applicant's `annual_income_cents`, rounded to four decimal
    places (round-half-up)".

    Design: Corner/calculations/financing_monthly_payment_amortization_correct
    """
    cust, proj, fa = fx.setup_submitted_financing(
        annual_income_cents=3_800_000, amount_cents=2_000_000, term_months=36)
    # term 36 -> APR 0.0799; monthly_payment 62664; dti (62664*12)/3800000 = 0.1979.
    assert fa["monthly_payment_cents"] == 62664, \
        f"expected monthly_payment_cents 62664, got {fa['monthly_payment_cents']}"
    assert fa["dti_ratio"] == 0.1979, \
        f"expected dti_ratio 0.1979, got {fa['dti_ratio']}"


def test_dti_just_over_threshold_blocks_approval(api):
    """PRD §3.12: "A `PlatformAdmin` approves a submitted application, moving it
    `SUBMITTED → APPROVED`, but only when the `dti_ratio` is at most 0.20; an
    approval attempt where the `dti_ratio` exceeds 0.20 is rejected with
    `ERR_DTI_EXCEEDED` (HTTP 422)."

    Design: Corner/calculations/dti_boundary_decline_just_over_threshold
    """
    from test_helpers import validate_error, ApiErrorId
    cust, proj, fa = fx.setup_submitted_financing(
        annual_income_cents=3_700_000, amount_cents=2_000_000, term_months=36)
    # Same payment 62664; dti (62664*12)/3700000 = 0.2032 (> 0.20).
    assert fa["dti_ratio"] == 0.2032, \
        f"expected dti_ratio 0.2032, got {fa['dti_ratio']}"
    resp = api.approve_financing_application(fa["id"], _ADMIN)
    validate_error(resp, ApiErrorId.ERR_DTI_EXCEEDED.value)
