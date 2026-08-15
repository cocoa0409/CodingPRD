"""Seasonal drop windows: half-open adjacency, open gating, default clock, OCC."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_active_program,
    create_drop,
    drop_transition,
    fresh_program_version,
    set_clock,
    TEST_USERS,
    validate_error,
    validate_success,
)

DIRECTOR = TEST_USERS["director_headers"]
MANAGER = TEST_USERS["store_manager_headers"]


class TestDropWindowOverlap:
    def test_adjacent_drop_windows_allowed(self, api):
        """PRD §3.3: "Windows of the same program may touch but never overlap:
        adjacency, where one drop closes at exactly the instant another opens,
        is allowed, while any true overlap is rejected with
        `ERR_DROP_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/drop_windows_half_open_adjacency
        """
        program = create_active_program()
        pv = program["version"]
        drop_a = create_drop(
            program["id"],
            pv,
            name="Fall",
            opens_at="2026-09-01T00:00:00Z",
            closes_at="2026-10-01T00:00:00Z",
        )
        assert drop_a["status"] == "SCHEDULED"

        drop_b = create_drop(
            program["id"],
            fresh_program_version(program["id"]),
            name="Winter",
            opens_at="2026-10-01T00:00:00Z",
            closes_at="2026-11-01T00:00:00Z",
        )
        assert drop_b["id"], (
            "B.opens_at == A.closes_at is adjacency, not overlap, under "
            "half-open [opens_at, closes_at) semantics"
        )

    def test_overlapping_drop_window_rejected(self, api):
        """PRD §3.3: "Windows of the same program may touch but never overlap:
        adjacency, where one drop closes at exactly the instant another opens,
        is allowed, while any true overlap is rejected with
        `ERR_DROP_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/drop_windows_half_open_adjacency
        """
        program = create_active_program()
        create_drop(
            program["id"],
            program["version"],
            name="Fall",
            opens_at="2026-09-01T00:00:00Z",
            closes_at="2026-10-01T00:00:00Z",
        )
        res = api.create_seasonal_drop(
            {
                "program_id": program["id"],
                "name": "Homecoming",
                "opens_at": "2026-09-15T00:00:00Z",
                "closes_at": "2026-10-15T00:00:00Z",
                "expected_program_version": fresh_program_version(program["id"]),
            },
            MANAGER,
        )
        validate_error(res, ApiErrorId.ERR_DROP_WINDOW_OVERLAP, 409)


class TestDropOpenWindow:
    def test_drop_open_before_opens_at_rejected(self, api):
        """PRD §3.3: "Opening a drop moves `SCHEDULED` to `OPEN` and requires
        the logical clock to have reached `opens_at`; an early attempt is
        `ERR_DROP_WINDOW_NOT_STARTED`."

        Design: Corner/state_machines/drop_open_before_opens_at_rejected
        """
        program = create_active_program()
        drop = create_drop(
            program["id"],
            program["version"],
            name="Fall",
            opens_at="2026-09-01T00:00:00Z",
            closes_at="2026-10-01T00:00:00Z",
        )
        res = api.seasonal_drop_transition(drop["id"], {"to_state": "OPEN"}, MANAGER)
        validate_error(res, ApiErrorId.ERR_DROP_WINDOW_NOT_STARTED, 409)

        set_clock("2026-09-01T00:00:00Z")
        opened = validate_success(
            api.seasonal_drop_transition(drop["id"], {"to_state": "OPEN"}, MANAGER),
            200,
        )
        assert opened["status"] == "OPEN", (
            "clock exactly at opens_at satisfies 'reached opens_at' "
            "(>= semantics)"
        )

    def test_clock_default_is_fixed_earliest(self, api):
        """PRD §2.5: "Before any such set call, the logical clock reads exactly
        `2026-08-01T00:00:00Z` and MUST NOT fall back to wall-clock time."
        PRD §3.3: "Opening a drop moves `SCHEDULED` to `OPEN` and requires the
        logical clock to have reached `opens_at`; an early attempt is
        `ERR_DROP_WINDOW_NOT_STARTED`."

        Design: Corner/endpoints/clock_default_is_fixed_earliest
        """
        program = create_active_program()
        drop = create_drop(
            program["id"],
            program["version"],
            name="Launch",
            opens_at="2026-08-01T00:00:00Z",
            closes_at="2026-09-01T00:00:00Z",
        )
        opened = validate_success(
            api.seasonal_drop_transition(drop["id"], {"to_state": "OPEN"}, MANAGER),
            200,
        )
        assert opened["status"] == "OPEN", (
            "no clock-set call was issued: the drop whose opens_at equals the "
            "documented default instant must open immediately"
        )


class TestDropCreateOcc:
    def test_occ_stale_program_version_on_drop_create(self, api):
        """PRD §2.7: "a mismatch between `expected_program_version` and the
        program's current `version` means the writer's view of program
        configuration is out of date, and the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.4: "creating a seasonal drop increments the owning program's
        `version` by 1"

        Design: Corner/cross_cutting_layers/occ_stale_program_version_on_drop_create
        """
        program = create_active_program()
        observed_version = program["version"]

        drop1 = create_drop(
            program["id"],
            observed_version,
            name="Fall",
            opens_at="2026-09-01T00:00:00Z",
            closes_at="2026-10-01T00:00:00Z",
        )
        assert drop1["id"]

        stale_res = api.create_seasonal_drop(
            {
                "program_id": program["id"],
                "name": "Winter",
                "opens_at": "2026-11-01T00:00:00Z",
                "closes_at": "2026-12-01T00:00:00Z",
                "expected_program_version": observed_version,
            },
            MANAGER,
        )
        validate_error(stale_res, ApiErrorId.ERR_STALE_VERSION, 412)

        program_after = validate_success(api.get_program(program["id"], MANAGER), 200)
        assert program_after["version"] == observed_version + 1, (
            f"only the successful create advances the program version: "
            f"expected {observed_version + 1}, got {program_after['version']}"
        )
