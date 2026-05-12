"""Per-entity assertions and domain invariant checkers.

Each assert_<entity> validates the response shape against PRD §2.4 (common
fields) plus the per-entity field set listed in PRD §3.
"""
from __future__ import annotations
from typing import Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    ALARM_SEVERITIES,
    AUDIT_ACTIONS,
    EQUIPMENT_CATEGORIES,
    EQUIPMENT_CRITICALITIES,
    PAUSE_REASONS,
    PLAN_KINDS,
    PLAN_STATUSES,
    REQUISITION_STATUSES,
    TECHNICIAN_STATUSES,
    TEMPLATE_PRIORITIES,
    TEMPLATE_SKILLS,
    THRESHOLD_OPS,
    WORK_ORDER_SOURCES,
    WORK_ORDER_STATUSES,
)


# ---------------------------------------------------------------------------
# Common-field helpers (PRD §2.4)
# ---------------------------------------------------------------------------
def _assert_common_full(data: dict, label: str) -> None:
    """Common quartet for entities that carry id, created_at, updated_at,
    version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{label}.version must be int >= 1"


def _assert_common_append_only(data: dict, label: str) -> None:
    """Append-only entities carry only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be ISO 8601"


# ---------------------------------------------------------------------------
# Site (common-fields)
# ---------------------------------------------------------------------------
def assert_site(data: dict) -> None:
    _assert_common_full(data, "Site")
    assert isinstance(data.get("name"), str) and data["name"]
    assert is_iso8601_timestamp(data.get("clock_now", "")), \
        "Site.clock_now must be ISO 8601"
    assert isinstance(data.get("sweep_run_index"), int) \
        and data["sweep_run_index"] >= 0


# ---------------------------------------------------------------------------
# Equipment (common-fields)
# ---------------------------------------------------------------------------
def assert_equipment(data: dict) -> None:
    _assert_common_full(data, "Equipment")
    assert isinstance(data.get("site_id"), str) and is_valid_uuid(data["site_id"])
    assert isinstance(data.get("asset_tag"), str) and data["asset_tag"]
    assert data.get("category") in EQUIPMENT_CATEGORIES
    assert data.get("criticality") in EQUIPMENT_CRITICALITIES
    assert isinstance(data.get("location"), str)
    assert isinstance(data.get("responsible_user_id"), str) \
        and data["responsible_user_id"]
    assert isinstance(data.get("technical_spec"), dict)
    assert is_iso8601_timestamp(data.get("warranty_start", ""))
    assert is_iso8601_timestamp(data.get("warranty_end", ""))
    assert isinstance(data.get("usage_counter"), int) and data["usage_counter"] >= 0
    assert data.get("lifecycle_status") in {
        "INSTALLED", "COMMISSIONED", "IN_SERVICE", "UNDER_MAINTENANCE",
        "DECOMMISSIONED",
    }
    # last_failure_at, last_repair_completed_at, open_work_order_id may be null


# ---------------------------------------------------------------------------
# TaskTemplate (append-only — no updated_at, no version per PRD §2.4)
# ---------------------------------------------------------------------------
def assert_task_template(data: dict) -> None:
    _assert_common_append_only(data, "TaskTemplate")
    assert isinstance(data.get("code"), str) and data["code"]
    assert isinstance(data.get("title"), str) and data["title"]
    assert data.get("equipment_category") in EQUIPMENT_CATEGORIES
    assert data.get("required_skill") in TEMPLATE_SKILLS
    assert isinstance(data.get("estimated_minutes"), int) \
        and data["estimated_minutes"] > 0
    assert data.get("default_priority") in TEMPLATE_PRIORITIES
    # No updated_at, no version (PRD §2.4)
    assert "updated_at" not in data, \
        "PRD §2.4: TaskTemplate has no updated_at"
    assert "version" not in data, "PRD §2.4: TaskTemplate has no version"


# ---------------------------------------------------------------------------
# MaintenancePlan (common-fields)
# ---------------------------------------------------------------------------
def assert_maintenance_plan(data: dict) -> None:
    _assert_common_full(data, "MaintenancePlan")
    assert isinstance(data.get("equipment_id"), str) \
        and is_valid_uuid(data["equipment_id"])
    assert isinstance(data.get("template_id"), str) \
        and is_valid_uuid(data["template_id"])
    assert data.get("kind") in PLAN_KINDS
    assert data.get("status") in PLAN_STATUSES


# ---------------------------------------------------------------------------
# SparePart (common-fields)
# ---------------------------------------------------------------------------
def assert_spare_part(data: dict) -> None:
    _assert_common_full(data, "SparePart")
    assert isinstance(data.get("sku"), str) and data["sku"]
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("unit_cost_cents"), int) \
        and data["unit_cost_cents"] >= 0
    assert isinstance(data.get("stock_on_hand"), int) \
        and data["stock_on_hand"] >= 0
    assert isinstance(data.get("stock_reserved"), int) \
        and data["stock_reserved"] >= 0
    assert isinstance(data.get("reorder_point"), int) \
        and data["reorder_point"] >= 0
    assert isinstance(data.get("replenish_pending"), bool)
    # Domain invariant: stock_reserved is between 0 and stock_on_hand (PRD §3.8)
    assert data["stock_reserved"] <= data["stock_on_hand"], \
        "PRD §3.8 invariant: stock_reserved must be in [0, stock_on_hand]"


# ---------------------------------------------------------------------------
# Technician (common-fields)
# ---------------------------------------------------------------------------
def assert_technician(data: dict) -> None:
    _assert_common_full(data, "Technician")
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("skills"), list) \
        and all(s in TEMPLATE_SKILLS for s in data["skills"])
    assert data.get("status") in TECHNICIAN_STATUSES
    assert isinstance(data.get("open_load"), int) and data["open_load"] >= 0


# ---------------------------------------------------------------------------
# WorkOrder (common-fields)
# ---------------------------------------------------------------------------
def assert_work_order(data: dict) -> None:
    _assert_common_full(data, "WorkOrder")
    assert isinstance(data.get("equipment_id"), str)
    assert isinstance(data.get("template_id"), str)
    assert data.get("source") in WORK_ORDER_SOURCES
    assert data.get("status") in WORK_ORDER_STATUSES
    assert data.get("priority") in TEMPLATE_PRIORITIES
    assert isinstance(data.get("priority_score"), int)
    assert data.get("required_skill") in TEMPLATE_SKILLS
    assert isinstance(data.get("estimated_minutes"), int) \
        and data["estimated_minutes"] > 0
    assert is_iso8601_timestamp(data.get("opened_at", ""))
    assert is_iso8601_timestamp(data.get("sla_due_at", ""))
    assert isinstance(data.get("sla_breached"), bool)
    assert isinstance(data.get("total_active_minutes"), int) \
        and data["total_active_minutes"] >= 0
    assert isinstance(data.get("reassign_count"), int) \
        and data["reassign_count"] >= 0
    pr = data.get("pause_reason")
    if pr is not None:
        assert pr in PAUSE_REASONS


# ---------------------------------------------------------------------------
# Requisition (common-fields)
# ---------------------------------------------------------------------------
def assert_requisition(data: dict) -> None:
    _assert_common_full(data, "Requisition")
    assert isinstance(data.get("work_order_id"), str)
    assert isinstance(data.get("part_id"), str)
    assert isinstance(data.get("qty"), int) and data["qty"] > 0
    assert data.get("status") in REQUISITION_STATUSES
    assert isinstance(data.get("returned_qty"), int) \
        and 0 <= data["returned_qty"] <= data["qty"]


# ---------------------------------------------------------------------------
# RepairRecord (append-only)
# ---------------------------------------------------------------------------
def assert_repair_record(data: dict) -> None:
    _assert_common_append_only(data, "RepairRecord")
    assert isinstance(data.get("work_order_id"), str)
    assert isinstance(data.get("fault_description"), str)
    assert isinstance(data.get("root_cause"), str)
    assert isinstance(data.get("repair_actions"), str)
    assert isinstance(data.get("working_minutes"), int) \
        and data["working_minutes"] > 0
    assert isinstance(data.get("before_evidence_url"), str)
    assert isinstance(data.get("after_evidence_url"), str)
    assert isinstance(data.get("parts_replaced"), list)
    assert "updated_at" not in data, \
        "PRD §2.4: RepairRecord has no updated_at"
    assert "version" not in data, "PRD §2.4: RepairRecord has no version"


# ---------------------------------------------------------------------------
# AlarmEvent (append-only)
# ---------------------------------------------------------------------------
def assert_alarm_event(data: dict) -> None:
    _assert_common_append_only(data, "AlarmEvent")
    assert isinstance(data.get("equipment_id"), str)
    assert isinstance(data.get("alarm_code"), str) and data["alarm_code"]
    assert data.get("severity") in ALARM_SEVERITIES
    assert is_iso8601_timestamp(data.get("emitted_at", ""))
    assert "updated_at" not in data, \
        "PRD §2.4: AlarmEvent has no updated_at"
    assert "version" not in data, "PRD §2.4: AlarmEvent has no version"


# ---------------------------------------------------------------------------
# AuditEntry (append-only)
# ---------------------------------------------------------------------------
def assert_audit_entry(data: dict) -> None:
    _assert_common_append_only(data, "AuditEntry")
    assert isinstance(data.get("actor_role"), str) and data["actor_role"]
    assert isinstance(data.get("actor_user_id"), str)
    assert data.get("action") in AUDIT_ACTIONS
    assert isinstance(data.get("target_id"), str)
    assert isinstance(data.get("from_value"), str)
    assert isinstance(data.get("to_value"), str)
    assert is_iso8601_timestamp(data.get("occurred_at", ""))
    assert "updated_at" not in data, \
        "PRD §2.4: AuditEntry has no updated_at"
    assert "version" not in data, "PRD §2.4: AuditEntry has no version"


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------
def find_audit_entries(audit_list: Iterable[dict],
                       action: Optional[str] = None,
                       target_id: Optional[str] = None) -> List[dict]:
    """Filter audit entries by action and/or target_id."""
    out: List[dict] = []
    for entry in audit_list:
        if action is not None and entry.get("action") != action:
            continue
        if target_id is not None and entry.get("target_id") != target_id:
            continue
        out.append(entry)
    return out


def find_part_replaced(parts_replaced: Iterable[dict],
                       requisition_id: str) -> Optional[dict]:
    """Look up a parts_replaced row by its requisition_id."""
    for row in parts_replaced:
        if row.get("requisition_id") == requisition_id:
            return row
    return None


__all__ = [
    "assert_site",
    "assert_equipment",
    "assert_task_template",
    "assert_maintenance_plan",
    "assert_spare_part",
    "assert_technician",
    "assert_work_order",
    "assert_requisition",
    "assert_repair_record",
    "assert_alarm_event",
    "assert_audit_entry",
    "find_audit_entries",
    "find_part_replaced",
]
