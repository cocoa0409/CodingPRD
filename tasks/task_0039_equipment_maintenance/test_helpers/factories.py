"""Payload factories — one per entity, input fields only.

Each factory returns a dict that satisfies PRD §3's body contract for the
corresponding endpoint. Defaults keep tests concise; pass overrides for
fields a test needs to control.
"""
from __future__ import annotations
import time
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_seq_counter = 0


def _seq() -> int:
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def unique_token(prefix: str) -> str:
    """Build a unique-per-invocation string for fields like asset_tag, sku,
    template code, site name."""
    return f"{prefix}-{int(time.time() * 1000) % 10**8}-{_seq()}"


# ---------------------------------------------------------------------------
# Site
# ---------------------------------------------------------------------------
def create_site_payload(**overrides) -> Dict[str, Any]:
    payload = {"name": unique_token("site")}
    payload.update(overrides)
    return payload


def advance_clock_payload(seconds: int = 60) -> Dict[str, Any]:
    return {"seconds": seconds}


# ---------------------------------------------------------------------------
# Equipment
# ---------------------------------------------------------------------------
def create_equipment_payload(
    responsible_user_id: str,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.2: required fields are asset_tag, category, location,
    responsible_user_id, technical_spec, criticality, warranty_start,
    warranty_end. usage_counter is optional."""
    payload: Dict[str, Any] = {
        "asset_tag": unique_token("AT"),
        "category": "PUMP",
        "location": "Bay-A1",
        "responsible_user_id": responsible_user_id,
        "technical_spec": {"model": "PMP-1000", "voltage": 480},
        "criticality": "MEDIUM",
        "warranty_start": "2026-01-01T00:00:00.000Z",
        "warranty_end": "2027-01-01T00:00:00.000Z",
        "usage_counter": 0,
    }
    payload.update(overrides)
    return payload


def patch_equipment_payload(version: int, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"version": version}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TaskTemplate
# ---------------------------------------------------------------------------
def create_template_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.3 lists code, title, equipment_category, required_skill,
    estimated_minutes (>0), default_priority."""
    payload: Dict[str, Any] = {
        "code": unique_token("TPL"),
        "title": "Standard Pump Service",
        "equipment_category": "PUMP",
        "required_skill": "MECHANICAL",
        "estimated_minutes": 120,
        "default_priority": "P3",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# MaintenancePlan
# ---------------------------------------------------------------------------
def create_plan_payload(equipment_id: str, template_id: str,
                        kind: str = "PERIODIC_TIME",
                        **overrides) -> Dict[str, Any]:
    """PRD §3.3: a plan body identifies kind plus the kind-required field(s).
    PERIODIC_TIME → interval_days; PERIODIC_USAGE → interval_usage;
    TRIGGER_ALARM → alarm_code; TRIGGER_THRESHOLD → all of
    threshold_metric/op/value."""
    payload: Dict[str, Any] = {
        "equipment_id": equipment_id,
        "template_id": template_id,
        "kind": kind,
    }
    if kind == "PERIODIC_TIME":
        payload["interval_days"] = 7
    elif kind == "PERIODIC_USAGE":
        payload["interval_usage"] = 100
    elif kind == "TRIGGER_ALARM":
        payload["alarm_code"] = "OVERHEAT"
    elif kind == "TRIGGER_THRESHOLD":
        payload["threshold_metric"] = "VIBRATION"
        payload["threshold_op"] = "GTE"
        payload["threshold_value"] = 5.0
    payload.update(overrides)
    return payload


def patch_plan_payload(version: int, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"version": version}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# SparePart
# ---------------------------------------------------------------------------
def create_spare_part_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.8: sku (unique per site), name, unit_cost_cents (>=0),
    optional initial stock_on_hand (default 0), reorder_point (>=0)."""
    payload: Dict[str, Any] = {
        "sku": unique_token("SKU"),
        "name": "Bearing 25mm",
        "unit_cost_cents": 500,
        "stock_on_hand": 100,
        "reorder_point": 5,
    }
    payload.update(overrides)
    return payload


def patch_spare_part_payload(version: int, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"version": version}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Technician
# ---------------------------------------------------------------------------
def create_technician_payload(skills: Optional[List[str]] = None,
                              **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": unique_token("TECH"),
        "skills": list(skills) if skills is not None else ["MECHANICAL"],
    }
    payload.update(overrides)
    return payload


def patch_technician_payload(version: int, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"version": version}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# WorkOrder
# ---------------------------------------------------------------------------
def create_work_order_payload(equipment_id: str, template_id: str,
                              **overrides) -> Dict[str, Any]:
    """PRD §3.5–§3.6: ad-hoc create body has equipment_id, template_id,
    optional explicit_priority, optional preferred_technician_id."""
    payload: Dict[str, Any] = {
        "equipment_id": equipment_id,
        "template_id": template_id,
    }
    payload.update(overrides)
    return payload


def reassign_payload(new_technician_id: str) -> Dict[str, Any]:
    return {"new_technician_id": new_technician_id}


def pause_payload(pause_reason: str = "WAIT_INFO") -> Dict[str, Any]:
    return {"pause_reason": pause_reason}


def complete_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.6 completion body: fault_description, root_cause,
    repair_actions, working_minutes (>0), before_evidence_url,
    after_evidence_url."""
    payload: Dict[str, Any] = {
        "fault_description": "Bearing wear and audible whine",
        "root_cause": "Lack of lubrication at bearing assembly",
        "repair_actions": "Replaced bearing; cleaned shaft; relubricated",
        "working_minutes": 90,
        "before_evidence_url": "https://photo.example.com/before.jpg",
        "after_evidence_url": "https://photo.example.com/after.jpg",
    }
    payload.update(overrides)
    return payload


def cancel_work_order_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Requisition
# ---------------------------------------------------------------------------
def create_requisition_payload(part_id: str, qty: int = 1,
                               **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"part_id": part_id, "qty": qty}
    payload.update(overrides)
    return payload


def return_requisition_payload(returned_qty: int) -> Dict[str, Any]:
    return {"returned_qty": returned_qty}


# ---------------------------------------------------------------------------
# Alarm event
# ---------------------------------------------------------------------------
def emit_alarm_payload(alarm_code: str = "OVERHEAT",
                       severity: str = "WARN",
                       metric_value: Optional[float] = None,
                       **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "alarm_code": alarm_code,
        "severity": severity,
    }
    if metric_value is not None:
        payload["metric_value"] = metric_value
    payload.update(overrides)
    return payload


__all__ = [
    "unique_token",
    "create_site_payload",
    "advance_clock_payload",
    "create_equipment_payload",
    "patch_equipment_payload",
    "create_template_payload",
    "create_plan_payload",
    "patch_plan_payload",
    "create_spare_part_payload",
    "patch_spare_part_payload",
    "create_technician_payload",
    "patch_technician_payload",
    "create_work_order_payload",
    "reassign_payload",
    "pause_payload",
    "complete_payload",
    "cancel_work_order_payload",
    "create_requisition_payload",
    "return_requisition_payload",
    "emit_alarm_payload",
]
