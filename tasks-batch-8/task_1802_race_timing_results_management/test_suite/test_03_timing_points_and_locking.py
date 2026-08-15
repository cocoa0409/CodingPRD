"""Timing-point layout rules: device deployment windows, the lock's
completeness audit, the configuration freeze, and wave-start gating."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    build_race,
    create_race_payload,
    create_timing_point_payload,
    create_wave_payload,
    is_iso8601_timestamp,
    make_race_director_headers,
    validate_error,
    validate_success,
)

RD = TEST_USERS["race_director_headers"]
OP = TEST_USERS["timing_operator_headers"]


class TestDeviceWindowOverlap:
    def _race_with_first_point(self, api):
        ctx = build_race(
            name="Device 5K", distance_km=5.0,
            course_type="UNCERTIFIED_COURSE", cutoff_minutes=90,
            points=[{"key": "p1", "point_index": 1, "kind": "START",
                     "distance_km": 0.0, "device_id": "MAT-9",
                     "deploy_at": "2026-08-01T05:00:00Z",
                     "expected_teardown_at": "2026-08-01T08:00:00Z",
                     "deploy": False}],
            waves=(), chips=(), registrations=(), lock=False)
        return ctx

    def test_adjacent_teardown_equals_deploy_windows_accepted(self, api):
        """PRD §3.1: "The deployment windows of any single `device_id` must
        never overlap across timing points: the windows are half-open, so one
        window's teardown at exactly the instant another begins is permitted,
        and any true overlap is rejected with `ERR_DEVICE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/device_window_half_open_adjacency
        """
        ctx = self._race_with_first_point(api)
        # [08:00, 12:00) begins exactly when [05:00, 08:00) ends: no overlap.
        point2 = validate_success(api.create_timing_point(
            create_timing_point_payload(
                ctx["race"]["id"], 2, "FINISH", 5.0, "MAT-9",
                deploy_at="2026-08-01T08:00:00Z",
                expected_teardown_at="2026-08-01T12:00:00Z"),
            OP), 201)
        assert point2["status"] == "PLANNED"
        assert point2["device_id"] == "MAT-9"

    def test_overlapping_window_by_one_second_rejected(self, api):
        """PRD §3.1: "The deployment windows of any single `device_id` must
        never overlap across timing points: the windows are half-open, so one
        window's teardown at exactly the instant another begins is permitted,
        and any true overlap is rejected with `ERR_DEVICE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/device_window_half_open_adjacency
        """
        ctx = self._race_with_first_point(api)
        validate_success(api.create_timing_point(
            create_timing_point_payload(
                ctx["race"]["id"], 2, "FINISH", 5.0, "MAT-9",
                deploy_at="2026-08-01T08:00:00Z",
                expected_teardown_at="2026-08-01T12:00:00Z"),
            OP), 201)
        # [07:59:59, 12:00) starts one second before [05:00, 08:00) ends.
        resp = api.create_timing_point(
            create_timing_point_payload(
                ctx["race"]["id"], 3, "SPLIT", 2.5, "MAT-9",
                deploy_at="2026-08-01T07:59:59Z",
                expected_teardown_at="2026-08-01T12:00:00Z"),
            OP)
        validate_error(resp, ApiErrorId.ERR_DEVICE_WINDOW_OVERLAP,
                       expected_status=409)


class TestLockTimingGatedByPointConfig:
    def _race_with_planned_finish(self, api):
        return build_race(
            name="Lock Gate 5K", distance_km=5.0,
            course_type="UNCERTIFIED_COURSE", cutoff_minutes=90,
            points=[
                {"key": "start", "point_index": 1, "kind": "START",
                 "distance_km": 0.0},
                {"key": "finish", "point_index": 2, "kind": "FINISH",
                 "distance_km": 5.0, "deploy": False},
            ],
            waves=[{"key": "w1", "wave_index": 1,
                    "scheduled_start_time": "2026-08-01T07:00:00Z",
                    "max_capacity": 10}],
            chips=(), registrations=(), lock=False)

    def test_lock_with_planned_finish_rejected(self, api):
        """PRD §3.4: "Locking is a completeness audit, and any shortfall rejects
        with `ERR_TIMING_CONFIG_INCOMPLETE`: the race must have at least one
        wave; exactly one `DEPLOYED` timing point of kind `START`; exactly one
        `DEPLOYED` timing point of kind `FINISH` whose `distance_km` equals the
        race's `distance_km`; and no timing point remaining in `PLANNED`."

        Design: Difficulty/cross_entity_state_dependency/lock_timing_gated_by_point_config
        """
        ctx = self._race_with_planned_finish(api)
        resp = api.lock_timing(ctx["race"]["id"], make_race_director_headers("director-1"))
        validate_error(resp, ApiErrorId.ERR_TIMING_CONFIG_INCOMPLETE,
                       expected_status=409)
        race = validate_success(api.get_race(ctx["race"]["id"], RD), 200)
        assert race["status"] == "REGISTRATION_OPEN"

    def test_lock_after_deploy_captures_fingerprint_and_locker(self, api):
        """PRD §3.4: "A successful lock stamps `timing_locked_at` with the
        logical now and records the acting operator in `locked_by_user_id`"
        PRD §3.4: "It also captures the `timing_config_fingerprint`: for every
        deployed point, ordered by `point_index` ascending, a segment joining
        the point's index, kind, and distance in kilometers with colons, with
        the segments themselves joined by commas."

        Design: Difficulty/cross_entity_state_dependency/lock_timing_gated_by_point_config
        """
        ctx = self._race_with_planned_finish(api)
        validate_success(
            api.deploy_timing_point(ctx["points"]["finish"]["id"], OP), 200)
        locked = validate_success(api.lock_timing(
            ctx["race"]["id"], make_race_director_headers("director-1")), 200)
        assert locked["status"] == "TIMING_LOCKED"
        assert is_iso8601_timestamp(locked["timing_locked_at"])
        assert locked["locked_by_user_id"] == "director-1"
        # PRD pins the fingerprint's structure — one segment per deployed
        # point, ordered by point_index ascending, each segment joining the
        # point's index, kind, and distance in kilometers with colons, the
        # segments joined by commas — but not the distance's decimal
        # rendering, so the segments are checked structurally, not as an
        # exact string.
        fingerprint = locked["timing_config_fingerprint"]
        assert fingerprint is not None, "a successful lock captures the fingerprint"
        segments = fingerprint.split(",")
        assert len(segments) == 2, "one comma-joined segment per deployed point"
        idx0, kind0, dist0 = segments[0].split(":")
        idx1, kind1, dist1 = segments[1].split(":")
        assert (idx0, kind0, float(dist0)) == ("1", "START", 0.0)
        assert (idx1, kind1, float(dist1)) == ("2", "FINISH", 5.0)


class TestRaceAndWaveStateGates:
    def test_lock_timing_from_draft_rejected(self, api):
        """PRD §3.4: "Before the first start gun, the `RaceDirector` locks the
        timing configuration, moving the race `REGISTRATION_OPEN →
        TIMING_LOCKED`." A race still in `DRAFT` has no such transition.

        Design: Corner/state_machines/lock_timing_from_draft_rejected
        """
        race = validate_success(api.create_race(
            create_race_payload(name="Skip 5K", distance_km=5.0,
                                course_type="UNCERTIFIED_COURSE",
                                course_time_limit_minutes=90),
            RD), 201)
        resp = api.lock_timing(race["id"], RD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        after = validate_success(api.get_race(race["id"], RD), 200)
        assert after["status"] == "DRAFT"

    def test_wave_start_before_lock_rejected(self, api):
        """PRD §3.4: "A `TimingOperator` starts each wave when it actually goes
        off, moving the wave addressed by `wave_id` from `SCHEDULED` to
        `STARTED`; the wave's race must already be in `TIMING_LOCKED` or
        `IN_PROGRESS`."

        Design: Corner/state_machines/wave_start_before_lock_rejected
        """
        ctx = build_race(
            name="Early Wave 5K", distance_km=5.0,
            course_type="UNCERTIFIED_COURSE", cutoff_minutes=90, points=(),
            waves=[{"key": "w1", "wave_index": 1,
                    "scheduled_start_time": "2026-08-01T07:00:00Z",
                    "max_capacity": 10}],
            chips=(), registrations=(), lock=False)
        wave_id = ctx["waves"]["w1"]["id"]
        resp = api.start_wave(wave_id, OP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        wave = validate_success(
            api.list_race_waves(ctx["race"]["id"], RD), 200)
        assert wave[0]["status"] == "SCHEDULED"
        assert wave[0]["actual_start_time"] is None
        race = validate_success(api.get_race(ctx["race"]["id"], RD), 200)
        assert race["status"] == "REGISTRATION_OPEN"


class TestTimingConfigFreeze:
    def test_timing_point_mutation_after_lock_rejected(self, api):
        """PRD §3.1: "Deploying the point addressed by `point_id` moves it
        `PLANNED → DEPLOYED`, and a point may also be deleted outright — but
        creation, deployment, and deletion are all permitted only while the race
        sits in `DRAFT` or `REGISTRATION_OPEN`; the same freeze rejects all three
        with `ERR_TIMING_CONFIG_LOCKED` afterwards."
        PRD §4: "Removing a timing point returns `204 No Content` with no
        response body."

        Design: Corner/endpoints/timing_point_mutation_after_lock_rejected
        """
        race = validate_success(api.create_race(
            create_race_payload(name="Freeze 5K", distance_km=5.0,
                                course_type="UNCERTIFIED_COURSE",
                                course_time_limit_minutes=90),
            RD), 201)
        race = validate_success(api.open_registration(race["id"], RD), 200)
        tp_start = validate_success(api.create_timing_point(
            create_timing_point_payload(race["id"], 1, "START", 0.0, "MAT-FZ1"),
            OP), 201)
        # PRD §3.1: point_index must strictly increase with distance_km, so the
        # 2.5 km SPLIT sits between the START (index 1) and the FINISH (index 3).
        tp_split = validate_success(api.create_timing_point(
            create_timing_point_payload(race["id"], 2, "SPLIT", 2.5, "MAT-FZ3"),
            OP), 201)
        tp_fin = validate_success(api.create_timing_point(
            create_timing_point_payload(race["id"], 3, "FINISH", 5.0, "MAT-FZ2"),
            OP), 201)
        validate_success(api.deploy_timing_point(tp_start["id"], OP), 200)
        validate_success(api.deploy_timing_point(tp_fin["id"], OP), 200)

        # Pre-lock delete of the PLANNED point succeeds with 204.
        delete_resp = api.delete_timing_point(tp_split["id"], OP)
        assert delete_resp.status_code == 204, (
            f"pre-lock DELETE of a PLANNED point returns 204, got {delete_resp.status_code}"
        )

        validate_success(api.create_wave(
            create_wave_payload(race["id"], 1, "2026-08-01T07:00:00Z", 10), RD), 201)
        validate_success(api.lock_timing(
            race["id"], make_race_director_headers("director-1")), 200)

        # The post-lock create uses the index freed by the pre-lock delete, so
        # the layout would be legal — only the configuration freeze can reject.
        resp1 = api.create_timing_point(
            create_timing_point_payload(race["id"], 2, "SPLIT", 2.5, "MAT-FZ4"),
            OP)
        validate_error(resp1, ApiErrorId.ERR_TIMING_CONFIG_LOCKED, expected_status=409)
        resp2 = api.delete_timing_point(tp_start["id"], OP)
        validate_error(resp2, ApiErrorId.ERR_TIMING_CONFIG_LOCKED, expected_status=409)
