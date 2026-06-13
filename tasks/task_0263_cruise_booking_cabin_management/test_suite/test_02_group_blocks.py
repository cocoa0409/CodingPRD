"""Group blocks: holding, recall cycle, release, materialization, and cutoff.

Covers the GroupBlock non-linear NEGOTIATING -> HELD -> NEGOTIATING cycle,
the default discount, insufficient-inventory and block-has-bookings errors,
group-block-not-held on booking create, and the clock-driven cutoff release.
"""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, get_success_data,
    ApiErrorId, TEST_USERS,
    create_group_block_payload,
    setup_open_sailing, setup_held_group_block, create_group_block,
    create_deposit_held_booking, set_clock,
)

RM = TEST_USERS["revenue_manager_headers"]


# ===========================================================================
# Difficulty: GroupBlock HELD -> NEGOTIATING recall cycle
# ===========================================================================
def test_recall_held_block_returns_to_negotiating(api):
    """PRD 3.2: "A `RevenueManager` may recall a held block (`HELD → NEGOTIATING`)
    only when its `materialized_count` is 0 ... at which point every `BLOCKED`
    cabin bearing this `group_block_id` returns to `AVAILABLE` with its
    `group_block_id` cleared, the category's `blocked_cabins` falls and
    `available_cabins` rises by the freed count, and the block's `blocked_count`
    returns to 0."

    Design: Difficulty/non_linear_state_machine/group_block_held_recall_back_to_negotiating_cycle
    """
    sailing, category, _cabins, block = setup_held_group_block(num_cabins=4, block_size=2)
    resp = api.recall_group_block(block["id"], RM)
    data = validate_success(resp)
    assert data["status"] == "NEGOTIATING"
    assert data["blocked_count"] == 0


def test_recall_held_block_restores_category_counts(api):
    """PRD 3.2: "every `BLOCKED` cabin bearing this `group_block_id` returns to
    `AVAILABLE` with its `group_block_id` cleared, the category's `blocked_cabins`
    falls and `available_cabins` rises by the freed count".

    Design: Difficulty/non_linear_state_machine/group_block_held_recall_back_to_negotiating_cycle
    """
    sailing, category, _cabins, block = setup_held_group_block(num_cabins=4, block_size=2)
    get_success_data(api.recall_group_block(block["id"], RM))
    after = get_success_data(api.get_cabin_category(category["id"], RM))
    assert after["available_cabins"] == 4
    assert after["blocked_cabins"] == 0


# ===========================================================================
# Corner: defaults, errors, cutoff release
# ===========================================================================
def test_group_block_discount_default_applied(api):
    """PRD 2.9: "A group block carries a `group_discount_pct` expressed as a
    fraction between 0 and 0.5 inclusive, defaulting to 0.15 when omitted at
    creation".

    Design: Corner/entities/group_block_discount_pct_default_applied
    """
    sailing, category, _cabins = setup_open_sailing(num_cabins=2)
    payload = create_group_block_payload(sailing["id"], category["id"], block_size=2)
    del payload["group_discount_pct"]
    resp = api.create_group_block(payload, RM)
    data = validate_success(resp, expected_status=201)
    assert data["group_discount_pct"] == 0.15


def test_group_block_not_held_on_booking_create(api):
    """PRD 3.3: "When a `group_block_id` is supplied, the referenced block must be in
    `HELD` or `PARTIALLY_MATERIALIZED` status, or the creation is rejected with
    `ERR_GROUP_BLOCK_NOT_HELD`."

    Design: Corner/errors/group_block_not_held_on_booking_create
    """
    sailing, category, _cabins = setup_open_sailing(num_cabins=1)
    block = create_group_block(sailing["id"], category["id"], block_size=1)  # NEGOTIATING
    from test_helpers import create_booking_payload, make_guest_user_headers
    resp = api.create_booking(
        create_booking_payload(sailing["id"], category["id"], "guest-c15",
                               sailing["version"], group_block_id=block["id"]),
        make_guest_user_headers("guest-c15"),
    )
    validate_error(resp, ApiErrorId.ERR_GROUP_BLOCK_NOT_HELD.value)


def test_insufficient_inventory_on_group_block_hold(api):
    """PRD 3.2: "It is permitted only while the parent sailing is `OPEN` or `CLOSED`
    (otherwise `ERR_SAILING_NOT_BOOKABLE`) and only when the category's
    `available_cabins` is at least `block_size` (otherwise
    `ERR_INSUFFICIENT_INVENTORY`)."

    Design: Corner/errors/insufficient_inventory_on_group_block_hold
    """
    sailing, category, _cabins = setup_open_sailing(num_cabins=2)
    block = create_group_block(sailing["id"], category["id"], block_size=3)
    resp = api.hold_group_block(block["id"], RM)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY.value)


def test_block_recall_with_materialized_bookings_rejected(api):
    """PRD 3.2: "A `RevenueManager` may recall a held block (`HELD → NEGOTIATING`)
    only when its `materialized_count` is 0 — a block with materialized bookings is
    rejected with `ERR_BLOCK_HAS_BOOKINGS`".

    Design: Corner/errors/block_recall_with_materialized_bookings_rejected
    """
    sailing, category, _cabins, block = setup_held_group_block(num_cabins=2, block_size=2)
    create_deposit_held_booking(
        "guest-c16", num_guests=2, sailing=sailing, category=category,
        group_block_id=block["id"], deposit_cents=75000,
    )
    resp = api.recall_group_block(block["id"], RM)
    # Materializing the booking auto-transitions the block HELD -> PARTIALLY_MATERIALIZED
    # (PRD 3.4). The recall edge is defined HELD -> NEGOTIATING; PRD 2.5 orders
    # state-transition legality (ERR_INVALID_STATE) strictly before domain business
    # constraints (ERR_BLOCK_HAS_BOOKINGS), so both error_ids are PRD-faithful here.
    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_BLOCK_HAS_BOOKINGS.value, ApiErrorId.ERR_INVALID_STATE.value],
    )


def test_clock_advance_releases_group_block_past_cutoff(api):
    """PRD 3.2: "When the simulated clock advances past a block's
    `release_cutoff_date`, a block that is `HELD` or `PARTIALLY_MATERIALIZED`
    transitions to `RELEASED`: every still-`BLOCKED` (unmaterialized) cabin of the
    block returns to `AVAILABLE` and the category counts are restored".

    Design: Corner/cross_cutting_complexity_layers/clock_advance_releases_group_block_past_cutoff
    """
    set_clock("2026-06-18T16:00:00Z")
    sailing, category, _cabins, block = setup_held_group_block(
        num_cabins=2, block_size=2,
    )
    set_clock("2026-08-02T00:00:00Z")  # past release_cutoff_date 2026-08-01
    blk = get_success_data(api.get_group_block(block["id"], RM))
    assert blk["status"] == "RELEASED"
    cat = get_success_data(api.get_cabin_category(category["id"], RM))
    assert cat["available_cabins"] == 2
    assert cat["blocked_cabins"] == 0
