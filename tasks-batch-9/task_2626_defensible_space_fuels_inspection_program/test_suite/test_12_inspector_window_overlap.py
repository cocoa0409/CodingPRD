"""The inspector's half-open occupation window: adjacency versus intersection."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ERR_INSPECTOR_WINDOW_CONFLICT,
    create_inspector,
    create_parcel,
    get_inspector,
    inspection_payload,
    list_inspections,
    open_cycle,
    reason_payload,
    schedule_inspection,
)
from test_helpers.test_users import PROGRAM_ADMIN_HEADERS


def _adjacent_bookings_world(client):
    """One inspector holding two exactly adjacent visits, plus a free parcel.

    ins1 occupies 2026-08-20T15:00Z-17:00Z on p1 and ins2 occupies
    2026-08-20T17:00Z-19:00Z on p2; the second booking is accepted precisely
    because the windows are half-open.  p3 carries nothing yet.
    """
    cycle = open_cycle(client)
    inspector = create_inspector(client)
    parcels = [create_parcel(client) for _ in range(3)]
    first = schedule_inspection(
        client,
        parcels[0]["id"],
        cycle["id"],
        inspector["id"],
        scheduled_start_utc="2026-08-20T15:00:00Z",
        scheduled_end_utc="2026-08-20T17:00:00Z",
    )
    second = schedule_inspection(
        client,
        parcels[1]["id"],
        cycle["id"],
        inspector["id"],
        scheduled_start_utc="2026-08-20T17:00:00Z",
        scheduled_end_utc="2026-08-20T19:00:00Z",
    )
    return {
        "cycle": cycle,
        "inspector": inspector,
        "parcels": parcels,
        "first": first,
        "second": second,
    }


def _book(client, world, start, end, inspector_id=None):
    return client.create_inspection(
        inspection_payload(
            world["parcels"][2]["id"],
            world["cycle"]["id"],
            inspector_id or world["inspector"]["id"],
            start,
            end,
        ),
        headers=PROGRAM_ADMIN_HEADERS,
    )


class TestInspectorWindowOverlap:
    """Touching endpoints are free; any real intersection is refused."""

    def test_adjacency_is_accepted_but_a_straddling_window_conflicts(self, client):
        """[17:00, 19:00) sits happily beside [15:00, 17:00), while [16:00, 18:00)
        straddles both and is refused.

        PRD: "the requested window is treated as half-open, occupying every
        instant from scheduled_start_utc inclusive up to scheduled_end_utc
        exclusive, and it must not intersect the half-open window of any other
        inspection assigned to the same inspector that still stands in SCHEDULED,
        NOTICED or ACCESS_DENIED."

        PRD: "Because the window is half-open, exact adjacency is fine - a new
        visit starting at the precise instant an existing one ends, or ending at
        the precise instant an existing one begins, does not conflict. Any real
        overlap is refused with ERR_INSPECTOR_WINDOW_CONFLICT."

        PRD: "An inspector's assigned_open_count must always equal the number of
        inspections carrying that inspector_id whose status is SCHEDULED, NOTICED
        or ACCESS_DENIED."

        Design: Difficulty/resource_temporal_overlap/inspector_half_open_window_adjacent_ok_overlap_conflict
        """
        world = _adjacent_bookings_world(client)
        assert world["second"]["status"] == "SCHEDULED"
        assert get_inspector(client, world["inspector"]["id"])["assigned_open_count"] == 2

        validate_error(
            _book(client, world, "2026-08-20T16:00:00Z", "2026-08-20T18:00:00Z"),
            ERR_INSPECTOR_WINDOW_CONFLICT,
        )
        rows, _meta = list_inspections(client, parcel_id=world["parcels"][2]["id"])
        assert rows == [], "a refused booking must leave no inspection behind"
        assert get_inspector(client, world["inspector"]["id"])["assigned_open_count"] == 2

        # A new end equal to an existing start is mere adjacency too.
        earlier = validate_success(
            _book(client, world, "2026-08-20T13:00:00Z", "2026-08-20T15:00:00Z"), 201
        )
        assert earlier["status"] == "SCHEDULED"
        assert get_inspector(client, world["inspector"]["id"])["assigned_open_count"] == 3

    def test_one_second_of_overlap_conflicts_and_cancellation_frees_the_window(
        self, client
    ):
        """A single second of intersection is enough to refuse, and a CANCELLED
        visit stops occupying its window at all.

        PRD: "Any real overlap is refused with ERR_INSPECTOR_WINDOW_CONFLICT."

        PRD: "Cancellation releases the inspector's half-open window so that a
        later inspection may occupy it and decrements that inspector's
        assigned_open_count by 1."

        PRD: "Inspections that have reached COMPLETED, CANCELLED or ABANDONED
        release their window and no longer block anything."

        Design: Difficulty/resource_temporal_overlap/inspector_half_open_window_adjacent_ok_overlap_conflict
        """
        world = _adjacent_bookings_world(client)

        validate_error(
            _book(client, world, "2026-08-20T16:59:59Z", "2026-08-20T18:00:00Z"),
            ERR_INSPECTOR_WINDOW_CONFLICT,
        )

        # The constraint is per inspector, never global.
        other = create_inspector(client)
        shared = validate_success(
            _book(
                client,
                world,
                "2026-08-20T16:00:00Z",
                "2026-08-20T18:00:00Z",
                inspector_id=other["id"],
            ),
            201,
        )
        assert shared["inspector_id"] == other["id"]

        validate_success(
            client.cancel_inspection(
                world["first"]["id"],
                headers=PROGRAM_ADMIN_HEADERS,
                payload=reason_payload("Owner rescheduled"),
            )
        )
        assert get_inspector(client, world["inspector"]["id"])["assigned_open_count"] == 1

        reused = validate_success(
            _book(client, world, "2026-08-20T15:00:00Z", "2026-08-20T17:00:00Z"), 201
        )
        assert reused["status"] == "SCHEDULED"
        assert reused["inspector_id"] == world["inspector"]["id"]
