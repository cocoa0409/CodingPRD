"""Entity -> public JSON serializers.

Each function returns the externally visible field set for one entity, drawn
from SCAFFOLD §1.1. Internal bookkeeping fields (anything prefixed with `_`)
are stripped. Records already carry the system-managed common fields
(id, created_at, updated_at, version) which are emitted verbatim — except for
MeterReading, which carries only id + created_at (PRD §2.4).
"""

_COMMON = ("id", "created_at", "updated_at", "version")


def _pick(rec, fields):
    out = {}
    for f in fields:
        if f in rec:
            out[f] = rec[f]
    return out


def site(rec):
    return _pick(rec, _COMMON + (
        "name", "timezone", "maintenance_budget_cents", "budget_spent_cents",
    ))


def spare_part(rec):
    return _pick(rec, _COMMON + (
        "sku", "name", "on_hand_qty", "reserved_qty", "unit_cost_cents",
        "reorder_point",
    ))


def technician(rec):
    return _pick(rec, _COMMON + (
        "name", "skill_level", "weekly_capacity_hours", "backlog_hours",
    ))


def asset(rec):
    return _pick(rec, _COMMON + (
        "site_id", "parent_asset_id", "name", "criticality", "status",
        "meter_unit", "meter_reading", "warranty_expires_at",
        "warranty_cost_cap_cents", "acquisition_cost_cents",
        "mtbf_hours", "mttr_hours",
    ))


def pm_schedule(rec):
    return _pick(rec, _COMMON + (
        "asset_id", "trigger_type", "meter_interval", "calendar_interval_days",
        "estimated_labor_hours", "severity", "anchor_meter", "anchor_date",
        "next_due_meter", "next_due_date", "active",
    ))


def meter_reading(rec):
    # PRD §2.4: only id + created_at (no updated_at/version).
    return _pick(rec, ("id", "created_at") + (
        "asset_id", "value", "reading_at", "triggered_pm",
    ))


def work_order(rec):
    return _pick(rec, _COMMON + (
        "asset_id", "pm_schedule_id", "assigned_technician_id", "wo_type",
        "severity", "execution_status", "parts_status", "priority_score",
        "estimated_labor_hours", "actual_cost_cents", "warranty_claim_id",
        "opened_at", "closed_at", "scheduled_start", "scheduled_end",
    ))


def part_reservation(rec):
    return _pick(rec, _COMMON + (
        "work_order_id", "spare_part_id", "qty", "status",
        "committed_cost_cents",
    ))


def downtime_event(rec):
    return _pick(rec, _COMMON + (
        "asset_id", "work_order_id", "reason_code", "started_at", "ended_at",
        "status", "duration_hours",
    ))


def warranty_claim(rec):
    return _pick(rec, _COMMON + (
        "asset_id", "work_order_id", "claim_type", "claimed_cost_cents",
        "payable_cost_cents", "status", "decision_reason",
    ))
