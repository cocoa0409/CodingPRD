"""Compensating actions and conserved quantities: reopen voids the period's line
items (money conservation) and device return restores the monitoring flag.

Covers difficulty rule compensating_invariant (both instances).
"""
from test_helpers import (
    api_client, validate_success, get_success_data, TEST_USERS,
    setup_finalized_eligible_period, setup_enrolled_patient_with_active_device,
)

BILL = TEST_USERS["billing_specialist_headers"]
CC = TEST_USERS["care_coordinator_headers"]


def test_reopen_voids_all_line_items_zeroing_period_charge(api):
    """PRD §3.9: "Reopening voids every `FINALIZED` line item for the period (moving them
    `FINALIZED → VOIDED`), clears `finalized_total_minutes` and `finalized_total_cents`
    back to null, and sets the period's `status` to `REOPENED`."

    Design: Difficulty/compensating_invariant/reopen_voids_line_items_conserving_period_charge_total
    """
    ctx = setup_finalized_eligible_period(
        mrn="M-CI1-1", serial_number="SN-CI1-1", device_type="BP_CUFF",
        care_minutes=20, device_day_count=0)
    period_id = ctx["period"]["id"]
    before = ctx["finalized_period"]
    assert before["finalized_total_cents"] == 6842, "99453 + 99457 = 6842"
    items_before = get_success_data(api.list_line_items(period_id, BILL))
    non_voided_before = sum(it["amount_cents"] for it in items_before if it["status"] != "VOIDED")
    assert non_voided_before == 6842, "non-VOIDED charge total equals finalized total"

    reopened = validate_success(api.reopen_billing_period(period_id, BILL), 200)
    assert reopened["status"] == "REOPENED"
    assert reopened["finalized_total_cents"] is None, "finalized_total_cents cleared to null"

    items_after = get_success_data(api.list_line_items(period_id, BILL))
    assert all(it["status"] == "VOIDED" for it in items_after), "every line item VOIDED"
    non_voided_after = sum(it["amount_cents"] for it in items_after if it["status"] != "VOIDED")
    assert non_voided_after == 0, "no residual charge after reopen (conserved -> 0)"


def test_reopen_clears_finalized_totals(api):
    """PRD §3.9: "Reopening voids every `FINALIZED` line item for the period (moving them
    `FINALIZED → VOIDED`), clears `finalized_total_minutes` and `finalized_total_cents`
    back to null, and sets the period's `status` to `REOPENED`."

    Design: Difficulty/compensating_invariant/reopen_voids_line_items_conserving_period_charge_total
    """
    ctx = setup_finalized_eligible_period(
        mrn="M-CI1-2", serial_number="SN-CI1-2", device_type="BP_CUFF",
        care_minutes=20, device_day_count=0)
    period_id = ctx["period"]["id"]
    reopened = validate_success(api.reopen_billing_period(period_id, BILL), 200)
    assert reopened["status"] == "REOPENED"
    assert reopened["finalized_total_minutes"] is None
    assert reopened["finalized_total_cents"] is None


def test_returning_only_active_device_pauses_monitoring(api):
    """PRD §3.4: "When an `ACTIVE` device is returned and no remaining device for that
    patient is `ACTIVE`, monitoring pauses as a cross-entity cascade: `monitoring_status`
    moves to `PAUSED`."

    Design: Difficulty/compensating_invariant/device_return_conserves_monitoring_count_invariant
    """
    ctx = setup_enrolled_patient_with_active_device(
        mrn="M-CI2-1", serial_number="SN-CI2-1", consent_type="RPM")
    patient = get_success_data(api.get_patient(ctx["patient"]["id"], CC))
    assert patient["monitoring_status"] == "MONITORING", "one ACTIVE device -> MONITORING"
    returned = validate_success(
        api.return_device(ctx["patient"]["id"], ctx["device"]["id"], CC), 200)
    assert returned["status"] == "RETURNED"
    after = get_success_data(api.get_patient(ctx["patient"]["id"], CC))
    assert after["monitoring_status"] == "PAUSED", "zero ACTIVE devices -> PAUSED"


def test_device_activation_then_return_round_trips_monitoring_flag(api):
    """PRD §3.4: "the activation of this first device starts monitoring as a cross-entity
    cascade, advancing `monitoring_status` `INACTIVE → MONITORING` and bumping the
    patient's version."
    PRD §3.4: "When an `ACTIVE` device is returned and no remaining device for that
    patient is `ACTIVE`, monitoring pauses as a cross-entity cascade: `monitoring_status`
    moves to `PAUSED`."

    Design: Difficulty/compensating_invariant/device_return_conserves_monitoring_count_invariant
    """
    ctx = setup_enrolled_patient_with_active_device(
        mrn="M-CI2-2", serial_number="SN-CI2-2", consent_type="RPM")
    device = get_success_data(api.get_device(ctx["device"]["id"], CC))
    assert device["status"] == "ACTIVE"
    monitoring_on = get_success_data(api.get_patient(ctx["patient"]["id"], CC))
    assert monitoring_on["monitoring_status"] == "MONITORING"
    api.return_device(ctx["patient"]["id"], ctx["device"]["id"], CC)
    monitoring_off = get_success_data(api.get_patient(ctx["patient"]["id"], CC))
    assert monitoring_off["monitoring_status"] == "PAUSED"
