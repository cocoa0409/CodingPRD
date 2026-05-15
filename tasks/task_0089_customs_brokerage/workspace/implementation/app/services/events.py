"""External event handler for POST /customs/_events/emit (PRD §2.12)."""
from __future__ import annotations

from typing import Any

from ..audit import emit_audit
from ..auth import current_actor
from ..clock import add_hours, format_iso, now_dt, now_iso_ms
from ..errors import ApiError
from ..store import bump_version, common_fields_append_only, get_store
from .settlements import cascade_create_settlement, process_bank_debit


VALID_SOURCE_SYSTEMS = {"SINGLE_WINDOW", "INSPECTION_QUARANTINE", "BANK", "LOGISTICS"}
VALID_EVENT_TYPES = {
    "CUSTOMS_RESPONSE",
    "MANIFEST_DROPPED",
    "INSPECTION_NOTICE",
    "BANK_DEBIT_CONFIRMED",
    "RETURN_SHIPMENT_DISPATCHED",
}
VALID_TARGET_ENTITY_TYPES = {"FILING", "DECLARATION", "SETTLEMENT", "INSPECTION_CASE"}
VALID_RESPONSE_TYPES = {"QUERY", "INSPECT", "RELEASE", "REJECT"}


def emit_event(body: dict[str, Any]) -> dict[str, Any]:
    source_system = body.get("source_system")
    event_type = body.get("event_type")
    target_entity_type = body.get("target_entity_type")
    target_entity_id = body.get("target_entity_id")
    payload = body.get("payload") or {}

    if source_system not in VALID_SOURCE_SYSTEMS:
        raise ApiError("ERR_INVALID_INPUT", f"Invalid source_system: {source_system!r}.")
    if event_type not in VALID_EVENT_TYPES:
        raise ApiError("ERR_INVALID_INPUT", f"Invalid event_type: {event_type!r}.")
    if target_entity_type not in VALID_TARGET_ENTITY_TYPES:
        raise ApiError(
            "ERR_INVALID_INPUT", f"Invalid target_entity_type: {target_entity_type!r}."
        )
    if not isinstance(target_entity_id, str) or not target_entity_id:
        raise ApiError("ERR_INVALID_INPUT", "target_entity_id is required.")
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_INPUT", "payload must be an object.")

    store = get_store()

    # Existence check (priority 21)
    if target_entity_type == "FILING" and target_entity_id not in store.filings:
        raise ApiError("ERR_NOT_FOUND", f"Filing {target_entity_id!r} not found.")
    if target_entity_type == "DECLARATION" and target_entity_id not in store.declarations:
        raise ApiError("ERR_NOT_FOUND", f"Declaration {target_entity_id!r} not found.")
    if target_entity_type == "SETTLEMENT" and target_entity_id not in store.settlements:
        raise ApiError("ERR_NOT_FOUND", f"Settlement {target_entity_id!r} not found.")
    if (
        target_entity_type == "INSPECTION_CASE"
        and target_entity_id not in store.inspection_cases
    ):
        raise ApiError(
            "ERR_NOT_FOUND", f"InspectionCase {target_entity_id!r} not found."
        )

    # Dispatch
    if event_type == "CUSTOMS_RESPONSE":
        _handle_customs_response(target_entity_type, target_entity_id, payload)
    elif event_type == "MANIFEST_DROPPED":
        _handle_manifest_dropped(target_entity_type, target_entity_id, payload)
    elif event_type == "BANK_DEBIT_CONFIRMED":
        _handle_bank_debit(target_entity_type, target_entity_id, payload)
    elif event_type == "INSPECTION_NOTICE":
        # passive — record only
        pass
    elif event_type == "RETURN_SHIPMENT_DISPATCHED":
        pass

    # Record ExternalEvent row
    ev = common_fields_append_only()
    ev.update(
        {
            "source_system": source_system,
            "event_type": event_type,
            "target_entity_type": target_entity_type,
            "target_entity_id": target_entity_id,
            "payload": payload,
            "processed_at": now_iso_ms(),
        }
    )
    store.external_events[ev["id"]] = ev
    return ev


def _handle_customs_response(
    target_entity_type: str, target_entity_id: str, payload: dict[str, Any]
) -> None:
    store = get_store()
    if target_entity_type not in {"FILING", "DECLARATION"}:
        raise ApiError(
            "ERR_INVALID_INPUT",
            "CUSTOMS_RESPONSE must target FILING or DECLARATION.",
        )

    if target_entity_type == "FILING":
        filing = store.filings.get(target_entity_id)
        declaration = store.declarations.get(filing.get("declaration_id")) if filing else None
    else:
        declaration = store.declarations.get(target_entity_id)
        filing = _latest_filing_for_declaration(target_entity_id)
    if filing is None:
        raise ApiError("ERR_NOT_FOUND", "Filing not found for customs response.")
    if declaration is None:
        raise ApiError("ERR_NOT_FOUND", "Declaration not found.")

    response_type = payload.get("response_type")
    if response_type not in VALID_RESPONSE_TYPES:
        raise ApiError(
            "ERR_INVALID_INPUT",
            f"payload.response_type must be one of {sorted(VALID_RESPONSE_TYPES)}.",
        )

    if filing.get("response_type") != "AWAITING":
        raise ApiError("ERR_INVALID_STATE", "Filing.response_type is not AWAITING.")

    user_id = "system"
    actor_role = "system"
    prev_decl_status = declaration["status"]

    if response_type == "QUERY":
        filing["response_type"] = "QUERY"
        filing["response_received_at"] = now_iso_ms()
        filing["query_due_at"] = format_iso(add_hours(now_dt(), 48))
        bump_version(filing)
        if declaration.get("status") != "FILED":
            raise ApiError("ERR_INVALID_STATE", "Declaration must be FILED to receive QUERY.")
        declaration["status"] = "QUERIED"
        bump_version(declaration)
        emit_audit(
            "DECLARATION",
            declaration["id"],
            "STATE_TRANSITION",
            actor_role,
            user_id,
            {"from": prev_decl_status, "to": "QUERIED"},
        )

    elif response_type == "INSPECT":
        filing["response_type"] = "INSPECT"
        filing["response_received_at"] = now_iso_ms()
        bump_version(filing)
        if declaration.get("status") != "FILED":
            raise ApiError("ERR_INVALID_STATE", "Declaration must be FILED to receive INSPECT.")
        declaration["status"] = "INSPECTING"
        bump_version(declaration)
        emit_audit(
            "DECLARATION",
            declaration["id"],
            "STATE_TRANSITION",
            actor_role,
            user_id,
            {"from": prev_decl_status, "to": "INSPECTING"},
        )

    elif response_type == "RELEASE":
        if filing.get("manifest_match_status") != "MATCHED":
            raise ApiError(
                "ERR_MANIFEST_MISMATCH",
                "Cannot release filing: manifest_match_status is not MATCHED.",
            )
        if declaration.get("status") != "FILED":
            raise ApiError("ERR_INVALID_STATE", "Declaration must be FILED to receive RELEASE.")
        filing["response_type"] = "RELEASE"
        filing["response_received_at"] = now_iso_ms()
        bump_version(filing)
        declaration["status"] = "RELEASED"
        bump_version(declaration)
        emit_audit(
            "DECLARATION",
            declaration["id"],
            "STATE_TRANSITION",
            actor_role,
            user_id,
            {"from": prev_decl_status, "to": "RELEASED"},
        )
        # Cascade settlement creation (penalty 0)
        cascade_create_settlement(declaration, penalty_in_declared=0)

    elif response_type == "REJECT":
        reason_code = payload.get("reason_code") or "OTHER"
        if reason_code not in {
            "HS_MISMATCH",
            "VALUE_UNDERSTATED",
            "MISSING_LICENSE",
            "INSPECTION_FAILED",
            "MANIFEST_MISMATCH",
            "OTHER",
        }:
            raise ApiError("ERR_INVALID_INPUT", f"Invalid reason_code: {reason_code!r}.")
        if declaration.get("status") != "FILED":
            raise ApiError("ERR_INVALID_STATE", "Declaration must be FILED to receive REJECT.")
        filing["response_type"] = "REJECT"
        filing["response_received_at"] = now_iso_ms()
        bump_version(filing)
        declaration["status"] = "REJECTED"
        declaration["rejection_reason_code"] = reason_code
        bump_version(declaration)

        rr = common_fields_append_only()
        rr.update(
            {
                "declaration_id": declaration["id"],
                "rejection_reason_code": reason_code,
                "archived_at": now_iso_ms(),
                "free_text_note": payload.get("free_text_note"),
                "prior_amendment_count": int(declaration.get("amendment_count", 0) or 0),
            }
        )
        store.rejection_records[rr["id"]] = rr

        emit_audit(
            "DECLARATION",
            declaration["id"],
            "STATE_TRANSITION",
            actor_role,
            user_id,
            {"from": prev_decl_status, "to": "REJECTED"},
        )


def _handle_manifest_dropped(
    target_entity_type: str, target_entity_id: str, payload: dict[str, Any]
) -> None:
    store = get_store()
    if target_entity_type != "FILING":
        raise ApiError("ERR_INVALID_INPUT", "MANIFEST_DROPPED must target FILING.")
    filing = store.filings.get(target_entity_id)
    if not filing:
        raise ApiError("ERR_NOT_FOUND", "Filing not found.")
    if filing.get("response_type") != "AWAITING":
        raise ApiError("ERR_INVALID_STATE", "Filing.response_type is not AWAITING.")

    declaration = store.declarations.get(filing.get("declaration_id"))
    if not declaration:
        raise ApiError("ERR_NOT_FOUND", "Parent declaration not found.")

    payload_sr = payload.get("shipment_reference")
    payload_hs = payload.get("hs_code")
    if (
        payload_sr == declaration.get("shipment_reference")
        and payload_hs == declaration.get("hs_code")
    ):
        new_status = "MATCHED"
    else:
        new_status = "MISMATCHED"

    old_status = filing.get("manifest_match_status")
    filing["manifest_match_status"] = new_status
    bump_version(filing)
    if old_status != new_status:
        emit_audit(
            "FILING",
            filing["id"],
            "FIELD_CHANGE",
            "system",
            "system",
            {
                "field": "manifest_match_status",
                "old": old_status,
                "new": new_status,
            },
        )


def _handle_bank_debit(
    target_entity_type: str, target_entity_id: str, payload: dict[str, Any]
) -> None:
    store = get_store()
    if target_entity_type != "SETTLEMENT":
        raise ApiError("ERR_INVALID_INPUT", "BANK_DEBIT_CONFIRMED must target SETTLEMENT.")
    settlement = store.settlements.get(target_entity_id)
    if not settlement:
        raise ApiError("ERR_NOT_FOUND", "Settlement not found.")
    process_bank_debit(settlement, payload)


def _latest_filing_for_declaration(declaration_id: str):
    store = get_store()
    candidates = [
        f for f in store.filings.values() if f.get("declaration_id") == declaration_id
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda f: f.get("submitted_at") or "")
    return candidates[-1]
