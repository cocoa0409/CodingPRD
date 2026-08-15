"""Difficulty tests — resource_temporal_overlap rule.

Covers lodging-block half-open adjacency and crew-lodging containment plus
aggregate capacity.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_and_activate_event,
    create_available_mutual_aid_crew,
    create_committed_lodging_block,
    create_lodging_block_payload,
    create_mutual_aid_crew_payload,
    get_success_data,
    set_clock,
    validate_error,
)

ED = TEST_USERS["emergency_director_headers"]
MAC = TEST_USERS["mutual_aid_coordinator_headers"]


class TestLodgingBlockHalfOpenAdjacencyVsOverlap:
    """Half-open [start, end) intervals: touching is allowed, overlap is not."""

    def test_adjacent_block_at_endpoint_is_allowed(self, api):
        """PRD §3.7: "a new block whose window overlaps an existing block for
        the same event and `hotel_name` under half-open interval semantics —
        touching at an endpoint does not overlap — is rejected with
        `ERR_LODGING_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/lodging_block_half_open_adjacency_vs_overlap
        """
        set_clock("2026-08-10T00:00:00Z")
        ev = create_and_activate_event(event_name="Storm Omicron", event_type="HURRICANE")
        lb_a = get_success_data(
            api.create_lodging_block(
                create_lodging_block_payload(
                    ev["id"],
                    hotel_name="Hotel H",
                    room_count=5,
                    nightly_rate_cents=10000,
                    window_start="2026-08-10T00:00:00Z",
                    window_end="2026-08-12T00:00:00Z",
                ),
                MAC,
            )
        )
        # Adjacency: B.window_start == A.window_end — allowed.
        lb_b = get_success_data(
            api.create_lodging_block(
                create_lodging_block_payload(
                    ev["id"],
                    hotel_name="Hotel H",
                    room_count=3,
                    nightly_rate_cents=10000,
                    window_start="2026-08-12T00:00:00Z",
                    window_end="2026-08-14T00:00:00Z",
                ),
                MAC,
            )
        )
        assert lb_b["id"] is not None

    def test_true_overlap_rejected_and_other_hotel_ignored(self, api):
        """PRD §3.7: "The uniqueness and overlap scope is the pair of storm
        event and hotel: a new block whose window overlaps an existing block
        for the same event and `hotel_name` under half-open interval semantics
        — touching at an endpoint does not overlap — is rejected with
        `ERR_LODGING_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/lodging_block_half_open_adjacency_vs_overlap
        """
        set_clock("2026-08-10T00:00:00Z")
        ev = create_and_activate_event(event_name="Storm Omicron", event_type="HURRICANE")
        get_success_data(
            api.create_lodging_block(
                create_lodging_block_payload(
                    ev["id"],
                    hotel_name="Hotel H",
                    room_count=5,
                    nightly_rate_cents=10000,
                    window_start="2026-08-10T00:00:00Z",
                    window_end="2026-08-12T00:00:00Z",
                ),
                MAC,
            )
        )
        # True overlap on the same hotel.
        resp = api.create_lodging_block(
            create_lodging_block_payload(
                ev["id"],
                hotel_name="Hotel H",
                room_count=2,
                nightly_rate_cents=10000,
                window_start="2026-08-11T00:00:00Z",
                window_end="2026-08-13T00:00:00Z",
            ),
            MAC,
        )
        err = validate_error(resp, ApiErrorId.ERR_LODGING_WINDOW_OVERLAP)
        assert err["error_id"] == "ERR_LODGING_WINDOW_OVERLAP"
        # Same window on a different hotel is allowed — scope is (event, hotel).
        lb_d = get_success_data(
            api.create_lodging_block(
                create_lodging_block_payload(
                    ev["id"],
                    hotel_name="Hotel H2",
                    room_count=2,
                    nightly_rate_cents=10000,
                    window_start="2026-08-10T00:00:00Z",
                    window_end="2026-08-12T00:00:00Z",
                ),
                MAC,
            )
        )
        assert lb_d["id"] is not None


class TestCrewLodgingContainmentAndAggregateCapacity:
    """Crew window must be contained in the block window; rooms are a sum."""

    def test_intersecting_but_not_contained_window_rejected(self, api):
        """PRD §3.7: "the crew's committed window must be contained in the
        block's window — starting no earlier than `window_start` and ending no
        later than `window_end` — (`ERR_WINDOW_OUTSIDE_BLOCK`)".

        Design: Difficulty/resource_temporal_overlap/crew_lodging_containment_and_aggregate_capacity
        """
        set_clock("2026-08-10T00:00:00Z")
        ev = create_and_activate_event(event_name="Storm Pi", event_type="ICE_STORM")
        lb = create_committed_lodging_block(
            ev["id"],
            room_count=3,
            nightly_rate_cents=10000,
            window_start="2026-08-10T00:00:00Z",
            window_end="2026-08-13T00:00:00Z",
            county_code="C1",
            hotel_name="Hotel H",
        )
        # Crew A: window pokes past the block's end.
        ma = get_success_data(
            api.create_mutual_aid_crew(
                create_mutual_aid_crew_payload(
                    ev["id"],
                    committed_window_start="2026-08-10T00:00:00Z",
                    committed_window_end="2026-08-14T00:00:00Z",
                    company_name="PeerCo A",
                    crew_type="LINE",
                    roster_size=1,
                ),
                MAC,
            )
        )
        get_success_data(api.mark_arrived(ma["id"], MAC))
        resp = api.assign_lodging(ma["id"], {"lodging_block_id": lb["id"]}, MAC)
        err = validate_error(resp, ApiErrorId.ERR_WINDOW_OUTSIDE_BLOCK)
        assert err["error_id"] == "ERR_WINDOW_OUTSIDE_BLOCK"
        block = get_success_data(api.get_lodging_block(lb["id"], MAC))
        assert block["rooms_allocated"] == 0

    def test_contained_assignment_then_capacity_exhaustion(self, api):
        """PRD §3.7: "the block must have room, meaning `rooms_allocated`
        plus the crew's `roster_size` stays within `room_count`
        (`ERR_NO_ROOMS_AVAILABLE`)".

        Design: Difficulty/resource_temporal_overlap/crew_lodging_containment_and_aggregate_capacity
        """
        set_clock("2026-08-10T00:00:00Z")
        ev = create_and_activate_event(event_name="Storm Pi", event_type="ICE_STORM")
        lb = create_committed_lodging_block(
            ev["id"],
            room_count=3,
            nightly_rate_cents=10000,
            window_start="2026-08-10T00:00:00Z",
            window_end="2026-08-13T00:00:00Z",
            county_code="C1",
            hotel_name="Hotel H",
        )
        # Crew B (roster 2) is contained; crew C (roster 2) would exceed 3.
        mb = get_success_data(
            api.create_mutual_aid_crew(
                create_mutual_aid_crew_payload(
                    ev["id"],
                    committed_window_start="2026-08-11T00:00:00Z",
                    committed_window_end="2026-08-12T00:00:00Z",
                    company_name="PeerCo B",
                    crew_type="TREE",
                    roster_size=2,
                ),
                MAC,
            )
        )
        mc = get_success_data(
            api.create_mutual_aid_crew(
                create_mutual_aid_crew_payload(
                    ev["id"],
                    committed_window_start="2026-08-11T00:00:00Z",
                    committed_window_end="2026-08-12T00:00:00Z",
                    company_name="PeerCo C",
                    crew_type="LINE",
                    roster_size=2,
                ),
                MAC,
            )
        )
        set_clock("2026-08-11T00:00:00Z")
        get_success_data(api.mark_arrived(mb["id"], MAC))
        get_success_data(api.mark_arrived(mc["id"], MAC))
        # Contained assignment succeeds.
        assigned = get_success_data(
            api.assign_lodging(mb["id"], {"lodging_block_id": lb["id"]}, MAC)
        )
        assert assigned["lodging_block_id"] == lb["id"]
        block = get_success_data(api.get_lodging_block(lb["id"], MAC))
        assert block["rooms_allocated"] == 2
        # Aggregate capacity: 2 + 2 > 3.
        resp = api.assign_lodging(mc["id"], {"lodging_block_id": lb["id"]}, MAC)
        err = validate_error(resp, ApiErrorId.ERR_NO_ROOMS_AVAILABLE)
        assert err["error_id"] == "ERR_NO_ROOMS_AVAILABLE"
        # No partial reservation was recorded.
        block = get_success_data(api.get_lodging_block(lb["id"], MAC))
        assert block["rooms_allocated"] == 2
