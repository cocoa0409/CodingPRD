"""Lot lifecycle (publish, sale, unsold close, removal), lot OCC, and event
settlement (PRD §2.6, §2.10, §3.8)."""
from test_helpers import (
    ApiErrorId,
    add_lot_item,
    create_item,
    create_lot,
    create_program,
    finalize_lot,
    get_item,
    get_lot,
    make_auction_coordinator_headers,
    make_item_auction_eligible,
    publish_lot,
    set_clock,
    settle_event,
    setup_auction_eligible_item,
    setup_event_with_lot,
    setup_lot_with_eligible_item,
    setup_published_lot_with_item,
    validate_error,
    validate_success,
)

COORD_1 = make_auction_coordinator_headers("coord-1")
COORD_2 = make_auction_coordinator_headers("coord-2")


def test_lot_publish_empty_rejected(api):
    """PRD §3.8: "Publishing moves a `DRAFT` lot to `PUBLISHED` and requires at
    least one membership row — publishing an empty lot is rejected with
    `ERR_LOT_EMPTY`."

    Design: Corner/state_machines/lot_publish_empty_rejected
    """
    program = create_program("TRANSIT")
    auction = setup_event_with_lot(program["id"])
    res = api.publish_lot(auction.lot["id"], COORD_1)
    validate_error(res, ApiErrorId.ERR_LOT_EMPTY, expected_status=422)
    assert get_lot(auction.lot["id"])["status"] == "DRAFT"


def test_unsold_escalation_second_cycle_reaches_disposal(api):
    """PRD §3.8: "Closing a lot unsold moves `PUBLISHED` to `CLOSED_UNSOLD` and
    runs the per-item unsold escalation: each lotted item's `unsold_count`
    increments by one, and an item whose count has reached 2 moves to
    `DISPOSAL_PENDING` with `pending_disposal_method` fixed to `DESTRUCTION`,
    while an item still below 2 returns to `AUCTION_ELIGIBLE`."

    Design: Corner/calculations/unsold_threshold_second_cycle
    """
    ctx = setup_published_lot_with_item(declared_value_cents=5005)
    validate_success(api.close_lot_unsold(ctx.lot["id"], COORD_1), 200)
    item = get_item(ctx.item["id"])
    assert item["unsold_count"] == 1 and item["status"] == "AUCTION_ELIGIBLE", (
        "first unsold close returns the item to the auction pool")

    lot2 = create_lot(ctx.event["id"], title="L2")
    add_lot_item(lot2["id"], ctx.item["id"])
    publish_lot(lot2["id"])
    validate_success(api.close_lot_unsold(lot2["id"], COORD_1), 200)

    item = get_item(ctx.item["id"])
    assert item["unsold_count"] == 2
    assert item["status"] == "DISPOSAL_PENDING", (
        "the second unsold close reaches the escalation boundary")
    assert item["pending_disposal_method"] == "DESTRUCTION", (
        "escalation fixes destruction regardless of the policy's AUCTION method")


def test_settlement_ten_percent_band(api):
    """PRD §3.8: "the commission rate is keyed on that gross — 10% when gross
    is below 1,000,000 cents" and "`net_proceeds_cents` is the gross minus the
    total commission."

    Design: Corner/calculations/settlement_lowest_commission_band
    """
    ctx = setup_published_lot_with_item(declared_value_cents=9000)
    finalize_lot(ctx.lot["id"], 500000, coordinator_id="coord-2")
    set_clock("2026-08-21T00:00:00Z")

    settled = settle_event(ctx.event["id"])
    assert settled["status"] == "COMPLETED"
    assert settled["gross_proceeds_cents"] == 500000
    assert settled["total_commission_cents"] == 50000, "10% band on gross 500000"
    assert settled["net_proceeds_cents"] == 450000


def test_settlement_commission_tier_keyed_on_gross(api):
    """PRD §3.8: "`gross_proceeds_cents` is the sum of `hammer_price_cents`
    over the event's `SOLD` lots only" and "the commission rate is keyed on
    that gross — 10% when gross is below 1,000,000 cents, 8% when gross is at
    least 1,000,000 but below 5,000,000 cents".

    Design: Difficulty/combinatorial_formula/auction_settlement_pinned_evaluation_order
    """
    ctx = setup_published_lot_with_item(declared_value_cents=9000)
    finalize_lot(ctx.lot["id"], 600000, coordinator_id="coord-2")

    item_b = create_item(
        ctx.program["id"], ctx.location["id"], declared_value_cents=9000,
        description="item B")
    make_item_auction_eligible(item_b["id"], "2026-08-11T09:00:00Z")
    lot_b = create_lot(ctx.event["id"], title="Lot B")
    add_lot_item(lot_b["id"], item_b["id"])
    publish_lot(lot_b["id"])
    finalize_lot(lot_b["id"], 500000, coordinator_id="coord-2")

    set_clock("2026-08-21T00:00:00Z")
    settled = settle_event(ctx.event["id"])
    assert settled["status"] == "COMPLETED"
    assert settled["gross_proceeds_cents"] == 1100000, "600000 + 500000"
    # Gross 1,100,000 lands in the 8% tier; 48000 + 40000 per-lot.
    assert settled["total_commission_cents"] == 88000
    assert settled["net_proceeds_cents"] == 1012000


def test_settlement_commission_rounded_per_lot_before_summing(api):
    """PRD §3.8: "`total_commission_cents` is the sum over each `SOLD` lot of
    that lot's hammer price multiplied by the rate and rounded half-up to whole
    cents, rounding per lot before summing".

    Design: Difficulty/combinatorial_formula/auction_settlement_pinned_evaluation_order
    """
    ctx = setup_published_lot_with_item(declared_value_cents=9000)
    finalize_lot(ctx.lot["id"], 500005, coordinator_id="coord-2")

    item_b = create_item(
        ctx.program["id"], ctx.location["id"], declared_value_cents=9000,
        description="item B")
    make_item_auction_eligible(item_b["id"], "2026-08-11T09:00:00Z")
    lot_b = create_lot(ctx.event["id"], title="Lot B")
    add_lot_item(lot_b["id"], item_b["id"])
    publish_lot(lot_b["id"])
    finalize_lot(lot_b["id"], 500030, coordinator_id="coord-2")

    set_clock("2026-08-21T00:00:00Z")
    settled = settle_event(ctx.event["id"])
    assert settled["gross_proceeds_cents"] == 1000035, "500005 + 500030"
    # 8% tier. Per-lot: round_half_up(40000.40)=40000, round_half_up(40002.40)=40002.
    # Summing raw products first would yield round_half_up(80002.80)=80003.
    assert settled["total_commission_cents"] == 80002
    assert settled["net_proceeds_cents"] == 920033


def test_finalize_by_lot_creator_segregation_rejected(api):
    """PRD §3.8: "the finalizing coordinator's `X-User-ID` must differ from the
    lot's `created_by` (`ERR_SEGREGATION_OF_DUTIES`)" and "Success stamps
    `hammer_price_cents`, records `finalized_by`, moves the lot to `SOLD`,
    transitions every lotted item from `LOTTED` to `SOLD`".

    Design: Corner/rbac/segregation_finalize_by_lot_creator_rejected
    """
    ctx = setup_published_lot_with_item(declared_value_cents=9000)
    min_bid = get_lot(ctx.lot["id"])["minimum_bid_cents"]
    assert min_bid == 900

    res = api.finalize_lot_sale(ctx.lot["id"], 900, COORD_1)
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)

    sold = finalize_lot(ctx.lot["id"], 900, coordinator_id="coord-2")
    assert sold["status"] == "SOLD"
    assert sold["finalized_by"] == "coord-2"
    assert sold["hammer_price_cents"] == 900
    assert get_item(ctx.item["id"])["status"] == "SOLD"


def test_finalize_below_minimum_bid_rejected(api):
    """PRD §3.8: "the hammer price must be at least the lot's
    `minimum_bid_cents` (`ERR_BELOW_MINIMUM_BID`, HTTP 422)".

    Design: Corner/errors/err_below_minimum_bid_rejected
    """
    ctx = setup_published_lot_with_item(declared_value_cents=9000)
    res = api.finalize_lot_sale(ctx.lot["id"], 100, COORD_2)
    validate_error(res, ApiErrorId.ERR_BELOW_MINIMUM_BID, expected_status=422)
    lot = get_lot(ctx.lot["id"])
    assert lot["status"] == "PUBLISHED"
    assert lot["hammer_price_cents"] is None


def test_lot_add_with_stale_version_rejected(api):
    """PRD §2.6: "Adding an item to an auction lot requires
    `expected_lot_version` matching the lot's current `version`. A mismatch is
    rejected with `ERR_STALE_LOT_VERSION` (HTTP 412), because the lot's
    composition and `minimum_bid_cents` have changed and the coordinator's
    insurance-cap reasoning is stale."

    Design: Corner/cross_cutting_layers/occ_lot_add_stale_version_returns_412
    """
    ctx = setup_auction_eligible_item(declared_value_cents=5000, description="item A")
    item_b = create_item(
        ctx.program["id"], ctx.location["id"], declared_value_cents=5000,
        description="item B")
    make_item_auction_eligible(item_b["id"], "2026-08-11T09:00:00Z")
    auction = setup_event_with_lot(ctx.program["id"])
    stale_version = auction.lot["version"]

    add_lot_item(auction.lot["id"], ctx.item["id"],
                 expected_lot_version=stale_version)
    assert get_lot(auction.lot["id"])["version"] == stale_version + 1

    res = api.add_lot_item(auction.lot["id"], item_b["id"], stale_version, COORD_1)
    validate_error(res, ApiErrorId.ERR_STALE_LOT_VERSION, expected_status=412)
    assert get_item(item_b["id"])["status"] == "AUCTION_ELIGIBLE"


def test_lot_add_sets_minimum_and_lotted_status(api):
    """PRD §3.8: "A successful addition creates the lot-item row with its
    computed `floor_price_cents`, transitions the item from `AUCTION_ELIGIBLE`
    to `LOTTED`, recomputes the lot minimum, increments both the lot's and the
    item's versions, and answers 201 Created."

    Design: Difficulty/compensating_invariant/lot_add_remove_conserves_auction_pool
    """
    ctx = setup_auction_eligible_item(declared_value_cents=5005)
    auction = setup_event_with_lot(ctx.program["id"])
    lot_item = add_lot_item(auction.lot["id"], ctx.item["id"])
    assert lot_item["floor_price_cents"] == 501
    assert get_lot(auction.lot["id"])["minimum_bid_cents"] == 501
    assert get_item(ctx.item["id"])["status"] == "LOTTED"


def test_lot_remove_restores_pool_and_minimum(api):
    """PRD §3.8: "Removing an item from a `DRAFT` lot reverses it without
    penalty: the membership row is deleted, the item returns from `LOTTED` to
    `AUCTION_ELIGIBLE` with no change to `unsold_count`, the minimum is
    recomputed, both versions increment, and the removal answers 204 with no
    body." PRD §3.8: "Manual removal and event cancellation never increment
    `unsold_count` — only an unsold close does."

    Design: Difficulty/compensating_invariant/lot_add_remove_conserves_auction_pool
    """
    ctx = setup_lot_with_eligible_item(declared_value_cents=5005)
    assert get_lot(ctx.lot["id"])["minimum_bid_cents"] == 501

    res = api.remove_lot_item(ctx.lot["id"], ctx.item["id"], COORD_1)
    assert res.status_code == 204, f"removal answers 204, got {res.status_code}"

    lot = get_lot(ctx.lot["id"])
    assert lot["minimum_bid_cents"] == 0, "an emptied lot's minimum recomputes to 0"
    item = get_item(ctx.item["id"])
    assert item["status"] == "AUCTION_ELIGIBLE", (
        "the item returns to the auction pool (pool cardinality conserved)")
    assert item["unsold_count"] == 0, "manual removal is not an unsold cycle"
