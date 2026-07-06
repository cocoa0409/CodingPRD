"""Shipment fulfillment: sourcing gate, allocations, confirm-sourced branches,
stem valuation, cold-chain freshness boundary, stem cost rounding, ship on route,
delivery, loyalty tier, substitution policy.

Covers difficulty rules stem_valuation, shipment_stem_cost, shipment branches,
cold_chain boundary, insufficient_stems boundary, cross-entity source/commit,
resource temporal overlaps, plus multiple corner instances.
"""
from test_helpers import (
    api_client,
    make_customer_headers,
    TEST_USERS,
    validate_error,
    validate_success,
    ApiErrorId,
    setup_plan_customer_subscription,
    setup_sourcing_shipment,
    setup_sourcing_shipment_with_allocation,
    get_subscription_shipments,
    create_stem_lot,
    create_substitution_rule,
    create_carrier_route,
    set_clock,
    source_shipment,
    reserve_allocation,
    confirm_sourced,
    ship,
    deliver,
    pause,
    get_lot,
    get_customer,
    get_subscription,
    create_plan,
    create_customer,
    create_subscription_for,
)
from test_helpers.factories import (
    confirm_sourced_payload,
    ship_shipment_payload,
    create_allocation_payload,
)


# =====================================================================
# Difficulty §1.8: dual_variant_calc.stem_reserved_vs_committed_valuation
# =====================================================================


def test_stem_reserved_value_full_at_reserve_time_age_zero():
    """PRD §3.5: "The `reserved_value_cents` is the base value multiplied by (one minus the shrinkage evaluated at the reservation time), rounded half up; because a lot is usually reserved when very fresh, this is typically the full base value."
    PRD §3.5: "it is 0 when the age is under 24 hours".

    Reserving 20 stems @ 50 cents at reserve_time == sourced_at (age 0h -> shrinkage 0):
    reserved_value_cents = round(20 * 50 * 1.0) = 1000.

    Design: Difficulty/dual_variant_calc/stem_reserved_vs_committed_valuation
    """
    _plan, _customer, _sub, shipment, lot = setup_sourcing_shipment(
        lot_kwargs={
            "quantity_total": 100,
            "unit_cost_cents": 50,
            "sourced_at": "2026-03-04T00:00:00Z",
            "shelf_life_hours": 96,
        },
        clock_at_source="2026-03-04T00:00:00Z",
    )
    allocation = reserve_allocation(
        shipment["id"],
        lot["id"],
        quantity_reserved=20,
        hold_start="2026-03-04T08:00:00Z",
        hold_end="2026-03-04T10:00:00Z",
    )
    assert allocation["reserved_value_cents"] == 1000, (
        f"expected 1000 (full base at age 0); got {allocation['reserved_value_cents']}"
    )


def test_stem_committed_value_shrunk_at_commit_time_after_fresh_hours():
    """PRD §3.5: "The `committed_value_cents`, computed later at commit time, is the base value multiplied by (one minus the shrinkage evaluated at that commit instant), rounded half up; a lot that has aged past 24 hours by commit time therefore loses 15% of its value."

    Reserve at age 0 (value 1000), advance clock to age 48h (>= 24h, lot still FRESH via
    shelf_life 96h), commit -> committed_value_cents = round(20*50*0.85) = 850.

    Design: Difficulty/dual_variant_calc/stem_reserved_vs_committed_valuation
    """
    _plan, _customer, _sub, shipment, lot = setup_sourcing_shipment(
        lot_kwargs={
            "quantity_total": 100,
            "unit_cost_cents": 50,
            "sourced_at": "2026-03-04T00:00:00Z",
            "shelf_life_hours": 96,
        },
        clock_at_source="2026-03-04T00:00:00Z",
    )
    allocation = reserve_allocation(
        shipment["id"],
        lot["id"],
        quantity_reserved=20,
        hold_start="2026-03-04T08:00:00Z",
        hold_end="2026-03-04T10:00:00Z",
    )
    assert allocation["reserved_value_cents"] == 1000
    # Advance clock to age 48h (still fresh; usable_until = sourced_at + 96h = 2026-03-08).
    set_clock("2026-03-06T00:00:00Z")
    confirm_sourced(shipment["id"], substitution_applied=False)
    res = api_client.list_shipment_allocations(
        shipment["id"], TEST_USERS["fulfillment_ops_headers"]
    )
    committed_data = validate_success(res)
    assert committed_data[0]["status"] == "COMMITTED"
    assert committed_data[0]["committed_value_cents"] == 850, (
        f"expected 850 (base 1000 * 0.85); got {committed_data[0]['committed_value_cents']}"
    )


# =====================================================================
# Difficulty §1.8: combinatorial_formula.shipment_stem_cost_line_then_sum_rounding
# =====================================================================


def test_shipment_stem_cost_rounds_per_line_then_sums():
    """PRD §3.5: "The shipment's `stem_cost_cents` is computed by taking each `COMMITTED` allocation in turn, multiplying its `committed_value_cents` by a stem markup of 1.375 and rounding that line half up to whole cents, and then summing those per-line rounded amounts; the rounding is applied per line and only then summed, never by summing first and rounding once."

    Two committed lines each 100 -> round(100*1.375)=round(137.5)=138 per line; sum = 276.
    (Sum-first would give round(200*1.375)=275; per-line-then-sum is 276.)

    Design: Difficulty/combinatorial_formula/shipment_stem_cost_line_then_sum_rounding
    """
    _plan, _customer, _sub, shipment, lot = setup_sourcing_shipment(
        lot_kwargs={
            "quantity_total": 200,
            "unit_cost_cents": 25,
            "sourced_at": "2026-03-04T00:00:00Z",
            "shelf_life_hours": 240,
        },
        clock_at_source="2026-03-04T12:00:00Z",
    )
    # Two allocations, each 4 stems -> base 100 each; age 12h < 24 -> shrinkage 0.
    reserve_allocation(
        shipment["id"], lot["id"],
        quantity_reserved=4,
        hold_start="2026-03-04T13:00:00Z",
        hold_end="2026-03-04T14:00:00Z",
    )
    reserve_allocation(
        shipment["id"], lot["id"],
        quantity_reserved=4,
        hold_start="2026-03-04T15:00:00Z",
        hold_end="2026-03-04T16:00:00Z",
    )
    confirmed = confirm_sourced(shipment["id"], substitution_applied=False)
    assert confirmed["stem_cost_cents"] == 276, (
        f"expected 276 = 138+138 (per-line then sum); got {confirmed['stem_cost_cents']}"
    )


def test_shipment_stem_cost_single_line_exact_markup():
    """PRD §3.5: "multiplying its `committed_value_cents` by a stem markup of 1.375 and rounding that line half up to whole cents".

    Single COMMITTED allocation with committed_value 200 -> round(200*1.375)=round(275.0)=275.

    Design: Difficulty/combinatorial_formula/shipment_stem_cost_line_then_sum_rounding
    """
    _plan, _customer, _sub, shipment, lot = setup_sourcing_shipment(
        lot_kwargs={
            "quantity_total": 100,
            "unit_cost_cents": 25,
            "sourced_at": "2026-03-04T00:00:00Z",
            "shelf_life_hours": 240,
        },
        clock_at_source="2026-03-04T12:00:00Z",
    )
    # 8 stems * 25 = 200 base; age 12h -> shrinkage 0.
    reserve_allocation(
        shipment["id"], lot["id"],
        quantity_reserved=8,
        hold_start="2026-03-04T13:00:00Z",
        hold_end="2026-03-04T14:00:00Z",
    )
    confirmed = confirm_sourced(shipment["id"], substitution_applied=False)
    # round(200 * 1.375) = round(275.0) = 275
    assert confirmed["stem_cost_cents"] == 275


# =====================================================================
# Difficulty §1.8: non_linear_state_machine.shipment_branch_sourced_vs_substituted
# =====================================================================


def test_confirm_sourced_branch_a_no_substitution_flag_stays_false():
    """PRD §3.5: "In the first branch, the operator confirms with `substitution_applied` false: each `RESERVED` allocation moves to `COMMITTED` with its `committed_value_cents` set, the shipment's `stem_cost_cents` is computed, the shipment's `substitution_applied` stays false, and the shipment moves to `SOURCED`."

    Design: Difficulty/non_linear_state_machine/shipment_branch_sourced_vs_substituted
    """
    _plan, _customer, subscription = setup_plan_customer_subscription()
    shipments = get_subscription_shipments(subscription["id"])
    source_shipment(shipments[0]["id"])
    confirmed = confirm_sourced(shipments[0]["id"], substitution_applied=False)
    assert confirmed["status"] == "SOURCED"
    assert confirmed["substitution_applied"] is False


def test_confirm_sourced_branch_b_substituted_with_allowed_rule():
    """PRD §3.5: "In the second branch, the operator confirms with `substitution_applied` true and supplies the `from_variety` and `to_variety` of the substitution; this branch additionally requires that a substitution rule exist for that variety pair with `allowed` true, failing which the request is rejected with `ERR_SUBSTITUTION_NOT_ALLOWED`. When it succeeds, each `RESERVED` allocation likewise moves to `COMMITTED` with its `committed_value_cents` set and the shipment's `stem_cost_cents` is computed, but the shipment's `substitution_applied` is set to true and the shipment moves to `SUBSTITUTED`."

    Design: Difficulty/non_linear_state_machine/shipment_branch_sourced_vs_substituted
    """
    _plan, _customer, subscription = setup_plan_customer_subscription()
    shipments = get_subscription_shipments(subscription["id"])
    create_substitution_rule(from_variety="ROSE", to_variety="TULIP", allowed=True)
    source_shipment(shipments[1]["id"])
    confirmed = confirm_sourced(
        shipments[1]["id"],
        substitution_applied=True,
        from_variety="ROSE",
        to_variety="TULIP",
    )
    assert confirmed["status"] == "SUBSTITUTED"
    assert confirmed["substitution_applied"] is True


# =====================================================================
# Difficulty §1.8: boundary_precision_check.cold_chain_expiry_at_exact_deadline
# =====================================================================


def test_cold_chain_expiry_at_exact_usable_until_blocks_commit():
    """PRD §3.5: "Its `cold_chain_state` is `FRESH` while the logical clock is strictly before `usable_until` and `EXPIRED` once the clock reaches or passes `usable_until` — the boundary instant itself counts as `EXPIRED`."
    PRD §3.5: "in both branches every `RESERVED` allocation on the shipment must belong to a lot that is still `FRESH` at commit time — if any required lot is `EXPIRED`, the confirmation is rejected with `ERR_LOT_EXPIRED`."

    Lot sourced 2026-03-04, shelf_life 48h -> usable_until = 2026-03-06T00:00:00Z.
    At clock exactly 2026-03-06T00:00:00Z the lot is EXPIRED (boundary inclusive).

    Design: Difficulty/boundary_precision_check/cold_chain_expiry_at_exact_deadline
    """
    _plan, _customer, _sub, shipment, lot = setup_sourcing_shipment(
        lot_kwargs={
            "quantity_total": 30,
            "unit_cost_cents": 50,
            "sourced_at": "2026-03-04T00:00:00Z",
            "shelf_life_hours": 48,
        },
        clock_at_source="2026-03-05T00:00:00Z",
    )
    reserve_allocation(
        shipment["id"], lot["id"],
        quantity_reserved=10,
        hold_start="2026-03-05T08:00:00Z",
        hold_end="2026-03-05T10:00:00Z",
    )
    # Advance to exactly usable_until.
    set_clock("2026-03-06T00:00:00Z")
    res = api_client.confirm_sourced_shipment(
        shipment["id"],
        confirm_sourced_payload(substitution_applied=False),
        TEST_USERS["fulfillment_ops_headers"],
    )
    validate_error(res, ApiErrorId.ERR_LOT_EXPIRED.value)
    # Allocation stays RESERVED (commit blocked at the boundary).
    alloc_res = api_client.list_shipment_allocations(
        shipment["id"], TEST_USERS["fulfillment_ops_headers"]
    )
    alloc_data = validate_success(alloc_res)
    assert alloc_data[0]["status"] == "RESERVED"


def test_cold_chain_fresh_just_before_usable_until_commits_successfully():
    """PRD §3.5: "Its `cold_chain_state` is `FRESH` while the logical clock is strictly before `usable_until`".

    Sourced 2026-03-04, shelf_life 48h -> usable_until 2026-03-06T00:00:00Z. At clock
    2026-03-05T23:59:59Z (strictly before usable_until) the lot is FRESH and commit succeeds.

    Design: Difficulty/boundary_precision_check/cold_chain_expiry_at_exact_deadline
    """
    _plan, _customer, _sub, shipment, lot = setup_sourcing_shipment(
        lot_kwargs={
            "quantity_total": 30,
            "unit_cost_cents": 50,
            "sourced_at": "2026-03-04T00:00:00Z",
            "shelf_life_hours": 48,
        },
        clock_at_source="2026-03-05T00:00:00Z",
    )
    reserve_allocation(
        shipment["id"], lot["id"],
        quantity_reserved=10,
        hold_start="2026-03-05T08:00:00Z",
        hold_end="2026-03-05T10:00:00Z",
    )
    # Advance to strictly-before usable_until.
    set_clock("2026-03-05T23:59:59Z")
    confirmed = confirm_sourced(shipment["id"], substitution_applied=False)
    assert confirmed["status"] == "SOURCED"


# =====================================================================
# Difficulty §1.8: boundary_precision_check.insufficient_stems_at_available_boundary
# =====================================================================


def test_reserving_one_more_than_available_returns_insufficient_stems():
    """PRD §3.5: "The reservation is refused with `ERR_INSUFFICIENT_STEMS` if `quantity_reserved` exceeds the lot's current `quantity_available`".

    Lot total 10; requesting 11 exceeds available.

    Design: Difficulty/boundary_precision_check/insufficient_stems_at_available_boundary
    """
    _plan, _customer, _sub, shipment, lot = setup_sourcing_shipment(
        lot_kwargs={
            "quantity_total": 10,
            "unit_cost_cents": 40,
            "sourced_at": "2026-03-04T00:00:00Z",
            "shelf_life_hours": 240,
        },
        clock_at_source="2026-03-04T12:00:00Z",
    )
    res = api_client.create_shipment_allocation(
        shipment["id"],
        create_allocation_payload(
            lot_id=lot["id"],
            quantity_reserved=11,
            hold_start="2026-03-04T13:00:00Z",
            hold_end="2026-03-04T14:00:00Z",
        ),
        TEST_USERS["fulfillment_ops_headers"],
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_STEMS.value)


def test_reserving_exact_available_succeeds_and_drives_availability_to_zero():
    """PRD §3.5: "A successful reservation creates a `StemAllocation` in `RESERVED` status whose `shipment_id` ties it to the consuming shipment, debits the lot's `quantity_available` by `quantity_reserved`".

    Lot total 10; reserving exactly 10 (== available) succeeds; quantity_available -> 0.

    Design: Difficulty/boundary_precision_check/insufficient_stems_at_available_boundary
    """
    _plan, _customer, _sub, shipment, lot = setup_sourcing_shipment(
        lot_kwargs={
            "quantity_total": 10,
            "unit_cost_cents": 40,
            "sourced_at": "2026-03-04T00:00:00Z",
            "shelf_life_hours": 240,
        },
        clock_at_source="2026-03-04T12:00:00Z",
    )
    reserve_allocation(
        shipment["id"], lot["id"],
        quantity_reserved=10,
        hold_start="2026-03-04T15:00:00Z",
        hold_end="2026-03-04T16:00:00Z",
    )
    lot_after = get_lot(lot["id"])
    assert lot_after["quantity_available"] == 0


# =====================================================================
# Difficulty §1.8: cross_entity_state_dependency.source_requires_subscription_active
# =====================================================================


def test_source_paused_subscription_shipment_returns_subscription_not_active():
    """PRD §3.5: "An operator starts sourcing a `SCHEDULED` shipment, advancing it to `SOURCING`, but only while the shipment's subscription is simultaneously `ACTIVE` on its lifecycle axis and `CURRENT` on its billing axis; if the subscription is not in that combined state, the attempt is rejected with `ERR_SUBSCRIPTION_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/source_requires_subscription_active
    """
    _plan, customer, subscription = setup_plan_customer_subscription()
    shipments = get_subscription_shipments(subscription["id"])
    pause(subscription["id"], customer["id"])
    res = api_client.source_shipment(
        shipments[0]["id"], {}, TEST_USERS["fulfillment_ops_headers"]
    )
    validate_error(res, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE.value)


def test_source_paused_subscription_rejects_every_scheduled_shipment():
    """PRD §3.5: "An operator starts sourcing a `SCHEDULED` shipment, advancing it to `SOURCING`, but only while the shipment's subscription is simultaneously `ACTIVE` on its lifecycle axis and `CURRENT` on its billing axis; if the subscription is not in that combined state, the attempt is rejected with `ERR_SUBSCRIPTION_NOT_ACTIVE`."

    The cross-entity precondition is on the subscription, not on a specific shipment index;
    sourcing shipment[2] while the subscription is PAUSED must return the same error as
    sourcing shipment[0] (already covered).

    Design: Difficulty/cross_entity_state_dependency/source_requires_subscription_active
    """
    _plan, customer, subscription = setup_plan_customer_subscription()
    shipments = get_subscription_shipments(subscription["id"])
    pause(subscription["id"], customer["id"])
    res = api_client.source_shipment(
        shipments[2]["id"], {}, TEST_USERS["fulfillment_ops_headers"]
    )
    validate_error(res, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE.value)


# =====================================================================
# Difficulty §1.8: cross_entity_state_dependency.commit_requires_lot_fresh
# =====================================================================


def test_commit_with_clearly_expired_lot_returns_lot_expired_and_keeps_reserved():
    """PRD §3.5: "in both branches every `RESERVED` allocation on the shipment must belong to a lot that is still `FRESH` at commit time — if any required lot is `EXPIRED`, the confirmation is rejected with `ERR_LOT_EXPIRED`."

    Lot usable_until 2026-03-06; advance clock past to 2026-03-08 — clearly EXPIRED.

    Design: Difficulty/cross_entity_state_dependency/commit_requires_lot_fresh
    """
    _plan, _customer, _sub, shipment, lot = setup_sourcing_shipment(
        lot_kwargs={
            "quantity_total": 30,
            "unit_cost_cents": 50,
            "sourced_at": "2026-03-04T00:00:00Z",
            "shelf_life_hours": 48,
        },
        clock_at_source="2026-03-05T00:00:00Z",
    )
    reserve_allocation(
        shipment["id"], lot["id"],
        quantity_reserved=10,
        hold_start="2026-03-05T08:00:00Z",
        hold_end="2026-03-05T10:00:00Z",
    )
    set_clock("2026-03-08T00:00:00Z")
    lot_now = get_lot(lot["id"])
    assert lot_now["cold_chain_state"] == "EXPIRED"
    res = api_client.confirm_sourced_shipment(
        shipment["id"],
        confirm_sourced_payload(substitution_applied=False),
        TEST_USERS["fulfillment_ops_headers"],
    )
    validate_error(res, ApiErrorId.ERR_LOT_EXPIRED.value)
    alloc_res = api_client.list_shipment_allocations(
        shipment["id"], TEST_USERS["fulfillment_ops_headers"]
    )
    alloc_data = validate_success(alloc_res)
    assert alloc_data[0]["status"] == "RESERVED"


def test_commit_lot_fresh_at_commit_time_moves_allocation_to_committed():
    """PRD §3.5: "each `RESERVED` allocation moves to `COMMITTED` with its `committed_value_cents` set, the shipment's `stem_cost_cents` is computed, the shipment's `substitution_applied` stays false, and the shipment moves to `SOURCED`."

    With a still-FRESH lot at commit time, the allocation transitions RESERVED -> COMMITTED.

    Design: Difficulty/cross_entity_state_dependency/commit_requires_lot_fresh
    """
    _plan, _customer, _sub, shipment, lot = setup_sourcing_shipment(
        lot_kwargs={
            "quantity_total": 30,
            "unit_cost_cents": 50,
            "sourced_at": "2026-03-04T00:00:00Z",
            "shelf_life_hours": 240,
        },
        clock_at_source="2026-03-05T00:00:00Z",
    )
    reserve_allocation(
        shipment["id"], lot["id"],
        quantity_reserved=10,
        hold_start="2026-03-05T08:00:00Z",
        hold_end="2026-03-05T10:00:00Z",
    )
    confirmed = confirm_sourced(shipment["id"], substitution_applied=False)
    assert confirmed["status"] == "SOURCED"
    alloc_res = api_client.list_shipment_allocations(
        shipment["id"], TEST_USERS["fulfillment_ops_headers"]
    )
    alloc_data = validate_success(alloc_res)
    assert alloc_data[0]["status"] == "COMMITTED"


# =====================================================================
# Difficulty §1.8: resource_temporal_overlap.route_window_half_open_overlap_adjacency_ok
# =====================================================================


def test_route_window_true_overlap_rejected():
    """PRD §3.6: "The window is treated as half-open, and it must not overlap the window of any other shipment already `SHIPPED` on the same route; because the interval is half-open, two windows that merely touch at a shared endpoint are considered adjacent and are allowed, but any true overlap is rejected with `ERR_ROUTE_WINDOW_CONFLICT`."

    First shipment books [09:00, 11:00); second's [10:00, 12:00) truly overlaps.

    Design: Difficulty/resource_temporal_overlap/route_window_half_open_overlap_adjacency_ok
    """
    _plan, _customer, subscription = setup_plan_customer_subscription()
    shipments = get_subscription_shipments(subscription["id"])
    route = create_carrier_route(zone="Z1", service_date="2026-03-10T00:00:00Z")
    # Source and commit two shipments.
    source_shipment(shipments[0]["id"])
    confirm_sourced(shipments[0]["id"], substitution_applied=False)
    source_shipment(shipments[1]["id"])
    confirm_sourced(shipments[1]["id"], substitution_applied=False)
    # First ship succeeds.
    first = ship(
        shipments[0]["id"], route["id"],
        "2026-03-10T09:00:00Z", "2026-03-10T11:00:00Z",
    )
    assert first["status"] == "SHIPPED"
    # Second overlaps.
    res = api_client.ship_shipment(
        shipments[1]["id"],
        ship_shipment_payload(
            route_id=route["id"],
            delivery_window_start="2026-03-10T10:00:00Z",
            delivery_window_end="2026-03-10T12:00:00Z",
        ),
        TEST_USERS["fulfillment_ops_headers"],
    )
    validate_error(res, ApiErrorId.ERR_ROUTE_WINDOW_CONFLICT.value)


def test_route_window_adjacent_at_shared_endpoint_allowed():
    """PRD §3.6: "because the interval is half-open, two windows that merely touch at a shared endpoint are considered adjacent and are allowed".

    First shipment [09:00, 11:00); a second at [11:00, 12:00) is adjacent -> accepted.

    Design: Difficulty/resource_temporal_overlap/route_window_half_open_overlap_adjacency_ok
    """
    _plan, _customer, subscription = setup_plan_customer_subscription()
    shipments = get_subscription_shipments(subscription["id"])
    route = create_carrier_route(zone="Z1", service_date="2026-03-10T00:00:00Z")
    source_shipment(shipments[0]["id"])
    confirm_sourced(shipments[0]["id"], substitution_applied=False)
    source_shipment(shipments[2]["id"])
    confirm_sourced(shipments[2]["id"], substitution_applied=False)
    ship(shipments[0]["id"], route["id"], "2026-03-10T09:00:00Z", "2026-03-10T11:00:00Z")
    # Adjacent [11:00, 12:00).
    adjacent = ship(
        shipments[2]["id"], route["id"],
        "2026-03-10T11:00:00Z", "2026-03-10T12:00:00Z",
    )
    assert adjacent["status"] == "SHIPPED"


# =====================================================================
# Difficulty §1.8: resource_temporal_overlap.lot_hold_closed_interval_buffer_overlap
# =====================================================================


def test_lot_hold_within_clean_buffer_rejected():
    """PRD §3.5: "refused with `ERR_LOT_HOLD_CONFLICT` if the requested hold window collides with another active hold on the same lot — where a collision means the two closed hold intervals overlap or lie within a 30-minute clean buffer of each other."

    First hold [08:00, 10:00]; second [10:15, 11:00] leaves a 15-min gap (< 30) -> conflict.

    Design: Difficulty/resource_temporal_overlap/lot_hold_closed_interval_buffer_overlap
    """
    _plan, _customer, _sub, shipment, lot = setup_sourcing_shipment(
        lot_kwargs={
            "quantity_total": 100,
            "unit_cost_cents": 40,
            "sourced_at": "2026-03-04T00:00:00Z",
            "shelf_life_hours": 240,
        },
        clock_at_source="2026-03-05T00:00:00Z",
    )
    reserve_allocation(
        shipment["id"], lot["id"],
        quantity_reserved=5,
        hold_start="2026-03-05T08:00:00Z",
        hold_end="2026-03-05T10:00:00Z",
    )
    res = api_client.create_shipment_allocation(
        shipment["id"],
        create_allocation_payload(
            lot_id=lot["id"],
            quantity_reserved=5,
            hold_start="2026-03-05T10:15:00Z",
            hold_end="2026-03-05T11:00:00Z",
        ),
        TEST_USERS["fulfillment_ops_headers"],
    )
    validate_error(res, ApiErrorId.ERR_LOT_HOLD_CONFLICT.value)


# =====================================================================
# Corner: skip_non_scheduled_invalid — state gate
# =====================================================================


def test_skip_from_sourcing_returns_shipment_not_skippable():
    """PRD §3.4: "A skip is only legal while the shipment is still `SCHEDULED`; attempting it on a shipment in any other status is rejected with `ERR_SHIPMENT_NOT_SKIPPABLE`."

    Design: Corner/state_machines/corner_skip_non_scheduled_invalid
    """
    _plan, customer, subscription = setup_plan_customer_subscription()
    shipments = get_subscription_shipments(subscription["id"])
    source_shipment(shipments[2]["id"])
    res = api_client.skip_shipment(
        shipments[2]["id"], {}, make_customer_headers(customer["id"])
    )
    validate_error(res, ApiErrorId.ERR_SHIPMENT_NOT_SKIPPABLE.value)


# =====================================================================
# Corner: cold_chain_usable_until_computed
# =====================================================================


def test_stem_lot_usable_until_and_fresh_default_clock():
    """PRD §3.5: "The lot's `usable_until` is its `sourced_at` plus its `shelf_life_hours`. Its `cold_chain_state` is `FRESH` while the logical clock is strictly before `usable_until`".
    PRD §2.6: "On server startup the clock reads exactly `2026-03-01T00:00:00Z`".

    sourced 2026-03-04, shelf_life 48h -> usable_until 2026-03-06; clock (default 2026-03-01) < usable_until -> FRESH.

    Design: Corner/calculations/corner_cold_chain_usable_until_computed
    """
    lot = create_stem_lot(
        variety="ROSE", grade="A",
        quantity_total=50, unit_cost_cents=40,
        sourced_at="2026-03-04T00:00:00Z", shelf_life_hours=48,
    )
    fetched = get_lot(lot["id"])
    # Compare ISO instants at second granularity; server may include ".000Z".
    assert fetched["usable_until"].startswith("2026-03-06T00:00:00")
    assert fetched["cold_chain_state"] == "FRESH"


# =====================================================================
# Corner: substitution_not_allowed
# =====================================================================


def test_confirm_sourced_substitution_without_allowed_rule_rejected():
    """PRD §3.5: "this branch additionally requires that a substitution rule exist for that variety pair with `allowed` true, failing which the request is rejected with `ERR_SUBSTITUTION_NOT_ALLOWED`."

    Design: Corner/validations/corner_substitution_not_allowed
    """
    _plan, _customer, subscription = setup_plan_customer_subscription()
    shipments = get_subscription_shipments(subscription["id"])
    source_shipment(shipments[0]["id"])
    res = api_client.confirm_sourced_shipment(
        shipments[0]["id"],
        confirm_sourced_payload(
            substitution_applied=True, from_variety="ROSE", to_variety="LILY"
        ),
        TEST_USERS["fulfillment_ops_headers"],
    )
    validate_error(res, ApiErrorId.ERR_SUBSTITUTION_NOT_ALLOWED.value)


# =====================================================================
# Corner: loyalty_tier_silver_after_two_deliveries
# =====================================================================


def test_loyalty_tier_silver_after_two_deliveries():
    """PRD §3.6: "Marking a `SHIPPED` shipment delivered advances it to `DELIVERED`, the terminal fulfilled state. Delivery is what grows loyalty: it increments the owning customer's `lifetime_cycles` by one and recomputes the customer's `loyalty_tier` from the new count using the `BRONZE`/`SILVER`/`GOLD` thresholds of §3.1."
    PRD §3.1: "The loyalty tier is `BRONZE` while the customer has fewer than two delivered cycles, becomes `SILVER` once delivered cycles reach two and while they remain below five".

    Design: Corner/entities/corner_loyalty_tier_silver_after_two_deliveries
    """
    _plan, customer, subscription = setup_plan_customer_subscription()
    shipments = get_subscription_shipments(subscription["id"])
    route = create_carrier_route(zone="Z1", service_date="2026-03-10T00:00:00Z")
    # Clock at 2026-03-04T12:00:00Z gives a FRESH default lot (implicit — no lots are used
    # here since we commit without allocations). Advance clock so downstream calls treat
    # the default lot as fresh; commit with zero allocations is legal per §3.5 (sum over
    # an empty set of COMMITTED allocations = 0 stem_cost_cents).
    set_clock("2026-03-04T12:00:00Z")
    for idx, window in [
        (0, ("2026-03-10T09:00:00Z", "2026-03-10T10:00:00Z")),
        (1, ("2026-03-10T10:00:00Z", "2026-03-10T11:00:00Z")),
    ]:
        sh = shipments[idx]
        source_shipment(sh["id"])
        confirm_sourced(sh["id"], substitution_applied=False)
        ship(sh["id"], route["id"], window[0], window[1])
        deliver(sh["id"])
    fetched = get_customer(customer["id"])
    assert fetched["lifetime_cycles"] == 2
    assert fetched["loyalty_tier"] == "SILVER"
