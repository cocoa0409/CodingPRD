"""Two contended resources with deliberately opposite occupancy geometry.

A preservation rail position is occupied over a CLOSED-CLOSED interval with no
buffer, so the instant exactly equal to the incumbent's expiry still belongs to
the incumbent and a reopen there collides; one second later the same request is
accepted.  An event window is HALF-OPEN and widened by a symmetric two-hour
turnover buffer compared with strict inequalities, so the mirror-image edge --
a dinner starting exactly 120 minutes after another ends -- is legal, while one
minute earlier is refused.  Each edge is pinned at the exact instant and at the
instant one unit inside.
"""
from datetime import datetime

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ERR_EVENT_WINDOW_CONFLICT, ERR_SLOT_OCCUPIED
from test_helpers.assertions import assert_fields_equal
from test_helpers.test_users import BEVERAGE_DIRECTOR_HEADERS, sommelier_headers

_CATEGORY_TARGETS = f.cogs_targets(
    30.0, WHITE=25.0, ROSE=28.0, RED=28.0, DESSERT=32.0, FORTIFIED=35.0)


def _instant(value):
    """Parse a server-minted ISO 8601 instant, tolerating the fractional digits."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _harbor_room(**overrides):
    fx.set_clock("2026-09-01T12:00:00Z")
    return fx.create_venue(name="Harbor Room", venue_code="HRB",
                           cogs_target_pct_by_category=_CATEGORY_TARGETS,
                           priority_rank=1, **overrides)


def _red_wine():
    return fx.create_wine(producer="Ridge", cuvee="Monte Bello", vintage_year=2019,
                          category="RED", reference_cost_cents=2400,
                          bottle_size_ml=750, case_pack=6, is_allocated=False)


def _published_btg_programme(venue):
    return fx.setup_published_entry(
        venue=venue, wine=_red_wine(), by_the_glass=True, pour_size_ml=177,
        bottles_received=12, unit_cost_cents=2400,
        received_at="2026-08-10T00:00:00Z",
        entry_overrides={"par_bottles": 6, "education_verified": False})


def _slot_response(venue, entry, lot, slot_index=1):
    venue_id = venue["id"]
    payload = f.btg_slot_payload(venue_id, entry["id"], lot["id"], slot_index,
                                 "ARGON")
    return api_client.create_btg_slot(payload, sommelier_headers(venue_id))


class TestPreservationRailAdjacencyCollides:
    """A rail position is held from `opened_at` through `preservation_expires_at`
    inclusive with no buffer.  The incumbent is a RED wine under argon opened at
    2026-09-01T12:00:00Z, so its computed expiry is 192 hours later."""

    def test_a_reopen_at_the_exact_expiry_instant_is_refused_as_occupied(self):
        """The instant equal to the incumbent's expiry still belongs to the incumbent.

        "Adjacency therefore collides: a request at an instant exactly equal to an occupant's expiry is rejected, while one millisecond later is accepted, and all comparisons are made at whole-millisecond granularity."

        Design: Difficulty/resource_temporal_overlap/btg_slot_closed_closed_adjacency_collides_at_exact_expiry
        """
        venue = _harbor_room()
        chain = _published_btg_programme(venue)
        incumbent = fx.open_slot(venue, chain["entry"], chain["lot"], slot_index=1,
                                 preservation_method="ARGON")
        assert _instant(incumbent["opened_at"]) == _instant("2026-09-01T12:00:00Z")
        assert _instant(incumbent["preservation_expires_at"]) == _instant(
            "2026-09-09T12:00:00Z"), (
            "RED at 96 base hours doubled by ARGON gives 192 hours, got %r"
            % (incumbent["preservation_expires_at"],))

        fx.set_clock("2026-09-09T12:00:00Z")
        validate_error(_slot_response(venue, chain["entry"], chain["lot"],
                                     slot_index=1),
                       ERR_SLOT_OCCUPIED)

        still = validate_success(api_client.get_btg_slot(
            incumbent["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert still["state"] == "OPEN", (
            "a rejected occupancy check must not expire the incumbent, got %r"
            % (still["state"],))
        _rows, meta = validate_paginated(api_client.list_btg_slots(
            BEVERAGE_DIRECTOR_HEADERS, params={"venue_id": venue["id"]}))
        assert meta["total_count"] == 1, (
            "the refused reopen must leave the rail with a single row, got %r"
            % (meta["total_count"],))

    def test_a_reopen_one_second_past_the_expiry_is_accepted_and_expires_the_incumbent(self):
        """One second past the expiry the position is free and the incumbent is swept.

        "When no occupant covers the current instant, any occupant still sitting in `OPEN` whose expiry the clock has passed is swept `OPEN → EXPIRED` as part of accepting the new slot; that sweep writes no ledger entry and leaves its stale bottle still committed to the abandoned slot, where it stays until a write-off resolves it."

        Design: Difficulty/resource_temporal_overlap/btg_slot_closed_closed_adjacency_collides_at_exact_expiry
        """
        venue = _harbor_room()
        chain = _published_btg_programme(venue)
        incumbent = fx.open_slot(venue, chain["entry"], chain["lot"], slot_index=1,
                                 preservation_method="ARGON")

        fx.set_clock("2026-09-09T12:00:01Z")
        successor = validate_success(
            _slot_response(venue, chain["entry"], chain["lot"], slot_index=1), 201)
        assert_fields_equal(successor, {"state": "OPEN", "slot_index": 1},
                            name="successor slot")
        assert _instant(successor["preservation_expires_at"]) == _instant(
            "2026-09-17T12:00:01Z"), (
            "the successor's own 192-hour window runs from its opened_at, got %r"
            % (successor["preservation_expires_at"],))

        swept = validate_success(api_client.get_btg_slot(
            incumbent["id"], BEVERAGE_DIRECTOR_HEADERS))
        assert swept["state"] == "EXPIRED", (
            "accepting the successor must sweep the passed-expiry incumbent to"
            " EXPIRED, got %r" % (swept["state"],))

    def test_the_occupancy_refusal_is_scoped_to_the_rail_position(self):
        """A different rail position is free at the very instant position one is held.

        "When a new slot is requested, the system looks at the slots on the same venue and the same `slot_index` whose state is `OPEN` or `EXPIRED`."

        Design: Difficulty/resource_temporal_overlap/btg_slot_closed_closed_adjacency_collides_at_exact_expiry
        """
        venue = _harbor_room()
        chain = _published_btg_programme(venue)
        fx.open_slot(venue, chain["entry"], chain["lot"], slot_index=1,
                     preservation_method="ARGON")

        fx.set_clock("2026-09-09T12:00:00Z")
        validate_error(_slot_response(venue, chain["entry"], chain["lot"],
                                     slot_index=1),
                       ERR_SLOT_OCCUPIED)
        neighbour = validate_success(
            _slot_response(venue, chain["entry"], chain["lot"], slot_index=2), 201)
        assert_fields_equal(neighbour, {"state": "OPEN", "slot_index": 2},
                            name="neighbouring slot")


def _dinner_venue():
    """Venue with a published by-the-glass RED entry, ready to take dinners."""
    venue = _harbor_room(event_cogs_target_pct=28.0)
    return _published_btg_programme(venue)


def _event_response(chain, name, starts_at, ends_at):
    venue_id = chain["venue"]["id"]
    payload = f.wine_dinner_event_payload(
        venue_id, chain["version"]["id"],
        [f.pour_plan_line(chain["entry"]["id"], 2)],
        name=name, starts_at=starts_at, ends_at=ends_at, seat_count=24)
    return api_client.create_wine_dinner_event(payload,
                                              sommelier_headers(venue_id))


class TestEventWindowBufferAdjacencyIsAllowed:
    """Event windows are half-open and each existing window is widened by 120
    minutes on each side, compared with strict inequalities -- so the exact
    buffer edge is legal.  The incumbent runs 18:00 to 21:00 on 2026-10-10, which
    puts the edge at 23:00."""

    def test_a_dinner_one_minute_inside_the_turnover_buffer_is_refused(self):
        """A 22:59 start falls inside the incumbent's 21:00-plus-two-hours buffer.

        "Because both comparisons are strict, adjacency is permitted: an event starting exactly 120 minutes after another one ends is accepted, while one minute earlier is refused."

        Design: Difficulty/resource_temporal_overlap/event_window_half_open_buffer_adjacency_allowed_at_exact_edge
        """
        chain = _dinner_venue()
        incumbent = validate_success(_event_response(
            chain, "Ridge Vertical", "2026-10-10T18:00:00Z",
            "2026-10-10T21:00:00Z"), 201)
        assert incumbent["state"] == "PLANNED"

        validate_error(_event_response(chain, "Late Seating A",
                                      "2026-10-10T22:59:00Z",
                                      "2026-10-11T01:00:00Z"),
                       ERR_EVENT_WINDOW_CONFLICT)

        _rows, meta = validate_paginated(api_client.list_wine_dinner_events(
            BEVERAGE_DIRECTOR_HEADERS, params={"venue_id": chain["venue"]["id"]}))
        assert meta["total_count"] == 1, (
            "the refused dinner must leave no row, got %r" % (meta["total_count"],))

    def test_a_dinner_starting_exactly_at_the_buffer_edge_is_accepted(self):
        """A 23:00 start is exactly 120 minutes after the incumbent ends and is legal.

        "A new event conflicts with an existing one when the new event's `starts_at` falls strictly before that event's `ends_at` advanced by the buffer **and** that event's `starts_at` falls strictly before the new event's `ends_at` advanced by the buffer."

        Design: Difficulty/resource_temporal_overlap/event_window_half_open_buffer_adjacency_allowed_at_exact_edge
        """
        chain = _dinner_venue()
        incumbent = validate_success(_event_response(
            chain, "Ridge Vertical", "2026-10-10T18:00:00Z",
            "2026-10-10T21:00:00Z"), 201)
        validate_error(_event_response(chain, "Late Seating A",
                                      "2026-10-10T22:59:00Z",
                                      "2026-10-11T01:00:00Z"),
                       ERR_EVENT_WINDOW_CONFLICT)

        late = validate_success(_event_response(
            chain, "Late Seating B", "2026-10-10T23:00:00Z",
            "2026-10-11T01:00:00Z"), 201)
        assert_fields_equal(late, {"state": "PLANNED", "pinned_version_no": 1,
                                   "pinned_version_stale": False},
                            name="edge-adjacent dinner")

        rows, meta = validate_paginated(api_client.list_wine_dinner_events(
            BEVERAGE_DIRECTOR_HEADERS, params={"venue_id": chain["venue"]["id"]}))
        assert meta["total_count"] == 2, (
            "exactly the incumbent and the edge-adjacent dinner survive, got %r"
            % (meta["total_count"],))
        assert [row["id"] for row in rows] == [incumbent["id"], late["id"]], (
            "dinners come back in starts_at ascending order")

    def test_cancelling_a_dinner_releases_its_window_for_rebooking(self):
        """The occupant set is state-filtered: a cancelled dinner holds nothing.

        "Any conflict against an event of the same venue in state `PLANNED`, `PRICED`, `CONFIRMED`, `SETTLED` or `SETTLEMENT_VOIDED` is refused with `ERR_EVENT_WINDOW_CONFLICT` (HTTP 409); cancelled events do not occupy their windows, and cancelling an event releases its window for future bookings."

        Design: Difficulty/resource_temporal_overlap/event_window_half_open_buffer_adjacency_allowed_at_exact_edge
        """
        chain = _dinner_venue()
        venue_id = chain["venue"]["id"]
        incumbent = validate_success(_event_response(
            chain, "Ridge Vertical", "2026-10-10T18:00:00Z",
            "2026-10-10T21:00:00Z"), 201)
        validate_error(_event_response(chain, "Second Sitting",
                                      "2026-10-10T18:00:00Z",
                                      "2026-10-10T21:00:00Z"),
                       ERR_EVENT_WINDOW_CONFLICT)

        cancelled = validate_success(api_client.cancel_event(
            incumbent["id"], f.note_payload("Chef unavailable."),
            sommelier_headers(venue_id)))
        assert cancelled["state"] == "CANCELLED"

        rebooked = validate_success(_event_response(
            chain, "Second Sitting", "2026-10-10T18:00:00Z",
            "2026-10-10T21:00:00Z"), 201)
        assert rebooked["state"] == "PLANNED"

    def test_the_surviving_dinner_still_holds_the_window_the_cancelled_one_freed(self):
        """Cancelling the incumbent does not free a window the edge-adjacent dinner covers.

        "A new event conflicts with an existing one when the new event's `starts_at` falls strictly before that event's `ends_at` advanced by the buffer **and** that event's `starts_at` falls strictly before the new event's `ends_at` advanced by the buffer."

        Design: Difficulty/resource_temporal_overlap/event_window_half_open_buffer_adjacency_allowed_at_exact_edge
        """
        chain = _dinner_venue()
        venue_id = chain["venue"]["id"]
        incumbent = validate_success(_event_response(
            chain, "Ridge Vertical", "2026-10-10T18:00:00Z",
            "2026-10-10T21:00:00Z"), 201)
        validate_success(_event_response(
            chain, "Late Seating B", "2026-10-10T23:00:00Z",
            "2026-10-11T01:00:00Z"), 201)
        validate_success(api_client.cancel_event(
            incumbent["id"], f.note_payload("Chef unavailable."),
            sommelier_headers(venue_id)))

        validate_error(_event_response(chain, "Late Seating A",
                                      "2026-10-10T22:59:00Z",
                                      "2026-10-11T01:00:00Z"),
                       ERR_EVENT_WINDOW_CONFLICT)
