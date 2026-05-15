"""InspectionCase service + outcome cascade."""
from __future__ import annotations

from typing import Any

from ..audit import emit_audit
from ..auth import current_actor
from ..clock import now_dt, now_iso_ms, parse_iso
from ..constants import INSPECTION_OUTCOMES
from ..errors import ApiError
from ..store import bump_version, common_fields_create, get_store
from .validation import (
    ensure_bool,
    ensure_enum,
    ensure_non_negative_number,
    ensure_string,
    occ_check,
)


def create_inspection_case(body: dict[str, Any]) -> dict[str, Any]:
    filing_id = ensure_string(body.get("filing_id"), "filing_id", 1, 200)
    store = get_store()
    filing = store.filings.get(filing_id)
    if not filing:
        raise ApiError("ERR_NOT_FOUND", f"Filing {filing_id!r} not found.")
    if filing.get("response_type") != "INSPECT":
        raise ApiError(
            "ERR_INVALID_STATE",
            "InspectionCase can only be created for filings with response_type=INSPECT.",
        )

    warehouse_code = ensure_string(body.get("warehouse_code"), "warehouse_code", 1, 40)
    scheduled_at_raw = body.get("scheduled_at")
    if not isinstance(scheduled_at_raw, str):
        raise ApiError("ERR_INVALID_INPUT", "scheduled_at is required.")
    try:
        parse_iso(scheduled_at_raw)
    except ValueError as exc:
        raise ApiError("ERR_INVALID_INPUT", f"Invalid scheduled_at: {exc}")

    sample_required = body.get("sample_required", False)
    if not isinstance(sample_required, bool):
        raise ApiError("ERR_INVALID_INPUT", "sample_required must be boolean.")

    record = common_fields_create()
    record.update(
        {
            "filing_id": filing_id,
            "warehouse_code": warehouse_code,
            "scheduled_at": scheduled_at_raw,
            "sample_required": sample_required,
            "sample_provided_at": None,
            "outcome": "PENDING",
            "penalty_amount": 0,
            "post_inspection_doc_uri": None,
        }
    )
    store.inspection_cases[record["id"]] = record
    return record


def get_inspection_case(inspection_case_id: str) -> dict[str, Any]:
    ic = get_store().inspection_cases.get(inspection_case_id)
    if not ic:
        raise ApiError("ERR_NOT_FOUND", f"InspectionCase {inspection_case_id!r} not found.")
    return ic


def provide_sample(inspection_case_id: str, body: dict[str, Any]) -> dict[str, Any]:
    ic = get_inspection_case(inspection_case_id)
    occ_check(ic, body.get("version"))
    if ic.get("outcome") != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "InspectionCase must be PENDING.")

    # ClientUser ownership check
    user_id, role = current_actor()
    if role == "ClientUser":
        store = get_store()
        filing = store.filings.get(ic.get("filing_id"))
        declaration = (
            store.declarations.get(filing.get("declaration_id")) if filing else None
        )
        agreement = (
            store.agreements.get(declaration.get("agreement_id")) if declaration else None
        )
        if not agreement or agreement.get("client_id") != user_id:
            raise ApiError("ERR_FORBIDDEN", "ClientUser can only act on their own cases.")

    ic["sample_provided_at"] = now_iso_ms()
    bump_version(ic)
    return ic


def record_outcome(inspection_case_id: str, body: dict[str, Any]) -> dict[str, Any]:
    from .settlements import cascade_create_settlement

    ic = get_inspection_case(inspection_case_id)
    occ_check(ic, body.get("version"))
    if ic.get("outcome") != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "InspectionCase already has an outcome.")

    outcome = ensure_enum(body.get("outcome"), "outcome", INSPECTION_OUTCOMES)
    post_uri = ensure_string(
        body.get("post_inspection_doc_uri"), "post_inspection_doc_uri", 1, 500
    )
    penalty_amount = body.get("penalty_amount", 0)
    if outcome == "PENALTY":
        if isinstance(penalty_amount, bool) or not isinstance(penalty_amount, (int, float)):
            raise ApiError("ERR_INVALID_INPUT", "penalty_amount must be a number when PENALTY.")
        if penalty_amount <= 0:
            raise ApiError("ERR_INVALID_INPUT", "penalty_amount must be > 0 for PENALTY.")
    else:
        penalty_amount = 0

    # Preconditions
    if now_dt() < parse_iso(ic["scheduled_at"]):
        raise ApiError("ERR_INVALID_STATE", "Cannot record outcome before scheduled_at.")
    if ic.get("sample_required") and not ic.get("sample_provided_at"):
        raise ApiError("ERR_INVALID_STATE", "Sample required but not provided.")

    store = get_store()
    filing = store.filings.get(ic["filing_id"])
    if not filing:
        raise ApiError("ERR_NOT_FOUND", "Parent Filing not found.")
    declaration = store.declarations.get(filing["declaration_id"])
    if not declaration:
        raise ApiError("ERR_NOT_FOUND", "Parent Declaration not found.")
    if declaration.get("status") != "INSPECTING":
        raise ApiError(
            "ERR_INVALID_STATE",
            f"Declaration not INSPECTING (got {declaration.get('status')!r}).",
        )

    user_id, role = current_actor()

    # Apply
    ic["outcome"] = outcome
    ic["penalty_amount"] = float(penalty_amount) if outcome == "PENALTY" else 0
    ic["post_inspection_doc_uri"] = post_uri
    bump_version(ic)

    prev_decl_status = declaration["status"]
    if outcome == "RELEASE":
        declaration["status"] = "RELEASED"
        bump_version(declaration)
        emit_audit(
            "DECLARATION",
            declaration["id"],
            "STATE_TRANSITION",
            role,
            user_id,
            {"from": prev_decl_status, "to": "RELEASED"},
        )
        emit_audit(
            "INSPECTION_CASE",
            ic["id"],
            "STATE_TRANSITION",
            role,
            user_id,
            {"from": "PENDING", "to": "RELEASE"},
        )
        # Cascade: settlement with penalty=0
        cascade_create_settlement(declaration, penalty_in_declared=0)
    else:
        # DETENTION or PENALTY → REJECTED
        declaration["status"] = "REJECTED"
        declaration["rejection_reason_code"] = "INSPECTION_FAILED"
        bump_version(declaration)
        emit_audit(
            "DECLARATION",
            declaration["id"],
            "STATE_TRANSITION",
            role,
            user_id,
            {"from": prev_decl_status, "to": "REJECTED"},
        )
        emit_audit(
            "INSPECTION_CASE",
            ic["id"],
            "STATE_TRANSITION",
            role,
            user_id,
            {"from": "PENDING", "to": outcome},
        )
        # Create RejectionRecord
        from ..store import common_fields_append_only

        rr = common_fields_append_only()
        rr.update(
            {
                "declaration_id": declaration["id"],
                "rejection_reason_code": "INSPECTION_FAILED",
                "archived_at": now_iso_ms(),
                "free_text_note": body.get("free_text_note"),
                "prior_amendment_count": int(declaration.get("amendment_count", 0) or 0),
            }
        )
        store.rejection_records[rr["id"]] = rr

        if outcome == "PENALTY":
            cascade_create_settlement(
                declaration, penalty_in_declared=float(penalty_amount)
            )
    return ic
