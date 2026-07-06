"""Suppression cascades and conserved derived counters."""
from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS, make_contact_headers,
)
from test_helpers.fixtures import (
    get_alert_notifications,
    setup_dispatched_single_recipient, setup_sent_single_recipient,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
INTEGRATOR = TEST_USERS["integrator_headers"]


def test_optout_suppresses_notification(api):
    """PRD §3.7: "When a resident opts a channel out (`PENDING`/`CONFIRMED` →
    `OPTED_OUT`), every non-terminal notification on that channel — those with
    `delivery_status` in `QUEUED`, `SENT`, `RETRYING`, or `FAILED` — advances to the
    terminal `SUPPRESSED`".

    Design: Difficulty/transitive_cascade/optout_suppresses_notification_then_autocloses_alert
    """
    scenario = setup_sent_single_recipient(api, severity="WARNING", channels=["SMS"])
    channel = validate_success(api.opt_out_channel(
        scenario["channel"]["id"], make_contact_headers(scenario["contact"]["id"])))
    assert channel["opt_in_status"] == "OPTED_OUT", f"Expected OPTED_OUT, got {channel['opt_in_status']}"
    notif = get_success_data(api.get_notification(scenario["notification"]["id"], DISPATCHER))
    assert notif["delivery_status"] == "SUPPRESSED", f"Expected SUPPRESSED, got {notif['delivery_status']}"


def test_optout_cascade_autocloses_alert(api):
    """PRD §3.7: "each such suppression decrements its parent alert's `pending_count`;
    when an affected alert's `pending_count` reaches zero while that alert is
    `DISPATCHING` or `SENT`, that alert advances to `CLOSED` and its `delivered_reach` is
    recorded".

    Design: Difficulty/transitive_cascade/optout_suppresses_notification_then_autocloses_alert
    """
    scenario = setup_sent_single_recipient(api, severity="WARNING", channels=["SMS"])
    get_success_data(api.opt_out_channel(
        scenario["channel"]["id"], make_contact_headers(scenario["contact"]["id"])))
    alert = get_success_data(api.get_alert(scenario["alert"]["id"], DISPATCHER))
    assert alert["pending_count"] == 0, f"Expected pending_count 0, got {alert['pending_count']}"
    assert alert["status"] == "CLOSED", f"Expected CLOSED after cascade, got {alert['status']}"


def test_cancel_suppresses_queued_notification(api):
    """PRD §3.7: "Cancellation suppresses every non-terminal notification of the alert
    (`QUEUED`, `SENT`, `RETRYING`, `FAILED` → `SUPPRESSED`), which in turn triggers a
    recompute of each affected gateway's `window_count` to drop those suppressed sends,
    and the alert's `pending_count` is recomputed to zero."

    Design: Difficulty/transitive_cascade/cancel_suppresses_queued_then_recomputes_gateway_window
    """
    scenario = setup_dispatched_single_recipient(api, severity="WARNING", channels=["SMS"])
    cancelled = validate_success(api.cancel_alert(scenario["alert"]["id"], DISPATCHER))
    assert cancelled["status"] == "CANCELLED", f"Expected CANCELLED, got {cancelled['status']}"
    notifs = get_alert_notifications(api, scenario["alert"]["id"])
    assert notifs[0]["delivery_status"] == "SUPPRESSED", f"Expected SUPPRESSED, got {notifs[0]['delivery_status']}"


def test_cancel_recomputes_gateway_window_to_zero(api):
    """PRD §3.7: "Cancellation suppresses every non-terminal notification of the alert
    (`QUEUED`, `SENT`, `RETRYING`, `FAILED` → `SUPPRESSED`), which in turn triggers a
    recompute of each affected gateway's `window_count` to drop those suppressed sends".

    Design: Difficulty/transitive_cascade/cancel_suppresses_queued_then_recomputes_gateway_window
    """
    scenario = setup_dispatched_single_recipient(api, severity="WARNING", channels=["SMS"])
    get_success_data(api.cancel_alert(scenario["alert"]["id"], DISPATCHER))
    gateway = get_success_data(api.get_gateway(scenario["gateway"]["id"], DISPATCHER))
    assert gateway["window_count"] == 0, f"Expected window_count 0 after cancel, got {gateway['window_count']}"


def test_gateway_window_count_one_after_dispatch(api):
    """PRD §2.9: "A gateway's `window_count` is the number of non-`SUPPRESSED`
    notifications whose `channel_type` equals the gateway's `channel_type` and whose
    `created_at` falls in the current throttle window."

    Design: Difficulty/compensating_invariant/gateway_window_count_conserved_across_dispatch_and_cancel
    """
    scenario = setup_dispatched_single_recipient(api, severity="WARNING", channels=["SMS"])
    gateway = get_success_data(api.get_gateway(scenario["gateway"]["id"], DISPATCHER))
    assert gateway["window_count"] == 1, f"Expected window_count 1 after dispatch, got {gateway['window_count']}"


def test_gateway_window_count_conserved_back_to_zero_on_cancel(api):
    """PRD §2.9: "Whenever a notification is suppressed — whether by an alert
    cancellation or by a channel opt-out — the owning alert's `pending_count` is
    decremented and every affected gateway's `window_count` is recomputed to drop the
    suppressed sends."

    Design: Difficulty/compensating_invariant/gateway_window_count_conserved_across_dispatch_and_cancel
    """
    scenario = setup_dispatched_single_recipient(api, severity="WARNING", channels=["SMS"])
    before = get_success_data(api.get_gateway(scenario["gateway"]["id"], DISPATCHER))
    assert before["window_count"] == 1
    get_success_data(api.cancel_alert(scenario["alert"]["id"], DISPATCHER))
    after = get_success_data(api.get_gateway(scenario["gateway"]["id"], DISPATCHER))
    assert after["window_count"] == 0, f"Expected window_count conserved to 0, got {after['window_count']}"


def test_alert_pending_count_one_after_dispatch_and_tick(api):
    """PRD §2.9: "An alert's `pending_count` is the number of that alert's notifications
    whose `delivery_status` is one of `QUEUED`, `SENT`, `RETRYING`, or `FAILED` — the
    messages still in flight."

    Design: Difficulty/compensating_invariant/alert_pending_count_conserved_across_dispatch_and_deliver
    """
    scenario = setup_sent_single_recipient(api, severity="WARNING", channels=["SMS"])
    alert = get_success_data(api.get_alert(scenario["alert"]["id"], DISPATCHER))
    assert alert["pending_count"] == 1, f"Expected pending_count 1, got {alert['pending_count']}"


def test_alert_pending_count_conserved_to_zero_on_delivery(api):
    """PRD §3.6: "A `DELIVERED` outcome advances the notification `SENT → DELIVERED`,
    decrements the parent alert's `pending_count`, and — if that decrement brings
    `pending_count` to zero while the alert is `SENT` — closes the alert and records its
    delivered reach."

    Design: Difficulty/compensating_invariant/alert_pending_count_conserved_across_dispatch_and_deliver
    """
    scenario = setup_sent_single_recipient(api, severity="WARNING", channels=["SMS"])
    get_success_data(api.delivery_report(scenario["notification"]["id"], {"outcome": "DELIVERED"}, INTEGRATOR))
    alert = get_success_data(api.get_alert(scenario["alert"]["id"], DISPATCHER))
    assert alert["pending_count"] == 0, f"Expected pending_count 0, got {alert['pending_count']}"
    assert alert["status"] == "CLOSED", f"Expected auto-CLOSED, got {alert['status']}"
