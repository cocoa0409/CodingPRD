"""Single writes whose consequences travel four and five hops outward.

One telemetry ingest mints an event, that event opens a ticket, the same event
closes the valve, and the closure suspends the property's irrigation window.  One
transfer acceptance rewrites ownership, which invalidates the baseline, which
demotes the device, which drops the insurer credit and books a clawback.
"""

import pytest

from test_helpers import (
    ApiClient,
    assert_anomaly_event,
    assert_device,
    assert_device_transfer,
    assert_escalation_ticket,
    assert_insurance_policy,
    assert_irrigation_window,
    assert_property,
)
from test_helpers.fixtures import (
    accept_transfer,
    create_buyer,
    ingest_burst_reading,
    ingest_drip_reading,
    initiate_transfer,
    read_device,
    read_device_version,
    read_events,
    read_homeowner,
    read_irrigation_windows,
    read_live_baseline,
    read_policy,
    read_property,
    read_telemetry,
    read_tickets,
    read_transfer,
    set_clock,
    setup_finalized_credit_period,
    setup_irrigation_window,
)

BURST_AT = "2026-08-01T07:00:00Z"
WINDOW = ("2026-08-03T05:00:00Z", "2026-08-03T06:00:00Z")


def _burst_under_a_future_irrigation_window(api: ApiClient) -> dict:
    """An armed device with an ACTIVE window two days out, then a burst."""
    state = setup_irrigation_window(api, *WINDOW, label="Front zone Monday")
    set_clock(api, BURST_AT)
    state["burst_reading"] = ingest_burst_reading(api, state["device_id"], BURST_AT)
    return state


class TestTelemetryBurstCascade:
    def test_one_ingest_mints_the_event_and_opens_its_homeowner_ticket(
        self, api: ApiClient
    ):
        """Hops one and two: the reading causes the event, the event the ticket.

        "The event begins in `event_state` `DETECTED` and never remains there past
        the end of the request — it becomes either `ALERTED` or `SUPPRESSED` in the
        same ingest."
        "The new ticket references its `anomaly_event_id`, begins in `stage`
        `PENDING_HOMEOWNER` with `notification_attempt_count` at 1 — the stage-1
        notification to the homeowner's `phone_e164` over their chosen
        `notification_channel` counts as the first attempt — and carries
        `homeowner_deadline_at` set to its own `created_at` plus 15 minutes."

        Design: Difficulty/transitive_cascade/telemetry_burst_three_hop_cascade
        """
        state = _burst_under_a_future_irrigation_window(api)

        events = read_events(api, state["device_id"], event_state="ALERTED")
        assert len(events) == 1
        event = events[0]
        assert_anomaly_event(event)
        assert event["classification"] == "CATASTROPHIC_BURST"
        assert event["event_state"] == "ALERTED"
        assert event["detected_at"].startswith("2026-08-01T07:00:00")
        assert event["severity_score"] == pytest.approx(0.833, abs=0.0005)
        assert event["baseline_version_used"] == 3

        tickets = read_tickets(api, anomaly_event_id=event["id"])
        assert len(tickets) == 1
        ticket = tickets[0]
        assert_escalation_ticket(ticket)
        assert ticket["stage"] == "PENDING_HOMEOWNER"
        assert ticket["homeowner_deadline_at"].startswith("2026-08-01T07:15:00")
        assert ticket["notification_attempt_count"] == 1
        assert ticket["notified_contact_id"] is None
        assert ticket["contact_deadline_at"] is None

    def test_the_shutoff_hop_carries_on_into_the_irrigation_window(
        self, api: ApiClient
    ):
        """Hops three and four: the closure suspends the declared window.

        "When no gate applies, the closure executes as a single atomic cascade: the
        device's `valve_state` moves `OPEN → CLOSED`, `close_count` increases by 1,
        `last_shutoff_at` is stamped with the clock, and the device's `version`
        increases by 1."
        "And every irrigation window belonging to the device's property whose
        `status` is `ACTIVE` moves to `SUSPENDED_BY_SHUTOFF` with `suspended_at`
        stamped at the clock; there is no point excusing sprinkler flow on a line
        that has no water in it."

        Design: Difficulty/transitive_cascade/telemetry_burst_three_hop_cascade
        """
        state = _burst_under_a_future_irrigation_window(api)

        device = read_device(api, state["device_id"])
        assert_device(device)
        assert device["valve_state"] == "CLOSED"
        assert device["close_count"] == 1
        assert device["reopen_count"] == 0
        assert device["last_shutoff_at"].startswith("2026-08-01T07:00:00")

        event = read_events(api, state["device_id"])[0]
        assert event["auto_shutoff_executed"] is True
        assert event["shutoff_latency_minutes"] == pytest.approx(0.0, abs=0.01)

        windows = read_irrigation_windows(
            api, state["property_id"], state["homeowner_headers"]
        )
        assert len(windows) == 1
        window = windows[0]
        assert_irrigation_window(window)
        assert window["id"] == state["irrigation_window_id"]
        assert window["status"] == "SUSPENDED_BY_SHUTOFF"
        assert window["suspended_at"].startswith("2026-08-01T07:00:00")

        # The cascade travelled outward without disturbing the two dimensions it
        # never touches.
        assert device["lifecycle_state"] == "ARMED"
        assert read_live_baseline(api, state["device_id"])["learning_state"] == "COMPLETE"

        reading = read_telemetry(api, state["device_id"])[-1]
        assert reading["anomaly_event_created"] is True
        assert reading["suppressed_by_irrigation"] is False
        assert reading["baseline_eligible"] is False

    def test_a_drip_stops_at_hop_two_and_leaves_the_window_active(
        self, api: ApiClient
    ):
        """Removing the shutoff hop removes the irrigation hop with it.

        "A shutoff is *required* in exactly two situations: the classification is
        `CATASTROPHIC_BURST`, in any mode; or the classification is
        `RUNNING_FIXTURE` and the device's `monitor_mode` is `VACATION`."
        "And every irrigation window belonging to the device's property whose
        `status` is `ACTIVE` moves to `SUSPENDED_BY_SHUTOFF` with `suspended_at`
        stamped at the clock; there is no point excusing sprinkler flow on a line
        that has no water in it."

        Design: Difficulty/transitive_cascade/telemetry_burst_three_hop_cascade
        """
        state = setup_irrigation_window(api, *WINDOW, label="Front zone Monday")
        set_clock(api, BURST_AT)
        ingest_drip_reading(api, state["device_id"], BURST_AT)

        events = read_events(api, state["device_id"])
        assert len(events) == 1
        assert events[0]["classification"] == "DRIP"
        assert events[0]["event_state"] == "ALERTED"
        assert events[0]["auto_shutoff_executed"] is False

        device = read_device(api, state["device_id"])
        assert device["valve_state"] == "OPEN"
        assert device["close_count"] == 0

        window = read_irrigation_windows(
            api, state["property_id"], state["homeowner_headers"]
        )[0]
        assert window["status"] == "ACTIVE"
        assert window["suspended_at"] is None


ACCEPT_AT = "2026-08-02T06:40:00Z"


def _accepted_transfer_of_a_credit_earning_device(api: ApiClient) -> dict:
    """One awarded period, then a transfer the buyer accepts."""
    state = setup_finalized_credit_period(api)
    buyer = create_buyer(api)
    state["buyer"] = buyer
    state["buyer_id"] = buyer["id"]

    set_clock(api, ACCEPT_AT)
    transfer = initiate_transfer(
        api,
        state["device_id"],
        buyer["id"],
        state["homeowner_id"],
        read_device_version(api, state["device_id"], state["homeowner_headers"]),
        transfer_note="Closing 2026-08-02",
    )
    state["transfer_id"] = transfer["id"]
    state["accepted"] = accept_transfer(api, transfer["id"], buyer["id"])
    return state


class TestTransferAcceptCascade:
    def test_acceptance_rewrites_ownership_and_releases_both_holds(
        self, api: ApiClient
    ):
        """Hops one and two of the acceptance chain.

        "The property's `homeowner_id` is rewritten to `to_homeowner_id` and its
        `property_state` moves `TRANSFER_PENDING → ACTIVE` with its `version`
        incremented by 1."

        Design: Difficulty/transitive_cascade/transfer_accept_five_hop_cascade
        """
        state = _accepted_transfer_of_a_credit_earning_device(api)

        transfer = read_transfer(api, state["transfer_id"], state["homeowner_headers"])
        assert_device_transfer(transfer)
        assert transfer["status"] == "ACCEPTED"
        assert transfer["accepted_at"].startswith("2026-08-02T06:40:00")
        assert transfer["accepted_by_user_id"] == state["buyer_id"]
        assert transfer["from_homeowner_id"] == state["homeowner_id"]
        assert transfer["to_homeowner_id"] == state["buyer_id"]

        prop = read_property(api, state["property_id"])
        assert_property(prop)
        assert prop["homeowner_id"] == state["buyer_id"]
        assert prop["property_state"] == "ACTIVE"

        assert read_homeowner(api, state["buyer_id"])["owned_property_count"] == 1
        assert read_homeowner(api, state["homeowner_id"])["owned_property_count"] == 0

    def test_ownership_change_invalidates_the_baseline_and_demotes_the_device(
        self, api: ApiClient
    ):
        """Hops three and four: a new household means a new baseline.

        "That ownership rewrite invalidates the learned baseline — the profile moves
        `COMPLETE → INVALIDATED` with `invalidated_reason` `OWNERSHIP_TRANSFER`,
        `completed_at` cleared, and `false_positive_count` reset to 0 — because the
        new household's water habits are not the old one's."
        "The invalidation in turn demotes the device `TRANSFER_PENDING → LEARNING`,
        sets `baseline_ready` back to false, forces `monitor_mode` to `NORMAL` with
        `monitor_mode_updated_at` refreshed and both `vacation_started_at` and
        `vacation_ends_at` cleared, and increments the device's `version` by 1."

        Design: Difficulty/transitive_cascade/transfer_accept_five_hop_cascade
        """
        state = _accepted_transfer_of_a_credit_earning_device(api)

        profile = read_live_baseline(api, state["device_id"])
        assert profile["learning_state"] == "INVALIDATED"
        assert profile["invalidated_reason"] == "OWNERSHIP_TRANSFER"
        assert profile["completed_at"] is None
        assert profile["false_positive_count"] == 0
        # The reopen waits for the next accepted reading.
        assert profile["learning_cycle_no"] == 1

        device = read_device(api, state["device_id"])
        assert_device(device)
        assert device["lifecycle_state"] == "LEARNING"
        assert device["baseline_ready"] is False
        assert device["monitor_mode"] == "NORMAL"
        assert device["valve_state"] == "OPEN"

    def test_the_demotion_suspends_the_credit_and_books_a_3748_cent_clawback(
        self, api: ApiClient
    ):
        """Hop five: the insurer credit moves only because the device left ARMED.

        "The demotion out of `ARMED` then suspends any policy on the property that
        was `CREDIT_ACTIVE`, moving it to `CREDIT_SUSPENDED` with `suspended_reason`
        `OWNERSHIP_TRANSFER` and clawing back the newest awarded period exactly as
        described in §3.8."
        "That amount is added to `clawback_cents_total` and subtracted from
        `credited_cents_total`, `current_credit_tier_pct` is reset to 0, and the
        policy's `version` increments by 1."
        "The attestation rows themselves are never rewritten: `credited_cents_total`
        is defined as the sum of `credit_cents_awarded` across awarded periods, plus
        the `true_up_cents` of any policy-year-closing period, minus
        `clawback_cents_total`."

        Design: Difficulty/transitive_cascade/transfer_accept_five_hop_cascade
        """
        state = _accepted_transfer_of_a_credit_earning_device(api)
        assert state["policy"]["credit_state"] == "CREDIT_ACTIVE"
        assert state["policy"]["credited_cents_total"] == 3748
        assert state["policy"]["clawback_cents_total"] == 0

        policy = read_policy(api, state["policy_id"])
        assert_insurance_policy(policy)
        assert policy["credit_state"] == "CREDIT_SUSPENDED"
        assert policy["suspended_reason"] == "OWNERSHIP_TRANSFER"
        assert policy["clawback_cents_total"] == 3748
        assert policy["credited_cents_total"] == 0
        assert policy["current_credit_tier_pct"] == pytest.approx(0.00, abs=0.01)

        # The awarded period itself is untouched; the clawback lives on the ledger.
        assert state["attestation"]["status"] == "FINALIZED_AWARDED"
        assert state["attestation"]["credit_cents_awarded"] == 3748
        assert policy["finalized_period_count"] == 1
        assert policy["last_attestation_end_at"].startswith("2026-08-02T06:40:00")
