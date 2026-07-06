"""Events, RSVP capacity, group concurrency, CivicNotice adjacency + overlap."""
import pytest

from test_helpers import (
    get_success_data, validate_success, validate_error,
    make_resident_headers, make_agency_officer_headers,
    setup_neighborhood_with_verified_residents,
    create_group, create_event, rsvp_yes,
    create_active_civic_notice,
    create_neighborhood, set_clock, api_client, ADMIN,
    AGENCY_OFFICER_USER_ID,
)


class TestEventRsvpCapacityBoundary:
    """Difficulty rule 6 — boundary at rsvp_count == capacity for RSVP."""

    def test_rsvp_admits_at_capacity_minus_one_and_rejects_at_capacity(self, api):
        """PRD §3.6: "Before an increment is applied, the event capacity is
        evaluated with a non-strict boundary: if the event's `rsvp_count` is
        at least the event's `capacity`, the RSVP is rejected with
        `ERR_EVENT_FULL` (HTTP 409). This means a 500-capacity event admits
        resident number 500 (whose RSVP raises the count from 499 to 500)
        and rejects resident number 501."

        Design: Difficulty/boundary_precision_check/event_rsvp_admits_at_capacity_minus_one_and_rejects_at_capacity
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod, residents = setup_neighborhood_with_verified_residents(4)
        r1 = residents[0]
        g = create_group(r1["id"], n["id"], name="Book Club")
        e = create_event(g["id"], n["id"], creator_resident_id=r1["id"],
                         capacity=3)
        # 3 RSVPs by R2, R3, R4 fill the event.
        for r in residents[1:4]:
            rsvp_yes(e["id"], r["id"])
        e_now = get_success_data(api_client.get_event(e["id"], ADMIN))
        assert e_now["rsvp_count"] == 3, \
            f"Expected rsvp_count=3 after third YES (boundary allowed), got {e_now['rsvp_count']}"
        # R1's YES now exceeds capacity -> ERR_EVENT_FULL.
        from test_helpers import create_event_rsvp_payload
        resp = api_client.create_event_rsvp(
            create_event_rsvp_payload(e["id"], r1["id"], rsvp_status="YES"),
            make_resident_headers(r1["id"]),
        )
        validate_error(resp, "ERR_EVENT_FULL")

    def test_third_rsvp_lifts_count_from_two_to_three_at_capacity(self, api):
        """PRD §3.6: "This means a 500-capacity event admits resident number
        500 (whose RSVP raises the count from 499 to 500) and rejects
        resident number 501."

        Design: Difficulty/boundary_precision_check/event_rsvp_admits_at_capacity_minus_one_and_rejects_at_capacity
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod, residents = setup_neighborhood_with_verified_residents(4)
        r1 = residents[0]
        g = create_group(r1["id"], n["id"], name="BC")
        e = create_event(g["id"], n["id"], creator_resident_id=r1["id"],
                         capacity=3)
        rsvp_yes(e["id"], residents[1]["id"])
        rsvp_yes(e["id"], residents[2]["id"])
        e_mid = get_success_data(api_client.get_event(e["id"], ADMIN))
        assert e_mid["rsvp_count"] == 2
        # Third RSVP still succeeds (rsvp_count 2 -> 3).
        rsvp_yes(e["id"], residents[3]["id"])
        e_after = get_success_data(api_client.get_event(e["id"], ADMIN))
        assert e_after["rsvp_count"] == 3, \
            "Boundary RSVP at capacity-1 -> capacity must succeed"


class TestCivicNoticeAdjacentIntervalsDoNotOverlap:
    """Difficulty rule 6 empty-overlap boundary — [from, until) half-open."""

    def test_touching_intervals_on_same_kind_do_not_overlap(self, api):
        """PRD §3.5: "Two touching intervals do not overlap: when a
        scheduled notice's `effective_until` equals the proposed notice's
        `effective_from` (or vice versa), the proposed notice is accepted;
        any strictly interior overlap is rejected with the notice-window
        overlap error."
        PRD §2.6: "a touching endpoint (where one notice's `effective_until`
        equals another's `effective_from`) does not count as overlap. A true
        overlap is rejected with `ERR_NOTICE_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/civic_notice_adjacent_intervals_do_not_overlap
        """
        set_clock("2026-06-01T00:00:00Z")
        n = create_neighborhood()
        cn1 = create_active_civic_notice(
            n["id"], effective_from="2026-06-05T00:00:00Z",
            effective_until="2026-06-10T00:00:00Z",
            notice_kind="POLICE",
        )
        set_clock("2026-06-04T00:00:00Z")
        # cn2 starts exactly at cn1's end -> touching, not overlap.
        from test_helpers import create_civic_notice_payload
        resp = api_client.create_civic_notice(
            create_civic_notice_payload(
                n["id"], effective_from="2026-06-10T00:00:00Z",
                effective_until="2026-06-15T00:00:00Z", notice_kind="POLICE",
                title="Followup", body="more"),
            make_agency_officer_headers(AGENCY_OFFICER_USER_ID),
        )
        cn2 = validate_success(resp, expected_status=201)
        assert cn2["state"] == "SCHEDULED", \
            "Adjacent-boundary notice must be accepted"

    def test_touching_notice_has_scheduled_state(self, api):
        """PRD §3.5: "The notice begins in `state=SCHEDULED`."

        Design: Difficulty/boundary_precision_check/civic_notice_adjacent_intervals_do_not_overlap
        """
        set_clock("2026-06-01T00:00:00Z")
        n = create_neighborhood()
        create_active_civic_notice(
            n["id"], effective_from="2026-06-05T00:00:00Z",
            effective_until="2026-06-10T00:00:00Z", notice_kind="POLICE",
        )
        set_clock("2026-06-04T00:00:00Z")
        cn2 = create_active_civic_notice(
            n["id"], effective_from="2026-06-10T00:00:00Z",
            effective_until="2026-06-15T00:00:00Z", notice_kind="POLICE",
        )
        assert cn2["state"] == "SCHEDULED"


class TestCivicNoticeHalfOpenOverlap:
    """Difficulty rule 8 interval semantics — strictly-interior overlap rejects."""

    def test_overlap_by_one_hour_on_same_kind_returns_overlap(self, api):
        """PRD §3.5: "any strictly interior overlap is rejected with the
        notice-window overlap error."
        PRD §2.6: "A true overlap is rejected with
        `ERR_NOTICE_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/civic_notice_half_open_overlap_rejects_strict_intersect_on_same_kind
        """
        set_clock("2026-06-01T00:00:00Z")
        n = create_neighborhood()
        create_active_civic_notice(
            n["id"], effective_from="2026-06-05T00:00:00Z",
            effective_until="2026-06-10T00:00:00Z", notice_kind="POLICE",
        )
        # Propose a notice overlapping by 1h.
        from test_helpers import create_civic_notice_payload
        resp = api_client.create_civic_notice(
            create_civic_notice_payload(
                n["id"], effective_from="2026-06-09T23:00:00Z",
                effective_until="2026-06-11T00:00:00Z", notice_kind="POLICE"),
            make_agency_officer_headers(AGENCY_OFFICER_USER_ID),
        )
        validate_error(resp, "ERR_NOTICE_WINDOW_OVERLAP")

    def test_overlap_rejection_is_scoped_to_same_neighborhood_and_kind(self, api):
        """PRD §3.5: "the proposed half-open interval `[effective_from,
        effective_until)` must not overlap any `ACTIVE` or `SCHEDULED`
        `CivicNotice` sharing the same combination of `neighborhood_id` and
        `notice_kind`."

        A notice of a DIFFERENT kind on the same neighborhood is unaffected
        by the overlap check because the (neighborhood_id, notice_kind) key
        is composite.

        Design: Difficulty/resource_temporal_overlap/civic_notice_half_open_overlap_rejects_strict_intersect_on_same_kind
        """
        set_clock("2026-06-01T00:00:00Z")
        n = create_neighborhood()
        # POLICE notice.
        create_active_civic_notice(
            n["id"], effective_from="2026-06-05T00:00:00Z",
            effective_until="2026-06-10T00:00:00Z", notice_kind="POLICE",
        )
        # Overlapping FIRE notice must succeed (different notice_kind).
        cn_fire = create_active_civic_notice(
            n["id"], effective_from="2026-06-05T00:00:00Z",
            effective_until="2026-06-10T00:00:00Z", notice_kind="FIRE",
        )
        assert cn_fire["state"] == "SCHEDULED"


class TestGroupEventCapacityCeiling:
    """Difficulty rule 8 interval semantics 2 — 3-concurrent-event cap on group."""

    def test_fourth_concurrent_event_returns_group_event_capacity(self, api):
        """PRD §2.6: "On event creation, adding the new `Event` must not
        cause more than 3 `SCHEDULED` events on the same `group_id` to have
        half-open `[starts_at, ends_at)` intervals that mutually overlap;
        adjacency (one event's `ends_at` equal to another's `starts_at`)
        does not count as overlap, and exceeding the ceiling is rejected
        with `ERR_GROUP_EVENT_CAPACITY` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/event_group_aggregate_capacity_rejects_fourth_concurrent_event
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod, residents = setup_neighborhood_with_verified_residents(1)
        r1 = residents[0]
        g = create_group(r1["id"], n["id"], name="Club")
        # 3 overlapping SCHEDULED events.
        for i in range(3):
            create_event(g["id"], n["id"], creator_resident_id=r1["id"],
                         title=f"E{i+1}", capacity=10,
                         starts_at="2026-06-10T12:00:00Z",
                         ends_at="2026-06-10T14:00:00Z")
        # Fourth overlapping event -> ERR_GROUP_EVENT_CAPACITY.
        from test_helpers import create_event_payload
        resp = api_client.create_event(
            create_event_payload(g["id"], n["id"],
                                title="E4", capacity=10,
                                starts_at="2026-06-10T13:00:00Z",
                                ends_at="2026-06-10T15:00:00Z"),
            make_resident_headers(r1["id"]),
        )
        validate_error(resp, "ERR_GROUP_EVENT_CAPACITY")

    def test_group_event_ceiling_is_exactly_three(self, api):
        """PRD §2.6: "adding the new `Event` must not cause more than 3
        `SCHEDULED` events on the same `group_id` to have half-open
        `[starts_at, ends_at)` intervals that mutually overlap"

        Design: Difficulty/resource_temporal_overlap/event_group_aggregate_capacity_rejects_fourth_concurrent_event
        """
        set_clock("2026-06-01T00:00:00Z")
        n, mod, residents = setup_neighborhood_with_verified_residents(1)
        r1 = residents[0]
        g = create_group(r1["id"], n["id"], name="Club")
        # 3 overlapping SCHEDULED events must all be admitted.
        events = []
        for i in range(3):
            e = create_event(g["id"], n["id"], creator_resident_id=r1["id"],
                             title=f"E{i+1}", capacity=10,
                             starts_at="2026-06-10T12:00:00Z",
                             ends_at="2026-06-10T14:00:00Z")
            events.append(e)
        assert len(events) == 3, "Cap of 3 must permit 3 overlapping events"
