"""Slot and venue lifecycle transitions plus the multi-step cascades that fire
when a booking is cancelled or a venue enters a weather hold.

Covers Difficulty queue rules transitive_cascade and
cross_entity_state_dependency, plus corner-design state-machine claims.
"""
from test_helpers import (
    validate_success, validate_error,
    make_ops_manager_headers, make_cashier_headers,
    setup_open_heat_scenario, setup_open_tee_scenario, make_signed_guest,
    create_heat_hold_booking, create_tee_hold_booking,
    confirm_booking_heat, get_heat, get_booking, get_venue, get_party_group,
    create_venue, create_attraction, create_heat, create_tee_session,
    create_pricing_plan, create_guest,
    create_party_group,
)

OPS = make_ops_manager_headers()
CASHIER = make_cashier_headers()


# ───────────────────── Difficulty: transitive_cascade ────────────────────────

def test_booking_cancel_cascades_to_promotion_and_party_units(api):
    """PRD §3.8: "If it was CONFIRMED, its committed capacity is released (the
    slot's committed counter drops by party_size, available is recomputed, the
    slot's version increments, and the earliest-eligible waitlisted booking is
    promoted)".
    PRD §3.6: "Promotion moves the booking from WAITLISTED to CONFIRMED: ... and —
    if the booking belongs to a group — raises that group's units_consumed by
    party_size."

    Design: Difficulty/transitive_cascade/booking_cancel_cascades_to_promotion_to_party_units
    """
    s = setup_open_heat_scenario(lane_count=2)
    venue_id, heat_id, plan_id = s["venue"]["id"], s["heat"]["id"], s["plan"]["id"]
    ga = make_signed_guest(full_name="GA", height_cm=180)
    gb = make_signed_guest(full_name="GB", height_cm=180)
    grp = create_party_group(venue_id, gb["id"], deposit_cents=0, included_unit_count=10, package_name="BdayB")

    bk_a = create_heat_hold_booking(venue_id, ga["id"], heat_id, plan_id, party_size=2)
    bk_a = confirm_booking_heat(bk_a["id"], s["heat"]["version"])
    heat_v2 = get_heat(heat_id)["version"]

    bk_b = create_heat_hold_booking(venue_id, gb["id"], heat_id, plan_id, party_size=2, group_id=grp["id"])
    # PRD §3.10: group confirm requires at least one member in HOLD or CONFIRMED.
    # bk_b is the sole member and is still HOLD here, so confirm the group now,
    # before bk_b is pushed to WAITLISTED by the full-heat confirm below.
    grp_v = get_party_group(grp["id"])["version"]
    validate_success(api.confirm_party_group(grp["id"], {"expected_group_version": grp_v}, OPS), 200)

    bk_b = confirm_booking_heat(bk_b["id"], heat_v2)  # WAITLISTED (heat full)
    assert bk_b["status"] == "WAITLISTED"
    assert get_party_group(grp["id"])["units_consumed"] == 0  # B not yet counted (WAITLISTED)

    # Trigger: cancel A -> capacity released -> B promoted -> group units rise.
    validate_success(api.cancel_booking(bk_a["id"], OPS), 200)

    assert get_booking(bk_a["id"])["status"] == "CANCELLED"
    assert get_booking(bk_b["id"])["status"] == "CONFIRMED", "B promoted from WAITLISTED"
    assert get_heat(heat_id)["lanes_committed"] == 2, "B occupies the 2 freed lanes"
    assert get_party_group(grp["id"])["units_consumed"] == 2, "B counted only after promotion"


def test_weather_hold_closes_open_slot_and_cancels_waitlist(api):
    """PRD §3.11: "every heat and tee session on the venue currently in OPEN status
    is moved to CLOSED so no new bookings are taken, and on each of those
    just-closed slots every WAITLISTED booking is moved to CANCELLED."
    PRD §3.11: "Critically, CONFIRMED and CHECKED_IN bookings on those slots are
    not auto-completed under a weather hold — they stay CONFIRMED or CHECKED_IN".

    Design: Difficulty/transitive_cascade/venue_weather_hold_cascades_slot_close_to_waitlist_cancel
    """
    s = setup_open_heat_scenario(lane_count=1)
    venue_id, heat_id, plan_id = s["venue"]["id"], s["heat"]["id"], s["plan"]["id"]
    ga = make_signed_guest(full_name="GA", height_cm=180)
    gb = make_signed_guest(full_name="GB", height_cm=180)

    bk_a = create_heat_hold_booking(venue_id, ga["id"], heat_id, plan_id, party_size=1)
    bk_a = confirm_booking_heat(bk_a["id"], s["heat"]["version"])  # CONFIRMED, fills heat
    heat_v2 = get_heat(heat_id)["version"]
    bk_b = create_heat_hold_booking(venue_id, gb["id"], heat_id, plan_id, party_size=1)
    bk_b = confirm_booking_heat(bk_b["id"], heat_v2)  # WAITLISTED
    assert bk_b["status"] == "WAITLISTED"

    venue_v = get_venue(venue_id)["version"]
    validate_success(api.weather_hold_venue(
        venue_id, {"weather_hold_reason": "Lightning", "expected_venue_version": venue_v}, OPS), 200)

    assert get_venue(venue_id)["posture"] == "WEATHER_HOLD"
    assert get_heat(heat_id)["status"] == "CLOSED", "OPEN heat closed by weather-hold"
    assert get_booking(bk_b["id"])["status"] == "CANCELLED", "WAITLISTED booking cancelled"
    assert get_booking(bk_a["id"])["status"] == "CONFIRMED", "CONFIRMED booking preserved, not auto-completed"


def test_booking_cancel_releases_capacity_link(api):
    """PRD §3.8: "If it was CONFIRMED, its committed capacity is released (the
    slot's committed counter drops by party_size, available is recomputed, the
    slot's version increments, and the earliest-eligible waitlisted booking is
    promoted)".

    Design: Difficulty/transitive_cascade/booking_cancel_cascades_to_promotion_to_party_units
    """
    # First link of the chain in isolation: cancel of a CONFIRMED booking with no
    # waitlist behind it just releases the lanes (committed drops back to 0).
    s = setup_open_heat_scenario(lane_count=4)
    guest = make_signed_guest(height_cm=180)
    bk = create_heat_hold_booking(
        s["venue"]["id"], guest["id"], s["heat"]["id"], s["plan"]["id"], party_size=2
    )
    bk = confirm_booking_heat(bk["id"], s["heat"]["version"])
    assert get_heat(s["heat"]["id"])["lanes_committed"] == 2

    validate_success(api.cancel_booking(bk["id"], OPS), 200)
    heat = get_heat(s["heat"]["id"])
    assert heat["lanes_committed"] == 0, "cancel releases the committed lanes"
    assert heat["lanes_available"] == 4


def test_weather_hold_captures_reason(api):
    """PRD §3.11: "The hold cascades immediately: the reason is captured into
    weather_hold_reason, every heat and tee session on the venue currently in OPEN
    status is moved to CLOSED so no new bookings are taken".

    Design: Difficulty/transitive_cascade/venue_weather_hold_cascades_slot_close_to_waitlist_cancel
    """
    # Same trigger (weather-hold) viewed at the venue link: posture flips and the
    # supplied reason is captured onto the venue.
    s = setup_open_heat_scenario(lane_count=5)
    venue_id = s["venue"]["id"]
    venue_v = get_venue(venue_id)["version"]
    held = validate_success(api.weather_hold_venue(
        venue_id, {"weather_hold_reason": "Tornado warning", "expected_venue_version": venue_v}, OPS), 200)
    assert held["posture"] == "WEATHER_HOLD"
    assert held["weather_hold_reason"] == "Tornado warning", "reason captured from request"
    assert get_heat(s["heat"]["id"])["status"] == "CLOSED", "OPEN heat closed by the hold"


# ───────────── Difficulty: cross_entity_state_dependency ──────────────────────

def test_heat_open_requires_venue_open(api):
    """PRD §3.2: "A scheduled slot does not accept bookings until it is opened. An
    OpsManager opens a heat or a tee session, advancing it from SCHEDULED to OPEN;
    this is permitted only when the slot is currently SCHEDULED and the venue's
    posture is OPEN".
    PRD §3.2: "Opening a slot whose venue is not open is refused under the posture
    gate with ERR_VENUE_NOT_OPEN".

    Design: Difficulty/cross_entity_state_dependency/heat_open_requires_venue_open
    """
    venue = create_venue(name="Track K", set_clock=None)
    attraction = create_attraction(venue["id"], kind="GO_KART", min_height_cm=0, lane_count=5)
    heat = create_heat(venue["id"], attraction["id"])
    venue_v = get_venue(venue["id"])["version"]
    validate_success(api.weather_hold_venue(
        venue["id"], {"weather_hold_reason": "Rain", "expected_venue_version": venue_v}, OPS), 200)

    res = api.open_heat(heat["id"], OPS)
    validate_error(res, "ERR_VENUE_NOT_OPEN")
    assert get_heat(heat["id"])["status"] == "SCHEDULED", "heat unchanged"


def test_booking_confirm_requires_tee_session_open(api):
    """PRD §3.6: "A confirm carries the slot's expected version ... and proceeds
    only when the venue's posture is OPEN, the owning slot is OPEN, the OCC version
    matches, the height and waiver safety gates pass, any named combo pass is
    valid, and capacity is examined."
    PRD §3.8: "a transition attempted against a booking already terminal, or
    otherwise out of the legal source state, is rejected with ERR_INVALID_STATE."

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_requires_tee_session_open
    """
    # Tee session created but NOT opened (SCHEDULED).
    s = setup_open_tee_scenario(party_slot_capacity=10, base_price_cents=1000, mode="PER_ROUND",
                                open_session=False)
    guest = make_signed_guest(full_name="GTee", height_cm=175)
    bk = create_tee_hold_booking(
        s["venue"]["id"], guest["id"], s["tee_session"]["id"], s["plan"]["id"], party_size=1
    )
    res = api.confirm_booking(bk["id"], {"expected_tee_session_version": s["tee_session"]["version"]}, OPS)
    validate_error(res, "ERR_INVALID_STATE")
    assert get_booking(bk["id"])["status"] == "HOLD", "booking unchanged"


def test_tee_session_open_requires_venue_open(api):
    """PRD §3.2: "An OpsManager opens a heat or a tee session, advancing it from
    SCHEDULED to OPEN; this is permitted only when the slot is currently SCHEDULED
    and the venue's posture is OPEN".
    PRD §3.2: "Opening a slot whose venue is not open is refused under the posture
    gate with ERR_VENUE_NOT_OPEN".

    Design: Difficulty/cross_entity_state_dependency/heat_open_requires_venue_open
    """
    # Same Slot->Venue dependency exercised on the TeeSession arm of the rule.
    venue = create_venue(name="Track K2", set_clock=None)
    attraction = create_attraction(venue["id"], kind="MINI_GOLF")
    tee = create_tee_session(venue["id"], attraction["id"],
                             start_utc="2026-06-14T10:00:00Z", end_utc="2026-06-14T11:00:00Z",
                             party_slot_capacity=10)
    venue_v = get_venue(venue["id"])["version"]
    validate_success(api.weather_hold_venue(
        venue["id"], {"weather_hold_reason": "Rain", "expected_venue_version": venue_v}, OPS), 200)
    res = api.open_tee_session(tee["id"], OPS)
    validate_error(res, "ERR_VENUE_NOT_OPEN")


def test_heat_booking_confirm_requires_heat_open(api):
    """PRD §3.6: "Confirming a held booking is where capacity is tested. A confirm
    carries the slot's expected version ... and proceeds only when the venue's
    posture is OPEN, the owning slot is OPEN, the OCC version matches".
    PRD §3.8: "a transition attempted against a booking already terminal, or
    otherwise out of the legal source state, is rejected with ERR_INVALID_STATE."

    Design: Difficulty/cross_entity_state_dependency/booking_confirm_requires_tee_session_open
    """
    # Same Booking->owning-slot dependency exercised on the Heat arm: confirm a
    # booking against a still-SCHEDULED (unopened) heat.
    venue = create_venue(name="Track L2", set_clock="2026-06-14T09:00:00Z")
    attraction = create_attraction(venue["id"], kind="GO_KART", lane_count=5)
    plan = create_pricing_plan(venue["id"], mode="PER_HEAT", base_price_cents=1000)
    heat = create_heat(venue["id"], attraction["id"])  # SCHEDULED, not opened
    guest = make_signed_guest(height_cm=180)
    bk = create_heat_hold_booking(venue["id"], guest["id"], heat["id"], plan["id"], party_size=1)
    res = api.confirm_booking(bk["id"], {"expected_heat_version": heat["version"]}, OPS)
    validate_error(res, "ERR_INVALID_STATE")
    assert get_booking(bk["id"])["status"] == "HOLD"


# ───────────────────────── Corner: state_machines ────────────────────────────

def test_cancel_already_cancelled_booking_rejected(api):
    """PRD §3.8: "The terminal booking statuses COMPLETED, CANCELLED, and NO_SHOW
    admit no further transitions, and a transition attempted against a booking
    already terminal, or otherwise out of the legal source state, is rejected with
    ERR_INVALID_STATE."

    Design: Corner/state_machines/cancel_booking_already_cancelled_returns_invalid_state
    """
    s = setup_open_heat_scenario(lane_count=5)
    guest = create_guest(full_name="G", height_cm=180)
    bk = create_heat_hold_booking(
        s["venue"]["id"], guest["id"], s["heat"]["id"], s["plan"]["id"], party_size=1
    )
    validate_success(api.cancel_booking(bk["id"], OPS), 200)
    res = api.cancel_booking(bk["id"], OPS)
    validate_error(res, "ERR_INVALID_STATE")
    assert get_booking(bk["id"])["status"] == "CANCELLED"


def test_open_heat_twice_rejected(api):
    """PRD §3.2: "opening a slot that is not in SCHEDULED is refused as an invalid
    state transition with ERR_INVALID_STATE."

    Design: Corner/state_machines/open_heat_twice_idempotency_rejected
    """
    venue = create_venue(name="V", set_clock=None)
    attraction = create_attraction(venue["id"], kind="GO_KART", lane_count=5)
    heat = create_heat(venue["id"], attraction["id"])
    validate_success(api.open_heat(heat["id"], OPS), 200)
    res = api.open_heat(heat["id"], OPS)
    validate_error(res, "ERR_INVALID_STATE")
    assert get_heat(heat["id"])["status"] == "OPEN"


def test_venue_close_blocked_while_slot_open(api):
    """PRD §3.11: "A permanent close is allowed only when no heat or tee session on
    the venue is currently in OPEN status; if any open slot remains the close is
    refused as an invalid state transition."

    Design: Corner/state_machines/venue_close_blocked_while_slot_open
    """
    venue = create_venue(name="V", set_clock=None)
    attraction = create_attraction(venue["id"], kind="GO_KART", lane_count=5)
    heat = create_heat(venue["id"], attraction["id"])
    validate_success(api.open_heat(heat["id"], OPS), 200)
    venue_v = get_venue(venue["id"])["version"]
    res = api.close_venue(venue["id"], {"expected_venue_version": venue_v}, OPS)
    validate_error(res, "ERR_INVALID_STATE")
    assert get_venue(venue["id"])["posture"] == "OPEN"


def test_resume_from_open_venue_rejected(api):
    """PRD §3.11: "An OpsManager resumes a held venue, supplying
    expected_venue_version, which advances posture from WEATHER_HOLD back to OPEN".
    PRD §3.8: "a transition attempted against a booking already terminal, or
    otherwise out of the legal source state, is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/resume_from_open_venue_returns_invalid_state
    """
    venue = create_venue(name="V", set_clock=None)
    venue_v = get_venue(venue["id"])["version"]
    res = api.resume_venue(venue["id"], {"expected_venue_version": venue_v}, OPS)
    validate_error(res, "ERR_INVALID_STATE")
    assert get_venue(venue["id"])["posture"] == "OPEN"


def test_weather_hold_then_resume_restores_open(api):
    """PRD §3.11: "An OpsManager resumes a held venue, supplying
    expected_venue_version, which advances posture from WEATHER_HOLD back to OPEN,
    clears weather_hold_reason to null, and increments the venue's version."

    Design: Corner/state_machines/weather_hold_resume_restores_open
    """
    venue = create_venue(name="V", set_clock=None)
    venue_v0 = get_venue(venue["id"])["version"]
    held = validate_success(api.weather_hold_venue(
        venue["id"], {"weather_hold_reason": "Storm", "expected_venue_version": venue_v0}, OPS), 200)
    resumed = validate_success(api.resume_venue(
        venue["id"], {"expected_venue_version": held["version"]}, OPS), 200)
    assert resumed["posture"] == "OPEN"
    assert resumed["weather_hold_reason"] is None, "weather_hold_reason cleared to null on resume"


def test_confirm_under_weather_hold_blocked(api):
    """PRD §3.11: "While the venue is in WEATHER_HOLD, the posture gate blocks slot
    opening, booking confirmation, booking check-in, and party-group confirmation
    with ERR_VENUE_NOT_OPEN."

    Design: Corner/state_machines/confirm_under_weather_hold_blocked
    """
    s = setup_open_heat_scenario(lane_count=5)
    venue_id, heat_id, plan_id = s["venue"]["id"], s["heat"]["id"], s["plan"]["id"]
    guest = make_signed_guest(height_cm=180)
    bk = create_heat_hold_booking(venue_id, guest["id"], heat_id, plan_id, party_size=1)

    venue_v = get_venue(venue_id)["version"]
    validate_success(api.weather_hold_venue(
        venue_id, {"weather_hold_reason": "Hail", "expected_venue_version": venue_v}, OPS), 200)

    res = api.confirm_booking(bk["id"], {"expected_heat_version": s["heat"]["version"]}, OPS)
    validate_error(res, "ERR_VENUE_NOT_OPEN")
    assert get_booking(bk["id"])["status"] == "HOLD"


def test_manual_heat_close_completes_checked_in_booking(api):
    """PRD §3.2: "on a manual close, every CONFIRMED and CHECKED_IN booking on that
    slot is moved to COMPLETED, while every WAITLISTED booking on it is moved to
    CANCELLED (no promotion happens, since the slot is going away), and the slot's
    version increments."

    Design: Corner/state_machines/heat_manual_close_completes_checked_in_booking
    """
    # Clock inside the heat window [10:00,10:15) so check-in is permitted.
    s = setup_open_heat_scenario(lane_count=5, set_clock="2026-06-14T10:05:00Z")
    venue_id, heat_id, plan_id = s["venue"]["id"], s["heat"]["id"], s["plan"]["id"]
    guest = make_signed_guest(height_cm=180)
    bk = create_heat_hold_booking(venue_id, guest["id"], heat_id, plan_id, party_size=1, origin="WALK_IN")
    bk = confirm_booking_heat(bk["id"], s["heat"]["version"])
    validate_success(api.check_in_booking(bk["id"], CASHIER), 200)

    validate_success(api.close_heat(heat_id, OPS), 200)
    assert get_heat(heat_id)["status"] == "CLOSED"
    assert get_booking(bk["id"])["status"] == "COMPLETED", "CHECKED_IN booking completes on manual close"


def test_cancel_scheduled_heat_cascades_hold_booking(api):
    """PRD §3.2: "Cancelling a scheduled slot advances it from SCHEDULED to
    CANCELLED, moving all of its non-terminal bookings — those in HOLD or
    WAITLISTED — to CANCELLED and bumping the slot's version."

    Design: Corner/state_machines/cancel_scheduled_heat_cascades_hold_booking
    """
    venue = create_venue(name="V", set_clock=None)
    attraction = create_attraction(venue["id"], kind="GO_KART", lane_count=5)
    plan = create_pricing_plan(venue["id"], mode="PER_HEAT", base_price_cents=1000)
    heat = create_heat(venue["id"], attraction["id"])  # SCHEDULED, never opened
    guest = create_guest(full_name="G", height_cm=180)
    bk = create_heat_hold_booking(venue["id"], guest["id"], heat["id"], plan["id"], party_size=1)

    validate_success(api.cancel_heat(heat["id"], OPS), 200)
    assert get_heat(heat["id"])["status"] == "CANCELLED"
    assert get_booking(bk["id"])["status"] == "CANCELLED", "HOLD booking cascaded to CANCELLED"
