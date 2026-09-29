"""The two state dimensions of a piece move on their own schedules."""

from test_helpers import (
    GALLERY_MANAGER,
    SCORES_GRADE_B,
    fetch_consignor,
    fetch_item,
    fetch_zone,
    flag_inventory,
    run_markdown_epoch,
    set_clock,
    setup_item_on_floor,
    validate_paginated,
)

MISSING_SOFA = {
    "title": "Roll-arm sofa",
    "category": "SOFA",
    "declared_value_cents": 189_950,
    "photo_count": 5,
    "volume_cuft": 55,
    "footprint_sqft": 24,
}


def _sofa_on_the_floor():
    return setup_item_on_floor(
        screen_scores=SCORES_GRADE_B, item_overrides=MISSING_SOFA
    )


def test_missing_flag_moves_custody_alone_and_holds_the_square_feet():
    """The gap on the floor changes custody only; merchandising stands still.

    PRD 3.9: "a piece that is `MARKED_DOWN` keeps being marked down by the epoch
    while it is missing, because the two state dimensions of a piece evolve
    independently"; "the piece keeps counting toward its zone's `occupied_sqft` until
    the loss is actually booked"

    Design: Difficulty/non_linear_state_machine/item_lifecycle_and_inventory_dimensions_advance_independently
    """
    world = _sofa_on_the_floor()
    item_id = world["item"]["id"]
    zone_id = world["zone"]["id"]

    flag_inventory(item_id, "MISSING")
    item = fetch_item(item_id)

    assert item["inventory_state"] == "SHRINKAGE_MISSING", (
        f"Expected SHRINKAGE_MISSING, got {item['inventory_state']}"
    )
    assert item["lifecycle_state"] == "ON_FLOOR", (
        f"The merchandising dimension must not move, got {item['lifecycle_state']}"
    )
    assert item["placement_zone_id"] == zone_id, (
        "A missing piece is still nominally placed"
    )

    zone = fetch_zone(zone_id)
    assert zone["occupied_sqft"] == 24, (
        f"Expected 24 still occupied, got {zone['occupied_sqft']}"
    )
    assert zone["utilization_state"] == "NORMAL", (
        f"Expected NORMAL, got {zone['utilization_state']}"
    )


def test_markdown_epoch_steps_a_missing_piece_down_in_price():
    """Day thirty marks the piece down even though nobody can find it.

    PRD 3.7: "It visits every piece whose `listed_at` is not null and whose owning
    agreement is in `status` `ACTIVE` or `EXPIRED`, in `created_at` ascending order,
    and it increments a piece's `version` only when one of that piece's fields
    actually changed."; "The stepped price is `list_price_cents` multiplied by one
    minus the step's `markdown_pct`, rounded half up to a whole number of cents."

    Design: Difficulty/non_linear_state_machine/item_lifecycle_and_inventory_dimensions_advance_independently
    """
    world = _sofa_on_the_floor()
    item_id = world["item"]["id"]

    flag_inventory(item_id, "MISSING")
    set_clock("2026-08-31T00:00:00Z")
    run_markdown_epoch()
    item = fetch_item(item_id)

    assert item["lifecycle_state"] == "MARKED_DOWN", (
        f"Expected MARKED_DOWN, got {item['lifecycle_state']}"
    )
    assert item["markdown_sequence"] == 2, (
        f"Expected step 2, got {item['markdown_sequence']}"
    )
    assert item["current_price_cents"] == 107_369, (
        f"Expected 107369, got {item['current_price_cents']}"
    )
    assert item["inventory_state"] == "SHRINKAGE_MISSING", (
        f"Custody must be untouched by the epoch, got {item['inventory_state']}"
    )
    assert item["list_price_cents"] == 126_317, (
        f"The ticket price does not move, got {item['list_price_cents']}"
    )


def test_recovery_restores_custody_without_rewinding_the_pricing_dimension(api):
    """The piece turns up marked down, still in its zone, and costs nothing.

    PRD 3.9: "A `RECOVERED` flag on a piece in `SHRINKAGE_MISSING` simply moves it
    `SHRINKAGE_MISSING → IN_CUSTODY`"; "and leaves `placement_zone_id` unchanged, so
    the zone's `occupied_sqft` does not move either"

    Design: Difficulty/non_linear_state_machine/item_lifecycle_and_inventory_dimensions_advance_independently
    """
    world = _sofa_on_the_floor()
    item_id = world["item"]["id"]
    zone_id = world["zone"]["id"]
    consignor_id = world["consignor"]["id"]

    flag_inventory(item_id, "MISSING")
    set_clock("2026-08-31T00:00:00Z")
    run_markdown_epoch()

    flag_inventory(item_id, "RECOVERED")
    item = fetch_item(item_id)

    assert item["inventory_state"] == "IN_CUSTODY", (
        f"Expected IN_CUSTODY, got {item['inventory_state']}"
    )
    assert item["lifecycle_state"] == "MARKED_DOWN", (
        f"The recovery must not rewind merchandising, got {item['lifecycle_state']}"
    )
    assert item["current_price_cents"] == 107_369, (
        f"Expected 107369, got {item['current_price_cents']}"
    )
    assert item["list_price_cents"] == 126_317, (
        f"Expected 126317, got {item['list_price_cents']}"
    )
    assert item["placement_zone_id"] == zone_id, (
        "The piece never left its zone"
    )

    zone = fetch_zone(zone_id)
    assert zone["occupied_sqft"] == 24, (
        f"Expected 24, got {zone['occupied_sqft']}"
    )
    assert zone["utilization_state"] == "NORMAL", (
        f"Expected NORMAL, got {zone['utilization_state']}"
    )

    entries, meta = validate_paginated(
        api.list_consignor_ledger_entries(
            consignor_id, GALLERY_MANAGER, params={"limit": 100}
        )
    )
    assert meta["total_count"] == 1, (
        f"Only the collection charge should exist, got {meta['total_count']}"
    )
    assert entries[0]["amount_cents"] == -27_000, (
        f"Expected -27000, got {entries[0]['amount_cents']}"
    )

    consignor = fetch_consignor(consignor_id)
    assert consignor["unclaimed_balance_cents"] == -27_000, (
        f"Expected -27000, got {consignor['unclaimed_balance_cents']}"
    )
    assert consignor["status"] == "ACTIVE", (
        f"Expected ACTIVE, got {consignor['status']}"
    )
