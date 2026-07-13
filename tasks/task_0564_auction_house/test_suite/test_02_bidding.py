"""Bid placement: ownership, authentication, optimistic concurrency, escalating
increments, winner selection, deposit gating, and validation precedence.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    NON_EXISTENT_UUID,
    create_bid_payload,
    create_lot_payload,
    setup_open_lot,
    make_saleroom,
    make_auction,
    make_consignor,
    make_accepted_consignment,
    make_lot,
    make_bidder,
    place_bid,
    make_bidder_headers,
    TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]


# ─── Corner: existence, ownership, authentication on bid placement ───────

def test_bid_unknown_bidder_returns_not_found(api):
    """PRD §2.7: "The first identifier that does not resolve produces the
    corresponding not-found error (HTTP 404) before any later resolution or
    business rule is attempted."

    Design: Corner/entities/corner_bid_unknown_bidder_returns_404
    """
    bag = setup_open_lot(starting_bid_cents=100_000)
    res = api.place_bid(
        bag["lot"]["id"],
        create_bid_payload(NON_EXISTENT_UUID, 100_000, bag["lot_version"]),
        make_bidder_headers(NON_EXISTENT_UUID),
    )
    validate_error(res, "ERR_BIDDER_NOT_FOUND")


def test_bid_wrong_owner_returns_forbidden(api):
    """PRD §2.1: "When an entity-backed principal targets a resource they do not
    own, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/corner_bid_wrong_owner_returns_403
    """
    bag = setup_open_lot(starting_bid_cents=100_000)
    bd1 = make_bidder(display_name="B1", email="b1@x.com", paddle_number="P1")
    bd2 = make_bidder(display_name="B2", email="b2@x.com", paddle_number="P2")
    res = api.place_bid(
        bag["lot"]["id"],
        create_bid_payload(bd1["id"], 100_000, bag["lot_version"]),
        make_bidder_headers(bd2["id"]),
    )
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


def test_unauthenticated_bid_returns_401(api):
    """PRD §2.1: "A request missing either header, or presenting a role the server
    does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/corner_unauthenticated_bid_returns_401
    """
    bag = setup_open_lot(starting_bid_cents=100_000)
    res = api.place_bid(
        bag["lot"]["id"],
        create_bid_payload(NON_EXISTENT_UUID, 100_000, bag["lot_version"]),
        {},
    )
    validate_error(res, "ERR_UNAUTHENTICATED")


# ─── Corner: optimistic concurrency on Lot.version ───────────────────────

def test_stale_lot_version_bid_rejected(api):
    """PRD §2.8: "If `expected_lot_version` does not equal the lot's current
    `version`, the bid is rejected with `ERR_STALE_VERSION` (HTTP 412) and no bid
    is created."

    Design: Corner/cross_cutting/corner_bid_stale_lot_version_returns_412
    """
    bag = setup_open_lot(starting_bid_cents=50_000)
    stale_version = bag["lot_version"]
    bd1 = make_bidder(display_name="B1", email="b1@x.com", paddle_number="P1")
    bd2 = make_bidder(display_name="B2", email="b2@x.com", paddle_number="P2")
    place_bid(bag["lot"]["id"], bd1["id"], 50_000, stale_version)  # bumps Lot.version
    res = api.place_bid(
        bag["lot"]["id"],
        create_bid_payload(bd2["id"], 60_000, stale_version),
        make_bidder_headers(bd2["id"]),
    )
    validate_error(res, "ERR_STALE_VERSION")


def test_accepted_bid_bumps_lot_version(api):
    """PRD §2.8: "When a competing bid is accepted, it supersedes the prior high
    bid and increments the lot's `version`".
    PRD §3.4: "the lot's `current_high_bid_cents` and `current_high_bid_id` are
    updated to reflect the new high, incrementing the lot's `version` by one."

    Design: Corner/cross_cutting/corner_bid_bumps_lot_version
    """
    bag = setup_open_lot(starting_bid_cents=50_000)
    assert bag["lot_version"] == 2
    bd1 = make_bidder(display_name="B1", email="b1@x.com", paddle_number="P1")
    place_bid(bag["lot"]["id"], bd1["id"], 50_000, bag["lot_version"])
    lot = validate_success(api.get_lot(bag["lot"]["id"], STAFF), 200)
    assert lot["version"] == 3
    assert lot["current_high_bid_cents"] == 50_000


# ─── Corner: winner selection + list pagination ──────────────────────────

def test_highest_active_bid_wins_at_hammer(api):
    """PRD §3.5: "The winner is the `ACTIVE` bid with the greatest `amount_cents`;
    ties are broken in favor of the earliest `created_at`, and the bid's `id` is
    never used as a tie-break input."
    PRD §3.5: "Hammering advances the lot `OPEN → HAMMERED`, transitions the
    winning bid `ACTIVE → WINNING`, transitions every other `ACTIVE` bid on the
    lot `ACTIVE → OUTBID`, and records `hammer_price_cents` (the winner's
    `amount_cents`) and `winning_bid_id` (the winner's `id`) on the lot."

    Design: Corner/calculations/corner_winning_highest_active_bid_wins
    """
    bag = setup_open_lot(starting_bid_cents=100_000, estimate_low_cents=90_000)
    bd1 = make_bidder(display_name="B1", email="b1@x.com", paddle_number="P1")
    bd2 = make_bidder(display_name="B2", email="b2@x.com", paddle_number="P2")
    bid_a = place_bid(bag["lot"]["id"], bd1["id"], 100_000, bag["lot_version"])
    v2 = validate_success(api.get_lot(bag["lot"]["id"], STAFF), 200)["version"]
    bid_b = place_bid(bag["lot"]["id"], bd2["id"], 120_000, v2)

    lot = validate_success(api.hammer_lot(bag["lot"]["id"], STAFF), 200)
    assert lot["hammer_price_cents"] == 120_000
    assert lot["winning_bid_id"] == bid_b["id"]
    assert validate_success(api.get_bid(bid_b["id"], STAFF), 200)["status"] == "WINNING"
    assert validate_success(api.get_bid(bid_a["id"], STAFF), 200)["status"] == "OUTBID"


def test_list_lots_pagination_reports_total_and_has_more(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned".
    PRD §2.3: "Every list response reports `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/cross_cutting/corner_list_lots_pagination
    """
    saleroom = make_saleroom()
    auction = make_auction(saleroom["id"])
    consignor = make_consignor()
    consignment = make_accepted_consignment(consignor["id"])
    make_lot(consignment["id"], auction["id"], title="L1", lot_number=1)
    make_lot(consignment["id"], auction["id"], title="L2", lot_number=2)
    data, meta = validate_paginated(
        api.list_lots(STAFF, params={"auction_id": auction["id"], "limit": 1, "offset": 0})
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ─── Difficulty: bid-increment >= boundary ───────────────────────────────

def _open_lot_with_high_50000(api):
    """OPEN lot whose current high is 50000, so next minimum bid is 55000."""
    bag = setup_open_lot(starting_bid_cents=50_000,
                         estimate_low_cents=40_000, estimate_high_cents=90_000)
    bd1 = make_bidder(display_name="B1", email="b1@x.com", paddle_number="P1")
    place_bid(bag["lot"]["id"], bd1["id"], 50_000, bag["lot_version"])
    lot = validate_success(api.get_lot(bag["lot"]["id"], STAFF), 200)
    assert lot["current_high_bid_cents"] == 50_000
    return bag, lot["version"]


def test_bid_below_next_minimum_rejected(api):
    """PRD §3.4: "when it is at least 10,000 but below 100,000 cents the increment
    is 5,000 cents".
    PRD §3.4: "A bid is accepted only if `amount_cents` is greater than or equal
    to this next minimum bid; a bid below it is rejected with `ERR_BID_TOO_LOW`
    (HTTP 409)."

    Design: Difficulty/boundary_precision_check/bp_bid_increment_exact_next_min
    """
    bag, version = _open_lot_with_high_50000(api)
    bd2 = make_bidder(display_name="B2", email="b2@x.com", paddle_number="P2")
    res = api.place_bid(
        bag["lot"]["id"],
        create_bid_payload(bd2["id"], 54_999, version),
        make_bidder_headers(bd2["id"]),
    )
    validate_error(res, "ERR_BID_TOO_LOW")


def test_bid_exactly_next_minimum_accepted(api):
    """PRD §3.4: "The next minimum bid is the current high plus that increment. A
    bid is accepted only if `amount_cents` is greater than or equal to this next
    minimum bid; a bid below it is rejected with `ERR_BID_TOO_LOW` (HTTP 409)."
    PRD §3.4: "An accepted bid is created in `status` `ACTIVE`."

    Design: Difficulty/boundary_precision_check/bp_bid_increment_exact_next_min
    """
    bag, version = _open_lot_with_high_50000(api)
    bd2 = make_bidder(display_name="B2", email="b2@x.com", paddle_number="P2")
    res = api.place_bid(
        bag["lot"]["id"],
        create_bid_payload(bd2["id"], 55_000, version),
        make_bidder_headers(bd2["id"]),
    )
    data = validate_success(res, 201)
    assert data["status"] == "ACTIVE"


# ─── Difficulty: state check (lot not open) beats bid-too-low ────────────

def test_lot_not_open_beats_low_bid(api):
    """PRD §2.9: "(7) the target resource is in the correct state for the
    transition, else the applicable state error; and finally the endpoint-specific
    business rules described throughout §3."
    PRD §3.4: "a bid against a lot in any other `sale_status` is rejected with
    `ERR_LOT_NOT_OPEN` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/pc_lot_not_open_beats_bid_too_low
    """
    # Lot cataloged but never opened; a below-minimum bid also violates increment.
    saleroom = make_saleroom()
    auction = make_auction(saleroom["id"])
    consignor = make_consignor()
    consignment = make_accepted_consignment(consignor["id"])
    lot = make_lot(consignment["id"], auction["id"], starting_bid_cents=50_000)
    bidder = make_bidder()
    res = api.place_bid(
        lot["id"],
        create_bid_payload(bidder["id"], 100, lot["version"]),
        make_bidder_headers(bidder["id"]),
    )
    validate_error(res, "ERR_LOT_NOT_OPEN")


def test_low_bid_surfaces_when_lot_open(api):
    """PRD §2.9: "(7) the target resource is in the correct state for the
    transition, else the applicable state error; and finally the endpoint-specific
    business rules described throughout §3."
    PRD §3.4: "A bid is accepted only if `amount_cents` is greater than or equal
    to this next minimum bid; a bid below it is rejected with `ERR_BID_TOO_LOW`
    (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/pc_lot_not_open_beats_bid_too_low
    """
    # Same below-minimum bid, but the lot IS open, so the lower-priority check fires.
    bag = setup_open_lot(starting_bid_cents=50_000)
    bidder = make_bidder()
    res = api.place_bid(
        bag["lot"]["id"],
        create_bid_payload(bidder["id"], 100, bag["lot_version"]),
        make_bidder_headers(bidder["id"]),
    )
    validate_error(res, "ERR_BID_TOO_LOW")


# ─── Difficulty: bidder suspension beats insufficient deposit ────────────

def test_suspended_bidder_beats_insufficient_deposit(api):
    """PRD §3.4: "Once the lot's state is confirmed, the bidder's standing is
    checked: a `SUSPENDED` bidder may not bid, and the attempt is rejected with
    `ERR_BIDDER_SUSPENDED` (HTTP 403)."
    PRD §3.4: "These checks apply in the order given: the stale-version guard
    first, then lot state, then bidder suspension, then the minimum-increment
    check, then the deposit gate."

    Design: Difficulty/priority_pair_validation_conflict/pc_bidder_suspended_beats_insufficient_deposit
    """
    bag = setup_open_lot(starting_bid_cents=6_000_000,
                         estimate_low_cents=5_000_000, estimate_high_cents=9_000_000)
    bidder = make_bidder(deposit_cents=0)
    validate_success(api.suspend_bidder(bidder["id"], STAFF), 200)
    res = api.place_bid(
        bag["lot"]["id"],
        create_bid_payload(bidder["id"], 6_000_000, bag["lot_version"]),
        make_bidder_headers(bidder["id"]),
    )
    validate_error(res, "ERR_BIDDER_SUSPENDED")


def test_insufficient_deposit_surfaces_for_active_bidder(api):
    """PRD §3.4: "When `amount_cents` is at least the high-value threshold of
    1,000,000 cents (`HIGH_VALUE_LOT_CENTS`), the placing bidder's `deposit_cents`
    must be at least 100,000 cents (`MIN_DEPOSIT_FOR_HIGH_VALUE_CENTS`); if the
    deposit falls short, the bid is rejected with `ERR_INSUFFICIENT_DEPOSIT`
    (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/pc_bidder_suspended_beats_insufficient_deposit
    """
    # Active bidder, so suspension passes and the deposit gate (lower priority) fires.
    bag = setup_open_lot(starting_bid_cents=6_000_000,
                         estimate_low_cents=5_000_000, estimate_high_cents=9_000_000)
    bidder = make_bidder(deposit_cents=0)
    res = api.place_bid(
        bag["lot"]["id"],
        create_bid_payload(bidder["id"], 6_000_000, bag["lot_version"]),
        make_bidder_headers(bidder["id"]),
    )
    validate_error(res, "ERR_INSUFFICIENT_DEPOSIT")
