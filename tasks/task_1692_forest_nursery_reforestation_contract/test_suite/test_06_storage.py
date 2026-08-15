"""Cold storage: aggregate capacity, plantable remainder, discard compensation,
and oldest-first withdrawal conservation."""
from test_helpers import (
    validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_seed_zone, setup_graded_batch, create_storage_unit, create_placement,
    setup_ready_world, set_clock,
)

NM = TEST_USERS["nursery_manager_headers"]
CO = TEST_USERS["contract_officer_headers"]


def _unit_load(api, unit_id):
    return get_success_data(api.get_storage_unit(unit_id, NM))["current_load"]


def test_storage_capacity_exact_fill_passes(api):
    """PRD §3.4: "the unit's `current_load` plus the new `quantity` may not
    exceed `capacity_units`, with a placement that exactly fills the unit
    passing — otherwise `ERR_STORAGE_CAPACITY_EXCEEDED`"

    Design: Difficulty/boundary_precision_check/storage_capacity_exact_fill_passes
    """
    ctx = setup_graded_batch(quantity_grams=1000, sown_grams=600,
                             lifted_count=48000, plantable_count=45000)
    unit = create_storage_unit(capacity_units=25000)

    p1 = create_placement(ctx["batch"]["id"], unit["id"], 20000)
    p2 = create_placement(ctx["batch"]["id"], unit["id"], 5000)
    assert p1["status"] == "ACTIVE" and p2["status"] == "ACTIVE"

    assert _unit_load(api, unit["id"]) == 25000, (
        "20000 + 5000 must fill the 25000-capacity unit exactly"
    )


def test_storage_capacity_one_over_rejected(api):
    """PRD §3.4: "the unit's `current_load` plus the new `quantity` may not
    exceed `capacity_units`, with a placement that exactly fills the unit
    passing — otherwise `ERR_STORAGE_CAPACITY_EXCEEDED`"

    Design: Difficulty/boundary_precision_check/storage_capacity_exact_fill_passes
    """
    ctx = setup_graded_batch(quantity_grams=1000, sown_grams=600,
                             lifted_count=48000, plantable_count=45000)
    unit = create_storage_unit(capacity_units=25000)
    create_placement(ctx["batch"]["id"], unit["id"], 20000)
    create_placement(ctx["batch"]["id"], unit["id"], 5000)

    res = api.create_storage_placement(
        {"crop_batch_id": ctx["batch"]["id"], "storage_unit_id": unit["id"],
         "quantity": 1, "placed_on": "2027-03-12"}, NM
    )
    validate_error(res, ApiErrorId.ERR_STORAGE_CAPACITY_EXCEEDED)
    assert _unit_load(api, unit["id"]) == 25000, (
        "the rejected placement must not change the unit load"
    )


def test_storage_aggregate_overfill_rejected(api):
    """PRD §3.4: "The unit's `current_load` is derived, not stored by hand: the
    sum, over its `ACTIVE` placements, of each placement's `quantity` minus its
    `withdrawn_quantity`." and "the unit's `current_load` plus the new
    `quantity` may not exceed `capacity_units`, with a placement that exactly
    fills the unit passing — otherwise `ERR_STORAGE_CAPACITY_EXCEEDED`"

    Design: Difficulty/resource_temporal_overlap/storage_aggregate_load_release_and_reuse
    """
    ctx = setup_graded_batch(quantity_grams=1000, sown_grams=600,
                             lifted_count=48000, plantable_count=45000)
    unit = create_storage_unit(capacity_units=25000)
    create_placement(ctx["batch"]["id"], unit["id"], 20000)
    create_placement(ctx["batch"]["id"], unit["id"], 5000)

    res = api.create_storage_placement(
        {"crop_batch_id": ctx["batch"]["id"], "storage_unit_id": unit["id"],
         "quantity": 20000, "placed_on": "2027-03-13"}, NM
    )
    validate_error(res, ApiErrorId.ERR_STORAGE_CAPACITY_EXCEEDED)


def test_storage_discard_frees_capacity(api):
    """PRD §3.4: "a `NurseryManager` may instead discard an `ACTIVE` placement
    outright, recording a `reason`, which writes off the unwithdrawn remainder
    as culls — without altering the batch's `cull_count` — and moves the
    placement to `DISCARDED`. Withdrawal and discard both recompute the unit's
    `current_load`."

    Design: Difficulty/resource_temporal_overlap/storage_aggregate_load_release_and_reuse
    """
    ctx = setup_graded_batch(quantity_grams=1000, sown_grams=600,
                             lifted_count=48000, plantable_count=45000)
    unit = create_storage_unit(capacity_units=25000)
    p1 = create_placement(ctx["batch"]["id"], unit["id"], 20000)
    create_placement(ctx["batch"]["id"], unit["id"], 5000)

    discarded = get_success_data(
        api.discard_storage_placement(p1["id"], {"reason": "mold detected"}, NM)
    )
    assert discarded["status"] == "DISCARDED"
    assert _unit_load(api, unit["id"]) == 5000, (
        "discarding the 20000-unit placement must free its share of capacity"
    )

    p3 = create_placement(ctx["batch"]["id"], unit["id"], 20000, placed_on="2027-03-13")
    assert p3["status"] == "ACTIVE", "the freed capacity must be reusable"
    assert _unit_load(api, unit["id"]) == 25000


def _conserved_world(api):
    """READY_TO_PLANT world with a 45000-plantable batch, order 9000 allocated,
    and an empty 25000-capacity unit (placements created by the test)."""
    ctx = setup_ready_world(
        order_quantity=9000,
        lot_quantity_grams=1000, sown_grams=600,
        lifted_count=48000, plantable_count=45000,
        unit_capacity=25000, placement_quantities=[],
    )
    return ctx


def test_storage_load_conserved_forward_and_discard(api):
    """PRD §3.4: "The unit's `current_load` is derived, not stored by hand: the
    sum, over its `ACTIVE` placements, of each placement's `quantity` minus its
    `withdrawn_quantity`." and "Withdrawal and discard both recompute the unit's
    `current_load`."

    Design: Difficulty/compensating_invariant/storage_load_conserved_across_place_discard_ship
    """
    ctx = _conserved_world(api)
    unit_id = ctx["unit"]["id"]
    batch_id = ctx["batch"]["id"]

    p1 = create_placement(batch_id, unit_id, 20000)
    assert _unit_load(api, unit_id) == 20000
    create_placement(batch_id, unit_id, 5000)
    assert _unit_load(api, unit_id) == 25000
    get_success_data(api.discard_storage_placement(p1["id"], {"reason": "mold detected"}, NM))
    assert _unit_load(api, unit_id) == 5000, "discard must compensate the load"
    create_placement(batch_id, unit_id, 20000, placed_on="2027-03-13")
    assert _unit_load(api, unit_id) == 25000, "freed capacity must be reusable"


def test_storage_withdrawal_oldest_first(api):
    """PRD §3.4: "withdraws from the batch's `ACTIVE` placements oldest-first —
    earliest `placed_on` first, earliest `created_at` breaking ties — flips any
    emptied placement to `WITHDRAWN`" and "The unit's `current_load` is derived,
    not stored by hand: the sum, over its `ACTIVE` placements, of each
    placement's `quantity` minus its `withdrawn_quantity`."

    Design: Difficulty/compensating_invariant/storage_load_conserved_across_place_discard_ship
    """
    ctx = _conserved_world(api)
    unit_id = ctx["unit"]["id"]
    batch_id = ctx["batch"]["id"]

    p1 = create_placement(batch_id, unit_id, 20000)                       # 2027-03-12
    p2 = create_placement(batch_id, unit_id, 5000)                        # 2027-03-12
    get_success_data(api.discard_storage_placement(p1["id"], {"reason": "mold detected"}, NM))
    p3 = create_placement(batch_id, unit_id, 20000, placed_on="2027-03-13")

    set_clock("2027-04-01T00:00:00Z")
    shipment = get_success_data(
        api.create_shipment(
            {"planting_contract_id": ctx["contract"]["id"],
             "crop_batch_id": batch_id, "quantity": 6000}, NM
        )
    )
    assert shipment["quantity"] == 6000

    assert _unit_load(api, unit_id) == 19000, (
        "6000 withdrawn from a 25000 aggregate load must leave 19000"
    )
    p2_after = get_success_data(api.get_storage_placement(p2["id"], NM))
    assert p2_after["status"] == "WITHDRAWN", (
        "the oldest placement (2027-03-12) must be drained first and flipped"
    )
    assert p2_after["withdrawn_quantity"] == 5000
    p3_after = get_success_data(api.get_storage_placement(p3["id"], NM))
    assert p3_after["withdrawn_quantity"] == 1000, (
        "the remaining 1000 must come from the next-oldest placement"
    )


def test_placement_exceeds_unplaced_plantable(api):
    """PRD §3.4: "The placement may not exceed the batch's unplaced plantable
    remainder — the batch's `plantable_count` less the quantities on all of the
    batch's placements that have not been discarded — otherwise
    `ERR_PLACEMENT_EXCEEDS_PLANTABLE`."

    Design: Corner/validations/placement_exceeds_unplaced_plantable
    """
    ctx = setup_graded_batch(sown_grams=100, lifted_count=5200, plantable_count=5000)
    unit = create_storage_unit(capacity_units=100000)

    p1 = create_placement(ctx["batch"]["id"], unit["id"], 5000)
    assert p1["status"] == "ACTIVE", "placing the full plantable remainder must pass"

    res = api.create_storage_placement(
        {"crop_batch_id": ctx["batch"]["id"], "storage_unit_id": unit["id"],
         "quantity": 1, "placed_on": "2027-03-12"}, NM
    )
    validate_error(res, ApiErrorId.ERR_PLACEMENT_EXCEEDS_PLANTABLE)
