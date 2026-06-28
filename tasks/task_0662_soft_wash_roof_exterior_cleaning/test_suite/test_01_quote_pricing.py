"""Quote line pricing, chemical dose clamping, subtotal rounding order, and the travel
surcharge tier function. Translates Difficulty rule combinatorial_formula and the
calculations-section corner instances.
"""
from test_helpers import (
    validate_success,
    create_customer_payload, create_route_payload, create_property_payload,
    create_quote_payload, create_line_item_payload,
    TEST_USERS, make_customer_headers,
)

DISP = TEST_USERS["dispatcher_headers"]


def _draft_quote(api, stories=1, soiling_level=None, **prop_kwargs):
    cust = validate_success(api.create_customer(create_customer_payload(email=f"q{id(prop_kwargs)}@x.com"), DISP), 201)
    route = validate_success(api.create_route(create_route_payload(name="Z"), DISP), 201)
    prop = validate_success(
        api.create_property(create_property_payload(cust["id"], route["id"], stories=stories, **prop_kwargs), DISP), 201)
    qkw = {}
    if soiling_level is not None:
        qkw["soiling_level"] = soiling_level
    quote = validate_success(
        api.create_quote(create_quote_payload(prop["id"], prop["version"], **qkw), DISP), 201)
    return cust, route, prop, quote


# ─────────────────────────────────────────────────────────────────────────
# Difficulty / combinatorial_formula
# ─────────────────────────────────────────────────────────────────────────

def test_line_total_rounds_per_line_before_summing_into_subtotal(api):
    """PRD §2.5: "each individual line is rounded to whole cents first, and the rounded
    per-line amounts are then summed. The system never sums raw, unrounded line amounts and
    rounds at the end."
    PRD §3.2: "Multiply `measured_sqft` by the surface rate, by the service multiplier, and
    by the height multiplier, and round the product half-up to whole cents to obtain
    `line_total_cents`."

    Design: Difficulty/combinatorial_formula/quote_line_rounding_order_round_per_line_then_sum
    """
    cust, route, prop, quote = _draft_quote(api, stories=1, concrete_sqft=210)
    li1 = validate_success(
        api.add_line_item(quote["id"], create_line_item_payload("CONCRETE", "CONCRETE_CLEAN", 105), DISP), 201)
    validate_success(
        api.add_line_item(quote["id"], create_line_item_payload("CONCRETE", "CONCRETE_CLEAN", 105), DISP), 201)
    # 105 * 11 * 1.1 * 1.0 = 1270.5 -> round-half-up -> 1271 per line.
    assert li1["line_total_cents"] == 1271, li1["line_total_cents"]
    sent = validate_success(api.send_quote(quote["id"], DISP), 200)
    # 1271 + 1271 = 2542 (sum-then-round would give 2541).
    assert sent["subtotal_cents"] == 2542, sent["subtotal_cents"]


def test_subtotal_round_per_line_total_includes_full_travel(api):
    """PRD §3.2: "First the `subtotal_cents` is computed as the sum of the already-rounded
    `line_total_cents` across all of the quote's line items."
    PRD §3.2: "Otherwise the surcharge is the full flat travel charge of 7,500 cents (seventy-five dollars)."

    Design: Difficulty/combinatorial_formula/quote_line_rounding_order_round_per_line_then_sum
    """
    cust, route, prop, quote = _draft_quote(api, stories=1, concrete_sqft=210)
    validate_success(
        api.add_line_item(quote["id"], create_line_item_payload("CONCRETE", "CONCRETE_CLEAN", 105), DISP), 201)
    validate_success(
        api.add_line_item(quote["id"], create_line_item_payload("CONCRETE", "CONCRETE_CLEAN", 105), DISP), 201)
    sent = validate_success(api.send_quote(quote["id"], DISP), 200)
    assert sent["subtotal_cents"] == 2542, sent["subtotal_cents"]
    # subtotal 2542 < 1,500,000 -> full 7500; total 2542 + 7500 = 10042.
    assert sent["total_cents"] == 10042, sent["total_cents"]


def test_chemical_dose_three_inputs_clamps_up_to_priming_minimum(api):
    """PRD §3.2: "The resulting raw ounce figure is then clamped into the safe mixing band:
    it is first capped at the maximum tank capacity of 320.0 ounces (the raw figure or 320.0,
    whichever is smaller), and then raised to the priming minimum of 8.0 ounces if it falls
    below it (the just-capped figure or 8.0, whichever is larger). The final dose is rounded
    to one decimal place, round-half-up."

    Design: Difficulty/combinatorial_formula/chemical_dose_three_inputs_nested_min_max_clamps_to_minimum
    """
    cust, route, prop, quote = _draft_quote(api, stories=1, soiling_level="MODERATE", concrete_sqft=105)
    li = validate_success(
        api.add_line_item(quote["id"], create_line_item_payload("CONCRETE", "CONCRETE_CLEAN", 105), DISP), 201)
    # raw = (105/100)*4*1.0 = 4.2 oz, below MIN_PRIME 8.0 -> clamped up to 8.0.
    assert li["chemical_dose_oz"] == 8.0, li["chemical_dose_oz"]


def test_chemical_dose_line_total_independent_of_dose_clamp(api):
    """PRD §3.2: "Begin with a surface rate in cents per square foot keyed on `surface_type`
    — 22 cents for `ROOF`, 15 cents for `SIDING`, and 11 cents for `CONCRETE`."
    PRD §3.2: "Apply a service multiplier keyed on `service_type` — 1.25 for `ROOF_SOFT_WASH`,
    1.0 for `HOUSE_WASH`, and 1.1 for `CONCRETE_CLEAN`."

    Design: Difficulty/combinatorial_formula/chemical_dose_three_inputs_nested_min_max_clamps_to_minimum
    """
    cust, route, prop, quote = _draft_quote(api, stories=1, soiling_level="MODERATE", concrete_sqft=105)
    li = validate_success(
        api.add_line_item(quote["id"], create_line_item_payload("CONCRETE", "CONCRETE_CLEAN", 105), DISP), 201)
    # 105 * 11 * 1.1 * 1.0 = 1270.5 -> 1271.
    assert li["line_total_cents"] == 1271, li["line_total_cents"]


# ─────────────────────────────────────────────────────────────────────────
# Corner / calculations
# ─────────────────────────────────────────────────────────────────────────

def test_chemical_dose_caps_at_tank_maximum(api):
    """PRD §3.2: "it is first capped at the maximum tank capacity of 320.0 ounces (the raw
    figure or 320.0, whichever is smaller)".

    Design: Corner/calculations/chemical_dose_max_clamp_caps_at_tank_limit
    """
    cust, route, prop, quote = _draft_quote(api, stories=1, soiling_level="HEAVY", roof_sqft=100000)
    li = validate_success(
        api.add_line_item(quote["id"], create_line_item_payload("ROOF", "ROOF_SOFT_WASH", 100000), DISP), 201)
    # raw = (100000/100)*6*1.4 = 8400 oz -> capped at 320.0.
    assert li["chemical_dose_oz"] == 320.0, li["chemical_dose_oz"]


def test_travel_surcharge_zero_for_large_job(api):
    """PRD §3.2: "If `subtotal_cents` is at least 5,000,000 cents (that is, fifty thousand
    dollars), the surcharge is 0, because large jobs ship with free travel."

    Design: Corner/calculations/travel_surcharge_large_job_zero_branch
    """
    cust, route, prop, quote = _draft_quote(api, stories=1, siding_sqft=350000)
    validate_success(
        api.add_line_item(quote["id"], create_line_item_payload("SIDING", "HOUSE_WASH", 350000), DISP), 201)
    sent = validate_success(api.send_quote(quote["id"], DISP), 200)
    # 350000 * 15 * 1.0 * 1.0 = 5,250,000 >= 5,000,000 -> surcharge 0.
    assert sent["subtotal_cents"] == 5250000, sent["subtotal_cents"]
    assert sent["travel_surcharge_cents"] == 0, sent["travel_surcharge_cents"]
    assert sent["total_cents"] == 5250000, sent["total_cents"]


def test_travel_surcharge_full_flat_for_small_job(api):
    """PRD §3.2: "Otherwise the surcharge is the full flat travel charge of 7,500 cents
    (seventy-five dollars)."

    Design: Corner/calculations/travel_surcharge_small_job_full_branch
    """
    cust, route, prop, quote = _draft_quote(api, stories=2, roof_sqft=2000, siding_sqft=1500)
    validate_success(
        api.add_line_item(quote["id"], create_line_item_payload("ROOF", "ROOF_SOFT_WASH", 2000), DISP), 201)
    validate_success(
        api.add_line_item(quote["id"], create_line_item_payload("SIDING", "HOUSE_WASH", 1500), DISP), 201)
    sent = validate_success(api.send_quote(quote["id"], DISP), 200)
    # roof 60500 + siding 24750 = 85250 < 1,500,000 -> full 7500; total 92750.
    assert sent["subtotal_cents"] == 85250, sent["subtotal_cents"]
    assert sent["travel_surcharge_cents"] == 7500, sent["travel_surcharge_cents"]
    assert sent["total_cents"] == 92750, sent["total_cents"]
