"""Server ingest-lane capacity: closed, aggregated windows over two lanes.

The canonical auditorium runs `dcp_ingest_lane_count` of 2, so two windows may
overlap freely and only a third simultaneous window is refused.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_dcp_asset,
    book_asset,
    dcp_asset_payload,
    read_asset,
    setup_programming_baseline,
    validate_error,
    validate_paginated,
)


def _asset_payload(world, carrier_ref, start_at, end_at):
    return dcp_asset_payload(
        world["title"]["id"],
        world["distributor"]["id"],
        world["venue"]["id"],
        carrier_ref=carrier_ref,
        ingest_window_start_at=start_at,
        ingest_window_end_at=end_at,
    )


def _carrier_refs(headers, venue_id):
    rows, meta = validate_paginated(
        api_client.list_dcp_assets(headers, {"venue_id": venue_id})
    )
    return [row["carrier_ref"] for row in rows], meta


class TestIngestWindowsTouchingAtAnEndpoint:
    """Both endpoints are inclusive, so a touching window is concurrent."""

    def test_window_starting_exactly_when_another_ends_is_counted_as_concurrent(
        self, technical_manager_headers
    ):
        """Two live windows plus a touching candidate makes three at one instant.

        PRD: "Because both endpoints are inclusive, a window beginning at exactly the instant another ends counts as concurrent at that instant."

        Design: Difficulty/boundary_precision_check/ingest_lane_window_touching_at_endpoint_counts_as_concurrent
        """
        world = setup_programming_baseline(
            asset_overrides={
                "carrier_ref": "WB-80001",
                "ingest_window_start_at": "2026-08-02T08:00:00Z",
                "ingest_window_end_at": "2026-08-03T08:00:00Z",
            }
        )
        book_asset(
            world["title"]["id"],
            world["distributor"]["id"],
            world["venue"]["id"],
            carrier_ref="WB-80002",
            ingest_window_start_at="2026-08-02T12:00:00Z",
            ingest_window_end_at="2026-08-03T12:00:00Z",
        )

        response = api_client.create_dcp_asset(
            _asset_payload(
                world, "WB-80003", "2026-08-03T08:00:00Z", "2026-08-04T00:00:00Z"
            ),
            technical_manager_headers,
        )

        validate_error(response, ApiErrorId.ERR_INGEST_LANE_CAPACITY_EXCEEDED)

    def test_window_starting_one_minute_after_the_endpoint_is_admitted(
        self, technical_manager_headers
    ):
        """One minute past the shared instant leaves only two windows in play.

        PRD: "If the largest count reached at any evaluated instant is strictly greater than the auditorium's `dcp_ingest_lane_count`, the booking is refused with `ERR_INGEST_LANE_CAPACITY_EXCEEDED`; otherwise it is admitted."

        Design: Difficulty/boundary_precision_check/ingest_lane_window_touching_at_endpoint_counts_as_concurrent
        """
        world = setup_programming_baseline(
            asset_overrides={
                "carrier_ref": "WB-80001",
                "ingest_window_start_at": "2026-08-02T08:00:00Z",
                "ingest_window_end_at": "2026-08-03T08:00:00Z",
            }
        )
        book_asset(
            world["title"]["id"],
            world["distributor"]["id"],
            world["venue"]["id"],
            carrier_ref="WB-80002",
            ingest_window_start_at="2026-08-02T12:00:00Z",
            ingest_window_end_at="2026-08-03T12:00:00Z",
        )

        admitted = book_asset(
            world["title"]["id"],
            world["distributor"]["id"],
            world["venue"]["id"],
            carrier_ref="WB-80004",
            ingest_window_start_at="2026-08-03T08:01:00Z",
            ingest_window_end_at="2026-08-04T00:00:00Z",
        )

        assert_dcp_asset(admitted)
        assert admitted["status"] == "REQUESTED"
        assert admitted["carrier_ref"] == "WB-80004"
        assert admitted["ingest_window_start_at"] == "2026-08-03T08:01:00.000Z"

    def test_refused_touching_window_creates_no_asset_row(
        self, technical_manager_headers
    ):
        """The venue keeps the two booked windows plus the admitted late one.

        PRD: "At each of those instants it counts how many occupying assets at that auditorium have a window containing that instant, both ends inclusive, and adds one for the candidate itself."

        Design: Difficulty/boundary_precision_check/ingest_lane_window_touching_at_endpoint_counts_as_concurrent
        """
        world = setup_programming_baseline(
            asset_overrides={
                "carrier_ref": "WB-80001",
                "ingest_window_start_at": "2026-08-02T08:00:00Z",
                "ingest_window_end_at": "2026-08-03T08:00:00Z",
            }
        )
        book_asset(
            world["title"]["id"],
            world["distributor"]["id"],
            world["venue"]["id"],
            carrier_ref="WB-80002",
            ingest_window_start_at="2026-08-02T12:00:00Z",
            ingest_window_end_at="2026-08-03T12:00:00Z",
        )

        validate_error(
            api_client.create_dcp_asset(
                _asset_payload(
                    world, "WB-80003", "2026-08-03T08:00:00Z", "2026-08-04T00:00:00Z"
                ),
                technical_manager_headers,
            ),
            ApiErrorId.ERR_INGEST_LANE_CAPACITY_EXCEEDED,
        )
        book_asset(
            world["title"]["id"],
            world["distributor"]["id"],
            world["venue"]["id"],
            carrier_ref="WB-80004",
            ingest_window_start_at="2026-08-03T08:01:00Z",
            ingest_window_end_at="2026-08-04T00:00:00Z",
        )

        refs, meta = _carrier_refs(technical_manager_headers, world["venue"]["id"])
        assert meta["total_count"] == 3
        assert "WB-80003" not in refs, "the refused booking left no asset behind"
        assert sorted(refs) == ["WB-80001", "WB-80002", "WB-80004"]


def _two_lane_world():
    """Two 24-hour ingest windows overlapping by eighteen hours on one server."""
    world = setup_programming_baseline(
        asset_overrides={
            "carrier_ref": "WB-90001",
            "ingest_window_start_at": "2026-08-05T00:00:00Z",
            "ingest_window_end_at": "2026-08-06T00:00:00Z",
        }
    )
    world["second_asset"] = book_asset(
        world["title"]["id"],
        world["distributor"]["id"],
        world["venue"]["id"],
        carrier_ref="WB-90002",
        ingest_window_start_at="2026-08-05T06:00:00Z",
        ingest_window_end_at="2026-08-06T06:00:00Z",
    )
    return world


class TestIngestLanesAdmitOverlapUpToLaneCount:
    """Overlap alone is not an error; the third simultaneous window is."""

    def test_two_overlapping_windows_fill_both_lanes_without_error(self):
        """Eighteen hours of overlap is exactly what a two-lane server is for.

        PRD: "Overlapping windows are perfectly normal — a two-lane server happily runs two at once, and it is only the third simultaneous window that fails."

        Design: Difficulty/resource_temporal_overlap/ingest_lanes_admit_overlap_up_to_lane_count_then_refuse
        """
        world = _two_lane_world()

        first = read_asset(world["asset"]["id"])
        second = read_asset(world["second_asset"]["id"])

        assert_dcp_asset(first)
        assert_dcp_asset(second)
        assert first["status"] == "REQUESTED"
        assert second["status"] == "REQUESTED"
        assert first["ingest_window_end_at"] == "2026-08-06T00:00:00.000Z"
        assert second["ingest_window_start_at"] == "2026-08-05T06:00:00.000Z"

    def test_third_concurrent_window_exceeds_the_lane_count(
        self, technical_manager_headers
    ):
        """At 2026-08-05T12:00:00Z all three windows would be live at once.

        PRD: "**Ingest windows are closed and aggregated.** A package's ingest window runs from `ingest_window_start_at` through `ingest_window_end_at` inclusive, and overlap alone is not an error: the venue has `dcp_ingest_lane_count` parallel lanes, and only the window that would make more than that many windows concurrent at some instant is refused."

        Design: Difficulty/resource_temporal_overlap/ingest_lanes_admit_overlap_up_to_lane_count_then_refuse
        """
        world = _two_lane_world()

        response = api_client.create_dcp_asset(
            _asset_payload(
                world, "WB-90003", "2026-08-05T12:00:00Z", "2026-08-06T12:00:00Z"
            ),
            technical_manager_headers,
        )

        validate_error(response, ApiErrorId.ERR_INGEST_LANE_CAPACITY_EXCEEDED)

    def test_refused_third_window_leaves_exactly_two_asset_rows(
        self, technical_manager_headers
    ):
        """Both booked packages still occupy a lane and nothing else exists.

        PRD: "Only four asset states occupy a lane — `REQUESTED`, `IN_TRANSIT`, `RECEIVED` and `INGESTING` — while `INGESTED` and `RETURNED` release it."

        Design: Difficulty/resource_temporal_overlap/ingest_lanes_admit_overlap_up_to_lane_count_then_refuse
        """
        world = _two_lane_world()

        validate_error(
            api_client.create_dcp_asset(
                _asset_payload(
                    world, "WB-90003", "2026-08-05T12:00:00Z", "2026-08-06T12:00:00Z"
                ),
                technical_manager_headers,
            ),
            ApiErrorId.ERR_INGEST_LANE_CAPACITY_EXCEEDED,
        )

        refs, meta = _carrier_refs(technical_manager_headers, world["venue"]["id"])
        assert meta["total_count"] == 2
        assert sorted(refs) == ["WB-90001", "WB-90002"]
        assert "WB-90003" not in refs
