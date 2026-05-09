"""
Anomaly cascade tests (PRD §2.8 + §3.6 + §3.2).

The 4-hop chain: ticket creation → Device.status FAULTY → Slot.slot_status
FAULTY → OperatorTask auto-creation, all causally chained as described in
§2.8.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    OPERATOR_HEADERS,
    advance_clock_to,
    api_client,
    heartbeat,
    setup_borrow_environment,
    trigger_anomaly_cascade,
    validate_success,
)


# ---------------------------------------------------------------------------
# anomaly sweep cascade (PRD §3.6 / §2.8)
# ---------------------------------------------------------------------------


def test_anomaly_sweep_marks_device_faulty(api):
    """PRD §2.8: "the targeted Device transitions from AVAILABLE to FAULTY
    (cascade caused by ticket creation)."
    """
    env = trigger_anomaly_cascade()
    device_after = validate_success(
        api.get_device(env["device"]["id"], ADMIN_HEADERS), 200
    )
    assert device_after["status"] == "FAULTY"


def test_anomaly_sweep_marks_slot_faulty(api):
    """PRD §2.8: "the slot housing that device transitions from OCCUPIED to
    FAULTY (cascade caused by the device transition)."
    """
    env = trigger_anomaly_cascade()
    cab = validate_success(api.get_cabinet(env["cabinet"]["id"], ADMIN_HEADERS), 200)
    slot0 = next(s for s in cab["slots"] if s["slot_index"] == 0)
    assert slot0["slot_status"] == "FAULTY"


def test_anomaly_sweep_creates_operator_task(api):
    """PRD §2.8: "an OperatorTask of task_type REPAIR_DISPATCH is auto-created
    for the cabinet, with linked_repair_ticket_id pointing back to the
    originating ticket and priority_score computed at creation."
    """
    env = trigger_anomaly_cascade()
    res = api.auto_assign_task({"city_code": "BJ"}, OPERATOR_HEADERS)
    task = validate_success(res, 200)
    assert task["task_type"] == "REPAIR_DISPATCH"
    assert task["cabinet_id"] == env["cabinet"]["id"]
    assert task["linked_repair_ticket_id"] is not None


def test_anomaly_sweep_creates_open_repair_ticket(api):
    """PRD §3.6: "for each such device the sweep creates a RepairTicket with
    target_type DEVICE, target_id equal to the device's id, source
    AUTO_ANOMALY, issue_code ABNORMAL_BATTERY, and status OPEN."
    """
    env = trigger_anomaly_cascade()
    task = validate_success(
        api.auto_assign_task({"city_code": "BJ"}, OPERATOR_HEADERS), 200
    )
    ticket = validate_success(
        api.get_repair_ticket(task["linked_repair_ticket_id"], OPERATOR_HEADERS),
        200,
    )
    assert ticket["target_type"] == "DEVICE"
    assert ticket["target_id"] == env["device"]["id"]
    assert ticket["source"] == "AUTO_ANOMALY"
    assert ticket["issue_code"] == "ABNORMAL_BATTERY"
    # Note: PRD says ticket starts at OPEN; the auto_assign call above did
    # not touch the ticket (it touched the OperatorTask).
    assert ticket["status"] == "OPEN"


def test_anomaly_sweep_only_targets_battery_below_5(api):
    """PRD §3.6: "walks every device whose status is AVAILABLE, whose
    battery_level is strictly less than 5."

    Test at battery=5 (NOT triggered).
    """
    from test_helpers import (
        create_cabinet,
        create_device,
        create_location_partner,
        setup_pricing_plans,
    )

    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T10:00:00Z")
    device = create_device(cabinet["id"], 0, battery_level=5)
    api.run_sweep({"sweep_type": "anomaly"})
    d_after = validate_success(api.get_device(device["id"], ADMIN_HEADERS), 200)
    # battery=5 is NOT strictly less than 5 → unaffected.
    assert d_after["status"] == "AVAILABLE"


def test_anomaly_sweep_at_battery_4_triggers(api):
    """PRD §3.6: boundary at battery_level < 5 → battery=4 triggers."""
    from test_helpers import (
        create_cabinet,
        create_device,
        create_location_partner,
        setup_pricing_plans,
    )

    setup_pricing_plans(["BJ"])
    partner = create_location_partner()
    cabinet = create_cabinet(partner["id"], city_code="BJ", model="SLOT_8")
    advance_clock_to("2026-01-01T10:00:00Z")
    heartbeat(cabinet["id"], "2026-01-01T10:00:00Z")
    device = create_device(cabinet["id"], 0, battery_level=4)
    api.run_sweep({"sweep_type": "anomaly"})
    d_after = validate_success(api.get_device(device["id"], ADMIN_HEADERS), 200)
    assert d_after["status"] == "FAULTY"


# ---------------------------------------------------------------------------
# user-reported fault on AVAILABLE device fires cascade (PRD §3.2)
# ---------------------------------------------------------------------------


def test_user_report_fault_on_borrowed_device_keeps_borrowed(api):
    """PRD §3.2: "When the device is in BORROWED at the moment of the report,
    the device's status is left untouched."
    """
    env = setup_borrow_environment()
    from test_helpers import borrow_for, make_user_headers

    rental = borrow_for(env["user"], env["cabinet"]["id"])
    api.report_fault(
        rental["device_id"],
        {"issue_code": "PHYSICAL_DAMAGE"},
        make_user_headers(env["user"]["id"]),
    )
    device = validate_success(
        api.get_device(rental["device_id"], ADMIN_HEADERS), 200
    )
    assert device["status"] == "BORROWED"
