"""Tests for the pricing engine and profit calculations.

Covers: listed_price ceil-per-component-then-sum (§2.6, §3.6),
provisional vs final creator_profit dual variant (§3.8),
incremental vs full-recompute reprint-risk-score dual variant (§3.8),
pinned gross-then-fee-then-net payout order (§3.9).
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    api_client,
    make_creator_headers,
    make_platform_admin_headers,
    make_anonymous_headers,
    make_fulfillment_partner_headers,
    setup_basic_scenario,
    set_clock,
    create_active_partner,
    create_product_and_variant,
    create_verified_creator,
    create_storefront,
    upload_and_approve_design,
    create_and_publish_listing,
    create_and_capture_order,
    advance_order_to_shipped,
    advance_order_to_delivered,
    fail_shipped_job,
    open_reprint_on_failed_job,
    create_payout_cycle,
    listing_payload,
    reprint_request_payload,
    order_payload,
    creator_verify_payload,
    creator_register_payload,
    storefront_payload,
    design_payload,
    product_payload,
    variant_payload,
    payout_cycle_payload,
    fulfillment_partner_payload,
)


# =============================================================================
# Rule 2 (a) — listing_price ceil-per-component (2 tests per instance)
# =============================================================================

def test_listing_price_ceils_platform_fee_and_markup_independently(api):
    """PRD §2.6: "when computing a listed price, the platform fee and the creator
    markup are each ceiled independently before being added to the base cost —
    the sum of two ceilings, not the ceiling of a sum."
    PRD §3.6: "The platform fee in basis-points is chosen by product category:
    `APPAREL` carries 1500 basis-points, `DRINKWARE` 1200, `ACCESSORY` 1000, and `PRINT` 800."

    base=101, APPAREL fee=1500 bps, markup=1500 bps:
    platform_fee = ceil(101*1500/10000) = ceil(15.15) = 16
    creator_markup = ceil(101*1500/10000) = 16
    listed_price = 101 + 16 + 16 = 133. Sum-then-ceil would give ceil(101*3000/10000)=31 -> 132.

    Design: Difficulty/combinatorial_formula/listing_price_ceil_per_component_then_sum
    """
    set_clock("2026-06-01T00:00:00Z")
    product, variant = create_product_and_variant(
        sku="T-EDGE", category="APPAREL", base_cost_cents=101,
    )
    creator = create_verified_creator(email="c1@example.com", display_name="C1")
    storefront = create_storefront(
        creator_id=creator["id"], slug="c1-sf", markup_bps=1500,
    )
    design = upload_and_approve_design(creator["id"], file_hash="hash_edge_a")

    resp = api.create_listing(
        listing_payload(storefront["id"], design["id"], variant["id"], title="Edge Tee"),
        make_creator_headers(creator["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["listed_price_cents"] == 133, \
        f"Expected 133 (=101+16+16), got {data['listed_price_cents']}"
    assert data["listed_price_cents"] != 132, \
        "Value 132 would indicate incorrect sum-then-ceil order"


def test_listing_price_apparel_boundary_no_rounding_needed(api):
    """PRD §2.6: "when computing a listed price, the platform fee and the creator
    markup are each ceiled independently before being added to the base cost —
    the sum of two ceilings, not the ceiling of a sum."
    PRD §3.6: "The platform fee in basis-points is chosen by product category:
    `APPAREL` carries 1500 basis-points, `DRINKWARE` 1200, `ACCESSORY` 1000, and `PRINT` 800."

    base=2000, APPAREL fee=1500 bps, markup=5000 bps (exact divisions):
    platform_fee = ceil(2000*1500/10000) = 300, creator_markup = ceil(2000*5000/10000) = 1000,
    listed_price = 2000 + 300 + 1000 = 3300 (no ceil rounding at this boundary).

    Design: Difficulty/combinatorial_formula/listing_price_ceil_per_component_then_sum
    """
    scenario = setup_basic_scenario(
        creator_email="c2@example.com", display_name="C2", slug="c2-sf",
        sku="T-EXACT", base_cost_cents=2000, markup_bps=5000,
        file_hash="hash_exact_1", publish_listing_flag=False,
    )
    listing = scenario["listing"]
    assert listing["listed_price_cents"] == 3300, \
        f"Expected 3300 (2000+300+1000), got {listing['listed_price_cents']}"


# =============================================================================
# Rule 2 (c) — payout_cycle pinned gross->fee->net order
# =============================================================================

def test_payout_release_pins_gross_then_floor_fee_then_net(api):
    """PRD §3.9: "Step one sums the finalized creator margin (the `creator_net_cents`
    written by the final profit variant) across every `Order` owned by this creator
    whose `fulfillment_status` is `DELIVERED`, whose delivered timestamp (the order's
    `updated_at` at the moment of the delivered transition) falls in the half-open
    window `[cycle_start, cycle_end)`, and whose `is_sample` is false — sample
    orders are excluded from payout altogether."
    PRD §3.9: "Step two computes `fee_cents` as the floor of `gross_earnings_cents`
    multiplied by the creator's `default_payout_fee_bps` (frozen at release time onto
    the cycle) divided by ten thousand — payout fees are floored, not ceiled, so the
    platform never over-collects."
    PRD §3.9: "Step three computes `net_paid_cents` as `gross_earnings_cents` minus
    `fee_cents` exactly."

    For one DELIVERED non-sample order with creator_net_cents=1000 (base=2000, markup
    5000 bps, item_count=1) and default_payout_fee_bps=250:
    gross=1000, fee=floor(1000*250/10000)=25, net=1000-25=975.

    Design: Difficulty/combinatorial_formula/payout_cycle_pinned_gross_then_fee_then_net_order
    """
    scenario = setup_basic_scenario(
        creator_email="p1@example.com", display_name="P1", slug="p1-sf",
        sku="T-P1", base_cost_cents=2000, markup_bps=5000,
        file_hash="hash_p1", clock_iso="2026-06-15T00:00:00Z",
    )
    order, _ = create_and_capture_order(scenario, item_count=1)
    order, _ = advance_order_to_delivered(scenario, order)

    cycle = create_payout_cycle(
        scenario["creator"]["id"],
        cycle_start="2026-06-01T00:00:00Z",
        cycle_end="2026-06-30T00:00:00Z",
    )
    resp = api.release_payout(cycle["id"], make_platform_admin_headers())
    released = validate_success(resp)
    assert released["gross_earnings_cents"] == 1000, \
        f"Expected gross=1000, got {released['gross_earnings_cents']}"
    assert released["fee_cents"] == 25, \
        f"Expected fee=25 (floor(1000*250/10000)), got {released['fee_cents']}"
    assert released["net_paid_cents"] == 975, \
        f"Expected net=975 (1000-25), got {released['net_paid_cents']}"
    assert released["status"] == "RELEASED"


def test_payout_release_wallet_debited_by_net_paid(api):
    """PRD §3.9: "The cycle transitions to `RELEASED`, and the creator's
    `payout_wallet_cents` decreases by `net_paid_cents`."
    PRD §3.9: "Step two computes `fee_cents` as the floor of `gross_earnings_cents`
    multiplied by the creator's `default_payout_fee_bps` (frozen at release time onto
    the cycle) divided by ten thousand — payout fees are floored, not ceiled, so the
    platform never over-collects."

    Wallet before release = 1000; after release wallet = 1000 - 975 = 25 (the fee).

    Design: Difficulty/combinatorial_formula/payout_cycle_pinned_gross_then_fee_then_net_order
    """
    scenario = setup_basic_scenario(
        creator_email="p2@example.com", display_name="P2", slug="p2-sf",
        sku="T-P2", base_cost_cents=2000, markup_bps=5000,
        file_hash="hash_p2", clock_iso="2026-06-15T00:00:00Z",
    )
    order, _ = create_and_capture_order(scenario, item_count=1)
    order, _ = advance_order_to_delivered(scenario, order)

    creator_before = get_success_data(
        api.get_creator(scenario["creator"]["id"], make_platform_admin_headers())
    )
    assert creator_before["payout_wallet_cents"] == 1000, \
        f"Setup: wallet pre-release should be 1000, got {creator_before['payout_wallet_cents']}"

    cycle = create_payout_cycle(
        scenario["creator"]["id"],
        cycle_start="2026-06-01T00:00:00Z",
        cycle_end="2026-06-30T00:00:00Z",
    )
    api.release_payout(cycle["id"], make_platform_admin_headers())

    creator_after = get_success_data(
        api.get_creator(scenario["creator"]["id"], make_platform_admin_headers())
    )
    assert creator_after["payout_wallet_cents"] == 25, \
        f"Expected wallet=25 (1000-975), got {creator_after['payout_wallet_cents']}"


# =============================================================================
# Rule 1 (dual_variant_calc) — creator_profit provisional vs final
# =============================================================================

def test_provisional_creator_net_equals_gross_markup_at_order_creation(api):
    """PRD §3.8: "The provisional variant runs at order creation and stores the
    forward-looking gross markup — the per-unit creator markup ceiled independently,
    multiplied by `item_count` — without any partner-absorb deduction."
    PRD §3.6: "The platform fee in basis-points is chosen by product category:
    `APPAREL` carries 1500 basis-points, `DRINKWARE` 1200, `ACCESSORY` 1000, and `PRINT` 800."

    base=2000, markup=5000 bps, item_count=2:
    markup_per_unit = ceil(2000*5000/10000) = 1000; provisional_net = 1000*2 = 2000.

    Design: Difficulty/dual_variant_calc/creator_profit_provisional_vs_final_on_consumer_fault_reprint
    """
    scenario = setup_basic_scenario(
        creator_email="dv1@example.com", display_name="DV1", slug="dv1-sf",
        sku="T-DV1", base_cost_cents=2000, markup_bps=5000,
        file_hash="hash_dv1", clock_iso="2026-06-01T00:00:00Z",
    )
    resp = api.create_order(
        order_payload(
            storefront_id=scenario["storefront"]["id"],
            listing_id=scenario["listing"]["id"],
            item_count=2, is_sample=False,
        ),
        make_anonymous_headers(),
    )
    order = validate_success(resp, expected_status=201)
    assert order["creator_net_cents"] == 2000, \
        f"Expected provisional creator_net_cents=2000, got {order['creator_net_cents']}"


def test_final_creator_net_diverges_from_provisional_on_consumer_fault_reprint(api):
    """PRD §3.8: "The provisional variant runs at order creation and stores the
    forward-looking gross markup — the per-unit creator markup ceiled independently,
    multiplied by `item_count` — without any partner-absorb deduction. The final
    variant runs at the delivered transition and overwrites `creator_net_cents`
    with the same gross markup minus the final partner-absorb term."
    PRD §3.8: "For a `CONSUMER_FAULT` reprint, the partner charge is recomputed as
    the initial partner charge locked at first routing plus twenty-five percent of
    that initial charge multiplied by the reprint generation, rounded up to the
    next whole cent — the surcharge scales linearly with generation and lands in
    the final variant of the profit calculation as the creator's absorbance."

    base=2000, markup=5000 bps, item_count=2, cost_multiplier=1.0x, CONSUMER_FAULT
    reprint generation=1:
      initial partner_charge = ceil(2000*2*10000/10000) = 4000
      after reprint: partner_charge = 4000 + ceil(4000*0.25*1) = 5000
      final_partner_absorb = 5000 - 4000 = 1000
      final creator_net = 2000 - 1000 = 1000 (provisional was 2000).

    Design: Difficulty/dual_variant_calc/creator_profit_provisional_vs_final_on_consumer_fault_reprint
    """
    scenario = setup_basic_scenario(
        creator_email="dv2@example.com", display_name="DV2", slug="dv2-sf",
        sku="T-DV2", base_cost_cents=2000, markup_bps=5000,
        file_hash="hash_dv2", clock_iso="2026-06-01T00:00:00Z",
    )
    # Create order (provisional=2000); capture; ship; fail; open CONSUMER_FAULT reprint
    order, job = create_and_capture_order(scenario, item_count=2, is_sample=False)
    provisional_net = order["creator_net_cents"]
    assert provisional_net == 2000, \
        f"Setup: provisional net should be 2000, got {provisional_net}"

    order, job = advance_order_to_shipped(scenario, order)
    fail_shipped_job(scenario, job)
    from test_helpers.fixtures import _find_job_for_order
    job = _find_job_for_order(order["id"])
    reprint = open_reprint_on_failed_job(job, fault_category="CONSUMER_FAULT", reason_code="DAMAGED")

    # Approve reprint -> cycles job back to QUEUED; walk the reprint fulfillment cycle
    api.approve_reprint(reprint["id"], make_platform_admin_headers())
    partner_headers = make_fulfillment_partner_headers(scenario["partner"]["id"])
    api.mark_in_print(order["id"], partner_headers)
    api.mark_shipped(order["id"], partner_headers)
    delivered = get_success_data(api.mark_delivered(order["id"], partner_headers))

    assert delivered["creator_net_cents"] == 1000, \
        f"Expected final creator_net=1000 (2000-1000), got {delivered['creator_net_cents']}"
    assert delivered["creator_net_cents"] != provisional_net, \
        "Final creator_net must differ from provisional after CONSUMER_FAULT reprint"


# =============================================================================
# Rule 1 — creator_reprint_risk_score incremental vs full_recompute
# =============================================================================

def _cycle_consumer_fault_reprint(scenario, buyer_email: str, hash_suffix: str):
    """Helper: create a new order and take it through capture->ship->fail->reprint->approve
    with CONSUMER_FAULT/DAMAGED. Not exported as a fixture because it is only used inside
    this file to build a bulk-strike scenario.
    """
    order, _ = create_and_capture_order(scenario, item_count=1, buyer_email=buyer_email)
    order, job = advance_order_to_shipped(scenario, order)
    fail_shipped_job(scenario, job)
    from test_helpers.fixtures import _find_job_for_order
    job = _find_job_for_order(order["id"])
    reprint = open_reprint_on_failed_job(
        job, fault_category="CONSUMER_FAULT", reason_code="DAMAGED",
    )
    api_client.approve_reprint(reprint["id"], make_platform_admin_headers())


def test_incremental_variant_reaches_strike_count_four_after_four_approvals(api):
    """PRD §3.8: "The incremental variant fires on each individual approved-consumer-fault
    reprint approval: it adds only that request's weight to the stored
    `reprint_strike_count`, assuming the prior aggregate is still correct."
    PRD §3.8: "Each approved consumer-fault reprint contributes a weight determined
    by its `reason_code`: `DAMAGED` contributes 1, `WRONG_SIZE` contributes 2,
    `MISPRINT` contributes 0 (interpreted as more likely partner-fault-adjacent),
    and `OTHER` contributes 1."

    After 4 CONSUMER_FAULT/DAMAGED reprint approvals within a fresh 90-day window,
    reprint_strike_count == 4 via the incremental variant.

    Design: Difficulty/dual_variant_calc/reprint_risk_score_incremental_vs_full_recompute
    """
    scenario = setup_basic_scenario(
        creator_email="dv3@example.com", display_name="DV3", slug="dv3-sf",
        sku="T-DV3", base_cost_cents=2000, markup_bps=5000,
        file_hash="hash_dv3", clock_iso="2026-06-01T00:00:00Z",
    )
    for i in range(4):
        _cycle_consumer_fault_reprint(scenario, f"buy{i}@x.com", str(i))

    creator = get_success_data(
        api.get_creator(scenario["creator"]["id"], make_platform_admin_headers())
    )
    assert creator["reprint_strike_count"] == 4, \
        f"Expected incremental strike_count=4, got {creator['reprint_strike_count']}"


def test_full_recompute_drops_strikes_outside_ninety_day_window_to_zero(api):
    """PRD §3.8: "The full-recompute variant fires when the ops-run decay endpoint
    is invoked: it walks every creator's trailing-90-day reprint history from
    scratch, drops requests whose `updated_at` has fallen outside the window, and
    rewrites `reprint_strike_count` to the freshly-summed value."
    PRD §3.8: "Only reprint requests whose `status` is `APPROVED`, whose
    `fault_category` is `CONSUMER_FAULT`, and whose `updated_at` falls in the
    trailing 90-day window relative to the current logical clock instant contribute
    to the score."

    After the clock advances 91+ days beyond the reprint approvals, decay-strikes
    walks the fresh window, drops all four now-stale requests, and rewrites the
    count to 0. Divergence from the incremental value (4) is exactly 4.

    Design: Difficulty/dual_variant_calc/reprint_risk_score_incremental_vs_full_recompute
    """
    scenario = setup_basic_scenario(
        creator_email="dv4@example.com", display_name="DV4", slug="dv4-sf",
        sku="T-DV4", base_cost_cents=2000, markup_bps=5000,
        file_hash="hash_dv4", clock_iso="2026-06-01T00:00:00Z",
    )
    for i in range(4):
        _cycle_consumer_fault_reprint(scenario, f"buy_full_{i}@x.com", str(i))

    creator_before = get_success_data(
        api.get_creator(scenario["creator"]["id"], make_platform_admin_headers())
    )
    assert creator_before["reprint_strike_count"] == 4, \
        f"Setup: strike_count should be 4 pre-decay, got {creator_before['reprint_strike_count']}"

    # Advance clock 91+ days past the reprints (all approved at 2026-06-01), then decay.
    set_clock("2026-09-05T00:00:00Z")
    get_success_data(api.decay_strikes(make_platform_admin_headers()))

    creator_after = get_success_data(
        api.get_creator(scenario["creator"]["id"], make_platform_admin_headers())
    )
    assert creator_after["reprint_strike_count"] == 0, \
        f"Expected strike_count=0 after 91-day decay, got {creator_after['reprint_strike_count']}"
    assert creator_after["reprint_strike_count"] != creator_before["reprint_strike_count"], \
        "Full-recompute must diverge from incremental when window shifts"
