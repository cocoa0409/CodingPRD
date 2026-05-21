"""Entity → JSON-view serializers.

Centralizes which fields are exposed on read for each entity, and the
field-naming for computed/system-set fields. Common-fields entities
(`Employee`, `Shift`, `TimeEdit`, `TipDeclaration`, `Workweek`) carry
`id`, `created_at`, `updated_at`, `version`. Event records (`Punch`,
`MealBreak`, `DetentionEvent`, `AuditEntry`) carry only `id` and
`created_at` (no version, no updated_at).
"""
from __future__ import annotations

from typing import Any, Dict


def employee_view(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "full_name": row["full_name"],
        "jurisdiction": row["jurisdiction"],
        "classification": row["classification"],
        "base_hourly_rate_cents": row.get("base_hourly_rate_cents"),
        "tipped_role": row.get("tipped_role", False),
        "tipped_cash_rate_cents": row.get("tipped_cash_rate_cents"),
        "applicable_minimum_wage_cents": row.get("applicable_minimum_wage_cents"),
        "status": row["status"],
    }


def shift_view(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "employee_id": row["employee_id"],
        "scheduled_start": row["scheduled_start"],
        "scheduled_end": row["scheduled_end"],
        "actual_start": row.get("actual_start"),
        "actual_end": row.get("actual_end"),
        "state": row["state"],
        "workweek_id": row.get("workweek_id"),
        "requires_meal_break": row.get("requires_meal_break", False),
        "meal_break_premium_owed_cents": row.get("meal_break_premium_owed_cents", 0),
        "detention_minutes": row.get("detention_minutes", 0),
    }


def punch_view(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "shift_id": row["shift_id"],
        "employee_id": row["employee_id"],
        "punch_type": row["punch_type"],
        "punched_at": row["punched_at"],
        "source": row["source"],
        "superseded_by_edit_id": row.get("superseded_by_edit_id"),
    }


def time_edit_view(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "shift_id": row["shift_id"],
        "target_punch_id": row["target_punch_id"],
        "proposed_punched_at": row["proposed_punched_at"],
        "reason_code": row["reason_code"],
        "requested_by_user_id": row["requested_by_user_id"],
        "requested_by_role": row["requested_by_role"],
        "approved_by_user_id": row.get("approved_by_user_id"),
        "state": row["state"],
        "idempotency_key": row["idempotency_key"],
        "applied_at": row.get("applied_at"),
    }


def meal_break_view(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "shift_id": row["shift_id"],
        "meal_out_punch_id": row.get("meal_out_punch_id"),
        "meal_in_punch_id": row.get("meal_in_punch_id"),
        "duration_minutes": row.get("duration_minutes", 0),
        "taken_before_fifth_hour": row.get("taken_before_fifth_hour", False),
    }


def detention_view(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "shift_id": row["shift_id"],
        "minutes_past_scheduled_end": row.get("minutes_past_scheduled_end", 0),
        "premium_owed_cents": row.get("premium_owed_cents", 0),
        "tier": row.get("tier", "NONE"),
    }


def tip_declaration_view(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "shift_id": row["shift_id"],
        "declared_tips_cents": row["declared_tips_cents"],
        "tip_credit_applied_cents": row.get("tip_credit_applied_cents", 0),
        "shortfall_topup_cents": row.get("shortfall_topup_cents", 0),
    }


def workweek_view(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "employee_id": row["employee_id"],
        "week_start": row["week_start"],
        "total_hours": row.get("total_hours", 0),
        "regular_hours": row.get("regular_hours", 0),
        "overtime_hours": row.get("overtime_hours", 0),
        "double_time_hours": row.get("double_time_hours", 0),
        "gross_pay_cents": row.get("gross_pay_cents", 0),
        "payroll_status": row["payroll_status"],
    }


def audit_view(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "actor_user_id": row["actor_user_id"],
        "actor_role": row["actor_role"],
        "action": row["action"],
        "subject_entity": row["subject_entity"],
        "subject_id": row["subject_id"],
        "before_snapshot": row.get("before_snapshot", {}),
        "after_snapshot": row.get("after_snapshot", {}),
    }
