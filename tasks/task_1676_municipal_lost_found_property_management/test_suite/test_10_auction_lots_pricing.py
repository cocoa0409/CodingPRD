"""Lot composition pricing: floor rates, pinned rounding, caps, eligibility
(PRD §2.10, §3.8)."""
from test_helpers import (
    ApiErrorId,
    add_lot_item,
    assert_lot_item,
    create_auction_lot_payload,
    create_event,
    create_item,
    create_location,
    create_policy,
    create_program,
    create_venue,
    get_item,
    get_lot,
    make_auction_coordinator_headers,
    make_item_auction_eligible,
    set_clock,
    run_retention_sweep,
    setup_auction_eligible_item,
    setup_event_with_lot,
    setup_lot_with_eligible_item,
    setup_stored_item,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD_1 = make_auction_coordinator_headers("coord-1")


def test_lot_floor_price_rounded_half_up_per_item(api):
    """PRD §3.8: "each lotted item's `floor_price_cents` is its
    `declared_value_cents` multiplied by the rate for its `value_tier` — 10%
    for `LOW`, 20% for `MID`, 30% for `HIGH` — rounded half-up to whole cents".

    Design: Difficulty/combinatorial_formula/lot_minimum_bid_per_item_rounding
    """
    ctx = setup_auction_eligible_item(declared_value_cents=5005)
    auction = setup_event_with_lot(ctx.program["id"])
    lot_item = add_lot_item(auction.lot["id"], ctx.item["id"])
    # round_half_up(5005 * 0.10) = round_half_up(500.50) = 501.
    assert lot_item["floor_price_cents"] == 501
    assert_lot_item(lot_item)


def test_lot_minimum_bid_sums_rounded_floors(api):
    """PRD §2.10: "the rounding order is pinned: each individual amount is
    rounded to whole cents first, and only then are the rounded amounts
    summed." PRD §3.8: "the lot's `minimum_bid_cents` is the sum of those
    already-rounded floors."

    Design: Difficulty/combinatorial_formula/lot_minimum_bid_per_item_rounding
    """
    ctx = setup_auction_eligible_item(declared_value_cents=5005, description="charger A")
    item_b = create_item(ctx.program["id"], ctx.location["id"],
                         declared_value_cents=5005, description="charger B")
    make_item_auction_eligible(item_b["id"], "2026-08-11T09:00:00Z")
    auction = setup_event_with_lot(ctx.program["id"])

    add_lot_item(auction.lot["id"], ctx.item["id"])
    add_lot_item(auction.lot["id"], item_b["id"])
    lot = get_lot(auction.lot["id"])
    # Per-item rounding first (501 + 501); sum-then-round would yield 1001.
    assert lot["minimum_bid_cents"] == 1002
    assert get_item(ctx.item["id"])["status"] == "LOTTED"
    assert get_item(item_b["id"])["status"] == "LOTTED"


def test_lot_floor_high_tier_rate(api):
    """PRD §3.8: "each lotted item's `floor_price_cents` is its
    `declared_value_cents` multiplied by the rate for its `value_tier` — 10%
    for `LOW`, 20% for `MID`, 30% for `HIGH` — rounded half-up to whole cents".

    Design: Corner/calculations/lot_floor_high_tier_rate
    """
    ctx = setup_auction_eligible_item(declared_value_cents=150000, value_tier="HIGH",
                                      retention_days=10)
    auction = setup_event_with_lot(ctx.program["id"])
    lot_item = add_lot_item(auction.lot["id"], ctx.item["id"])
    assert lot_item["floor_price_cents"] == 45000, "150000 * 0.30"
    assert get_lot(auction.lot["id"])["minimum_bid_cents"] == 45000


def test_lot_item_rows_carry_no_version(api):
    """PRD §2.4: "A lot-item membership row carries only `id` and `created_at`;
    both `updated_at` and `version` are absent from it."

    Design: Corner/entities/lotitem_immutable_no_version
    """
    ctx = setup_lot_with_eligible_item(declared_value_cents=5005)
    rows, meta = validate_paginated(api.list_lot_items(ctx.lot["id"], COORD_1))
    assert len(rows) == 1
    row = rows[0]
    assert_lot_item(row)
    assert row["floor_price_cents"] == 501
    assert row["lot_id"] == ctx.lot["id"] and row["item_id"] == ctx.item["id"]


def test_lot_items_listing_shows_computed_floor(api):
    """PRD §3.8: "A successful addition creates the lot-item row with its
    computed `floor_price_cents`" and "Membership rows can be listed per lot or
    across lots with `lot_id` and `item_id` filters."

    Design: Corner/endpoints/lot_items_subresource_lists_floor
    """
    ctx = setup_lot_with_eligible_item(declared_value_cents=5005)

    rows, _ = validate_paginated(api.list_lot_items(ctx.lot["id"], COORD_1))
    assert len(rows) == 1
    assert rows[0]["item_id"] == ctx.item["id"]
    assert rows[0]["floor_price_cents"] == 501

    across, _ = validate_paginated(
        api.list_all_lot_items(COORD_1, params={"item_id": ctx.item["id"]}))
    assert len(across) == 1, "cross-lot list filter finds the same row"
    assert across[0]["id"] == rows[0]["id"]
    assert across[0]["lot_id"] == ctx.lot["id"]


def test_lot_add_stored_item_rejected(api):
    """PRD §3.8: "the item must be `AUCTION_ELIGIBLE`
    (`ERR_ITEM_NOT_AUCTION_ELIGIBLE`)".

    Design: Corner/errors/err_item_not_auction_eligible_rejected
    """
    ctx = setup_stored_item(declared_value_cents=5000)  # never swept: still STORED
    auction = setup_event_with_lot(ctx.program["id"])
    lot = get_lot(auction.lot["id"])
    res = api.add_lot_item(auction.lot["id"], ctx.item["id"], lot["version"], COORD_1)
    validate_error(res, ApiErrorId.ERR_ITEM_NOT_AUCTION_ELIGIBLE, expected_status=409)
    assert get_item(ctx.item["id"])["status"] == "STORED"


def test_lot_add_exceeding_insurance_cap_rejected(api):
    """PRD §3.1: "an addition that would push a lot's projected minimum bid
    above the cap is rejected with `ERR_INSURANCE_CAP_EXCEEDED`." PRD §3.8:
    "the lot's current `minimum_bid_cents` plus the candidate item's floor
    price must not exceed the venue's `insurance_cap_cents`
    (`ERR_INSURANCE_CAP_EXCEEDED`)".

    Design: Corner/errors/err_insurance_cap_exceeded_rejected
    """
    ctx = setup_auction_eligible_item(declared_value_cents=5005)
    auction = setup_event_with_lot(ctx.program["id"], venue_cap=100)
    lot = get_lot(auction.lot["id"])
    # Candidate floor is 501; 0 + 501 > cap 100.
    res = api.add_lot_item(auction.lot["id"], ctx.item["id"], lot["version"], COORD_1)
    validate_error(res, ApiErrorId.ERR_INSURANCE_CAP_EXCEEDED, expected_status=422)
    assert get_item(ctx.item["id"])["status"] == "AUCTION_ELIGIBLE"


def test_lot_add_cross_program_beats_cap_violation(api):
    """PRD §3.8: "the item's `program_id` must equal the event's `program_id`
    (`ERR_CROSS_PROGRAM_REFERENCE`), and the lot's current `minimum_bid_cents`
    plus the candidate item's floor price must not exceed the venue's
    `insurance_cap_cents` (`ERR_INSURANCE_CAP_EXCEEDED`)" — the cross-program
    check is narrated before the fiscal check, and PRD §2.7 orders
    "Cross-program referential consistency — `ERR_CROSS_PROGRAM_REFERENCE`"
    before "Fiscal rules — `ERR_INSURANCE_CAP_EXCEEDED`".

    Design: Difficulty/priority_pair_validation_conflict/referential_over_fiscal_on_lot_add
    """
    # Item lives under a FACILITY program and is swept eligible there.
    foreign = setup_auction_eligible_item(
        program_type="FACILITY", declared_value_cents=5005,
        sweep_clock="2026-08-12T00:00:00Z")
    # The lot's venue has cap 1, so the fiscal rule is ALSO violated.
    host_program = create_program("TRANSIT", name="Transit L&F")
    auction = setup_event_with_lot(host_program["id"], venue_cap=1)
    lot = get_lot(auction.lot["id"])

    res = api.add_lot_item(auction.lot["id"], foreign.item["id"],
                           lot["version"], COORD_1)
    validate_error(res, ApiErrorId.ERR_CROSS_PROGRAM_REFERENCE, expected_status=422)
    assert get_item(foreign.item["id"])["status"] == "AUCTION_ELIGIBLE", (
        "a rejected addition leaves the item AUCTION_ELIGIBLE")


def test_lot_add_rejection_leaves_lot_composition_unchanged(api):
    """PRD §3.8: "an empty lot's minimum is zero." PRD §2.6: "if that value
    does not match the parent's current `version` ... the request is rejected
    with the stated error and no change is applied."

    Design: Difficulty/priority_pair_validation_conflict/referential_over_fiscal_on_lot_add
    """
    foreign = setup_auction_eligible_item(
        program_type="FACILITY", declared_value_cents=5005,
        sweep_clock="2026-08-12T00:00:00Z")
    host_program = create_program("TRANSIT", name="Transit L&F")
    auction = setup_event_with_lot(host_program["id"], venue_cap=1)
    lot = get_lot(auction.lot["id"])

    res = api.add_lot_item(auction.lot["id"], foreign.item["id"],
                           lot["version"], COORD_1)
    validate_error(res, ApiErrorId.ERR_CROSS_PROGRAM_REFERENCE, expected_status=422)

    after = get_lot(auction.lot["id"])
    assert after["minimum_bid_cents"] == 0, "no membership row was created"
    rows, meta = validate_paginated(api.list_lot_items(auction.lot["id"], COORD_1))
    assert rows == [] and meta["total_count"] == 0
