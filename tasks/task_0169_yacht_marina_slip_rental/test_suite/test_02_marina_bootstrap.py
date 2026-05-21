"""Marina creation, the logical clock, and the operations sweep —
PRD §2.7, §3.1.

Covers the marina-bootstrap rules: clock initialized to the 1970 epoch,
`ops_run_index` starts at 0, `liveaboard_active_count` starts at 0,
clock-advance moves the marina clock, and `_ops/run` increments
`ops_run_index`.
"""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    advance_clock_to_iso,
    api_client,
    assert_marina,
    create_marina,
    create_marina_payload,
    run_ops,
    validate_error,
    validate_success,
)


# ===========================================================================
# Marina creation defaults — PRD §3.1
# ===========================================================================
class TestMarinaCreate:

    def test_marina_initial_current_date_is_epoch(
        self, api, dock_master_headers,
    ):
        """PRD §3.1: "At creation the marina's `current_date` is
        initialized to `1970-01-01T00:00:00.000Z`, its `ops_run_index`
        is 0, and its `liveaboard_active_count` is 0."

        Claim: new marina has current_date = 1970-01-01T00:00:00.000Z."""
        marina = create_marina()
        assert marina["current_date"] == "1970-01-01T00:00:00.000Z", (
            f"Initial current_date must be 1970-01-01T00:00:00.000Z; "
            f"got {marina['current_date']!r}"
        )

    def test_marina_initial_ops_run_index_zero(
        self, api, dock_master_headers,
    ):
        """PRD §3.1: "its `ops_run_index` is 0"."""
        marina = create_marina()
        assert marina["ops_run_index"] == 0, (
            f"Initial ops_run_index must be 0; "
            f"got {marina['ops_run_index']!r}"
        )

    def test_marina_initial_liveaboard_active_count_zero(
        self, api, dock_master_headers,
    ):
        """PRD §3.1: "its `liveaboard_active_count` is 0.\""""
        marina = create_marina()
        assert marina["liveaboard_active_count"] == 0, (
            f"Initial liveaboard_active_count must be 0; "
            f"got {marina['liveaboard_active_count']!r}"
        )

    def test_marina_default_timezone_is_new_york(
        self, api, dock_master_headers,
    ):
        """PRD §3.1: "a `timezone` (defaulting to `America/New_York` if
        omitted...)"

        Claim: omitting `timezone` in the create body yields
        timezone == America/New_York."""
        # Omit timezone explicitly.
        payload = create_marina_payload()
        payload.pop("timezone", None)
        resp = api.create_marina(payload, dock_master_headers)
        marina = validate_success(resp, expected_status=201)
        assert marina.get("timezone") == "America/New_York", (
            f"Default timezone must be America/New_York, got "
            f"{marina.get('timezone')!r}"
        )

    def test_marina_shape(self, api, dock_master_headers):
        """PRD §2.4: common-fields resource id + created_at +
        updated_at + version; PRD §3.1 marina field set."""
        marina = create_marina()
        assert_marina(marina)


# ===========================================================================
# Clock advance — PRD §2.7
# ===========================================================================
class TestClockAdvance:

    def test_clock_advance_updates_current_date(
        self, api, dock_master_headers,
    ):
        """PRD §2.7: "A test-driving capability accepts a target
        instant via the `to` request field and assigns it to the
        marina's `current_date`."

        Claim: POST /_clock/advance writes to marina.current_date."""
        marina = create_marina()
        target = "2024-06-15T12:00:00.000Z"
        updated = advance_clock_to_iso(marina["id"], target)
        assert updated["current_date"] == target, (
            f"After clock advance, current_date must be {target!r}; "
            f"got {updated['current_date']!r}"
        )


# ===========================================================================
# Ops sweep — PRD §2.7
# ===========================================================================
class TestOpsRun:

    def test_ops_run_increments_ops_run_index(
        self, api, dock_master_headers,
    ):
        """PRD §2.7: "A periodic operations sweep ... increments
        `ops_run_index` by one and then performs four cascading
        housekeeping actions..."

        Claim: each _ops/run bumps ops_run_index by 1."""
        marina = create_marina()
        assert marina["ops_run_index"] == 0
        after_first = run_ops(marina["id"])
        assert after_first["ops_run_index"] == 1, (
            f"After one ops/run, ops_run_index must be 1; "
            f"got {after_first['ops_run_index']!r}"
        )
        after_second = run_ops(marina["id"])
        assert after_second["ops_run_index"] == 2, (
            f"After two ops/runs, ops_run_index must be 2; "
            f"got {after_second['ops_run_index']!r}"
        )


# ===========================================================================
# Path resolution — PRD §2.5
# ===========================================================================
class TestPathResolution:

    def test_get_unknown_marina_returns_not_found(
        self, api, dock_master_headers,
    ):
        """PRD §2.5: "Path identifiers are validated strictly left to
        right ... the rejection is `ERR_NOT_FOUND` (HTTP 404) for the
        reservation."

        Claim: GET /marinas/{unknown} → ERR_NOT_FOUND."""
        resp = api.get_marina(NON_EXISTENT_UUID, dock_master_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
