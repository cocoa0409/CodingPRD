"""Formulae that combine several independently-branched contributions.

Order pricing rounds once per unit and then multiplies. Engineering lead time
decides expedite eligibility on the raw total and only then shaves. The cutting
envelope multiplies four branched factors and clamps the product against an
application-class ceiling. In each case the order of operations is what the
answer turns on.
"""

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_tool_order,
    assert_tool_product,
    assert_total_is_per_unit_times_quantity,
)
from test_helpers.fixtures import APP, COAT
from prd_bench_local_runner.testing import validate_success


# ─── Order pricing: round per unit, then multiply ─────────────────────────────

def test_order_pricing_rounds_per_unit_before_multiplying_by_quantity(api):
    """A 100-piece PVD catalogue order prices at 4485 per unit and 448500 in total.

    PRD §3.8: "The gross per-unit price is `list_price_cents` multiplied by the
    quantity one plus the sum of the three surcharge fractions;
    `per_unit_net_cents` is that gross figure multiplied by the quantity one
    minus the volume discount fraction, **rounded half up to whole cents at that
    point**; and `total_price_cents` is `per_unit_net_cents` multiplied by
    `quantity`."

    PRD §3.8: "The rounding order is pinned to the unit: rounding once on the
    multiplied-out total instead differs by tens of cents on a large order and
    is incorrect."

    Design: Difficulty/combinatorial_formula/order_per_unit_round_then_multiply
    """
    state = fx.draft_order(api, quantity=100)

    response = api.submit_tool_order(state["order"]["id"], APP)

    order = validate_success(response)
    assert_tool_order(order)
    assert order["per_unit_net_cents"] == 4485, (
        "4550 x 1.06 is 4823 gross, and 4823 x 0.93 rounds to 4485 per unit, "
        f"got {order['per_unit_net_cents']}"
    )
    assert order["total_price_cents"] == 448500, (
        f"4485 x 100 is 448500, got {order['total_price_cents']}"
    )
    assert order["total_price_cents"] != 448539, (
        "448539 is the answer produced by rounding the multiplied-out total "
        "instead of the per-unit price"
    )
    assert_total_is_per_unit_times_quantity(order)


def test_catalog_order_submission_routes_to_submitted_with_the_product_lead_time(api):
    """A CATALOG order takes the direct branch and quotes the lead time unchanged.

    PRD §3.8: "A `CATALOG` order additionally requires the product's
    `release_status` to be `RELEASED`, moves `DRAFT` → `SUBMITTED`, and sets
    `promised_lead_time_days` to the product's `engineering_lead_time_days`
    unchanged."

    PRD §3.8: "Both branches price the order, recompute the product's
    `open_order_units`, and advance both the order's `version` and the product's
    `version` by 1."

    Design: Difficulty/combinatorial_formula/order_per_unit_round_then_multiply
    """
    state = fx.draft_order(api, quantity=100)

    order = validate_success(api.submit_tool_order(state["order"]["id"], APP))

    assert order["status"] == "SUBMITTED", (
        f"a CATALOG order submits straight to SUBMITTED, got {order['status']}"
    )
    assert order["promised_lead_time_days"] == 6, (
        "the released catalogue insert carries a 6-day engineering lead time, "
        f"got {order['promised_lead_time_days']}"
    )
    product = validate_success(api.get_tool_product(state["product"]["id"], APP))
    assert product["open_order_units"] == 100, (
        f"the submitted 100 pieces are now open load, got {product['open_order_units']}"
    )


def test_release_leaves_the_catalog_product_stocked_with_its_qualification_figures(api):
    """Release moves the supply dimension and publishes the qualification figures.

    PRD §3.5: "On release the `supply_status` dimension moves in the same
    request, and it moves differently by class: a `CATALOG` product goes
    `UNAVAILABLE` → `STOCKED`, skipping `MAKE_TO_ORDER` entirely, while a
    `SPECIAL` product goes `UNAVAILABLE` → `MAKE_TO_ORDER` and stops there."

    PRD §3.7: "`tool_life_index` becomes the unweighted mean of those trials'
    `rated_life_min` values — the sum divided by the trial count, not weighted
    by `units_consumed` — rounded half up to one decimal place, and is null
    when no such trial exists."

    PRD §3.7: "`qualified_workpiece_groups` becomes the distinct
    `workpiece_group` values of those trials, sorted ascending by the
    alphabetical spelling of the enum value."

    Design: Difficulty/combinatorial_formula/order_per_unit_round_then_multiply
    """
    state = fx.released_product(api)

    product = state["product"]
    assert_tool_product(product)
    assert product["release_status"] == "RELEASED", (
        f"the product has been released, got {product['release_status']}"
    )
    assert product["supply_status"] == "STOCKED", (
        f"a CATALOG release lands on STOCKED, got {product['supply_status']}"
    )
    assert product["tool_life_index"] == 21.7, (
        "the mean of the 20.0 and 23.3 minute ratings is 21.65, which rounds "
        f"half up to 21.7, got {product['tool_life_index']}"
    )
    assert product["qualified_workpiece_groups"] == ["M", "P"], (
        "the P and M trials both passed and the list is sorted alphabetically, "
        f"got {product['qualified_workpiece_groups']}"
    )


# ─── Lead time: eligibility is decided before the shave ──────────────────────

def _special_derivation_state(api):
    """A released catalogue parent plus an unproven CVD recipe to derive from."""
    state = fx.released_product(api)
    state["cvd_recipe"] = validate_success(
        api.create_coating_recipe(f.cvd_recipe_payload(), COAT), 201
    )
    return state


def test_special_cvd_product_stays_at_its_raw_lead_time_and_is_not_expedite_eligible(api):
    """A raw total of 22 days is quoted as 22 days, not shaved down to 19.

    PRD §3.5: "Those four contributions are summed into a raw lead time, and
    here the evaluation order is pinned and matters: `expedite_eligible` is
    decided on the **raw** total, being true when the raw total is at most 21
    days, and is never revisited afterwards."

    PRD §3.5: "The consequence is deliberate — a raw total of 22 days yields an
    `engineering_lead_time_days` of 22 with `expedite_eligible` false, even
    though 22 minus 3 would have been 19, because the shave never re-opens
    eligibility."

    Design: Difficulty/combinatorial_formula/product_lead_time_pre_shave_eligibility
    """
    state = _special_derivation_state(api)

    response = api.create_tool_product(
        f.special_product_payload(
            state["grade"]["id"],
            state["geometry"]["id"],
            state["cvd_recipe"]["id"],
            state["product"]["id"],
            sku="SPE-CVD-1",
            list_price_cents=6100,
        ),
        APP,
    )

    special = validate_success(response, 201)
    assert special["engineering_lead_time_days"] == 22, (
        "15 special days plus 7 CVD days is a raw 22, and an ineligible "
        f"product is never shaved, got {special['engineering_lead_time_days']}"
    )
    assert special["expedite_eligible"] is False, (
        "a raw total above 21 days is not expedite eligible, got "
        f"{special['expedite_eligible']}"
    )
    assert special["engineering_lead_time_days"] != 19, (
        "19 is the answer produced by shaving first and then testing eligibility"
    )


def test_special_pvd_product_is_expedite_eligible_and_takes_the_three_day_shave(api):
    """A raw total of 19 days is eligible and therefore quoted at 16 days.

    PRD §3.5: "Only if the product is expedite eligible is 3 days shaved off
    the raw total. The result is then floored at 2 days, and that final figure
    is `engineering_lead_time_days`."

    PRD §3.5: "The coating contributes nothing when `coating_recipe_id` is
    null, 4 days when the recipe's `deposition_type` is `PVD`, and 7 days when
    it is `CVD`."

    Design: Difficulty/combinatorial_formula/product_lead_time_pre_shave_eligibility
    """
    state = fx.released_product(api)

    response = api.create_tool_product(
        f.special_product_payload(
            state["grade"]["id"],
            state["geometry"]["id"],
            state["recipe"]["id"],
            state["product"]["id"],
            sku="SPE-PVD-1",
            list_price_cents=5800,
        ),
        APP,
    )

    special = validate_success(response, 201)
    assert special["expedite_eligible"] is True, (
        "15 special days plus 4 PVD days is a raw 19, inside the 21-day "
        f"window, got {special['expedite_eligible']}"
    )
    assert special["engineering_lead_time_days"] == 16, (
        f"19 raw days less the 3-day shave is 16, got {special['engineering_lead_time_days']}"
    )


def test_released_catalog_product_lead_time_is_shaved_to_six_days(api):
    """The catalogue parent's own raw 9 days shave to 6 and stay eligible.

    PRD §3.5: "The base contribution is 5 days for a `CATALOG` product and 15
    days for a `SPECIAL` one. The geometry contributes nothing when the
    geometry's `status` is `RELEASED` and 8 days otherwise."

    PRD §3.5: "The grade contributes nothing when the grade's `status` is
    `QUALIFIED` and 6 days otherwise."

    Design: Difficulty/combinatorial_formula/product_lead_time_pre_shave_eligibility
    """
    state = fx.released_product(api)

    product = validate_success(api.get_tool_product(state["product"]["id"], APP))

    assert product["engineering_lead_time_days"] == 6, (
        "5 catalogue days plus 4 PVD days is a raw 9, less the 3-day shave, "
        f"got {product['engineering_lead_time_days']}"
    )
    assert product["expedite_eligible"] is True, (
        f"a raw 9 days is well inside the window, got {product['expedite_eligible']}"
    )


# ─── The cutting envelope: four factors under a class ceiling ────────────────

def test_speeds_feeds_speed_is_capped_by_the_application_class_ceiling(api):
    """An N-group aluminium enquiry is clamped to the MEDIUM 340 m/min ceiling.

    PRD §3.5: "`recommended_vc` is that baseline multiplied by all four
    factors, then capped by the geometry's `application_class` ceiling — 260 for
    `ROUGHING`, 340 for `MEDIUM`, 420 for `FINISHING` — and rounded half up to a
    whole number of metres per minute."

    PRD §3.5: "Finally `confidence_class` is `HIGH` when the requested
    `workpiece_group` appears in the product's `qualified_workpiece_groups`;
    otherwise `MEDIUM` when the product's `release_status` is `RELEASED`;
    otherwise `LOW`."

    Design: Difficulty/combinatorial_formula/speeds_feeds_envelope_nested_min_max
    """
    state = fx.released_product(api)

    response = api.get_speeds_feeds(
        state["product"]["id"],
        f.speeds_feeds_params(
            workpiece_group="N", machine_rigidity="RIGID", coolant="THROUGH_TOOL"
        ),
        APP,
    )

    envelope = validate_success(response)
    assert envelope["recommended_vc"] == 340, (
        "400 x 1.08 x 1.16 x 1.00 x 1.10 is 551.232, clamped to the MEDIUM "
        f"ceiling of 340, got {envelope['recommended_vc']}"
    )
    assert envelope["confidence_class"] == "MEDIUM", (
        "the N group was never qualified on this released product, got "
        f"{envelope['confidence_class']}"
    )


def test_speeds_feeds_returns_the_full_uncapped_envelope_for_a_qualified_group(api):
    """A P-group enquiry falls under every ceiling and reports HIGH confidence.

    PRD §3.5: "The grade factor is 1.00 plus 0.02 for each percentage point by
    which `co_binder_pct` falls below 10.0 — equivalently, 1.00 plus 0.02
    multiplied by the quantity 10.0 minus `co_binder_pct`, which is negative for
    a high-binder grade — and the result is then clamped to lie between a floor
    of 0.85 and a ceiling of 1.20."

    PRD §3.5: "`recommended_fz` is the geometry's `nose_radius_mm` multiplied
    by 0.35, capped by the class feed ceiling of 0.55 millimetres for
    `ROUGHING`, 0.30 for `MEDIUM` or 0.14 for `FINISHING`, and rounded half up
    to three decimal places."

    PRD §3.5: "`recommended_ap` is the geometry's `max_depth_of_cut_mm`, capped
    by the class depth ceiling of 6.0 millimetres for `ROUGHING`, 3.0 for
    `MEDIUM` or 1.0 for `FINISHING`, and rounded half up to two decimal
    places."

    Design: Difficulty/combinatorial_formula/speeds_feeds_envelope_nested_min_max
    """
    state = fx.released_product(api)

    response = api.get_speeds_feeds(
        state["product"]["id"],
        f.speeds_feeds_params(
            workpiece_group="P", machine_rigidity="RIGID", coolant="FLOOD"
        ),
        APP,
    )

    envelope = validate_success(response)
    assert envelope["recommended_vc"] == 276, (
        "220 x 1.08 x 1.16 is 275.616, under the 340 ceiling, so it rounds to "
        f"276, got {envelope['recommended_vc']}"
    )
    assert envelope["recommended_fz"] == 0.280, (
        "a 0.8 mm nose radius times 0.35 is 0.280, under the 0.30 MEDIUM "
        f"ceiling, got {envelope['recommended_fz']}"
    )
    assert envelope["recommended_ap"] == 3.00, (
        "a 4.0 mm maximum depth is capped by the 3.0 MEDIUM ceiling, got "
        f"{envelope['recommended_ap']}"
    )
    assert envelope["confidence_class"] == "HIGH", (
        "the P group is in the product's qualified groups, got "
        f"{envelope['confidence_class']}"
    )


def test_speeds_feeds_weak_machine_and_dry_cutting_multiply_the_speed_down(api):
    """A superalloy enquiry on a weak, dry machine drops to 39 m/min.

    PRD §3.5: "The rigidity factor is 1.00 for `RIGID`, 0.85 for `MEDIUM` and
    0.70 for `WEAK`. The coolant factor is 1.00 for `FLOOD` and 1.10 for
    `THROUGH_TOOL`; for `DRY` it depends on the tool, being 0.60 for an
    uncoated product and 0.75 for a coated one."

    PRD §3.5: "The material baseline cutting speed in metres per minute is 220
    for group `P`, 170 for `M`, 150 for `K`, 400 for `N`, 60 for `S` and 45 for
    `H`."

    Design: Difficulty/combinatorial_formula/speeds_feeds_envelope_nested_min_max
    """
    state = fx.released_product(api)

    response = api.get_speeds_feeds(
        state["product"]["id"],
        f.speeds_feeds_params(
            workpiece_group="S", machine_rigidity="WEAK", coolant="DRY"
        ),
        APP,
    )

    envelope = validate_success(response)
    assert envelope["recommended_vc"] == 39, (
        "60 x 1.08 x 1.16 x 0.70 x 0.75 is 39.4632, which rounds to 39, got "
        f"{envelope['recommended_vc']}"
    )
