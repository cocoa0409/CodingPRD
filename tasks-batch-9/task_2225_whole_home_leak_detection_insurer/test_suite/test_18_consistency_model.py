"""One ingest, and every consequence already visible in the same instant.

Nothing in this platform settles later.  The burst sample's own response body
carries its frozen verdict, and the reads issued straight afterwards — event,
ticket, valve, sprinkler schedule and the computed health summary — all show the
full fan-out without any sweep, retry or delay in between.
"""

from test_helpers import (
    ApiClient,
    validate_paginated,
)
from test_helpers.fixtures import (
    ingest_burst_reading,
    read_device,
    read_health_summary,
    read_irrigation_windows,
    set_clock,
    setup_irrigation_window,
)
from test_helpers.test_users import (
    INSURER_ANALYST_USER_ID,
    PROGRAM_ADMIN_USER_ID,
    make_insurer_analyst_headers,
    make_program_admin_headers,
)

WINDOW_START_AT = "2026-08-01T05:00:00Z"
WINDOW_END_AT = "2026-08-01T09:00:00Z"
SPRINKLER_CEILING_GPM = 4.0
BURST_AT = "2026-08-01T07:00:00Z"
ANALYST = make_insurer_analyst_headers(INSURER_ANALYST_USER_ID)
# The escalation-ticket list is authorised to Homeowner and ProgramAdmin alone.
ADMIN = make_program_admin_headers(PROGRAM_ADMIN_USER_ID)
SUMMARY_WINDOW = {
    "window_start_at": BURST_AT,
    "window_end_at": WINDOW_END_AT,
}


def _one_burst_landing_inside_a_sprinkler_window(api: ApiClient) -> dict:
    """The window is live at 07:00, but 12.0 gpm is nothing like irrigation."""
    state = setup_irrigation_window(
        api, WINDOW_START_AT, WINDOW_END_AT, SPRINKLER_CEILING_GPM
    )
    set_clock(api, BURST_AT)
    state["burst_reading"] = ingest_burst_reading(api, state["device_id"], BURST_AT)
    return state


class TestTheBurstIngestResponseAlreadyCarriesEveryDerivedChange:
    def test_the_ingest_body_itself_holds_the_frozen_verdict(self, api: ApiClient):
        """The classification is decided and returned inside the write, not after it.

        "**Step two**, classification runs against the baseline snapshot *as it stood before
        this reading was folded in* — that is, against the values published by earlier readings
        — and the resulting verdict is frozen in the reading's `classification_at_ingest` and,
        on any anomaly event minted, in `baseline_version_used`."
        "During ingest, a reading whose `reading_at` falls inside an `ACTIVE` window for the
        property and whose `flow_gpm` is at or below that window's `expected_max_flow_gpm` has
        `suppressed_by_irrigation` set to true, its classification forced to `NONE`, and no
        anomaly event written — the sprinklers are simply doing their job."

        Design: Corner/consistency_model/immediate_burst_ingest_response_already_carries_every_derived_change
        """
        state = _one_burst_landing_inside_a_sprinkler_window(api)

        reading = state["burst_reading"]
        assert reading["classification_at_ingest"] == "CATASTROPHIC_BURST"
        assert reading["anomaly_event_created"] is True
        # The window is active, but 12.0 gpm is far above its 4.0 gpm ceiling.
        assert reading["suppressed_by_irrigation"] is False
        assert reading["baseline_eligible"] is False

    def test_the_event_is_readable_in_the_same_instant_already_alerted(
        self, api: ApiClient
    ):
        """No intermediate state survives the request that created the event.

        "The event begins in `event_state` `DETECTED` and never remains there past the end of
        the request — it becomes either `ALERTED` or `SUPPRESSED` in the same ingest."
        "An event is created `ALERTED` when the device is `ARMED`, its `monitor_mode` is not
        `SNOOZE`, and no earlier event on the same device shares this classification with a
        `detected_at` inside the last hour."

        Design: Corner/consistency_model/immediate_burst_ingest_response_already_carries_every_derived_change
        """
        state = _one_burst_landing_inside_a_sprinkler_window(api)

        events, meta = validate_paginated(
            api.list_anomaly_events(ANALYST, {"device_id": state["device_id"]})
        )
        assert meta["total_count"] == 1
        event = events[0]
        assert event["event_state"] == "ALERTED"
        assert event["detected_at"].startswith("2026-08-01T07:00:00")
        assert event["auto_shutoff_executed"] is True
        assert event["shutoff_latency_minutes"] == 0.0

    def test_the_ticket_and_the_closed_valve_need_no_sweep_to_appear(
        self, api: ApiClient
    ):
        """The ladder's first rung and the closure both belong to the ingest itself.

        "The new ticket references its `anomaly_event_id`, begins in `stage`
        `PENDING_HOMEOWNER` with `notification_attempt_count` at 1 — the stage-1 notification to
        the homeowner's `phone_e164` over their chosen `notification_channel` counts as the
        first attempt — and carries `homeowner_deadline_at` set to its own `created_at` plus 15
        minutes."
        "When no gate applies, the closure executes as a single atomic cascade: the device's
        `valve_state` moves `OPEN → CLOSED`, `close_count` increases by 1, `last_shutoff_at` is
        stamped with the clock, and the device's `version` increases by 1."

        Design: Corner/consistency_model/immediate_burst_ingest_response_already_carries_every_derived_change
        """
        state = _one_burst_landing_inside_a_sprinkler_window(api)
        events, _ = validate_paginated(
            api.list_anomaly_events(ANALYST, {"device_id": state["device_id"]})
        )

        tickets, meta = validate_paginated(
            api.list_escalation_tickets(
                ADMIN, {"anomaly_event_id": events[0]["id"]}
            )
        )
        assert meta["total_count"] == 1
        ticket = tickets[0]
        assert ticket["stage"] == "PENDING_HOMEOWNER"
        assert ticket["homeowner_deadline_at"].startswith("2026-08-01T07:15:00")
        assert ticket["notification_attempt_count"] == 1
        assert ticket["notified_contact_id"] is None

        # Read in the same logical instant, with no operational sweep in between.
        device = read_device(api, state["device_id"])
        assert device["valve_state"] == "CLOSED"
        assert device["close_count"] == 1
        assert device["last_shutoff_at"].startswith("2026-08-01T07:00:00")

    def test_the_sprinkler_window_and_the_health_summary_have_already_moved(
        self, api: ApiClient
    ):
        """The stored side effect and the computed read agree at the same instant.

        "And every irrigation window belonging to the device's property whose `status` is
        `ACTIVE` moves to `SUSPENDED_BY_SHUTOFF` with `suspended_at` stamped at the clock; there
        is no point excusing sprinkler flow on a line that has no water in it."
        "Every accepted telemetry reading for the resolved device whose `reading_at` falls at or
        after `period_start_at` and strictly before `period_end_at` vouches for the two hours of
        monitoring that follow it: each contributes a coverage interval beginning at its
        `reading_at` and ending at the earlier of two hours later or `period_end_at`, so the
        tail of the last reading is clamped at the period boundary."

        Design: Corner/consistency_model/immediate_burst_ingest_response_already_carries_every_derived_change
        """
        state = _one_burst_landing_inside_a_sprinkler_window(api)

        windows = read_irrigation_windows(api, state["property_id"])
        assert len(windows) == 1
        assert windows[0]["status"] == "SUSPENDED_BY_SHUTOFF"
        assert windows[0]["suspended_at"].startswith("2026-08-01T07:00:00")

        summary = read_health_summary(
            api, state["device_id"], ANALYST, SUMMARY_WINDOW
        )
        assert summary["period_minutes"] == 120
        assert summary["covered_minutes"] == 120
        assert summary["uptime_pct"] == 100.00
        assert summary["offline_gap_count"] == 0
