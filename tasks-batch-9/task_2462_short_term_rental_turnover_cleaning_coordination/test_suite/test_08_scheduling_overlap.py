"""Two different interval rules: zero-buffer occupancy and buffered cleaner windows."""

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assign_turnover_payload,
    create_booking_payload,
    fixtures as fx,
    make_cleaner_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

COORDINATOR = TEST_USERS["coordinator_headers"]


# ─── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def occupied_unit(api):
    """P1 carrying one SCHEDULED stay that vacates at 2026-08-08T16:00:00Z."""
    fx.reset_clock(api)
    p1 = fx.seed_property(api)
    b_out = fx.seed_booking(
        api, p1["id"], external_ref="OUT-1", guest_name="Guest Out",
        checkin_at="2026-08-05T21:00:00Z", checkout_at="2026-08-08T16:00:00Z")
    return {"p1": p1, "b_out": b_out}


@pytest.fixture
def cross_zone_schedule_world(api):
    """Cleaner C holding an ACCEPTED ZONE_A turn, plus two ZONE_B turns to offer."""
    fx.reset_clock(api)
    p1 = fx.seed_property(api)
    zone_b = {
        "zone_code": "ZONE_B", "size_tier": "ONE_BR", "bedroom_count": 1,
        "bathroom_count": 1, "bed_count": 1, "local_utc_offset_minutes": 0,
        "min_clean_minutes": 60, "min_skill_level": 1,
    }
    p2 = fx.seed_property(
        api, code="ATX-201", name="Riverside One",
        owner_contact_email="owner5@example.com", **zone_b)
    p3 = fx.seed_property(
        api, code="ATX-202", name="Riverside Two",
        owner_contact_email="owner6@example.com", **zone_b)
    cc = fx.seed_cleaner(api, secondary_zone_codes=["ZONE_B"])

    b_out, b_in = fx.seed_stay_pair(api, p1["id"])
    t1 = fx.seed_turnover(api, b_out["id"], b_in["id"])
    a1 = validate_success(api.assign_turnover(
        t1["id"], assign_turnover_payload(t1["version"], cc["id"]),
        COORDINATOR), 201)
    validate_success(api.accept_assignment(
        a1["id"], {}, make_cleaner_headers(cc["id"])))

    b_out2 = fx.seed_booking(
        api, p2["id"], external_ref="OUT-2", guest_name="Guest Out 2",
        checkin_at="2026-08-06T21:00:00Z", checkout_at="2026-08-08T20:40:00Z")
    b_in2 = fx.seed_booking(
        api, p2["id"], external_ref="IN-2", guest_name="Guest In 2",
        checkin_at="2026-08-08T23:40:00Z", checkout_at="2026-08-10T16:00:00Z")
    t2 = fx.seed_turnover(api, b_out2["id"], b_in2["id"])

    b_out3 = fx.seed_booking(
        api, p3["id"], external_ref="OUT-3", guest_name="Guest Out 3",
        checkin_at="2026-08-06T21:00:00Z", checkout_at="2026-08-08T21:15:00Z")
    b_in3 = fx.seed_booking(
        api, p3["id"], external_ref="IN-3", guest_name="Guest In 3",
        checkin_at="2026-08-09T00:15:00Z", checkout_at="2026-08-10T16:00:00Z")
    t3 = fx.seed_turnover(api, b_out3["id"], b_in3["id"])

    return {"p1": p1, "p2": p2, "p3": p3, "cc": cc, "t1": t1, "a1": a1,
            "t2": t2, "t3": t3}


# ─── booking_occupancy_half_open_adjacency_allowed_on_property ────────────

def test_01_a_stay_beginning_one_minute_before_the_departure_is_refused(
        api, occupied_unit):
    """15:59 is strictly earlier than a 16:00 departure, so the unit is occupied.

    PRD §2.6: "Two stays overlap when the new stay's `checkin_at` is strictly
    earlier than the existing stay's `checkout_at` and the existing stay's
    `checkin_at` is strictly earlier than the new stay's `checkout_at`." PRD
    §2.5: "**Occupancy overlap.** On `POST /bookings`, the new stay's occupancy
    interval must not overlap another `SCHEDULED` or `CHECKED_OUT` stay on the
    same property, with adjacency permitted. Failure yields
    `ERR_BOOKING_OVERLAP` (409)."

    Design: Difficulty/resource_temporal_overlap/booking_occupancy_half_open_adjacency_allowed_on_property
    """
    world = occupied_unit
    response = api.create_booking(create_booking_payload(
        world["p1"]["id"], external_ref="OVL-1", guest_name="Guest Overlap",
        checkin_at="2026-08-08T15:59:00Z", checkout_at="2026-08-08T20:00:00Z"),
        COORDINATOR)
    validate_error(response, ApiErrorId.ERR_BOOKING_OVERLAP.value, 409)

    _, meta = validate_paginated(api.list_bookings(
        COORDINATOR, {"property_id": world["p1"]["id"]}))
    assert meta["total_count"] == 1, (
        f"the refused import must leave only the sitting stay, "
        f"got {meta['total_count']}")


def test_02_a_stay_beginning_at_the_exact_departure_instant_is_accepted(
        api, occupied_unit):
    """Zero occupancy buffer makes back-to-back stays legal on the same unit.

    PRD §2.6: "There is no occupancy buffer whatsoever — the buffer is zero
    minutes — so a new stay may begin at the exact instant a prior stay ends and
    that adjacency is permitted rather than rejected." PRD §3.2: "A fresh
    reservation lands with `status` `SCHEDULED`, `checkin_gate` `OPEN` and
    `guest_notice_code` `NONE`, and is refused with `ERR_BOOKING_OVERLAP` if its
    half-open occupancy interval collides with another `SCHEDULED` or
    `CHECKED_OUT` stay on the same unit under the zero-buffer rule of §2.6."

    Design: Difficulty/resource_temporal_overlap/booking_occupancy_half_open_adjacency_allowed_on_property
    """
    world = occupied_unit
    api.create_booking(create_booking_payload(
        world["p1"]["id"], external_ref="OVL-1", guest_name="Guest Overlap",
        checkin_at="2026-08-08T15:59:00Z", checkout_at="2026-08-08T20:00:00Z"),
        COORDINATOR)

    adjacent = validate_success(api.create_booking(create_booking_payload(
        world["p1"]["id"], external_ref="ADJ-1", guest_name="Guest Adjacent",
        checkin_at="2026-08-08T16:00:00Z", checkout_at="2026-08-08T20:00:00Z"),
        COORDINATOR), 201)

    assert adjacent["status"] == "SCHEDULED", (
        f"the adjacent stay must be imported, got {adjacent['status']}")
    assert adjacent["checkin_gate"] == "OPEN", (
        f"a fresh reservation opens its gate, got {adjacent['checkin_gate']}")
    assert adjacent["checkin_at"] == world["b_out"]["checkout_at"], (
        f"the arrival must sit exactly on the prior departure, "
        f"got {adjacent['checkin_at']} against {world['b_out']['checkout_at']}")

    rows, meta = validate_paginated(api.list_bookings(
        COORDINATOR, {"property_id": world["p1"]["id"]}))
    assert meta["total_count"] == 2, (
        f"only the sitting stay and the adjacent one may exist, "
        f"got {meta['total_count']}")
    assert {row["external_ref"] for row in rows} == {"OUT-1", "ADJ-1"}
    assert validate_success(api.get_booking(
        world["b_out"]["id"], COORDINATOR))["status"] == "SCHEDULED", (
        "the refused import must not have disturbed the sitting stay")


# ─── cleaner_cross_zone_buffer_overlap_rejected_and_exact_boundary_… ──────

def test_03_a_ten_minute_gap_across_zones_collides_with_the_held_window(
        api, cross_zone_schedule_world):
    """A ZONE_A to ZONE_B hop demands 45 minutes, so 10 minutes is a conflict.

    PRD §2.6: "When comparing two turnover windows held by the same cleaner,
    the buffer is 15 minutes if the two turnovers' properties share the same
    `zone_code`, and 45 minutes otherwise." PRD §2.6: "The two windows conflict
    when the first window's start is strictly earlier than the second window's
    end extended forward by the buffer, and simultaneously the second window's
    start is strictly earlier than the first window's end extended forward by
    the buffer." PRD §3.4: "In explicit mode nothing is filtered — each pool
    condition the named cleaner fails becomes an error in its own right
    instead: a suspended or offboarded cleaner draws `ERR_CLEANER_NOT_ACTIVE`,
    a cleaner outside the served zones or below the required skill tier draws
    `ERR_CLEANER_NOT_ELIGIBLE`, a cleaner already at the daily ceiling draws
    `ERR_CLEANER_DAILY_CAP_REACHED`, and a cleaner whose existing windows
    collide draws `ERR_CLEANER_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/cleaner_cross_zone_buffer_overlap_rejected_and_exact_boundary_allowed
    """
    world = cross_zone_schedule_world
    assert float(world["a1"]["match_score"]) == pytest.approx(0.9100, abs=0.00005), (
        f"the held ZONE_A offer must have scored 0.9100, "
        f"got {world['a1']['match_score']}")
    assert world["t2"]["window_minutes"] == 150, (
        f"20:40Z to 23:10Z is 150 minutes, got {world['t2']['window_minutes']}")
    assert world["t2"]["required_minutes"] == 140, (
        f"a ONE_BR with 1 bath and 1 bed requires 120 + 12 + 8 minutes, "
        f"got {world['t2']['required_minutes']}")

    response = api.assign_turnover(
        world["t2"]["id"],
        assign_turnover_payload(world["t2"]["version"], world["cc"]["id"]),
        COORDINATOR)
    validate_error(response, ApiErrorId.ERR_CLEANER_SCHEDULE_CONFLICT.value, 409)

    after = validate_success(api.get_turnover(world["t2"]["id"], COORDINATOR))
    assert after["version"] == 1, (
        f"the refused offer must leave the turn at version 1, "
        f"got {after['version']}")
    _, meta = validate_paginated(api.list_assignments(
        COORDINATOR, {"turnover_id": world["t2"]["id"]}))
    assert meta["total_count"] == 0, (
        f"no offer row may be created, got {meta['total_count']}")


def test_04_a_gap_of_exactly_the_buffer_length_is_not_a_conflict(
        api, cross_zone_schedule_world):
    """21:15 is not strictly earlier than 20:30 plus 45, so the offer lands.

    PRD §2.6: "Both comparisons are strict, so a gap of exactly the buffer
    length does **not** count as a conflict." PRD §3.4: "The zone factor is 1.0
    when the cleaner's `home_zone_code` equals the property's `zone_code`, 0.4
    when the property's zone appears among the cleaner's
    `secondary_zone_codes`, and 0.0 otherwise, the last case being reachable
    only for a cleaner who accepts cross-zone work." PRD §3.4: "Skill headroom
    measures how far above the unit's floor the cleaner sits: take the
    cleaner's `skill_level`, subtract the property's `min_skill_level`, add 1,
    divide by 4, and cap the result at 1.0 — so a cleaner exactly at the floor
    scores 0.25 of headroom and a cleaner four tiers above it saturates."

    Design: Difficulty/resource_temporal_overlap/cleaner_cross_zone_buffer_overlap_rejected_and_exact_boundary_allowed
    """
    world = cross_zone_schedule_world
    api.assign_turnover(
        world["t2"]["id"],
        assign_turnover_payload(world["t2"]["version"], world["cc"]["id"]),
        COORDINATOR)

    assert world["t3"]["window_minutes"] == 150, (
        f"21:15Z to 23:45Z is 150 minutes, got {world['t3']['window_minutes']}")
    assert world["t3"]["required_minutes"] == 140, (
        f"the second ZONE_B unit requires the same 140 minutes, "
        f"got {world['t3']['required_minutes']}")

    offer = validate_success(api.assign_turnover(
        world["t3"]["id"],
        assign_turnover_payload(world["t3"]["version"], world["cc"]["id"]),
        COORDINATOR), 201)
    assert offer["status"] == "OFFERED", (
        f"the boundary-legal offer must be created, got {offer['status']}")
    assert float(offer["zone_match_factor"]) == pytest.approx(0.4, abs=0.00005), (
        f"the unit's zone is a secondary zone for this cleaner, "
        f"got {offer['zone_match_factor']}")
    assert float(offer["match_score"]) == pytest.approx(0.7800, abs=0.00005), (
        f"0.50*0.92 + 0.30*0.4 + 0.20*1.0 is 0.7800, got {offer['match_score']}")

    after = validate_success(api.get_turnover(world["t3"]["id"], COORDINATOR))
    assert after["version"] == 2, (
        f"the accepted offer bumps this turn to version 2, got {after['version']}")
