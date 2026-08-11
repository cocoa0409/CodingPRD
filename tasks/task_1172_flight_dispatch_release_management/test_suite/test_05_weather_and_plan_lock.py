"""Plan locking weather gates, weather window overlap, weather replace OCC,
and the weather revalidation cascade (PRD §2.6, §3.3, §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_station_payload,
    create_weather_package_payload,
    setup_computed_plan,
    setup_release_released,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

SUP = TEST_USERS["supervisor_headers"]


class TestWeatherWindowOverlap:
    def test_weather_window_half_open_adjacency_accepted(self, api):
        """PRD §3.7: "Among one station's `ACTIVE` packages, windows must never
        intersect, though adjacency is allowed: a new window beginning exactly
        where another ends is legal, while any true overlap is rejected with
        `ERR_WEATHER_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/weather_window_half_open_adjacency
        """
        stw = validate_success(
            api.create_station(
                create_station_payload(iata_code="KWTH", alternate_distance_nm=50), SUP
            ),
            201,
        )
        validate_success(
            api.create_weather_package(create_weather_package_payload(stw["id"]), SUP),
            201,
        )
        adjacent = api.create_weather_package(
            create_weather_package_payload(
                stw["id"],
                valid_from_utc="2026-05-01T13:00:00Z",
                valid_to_utc="2026-05-01T17:00:00Z",
                ceiling_ft=900, visibility_m=4000,
            ),
            SUP,
        )
        created = validate_success(adjacent, 201)
        assert created["status"] == "ACTIVE"

    def test_weather_window_straddling_boundary_rejected(self, api):
        """PRD §3.7: "Among one station's `ACTIVE` packages, windows must never
        intersect, though adjacency is allowed: a new window beginning exactly
        where another ends is legal, while any true overlap is rejected with
        `ERR_WEATHER_WINDOW_OVERLAP`." [12:30,14:00) truly intersects both
        [09:00,13:00) and [13:00,17:00).

        Design: Difficulty/resource_temporal_overlap/weather_window_half_open_adjacency
        """
        stw = validate_success(
            api.create_station(
                create_station_payload(iata_code="KWTH", alternate_distance_nm=50), SUP
            ),
            201,
        )
        validate_success(
            api.create_weather_package(create_weather_package_payload(stw["id"]), SUP),
            201,
        )
        validate_success(
            api.create_weather_package(
                create_weather_package_payload(
                    stw["id"],
                    valid_from_utc="2026-05-01T13:00:00Z",
                    valid_to_utc="2026-05-01T17:00:00Z",
                    ceiling_ft=900, visibility_m=4000,
                ),
                SUP,
            ),
            201,
        )
        res = api.create_weather_package(
            create_weather_package_payload(
                stw["id"],
                valid_from_utc="2026-05-01T12:30:00Z",
                valid_to_utc="2026-05-01T14:00:00Z",
                ceiling_ft=900, visibility_m=4000,
            ),
            SUP,
        )
        validate_error(res, ApiErrorId.ERR_WEATHER_WINDOW_OVERLAP.value)


class TestPlanLockWeatherGates:
    def test_lock_without_covering_weather_rejected(self, api):
        """PRD §3.3: "Locking re-verifies the destination environment: an
        `ACTIVE` weather package for the arrival station must cover the current
        `sched_arr_utc` (`ERR_WEATHER_NOT_CURRENT` when none does)"

        Design: Corner/validations/lock_without_covering_weather_rejected
        """
        # No weather package is published for the arrival station; plan create
        # itself succeeds (weather is a lock-time gate).
        ctx = setup_computed_plan()
        assert ctx["plan"]["status"] == "COMPUTED"
        res = api.lock_plan(ctx["plan"]["id"], ctx["d_headers"])
        validate_error(res, ApiErrorId.ERR_WEATHER_NOT_CURRENT.value)

    def test_below_minima_weather_blocks_lock(self, api):
        """PRD §3.3: "that package's ceiling and visibility must meet the
        arrival station's minima, raised by the MEL bump described in §3.6 when
        any `OPEN` defect with `minima_bump` exists on the aircraft
        (`ERR_WEATHER_BELOW_MINIMA` otherwise)" — ceiling 100 < min_ceiling 200.

        Design: Corner/validations/below_minima_weather_blocks_lock
        """
        ctx = setup_computed_plan()
        set_clock(ctx, "2026-05-01T08:00:00Z")
        validate_success(
            api.create_weather_package(
                create_weather_package_payload(ctx["arr_station"]["id"],
                                               ceiling_ft=100, visibility_m=5000),
                SUP,
            ),
            201,
        )
        res = api.lock_plan(ctx["plan"]["id"], ctx["d_headers"])
        validate_error(res, ApiErrorId.ERR_WEATHER_BELOW_MINIMA.value)


class TestWeatherReplaceOcc:
    def test_occ_weather_replace_stale_station_version(self, api):
        """PRD §2.6: "Replacing a weather package requires the request to carry
        `expected_station_version`, a non-optional field holding the client's
        last-observed `version` of the Station the target package belongs to. A
        mismatch with the station's current `version` is rejected with
        `ERR_STALE_VERSION` (HTTP 412), so a forecaster whose view of the
        station predates another publish or replace must re-read before
        superseding."

        Design: Corner/complexity_layers/occ_weather_replace_stale_station_version
        """
        stw = validate_success(
            api.create_station(
                create_station_payload(iata_code="KWTH", alternate_distance_nm=50), SUP
            ),
            201,
        )
        wx1 = validate_success(
            api.create_weather_package(create_weather_package_payload(stw["id"]), SUP),
            201,
        )
        station = validate_success(api.get_station(stw["id"], SUP), 200)
        observed_version = station["version"]

        replaced = api.replace_weather_package(
            wx1["id"],
            {
                "valid_from_utc": "2026-05-01T09:00:00Z",
                "valid_to_utc": "2026-05-01T13:00:00Z",
                "ceiling_ft": 900,
                "visibility_m": 4500,
                "expected_station_version": observed_version,
            },
            SUP,
        )
        wx2 = validate_success(replaced, 201)
        assert wx2["status"] == "ACTIVE"

        # Replaying the same observed version after the successful replace is stale.
        stale = api.replace_weather_package(
            wx2["id"],
            {
                "valid_from_utc": "2026-05-01T09:00:00Z",
                "valid_to_utc": "2026-05-01T13:00:00Z",
                "ceiling_ft": 800,
                "visibility_m": 4000,
                "expected_station_version": observed_version,
            },
            SUP,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value,
                       expected_status=412)


class TestWeatherRevalidationCascade:
    def _setup_and_replace(self, api):
        ctx = setup_release_released()
        station = validate_success(
            api.get_station(ctx["arr_station"]["id"], SUP), 200
        )
        replace_res = api.replace_weather_package(
            ctx["weather"]["id"],
            {
                "valid_from_utc": "2026-05-01T09:00:00Z",
                "valid_to_utc": "2026-05-01T13:00:00Z",
                "ceiling_ft": 100,
                "visibility_m": 400,
                "expected_station_version": station["version"],
            },
            SUP,
        )
        ctx["weather_new"] = validate_success(replace_res, 201)
        return ctx

    def test_weather_replace_cascade_drops_plan_and_amends_release(self, api):
        """PRD §3.7: "When the check fails, the cascade runs three hops deep:
        the plan drops from `LOCKED` back to `COMPUTED`; any release referencing
        that plan moves from `RELEASED` to `UNDER_AMENDMENT` or from
        `PENDING_SIGNATURES` to `DRAFT`, with `cycle_seq` incremented by one in
        either case and `amendment_count` incremented by one when the release
        came from `RELEASED`; and the cycle increment invalidates the release's
        collected signatures."

        Design: Difficulty/transitive_cascade/weather_replace_cascade_to_release_amendment
        """
        ctx = self._setup_and_replace(api)
        assert ctx["weather_new"]["status"] == "ACTIVE"

        old = validate_success(
            api.get_weather_package(ctx["weather"]["id"], SUP), 200
        )
        assert old["status"] == "SUPERSEDED"

        plan = validate_success(api.get_plan(ctx["plan"]["id"], ctx["d_headers"]), 200)
        assert plan["status"] == "COMPUTED"

        release = validate_success(
            api.get_release(ctx["release"]["id"], ctx["d_headers"]), 200
        )
        assert release["status"] == "UNDER_AMENDMENT"
        assert release["cycle_seq"] == ctx["release"]["cycle_seq"] + 1
        assert release["amendment_count"] == 1

    def test_weather_replace_cascade_writes_auto_amended_record(self, api):
        """PRD §3.7: "Each cascaded release writes a `RELEASE_AUTO_AMENDED`
        record." The cycle increment also leaves the previously collected
        signatures stale per PRD §3.5: "A signature is valid only while its
        recorded `cycle_seq` equals the release's current `cycle_seq`; the
        moment the cycle advances, every earlier signature goes stale."

        Design: Difficulty/transitive_cascade/weather_replace_cascade_to_release_amendment
        """
        ctx = self._setup_and_replace(api)
        records, _ = validate_paginated(
            api.list_control_records(ctx["leg"]["id"], ctx["d_headers"])
        )
        actions = [r["action"] for r in records]
        assert "RELEASE_AUTO_AMENDED" in actions

        release = validate_success(
            api.get_release(ctx["release"]["id"], ctx["d_headers"]), 200
        )
        sigs, sig_meta = validate_paginated(
            api.list_release_signatures(release["id"], ctx["d_headers"])
        )
        assert sig_meta["total_count"] == 2
        for sig in sigs:
            assert sig["cycle_seq"] == 1
            assert sig["cycle_seq"] != release["cycle_seq"]
