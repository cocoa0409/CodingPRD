"""Entity creation, mutation bookkeeping, and serialization.

Common system fields (PRD 2.4):
  id          UUID, no prefix
  created_at  ISO 8601 UTC, 3 fractional digits, set at creation
  updated_at  refreshed on every mutation
  version     starts at 1, +1 on each mutation

DeviceTest is leaner (PRD 2.4): only id + created_at, no updated_at, no version.
"""
from clock import clock
from db import store, new_id, iso


def now_dt():
    return clock.now()


def new_record(with_common=True):
    """Create a base record dict. Timestamps use the logical clock."""
    n = clock.now()
    rec = {"id": new_id(), "_seq": store.next_seq()}
    rec["created_at_dt"] = n
    if with_common:
        rec["updated_at_dt"] = n
        rec["version"] = 1
    return rec


def touch(rec):
    """Apply a mutation: bump version, refresh updated_at to current clock."""
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at_dt"] = clock.now()


# ---------------------------------------------------------------------------
# Serialization — convert internal records to API JSON.
# Internal datetime fields are stored as *_dt and exposed without the suffix.
# ---------------------------------------------------------------------------
def _base(rec, has_common=True):
    out = {"id": rec["id"], "created_at": iso(rec["created_at_dt"])}
    if has_common:
        out["updated_at"] = iso(rec.get("updated_at_dt"))
        out["version"] = rec["version"]
    return out


def serialize_plan(r):
    out = _base(r)
    out.update({
        "tier": r["tier"],
        "monthly_fee_cents": r["monthly_fee_cents"],
        "fall_detection_addon_cents": r["fall_detection_addon_cents"],
        "included_test_interval_days": r["included_test_interval_days"],
        "response_sla_seconds": r["response_sla_seconds"],
        "early_termination_fee_cents": r["early_termination_fee_cents"],
        "min_commitment_months": r["min_commitment_months"],
        "archived": r["archived"],
    })
    return out


def serialize_subscriber(r):
    out = _base(r)
    out.update({
        "full_name": r["full_name"],
        "email": r["email"],
        "residence_address": r["residence_address"],
        "phone": r["phone"],
        "status": r["status"],
    })
    return out


def serialize_contract(r):
    out = _base(r)
    out.update({
        "subscriber_id": r["subscriber_id"],
        "plan_id": r["plan_id"],
        "pinned_monthly_fee_cents": r.get("pinned_monthly_fee_cents"),
        "pinned_addon_cents": r.get("pinned_addon_cents"),
        "pinned_etf_cents": r.get("pinned_etf_cents"),
        "pinned_min_commitment_months": r.get("pinned_min_commitment_months"),
        "billing_status": r["billing_status"],
        "service_status": r["service_status"],
        "activated_at": iso(r.get("activated_at_dt")),
        "paid_through_at": iso(r.get("paid_through_at_dt")),
        "cancellation_effective_at": iso(r.get("cancellation_effective_at_dt")),
        "refund_cents": r.get("refund_cents", 0),
        "etf_charged_cents": r.get("etf_charged_cents", 0),
        "outstanding_balance_cents": r.get("outstanding_balance_cents", 0),
    })
    return out


def serialize_device(r):
    out = _base(r)
    out.update({
        "contract_id": r["contract_id"],
        "serial_number": r["serial_number"],
        "device_type": r["device_type"],
        "fall_detection_enabled": r["fall_detection_enabled"],
        "status": r["status"],
        "battery_pct": r["battery_pct"],
        "battery_health": r["battery_health"],
        "last_test_at": iso(r.get("last_test_at_dt")),
        "next_test_due_at": iso(r.get("next_test_due_at_dt")),
        "open_alarm_count": r["open_alarm_count"],
    })
    return out


def serialize_contact(r):
    out = _base(r)
    out.update({
        "subscriber_id": r["subscriber_id"],
        "name": r["name"],
        "phone": r["phone"],
        "relationship": r["relationship"],
        "priority_rank": r["priority_rank"],
        "escalates_to_contact_id": r.get("escalates_to_contact_id"),
        "can_authorize_911": r["can_authorize_911"],
        "active": r["active"],
    })
    return out


def serialize_alarm(r):
    out = _base(r)
    out.update({
        "device_id": r["device_id"],
        "assigned_agent_id": r.get("assigned_agent_id"),
        "signal_type": r["signal_type"],
        "priority": r["priority"],
        "status": r["status"],
        "signal_received_at": iso(r.get("signal_received_at_dt")),
        "agent_assigned_at": iso(r.get("agent_assigned_at_dt")),
        "resolved_at": iso(r.get("resolved_at_dt")),
        "sla_breached": r["sla_breached"],
        "current_escalation_rank": r["current_escalation_rank"],
        "dispatch_count": r["dispatch_count"],
    })
    return out


def serialize_dispatch(r):
    out = _base(r)
    out.update({
        "alarm_event_id": r["alarm_event_id"],
        "action_type": r["action_type"],
        "target_contact_id": r.get("target_contact_id"),
        "outcome": r["outcome"],
        "recorded_at": iso(r.get("recorded_at_dt")),
    })
    return out


def serialize_device_test(r):
    # leaner: only id + created_at (PRD 2.4)
    out = _base(r, has_common=False)
    out.update({
        "device_id": r["device_id"],
        "reported_battery_pct": r["reported_battery_pct"],
        "signal_ok": r["signal_ok"],
        "result": r["result"],
        "tested_at": iso(r.get("tested_at_dt")),
    })
    return out


def serialize_equipment_return(r):
    out = _base(r)
    out.update({
        "contract_id": r["contract_id"],
        "device_id": r["device_id"],
        "status": r["status"],
        "condition_grade": r.get("condition_grade"),
        "damage_fee_cents": r.get("damage_fee_cents", 0),
        "due_back_at": iso(r.get("due_back_at_dt")),
        "received_at": iso(r.get("received_at_dt")),
    })
    return out


def serialize_agent_shift(r):
    out = _base(r)
    out.update({
        "agent_user_id": r["agent_user_id"],
        "starts_at": iso(r.get("starts_at_dt")),
        "ends_at": iso(r.get("ends_at_dt")),
        "status": r["status"],
    })
    return out


def serialize_monitoring_hold(r):
    out = _base(r)
    out.update({
        "device_id": r["device_id"],
        "starts_at": iso(r.get("starts_at_dt")),
        "ends_at": iso(r.get("ends_at_dt")),
        "status": r["status"],
    })
    return out
