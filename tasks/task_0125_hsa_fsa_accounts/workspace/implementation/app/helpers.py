"""Serializers + small validation helpers shared across routes."""
from __future__ import annotations

from typing import Any

from flask import request

from .clock import format_iso, parse_iso
from .errors import ApiError


# ----- Body parsing ----- #

def get_json_body(allow_empty: bool = True) -> dict:
    """Parse the request body as JSON. Empty body returns {} when allow_empty."""
    if request.content_length in (None, 0):
        if allow_empty:
            return {}
        raise ApiError("ERR_BAD_REQUEST", "Request body required.")
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_BAD_REQUEST", "Malformed JSON body.")
    if data is None:
        if allow_empty:
            return {}
        raise ApiError("ERR_BAD_REQUEST", "Request body required.")
    if not isinstance(data, dict):
        raise ApiError("ERR_BAD_REQUEST", "JSON body must be an object.")
    return data


def require_fields(body: dict, fields: list[str]) -> None:
    missing = [f for f in fields if body.get(f) is None]
    if missing:
        raise ApiError("ERR_BAD_REQUEST", f"Missing required field(s): {', '.join(missing)}.")


def require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ApiError("ERR_BAD_REQUEST", f"Field '{name}' must be a non-empty string.")
    return value


def require_enum(value: Any, allowed: set[str], name: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ApiError("ERR_BAD_REQUEST", f"Field '{name}' must be one of: {sorted(allowed)}.")
    return value


def require_positive_int(value: Any, name: str, min_value: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_BAD_REQUEST", f"Field '{name}' must be an integer.")
    if value < min_value:
        raise ApiError("ERR_BAD_REQUEST", f"Field '{name}' must be >= {min_value}.")
    return value


def parse_iso_field(value: Any, name: str):
    try:
        return parse_iso(value)
    except ValueError:
        raise ApiError("ERR_BAD_REQUEST", f"Field '{name}' must be a valid ISO 8601 datetime.")


# ----- Serializers ----- #

def _common_meta(row: dict) -> dict:
    """Common system-managed fields (id, created_at, updated_at, version)."""
    out = {"id": row["id"]}
    if "created_at" in row:
        out["created_at"] = format_iso(row["created_at"]) if not isinstance(row["created_at"], str) else row["created_at"]
    if "updated_at" in row:
        out["updated_at"] = format_iso(row["updated_at"]) if not isinstance(row["updated_at"], str) else row["updated_at"]
    if "version" in row:
        out["version"] = row["version"]
    return out


def serialize_account_holder(row: dict) -> dict:
    return {
        **_common_meta(row),
        "full_name": row["full_name"],
        "ssn_last4": row["ssn_last4"],
        "tax_filing_status": row["tax_filing_status"],
        "birth_date": format_iso(row["birth_date"]),
    }


def serialize_dependent(row: dict) -> dict:
    return {
        **_common_meta(row),
        "account_holder_id": row["account_holder_id"],
        "full_name": row["full_name"],
        "birth_date": format_iso(row["birth_date"]),
        "relationship": row["relationship"],
        "status": row["status"],
    }


def serialize_account(row: dict) -> dict:
    return {
        **_common_meta(row),
        "account_holder_id": row["account_holder_id"],
        "account_type": row["account_type"],
        "coverage_tier": row.get("coverage_tier"),
        "account_holder_birth_date": format_iso(row["account_holder_birth_date"]),
        "year_end_policy": row["year_end_policy"],
        "status": row["status"],
        "closed_at": format_iso(row["closed_at"]) if row.get("closed_at") else None,
    }


def serialize_plan_year(row: dict) -> dict:
    grace = row.get("grace_period_end_date")
    return {
        **_common_meta(row),
        "account_id": row["account_id"],
        "calendar_year": row["calendar_year"],
        "status": row["status"],
        "contribution_cap_cents": row["contribution_cap_cents"],
        "catch_up_cap_cents": row["catch_up_cap_cents"],
        "contributions_ytd_cents": row["contributions_ytd_cents"],
        "claims_paid_ytd_cents": row["claims_paid_ytd_cents"],
        "provisional_balance_cents": row["provisional_balance_cents"],
        "carryover_in_cents": row["carryover_in_cents"],
        "carryover_consumed_cents": row["carryover_consumed_cents"],
        "forfeited_cents": row["forfeited_cents"],
        "grace_period_end_date": format_iso(grace) if grace else None,
    }


def serialize_contribution(row: dict) -> dict:
    return {
        "id": row["id"],
        "created_at": format_iso(row["created_at"]),
        "plan_year_id": row["plan_year_id"],
        "amount_cents": row["amount_cents"],
        "source": row["source"],
        "posted_at": format_iso(row["posted_at"]) if row.get("posted_at") else None,
        "status": row["status"],
        "reversal_of_id": row.get("reversal_of_id"),
    }


def serialize_qualified_expense(row: dict) -> dict:
    return {
        "id": row["id"],
        "created_at": format_iso(row["created_at"]),
        "code": row["code"],
        "category": row["category"],
        "eligible_account_types": list(row["eligible_account_types"]),
        "requires_dependent": row["requires_dependent"],
    }


def serialize_claim(row: dict) -> dict:
    return {
        **_common_meta(row),
        "account_id": row["account_id"],
        "plan_year_id": row.get("plan_year_id"),
        "service_date": format_iso(row["service_date"]),
        "expense_code": row["expense_code"],
        "amount_cents": row["amount_cents"],
        "dependent_id": row.get("dependent_id"),
        "status": row["status"],
        "denial_reason": row.get("denial_reason"),
        "paid_amount_cents": row.get("paid_amount_cents"),
        "reversed_from_id": row.get("reversed_from_id"),
    }


def serialize_audit_event(row: dict) -> dict:
    return {
        "id": row["id"],
        # PRD §2.0: AuditEvent (append-only) carries id and created_at.
        "created_at": format_iso(row.get("created_at", row["occurred_at"])),
        "account_id": row.get("account_id"),
        "plan_year_id": row.get("plan_year_id"),
        "event_type": row["event_type"],
        "subject_entity": row["subject_entity"],
        "subject_id": row["subject_id"],
        "actor_role": row["actor_role"],
        "actor_user_id": row["actor_user_id"],
        "cents_delta": row["cents_delta"],
        "ops_run_index": row.get("ops_run_index"),
        "occurred_at": format_iso(row["occurred_at"]),
    }


def serialize_ops_run(row: dict) -> dict:
    return {
        "id": row["id"],
        "created_at": format_iso(row["created_at"]),
        "index": row["index"],
        "as_of_date": format_iso(row["as_of_date"]),
        "kind": row["kind"],
        "plan_years_affected": list(row["plan_years_affected"]),
        "total_forfeited_cents": row["total_forfeited_cents"],
    }


# ----- Sorting helpers ----- #

def sort_key_created_then_id(row: dict):
    """Primary sort by (created_at, id). Both ascending."""
    ts = row.get("created_at")
    return (ts.timestamp() if hasattr(ts, "timestamp") else 0, row["id"])
