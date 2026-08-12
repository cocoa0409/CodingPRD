"""Build-spec pricing: provisional vs final variants, rebate/tier ordering,
loyalty threshold, OCC on quotes, and immediate consistency of approve."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, api_client,
    set_clock, create_customer, create_specialist, create_technician,
    create_bay, create_completed_session, book_session, create_component_trio,
    create_draft_spec, quote_spec, approve_spec, mark_ready, deliver_spec,
    setup_quoted_spec, get_spec, get_order_for_spec,
    customer_headers, staff_headers, create_component_item,
)


def _setup_dual_variant_spec():
    """Items: head 40000/55000, shaft 12000/18000, grip 800/1500; labor 15000;
    session COMPLETED. Provisional: 74500 + 15000 = 89500. Final: 52800 + 15000 - 7500 = 60300."""
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer("Ann Arbor")
    specialist = create_specialist()
    ctx = create_completed_session(customer, specialist)
    items = create_component_trio(
        head_stock=5, shaft_stock=5, grip_stock=20,
        head_unit=40_000, head_msrp=55_000,
        shaft_unit=12_000, shaft_msrp=18_000,
        grip_unit=800, grip_msrp=1_500,
    )
    spec = create_draft_spec(customer, ctx["session"], items, specialist, labor_cents=15_000)
    spec = quote_spec(spec, specialist)
    return {"customer": customer, "specialist": specialist, "items": items, "spec": spec}


def test_provisional_quote_prices_components_at_msrp(api):
    """PRD §3.4: "The provisional quote is an MSRP-based figure meant for the
    showroom floor." and "The quoted `provisional_quote_cents` is then the MSRP
    sum minus the discount plus `labor_cents`."

    Design: Difficulty/dual_variant_calc/build_price_provisional_msrp_vs_final_unitcost
    """
    ctx = _setup_dual_variant_spec()
    spec = ctx["spec"]
    # MSRP sum 55000+18000+1500 = 74500, below both tier thresholds -> no discount.
    assert spec["provisional_quote_cents"] == 89500, (
        f"expected provisional quote 89500 (74500 MSRP + 15000 labor), "
        f"got {spec['provisional_quote_cents']}"
    )
    assert spec["status"] == "QUOTED"


def test_final_price_prices_components_at_unit_cost_with_rebate(api):
    """PRD §3.4: "Fifth, a fitting-fee rebate of 7,500 cents is granted when the
    linked fitting session has reached `COMPLETED`, and is zero otherwise" and
    "the provisional and final variants use different bases, so identical spec
    inputs generally produce different totals at quote time and at approval time."

    Design: Difficulty/dual_variant_calc/build_price_provisional_msrp_vs_final_unitcost
    """
    ctx = _setup_dual_variant_spec()
    spec = approve_spec(ctx["spec"], ctx["customer"], "EXTERNAL")
    # Unit-cost sum 40000+12000+800 = 52800, no tier, +15000 labor - 7500 rebate.
    assert spec["final_price_cents"] == 60300, (
        f"expected final price 60300 (52800 + 15000 - 7500), got {spec['final_price_cents']}"
    )
    assert spec["provisional_quote_cents"] == 89500
    assert spec["provisional_quote_cents"] != spec["final_price_cents"]
    # Order fully allocated at approve -> auto-advance ORDERED -> IN_BUILD.
    assert spec["status"] == "IN_BUILD", f"expected IN_BUILD, got {spec['status']}"


def _setup_rebate_tier_spec():
    """Unit-cost sum 202000 (>= 200000 tier) with a COMPLETED session so the
    7500 rebate applies; tier must be selected on the pre-rebate sum."""
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer("Eli Elm")
    specialist = create_specialist()
    ctx = create_completed_session(customer, specialist)
    items = create_component_trio(
        head_stock=2, shaft_stock=2, grip_stock=5,
        head_unit=160_000, head_msrp=180_000,
        shaft_unit=41_000, shaft_msrp=46_000,
        grip_unit=1_000, grip_msrp=1_500,
    )
    spec = create_draft_spec(customer, ctx["session"], items, specialist, labor_cents=15_000)
    spec = quote_spec(spec, specialist)
    return {"customer": customer, "specialist": specialist, "items": items, "spec": spec}


def test_final_price_tier_selected_before_rebate(api):
    """PRD §3.4: "Second, the tier is selected on that cost sum before any
    rebate: ten percent at or above 500,000 cents, five percent at or above
    200,000 cents, otherwise zero." and "the rebate never influences tier
    selection."

    Design: Difficulty/combinatorial_formula/build_final_price_rebate_tier_evaluation_order
    """
    ctx = _setup_rebate_tier_spec()
    spec = approve_spec(ctx["spec"], ctx["customer"], "EXTERNAL")
    # 202000 - round(202000*0.05)=10100 + 15000 - 7500 = 199400.
    assert spec["final_price_cents"] == 199_400, (
        f"expected 199400 (tier on pre-rebate 202000), got {spec['final_price_cents']}"
    )
    assert spec["final_price_cents"] != 209_500, (
        "209500 is the wrong rebate-before-tier result"
    )


def test_final_price_rebate_tier_order_full_pipeline(api):
    """PRD §3.4: "Finally, `final_price_cents` is the cost sum minus the
    discount, plus `labor_cents`, minus the rebate, floored at zero" and "if
    the sweep fully allocates the order, the spec advances from `ORDERED` to
    `IN_BUILD` in the same request"

    Design: Difficulty/combinatorial_formula/build_final_price_rebate_tier_evaluation_order
    """
    ctx = _setup_rebate_tier_spec()
    spec = ctx["spec"]
    # Provisional on MSRP basis: 227500 >= 200000 -> 5% -> discount 11375 -> 231125.
    assert spec["provisional_quote_cents"] == 231_125, (
        f"expected provisional 231125, got {spec['provisional_quote_cents']}"
    )
    spec = approve_spec(spec, ctx["customer"], "EXTERNAL")
    assert spec["final_price_cents"] == 199_400
    assert spec["status"] == "IN_BUILD", f"expected IN_BUILD, got {spec['status']}"


def test_loyalty_discount_applies_at_two_completed_builds(api):
    """PRD §3.4: "A loyalty rate of five percent is added when the customer's
    `completed_builds_count` at quote time is at least two." and "`completed_builds_count`,
    starting at zero and incremented each time one of their builds is delivered" (§3.1).

    Design: Corner/calculations/loyalty_discount_threshold_at_two_builds
    """
    set_clock("2026-05-10T09:00:00Z")
    customer = create_customer("Liv Loch")
    specialist = create_specialist()
    technician = create_technician()
    ctx = create_completed_session(customer, specialist)
    session = ctx["session"]
    items = create_component_trio(
        head_stock=5, shaft_stock=5, grip_stock=5,
        head_unit=40_000, head_msrp=55_000,
        shaft_unit=12_000, shaft_msrp=18_000,
        grip_unit=800, grip_msrp=1_500,
    )

    def full_build():
        spec = create_draft_spec(customer, session, items, specialist, labor_cents=15_000)
        spec = quote_spec(spec, specialist)
        provisional = spec["provisional_quote_cents"]
        spec = approve_spec(spec, customer)
        spec = mark_ready(spec, technician)
        spec = deliver_spec(spec, specialist)
        return provisional, spec

    p1, _ = full_build()
    assert p1 == 89_500, f"count 0: expected 89500 (no loyalty), got {p1}"
    full_build()

    customer = get_success_data(api_client.get_customer(customer["id"], customer_headers(customer)))
    assert customer["completed_builds_count"] == 2, (
        f"expected completed_builds_count 2 after two deliveries, "
        f"got {customer['completed_builds_count']}"
    )

    spec3 = create_draft_spec(customer, session, items, specialist, labor_cents=15_000)
    spec3 = quote_spec(spec3, specialist)
    # 74500 - round(74500*0.05)=3725 + 15000 = 85775.
    assert spec3["provisional_quote_cents"] == 85_775, (
        f"count 2: expected 85775 (loyalty applies at >= 2), "
        f"got {spec3['provisional_quote_cents']}"
    )


def test_approve_response_carries_post_cascade_state(api):
    """PRD §3.4: "if the sweep fully allocates the order, the spec advances
    from `ORDERED` to `IN_BUILD` in the same request". PRD §2.2: "operations
    that create or modify a resource will return the created or updated
    resource object in the data field."

    Design: Corner/consistency_model/approve_response_reflects_final_state
    """
    ctx = setup_quoted_spec(
        complete_session=True, labor_cents=1_000,
        trio_overrides={
            "head_stock": 1, "shaft_stock": 1, "grip_stock": 1,
            "head_unit": 5_000, "head_msrp": 7_000,
            "shaft_unit": 3_000, "shaft_msrp": 4_000,
            "grip_unit": 800, "grip_msrp": 1_000,
        },
    )
    resp = api_client.approve_build_spec(
        ctx["spec"]["id"], {"payment_method": "EXTERNAL"},
        customer_headers(ctx["customer"]),
    )
    data = validate_success(resp)
    assert data["status"] == "IN_BUILD", (
        f"approve response must carry post-cascade state IN_BUILD, got {data['status']}"
    )
    assert data["final_price_cents"] == 2_300, (
        f"expected final_price_cents 2300 in the approve response, "
        f"got {data['final_price_cents']}"
    )


def test_occ_stale_quote_version_rejected(api):
    """PRD §2.7: "A request to quote or re-quote a build spec must carry
    `expected_build_spec_version`, a non-optional input holding the spec
    `version` the client last observed. If the spec's current `version` has
    advanced beyond that observed value, the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/occ_stale_quote_version_rejected
    """
    ctx = setup_quoted_spec(complete_session=False, labor_cents=15_000)
    spec = ctx["spec"]
    fs_headers = staff_headers(ctx["specialist"])
    stale_version = spec["version"] - 1  # version observed before the first quote

    resp = api_client.quote_build_spec(
        spec["id"], {"expected_build_spec_version": stale_version}, fs_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    resp = api_client.quote_build_spec(
        spec["id"], {"expected_build_spec_version": spec["version"]}, fs_headers,
    )
    data = validate_success(resp)
    assert data["status"] == "QUOTED"
    assert data["version"] == spec["version"] + 1, (
        f"re-quote with the current version must succeed and bump version to "
        f"{spec['version'] + 1}, got {data['version']}"
    )
