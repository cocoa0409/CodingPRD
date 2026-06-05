"""Virtual queue advancement, offer windows, allocation overlap, and expiry.

Covers difficulty queue A rules non_linear_state_machine (queue branch),
boundary_precision_check (empty pool), resource_temporal_overlap, and
cross_entity_state_dependency (offer expiry path).
"""
from test_helpers import (
    validate_success,
    validate_error,
    setup_event_with_tier,
    register_and_verify_fan,
    create_offered_entry,
    create_pending_order,
    join_queue,
    advance,
    set_clock,
    make_fan_headers,
    api_client,
)
from test_helpers.fixtures import PROMOTER


def test_offer_expires_and_releases_reserved_seats(api):
    """PRD §3.3: "any entry in OFFERED whose offer_expires_at has passed (the
    current time is strictly later than offer_expires_at) transitions
    OFFERED → EXPIRED, and its reserved seats are released — reserved_count is
    decremented by that entry's requested_qty and the tier's version is
    incremented — returning the seats to the finite pool for the next waiting
    entry."

    Design: Difficulty/non_linear_state_machine/queue_entry_branching_offered_to_purchased_or_expired
    """
    set_clock("2026-06-01T00:00:00Z")
    event, tier = setup_event_with_tier(phase="GENERAL")
    fan = register_and_verify_fan("g@x.com", device="dev-g")
    qe = create_offered_entry(event, tier, fan, requested_qty=1)
    assert qe["status"] == "OFFERED"
    # Advance the clock past the 120s offer window, then sweep.
    set_clock("2026-06-01T01:00:00Z")
    advance(event["id"], tier_id=tier["id"], max_offers=5)
    refreshed = validate_success(api.get_queue_entry(qe["id"], make_fan_headers(fan["id"])), 200)
    assert refreshed["status"] == "EXPIRED", refreshed
    tier_after = validate_success(api.get_price_tier(tier["id"], PROMOTER), 200)
    assert tier_after["reserved_count"] == 0, tier_after


def test_offer_redeemed_to_purchased_on_pay(api):
    """PRD §3.4: "Payment is a depth-three cascade. The order moves
    PENDING → PAID; the linked queue entry moves to PURCHASED".

    The OFFERED entry forks to PURCHASED when its order is paid (the other
    branch being EXPIRED).

    Design: Difficulty/non_linear_state_machine/queue_entry_branching_offered_to_purchased_or_expired
    """
    event, tier = setup_event_with_tier(phase="GENERAL")
    fan = register_and_verify_fan("g2@x.com", device="dev-g2")
    qe, order = create_pending_order(event, tier, fan, requested_qty=1)
    validate_success(api.pay_order(
        order["id"], {"expected_order_version": order["version"]},
        make_fan_headers(fan["id"]),
    ), 200)
    refreshed = validate_success(api.get_queue_entry(qe["id"], make_fan_headers(fan["id"])), 200)
    assert refreshed["status"] == "PURCHASED", refreshed


def test_advance_queue_empty_waiting_pool_returns_empty(api):
    """PRD §3.3: "it offers seats to the most senior admittable waiting entries:
    an entry transitions WAITING → OFFERED only when its event is in PRESALE or
    GENERAL, it holds the lowest queue_position among WAITING entries for its
    tier (by created_at ascending) whose requested_qty still fits, and the
    tier's remaining capacity ... is at least the entry's requested_qty."

    With no WAITING entries, advancing offers nothing and changes no counters.

    Design: Difficulty/boundary_precision_check/advance_queue_empty_waiting_pool_returns_empty
    """
    event, tier = setup_event_with_tier(phase="GENERAL")
    res = api.advance_queue(event["id"], {"tier_id": tier["id"], "max_offers": 5}, PROMOTER)
    offered = validate_success(res, 200)
    assert isinstance(offered, list), offered
    assert len(offered) == 0, offered
    tier_after = validate_success(api.get_price_tier(tier["id"], PROMOTER), 200)
    assert tier_after["reserved_count"] == 0, tier_after


def test_allocation_overlap_offers_first_blocks_second(api):
    """PRD §3.3: "the tier's remaining capacity — allocation minus the sum of
    reserved_count and sold_count — is at least the entry's requested_qty."
    PRD §3.3: "An offer that would push a tier's occupancy beyond its allocation
    is barred with ERR_ALLOCATION_EXCEEDED."

    Tier allocation=2: a first entry holding 2 seats is offered; a second entry
    requesting 1 more cannot be offered and stays WAITING.

    Design: Difficulty/resource_temporal_overlap/tier_allocation_capacity_overlap
    """
    event, tier = setup_event_with_tier(phase="GENERAL", allocation=2)
    fan1 = register_and_verify_fan("u1@x.com", device="dev-u1")
    fan2 = register_and_verify_fan("u2@x.com", device="dev-u2")
    qe1 = join_queue(event, tier, fan1, requested_qty=2)
    qe2 = join_queue(event, tier, fan2, requested_qty=1)
    advance(event["id"], tier_id=tier["id"], max_offers=5)
    e1 = validate_success(api.get_queue_entry(qe1["id"], make_fan_headers(fan1["id"])), 200)
    e2 = validate_success(api.get_queue_entry(qe2["id"], make_fan_headers(fan2["id"])), 200)
    assert e1["status"] == "OFFERED", e1
    assert e2["status"] == "WAITING", e2
    tier_after = validate_success(api.get_price_tier(tier["id"], PROMOTER), 200)
    assert tier_after["reserved_count"] == 2, tier_after


def test_redeem_after_offer_window_lapsed_rejected(api):
    """PRD §3.4: "Redeeming an entry whose offer_expires_at has already passed is
    rejected with ERR_OFFER_EXPIRED."

    Clock advanced strictly past offer_expires_at (without a sweep); redemption
    via POST /orders is rejected.

    Design: Difficulty/resource_temporal_overlap/ticket_offer_window_temporal_expiry
    """
    set_clock("2026-06-01T00:00:00Z")
    event, tier = setup_event_with_tier(phase="GENERAL")
    fan = register_and_verify_fan("v@x.com", device="dev-v")
    qe = create_offered_entry(event, tier, fan, requested_qty=1)
    assert qe["status"] == "OFFERED"
    set_clock("2026-06-01T02:00:00Z")
    res = api.create_order(
        {"queue_entry_id": qe["id"], "fan_id": fan["id"], "tier_id": tier["id"], "quantity": 1},
        make_fan_headers(fan["id"]),
    )
    validate_error(res, "ERR_OFFER_EXPIRED")


def test_pay_after_offer_expired_rejected(api):
    """PRD §3.4: "the order must be PENDING, its linked queue entry must still be
    OFFERED and not expired, and the version must match".
    PRD §3.4: "Redeeming an entry whose offer_expires_at has already passed is
    rejected with ERR_OFFER_EXPIRED."

    A PENDING order whose linked queue entry's offer has expired (after a clock
    advance + sweep) cannot be paid.

    Design: Difficulty/cross_entity_state_dependency/order_pay_requires_queue_entry_offered
    """
    set_clock("2026-06-01T00:00:00Z")
    event, tier = setup_event_with_tier(phase="GENERAL")
    fan = register_and_verify_fan("m@x.com", device="dev-m")
    qe, order = create_pending_order(event, tier, fan, requested_qty=1)
    set_clock("2026-06-01T01:00:00Z")
    advance(event["id"], tier_id=tier["id"], max_offers=5)
    res = api.pay_order(
        order["id"], {"expected_order_version": order["version"]},
        make_fan_headers(fan["id"]),
    )
    validate_error(res, "ERR_OFFER_EXPIRED")
    refreshed = validate_success(api.get_order(order["id"], make_fan_headers(fan["id"])), 200)
    assert refreshed["status"] == "PENDING", refreshed
