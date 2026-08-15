"""Allocations: accumulation, seed-transfer tolerance, cancel lockdown, OCC on lot."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_landowner, create_seed_zone, create_seed_lot, create_crop_batch,
    setup_graded_batch, setup_confirmed_order, cancel_order,
    make_landowner_headers,
)

NM = TEST_USERS["nursery_manager_headers"]
CO = TEST_USERS["contract_officer_headers"]


def test_allocation_partial_accumulates_then_overfill_rejected(api):
    """PRD §3.3: "The reservable ceiling is the smaller of the order's uncovered
    remainder (its `quantity` minus its `allocated_quantity`) and the batch's
    unreserved basis — the `plantable_count` for a `GRADED` batch, the
    `projected_plantable` while the batch is `SOWN` or `LIFTED` — less the
    batch's `reserved_plantable`; a reservation above that ceiling is rejected
    with `ERR_ALLOCATION_EXCEEDS_AVAILABLE`." and "When a new allocation brings
    `allocated_quantity` exactly level with the order's `quantity`, the order
    moves automatically from `CONFIRMED` to `ALLOCATED`"

    Design: Corner/calculations/allocation_partial_accumulates_then_overfill_rejected
    """
    ctx = setup_graded_batch(sown_grams=100, lifted_count=9500, plantable_count=9000)
    z_dst = create_seed_zone(zone_min=1400, zone_max=2400)
    landowner = create_landowner()
    order = setup_confirmed_order(landowner["id"], z_dst["id"], 4000)

    get_success_data(api.create_allocation(order["id"], {"crop_batch_id": ctx["batch"]["id"], "quantity": 2500}, CO))
    order = get_success_data(api.get_seedling_order(order["id"], CO))
    assert order["allocated_quantity"] == 2500
    assert order["status"] == "CONFIRMED", (
        f"a partial allocation must not flip the order, got {order['status']}"
    )

    get_success_data(api.create_allocation(order["id"], {"crop_batch_id": ctx["batch"]["id"], "quantity": 1500}, CO))
    order = get_success_data(api.get_seedling_order(order["id"], CO))
    assert order["allocated_quantity"] == 4000
    assert order["status"] == "ALLOCATED", (
        f"full coverage must auto-transition the order to ALLOCATED, got {order['status']}"
    )

    res = api.create_allocation(order["id"], {"crop_batch_id": ctx["batch"]["id"], "quantity": 1}, CO)
    validate_error(res, ApiErrorId.ERR_ALLOCATION_EXCEEDS_AVAILABLE)


def test_species_zone_transfer_tolerance(api):
    """PRD §3.3: "The seed-transfer rule binds the reservation: the batch's
    species must match the order's species, and the band midpoints of the batch
    lot's source zone and the order's destination zone may differ by no more
    than 500 feet, otherwise `ERR_SPECIES_ZONE_MISMATCH`."

    Design: Corner/validations/species_zone_transfer_tolerance
    """
    ctx = setup_graded_batch(sown_grams=100, lifted_count=9500, plantable_count=9000,
                             zone_min=1000, zone_max=2000)  # source midpoint 1500
    z_mid = create_seed_zone(zone_min=1600, zone_max=2400)   # midpoint 2000 (gap 500)
    z_far = create_seed_zone(zone_min=2100, zone_max=2900)   # midpoint 2500 (gap 1000)
    landowner = create_landowner()
    o_mid = setup_confirmed_order(landowner["id"], z_mid["id"], 1000)
    o_far = setup_confirmed_order(landowner["id"], z_far["id"], 1000)

    ok_res = api.create_allocation(o_mid["id"], {"crop_batch_id": ctx["batch"]["id"], "quantity": 1000}, CO)
    ok = validate_success(ok_res, 201)
    assert ok["quantity"] == 1000, "midpoint gap of exactly 500 ft must be admissible"

    err_res = api.create_allocation(o_far["id"], {"crop_batch_id": ctx["batch"]["id"], "quantity": 1000}, CO)
    validate_error(err_res, ApiErrorId.ERR_SPECIES_ZONE_MISMATCH)


def _cancelled_order_world():
    """GRADED 9000-plantable batch + an order confirmed then cancelled."""
    ctx = setup_graded_batch(sown_grams=100, lifted_count=9500, plantable_count=9000)
    z_dst = create_seed_zone(zone_min=1400, zone_max=2400)
    landowner = create_landowner()
    order = setup_confirmed_order(landowner["id"], z_dst["id"], 4000)
    cancelled = cancel_order(order["id"], landowner_id=landowner["id"])
    return ctx, cancelled


def test_allocate_to_cancelled_order_rejected(api):
    """PRD §2.6: "Every request passes through a fixed pipeline of checks, and
    when several checks could reject the same request, the one earliest in this
    order fires." with "State legality: the state machine's from-state permits
    the requested transition — otherwise `ERR_INVALID_STATE` (409)" preceding
    rule 21 "Allocation availability at allocation creation — otherwise
    `ERR_ALLOCATION_EXCEEDS_AVAILABLE` (422)."

    Design: Difficulty/priority_pair_validation_conflict/cancelled_order_allocation_state_beats_fiscal
    """
    ctx, cancelled = _cancelled_order_world()
    res = api.create_allocation(
        cancelled["id"], {"crop_batch_id": ctx["batch"]["id"], "quantity": 99999999}, CO
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_allocate_to_cancelled_order_state_beats_fiscal_409(api):
    """PRD §2.6: "Every request passes through a fixed pipeline of checks, and
    when several checks could reject the same request, the one earliest in this
    order fires." with "State legality: the state machine's from-state permits
    the requested transition — otherwise `ERR_INVALID_STATE` (409)" preceding
    rule 21 "Allocation availability at allocation creation — otherwise
    `ERR_ALLOCATION_EXCEEDS_AVAILABLE` (422)." and PRD §3.3: "A successful
    cancel moves the order to the terminal `CANCELLED` state"

    Design: Difficulty/priority_pair_validation_conflict/cancelled_order_allocation_state_beats_fiscal
    """
    ctx, cancelled = _cancelled_order_world()
    res = api.create_allocation(
        cancelled["id"], {"crop_batch_id": ctx["batch"]["id"], "quantity": 99999999}, CO
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    order = get_success_data(api.get_seedling_order(cancelled["id"], CO))
    assert order["status"] == "CANCELLED"
    assert order["allocated_quantity"] == 0, (
        "a rejected allocation must leave the cancelled order's coverage untouched"
    )


def test_immediate_consistency_read_after_write(api):
    """PRD §3.3: "`allocated_quantity`, the sum of quantities over the order's
    `ACTIVE` allocations" and PRD §3.2: "The batch's `reserved_plantable` is the
    total quantity across its `ACTIVE` allocation rows." and PRD §3.3: "When a
    new allocation brings `allocated_quantity` exactly level with the order's
    `quantity`, the order moves automatically from `CONFIRMED` to `ALLOCATED`"

    Design: Corner/cross_cutting/immediate_consistency_read_after_write
    """
    ctx = setup_graded_batch(sown_grams=100, lifted_count=9500, plantable_count=9000)
    z_dst = create_seed_zone(zone_min=1400, zone_max=2400)
    landowner = create_landowner()
    order = setup_confirmed_order(landowner["id"], z_dst["id"], 4000)

    get_success_data(api.create_allocation(order["id"], {"crop_batch_id": ctx["batch"]["id"], "quantity": 4000}, CO))

    order_now = get_success_data(api.get_seedling_order(order["id"], CO))
    assert order_now["allocated_quantity"] == 4000
    assert order_now["status"] == "ALLOCATED"

    batch_now = get_success_data(api.get_crop_batch(ctx["batch"]["id"], NM))
    assert batch_now["reserved_plantable"] == 4000, (
        f"batch reserved_plantable must reflect the allocation on the immediate read, "
        f"got {batch_now['reserved_plantable']}"
    )


def test_occ_crop_batch_stale_lot_version(api):
    """PRD §2.7: "Creating a crop batch requires `expected_seed_lot_version`,
    carrying the client-observed `version` of the seed lot the batch is planned
    against. If the lot's current `version` has advanced past the submitted
    value — a quarantine, a release, or another batch plan having been recorded
    since the client last read the lot — the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412)" and "recording a crop-batch plan advances
    the seed lot's `version` by one"

    Design: Corner/cross_cutting/occ_crop_batch_stale_lot_version
    """
    zone = create_seed_zone()
    lot = create_seed_lot(zone["id"], quantity_grams=500, germination_pct=0.85)
    observed = lot["version"]

    first = create_crop_batch(lot["id"], observed)
    assert first["seed_lot_id"] == lot["id"], "fresh observed version must be accepted"

    res = api.create_crop_batch(
        {
            "seed_lot_id": lot["id"],
            "planned_sow_date": "2026-09-02",
            "lift_window_start": "2027-03-01",
            "lift_window_end": "2027-03-31",
            "expected_seed_lot_version": observed,
        },
        NM,
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)
