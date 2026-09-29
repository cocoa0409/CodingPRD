"""The examiner's buffered calendar and the project's aggregate outage capacity."""
from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers.assertions import assert_flow
from test_helpers.factories import build_commission_payload, build_schedule_witness_payload
from test_helpers.fixtures import (
    create_auxiliary_system,
    open_acceptance_test,
    read_acceptance_test,
    read_auxiliary_system,
    read_project,
    build_permitted_stage,
    build_project_stage,
)
from test_helpers.test_users import make_ahj_reviewer_headers, make_contractor_headers

BOOKED_START = "2026-09-10T09:00:00.000Z"
BOOKED_END = "2026-09-10T11:00:00.000Z"
# One hour of travel on each side of a closed interval, so a 60 minute gap collides.
EXACT_BUFFER_START = "2026-09-10T12:00:00.000Z"
ONE_MINUTE_CLEAR_START = "2026-09-10T12:01:00.000Z"
CANDIDATE_END = "2026-09-10T13:00:00.000Z"


def _to_minute(timestamp):
    """Compare instants without depending on the server's fractional-second format."""
    assert timestamp is not None
    return timestamp[:16]


def _book(client, ctx, acceptance_test_id, start, end):
    return client.schedule_witness(
        acceptance_test_id,
        build_schedule_witness_payload(witness_window_start=start, witness_window_end=end),
        make_ahj_reviewer_headers(ctx["reviewer_id"]),
    )


def _two_tests_one_booked(client):
    ctx = build_permitted_stage(client)
    ctx["first_test"] = open_acceptance_test(client, ctx["project_id"])
    ctx["second_test"] = open_acceptance_test(
        client, ctx["project_id"], test_type="STANDPIPE_FLOW_TEST"
    )
    ctx["first_test"] = validate_success(
        _book(client, ctx, ctx["first_test"]["id"], BOOKED_START, BOOKED_END)
    )
    return ctx


class TestWitnessCalendarBuffer:
    def test_01_a_gap_of_exactly_sixty_minutes_collides(self, client):
        """Because both comparisons are inclusive, a gap of exactly 60 minutes between two
        windows collides, and a gap of 61 minutes does not.

        Design: Difficulty/resource_temporal_overlap/witness_calendar_closed_interval_with_sixty_minute_buffer_rejects_exact_gap
        """
        ctx = _two_tests_one_booked(client)
        assert ctx["first_test"]["witness_status"] == "SCHEDULED"
        assert _to_minute(ctx["first_test"]["witness_window_end"]) == "2026-09-10T11:00"

        refused = _book(
            client, ctx, ctx["second_test"]["id"], EXACT_BUFFER_START, CANDIDATE_END
        )
        validate_error(refused, "ERR_WITNESS_WINDOW_CONFLICT", expected_status=409)

        untouched = read_acceptance_test(client, ctx["second_test"]["id"])
        assert untouched["witness_status"] == "NOT_SCHEDULED"
        assert untouched["witness_window_start"] is None
        assert untouched["witness_window_end"] is None
        assert untouched["witness_reviewer_id"] is None

    def test_02_one_minute_more_clears_the_buffer_and_books(self, client):
        """The candidate window is inflated by one hour on each side, and the booking is
        refused with `ERR_WITNESS_WINDOW_CONFLICT` when the inflated candidate intersects
        the window of any other acceptance test naming the same `witness_reviewer_id` whose
        `witness_status` is `SCHEDULED`.

        Design: Difficulty/resource_temporal_overlap/witness_calendar_closed_interval_with_sixty_minute_buffer_rejects_exact_gap
        """
        ctx = _two_tests_one_booked(client)
        validate_error(
            _book(client, ctx, ctx["second_test"]["id"], EXACT_BUFFER_START, CANDIDATE_END),
            "ERR_WITNESS_WINDOW_CONFLICT",
        )
        booked = validate_success(
            _book(
                client,
                ctx,
                ctx["second_test"]["id"],
                ONE_MINUTE_CLEAR_START,
                CANDIDATE_END,
            )
        )
        assert booked["witness_status"] == "SCHEDULED"
        assert _to_minute(booked["witness_window_start"]) == "2026-09-10T12:01"
        assert _to_minute(booked["witness_window_end"]) == "2026-09-10T13:00"
        assert booked["witness_reviewer_id"] == ctx["reviewer_id"]
        assert booked["retest_count"] == 0

        rows, meta = validate_paginated(
            client.list_acceptance_tests(
                make_ahj_reviewer_headers(ctx["reviewer_id"]),
                params={
                    "witness_reviewer_id": ctx["reviewer_id"],
                    "witness_status": "SCHEDULED",
                },
            )
        )
        assert meta["total_count"] == 2
        assert {row["id"] for row in rows} == {
            ctx["first_test"]["id"],
            ctx["second_test"]["id"],
        }


OUTAGE_A = ("2026-09-08T09:00:00.000Z", "2026-09-08T12:00:00.000Z")
OUTAGE_B = ("2026-09-08T11:00:00.000Z", "2026-09-08T14:00:00.000Z")
THIRD_IN_FLIGHT = ("2026-09-08T11:30:00.000Z", "2026-09-08T13:00:00.000Z")
TOUCHING_THE_FIRST_END = ("2026-09-08T12:00:00.000Z", "2026-09-08T13:00:00.000Z")
HOSE_STATION_DEMAND_GPM = 100.0


def _commission(client, system_id, window):
    start, end = window
    return client.commission_auxiliary_system(
        system_id,
        build_commission_payload(outage_start_at=start, outage_end_at=end),
        make_contractor_headers(),
    )


def _three_hose_stations_two_in_flight(client):
    ctx = build_project_stage(client)
    ctx["stations"] = [
        create_auxiliary_system(
            client,
            ctx["project_id"],
            ctx["lead_id"],
            system_type="STANDPIPE_CLASS_II",
            label=f"Hose station {letter}",
            riser_count=1,
        )
        for letter in ("A", "B", "C")
    ]
    validate_success(_commission(client, ctx["stations"][0]["id"], OUTAGE_A))
    validate_success(_commission(client, ctx["stations"][1]["id"], OUTAGE_B))
    return ctx


class TestOutageConcurrencyCap:
    def test_03_two_overlapping_outages_are_legal_and_the_third_instant_is_not(self, client):
        """the request is refused with `ERR_OUTAGE_CONCURRENCY_EXCEEDED` when some instant
        inside the candidate half-open window falls inside the half-open outage windows of
        two or more *other* auxiliary systems of the same project whose `status` is
        `COMMISSIONED`.

        Design: Difficulty/resource_temporal_overlap/outage_calendar_half_open_aggregate_cap_of_two_concurrent_systems
        """
        ctx = _three_hose_stations_two_in_flight(client)
        for station in ctx["stations"][:2]:
            assert read_auxiliary_system(client, station["id"])["status"] == "COMMISSIONED"

        third = ctx["stations"][2]
        refused = _commission(client, third["id"], THIRD_IN_FLIGHT)
        validate_error(refused, "ERR_OUTAGE_CONCURRENCY_EXCEEDED", expected_status=409)

        untouched = read_auxiliary_system(client, third["id"])
        assert untouched["status"] == "PROPOSED"
        assert untouched["outage_start_at"] is None
        assert untouched["outage_end_at"] is None

    def test_04_a_window_starting_where_the_first_outage_ends_is_accepted(self, client):
        """The outage window is a **half-open** interval: it includes its start instant and
        excludes its end instant, so a window that ends exactly when another begins does not
        overlap it, and no travel buffer is applied.

        Design: Difficulty/resource_temporal_overlap/outage_calendar_half_open_aggregate_cap_of_two_concurrent_systems
        """
        ctx = _three_hose_stations_two_in_flight(client)
        third = ctx["stations"][2]
        validate_error(
            _commission(client, third["id"], THIRD_IN_FLIGHT),
            "ERR_OUTAGE_CONCURRENCY_EXCEEDED",
        )
        commissioned = validate_success(
            _commission(client, third["id"], TOUCHING_THE_FIRST_END)
        )
        assert commissioned["status"] == "COMMISSIONED"
        assert _to_minute(commissioned["outage_start_at"]) == "2026-09-08T12:00"
        assert commissioned["interlock_required"] is False
        assert_flow(commissioned["demand_gpm"], HOSE_STATION_DEMAND_GPM)

        # Commissioning never moves the ledger; only creation and withdrawal do.
        project = read_project(client, ctx["project_id"])
        assert_flow(project["auxiliary_demand_gpm"], 3 * HOSE_STATION_DEMAND_GPM)

        rows, meta = validate_paginated(
            client.list_auxiliary_systems(
                make_contractor_headers(),
                params={"project_id": ctx["project_id"], "status": "COMMISSIONED"},
            )
        )
        assert meta["total_count"] == 3
        assert len(rows) == 3
