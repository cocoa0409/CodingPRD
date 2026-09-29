"""Two occupancy rules over the same instant, with different boundary semantics.

A property's irrigation schedule is plain half-open non-overlap, so a window may
begin exactly where its neighbour ends.  A device's monitor-mode occupancy is
extended by a 60-minute cooldown whose right edge is available, so a snooze is
refused one minute early and accepted exactly on it.
"""

from test_helpers import (
    ApiClient,
    ApiErrorId,
    assert_irrigation_window,
    validate_error,
)
from test_helpers.factories import irrigation_window_payload, monitor_mode_payload
from test_helpers.fixtures import (
    create_irrigation_window,
    read_device,
    read_irrigation_windows,
    run_ops_sweep,
    set_clock,
    set_monitor_mode,
    setup_armed_device,
    setup_irrigation_window,
)
from test_helpers.test_users import make_homeowner_headers

FIRST_WINDOW = ("2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z")
ADJACENT_WINDOW = ("2026-08-01T11:00:00Z", "2026-08-01T12:00:00Z")
OVERLAPPING_WINDOW = ("2026-08-01T10:59:00Z", "2026-08-01T12:00:00Z")


class TestIrrigationWindowHalfOpenOverlap:
    def test_a_window_starting_exactly_at_an_existing_end_at_is_accepted(
        self, api: ApiClient
    ):
        """The shared 11:00Z instant belongs to the later window alone.

        "Because the spans are half-open, a window beginning at exactly the instant
        an existing window ends is admitted while one beginning a minute earlier is
        not."
        "New windows are created `ACTIVE` with `suspended_at` null and reference the
        owning `property_id`; a window may later be `SUSPENDED_BY_SHUTOFF` while the
        valve is closed, or `CANCELLED` when the owning account closes."

        Design: Difficulty/resource_temporal_overlap/irrigation_window_half_open_overlap_on_property
        """
        state = setup_irrigation_window(api, *FIRST_WINDOW)
        second = create_irrigation_window(
            api,
            state["property_id"],
            state["homeowner_id"],
            *ADJACENT_WINDOW,
            label="back lawn",
        )
        assert_irrigation_window(second)
        assert second["status"] == "ACTIVE"
        assert second["start_at"].startswith("2026-08-01T11:00:00")
        assert second["suspended_at"] is None

        windows = read_irrigation_windows(
            api, state["property_id"], state["homeowner_headers"]
        )
        assert len(windows) == 2
        first = [w for w in windows if w["id"] == state["irrigation_window_id"]][0]
        assert first["end_at"].startswith("2026-08-01T11:00:00")

    def test_one_minute_of_overlap_is_refused_and_leaves_no_row(
        self, api: ApiClient
    ):
        """A 10:59Z start crosses into the existing window and is rejected.

        "The property must have `irrigation_present` true or the declaration is
        refused with `ERR_IRRIGATION_NOT_ENABLED`, and the submitted half-open span
        must not overlap any window on the property whose `status` is `ACTIVE`, or
        the declaration is refused with `ERR_IRRIGATION_WINDOW_OVERLAP`."
        "Because the spans are half-open, a window beginning at exactly the instant
        an existing window ends is admitted while one beginning a minute earlier is
        not."

        Design: Difficulty/resource_temporal_overlap/irrigation_window_half_open_overlap_on_property
        """
        state = setup_irrigation_window(api, *FIRST_WINDOW)
        create_irrigation_window(
            api,
            state["property_id"],
            state["homeowner_id"],
            *ADJACENT_WINDOW,
            label="back lawn",
        )

        response = api.create_irrigation_window(
            state["property_id"],
            irrigation_window_payload(*OVERLAPPING_WINDOW, label="side strip"),
            make_homeowner_headers(state["homeowner_id"]),
        )
        validate_error(response, ApiErrorId.ERR_IRRIGATION_WINDOW_OVERLAP, 409)

        active = read_irrigation_windows(
            api,
            state["property_id"],
            state["homeowner_headers"],
            {"status": "ACTIVE"},
        )
        assert len(active) == 2
        assert all(
            not w["start_at"].startswith("2026-08-01T10:59:00") for w in active
        )


SNOOZE_AT = "2026-08-01T07:00:00Z"
ONE_MINUTE_INSIDE_BUFFER = "2026-08-01T08:29:00Z"
AT_BUFFER_BOUNDARY = "2026-08-01T08:30:00Z"


def _lapsed_snooze_reverted_by_the_ops_sweep(api: ApiClient) -> dict:
    """A 30-minute snooze ended at 07:30Z, so the buffer runs to 08:30Z."""
    state = setup_armed_device(api)
    set_clock(api, SNOOZE_AT)
    set_monitor_mode(
        api, state["device_id"], state["homeowner_id"], "SNOOZE", snooze_minutes=30
    )
    set_clock(api, ONE_MINUTE_INSIDE_BUFFER)
    run_ops_sweep(api)
    return state


def _request_a_snooze(api: ApiClient, state: dict):
    return api.set_monitor_mode(
        state["device_id"],
        monitor_mode_payload("SNOOZE", snooze_minutes=30),
        make_homeowner_headers(state["homeowner_id"]),
    )


class TestSnoozeCooldownBufferedWindow:
    def test_the_sweep_reverts_the_lapsed_snooze_and_retains_the_window(
        self, api: ApiClient
    ):
        """The buffer is computed from fields the revert deliberately keeps.

        "First, lapsed monitor modes revert: a device in `VACATION` whose
        `vacation_ends_at` the clock has reached moves to `NORMAL` with both
        vacation timestamps cleared, and a device in `SNOOZE` whose
        `snooze_window_end_at` the clock has reached moves to `NORMAL` with its
        window bounds retained for the cooldown; each device changed has
        `monitor_mode_updated_at` refreshed and its `version` incremented by 1."
        "Crucially, reverting to `NORMAL` early does **not** clear the window
        bounds: `snooze_window_start_at` and `snooze_window_end_at` are retained
        after the mode reverts, whether the revert was manual or done by the sweep,
        precisely so that the cooldown still applies to somebody who tries to escape
        it by toggling back to `NORMAL`."

        Design: Difficulty/resource_temporal_overlap/snooze_cooldown_buffered_window_on_device
        """
        state = _lapsed_snooze_reverted_by_the_ops_sweep(api)

        device = read_device(api, state["device_id"])
        assert device["monitor_mode"] == "NORMAL"
        assert device["snooze_window_start_at"].startswith("2026-08-01T07:00:00")
        assert device["snooze_window_end_at"].startswith("2026-08-01T07:30:00")

    def test_a_snooze_one_minute_inside_the_buffer_is_refused(self, api: ApiClient):
        """08:29Z is earlier than 07:30Z plus the 60-minute cooldown.

        "Once a snooze window has ever existed on a device, a new snooze is admitted
        only when the clock has reached `snooze_window_end_at` plus a further hour;
        strictly before that instant the request is refused with
        `ERR_SNOOZE_COOLDOWN_ACTIVE`."
        "Crucially, reverting to `NORMAL` early does **not** clear the window
        bounds: `snooze_window_start_at` and `snooze_window_end_at` are retained
        after the mode reverts, whether the revert was manual or done by the sweep,
        precisely so that the cooldown still applies to somebody who tries to escape
        it by toggling back to `NORMAL`."

        Design: Difficulty/resource_temporal_overlap/snooze_cooldown_buffered_window_on_device
        """
        state = _lapsed_snooze_reverted_by_the_ops_sweep(api)

        validate_error(
            _request_a_snooze(api, state), ApiErrorId.ERR_SNOOZE_COOLDOWN_ACTIVE, 409
        )

        device = read_device(api, state["device_id"])
        assert device["monitor_mode"] == "NORMAL"
        # The buffer is measured from the retained window, not from the attempt.
        assert device["snooze_window_start_at"].startswith("2026-08-01T07:00:00")
        assert device["snooze_window_end_at"].startswith("2026-08-01T07:30:00")
        # The gate is confined to one dimension.
        assert device["lifecycle_state"] == "ARMED"
        assert device["valve_state"] == "OPEN"

    def test_the_same_request_at_exactly_the_buffered_boundary_succeeds(
        self, api: ApiClient
    ):
        """08:30Z is the first available instant, so the snooze is granted.

        "Once a snooze window has ever existed on a device, a new snooze is admitted
        only when the clock has reached `snooze_window_end_at` plus a further hour;
        strictly before that instant the request is refused with
        `ERR_SNOOZE_COOLDOWN_ACTIVE`."
        "Acceptance sets `snooze_window_start_at` to the clock and
        `snooze_window_end_at` to the clock plus the requested minutes."

        Design: Difficulty/resource_temporal_overlap/snooze_cooldown_buffered_window_on_device
        """
        state = _lapsed_snooze_reverted_by_the_ops_sweep(api)
        validate_error(
            _request_a_snooze(api, state), ApiErrorId.ERR_SNOOZE_COOLDOWN_ACTIVE, 409
        )

        set_clock(api, AT_BUFFER_BOUNDARY)
        granted = set_monitor_mode(
            api,
            state["device_id"],
            state["homeowner_id"],
            "SNOOZE",
            snooze_minutes=30,
        )
        assert granted["monitor_mode"] == "SNOOZE"
        assert granted["snooze_window_start_at"].startswith("2026-08-01T08:30:00")
        assert granted["snooze_window_end_at"].startswith("2026-08-01T09:00:00")
        assert granted["monitor_mode_updated_at"].startswith("2026-08-01T08:30:00")
        assert granted["lifecycle_state"] == "ARMED"
        assert granted["valve_state"] == "OPEN"
