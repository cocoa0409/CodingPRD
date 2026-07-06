"""Quote pricing engine: tiered rates, premium-color surcharge, downspout
add-ons, subtotal-keyed discount caps, provisional-vs-final divergence, and the
tier boundary — plus the color/discount field constraints.
"""
from test_helpers import (
    ApiErrorId,
    create_appointment,
    create_lead,
    create_product,
    create_sales_rep,
    get_lead_version,
    present_quote,
    setup_draft_quote,
    validate_error,
    validate_success,
)


def _fresh_quote_context():
    """Product + rep + lead + a booked appointment, with no quote yet."""
    product = create_product()
    rep = create_sales_rep()
    lead = create_lead(rep["id"])
    appt = create_appointment(lead["id"], rep["id"])
    return product, rep, lead, appt


# ---------------------------------------------------------- dual-variant total
def test_quote_provisional_total_priced_from_estimate(api):
    """PRD §3.4: "The `subtotal_cents` is the sum of those three rounded lines:
    gutter line plus color line plus downspout line."
    PRD §3.4: "The `discount_cents` is the subtotal multiplied by the effective
    fraction, rounded half up to whole cents. Finally, `total_cents` is
    `subtotal_cents` minus `discount_cents`."

    Design: Difficulty/dual_variant_calc/quote_provisional_vs_final_total
    """
    scenario = setup_draft_quote(
        estimated_linear_feet=180, color="COPPER", measured_linear_feet=210,
        downspout_count=2, discount_pct=0.10, appt_via_confirmed=True,
    )
    quote = scenario["quote"]
    assert quote["status"] == "DRAFT"
    assert quote["subtotal_cents"] == 654000
    assert quote["discount_cents"] == 65400
    assert quote["total_cents"] == 588600


def test_quote_present_reprices_final_from_measured_feet(api):
    """PRD §3.5: "On presentation, the appointment's `measured_linear_feet` is
    copied onto the quote's own `measured_linear_feet`, the quote's `linear_feet`
    is reset to that measured value, and the subtotal, discount, and total are
    recomputed from the measured footage using the exact same pricing and
    discount procedure of Section 3.4 — only now the effective footage is the
    measured footage rather than the estimate, so the final total may differ from
    the provisional one for the identical product, color, and downspout count."

    Design: Difficulty/dual_variant_calc/quote_provisional_vs_final_total
    """
    scenario = setup_draft_quote(
        estimated_linear_feet=180, color="COPPER", measured_linear_feet=210,
        downspout_count=2, discount_pct=0.10, appt_via_confirmed=True,
    )
    provisional_total = scenario["quote"]["total_cents"]
    presented = present_quote(scenario["quote"]["id"])
    assert presented["status"] == "PRESENTED"
    assert presented["measured_linear_feet"] == 210
    assert presented["total_cents"] == 654750
    assert presented["total_cents"] != provisional_total, \
        "final total must diverge from the provisional total"


# ---------------------------------------------- combinatorial multifactor price
def test_quote_multifactor_subtotal_stacks_tier_color_downspout(api):
    """PRD §3.4: "The **tier rate** is the product's `base_rate_cents_per_foot`
    multiplied by that tier multiplier, kept exact and not rounded. The **gutter
    line** is the footage multiplied by the tier rate, rounded half up to whole
    cents. The **color line** is the footage multiplied by the product's
    `color_surcharge_cents_per_foot`, rounded half up to whole cents, but only
    when the chosen color is one of the product's `premium_colors`; otherwise the
    color line is 0. The **downspout line** is `downspout_count` multiplied by a
    fixed 12,000 cents (that is, $120) per drainage unit."

    Design: Difficulty/combinatorial_formula/quote_tiered_rate_multifactor_mode_a
    """
    scenario = setup_draft_quote(
        estimated_linear_feet=400, color="COPPER", downspout_count=1,
        discount_pct=0.05, complete_appt=False,
    )
    # gutter 1080000 = round(400 * 2700 [T3]) + color 200000 = round(400*500)
    # + downspout 12000
    assert scenario["quote"]["subtotal_cents"] == 1292000


def test_quote_multifactor_discount_and_total(api):
    """PRD §3.4: "The **effective discount fraction** is the smaller of the
    requested `discount_pct` and that cap. The `discount_cents` is the subtotal
    multiplied by the effective fraction, rounded half up to whole cents.
    Finally, `total_cents` is `subtotal_cents` minus `discount_cents`."

    Design: Difficulty/combinatorial_formula/quote_tiered_rate_multifactor_mode_a
    """
    scenario = setup_draft_quote(
        estimated_linear_feet=400, color="COPPER", downspout_count=1,
        discount_pct=0.05, complete_appt=False,
    )
    quote = scenario["quote"]
    # effective_pct = min(0.05, cap 0.20) = 0.05
    assert quote["discount_cents"] == 64600
    assert quote["total_cents"] == 1227400


# ------------------------------------------- discount cap keyed on the subtotal
def test_discount_cap_subtotal_produces_expected_subtotal(api):
    """PRD §3.4: "it is 1.00 when the footage is below 200 linear feet, 0.95 when
    the footage is at least 200 but below 400 linear feet, and 0.90 when the
    footage is 400 linear feet or more."
    PRD §3.4: "The `subtotal_cents` is the sum of those three rounded lines:
    gutter line plus color line plus downspout line."

    Design: Difficulty/combinatorial_formula/discount_cap_evaluation_order_mode_c
    """
    scenario = setup_draft_quote(
        estimated_linear_feet=350, color="COPPER", downspout_count=0,
        discount_pct=0.20, complete_appt=False,
    )
    # gutter 997500 = round(350 * 2850 [T2]) + color 175000 = round(350 * 500)
    assert scenario["quote"]["subtotal_cents"] == 1172500


def test_discount_cap_keyed_on_subtotal_not_post_discount_total(api):
    """PRD §3.4: "The discount is resolved against the subtotal, not against the
    final total, to avoid a circular dependency."
    PRD §3.4: "the cap is 0.10 when the subtotal is below 500,000 cents ($5,000),
    0.15 when the subtotal is at least 500,000 but below 1,000,000 cents
    ($10,000), and 0.20 when the subtotal is 1,000,000 cents or more."

    Design: Difficulty/combinatorial_formula/discount_cap_evaluation_order_mode_c
    """
    scenario = setup_draft_quote(
        estimated_linear_feet=350, color="COPPER", downspout_count=0,
        discount_pct=0.20, complete_appt=False,
    )
    quote = scenario["quote"]
    # cap keyed on subtotal 1172500 >= 1,000,000 -> 0.20 -> discount 234500.
    assert quote["discount_cents"] == 234500
    assert quote["total_cents"] == 938000


# ---------------------------------------------------------- tier boundary at 200
def test_quote_tier_boundary_below_200_stays_tier_one(api):
    """PRD §3.4: "it is 1.00 when the footage is below 200 linear feet, 0.95 when
    the footage is at least 200 but below 400 linear feet, and 0.90 when the
    footage is 400 linear feet or more."

    Design: Difficulty/boundary_precision_check/quote_tier_boundary_200ft
    """
    scenario = setup_draft_quote(
        estimated_linear_feet=199, color="COPPER", downspout_count=2,
        discount_pct=0.10, complete_appt=False,
    )
    quote = scenario["quote"]
    # 199 < 200 -> tier T1 rate 3000: gutter 597000 + color 99500 + downspout 24000
    assert quote["subtotal_cents"] == 720500
    assert quote["total_cents"] == 648450


def test_quote_tier_boundary_at_200_crosses_to_tier_two(api):
    """PRD §3.4: "it is 1.00 when the footage is below 200 linear feet, 0.95 when
    the footage is at least 200 but below 400 linear feet, and 0.90 when the
    footage is 400 linear feet or more."

    Design: Difficulty/boundary_precision_check/quote_tier_boundary_200ft
    """
    scenario = setup_draft_quote(
        estimated_linear_feet=200, color="COPPER", downspout_count=2,
        discount_pct=0.10, complete_appt=False,
    )
    quote = scenario["quote"]
    # 200 >= 200 -> tier T2 rate 2850: gutter 570000 + color 100000 + downspout 24000
    assert quote["subtotal_cents"] == 694000
    assert quote["total_cents"] == 624600


# ----------------------------------------------------------- corner: defaults
def test_quote_downspout_count_defaults_zero(api, admin_headers):
    """PRD §3.4: "Optional inputs are `downspout_count`, the number of drainage
    add-on units (default 0), and `discount_pct`, a requested discount as a
    fraction between 0 and 1 (default 0)."

    Design: Corner/entities/quote_downspout_count_defaults_zero
    """
    product, rep, lead, appt = _fresh_quote_context()
    lv = get_lead_version(lead["id"])
    # Omit downspout_count entirely; default 0 means no downspout add-on.
    payload = {
        "lead_id": lead["id"], "appointment_id": appt["id"], "sales_rep_id": rep["id"],
        "product_id": product["id"], "color": "WHITE", "estimated_linear_feet": 100,
        "discount_pct": 0, "expected_lead_version": lv,
    }
    data = validate_success(api.create_quote(payload, admin_headers), expected_status=201)
    assert data["downspout_count"] == 0
    # feet 100 T1 rate 3000, no color, no downspout -> 300000
    assert data["subtotal_cents"] == 300000


def test_standard_color_contributes_no_surcharge(api):
    """PRD §3.4: "The **color line** is the footage multiplied by the product's
    `color_surcharge_cents_per_foot`, rounded half up to whole cents, but only
    when the chosen color is one of the product's `premium_colors`; otherwise the
    color line is 0."

    Design: Corner/calculations/standard_color_no_surcharge
    """
    scenario = setup_draft_quote(
        estimated_linear_feet=100, color="WHITE", downspout_count=0,
        discount_pct=0, complete_appt=False,
    )
    quote = scenario["quote"]
    assert quote["subtotal_cents"] == 300000
    assert quote["total_cents"] == 300000


def test_quote_color_not_available_returns_error(api, admin_headers):
    """PRD §3.4: "The chosen color must be one of the product's
    `available_colors`, else `ERR_COLOR_UNAVAILABLE`; the requested discount must
    lie within the inclusive range 0 to 1, else `ERR_INVALID_DISCOUNT`; and the
    estimated footage must be greater than 0, else `ERR_INVALID_MEASUREMENT`."

    Design: Corner/validations/color_unavailable_returns_error
    """
    product, rep, lead, appt = _fresh_quote_context()
    lv = get_lead_version(lead["id"])
    payload = {
        "lead_id": lead["id"], "appointment_id": appt["id"], "sales_rep_id": rep["id"],
        "product_id": product["id"], "color": "GREEN", "estimated_linear_feet": 100,
        "downspout_count": 0, "discount_pct": 0, "expected_lead_version": lv,
    }
    validate_error(api.create_quote(payload, admin_headers), ApiErrorId.ERR_COLOR_UNAVAILABLE)


def test_quote_discount_out_of_range_returns_error(api, admin_headers):
    """PRD §3.4: "The chosen color must be one of the product's
    `available_colors`, else `ERR_COLOR_UNAVAILABLE`; the requested discount must
    lie within the inclusive range 0 to 1, else `ERR_INVALID_DISCOUNT`; and the
    estimated footage must be greater than 0, else `ERR_INVALID_MEASUREMENT`."

    Design: Corner/validations/invalid_discount_pct_returns_error
    """
    product, rep, lead, appt = _fresh_quote_context()
    lv = get_lead_version(lead["id"])
    payload = {
        "lead_id": lead["id"], "appointment_id": appt["id"], "sales_rep_id": rep["id"],
        "product_id": product["id"], "color": "WHITE", "estimated_linear_feet": 100,
        "downspout_count": 0, "discount_pct": 1.5, "expected_lead_version": lv,
    }
    validate_error(api.create_quote(payload, admin_headers), ApiErrorId.ERR_INVALID_DISCOUNT)
