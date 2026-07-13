"""Building an order: the required index tier, the five-term lens upcharge, the
volume discount, and the four safety checks that stand between payload and draft."""

from test_helpers import (
    ApiErrorId,
    assert_order,
    create_order_payload,
    make_customer_headers,
    new_coating,
    new_customer,
    new_frame,
    new_material,
    new_verified_prescription,
    setup_order_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    LOW_POWER_RX,
    RX_POWER_EXACTLY_SIX,
    RX_POWER_NINE_WITH_PRISM,
    RX_POWER_THIRTEEN,
    STORE,
)


# ═════════════════════════════════════════════════════════════════════════════
# The five-term lens upcharge
# ═════════════════════════════════════════════════════════════════════════════

def test_lens_upcharge_sums_material_coating_prism_and_high_power_terms(api):
    """PRD §3.5: "It takes the larger of the absolute values of `od_sphere` and
    `os_sphere` — the stronger eye's sphere — and the larger of the absolute values of
    `od_cylinder` and `os_cylinder` — the stronger eye's cylinder. The power is the
    stronger sphere plus one half of the stronger cylinder."
    PRD §3.5: "4. Add the **prism surcharge**: forty-five dollars — 4,500 cents —
    whenever the prescription's `prism_diopters` is at least 0.50, and nothing at all
    when it is below 0.50."
    PRD §3.5: "5. Add the **high-power surcharge**. Subtract 6.00 from the
    prescription's power, multiply the remainder by one thousand cents per diopter, and
    round that product half up to whole cents; if the result is negative — which it is
    for any power below 6.00 — treat it as zero; then clamp it downward to a ceiling of
    sixty dollars, that is 6,000 cents. The clamp binds at any power of 12.00 or more."

    Power 9.00 with one coating and a 0.75 prism: 20,000 material + 4,000 coating
    - 0 bundle (a single coating gets no break) + 4,500 prism + 3,000 high-power.

    Design: Difficulty/combinatorial_formula/lens_upcharge_nested_min_max_tier_and_prism_branch
    """
    scenario = setup_order_scenario(
        frame={"price_cents": 19500, "min_pd_mm": 54.0, "max_pd_mm": 70.0},
        material={"code": "M174", "base_price_cents": 20000, "material_index": 1.74},
        coatings=[{"code": "AR", "base_price_cents": 4000}],
        prescription=dict(RX_POWER_NINE_WITH_PRISM),
    )
    order = scenario["order"]

    assert_order(order)
    assert order["lens_upcharge_cents"] == 31500


def test_a_fifty_one_thousand_cent_subtotal_earns_the_fifteen_percent_tier(api):
    """PRD §3.6: "**Step one: the subtotal.** `subtotal_cents` is the frame's
    `price_cents` plus the order's frozen `lens_upcharge_cents`."
    PRD §3.6: "A `subtotal_cents` below 25,000 cents earns nothing. A subtotal of at
    least 25,000 cents but below 50,000 cents earns ten percent. A subtotal of 50,000
    cents or more earns fifteen percent. `discount_cents` is that rate applied to
    `subtotal_cents` and floored to whole cents."
    PRD §3.6: "**Step four: the benefit waterfall.** If the customer has no
    `insurance_policy_id`, or if their policy's `network` is `OUT_OF_NETWORK`, then
    `benefit_frame_cents` and `benefit_lens_cents` are both zero: an out-of-network plan
    pays the member afterwards, never the retailer at the counter."

    19,500 frame + 31,500 upcharge == 51,000, which clears the 50,000 tier: the
    discount is floor(51,000 * 0.15) == 7,650 and a self-pay customer owes the rest.

    Design: Difficulty/combinatorial_formula/lens_upcharge_nested_min_max_tier_and_prism_branch
    """
    scenario = setup_order_scenario(
        frame={"price_cents": 19500, "min_pd_mm": 54.0, "max_pd_mm": 70.0},
        material={"code": "M174", "base_price_cents": 20000, "material_index": 1.74},
        coatings=[{"code": "AR", "base_price_cents": 4000}],
        prescription=dict(RX_POWER_NINE_WITH_PRISM),
    )
    order = scenario["order"]

    assert order["subtotal_cents"] == 51000
    assert order["discount_cents"] == 7650
    assert order["benefit_applied_cents"] == 0, "a self-pay customer gets no benefit"
    assert order["customer_due_cents"] == 43350
    assert order["quote_variant"] == "ESTIMATED"
    assert order["fsa_applied_cents"] == 0, "a draft order always shows zero FSA"


# ═════════════════════════════════════════════════════════════════════════════
# The required index tier at exactly 6.00 diopters
# ═════════════════════════════════════════════════════════════════════════════

def test_index_one_sixty_is_too_weak_at_a_power_of_exactly_six(api):
    """PRD §3.5: "A power below 4.00 requires a tier of `1.50`. A power of at least 4.00
    but below 6.00 requires `1.60`. A power of at least 6.00 but below 8.00 requires
    `1.67`. A power of 8.00 or above requires `1.74`. If the selected material option's
    `material_index` is **below** the required tier, the order is refused with
    `ERR_LENS_INCOMPATIBLE_WITH_RX`; an index at or above the tier is accepted, and an
    over-specified blank is always permitted."

    Sphere 5.50 plus half of cylinder 1.00 is a power of exactly 6.00, which lands in
    the [6.00, 8.00) tier — the tier boundary is inclusive, so 1.60 is refused.

    Design: Difficulty/boundary_precision_check/required_index_tier_fires_at_exactly_six_diopters
    """
    scenario = setup_order_scenario(
        frame={"price_cents": 19500, "min_pd_mm": 54.0, "max_pd_mm": 70.0},
        material={"code": "M160", "base_price_cents": 6000, "material_index": 1.60},
        prescription=dict(RX_POWER_EXACTLY_SIX),
        build_order=False,
    )
    weak = scenario["material"]

    resp = api.create_order(
        create_order_payload(
            scenario["customer"]["id"],
            scenario["prescription"]["id"],
            scenario["frame"]["id"],
            weak["id"],
            delivery_method="SHIP",
        ),
        scenario["headers"],
    )
    validate_error(resp, ApiErrorId.ERR_LENS_INCOMPATIBLE_WITH_RX.value)


def test_index_one_sixty_seven_is_accepted_at_a_power_of_exactly_six(api):
    """PRD §3.5: "If the selected material option's `material_index` is **below** the
    required tier, the order is refused with `ERR_LENS_INCOMPATIBLE_WITH_RX`; an index at
    or above the tier is accepted, and an over-specified blank is always permitted."
    PRD §3.5: "3. Subtract the **coating bundle discount**. When two or more coatings are
    selected, the discount is fifteen percent of the coating total, floored to whole
    cents. When fewer than two coatings are selected, the discount is zero — a single
    coating gets no bundle break."

    At the tier boundary a 1.67 blank passes, and the upcharge is 12,000 material +
    7,000 coatings - 1,050 bundle + 0 prism + 0 high-power (the power is exactly 6.00,
    so the surcharge term is zero) == 17,950.

    Design: Difficulty/boundary_precision_check/required_index_tier_fires_at_exactly_six_diopters
    """
    frame = new_frame(price_cents=19500, min_pd_mm=54.0, max_pd_mm=70.0)
    weak = new_material(code="M160", base_price_cents=6000, material_index=1.60)
    strong = new_material(code="M167", base_price_cents=12000, material_index=1.67)
    ar = new_coating(code="AR", base_price_cents=4000)
    blue = new_coating(code="BLUE", base_price_cents=3000)
    customer = new_customer(full_name="Bo Undary", email="bo6@example.com")
    headers = make_customer_headers(customer["id"])
    rx = new_verified_prescription(customer["id"], **RX_POWER_EXACTLY_SIX)

    refused = api.create_order(
        create_order_payload(
            customer["id"],
            rx["id"],
            frame["id"],
            weak["id"],
            coating_option_ids=[ar["id"], blue["id"]],
        ),
        headers,
    )
    validate_error(refused, ApiErrorId.ERR_LENS_INCOMPATIBLE_WITH_RX.value)

    resp = api.create_order(
        create_order_payload(
            customer["id"],
            rx["id"],
            frame["id"],
            strong["id"],
            coating_option_ids=[ar["id"], blue["id"]],
        ),
        headers,
    )
    order = validate_success(resp, 201)

    assert order["lens_upcharge_cents"] == 17950
    assert order["subtotal_cents"] == 37450
    assert order["customer_due_cents"] == 33705, "self-pay: 37,450 less the 3,745 discount"


# ═════════════════════════════════════════════════════════════════════════════
# The pricing constants
# ═════════════════════════════════════════════════════════════════════════════

def test_coating_bundle_discount_needs_two_coatings(api):
    """PRD §3.5: "2. Add the **coating total**: the plain sum of `base_price_cents`
    across every selected coating. The order of the array does not affect the sum."
    PRD §3.5: "3. Subtract the **coating bundle discount**. When two or more coatings are
    selected, the discount is fifteen percent of the coating total, floored to whole
    cents. When fewer than two coatings are selected, the discount is zero — a single
    coating gets no bundle break."

    Design: Corner/calculations/coating_bundle_discount_applies_only_from_two_coatings
    """
    frame = new_frame(price_cents=9500, min_pd_mm=54.0, max_pd_mm=70.0)
    material = new_material(code="M160", base_price_cents=6000, material_index=1.60)
    ar = new_coating(code="AR", base_price_cents=4000)
    blue = new_coating(code="BLUE", base_price_cents=3000)
    customer = new_customer(full_name="Coa Ting", email="coat@example.com")
    headers = make_customer_headers(customer["id"])
    rx = new_verified_prescription(
        customer["id"],
        od_sphere=-2.00,
        od_cylinder=0.00,
        os_sphere=-2.00,
        os_cylinder=0.00,
        pd_mm=62.0,
    )

    one = validate_success(
        api.create_order(
            create_order_payload(
                customer["id"],
                rx["id"],
                frame["id"],
                material["id"],
                coating_option_ids=[ar["id"]],
            ),
            headers,
        ),
        201,
    )
    two = validate_success(
        api.create_order(
            create_order_payload(
                customer["id"],
                rx["id"],
                frame["id"],
                material["id"],
                coating_option_ids=[ar["id"], blue["id"]],
            ),
            headers,
        ),
        201,
    )

    assert one["lens_upcharge_cents"] == 10000, "6,000 + 4,000, no bundle break"
    assert two["lens_upcharge_cents"] == 11950, "6,000 + 7,000 - floor(7,000 * 0.15)"
    assert two["subtotal_cents"] == 21450
    assert two["discount_cents"] == 0, "21,450 sits below the 25,000c tier"


def test_high_power_surcharge_clamps_at_six_thousand_cents(api):
    """PRD §3.5: "5. Add the **high-power surcharge**. Subtract 6.00 from the
    prescription's power, multiply the remainder by one thousand cents per diopter, and
    round that product half up to whole cents; if the result is negative — which it is
    for any power below 6.00 — treat it as zero; then clamp it downward to a ceiling of
    sixty dollars, that is 6,000 cents. The clamp binds at any power of 12.00 or more."
    PRD §3.5: "4. Add the **prism surcharge**: forty-five dollars — 4,500 cents —
    whenever the prescription's `prism_diopters` is at least 0.50, and nothing at all
    when it is below 0.50."

    Power 13.00 gives a raw surcharge of (13.00 - 6.00) * 1,000 == 7,000, which the
    ceiling clamps to 6,000; a 0.25 prism sits below the 0.50 trigger and adds nothing.

    Design: Corner/calculations/high_power_surcharge_clamps_at_its_cap
    """
    scenario = setup_order_scenario(
        frame={"price_cents": 9500, "min_pd_mm": 54.0, "max_pd_mm": 70.0},
        material={"code": "M174", "base_price_cents": 20000, "material_index": 1.74},
        coatings=[{"code": "AR", "base_price_cents": 4000}],
        prescription=dict(RX_POWER_THIRTEEN),
    )
    order = scenario["order"]

    assert order["lens_upcharge_cents"] == 30000, "20,000 + 4,000 + 0 prism + 6,000 clamped"
    assert order["subtotal_cents"] == 39500
    assert order["discount_cents"] == 3950
    assert order["customer_due_cents"] == 35550


def test_discount_tier_fires_at_a_subtotal_of_exactly_twenty_five_thousand(api):
    """PRD §3.6: "A `subtotal_cents` below 25,000 cents earns nothing. A subtotal of at
    least 25,000 cents but below 50,000 cents earns ten percent. A subtotal of 50,000
    cents or more earns fifteen percent. `discount_cents` is that rate applied to
    `subtotal_cents` and floored to whole cents. The **net** amount is `subtotal_cents`
    minus `discount_cents`."

    A 19,000c frame plus a 6,000c blank is exactly 25,000 — the tier is inclusive, so
    the ten percent rate applies and the discount is 2,500.

    Design: Corner/calculations/discount_tier_fires_at_exactly_twenty_five_thousand
    """
    scenario = setup_order_scenario(
        frame={"price_cents": 19000, "min_pd_mm": 54.0, "max_pd_mm": 70.0},
        material={"code": "M160", "base_price_cents": 6000, "material_index": 1.60},
        prescription={
            "od_sphere": -2.00,
            "od_cylinder": 0.00,
            "os_sphere": -2.00,
            "os_cylinder": 0.00,
            "pd_mm": 62.0,
        },
    )
    order = scenario["order"]

    assert order["subtotal_cents"] == 25000
    assert order["discount_cents"] == 2500
    assert order["customer_due_cents"] == 22500


# ═════════════════════════════════════════════════════════════════════════════
# The order-creation safety and referential checks
# ═════════════════════════════════════════════════════════════════════════════

def test_prescription_pd_outside_the_frames_geometry_is_refused(api):
    """PRD §3.5: "The prescription's `pd_mm` must lie within the ordered frame's
    geometry — at least `min_pd_mm` and at most `max_pd_mm`, both bounds inclusive — or
    the order is refused with `ERR_PD_OUT_OF_RANGE`."

    Design: Corner/validations/pd_outside_the_frame_range_on_order_returns_pd_out_of_range
    """
    scenario = setup_order_scenario(
        frame={"price_cents": 9500, "min_pd_mm": 54.0, "max_pd_mm": 70.0},
        material={"code": "M150", "base_price_cents": 0, "material_index": 1.50},
        prescription=dict(LOW_POWER_RX, pd_mm=72.0),
        build_order=False,
    )

    resp = api.create_order(
        create_order_payload(
            scenario["customer"]["id"],
            scenario["prescription"]["id"],
            scenario["frame"]["id"],
            scenario["material"]["id"],
        ),
        scenario["headers"],
    )
    validate_error(resp, ApiErrorId.ERR_PD_OUT_OF_RANGE.value)

    _rows, meta = validate_paginated(
        api.list_orders(STORE, params={"customer_id": scenario["customer"]["id"]})
    )
    assert meta["total_count"] == 0, "no draft was persisted"


def test_two_mutually_exclusive_coatings_are_refused(api):
    """PRD §3.5: "No two selected coatings may be mutually exclusive: if either coating
    names the other's `code` in its `incompatible_with` array, the pairing is refused with
    `ERR_COATING_INCOMPATIBLE` — the check is symmetric, so one-sided declarations still
    block."

    Only BLUE declares PHOTO; PHOTO declares nothing. The symmetry rule blocks anyway.

    Design: Corner/validations/incompatible_coating_pair_rejected
    """
    frame = new_frame(price_cents=9500, min_pd_mm=54.0, max_pd_mm=70.0)
    material = new_material(code="M150", base_price_cents=0, material_index=1.50)
    blue = new_coating(code="BLUE", base_price_cents=3000, incompatible_with=["PHOTO"])
    photo = new_coating(code="PHOTO", base_price_cents=9000)
    customer = new_customer(full_name="Con Flict", email="con@example.com")
    rx = new_verified_prescription(customer["id"], **LOW_POWER_RX)

    resp = api.create_order(
        create_order_payload(
            customer["id"],
            rx["id"],
            frame["id"],
            material["id"],
            # PHOTO first: the one-sided declaration still blocks.
            coating_option_ids=[photo["id"], blue["id"]],
        ),
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_COATING_INCOMPATIBLE.value)


def test_ordering_a_discontinued_frame_is_refused(api):
    """PRD §3.5: "And the frame's `status` must be `ACTIVE`, or the order is refused with
    `ERR_FRAME_DISCONTINUED`."
    PRD §3.1: "`ACTIVE` frames may be ordered and tried on; `DISCONTINUED` frames may not
    be ordered."

    Design: Corner/validations/ordering_a_discontinued_frame_rejected
    """
    scenario = setup_order_scenario(
        frame={
            "price_cents": 9500,
            "min_pd_mm": 54.0,
            "max_pd_mm": 70.0,
            "status": "DISCONTINUED",
        },
        material={"code": "M150", "base_price_cents": 0, "material_index": 1.50},
        prescription=dict(LOW_POWER_RX),
        build_order=False,
    )

    resp = api.create_order(
        create_order_payload(
            scenario["customer"]["id"],
            scenario["prescription"]["id"],
            scenario["frame"]["id"],
            scenario["material"]["id"],
        ),
        scenario["headers"],
    )
    validate_error(resp, ApiErrorId.ERR_FRAME_DISCONTINUED.value)


def test_bopis_without_a_store_is_refused_and_ship_without_one_succeeds(api):
    """PRD §3.5: "Delivery method and store must agree — `BOPIS` requires a non-null
    `store_id` and `SHIP` requires `store_id` to be null; either mismatch is refused with
    `ERR_BOPIS_STORE_REQUIRED`."

    Design: Corner/validations/bopis_delivery_without_a_store_rejected
    """
    scenario = setup_order_scenario(
        frame={"price_cents": 9500, "min_pd_mm": 54.0, "max_pd_mm": 70.0},
        material={"code": "M150", "base_price_cents": 0, "material_index": 1.50},
        prescription=dict(LOW_POWER_RX),
        build_order=False,
    )

    bopis = api.create_order(
        create_order_payload(
            scenario["customer"]["id"],
            scenario["prescription"]["id"],
            scenario["frame"]["id"],
            scenario["material"]["id"],
            delivery_method="BOPIS",  # no store_id
        ),
        scenario["headers"],
    )
    validate_error(bopis, ApiErrorId.ERR_BOPIS_STORE_REQUIRED.value)

    ship = api.create_order(
        create_order_payload(
            scenario["customer"]["id"],
            scenario["prescription"]["id"],
            scenario["frame"]["id"],
            scenario["material"]["id"],
            delivery_method="SHIP",
        ),
        scenario["headers"],
    )
    order = validate_success(ship, 201)
    assert order["delivery_method"] == "SHIP"
    assert order["store_id"] is None


def test_a_retired_lens_option_is_invisible_to_order_creation(api):
    """PRD §2.9: "A lens option whose `status` is `RETIRED` is treated as **not found**
    at this step, as is a lens option referenced in the wrong slot (a coating supplied
    where a material was expected, or the reverse) — both surface as
    `ERR_LENS_OPTION_NOT_FOUND`."
    PRD §3.1: "A `RETIRED` option can never be selected on a new order."

    Design: Corner/errors/retired_lens_option_treated_as_lens_option_not_found
    """
    scenario = setup_order_scenario(
        frame={"price_cents": 9500, "min_pd_mm": 54.0, "max_pd_mm": 70.0},
        material={
            "code": "M150OLD",
            "base_price_cents": 0,
            "material_index": 1.50,
            "status": "RETIRED",
        },
        prescription=dict(LOW_POWER_RX),
        build_order=False,
    )

    resp = api.create_order(
        create_order_payload(
            scenario["customer"]["id"],
            scenario["prescription"]["id"],
            scenario["frame"]["id"],
            scenario["material"]["id"],
        ),
        scenario["headers"],
    )
    validate_error(resp, ApiErrorId.ERR_LENS_OPTION_NOT_FOUND.value)
