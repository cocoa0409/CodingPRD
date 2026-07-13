"""Multi-channel alerting: parallel channel dimensions and the conserved IPAWS slot budget."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_active_incident, create_zone, create_alert, set_alert_status, TEST_USERS,
)

COMMANDER = TEST_USERS["commander_headers"]
PIO = TEST_USERS["pio_headers"]


def test_alert_channel_wea_sent_leaves_eas_pending(api):
    """PRD 3.7: "An alert tracks each channel as an independent parallel dimension: `wea_status`, `eas_status`, `ipaws_status`, and `sms_status` are each set to `PENDING` if that channel was requested and to `NA` if it was not, and each later resolves to `SENT` or `FAILED`."

    Design: Difficulty/non_linear_state_machine/alert_parallel_channel_dimensions_independent
    """
    inc = create_active_incident()
    zone = create_zone(inc["id"])
    alert = create_alert(zone["id"], channels=["WEA", "EAS"], severity="WARNING")
    set_alert_status(alert["id"], "QUEUED")

    data = validate_success(
        api.record_alert_channel_result(alert["id"], {"channel": "WEA", "result": "SENT"}, PIO)
    )
    assert data["wea_status"] == "SENT"
    assert data["eas_status"] == "PENDING"


def test_alert_overall_stays_queued_until_all_resolve(api):
    """PRD 3.7: "The `overall_status` can leave `QUEUED` only once every requested channel has resolved."

    Design: Difficulty/non_linear_state_machine/alert_parallel_channel_dimensions_independent
    """
    inc = create_active_incident()
    zone = create_zone(inc["id"])
    alert = create_alert(zone["id"], channels=["WEA", "EAS"], severity="WARNING")
    set_alert_status(alert["id"], "QUEUED")

    data = validate_success(
        api.record_alert_channel_result(alert["id"], {"channel": "WEA", "result": "SENT"}, PIO)
    )
    # EAS still PENDING, so the rollup must stay QUEUED.
    assert data["overall_status"] == "QUEUED"


def test_ipaws_slots_reserved_one_between_queue_and_cancel(api):
    """PRD 2.8: "This count is a conserved quantity: queuing an IPAWS-bearing alert adds exactly one to it, and cancelling that queued alert (or the alert finishing its send) releases exactly one, so a queue-then-cancel pair nets to zero."

    Design: Difficulty/compensating_invariant/ipaws_slot_conserved_across_queue_then_cancel
    """
    inc = create_active_incident(ipaws_daily_slot_budget=5)
    zone = create_zone(inc["id"])
    alert = create_alert(zone["id"], channels=["IPAWS"], severity="EXTREME")
    set_alert_status(alert["id"], "QUEUED")

    mid = validate_success(api.get_incident(inc["id"], COMMANDER))
    assert mid["ipaws_slots_reserved"] == 1

    cancelled = set_alert_status(alert["id"], "CANCELLED")
    assert cancelled["overall_status"] == "CANCELLED"


def test_ipaws_slots_reserved_returns_to_zero_after_cancel(api):
    """PRD 3.7: "A queued alert may be cancelled `QUEUED → CANCELLED`, which releases its IPAWS reservation as a compensation, restoring `ipaws_slots_reserved` to its pre-queue value."

    Design: Difficulty/compensating_invariant/ipaws_slot_conserved_across_queue_then_cancel
    """
    inc = create_active_incident(ipaws_daily_slot_budget=5)
    zone = create_zone(inc["id"])
    alert = create_alert(zone["id"], channels=["IPAWS"], severity="EXTREME")
    set_alert_status(alert["id"], "QUEUED")
    set_alert_status(alert["id"], "CANCELLED")

    data = validate_success(api.get_incident(inc["id"], COMMANDER))
    assert data["ipaws_slots_reserved"] == 0


def test_ipaws_budget_exhausted_on_second_queue(api):
    """PRD 3.7: "if the requested `channels` include `IPAWS`, the queue is permitted only when the count of the incident's already-in-flight IPAWS alerts — those on the incident's zones with `IPAWS` among their channels and `overall_status` of `QUEUED`, `SENT`, or `PARTIAL` — is strictly less than the incident's `ipaws_daily_slot_budget`; otherwise the queue is rejected with `ERR_IPAWS_SLOTS_EXHAUSTED`."

    Design: Corner/validations/ipaws_budget_exhausted_on_second_queue
    """
    inc = create_active_incident(ipaws_daily_slot_budget=1)
    zone = create_zone(inc["id"])
    alert1 = create_alert(zone["id"], channels=["IPAWS"], severity="EXTREME", message="Go")
    set_alert_status(alert1["id"], "QUEUED")
    alert2 = create_alert(zone["id"], channels=["IPAWS"], severity="EXTREME", message="Go again")

    resp = api.set_alert_status(alert2["id"], {"state": "QUEUED"}, PIO)
    validate_error(resp, ApiErrorId.ERR_IPAWS_SLOTS_EXHAUSTED)
