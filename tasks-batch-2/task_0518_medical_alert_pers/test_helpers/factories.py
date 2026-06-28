"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Optional input fields (with PRD-stated defaults) are omitted
from the defaults so omission behavior can be tested where relevant.
"""
import itertools

# Monotonic counters guaranteeing uniqueness across a fresh DB per test.
_serial_counter = itertools.count(1)
_email_counter = itertools.count(1)


def unique_serial(prefix: str = "SN") -> str:
    return f"{prefix}-{next(_serial_counter)}"


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}{next(_email_counter)}@example.com"


# ---------------------------------------------------------------------------
# MonitoringPlan
# ---------------------------------------------------------------------------
def create_plan_payload(**overrides) -> dict:
    defaults = {
        "tier": "BASIC",
        "monthly_fee_cents": 3000,
        "fall_detection_addon_cents": 0,
        "included_test_interval_days": 30,
        "response_sla_seconds": 60,
        "early_termination_fee_cents": 0,
        "min_commitment_months": 0,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Subscriber
# ---------------------------------------------------------------------------
def create_subscriber_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Subscriber",
        "email": unique_email(),
        "residence_address": "1 Test St",
        "phone": "555-0100",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------
def create_contract_payload(subscriber_id: str, plan_id: str, **overrides) -> dict:
    defaults = {"subscriber_id": subscriber_id, "plan_id": plan_id}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Device  (fall_detection_enabled is optional, default false — omitted)
# ---------------------------------------------------------------------------
def create_device_payload(contract_id: str, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "serial_number": unique_serial(),
        "device_type": "PENDANT",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# DeviceTest
# ---------------------------------------------------------------------------
def create_test_payload(**overrides) -> dict:
    defaults = {"reported_battery_pct": 90, "signal_ok": True}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# EmergencyContact  (escalates_to_contact_id, can_authorize_911 optional)
# ---------------------------------------------------------------------------
def create_contact_payload(subscriber_id: str, priority_rank: int, **overrides) -> dict:
    defaults = {
        "subscriber_id": subscriber_id,
        "name": "Contact",
        "phone": "555-0200",
        "relationship": "CAREGIVER",
        "priority_rank": priority_rank,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# AlarmEvent
# ---------------------------------------------------------------------------
def create_alarm_payload(signal_type: str = "MANUAL_BUTTON", **overrides) -> dict:
    defaults = {"signal_type": signal_type}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# DispatchAction  (target_contact_id optional)
# ---------------------------------------------------------------------------
def create_dispatch_payload(action_type: str, outcome: str, **overrides) -> dict:
    defaults = {"action_type": action_type, "outcome": outcome}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# EquipmentReturn inspect
# ---------------------------------------------------------------------------
def inspect_payload(condition_grade: str, **overrides) -> dict:
    defaults = {"condition_grade": condition_grade}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# AgentShift
# ---------------------------------------------------------------------------
def create_shift_payload(agent_user_id: str, starts_at: str, ends_at: str, **overrides) -> dict:
    defaults = {"agent_user_id": agent_user_id, "starts_at": starts_at, "ends_at": ends_at}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# MonitoringHold
# ---------------------------------------------------------------------------
def create_hold_payload(device_id: str, starts_at: str, ends_at: str, **overrides) -> dict:
    defaults = {"device_id": device_id, "starts_at": starts_at, "ends_at": ends_at}
    defaults.update(overrides)
    return defaults
