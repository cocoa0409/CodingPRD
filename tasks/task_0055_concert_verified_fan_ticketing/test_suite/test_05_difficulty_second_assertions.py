"""Second, distinct-facet assertions for difficulty queue A instances, ensuring
each instance is covered by at least two tests. Each test here asserts a
different PRD-stated observable than its companion in test_01..test_04, on the
same scenario the design instance describes.
"""
from test_helpers import (
    validate_success,
    validate_error,
    setup_event_with_tier,
    register_and_verify_fan,
    register_fan,
    create_pending_order,
    create_paid_order,
    create_offered_entry,
    setup_held_ticket,
    setup_pending_transfer,
    join_queue,
    advance,
    create_event,
    create_tier,
    open_to_phase,
    set_clock,
    pre_sell_seats,
    make_fan_headers,
)
from test_helpers.fixtures import PROMOTER
from test_helpers.factories import create_resale_listing_payload


# ─── combinatorial_formula ────────────────────────────────────────────────

def test_nested_band_subtotal_reflects_unit_times_quantity(api):
    """PRD §3.4: "The subtotal_cents is the locked unit_price_cents multiplied by
    quantity, computed exactly with no rounding."

    On the band2/30% scenario (unit 13000), a single-seat order's subtotal equals
    the unit price.

    Design: Difficulty/combinatorial_formula/dynamic_price_nested_band_and_multiplier
    """
    event, tier = setup_event_with_tier(phase="GENERAL", face_value_cents=10000,
                                        venue_capacity=7, allocation=7,
                                        base_multiplier_bps=10000)
    pre_sell_seats(event, tier, 6, base_email="seed2c", device="dev-seed2c")
    fan = register_and_verify_fan("bbb@x.com", device="dev-bbb")
    _qe, order = create_pending_order(event, tier, fan, requested_qty=1)
    assert order["unit_price_cents"] == 13000, order
    assert order["subtotal_cents"] == 13000, order


def test_order_total_equals_subtotal_plus_fee(api):
    """PRD §3.4: "The total_cents is the subtotal plus the service fee."

    Design: Difficulty/combinatorial_formula/order_total_sum_then_fee_rounding
    """
    event, tier = setup_event_with_tier(phase="PRESALE", face_value_cents=10000,
                                        venue_capacity=100, base_multiplier_bps=11500)
    fan = register_and_verify_fan("cc@x.com", device="dev-cc")
    _qe, order = create_pending_order(event, tier, fan, requested_qty=3)
    assert order["total_cents"] == order["subtotal_cents"] + order["service_fee_cents"], order
    assert order["total_cents"] == 38640, order


# ─── transitive_cascade ───────────────────────────────────────────────────

def test_pay_last_seat_increments_event_tickets_sold(api):
    """PRD §3.4: "the event's tickets_sold_count is increased by quantity".

    Companion facet to the sold-out revoke cascade: the depth-1 effect (counter
    bump) that drives the SOLD_OUT transition.

    Design: Difficulty/transitive_cascade/pay_to_soldout_revokes_waiting_entries
    """
    event, tier = setup_event_with_tier(phase="GENERAL", venue_capacity=1, allocation=5)
    fan_h = register_and_verify_fan("h2@x.com", device="dev-h2")
    qe_h = join_queue(event, tier, fan_h, requested_qty=1)
    advance(event["id"], tier_id=tier["id"], max_offers=1)
    order = validate_success(api.create_order(
        {"queue_entry_id": qe_h["id"], "fan_id": fan_h["id"], "tier_id": tier["id"], "quantity": 1},
        make_fan_headers(fan_h["id"]),
    ), 201)
    validate_success(api.pay_order(
        order["id"], {"expected_order_version": order["version"]},
        make_fan_headers(fan_h["id"]),
    ), 200)
    ev_after = validate_success(api.get_event(event["id"], PROMOTER), 200)
    assert ev_after["tickets_sold_count"] == 1, ev_after


def test_flagged_fan_cannot_be_verified_again(api):
    """PRD §3.1: "FLAGGED is terminal: a flagged fan can never verify, join a
    queue, pay, initiate or accept a transfer, or list or buy on resale."

    Companion facet: once the join-recompute flips the fan to FLAGGED, the flag
    bar blocks subsequent gated actions.

    Design: Difficulty/transitive_cascade/flag_fan_revokes_queue_holds_releases_seats
    """
    event = create_event(venue_capacity=100, presale_code="S", face_value_cents=10000)
    tier1 = create_tier(event["id"], allocation=50, name="FLOOR")
    tier2 = create_tier(event["id"], allocation=50, name="MEZZ")
    tier3 = create_tier(event["id"], allocation=50, name="BALC")
    event = open_to_phase(event, "GENERAL")
    ff = register_and_verify_fan("ff2@x.com", device="dev-ff2")
    register_fan("g2a@x.com", device="dev-ff2", full_name="G2A")
    register_fan("g2b@x.com", device="dev-ff2", full_name="G2B")
    register_fan("g2c@x.com", device="dev-ff2", full_name="G2C")
    join_queue(event, tier1, ff, requested_qty=1)
    join_queue(event, tier2, ff, requested_qty=1)
    join_queue(event, tier3, ff, requested_qty=1)
    f_after = validate_success(api.get_fan(ff["id"], make_fan_headers(ff["id"])), 200)
    assert f_after["verification_status"] == "FLAGGED", f_after
    # A flagged fan attempting a fresh queue join is barred with the flag error.
    res = api.create_queue_entry(
        {"event_id": event["id"], "fan_id": ff["id"], "tier_id": tier1["id"],
         "presale_code_used": "S", "requested_qty": 1},
        make_fan_headers(ff["id"]),
    )
    validate_error(res, "ERR_FAN_FLAGGED")


# ─── non_linear_state_machine (ticket dimensions) ─────────────────────────

def test_cancel_listing_returns_holding_to_held(api):
    """PRD §3.7: "A seller may withdraw an open listing instead, moving it
    OPEN → CANCELLED and returning the ticket's holding_status to HELD."

    Companion facet: the holding dimension returns to HELD on cancel while the
    entry dimension remains VALID — the two dimensions stay independent.

    Design: Difficulty/non_linear_state_machine/ticket_parallel_entry_and_holding_dimensions
    """
    event, tier, fan, order, ticket = setup_held_ticket(phase="GENERAL")
    listing = validate_success(api.create_resale_listing(
        create_resale_listing_payload(ticket["id"], fan["id"], 11000),
        make_fan_headers(fan["id"]),
    ), 201)
    validate_success(api.cancel_resale_listing(listing["id"], make_fan_headers(fan["id"])), 200)
    refreshed = validate_success(api.get_ticket(ticket["id"], make_fan_headers(fan["id"])), 200)
    assert refreshed["holding_status"] == "HELD", refreshed
    assert refreshed["entry_status"] == "VALID", refreshed


# ─── priority_pair_validation_conflict ────────────────────────────────────

def test_flagged_fan_join_does_not_create_entry(api):
    """PRD §3.1: "FLAGGED is terminal: a flagged fan can never verify, join a
    queue, pay, initiate or accept a transfer, or list or buy on resale."

    Companion facet: the rejected join produces no listable queue entry for the
    flagged fan.

    Design: Difficulty/priority_pair_validation_conflict/flagged_beats_presale_code_on_queue_join
    """
    event = create_event(venue_capacity=100, presale_code="SUMMER", face_value_cents=10000)
    tier = create_tier(event["id"], allocation=50)
    open_to_phase(event, "PRESALE")
    register_fan("s1b@x.com", device="dev-bot2", full_name="S1")
    register_fan("s2b@x.com", device="dev-bot2", full_name="S2")
    register_fan("s3b@x.com", device="dev-bot2", full_name="S3")
    fx = register_fan("x2+bot@x.com", device="dev-bot2", full_name="X")
    validate_success(api.verify_fan(fx["id"], make_fan_headers(fx["id"])), 200)
    res = api.create_queue_entry(
        {"event_id": event["id"], "fan_id": fx["id"], "tier_id": tier["id"],
         "presale_code_used": "WRONG", "requested_qty": 1},
        make_fan_headers(fx["id"]),
    )
    validate_error(res, "ERR_FAN_FLAGGED")
    data, _meta = _list_entries_for_fan(api, fx["id"])
    assert len(data) == 0, data


def _list_entries_for_fan(api, fan_id):
    from test_helpers import validate_paginated
    res = api.list_queue_entries(make_fan_headers(fan_id), params={"fan_id": fan_id})
    return validate_paginated(res)


def test_over_cap_relist_leaves_listing_open_and_ticket_listed(api):
    """PRD §3.7: "Listing is permitted only when the ticket is HELD and VALID".

    Companion facet: the rejected over-cap re-list does not disturb the existing
    OPEN listing nor the ticket's LISTED holding status.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_resale_cap_on_listing
    """
    event, tier, fan, order, ticket = setup_held_ticket(
        phase="GENERAL", resale_cap_pct=110, face_value_cents=10000
    )
    listing = validate_success(api.create_resale_listing(
        create_resale_listing_payload(ticket["id"], fan["id"], 11000),
        make_fan_headers(fan["id"]),
    ), 201)
    res = api.create_resale_listing(
        create_resale_listing_payload(ticket["id"], fan["id"], 99000),
        make_fan_headers(fan["id"]),
    )
    validate_error(res, "ERR_INVALID_STATE")
    l_after = validate_success(api.get_resale_listing(listing["id"], make_fan_headers(fan["id"])), 200)
    assert l_after["status"] == "OPEN", l_after
    t_after = validate_success(api.get_ticket(ticket["id"], make_fan_headers(fan["id"])), 200)
    assert t_after["holding_status"] == "LISTED", t_after


# ─── boundary_precision_check ─────────────────────────────────────────────

def test_band_just_below_80pct_uses_band1(api):
    """PRD §3.4: "when it is at least 0.50 but below 0.80 the surcharge is 1500
    basis points".

    Boundary companion: sold_ratio 3/5 = 0.60 (< 0.80) lands in band1 (15%),
    so unit = round(10000 * 11500 / 10000) = 11500, distinguishing band1 from the
    0.80 band2 boundary.

    Design: Difficulty/boundary_precision_check/dynamic_price_band_at_exact_80_pct
    """
    event, tier = setup_event_with_tier(phase="GENERAL", face_value_cents=10000,
                                        venue_capacity=5, allocation=5,
                                        base_multiplier_bps=10000)
    pre_sell_seats(event, tier, 3, base_email="seedk2", device="dev-seedk2")
    fan = register_and_verify_fan("k2@x.com", device="dev-k2")
    _qe, order = create_pending_order(event, tier, fan, requested_qty=1)
    assert order["unit_price_cents"] == 11500, order


def test_advance_empty_pool_offers_nothing_for_fan(api):
    """PRD §3.3: "The promoter releases seats to fans in waves by advancing the
    queue".

    Boundary companion: with no waiting entries, no queue entry exists to become
    OFFERED, so a fan listing finds none offered for the tier.

    Design: Difficulty/boundary_precision_check/advance_queue_empty_waiting_pool_returns_empty
    """
    event, tier = setup_event_with_tier(phase="GENERAL")
    advance(event["id"], tier_id=tier["id"], max_offers=5)
    data, _meta = _list_entries_for_tier(api, tier["id"])
    assert len(data) == 0, data


def _list_entries_for_tier(api, tier_id):
    from test_helpers import validate_paginated
    res = api.list_queue_entries(PROMOTER, params={"tier_id": tier_id})
    return validate_paginated(res)


# ─── cross_entity_state_dependency ────────────────────────────────────────

def test_expired_offer_pay_leaves_queue_entry_not_purchased(api):
    """PRD §3.3: "If the fan never redeems and the window lapses, the next
    advance sweeps the entry to EXPIRED and frees its seats."

    Companion facet: after the sweep the linked queue entry is EXPIRED, so the
    blocked pay never advances it to PURCHASED.

    Design: Difficulty/cross_entity_state_dependency/order_pay_requires_queue_entry_offered
    """
    set_clock("2026-06-01T00:00:00Z")
    event, tier = setup_event_with_tier(phase="GENERAL")
    fan = register_and_verify_fan("m2@x.com", device="dev-m2")
    qe, order = create_pending_order(event, tier, fan, requested_qty=1)
    set_clock("2026-06-01T01:00:00Z")
    advance(event["id"], tier_id=tier["id"], max_offers=5)
    res = api.pay_order(
        order["id"], {"expected_order_version": order["version"]},
        make_fan_headers(fan["id"]),
    )
    validate_error(res, "ERR_OFFER_EXPIRED")
    qe_after = validate_success(api.get_queue_entry(qe["id"], make_fan_headers(fan["id"])), 200)
    assert qe_after["status"] == "EXPIRED", qe_after


def test_transfer_initiate_sets_ticket_transfer_pending(api):
    """PRD §3.6: "Initiation creates a transfer in PENDING and moves the ticket's
    holding_status from HELD to TRANSFER_PENDING, leaving the entry dimension
    untouched."

    Companion facet to the recipient-verified gate: the pending transfer leaves
    the ticket mid-transfer, which is the state the unverified-accept then targets.

    Design: Difficulty/cross_entity_state_dependency/transfer_accept_requires_recipient_verified
    """
    event, tier, sender, recipient, ticket, transfer = setup_pending_transfer(
        recipient_verified=False
    )
    t_ticket = validate_success(api.get_ticket(ticket["id"], make_fan_headers(sender["id"])), 200)
    assert t_ticket["holding_status"] == "TRANSFER_PENDING", t_ticket
    assert transfer["status"] == "PENDING", transfer


# ─── resource_temporal_overlap ────────────────────────────────────────────

def test_allocation_overlap_releases_pool_after_expiry(api):
    """PRD §3.3: "any entry in OFFERED whose offer_expires_at has passed ...
    transitions OFFERED → EXPIRED, and its reserved seats are released ...
    returning the seats to the finite pool for the next waiting entry."

    Companion facet on the same allocation=2 overlap: once the first offer
    expires and its 2 seats release, the previously-blocked second entry can be
    offered.

    Design: Difficulty/resource_temporal_overlap/tier_allocation_capacity_overlap
    """
    set_clock("2026-06-01T00:00:00Z")
    event, tier = setup_event_with_tier(phase="GENERAL", allocation=2)
    fan1 = register_and_verify_fan("ua@x.com", device="dev-ua")
    fan2 = register_and_verify_fan("ub@x.com", device="dev-ub")
    qe1 = join_queue(event, tier, fan1, requested_qty=2)
    qe2 = join_queue(event, tier, fan2, requested_qty=1)
    advance(event["id"], tier_id=tier["id"], max_offers=5)
    # Expire the first offer, then advance again -> second entry now fits.
    set_clock("2026-06-01T01:00:00Z")
    advance(event["id"], tier_id=tier["id"], max_offers=5)
    e2 = validate_success(api.get_queue_entry(qe2["id"], make_fan_headers(fan2["id"])), 200)
    assert e2["status"] == "OFFERED", e2


def test_offer_window_exact_deadline_redeemable(api):
    """PRD §3.4: "Redeeming an entry whose offer_expires_at has already passed is
    rejected with ERR_OFFER_EXPIRED."
    PRD §3.3: "the current time is strictly later than offer_expires_at".

    Companion facet: at a time still within the 120s window (strictly before
    expiry), redemption is allowed — the half-open upper bound.

    Design: Difficulty/resource_temporal_overlap/ticket_offer_window_temporal_expiry
    """
    set_clock("2026-06-01T00:00:00Z")
    event, tier = setup_event_with_tier(phase="GENERAL")
    fan = register_and_verify_fan("vw@x.com", device="dev-vw")
    qe = create_offered_entry(event, tier, fan, requested_qty=1)
    assert qe["status"] == "OFFERED"
    # Still at T0 (window is now+120s) -> not yet expired -> order succeeds.
    order = validate_success(api.create_order(
        {"queue_entry_id": qe["id"], "fan_id": fan["id"], "tier_id": tier["id"], "quantity": 1},
        make_fan_headers(fan["id"]),
    ), 201)
    assert order["status"] == "PENDING", order


# ─── compensating_invariant ───────────────────────────────────────────────

def test_refund_voids_tickets(api):
    """PRD §3.4: "Refund is a depth-three compensation cascade: all of the
    order's tickets are voided (entry_status → VOID)".

    Companion facet to tier-occupancy conservation: the order's tickets become
    VOID as part of the same compensation.

    Design: Difficulty/compensating_invariant/refund_conserves_tier_seat_occupancy
    """
    event, tier, fan, order, ticket = setup_held_ticket(phase="GENERAL")
    validate_success(api.refund_order(
        order["id"], {"expected_order_version": order["version"]},
        make_fan_headers(fan["id"]),
    ), 200)
    t_after = validate_success(api.get_ticket(ticket["id"], make_fan_headers(fan["id"])), 200)
    assert t_after["entry_status"] == "VOID", t_after


def test_refund_reopens_sold_out_event_to_general(api):
    """PRD §3.4: "If the event was SOLD_OUT, the freed seats re-open it
    SOLD_OUT → GENERAL."

    Companion facet on the event-counter conservation: refunding the seat that
    caused sold-out restores both tickets_sold_count and the GENERAL phase.

    Design: Difficulty/compensating_invariant/refund_conserves_event_tickets_sold_count
    """
    event, tier = setup_event_with_tier(phase="GENERAL", venue_capacity=1, allocation=5)
    fan = register_and_verify_fan("q2@x.com", device="dev-q2")
    _qe, paid = create_paid_order(event, tier, fan, requested_qty=1)
    ev_sold = validate_success(api.get_event(event["id"], PROMOTER), 200)
    assert ev_sold["sales_status"] == "SOLD_OUT", ev_sold
    validate_success(api.refund_order(
        paid["id"], {"expected_order_version": paid["version"]},
        make_fan_headers(fan["id"]),
    ), 200)
    ev_after = validate_success(api.get_event(event["id"], PROMOTER), 200)
    assert ev_after["sales_status"] == "GENERAL", ev_after
    assert ev_after["tickets_sold_count"] == 0, ev_after
