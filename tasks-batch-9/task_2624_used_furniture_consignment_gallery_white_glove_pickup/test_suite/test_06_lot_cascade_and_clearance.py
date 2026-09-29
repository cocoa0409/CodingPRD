"""A downgraded chair set drags its dining lot off the front showroom."""

from test_helpers import (
    GALLERY_MANAGER,
    SCORES_GRADE_A,
    SCORES_GRADE_B,
    SCORES_GRADE_D,
    STD_SCHEDULE_STEPS,
    create_zone,
    fetch_consignor,
    fetch_item,
    fetch_zone,
    place_item,
    receive_item,
    setup_lot,
    take_custody,
    validate_paginated,
)

TWO_STEP_SCHEDULE = STD_SCHEDULE_STEPS[:2]

PARENT = {
    "title": "Dining set lot",
    "category": "DINING",
    "declared_value_cents": 70_000,
    "photo_count": 6,
    "volume_cuft": 5,
    "footprint_sqft": 40,
}
TABLE = {
    "title": "Trestle table",
    "category": "DINING",
    "declared_value_cents": 40_000,
    "photo_count": 4,
    "volume_cuft": 25,
    "footprint_sqft": 20,
    "screen_scores": SCORES_GRADE_A,
}
CHAIRS = {
    "title": "Chair set",
    "category": "DINING",
    "declared_value_cents": 30_000,
    "photo_count": 4,
    "volume_cuft": 20,
    "footprint_sqft": 12,
    "screen_scores": SCORES_GRADE_B,
}


def _lot_on_the_front_showroom():
    """Parent on the front floor, table inspected, chairs still awaiting inspection.

    Two clearance zones exist: the smaller one was created first, so ranking by
    remaining room cannot be faked by taking the oldest eligible row.
    """
    world = setup_lot(
        parent_overrides=PARENT,
        component_specs=(TABLE, CHAIRS),
        parent_scores=SCORES_GRADE_A,
        schedule_steps=TWO_STEP_SCHEDULE,
        consignor_overrides={"floor_number": 3, "has_elevator": False},
    )
    table, chairs = world["components"]
    world.update(
        take_custody(
            world["consignor"]["id"],
            [world["parent"]["id"], table["id"], chairs["id"]],
            actual_stair_flights=2,
        )
    )
    receive_item(table["id"], scores=SCORES_GRADE_A)
    receive_item(world["parent"]["id"], scores=SCORES_GRADE_A)

    world["front_zone"] = create_zone(
        name="Front A", zone_type="SHOWROOM_FRONT", capacity_sqft=200
    )
    world["clearance_b"] = create_zone(
        name="Clearance B", zone_type="CLEARANCE", capacity_sqft=45
    )
    world["clearance_a"] = create_zone(
        name="Clearance A", zone_type="CLEARANCE", capacity_sqft=50
    )
    world["parent"] = place_item(world["parent"]["id"], world["front_zone"]["id"])
    world["table"] = table
    world["chairs"] = chairs
    return world


def test_component_downgrade_reprices_the_component_and_its_bundle():
    """The chairs fall to D and the lot's ticket price is re-summed.

    PRD 3.5: "A distance of two or more grades moves the piece
    `RECEIVED → RECEIVING_DISPUTE` instead"; "Second, because the component's price
    changed and its `parent_lot_item_id` is not null, the parent's `list_price_cents`
    is recomputed by the bundle calculation"

    Design: Difficulty/transitive_cascade/component_downgrade_cascades_lot_price_into_clearance_relocation
    """
    world = _lot_on_the_front_showroom()
    parent_id = world["parent"]["id"]
    chairs_id = world["chairs"]["id"]

    before = fetch_item(parent_id)
    assert before["lifecycle_state"] == "ON_FLOOR", (
        f"Expected ON_FLOOR, got {before['lifecycle_state']}"
    )
    assert before["current_price_cents"] >= 50_000, (
        "The lot must start above the clearance threshold, got "
        f"{before['current_price_cents']}"
    )
    assert before["clearance_relocation_pending"] is False, (
        "No relocation is owed yet"
    )

    receive_item(chairs_id, scores=SCORES_GRADE_D)

    chairs = fetch_item(chairs_id)
    assert chairs["photo_score"] == 3.53, (
        f"Expected 3.53 from 3.5/4.0/3.0, got {chairs['photo_score']}"
    )
    assert chairs["condition_grade"] == "D", (
        f"Expected D, got {chairs['condition_grade']}"
    )
    assert chairs["list_price_cents"] == 12_600, (
        f"Expected 12600, got {chairs['list_price_cents']}"
    )
    assert chairs["current_price_cents"] == 12_600, (
        f"Expected 12600, got {chairs['current_price_cents']}"
    )
    assert chairs["provisional_condition_grade"] == "B", (
        f"The photographed grade stays B, got {chairs['provisional_condition_grade']}"
    )
    assert chairs["provisional_list_price_cents"] == 22_050, (
        f"Expected 22050, got {chairs['provisional_list_price_cents']}"
    )
    assert chairs["lifecycle_state"] == "RECEIVING_DISPUTE", (
        f"B down to D is a two-grade fall, got {chairs['lifecycle_state']}"
    )
    assert chairs["election_deadline_at"] is not None, (
        "A dispute must carry an election deadline"
    )

    parent = fetch_item(parent_id)
    assert parent["list_price_cents"] == 43_470, (
        f"Expected 43470 from (35700 + 12600) at 90 hundredths, got {parent['list_price_cents']}"
    )
    assert parent["condition_grade"] == "D", (
        f"The lot takes its worst component's grade, got {parent['condition_grade']}"
    )


def test_cheapened_lot_is_relocated_to_the_roomiest_clearance_zone():
    """The lot moves to the 50-square-foot clearance zone, not the older one.

    PRD 3.5: "if the parent's `current_price_cents` has fallen below 50,000 cents
    while the parent occupies a zone whose `zone_type` is not `CLEARANCE`, the
    clearance relocation selector runs on the parent and updates its
    `placement_zone_id`"

    PRD 3.6: "Rank the survivors by remaining room descending, breaking ties by
    `created_at` ascending; a row's `id` is never consulted as a tie-break."

    Design: Difficulty/transitive_cascade/component_downgrade_cascades_lot_price_into_clearance_relocation
    """
    world = _lot_on_the_front_showroom()
    parent_id = world["parent"]["id"]

    receive_item(world["chairs"]["id"], scores=SCORES_GRADE_D)

    parent = fetch_item(parent_id)
    assert parent["markdown_sequence"] == 1, (
        f"Expected step 1, got {parent['markdown_sequence']}"
    )
    assert parent["current_price_cents"] == 43_470, (
        f"Expected 43470, got {parent['current_price_cents']}"
    )
    assert parent["placement_zone_id"] == world["clearance_a"]["id"], (
        "The lot must land in the clearance zone with the most free room"
    )
    assert parent["placement_zone_id"] != world["clearance_b"]["id"], (
        "The zone created first must not win on age alone"
    )
    assert parent["clearance_relocation_pending"] is False, (
        "A relocation that was honoured leaves nothing pending"
    )

    front = fetch_zone(world["front_zone"]["id"])
    assert front["occupied_sqft"] == 0, (
        f"Expected 0, got {front['occupied_sqft']}"
    )
    assert front["utilization_state"] == "NORMAL", (
        f"Expected NORMAL, got {front['utilization_state']}"
    )

    clearance_a = fetch_zone(world["clearance_a"]["id"])
    assert clearance_a["occupied_sqft"] == 40, (
        f"Expected 40, got {clearance_a['occupied_sqft']}"
    )
    assert clearance_a["utilization_state"] == "TIGHT", (
        f"40 of 50 is 0.80, so TIGHT; got {clearance_a['utilization_state']}"
    )

    clearance_b = fetch_zone(world["clearance_b"]["id"])
    assert clearance_b["occupied_sqft"] == 0, (
        f"Expected 0, got {clearance_b['occupied_sqft']}"
    )
    assert clearance_b["utilization_state"] == "NORMAL", (
        f"Expected NORMAL, got {clearance_b['utilization_state']}"
    )


def test_uninspected_sibling_and_the_ledger_are_left_alone(api):
    """The table keeps its own grade and price, and no money moves.

    PRD 3.3: "collect every component whose `lifecycle_state` is not
    `SCREEN_REJECTED`, sum their `list_price_cents` values"

    Design: Difficulty/transitive_cascade/component_downgrade_cascades_lot_price_into_clearance_relocation
    """
    world = _lot_on_the_front_showroom()
    consignor_id = world["consignor"]["id"]

    receive_item(world["chairs"]["id"], scores=SCORES_GRADE_D)

    table = fetch_item(world["table"]["id"])
    assert table["condition_grade"] == "A", (
        f"Expected A, got {table['condition_grade']}"
    )
    assert table["list_price_cents"] == 35_700, (
        f"Expected 35700, got {table['list_price_cents']}"
    )
    assert table["lifecycle_state"] == "AWAITING_PLACEMENT", (
        f"Expected AWAITING_PLACEMENT, got {table['lifecycle_state']}"
    )
    assert table["placement_zone_id"] is None, (
        "The table was never placed"
    )

    entries, meta = validate_paginated(
        api.list_consignor_ledger_entries(
            consignor_id, GALLERY_MANAGER, params={"limit": 100}
        )
    )
    assert meta["total_count"] == 1, (
        f"Only the collection charge should exist, got {meta['total_count']}"
    )
    assert entries[0]["amount_cents"] == -33_500, (
        f"Expected -33500, got {entries[0]['amount_cents']}"
    )
    assert fetch_consignor(consignor_id)["unclaimed_balance_cents"] == -33_500, (
        "Repricing a lot moves no money"
    )
