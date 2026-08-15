"""Shipment pipeline: fulfillment ledger, spoilage, handling window, stock age,
and cross-entity batch/lot gates."""
from datetime import datetime, timedelta

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    is_valid_uuid, ApiErrorId, TEST_USERS,
    create_seed_zone, create_seed_lot, create_crop_batch, sow_batch, lift_batch,
    setup_graded_batch, setup_confirmed_order, setup_ready_world,
    create_storage_unit, create_placement, create_landowner,
    create_contract, record_site_prep, verify_site_prep, mark_ready,
    create_crew, create_assignment, confirm_assignment, start_planting,
    set_clock,
)

NM = TEST_USERS["nursery_manager_headers"]
CO = TEST_USERS["contract_officer_headers"]
FA = TEST_USERS["field_auditor_headers"]


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_shipment_side_effects_order_fulfillment(api):
    """PRD §3.4: "On success the server stamps `dispatched_at` from the logical
    clock, computes `handling_deadline` as exactly 72 hours after
    `dispatched_at`" and "adds the quantity to the order's `shipped_quantity`,
    and moves the order automatically to `FULFILLED` once `shipped_quantity`
    reaches the ordered `quantity`." and "Spoilage moves the shipment to
    `SPOILED` and subtracts its quantity from the order's `shipped_quantity`:
    spoiled stock is written off rather than returned to storage, so it no
    longer counts toward fulfilment."

    Design: Corner/endpoints/shipment_side_effects_order_fulfillment
    """
    ctx = setup_ready_world(order_quantity=4000, plantable_count=20000)
    order_id = ctx["order"]["id"]
    contract_id = ctx["contract"]["id"]

    set_clock("2027-04-01T00:00:00Z")
    sh1 = get_success_data(
        api.create_shipment(
            {"planting_contract_id": contract_id, "crop_batch_id": ctx["batch"]["id"],
             "quantity": 2000}, NM
        )
    )
    expected_deadline = _parse_iso(sh1["dispatched_at"]) + timedelta(hours=72)
    assert _parse_iso(sh1["handling_deadline"]) == expected_deadline, (
        f"handling_deadline must be dispatched_at + 72h: {sh1['dispatched_at']} -> "
        f"{sh1['handling_deadline']}"
    )

    order = get_success_data(api.get_seedling_order(order_id, CO))
    assert order["shipped_quantity"] == 2000
    assert order["status"] == "ALLOCATED"

    spoiled = get_success_data(
        api.report_shipment_spoilage(sh1["id"], {"reason": "TEMP_EXCURSION"}, FA)
    )
    assert spoiled["status"] == "SPOILED"
    order = get_success_data(api.get_seedling_order(order_id, CO))
    assert order["shipped_quantity"] == 0, (
        "spoiled stock no longer counts toward fulfilment"
    )

    get_success_data(
        api.create_shipment(
            {"planting_contract_id": contract_id, "crop_batch_id": ctx["batch"]["id"],
             "quantity": 4000}, NM
        )
    )
    order = get_success_data(api.get_seedling_order(order_id, CO))
    assert order["shipped_quantity"] == 4000
    assert order["status"] == "FULFILLED", (
        "the order must auto-transition to FULFILLED at full shipped coverage"
    )


def _spoiled_shipment_world(api):
    """READY_TO_PLANT world; one shipment dispatched then spoiled."""
    ctx = setup_ready_world(order_quantity=4000, plantable_count=20000)
    set_clock("2027-04-01T00:00:00Z")
    sh = get_success_data(
        api.create_shipment(
            {"planting_contract_id": ctx["contract"]["id"],
             "crop_batch_id": ctx["batch"]["id"], "quantity": 1000}, NM
        )
    )
    spoiled = get_success_data(
        api.report_shipment_spoilage(sh["id"], {"reason": "TEMP_EXCURSION"}, FA)
    )
    return ctx, spoiled


def test_spoiled_shipment_is_terminal(api):
    """PRD §3.4: "Spoilage moves the shipment to `SPOILED`" and "Delivery moves
    a shipment from `DISPATCHED` to `DELIVERED`" and PRD §2.6: "State legality:
    the state machine's from-state permits the requested transition — otherwise
    `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/spoiled_shipment_is_terminal
    """
    ctx, spoiled = _spoiled_shipment_world(api)
    assert spoiled["status"] == "SPOILED", "DISPATCHED -> SPOILED branch"

    res = api.deliver_shipment(spoiled["id"], {"delivered_at": "2027-04-01T09:00:00Z"}, NM)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_handling_window_exactly_72h_boundary(api):
    """PRD §3.4: "computes `handling_deadline` as exactly 72 hours after
    `dispatched_at`" and "the recorded `planted_confirmed_at` must fall no later
    than the shipment's `handling_deadline` — a confirmation exactly at the
    deadline passes, anything later is rejected with
    `ERR_HANDLING_WINDOW_EXCEEDED`"

    Design: Corner/validations/handling_window_exactly_72h_boundary
    """
    ctx = setup_ready_world(order_quantity=4000, plantable_count=20000)
    contract_id = ctx["contract"]["id"]

    crew = create_crew()
    asg = create_assignment(crew["id"], contract_id, "2027-04-01", "2027-04-03", 4000)
    confirm_assignment(asg["id"])
    set_clock("2027-04-01T00:00:00Z")
    start_planting(contract_id)

    sh1 = get_success_data(
        api.create_shipment({"planting_contract_id": contract_id,
                             "crop_batch_id": ctx["batch"]["id"], "quantity": 1000}, NM)
    )
    sh2 = get_success_data(
        api.create_shipment({"planting_contract_id": contract_id,
                             "crop_batch_id": ctx["batch"]["id"], "quantity": 1000}, NM)
    )
    deadline = _parse_iso(sh1["dispatched_at"]) + timedelta(hours=72)
    assert _parse_iso(sh1["handling_deadline"]) == deadline, (
        f"handling_deadline must be dispatched_at + 72h: {sh1['dispatched_at']} -> "
        f"{sh1['handling_deadline']}"
    )

    for s in (sh1, sh2):
        get_success_data(
            api.deliver_shipment(s["id"], {"delivered_at": "2027-04-01T08:00:00Z"}, NM)
        )

    ok = get_success_data(
        api.confirm_shipment_planted(sh1["id"], {"planted_confirmed_at": "2027-04-04T00:00:00Z"}, CO)
    )
    assert ok["status"] == "PLANTED", "confirmation exactly at the deadline must pass"

    late = api.confirm_shipment_planted(sh2["id"], {"planted_confirmed_at": "2027-04-04T00:00:01Z"}, CO)
    validate_error(late, ApiErrorId.ERR_HANDLING_WINDOW_EXCEEDED)


def test_stock_age_45_day_boundary(api):
    """PRD §3.4: "Stock age is enforced at day granularity: for every `ACTIVE`
    placement the withdrawal touches, the dispatch date minus the placement's
    `placed_on` may not exceed 45 days, with a placement exactly 45 days old
    passing, otherwise `ERR_STOCK_AGE_EXCEEDED`."

    Design: Corner/validations/stock_age_45_day_boundary
    """
    z_src = create_seed_zone(zone_min=1000, zone_max=2000)
    z_dst = create_seed_zone(zone_min=1400, zone_max=2400)
    lo = create_landowner()
    lot = create_seed_lot(z_src["id"], quantity_grams=500, germination_pct=0.85)

    b1 = create_crop_batch(lot["id"], lot["version"])
    sow_batch(b1["id"], 100)
    lift_batch(b1["id"], lifted_on="2027-03-05", lifted_count=5200)
    b1 = get_success_data(api.grade_crop_batch(b1["id"], {"plantable_count": 5000}, NM))

    lot_now = get_success_data(api.get_seed_lot(lot["id"], NM))
    b2 = create_crop_batch(lot["id"], lot_now["version"])
    sow_batch(b2["id"], 100)
    lift_batch(b2["id"], lifted_on="2027-03-04", lifted_count=5200)
    b2 = get_success_data(api.grade_crop_batch(b2["id"], {"plantable_count": 5000}, NM))

    order = setup_confirmed_order(lo["id"], z_dst["id"], 9000)
    get_success_data(api.create_allocation(order["id"], {"crop_batch_id": b1["id"], "quantity": 4500}, CO))
    get_success_data(api.create_allocation(order["id"], {"crop_batch_id": b2["id"], "quantity": 4500}, CO))

    contract = create_contract(lo["id"], order["id"], z_dst["id"], acres=10,
                               window_start="2027-04-01", window_end="2027-05-31")
    set_clock("2027-03-15T00:00:00Z")
    record_site_prep(contract["id"], "2027-03-01")
    verify_site_prep(contract["id"])
    mark_ready(contract["id"])

    unit = create_storage_unit(capacity_units=20000)
    create_placement(b1["id"], unit["id"], 5000, placed_on="2027-03-12")
    create_placement(b2["id"], unit["id"], 5000, placed_on="2027-03-11")

    set_clock("2027-04-26T00:00:00Z")
    ok_res = api.create_shipment(
        {"planting_contract_id": contract["id"], "crop_batch_id": b1["id"], "quantity": 1000}, NM
    )
    ok = validate_success(ok_res, 201)
    assert is_valid_uuid(ok["id"]), "placement exactly 45 days old must ship"

    old_res = api.create_shipment(
        {"planting_contract_id": contract["id"], "crop_batch_id": b2["id"], "quantity": 1000}, NM
    )
    validate_error(old_res, ApiErrorId.ERR_STOCK_AGE_EXCEEDED)


def _lifted_not_graded_world(api):
    """Order allocated against a SOWN batch (projection basis); contract
    READY_TO_PLANT; the batch is then lifted but not graded."""
    ctx = setup_ready_world(order_quantity=4000, grade=False, with_storage=False)
    # Batch is SOWN; projection floor(300*88*0.85*0.88) = 19747 covers 4000.
    lift_batch(ctx["batch"]["id"], lifted_on="2027-03-10", lifted_count=9500)
    set_clock("2027-04-01T00:00:00Z")
    return ctx


def test_shipment_rejected_when_batch_not_graded(api):
    """PRD §3.4: "The batch must be `GRADED` (`ERR_BATCH_NOT_GRADED`) and its
    lot must not be quarantined (`ERR_LOT_QUARANTINED`)."

    Design: Difficulty/cross_entity_state_dependency/shipment_rejected_when_batch_not_graded
    """
    ctx = _lifted_not_graded_world(api)
    res = api.create_shipment(
        {"planting_contract_id": ctx["contract"]["id"],
         "crop_batch_id": ctx["batch"]["id"], "quantity": 4000}, NM
    )
    validate_error(res, ApiErrorId.ERR_BATCH_NOT_GRADED)


def test_allocation_allowed_on_sown_batch_shipment_not(api):
    """PRD §3.3: "The reservable ceiling is the smaller of the order's uncovered
    remainder (its `quantity` minus its `allocated_quantity`) and the batch's
    unreserved basis — the `plantable_count` for a `GRADED` batch, the
    `projected_plantable` while the batch is `SOWN` or `LIFTED`" and PRD §3.4:
    "The batch must be `GRADED` (`ERR_BATCH_NOT_GRADED`)"

    Design: Difficulty/cross_entity_state_dependency/shipment_rejected_when_batch_not_graded
    """
    # Allocation against the SOWN batch succeeds on the projected basis...
    ctx = setup_ready_world(order_quantity=4000, grade=False, with_storage=False)
    assert ctx["allocation"]["quantity"] == 4000, (
        "reserving against a SOWN batch's projected_plantable is legal"
    )
    # ...but shipping the same batch while it is only LIFTED is rejected.
    lift_batch(ctx["batch"]["id"], lifted_on="2027-03-10", lifted_count=9500)
    set_clock("2027-04-01T00:00:00Z")
    res = api.create_shipment(
        {"planting_contract_id": ctx["contract"]["id"],
         "crop_batch_id": ctx["batch"]["id"], "quantity": 4000}, NM
    )
    validate_error(res, ApiErrorId.ERR_BATCH_NOT_GRADED)


def _quarantined_shipment_world(api):
    """READY_TO_PLANT contract drawing on a GRADED batch; the lot is then
    quarantined and the placement ages past 45 days."""
    ctx = setup_ready_world(order_quantity=4000, plantable_count=20000)
    get_success_data(api.quarantine_seed_lot(ctx["lot"]["id"], NM))
    # Placement placed_on 2027-03-12; dispatch at 2027-05-01 -> age 50 days.
    set_clock("2027-05-01T00:00:00Z")
    return ctx


def test_quarantined_lot_shipment_rejected(api):
    """PRD §3.4: "The batch must be `GRADED` (`ERR_BATCH_NOT_GRADED`) and its
    lot must not be quarantined (`ERR_LOT_QUARANTINED`)." and PRD §2.6: "Every
    request passes through a fixed pipeline of checks, and when several checks
    could reject the same request, the one earliest in this order fires."
    (quarantine gate, rule 6, precedes cold-storage stock age, rule 12)

    Design: Difficulty/priority_pair_validation_conflict/quarantined_lot_shipment_safety_beats_stale_stock
    """
    ctx = _quarantined_shipment_world(api)
    res = api.create_shipment(
        {"planting_contract_id": ctx["contract"]["id"],
         "crop_batch_id": ctx["batch"]["id"], "quantity": 4000}, NM
    )
    validate_error(res, ApiErrorId.ERR_LOT_QUARANTINED)


def test_quarantine_gate_beats_stock_age_no_shipment_created(api):
    """PRD §2.6: "Every request passes through a fixed pipeline of checks, and
    when several checks could reject the same request, the one earliest in this
    order fires." (quarantine gate, rule 6, precedes cold-storage stock age,
    rule 12) and PRD §3.1: "while a lot is `QUARANTINED`, every attempt to sow
    against it, to allocate stock grown from it, or to ship that stock is
    rejected with `ERR_LOT_QUARANTINED`."

    Design: Difficulty/priority_pair_validation_conflict/quarantined_lot_shipment_safety_beats_stale_stock
    """
    ctx = _quarantined_shipment_world(api)
    lot_now = get_success_data(api.get_seed_lot(ctx["lot"]["id"], NM))
    assert lot_now["status"] == "QUARANTINED"

    res = api.create_shipment(
        {"planting_contract_id": ctx["contract"]["id"],
         "crop_batch_id": ctx["batch"]["id"], "quantity": 4000}, NM
    )
    validate_error(res, ApiErrorId.ERR_LOT_QUARANTINED, expected_status=422)

    data, meta = validate_paginated(
        api.list_shipments(NM, params={"planting_contract_id": ctx["contract"]["id"]})
    )
    assert meta["total_count"] == 0, "the rejected shipment must not persist"
    assert data == []
