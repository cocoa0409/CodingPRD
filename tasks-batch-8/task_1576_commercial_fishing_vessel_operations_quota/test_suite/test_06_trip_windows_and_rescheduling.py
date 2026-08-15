"""Temporal window rules: half-open vessel trip windows, closed-interval
opening windows, OCC-guarded rescheduling, and clock-driven opening closure
(PRD §3.2, §3.3, §2.5, §2.6)."""
from test_helpers import (
    TEST_USERS,
    advance_clock,
    api_client,
    create_fishing_trip_payload,
    create_opening,
    create_season_opening_payload,
    get_opening,
    get_trip,
    make_vessel_owner_headers,
    plan_trip,
    setup_vessel_ready,
    validate_error,
    validate_success,
)

REG = TEST_USERS["regulator_headers"]


class TestVesselTripWindows:
    def test_back_to_back_trips_allowed(self):
        """PRD §3.3: "Trip windows use half-open semantics, so back-to-back trips —
        one returning exactly when the next departs — are allowed; anything tighter
        is rejected with `ERR_TRIP_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/vessel_trip_windows_half_open
        """
        ctx = setup_vessel_ready()
        opening = create_opening()
        vessel_id = ctx["vessel"]["id"]
        trip_a = plan_trip(vessel_id, opening["id"],
                           departure="2026-08-10T06:00:00Z",
                           return_="2026-08-12T06:00:00Z")
        trip_b = plan_trip(vessel_id, opening["id"],
                           departure="2026-08-12T06:00:00Z",
                           return_="2026-08-14T06:00:00Z")
        assert trip_a["status"] == "PLANNED"
        assert trip_b["status"] == "PLANNED", (
            "a departure exactly at the previous trip's return must be allowed")

    def test_overlapping_trip_window_rejected(self):
        """PRD §3.3: "Trip windows use half-open semantics, so back-to-back trips
        — one returning exactly when the next departs — are allowed; anything
        tighter is rejected with `ERR_TRIP_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/vessel_trip_windows_half_open
        """
        ctx = setup_vessel_ready()
        opening = create_opening()
        vessel_id = ctx["vessel"]["id"]
        plan_trip(vessel_id, opening["id"],
                  departure="2026-08-10T06:00:00Z", return_="2026-08-12T06:00:00Z")
        plan_trip(vessel_id, opening["id"],
                  departure="2026-08-12T06:00:00Z", return_="2026-08-14T06:00:00Z")
        resp = api_client.create_fishing_trip(
            create_fishing_trip_payload(
                vessel_id=vessel_id, season_opening_id=opening["id"],
                planned_departure_utc="2026-08-11T06:00:00Z",
                planned_return_utc="2026-08-13T06:00:00Z"),
            make_vessel_owner_headers(vessel_id))
        validate_error(resp, "ERR_TRIP_WINDOW_OVERLAP", 409)


class TestOpeningWindows:
    def test_touching_opening_windows_conflict(self):
        """PRD §3.2: "Openings for the same fishery and area must not overlap: the
        windows are treated as closed intervals, so two openings whose windows
        merely touch still conflict and the second is rejected with
        `ERR_OPENING_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/opening_windows_closed_interval_touch
        """
        create_opening(opens_at="2026-08-05T00:00:00Z", closes_at="2026-08-25T00:00:00Z")
        touching = api_client.create_season_opening(
            create_season_opening_payload(
                opens_at="2026-08-25T00:00:00Z", closes_at="2026-09-05T00:00:00Z",
                tac_pounds=50000),
            REG)
        validate_error(touching, "ERR_OPENING_WINDOW_OVERLAP", 409)
        gapped = api_client.create_season_opening(
            create_season_opening_payload(
                opens_at="2026-08-26T00:00:00Z", closes_at="2026-09-05T00:00:00Z",
                tac_pounds=50000),
            REG)
        created = validate_success(gapped, 201)
        assert created["status"] == "SCHEDULED"

    def test_overlap_scoped_to_fishery_and_area(self):
        """PRD §3.2: "Openings for the same fishery and area must not overlap" —
        a different fishery in the same area, or the same fishery in a different
        area, does not share the overlap scope.

        Design: Difficulty/resource_temporal_overlap/opening_windows_closed_interval_touch
        """
        create_opening(fishery_code="HALIBUT", area_code="3A",
                       opens_at="2026-08-05T00:00:00Z", closes_at="2026-08-25T00:00:00Z")
        other_fishery = api_client.create_season_opening(
            create_season_opening_payload(
                fishery_code="SABLEFISH", area_code="3A",
                opens_at="2026-08-10T00:00:00Z", closes_at="2026-08-20T00:00:00Z",
                tac_pounds=50000),
            REG)
        assert validate_success(other_fishery, 201)["status"] == "SCHEDULED"
        other_area = api_client.create_season_opening(
            create_season_opening_payload(
                fishery_code="HALIBUT", area_code="4A",
                opens_at="2026-08-10T00:00:00Z", closes_at="2026-08-20T00:00:00Z",
                tac_pounds=50000),
            REG)
        assert validate_success(other_area, 201)["status"] == "SCHEDULED"


class TestTripRescheduleOcc:
    def test_occ_trip_patch_stale_version(self):
        """PRD §2.6: "Rescheduling a trip requires `expected_trip_version`, matching
        the trip's current `version`; a client whose planned window no longer
        reflects the trip's current state is refused." and "a value that does not
        match the parent entity's current `version` is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_trip_patch_stale_version
        """
        ctx = setup_vessel_ready()
        opening = create_opening()
        vessel_id = ctx["vessel"]["id"]
        trip = plan_trip(vessel_id, opening["id"])
        original_version = trip["version"]
        owner = make_vessel_owner_headers(vessel_id)
        patched = validate_success(api_client.patch_fishing_trip(
            trip["id"],
            {"planned_departure_utc": "2026-08-11T06:00:00Z",
             "planned_return_utc": "2026-08-13T06:00:00Z",
             "expected_trip_version": original_version},
            owner), 200)
        assert patched["version"] == original_version + 1
        resp = api_client.patch_fishing_trip(
            trip["id"],
            {"planned_departure_utc": "2026-08-12T06:00:00Z",
             "planned_return_utc": "2026-08-14T06:00:00Z",
             "expected_trip_version": original_version},
            owner)
        validate_error(resp, "ERR_STALE_VERSION", 412)
        current = get_trip(trip["id"])
        assert current["planned_departure_utc"].startswith("2026-08-11T06:00")
        assert current["planned_return_utc"].startswith("2026-08-13T06:00")


class TestOpeningClockLifecycle:
    def test_opening_auto_open_and_clock_close_cascade(self):
        """PRD §2.5: "A season opening in `SCHEDULED` moves to `OPEN` once the clock
        reaches its `opens_at` (the opening instant is inclusive)." and "An opening
        in `OPEN` moves to `CLOSED` once the clock passes its `closes_at`, and every
        trip still `PLANNED` on that opening is cancelled, with each cancelled
        trip's non-terminal observer assignments cancelled in turn."

        Design: Corner/state_machines/opening_auto_open_and_clock_close_cascade
        """
        ctx = setup_vessel_ready()
        opening = create_opening(opens_at="2026-08-05T00:00:00Z",
                                 closes_at="2026-08-25T00:00:00Z")
        assert get_opening(opening["id"])["status"] == "SCHEDULED"
        advance_clock("2026-08-10T06:00:00Z")
        assert get_opening(opening["id"])["status"] == "OPEN"
        trip = plan_trip(ctx["vessel"]["id"], opening["id"],
                         departure="2026-08-20T06:00:00Z",
                         return_="2026-08-22T06:00:00Z")
        advance_clock("2026-08-26T00:00:00Z")
        assert get_opening(opening["id"])["status"] == "CLOSED"
        assert get_trip(trip["id"])["status"] == "CANCELLED", (
            "the still-PLANNED trip must be cascade-cancelled when its opening closes")
