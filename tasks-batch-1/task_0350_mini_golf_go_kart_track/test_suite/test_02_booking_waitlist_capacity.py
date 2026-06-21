"""Booking capacity allocation, the confirmed<->waitlisted cycle, capacity
boundaries, and capacity/credit conservation invariants.

Covers Difficulty queue rules non_linear_state_machine (booking cyclic),
boundary_precision_check (capacity fit), and compensating_invariant.
"""
from test_helpers import (
    validate_success,
    make_ops_manager_headers,
    setup_open_heat_scenario, make_signed_guest,
    create_heat_hold_booking, confirm_booking_heat,
    setup_heat_filled_with_waitlist, get_heat, get_booking, get_combo_pass,
    create_combo_pass,
)

OPS = make_ops_manager_headers()


# ─────────────── Difficulty: non_linear_state_machine (booking cycle) ─────────

def test_hold_confirm_over_capacity_becomes_waitlisted(api):
    """PRD §3.6: "If instead the slot's free capacity is less than the booking's
    party_size, the booking moves from HOLD to WAITLISTED rather than being
    rejected: it receives a waitlist_seq equal to one more than the highest
    waitlist_seq among the slot's current waitlisted bookings (starting at 1 when
    it is the first), consumes no capacity, leaves the slot's version untouched,
    and keeps its provisional cash_due_cents."

    Design: Difficulty/non_linear_state_machine/booking_cyclic_confirmed_waitlisted_promotion
    """
    sc = setup_heat_filled_with_waitlist(lane_count=2, fill_party=2, wait_party=2)
    assert sc["booking_a"]["status"] == "CONFIRMED"
    assert sc["booking_b"]["status"] == "WAITLISTED", (
        f"booking B should be WAITLISTED, got {sc['booking_b']['status']}"
    )
    assert sc["booking_b"]["waitlist_seq"] == 1, (
        f"first waitlisted booking gets waitlist_seq 1, got {sc['booking_b']['waitlist_seq']}"
    )


def test_cancel_confirmed_promotes_earliest_waitlisted(api):
    """PRD §3.6: "When capacity is released on a slot — by cancelling or no-showing
    a previously CONFIRMED booking — the system promotes the earliest-eligible
    waitlisted booking on that same slot, automatically and without a client
    request."
    PRD §3.6: "Promotion moves the booking from WAITLISTED to CONFIRMED: ... clears
    the booking's waitlist_seq to null".

    Design: Difficulty/non_linear_state_machine/booking_cyclic_confirmed_waitlisted_promotion
    """
    sc = setup_heat_filled_with_waitlist(lane_count=2, fill_party=2, wait_party=2)
    # Cancel the CONFIRMED booking A -> releases capacity -> promotes B.
    validate_success(api.cancel_booking(sc["booking_a"]["id"], OPS), 200)

    bk_a = get_booking(sc["booking_a"]["id"])
    bk_b = get_booking(sc["booking_b"]["id"])
    heat = get_heat(sc["heat"]["id"])

    assert bk_a["status"] == "CANCELLED"
    assert bk_b["status"] == "CONFIRMED", f"B should be promoted to CONFIRMED, got {bk_b['status']}"
    assert bk_b["waitlist_seq"] is None, "promoted booking clears waitlist_seq to null"
    assert heat["lanes_committed"] == 2 and heat["lanes_available"] == 0, (
        f"B now occupies the 2 freed lanes; got committed={heat['lanes_committed']}, "
        f"available={heat['lanes_available']}"
    )


# ─────────────── Difficulty: boundary_precision_check (capacity) ──────────────

def test_party_size_exact_fit_confirms(api):
    """PRD §3.6: "If the slot's free capacity (lanes_available for a heat,
    players_available for a tee session) is greater than or equal to the booking's
    party_size, the booking moves from HOLD to CONFIRMED".

    Design: Difficulty/boundary_precision_check/capacity_exact_fit_confirms_one_over_waitlists
    """
    s = setup_open_heat_scenario(lane_count=5)
    venue_id, heat_id, plan_id = s["venue"]["id"], s["heat"]["id"], s["plan"]["id"]
    g1 = make_signed_guest(full_name="G1", height_cm=180)
    # Confirm a party-3 booking -> leaves lanes_available = 2.
    bk1 = create_heat_hold_booking(venue_id, g1["id"], heat_id, plan_id, party_size=3)
    confirm_booking_heat(bk1["id"], s["heat"]["version"])
    heat_after = get_heat(heat_id)
    assert heat_after["lanes_available"] == 2

    g2 = make_signed_guest(full_name="G2", height_cm=180)
    bk2 = create_heat_hold_booking(venue_id, g2["id"], heat_id, plan_id, party_size=2)
    confirmed = confirm_booking_heat(bk2["id"], heat_after["version"])
    # party_size 2 == lanes_available 2 -> exact fit confirms.
    assert confirmed["status"] == "CONFIRMED", (
        f"party 2 == available 2 should CONFIRM, got {confirmed['status']}"
    )


def test_party_size_one_over_capacity_waitlists(api):
    """PRD §3.6: "If instead the slot's free capacity is less than the booking's
    party_size, the booking moves from HOLD to WAITLISTED rather than being
    rejected".

    Design: Difficulty/boundary_precision_check/capacity_exact_fit_confirms_one_over_waitlists
    """
    s = setup_open_heat_scenario(lane_count=5)
    venue_id, heat_id, plan_id = s["venue"]["id"], s["heat"]["id"], s["plan"]["id"]
    g1 = make_signed_guest(full_name="G1", height_cm=180)
    bk1 = create_heat_hold_booking(venue_id, g1["id"], heat_id, plan_id, party_size=3)
    confirm_booking_heat(bk1["id"], s["heat"]["version"])
    heat_after = get_heat(heat_id)

    g2 = make_signed_guest(full_name="G2", height_cm=180)
    bk2 = create_heat_hold_booking(venue_id, g2["id"], heat_id, plan_id, party_size=2)
    bk2 = confirm_booking_heat(bk2["id"], heat_after["version"])
    heat_v3 = get_heat(heat_id)["version"]

    g3 = make_signed_guest(full_name="G3", height_cm=180)
    bk3 = create_heat_hold_booking(venue_id, g3["id"], heat_id, plan_id, party_size=3)
    bk3 = confirm_booking_heat(bk3["id"], heat_v3)
    # After bk2 confirms, lanes_available == 0; party 3 > 0 -> WAITLISTED.
    assert bk3["status"] == "WAITLISTED", (
        f"party 3 > available 0 should WAITLIST, got {bk3['status']}"
    )
    heat_final = get_heat(heat_id)
    assert heat_final["lanes_available"] == 0 and heat_final["lanes_committed"] == 5, (
        f"heat full: committed={heat_final['lanes_committed']}, available={heat_final['lanes_available']}"
    )


# ─────────────────────── Difficulty: compensating_invariant ──────────────────

def test_lane_capacity_conserved_after_confirm_then_cancel(api):
    """PRD §3.9: "A heat's lanes_committed is the sum of party_size over the
    bookings on that heat whose status is CONFIRMED or CHECKED_IN, and its
    lanes_available is lane_capacity minus that committed total, never below zero."
    PRD §3.8: "If it was CONFIRMED, its committed capacity is released (the slot's
    committed counter drops by party_size, available is recomputed, the slot's
    version increments, and the earliest-eligible waitlisted booking is promoted)".

    Design: Difficulty/compensating_invariant/lane_capacity_conserved_under_confirm_then_cancel
    """
    s = setup_open_heat_scenario(lane_count=4)
    guest = make_signed_guest(height_cm=180)
    bk = create_heat_hold_booking(
        s["venue"]["id"], guest["id"], s["heat"]["id"], s["plan"]["id"], party_size=3
    )
    bk = confirm_booking_heat(bk["id"], s["heat"]["version"])
    assert get_heat(s["heat"]["id"])["lanes_committed"] == 3

    validate_success(api.cancel_booking(bk["id"], OPS), 200)
    heat = get_heat(s["heat"]["id"])
    assert heat["lanes_committed"] == 0, (
        f"committed returns to pre-confirm value 0, got {heat['lanes_committed']}"
    )
    assert heat["lanes_available"] == 4, (
        f"lanes_committed + lanes_available == lane_capacity; got available={heat['lanes_available']}"
    )
    assert get_booking(bk["id"])["status"] == "CANCELLED"


def test_combo_credits_conserved_after_confirm_then_cancel_before_checkin(api):
    """PRD §3.5: "a pass's credits are applied at booking confirm but only redeemed
    against credits_redeemed at check-in: confirming a booking computes how many
    credits it will consume, but the pass's running credits_redeemed only advances
    when the booking is checked in."
    PRD §3.8: "If combo credits had been applied at confirm but not yet redeemed at
    check-in, those credits_applied are released without changing the pass's
    credits_redeemed."

    Design: Difficulty/compensating_invariant/combo_credits_conserved_under_confirm_then_cancel_before_checkin
    """
    s = setup_open_heat_scenario(lane_count=10)
    guest = make_signed_guest(height_cm=180)
    pass_ = create_combo_pass(guest["id"], total_credits=8)
    bk = create_heat_hold_booking(
        s["venue"]["id"], guest["id"], s["heat"]["id"], s["plan"]["id"],
        party_size=4, units=1, combo_pass_id=pass_["id"],
    )
    bk = confirm_booking_heat(bk["id"], s["heat"]["version"])
    # credits_applied = min(8, effective_units 1 * party 4) = 4
    assert bk["credits_applied"] == 4, f"expected 4 credits applied at confirm, got {bk['credits_applied']}"

    validate_success(api.cancel_booking(bk["id"], OPS), 200)
    pass_after = get_combo_pass(pass_["id"])
    assert pass_after["credits_redeemed"] == 0, "credits never drawn (cancel before check-in)"
    assert pass_after["credits_remaining"] == 8, (
        f"credits_remaining returns to total with zero drift, got {pass_after['credits_remaining']}"
    )
    assert pass_after["status"] == "ACTIVE"


def test_lane_capacity_invariant_holds_through_confirm(api):
    """PRD §2.9: "A heat's lanes_available is its lane_capacity minus its committed
    lanes, floored at zero".
    PRD §3.6: "the slot's committed counter rises by party_size and its available
    count is recomputed".

    Design: Difficulty/compensating_invariant/lane_capacity_conserved_under_confirm_then_cancel
    """
    # The conserved relation lanes_committed + lanes_available == lane_capacity
    # must already hold on the forward (confirm) leg, before any compensation.
    s = setup_open_heat_scenario(lane_count=4)
    guest = make_signed_guest(height_cm=180)
    bk = create_heat_hold_booking(
        s["venue"]["id"], guest["id"], s["heat"]["id"], s["plan"]["id"], party_size=3
    )
    confirm_booking_heat(bk["id"], s["heat"]["version"])
    heat = get_heat(s["heat"]["id"])
    assert heat["lanes_committed"] == 3
    assert heat["lanes_available"] == 1
    assert heat["lanes_committed"] + heat["lanes_available"] == heat["lane_capacity"], (
        "committed + available must equal lane_capacity on the confirm leg"
    )


def test_combo_credits_not_drawn_until_check_in(api):
    """PRD §3.5: "a pass's credits are applied at booking confirm but only redeemed
    against credits_redeemed at check-in: confirming a booking computes how many
    credits it will consume, but the pass's running credits_redeemed only advances
    when the booking is checked in."

    Design: Difficulty/compensating_invariant/combo_credits_conserved_under_confirm_then_cancel_before_checkin
    """
    # Forward leg only: after confirm (before check-in), credits_applied is set
    # on the booking but the pass's credits_redeemed has not advanced.
    s = setup_open_heat_scenario(lane_count=10)
    guest = make_signed_guest(height_cm=180)
    pass_ = create_combo_pass(guest["id"], total_credits=8)
    bk = create_heat_hold_booking(
        s["venue"]["id"], guest["id"], s["heat"]["id"], s["plan"]["id"],
        party_size=4, units=1, combo_pass_id=pass_["id"],
    )
    bk = confirm_booking_heat(bk["id"], s["heat"]["version"])
    assert bk["credits_applied"] == 4, f"credits applied at confirm, got {bk['credits_applied']}"
    pass_now = get_combo_pass(pass_["id"])
    assert pass_now["credits_redeemed"] == 0, "credits_redeemed only advances at check-in"
    assert pass_now["credits_remaining"] == 8
