"""Temporal-overlap interval semantics (slots vs actor shifts) and optimistic
concurrency control on slot/venue/attraction/waiver versions."""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    setup_venue_attraction_slot, create_venue, create_attraction,
    create_pricing_rule, create_time_slot, create_guest, create_reservation,
    add_ticket, get_slot_version,
    create_time_slot_payload, create_scare_zone_payload, create_actor_shift_payload,
    create_waiver_payload, revoke_payload, weather_payload, confirm_payload,
    create_closure_payload, make_guest_headers,
    TEST_USERS,
)

BOX = TEST_USERS["box_office_headers"]
OPS = TEST_USERS["ops_headers"]


# ─── Time-slot overlap (zero-buffer, half-open adjacency) ──────────────────

def test_time_slot_overlapping_existing_scheduled_slot_rejected(api):
    """PRD 3.2: "Overlap here uses half-open interval intersection: two slots conflict
    when one's start falls strictly before the other's end and vice versa ... An
    overlapping slot is rejected with ERR_SLOT_OVERLAP."

    A new slot [18:30,19:30) intersecting an existing [18:00,19:00) slot on the same
    attraction is rejected ERR_SLOT_OVERLAP.

    Design: Difficulty/resource_temporal_overlap/rto_time_slot_pure_adjacency_half_open
    """
    venue = create_venue()
    attraction = create_attraction(venue["id"])
    create_time_slot(attraction["id"], window_start="2026-10-31T18:00:00Z",
                     window_end="2026-10-31T19:00:00Z", capacity=10)
    res = api.create_time_slot(
        attraction["id"],
        create_time_slot_payload(window_start="2026-10-31T18:30:00Z",
                                 window_end="2026-10-31T19:30:00Z", capacity=10),
        OPS,
    )
    validate_error(res, "ERR_SLOT_OVERLAP")


def test_time_slot_touching_window_end_allowed_zero_buffer(api):
    """PRD 3.2: "two windows that merely touch — where the existing slot's window_end
    equals the new slot's window_start — are permitted with zero buffer."

    A new slot [19:00,20:00) starting exactly at the existing slot's window_end 19:00
    is accepted (adjacency allowed) with 201.

    Design: Difficulty/resource_temporal_overlap/rto_time_slot_pure_adjacency_half_open
    """
    venue = create_venue()
    attraction = create_attraction(venue["id"])
    create_time_slot(attraction["id"], window_start="2026-10-31T18:00:00Z",
                     window_end="2026-10-31T19:00:00Z", capacity=10)
    res = api.create_time_slot(
        attraction["id"],
        create_time_slot_payload(window_start="2026-10-31T19:00:00Z",
                                 window_end="2026-10-31T20:00:00Z", capacity=10),
        OPS,
    )
    created = validate_success(res, 201)
    assert created["status"] == "SCHEDULED"


# ─── Actor-shift overlap (30-minute rest buffer) ───────────────────────────

def _zone_for_shifts(api):
    venue = create_venue()
    attraction = create_attraction(venue["id"])
    return get_success_data(
        api.create_scare_zone(attraction["id"], create_scare_zone_payload(min_actors=1), OPS)
    )


def test_actor_shift_within_rest_buffer_rejected(api):
    """PRD 3.8: "Two shifts conflict when the new shift's shift_start falls before the
    existing shift's shift_end extended by thirty minutes, and simultaneously the
    existing shift's shift_start falls before the new shift's shift_end extended by
    thirty minutes; this buffered-interval test means even back-to-back shifts that
    touch are too close. A conflicting shift is rejected with ERR_SHIFT_OVERLAP."

    For actor-7 with an existing shift [18:00,19:00), a new shift starting 19:00 is
    rejected ERR_SHIFT_OVERLAP because 19:00 < 19:00+30min.

    Design: Difficulty/resource_temporal_overlap/rto_actor_shift_buffered_interval_rest_gap
    """
    zone = _zone_for_shifts(api)
    get_success_data(api.create_actor_shift(
        zone["id"], create_actor_shift_payload("actor-7", "2026-10-31T18:00:00Z", "2026-10-31T19:00:00Z"), OPS))
    res = api.create_actor_shift(
        zone["id"],
        create_actor_shift_payload("actor-7", "2026-10-31T19:00:00Z", "2026-10-31T20:00:00Z"),
        OPS,
    )
    validate_error(res, "ERR_SHIFT_OVERLAP")


def test_actor_shift_exactly_at_rest_buffer_allowed(api):
    """PRD 3.8: "A new shift for the same actor_user_id must preserve a mandatory
    thirty-minute rest buffer from every existing non-terminal shift". PRD 3.8: "Two
    shifts conflict when the new shift's shift_start falls before the existing shift's
    shift_end extended by thirty minutes".

    For actor-7 with an existing shift [18:00,19:00), a new shift starting 19:30
    (exactly 30 minutes after the existing shift_end) is accepted with 201 — the
    buffer is satisfied at the boundary.

    Design: Difficulty/resource_temporal_overlap/rto_actor_shift_buffered_interval_rest_gap
    """
    zone = _zone_for_shifts(api)
    get_success_data(api.create_actor_shift(
        zone["id"], create_actor_shift_payload("actor-7", "2026-10-31T18:00:00Z", "2026-10-31T19:00:00Z"), OPS))
    res = api.create_actor_shift(
        zone["id"],
        create_actor_shift_payload("actor-7", "2026-10-31T19:30:00Z", "2026-10-31T20:30:00Z"),
        OPS,
    )
    created = validate_success(res, 201)
    assert created["status"] == "SCHEDULED"


# ─── OCC stale-version (corner queue) ──────────────────────────────────────

def test_confirm_with_stale_time_slot_version_rejected(api):
    """PRD 2.10: "If any referenced slot's current version has advanced beyond the
    value the client supplied — because another confirmation has since incremented
    that slot's reserved_count and consumed capacity the earlier reader believed
    available — the confirmation is rejected with ERR_STALE_TIME_SLOT_VERSION and HTTP
    status 412."

    With two reservations on one slot, R1's confirm advances the slot version; R2
    confirming against the pre-R1 version is rejected ERR_STALE_TIME_SLOT_VERSION.

    Design: Corner/cross_cutting/occ_confirm_stale_time_slot
    """
    venue, attraction, slot = setup_venue_attraction_slot(slot_overrides={"capacity": 10})
    slot_v0 = slot["version"]
    g1 = create_guest(full_name="G1", email="g1@x.com")
    r1 = create_reservation(venue["id"], g1["id"])
    add_ticket(r1["id"], slot["id"], tier="GA")
    g2 = create_guest(full_name="G2", email="g2@x.com")
    r2 = create_reservation(venue["id"], g2["id"])
    add_ticket(r2["id"], slot["id"], tier="GA")

    validate_success(api.confirm_reservation(r1["id"], confirm_payload(slot_v0), BOX), 200)

    res = api.confirm_reservation(r2["id"], confirm_payload(slot_v0), BOX)
    validate_error(res, "ERR_STALE_TIME_SLOT_VERSION")


def test_weather_change_with_stale_venue_version_rejected(api):
    """PRD 2.10: "Setting venue weather requires expected_venue_version matching the
    venue's current version, and a mismatch is rejected with ERR_STALE_VENUE_VERSION
    (HTTP 412)."

    After one weather change advances the venue version, a second change still
    carrying the pre-change version is rejected ERR_STALE_VENUE_VERSION.

    Design: Corner/cross_cutting/occ_weather_stale_venue_version
    """
    venue = create_venue()
    v0 = venue["version"]
    validate_success(api.set_weather(venue["id"], weather_payload("ADVISORY", v0), OPS), 200)
    res = api.set_weather(venue["id"], weather_payload("CLEAR", v0), OPS)
    validate_error(res, "ERR_STALE_VENUE_VERSION")


def test_revoke_waiver_with_stale_version_rejected(api):
    """PRD 2.10: "Revoking a waiver requires expected_waiver_version matching the
    waiver's current version, and a mismatch is rejected with ERR_STALE_WAIVER_VERSION
    (HTTP 412)."

    Revoking a SIGNED waiver (version 1) with a stale expected_waiver_version of 0 is
    rejected ERR_STALE_WAIVER_VERSION.

    Design: Corner/cross_cutting/occ_waiver_stale_version_on_revoke
    """
    guest = create_guest()
    gh = make_guest_headers(guest["id"])
    waiver = get_success_data(
        api.create_waiver(guest["id"], create_waiver_payload(max_scare_level=5), gh)
    )
    stale = waiver["version"] - 1
    res = api.revoke_waiver(waiver["id"], revoke_payload(stale), gh)
    validate_error(res, "ERR_STALE_WAIVER_VERSION")
