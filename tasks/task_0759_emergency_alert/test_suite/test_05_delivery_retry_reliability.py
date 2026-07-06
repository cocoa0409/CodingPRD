"""Delivery, the retry loop, acknowledgement, and reliability scoring."""
from datetime import datetime
import pytest
from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS, make_contact_headers,
)
from test_helpers.fixtures import (
    set_clock, run_tick, get_alert_notifications,
    setup_sent_single_recipient, setup_two_channel_recipient_one_delivered,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
INTEGRATOR = TEST_USERS["integrator_headers"]


def _instant(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def test_failed_notification_enters_retrying_on_tick(api):
    """PRD §3.6: "When a tick processes a `FAILED` notification whose `attempt_count` is
    still below 3, the notification advances `FAILED → RETRYING` and its `next_retry_at`
    is set to the current clock plus a back-off delay."

    Design: Difficulty/combinatorial_formula/retry_backoff_tiered_min_delay
    """
    scenario = setup_sent_single_recipient(api, severity="WARNING", channels=["SMS"])
    get_success_data(api.delivery_report(scenario["notification"]["id"], {"outcome": "FAILED"}, INTEGRATOR))
    run_tick(api)
    notif = get_success_data(api.get_notification(scenario["notification"]["id"], DISPATCHER))
    assert notif["delivery_status"] == "RETRYING", f"Expected RETRYING, got {notif['delivery_status']}"
    assert notif["attempt_count"] == 1, f"Expected attempt_count 1, got {notif['attempt_count']}"


def test_retry_backoff_delay_warning_attempt1_is_120s(api):
    """PRD §3.6: "The back-off delay is computed from the base delay of 60 seconds
    multiplied by two raised to the power of one less than the current `attempt_count`,
    multiplied by a severity factor of 1 for `INFO`, 1 for `ADVISORY`, 2 for `WARNING`,
    and 4 for `CRITICAL`; the result is then capped at 3600 seconds by taking the smaller
    of the capped maximum and the computed value."

    Design: Difficulty/combinatorial_formula/retry_backoff_tiered_min_delay
    """
    scenario = setup_sent_single_recipient(api, severity="WARNING", channels=["SMS"],
                                           clock="2026-03-10T14:00:00Z")
    get_success_data(api.delivery_report(scenario["notification"]["id"], {"outcome": "FAILED"}, INTEGRATOR))
    run_tick(api)
    notif = get_success_data(api.get_notification(scenario["notification"]["id"], DISPATCHER))
    # 60 * 2^(1-1) * 2 (WARNING) = 120s -> 14:00:00 + 120s = 14:02:00Z.
    assert _instant(notif["next_retry_at"]) == _instant("2026-03-10T14:02:00Z"), (
        f"Expected next_retry_at 2026-03-10T14:02:00Z, got {notif['next_retry_at']}")


def test_retry_cycle_failed_to_retrying(api):
    """PRD §3.6: "When a tick processes a `FAILED` notification whose `attempt_count` is
    still below 3, the notification advances `FAILED → RETRYING` and its `next_retry_at`
    is set to the current clock plus a back-off delay."

    Design: Difficulty/non_linear_state_machine/notification_retry_cycle_failed_retrying_sent
    """
    scenario = setup_sent_single_recipient(api, severity="WARNING", channels=["SMS"],
                                           clock="2026-03-10T14:00:00Z")
    get_success_data(api.delivery_report(scenario["notification"]["id"], {"outcome": "FAILED"}, INTEGRATOR))
    run_tick(api)
    notif = get_success_data(api.get_notification(scenario["notification"]["id"], DISPATCHER))
    assert notif["delivery_status"] == "RETRYING", f"Expected RETRYING, got {notif['delivery_status']}"


def test_retry_cycle_retrying_back_to_sent_increments_attempt(api):
    """PRD §3.6: "When a later tick finds a `RETRYING` notification whose `next_retry_at`
    is at or before the current clock, the notification advances `RETRYING → SENT`, its
    `attempt_count` increments by 1, and `next_retry_at` returns to null."

    Design: Difficulty/non_linear_state_machine/notification_retry_cycle_failed_retrying_sent
    """
    scenario = setup_sent_single_recipient(api, severity="WARNING", channels=["SMS"],
                                           clock="2026-03-10T14:00:00Z")
    nid = scenario["notification"]["id"]
    get_success_data(api.delivery_report(nid, {"outcome": "FAILED"}, INTEGRATOR))
    run_tick(api)  # FAILED -> RETRYING (next_retry_at 14:02:00Z)
    set_clock(api, "2026-03-10T14:05:00Z")
    run_tick(api)  # RETRYING -> SENT (next_retry_at <= now)
    notif = get_success_data(api.get_notification(nid, DISPATCHER))
    assert notif["delivery_status"] == "SENT", f"Expected SENT, got {notif['delivery_status']}"
    assert notif["attempt_count"] == 2, f"Expected attempt_count 2, got {notif['attempt_count']}"


def test_reliability_optimistic_counts_sent_as_success(api):
    """PRD §3.6: "the default optimistic read counts notifications whose
    `delivery_status` is `SENT`, `DELIVERED`, or `RETRYING` as successes, while the strict
    read — selected by the `mode` query parameter set to strict — counts only `DELIVERED`
    notifications as successes."

    Design: Difficulty/dual_variant_calc/contact_reliability_optimistic_vs_strict
    """
    scenario = setup_two_channel_recipient_one_delivered(api)
    data = get_success_data(api.get_contact(scenario["contact"]["id"], DISPATCHER))
    assert data["reliability_score"] == pytest.approx(1.00, abs=0.001), (
        f"Optimistic (SENT+DELIVERED)/2 = 1.00, got {data['reliability_score']}")


def test_reliability_strict_counts_only_delivered(api):
    """PRD §3.6: "the strict read — selected by the `mode` query parameter set to strict
    — counts only `DELIVERED` notifications as successes. The two diverge whenever a sent
    or retrying notification has not yet been delivered."

    Design: Difficulty/dual_variant_calc/contact_reliability_optimistic_vs_strict
    """
    scenario = setup_two_channel_recipient_one_delivered(api)
    data = get_success_data(api.get_contact(scenario["contact"]["id"], DISPATCHER, params={"mode": "strict"}))
    assert data["reliability_score"] == pytest.approx(0.50, abs=0.001), (
        f"Strict DELIVERED/2 = 0.50, got {data['reliability_score']}")


def test_acknowledge_sets_receipt_and_delivers(api):
    """PRD §3.6: "A notification's `receipt_status` begins `NONE` and can advance to
    `ACKNOWLEDGED` when the recipient, acting as a `Contact` whose `X-User-ID` equals the
    notification's `contact_id`, acknowledges it — permitted only while the notification's
    `delivery_status` is `SENT`, `DELIVERED`, or `RETRYING`."
    PRD §3.6: "If the notification was `SENT` at the moment of acknowledgement, that same
    acknowledgement also advances its `delivery_status` `SENT → DELIVERED` (carrying the
    pending-count decrement and possible auto-close with it)."

    Design: Corner/state_machines/acknowledge_sets_receipt_and_delivers
    """
    scenario = setup_sent_single_recipient(api, severity="WARNING", channels=["SMS"])
    contact_id = scenario["contact"]["id"]
    data = validate_success(api.acknowledge_notification(
        scenario["notification"]["id"], make_contact_headers(contact_id)))
    assert data["receipt_status"] == "ACKNOWLEDGED", f"Expected ACKNOWLEDGED, got {data['receipt_status']}"
    assert data["delivery_status"] == "DELIVERED", f"Expected SENT->DELIVERED, got {data['delivery_status']}"
