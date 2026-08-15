"""Production orders: pricing tiers, allocation, QC gate, fulfillment (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    assert_production_order,
    assert_foam_mass_conservation,
    create_production_order_payload,
    create_shipment_payload,
    create_retailer_account,
    setup_active_model,
    setup_active_label,
    setup_planned_order,
    setup_complete_order,
    setup_cured_batch,
    create_poured_batch,
    place_order,
    allocate_order,
    qc_pass_order,
    make_retailer_headers,
)

PM = TEST_USERS["plant_manager_headers"]
LS1 = TEST_USERS["line_supervisor_headers"]
QC1 = TEST_USERS["qc_inspector_headers"]
LOG1 = TEST_USERS["logistics_headers"]


def test_order_fee_tier_keyed_on_subtotal_below_boundary(api):
    """PRD §3.7: "First, `subtotal_cents` is `quantity` multiplied by
    `unit_price_cents`. Second, `compliance_fee_cents` is tiered on that
    subtotal: a subtotal under 100,000 cents carries a 500-cent fee; a
    subtotal of at least 100,000 cents but under 500,000 cents carries 1,500
    cents; a subtotal of 500,000 cents or more carries 3,000 cents. Both tier
    boundaries are inclusive of the tier they open. Third, `total_cents` is
    the subtotal plus the fee. The tier is always keyed on the subtotal before
    the fee is added — never on the total."

    Design: Difficulty/combinatorial_formula/order_fee_tier_keyed_on_subtotal_not_total
    """
    retailer = create_retailer_account()
    ctx = setup_active_model()
    order = validate_success(api.create_production_order(
        create_production_order_payload(
            model_id=ctx["model"]["id"], retailer_id=retailer["id"],
            destination_state_code="NV", quantity=10, unit_price_cents=9999,
        ),
        PM,
    ), expected_status=201)
    assert_production_order(order)
    assert order["subtotal_cents"] == 99990
    # Subtotal 99990 stays in tier 1 even though total 100490 crosses 100000.
    assert order["compliance_fee_cents"] == 500
    assert order["total_cents"] == 100490


def test_order_fee_tier_boundary_inclusive_at_100000(api):
    """PRD §3.7: "Second, `compliance_fee_cents` is tiered on that subtotal: a
    subtotal under 100,000 cents carries a 500-cent fee; a subtotal of at
    least 100,000 cents but under 500,000 cents carries 1,500 cents; a
    subtotal of 500,000 cents or more carries 3,000 cents. Both tier
    boundaries are inclusive of the tier they open."

    Design: Difficulty/combinatorial_formula/order_fee_tier_keyed_on_subtotal_not_total
    """
    retailer = create_retailer_account()
    ctx = setup_active_model()
    order = validate_success(api.create_production_order(
        create_production_order_payload(
            model_id=ctx["model"]["id"], retailer_id=retailer["id"],
            destination_state_code="NV", quantity=10, unit_price_cents=10000,
        ),
        PM,
    ), expected_status=201)
    assert order["subtotal_cents"] == 100000
    assert order["compliance_fee_cents"] == 1500
    assert order["total_cents"] == 101500


def test_allocate_materials_rejected_while_batch_curing(api):
    """PRD §3.7: "A `LineSupervisor` names the `foam_batch_id` to draw from;
    that batch must be `CURED` (`ERR_BATCH_NOT_CURED`) and its
    `available_mass_kg` must be at least the order's `foam_mass_required_kg`
    — otherwise the allocation is rejected with `ERR_INSUFFICIENT_FOAM_MASS`
    (402)."

    Design: Difficulty/cross_entity_state_dependency/allocate_requires_batch_cured
    """
    ctx = setup_planned_order(state_code="NV", quantity=1, foam_mass_required_kg=10)
    batch = create_poured_batch(chamber_id="CH-1", poured_mass_kg=1000)
    get_success_data(api.start_cure(batch["id"], {"ambient_temp_c": 20}, LS1))

    resp = api.allocate_materials(ctx["order"]["id"], {"foam_batch_id": batch["id"]}, LS1)
    validate_error(resp, ApiErrorId.ERR_BATCH_NOT_CURED)


def test_allocate_materials_succeeds_once_batch_cured(api):
    """PRD §3.7: "Allocating materials moves `PLANNED` → `MATERIAL_ALLOCATED`
    (an order not in `PLANNED` answers `ERR_ORDER_NOT_PLANNED`)."
    PRD §3.7: "A `LineSupervisor` names the `foam_batch_id` to draw from; that
    batch must be `CURED` (`ERR_BATCH_NOT_CURED`) and its `available_mass_kg`
    must be at least the order's `foam_mass_required_kg` — otherwise the
    allocation is rejected with `ERR_INSUFFICIENT_FOAM_MASS` (402)."
    PRD §3.7: "The required mass moves out of `available_mass_kg` and into
    `reserved_mass_kg` on the batch, preserving the conservation invariant."

    Design: Difficulty/cross_entity_state_dependency/allocate_requires_batch_cured
    """
    ctx = setup_planned_order(state_code="NV", quantity=1, foam_mass_required_kg=10)
    batch = create_poured_batch(chamber_id="CH-1", poured_mass_kg=1000)
    get_success_data(api.start_cure(batch["id"], {"ambient_temp_c": 20}, LS1))
    get_success_data(api.set_clock("2026-08-02T00:00:00Z", PM))
    get_success_data(api.certify_cured(batch["id"], QC1))

    allocated = validate_success(
        api.allocate_materials(ctx["order"]["id"], {"foam_batch_id": batch["id"]}, LS1)
    )
    assert allocated["production_status"] == "MATERIAL_ALLOCATED"
    assert allocated["foam_batch_id"] == batch["id"]

    reloaded = get_success_data(api.get_foam_batch(batch["id"], PM))
    assert reloaded["available_mass_kg"] == 990
    assert reloaded["reserved_mass_kg"] == 10
    assert_foam_mass_conservation(reloaded)


def test_allocate_beyond_available_mass_rejected(api):
    """PRD §3.7: "its `available_mass_kg` must be at least the order's
    `foam_mass_required_kg` — otherwise the allocation is rejected with
    `ERR_INSUFFICIENT_FOAM_MASS` (402)."

    Design: Corner/validations/allocate_beyond_available_mass_rejected
    """
    ctx = setup_planned_order(state_code="NV", quantity=20, foam_mass_required_kg=2000)
    batch = setup_cured_batch(poured_mass_kg=1000)

    resp = api.allocate_materials(ctx["order"]["id"], {"foam_batch_id": batch["id"]}, LS1)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FOAM_MASS)

    reloaded = get_success_data(api.get_foam_batch(batch["id"], PM))
    assert reloaded["available_mass_kg"] == 1000
    assert reloaded["reserved_mass_kg"] == 0


def test_drop_ship_order_requires_retailer_flag(api):
    """PRD §3.7: "A `DROP_SHIP` order requires the retailer's
    `drop_ship_enabled` flag (`ERR_DROPSHIP_NOT_ENABLED`, 409)."

    Design: Corner/validations/dropship_order_rejected_when_flag_off
    """
    retailer = create_retailer_account(drop_ship_enabled=False)
    ctx = setup_active_model()

    denied = api.create_production_order(
        create_production_order_payload(
            model_id=ctx["model"]["id"], retailer_id=retailer["id"],
            destination_state_code="NV", ship_method="DROP_SHIP",
        ),
        PM,
    )
    validate_error(denied, ApiErrorId.ERR_DROPSHIP_NOT_ENABLED)

    allowed = validate_success(api.create_production_order(
        create_production_order_payload(
            model_id=ctx["model"]["id"], retailer_id=retailer["id"],
            destination_state_code="NV", ship_method="WAREHOUSE",
        ),
        PM,
    ), expected_status=201)
    assert allowed["production_status"] == "PLANNED"


def test_retailer_order_for_other_retailer_rejected(api):
    """PRD §3.7: "A `Retailer` caller must pass its own id as `retailer_id`;
    referencing any other retailer is rejected with
    `ERR_RETAILER_IDENTITY_MISMATCH` (422)."
    PRD §2.1: "When `X-User-Role` is `Retailer`, `X-User-ID` is the `id` of
    the acting `Retailer`; ownership checks on any resource that references a
    `Retailer` compare the resource's foreign-key field to `X-User-ID`."

    Design: Corner/validations/retailer_identity_mismatch_on_order_create
    """
    retailer_a = create_retailer_account(retailer_name="RA")
    retailer_b = create_retailer_account(retailer_name="RB")
    ctx = setup_active_model()

    resp = api.create_production_order(
        create_production_order_payload(
            model_id=ctx["model"]["id"], retailer_id=retailer_b["id"],
            destination_state_code="NV",
        ),
        make_retailer_headers(retailer_a["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RETAILER_IDENTITY_MISMATCH)


def test_qc_hold_release_cycle_then_pass(api):
    """PRD §3.7: "Passing moves `QC_PENDING` → `COMPLETE`; holding moves
    `QC_PENDING` → `QC_HOLD`; both are guarded by `ERR_ORDER_NOT_QC_PENDING`.
    Releasing a hold returns `QC_HOLD` → `QC_PENDING` (`ERR_ORDER_NOT_QC_HOLD`)."

    Design: Corner/state_machines/qc_hold_release_cycle_then_pass
    """
    ctx = setup_complete_order(state_code="CA", quantity=1, foam_mass_required_kg=10)
    order_id = ctx["order"]["id"]
    assert ctx["order"]["production_status"] == "QC_PENDING"

    held = validate_success(api.qc_hold_order(order_id, QC1))
    assert held["production_status"] == "QC_HOLD"
    released = validate_success(api.qc_release_order(order_id, QC1))
    assert released["production_status"] == "QC_PENDING"
    passed = validate_success(api.qc_pass_order(order_id, QC1))
    assert passed["production_status"] == "COMPLETE"


def test_partial_dispatch_marks_order_partially_shipped(api):
    """PRD §3.8: "Otherwise, if at least one unit has shipped, it is
    `PARTIALLY_SHIPPED`; if none have, `UNFULFILLED`."
    PRD §3.8: "Dispatching a shipment (moving it `CREATED` → `DISPATCHED`;
    guarded by `ERR_SHIPMENT_NOT_CREATED`) moves every unit it carries from
    `MANUFACTURED` to `SHIPPED` and recomputes the parent order's
    `fulfillment_status`."

    Design: Difficulty/non_linear_state_machine/production_order_parallel_fulfillment_dimension
    """
    ctx = setup_complete_order(state_code="CA", quantity=2, foam_mass_required_kg=20,
                               ship_method="DROP_SHIP")
    qc_pass_order(ctx)
    assert ctx["order"]["production_status"] == "COMPLETE"
    assert ctx["order"]["fulfillment_status"] == "UNFULFILLED"

    u1, u2 = ctx["units"][0]["id"], ctx["units"][1]["id"]
    shipment = get_success_data(api.create_shipment(
        create_shipment_payload(order_id=ctx["order"]["id"], unit_ids=[u1]), LOG1
    ))
    get_success_data(api.dispatch_shipment(shipment["id"], LOG1))

    order = get_success_data(api.get_production_order(ctx["order"]["id"], PM))
    assert order["production_status"] == "COMPLETE", (
        "Dispatch must not disturb the parallel production dimension"
    )
    assert order["fulfillment_status"] == "PARTIALLY_SHIPPED"


def test_full_delivery_marks_order_delivered(api):
    """PRD §3.8: "If the delivered count equals `quantity`, fulfillment is
    `DELIVERED`. Otherwise, if the shipped count equals `quantity`,
    fulfillment is `FULLY_SHIPPED`. Otherwise, if at least one unit has
    shipped, it is `PARTIALLY_SHIPPED`; if none have, `UNFULFILLED`."

    Design: Difficulty/non_linear_state_machine/production_order_parallel_fulfillment_dimension
    """
    ctx = setup_complete_order(state_code="CA", quantity=2, foam_mass_required_kg=20,
                               ship_method="DROP_SHIP")
    qc_pass_order(ctx)
    u1, u2 = ctx["units"][0]["id"], ctx["units"][1]["id"]

    s1 = get_success_data(api.create_shipment(
        create_shipment_payload(order_id=ctx["order"]["id"], unit_ids=[u1]), LOG1
    ))
    get_success_data(api.dispatch_shipment(s1["id"], LOG1))
    s2 = get_success_data(api.create_shipment(
        create_shipment_payload(order_id=ctx["order"]["id"], unit_ids=[u2]), LOG1
    ))
    get_success_data(api.dispatch_shipment(s2["id"], LOG1))

    order = get_success_data(api.get_production_order(ctx["order"]["id"], PM))
    assert order["fulfillment_status"] == "FULLY_SHIPPED"

    get_success_data(api.deliver_shipment(s1["id"], LOG1))
    delivered_s2 = validate_success(api.deliver_shipment(s2["id"], LOG1))
    assert delivered_s2["status"] == "DELIVERED"

    order = get_success_data(api.get_production_order(ctx["order"]["id"], PM))
    assert order["fulfillment_status"] == "DELIVERED", (
        "Once every unit is DELIVERED the order's fulfillment must be DELIVERED"
    )


def test_cancel_releases_reserved_foam_exactly(api):
    """PRD §3.7: "Cancelling an allocated order releases its foam reservation:
    `reserved_mass_kg` decreases by the required amount and
    `available_mass_kg` increases by the same, keeping the batch's mass ledger
    whole."
    PRD §2.6: "Foam mass obeys a conservation invariant on every batch: at all
    times, `poured_mass_kg` equals the sum of `available_mass_kg`,
    `reserved_mass_kg`, `consumed_mass_kg`, and `scrapped_mass_kg`."

    Design: Difficulty/compensating_invariant/foam_mass_conservation
    """
    retailer = create_retailer_account()
    ctx = setup_active_label(state_code="NV")
    batch = setup_cured_batch(poured_mass_kg=100)
    order = place_order(ctx["model"]["id"], retailer["id"], state_code="NV",
                        quantity=3, foam_mass_required_kg=30)
    allocate_order(order["id"], batch["id"])

    after_alloc = get_success_data(api.get_foam_batch(batch["id"], PM))
    assert after_alloc["available_mass_kg"] == 70
    assert after_alloc["reserved_mass_kg"] == 30
    assert_foam_mass_conservation(after_alloc)

    get_success_data(api.cancel_order(order["id"], PM))
    after_cancel = get_success_data(api.get_foam_batch(batch["id"], PM))
    assert after_cancel["available_mass_kg"] == 100
    assert after_cancel["reserved_mass_kg"] == 0
    assert_foam_mass_conservation(after_cancel)


def test_start_production_converts_reserved_to_consumed(api):
    """PRD §3.7: "On success the reserved mass converts — `reserved_mass_kg`
    decreases by the required amount and `consumed_mass_kg` increases by the
    same — and if the batch is thereby fully drained (zero available and zero
    reserved), it auto-transitions `CURED` → `CONSUMED` as described in §3.5."
    PRD §2.6: "Foam mass obeys a conservation invariant on every batch: at all
    times, `poured_mass_kg` equals the sum of `available_mass_kg`,
    `reserved_mass_kg`, `consumed_mass_kg`, and `scrapped_mass_kg`."

    Design: Difficulty/compensating_invariant/foam_mass_conservation
    """
    retailer = create_retailer_account()
    ctx = setup_active_label(state_code="NV")
    batch = setup_cured_batch(poured_mass_kg=100)
    order = place_order(ctx["model"]["id"], retailer["id"], state_code="NV",
                        quantity=2, foam_mass_required_kg=25)
    allocate_order(order["id"], batch["id"])
    get_success_data(api.start_production(order["id"], LS1))

    after_start = get_success_data(api.get_foam_batch(batch["id"], PM))
    assert after_start["available_mass_kg"] == 75
    assert after_start["reserved_mass_kg"] == 0
    assert after_start["consumed_mass_kg"] == 25
    assert after_start["scrapped_mass_kg"] == 0
    assert_foam_mass_conservation(after_start)


def test_allocate_response_and_batch_read_reflect_reservation_immediately(api):
    """PRD §3.7: "Allocating materials moves `PLANNED` → `MATERIAL_ALLOCATED`
    (an order not in `PLANNED` answers `ERR_ORDER_NOT_PLANNED`)."
    PRD §3.7: "The required mass moves out of `available_mass_kg` and into
    `reserved_mass_kg` on the batch, preserving the conservation invariant."

    Design: Corner/consistency_model/immediate_read_after_allocate_reflects_reservation
    """
    ctx = setup_planned_order(state_code="NV", quantity=4, foam_mass_required_kg=40)
    batch = setup_cured_batch(poured_mass_kg=1000)

    allocated = validate_success(
        api.allocate_materials(ctx["order"]["id"], {"foam_batch_id": batch["id"]}, LS1)
    )
    assert allocated["production_status"] == "MATERIAL_ALLOCATED"

    batch_now = get_success_data(api.get_foam_batch(batch["id"], PM))
    assert batch_now["available_mass_kg"] == 960
    assert batch_now["reserved_mass_kg"] == 40


def test_order_list_filters_by_retailer(api):
    """PRD §3.7: "Order lists filter by `model_id`, `retailer_id`,
    `foam_batch_id`, `production_status`, and `fulfillment_status`."

    Design: Corner/endpoints/filtered_list_returns_matching_subset
    """
    retailer_a = create_retailer_account(retailer_name="RA")
    retailer_b = create_retailer_account(retailer_name="RB")
    ctx = setup_active_model()
    place_order(ctx["model"]["id"], retailer_a["id"], state_code="NV", quantity=1)
    place_order(ctx["model"]["id"], retailer_b["id"], state_code="NV", quantity=2,
                foam_mass_required_kg=20)

    data, meta = validate_paginated(
        api.list_production_orders(PM, params={"retailer_id": retailer_b["id"]})
    )
    assert len(data) == 1
    assert meta["total_count"] == 1
    assert data[0]["retailer_id"] == retailer_b["id"]


def test_qc_inspector_cannot_cancel_order(api):
    """PRD §2.1: "If the caller's role is well-formed but not in the endpoint's
    authorized role list, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."
    PRD §4: POST /plant/production-orders/{orderId}/cancel is authorized for
    PlantManager only.

    Design: Corner/rbac/qc_inspector_cannot_cancel_order
    """
    ctx = setup_planned_order(state_code="NV", quantity=1)
    resp = api.cancel_order(ctx["order"]["id"], QC1)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    order = get_success_data(api.get_production_order(ctx["order"]["id"], PM))
    assert order["production_status"] == "PLANNED"


def test_units_list_paginates_with_limit_and_total(api):
    """PRD §2.3: "Every list endpoint accepts two query parameters: `limit`
    and `offset`. The `limit` parameter defaults to 10, with a minimum of 1
    and a maximum of 100. The `offset` parameter defaults to 0. List results
    are always sorted by `created_at` in ascending order. List responses carry
    the pagination fields `limit`, `offset`, `total_count`, and `has_more`
    inside the `meta` object, alongside `api_request_id` and
    `api_request_timestamp`."

    Design: Corner/entities/unit_list_pagination_envelope
    """
    ctx = setup_complete_order(state_code="CA", quantity=4, foam_mass_required_kg=40)
    assert len(ctx["units"]) == 4

    data, meta = validate_paginated(api.list_units(PM, params={"limit": 2, "offset": 0}))
    assert len(data) == 2
    assert meta["total_count"] == 4
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0
