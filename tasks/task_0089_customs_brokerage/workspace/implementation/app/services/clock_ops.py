"""POST /customs/_clock/advance — drives deferred system transitions."""
from __future__ import annotations

from typing import Any

from ..audit import emit_audit
from ..clock import CLOCK, format_iso, now_dt, parse_iso
from ..constants import DECLARATION_NON_TERMINAL
from ..errors import ApiError
from ..store import bump_version, common_fields_append_only, get_store


def advance_clock(body: dict[str, Any]) -> dict[str, Any]:
    raw = body.get("to_timestamp")
    if not isinstance(raw, str):
        raise ApiError("ERR_INVALID_INPUT", "to_timestamp is required.")
    try:
        target = parse_iso(raw)
    except ValueError as exc:
        raise ApiError("ERR_INVALID_INPUT", f"Invalid to_timestamp: {exc}")

    if target < CLOCK.now:
        raise ApiError("ERR_INVALID_INPUT", "to_timestamp must be >= current clock.")

    CLOCK.set(target)
    transitions = 0
    transitions += _expire_agreements()
    transitions += _expire_queries()

    return {
        "now": format_iso(CLOCK.now),
        "transitions_triggered": transitions,
    }


def _expire_agreements() -> int:
    """Auto-expire agreements past valid_until when no declaration is non-terminal."""
    store = get_store()
    n = 0
    for agreement in store.agreements.values():
        if agreement.get("status") != "ACTIVE":
            continue
        vu = parse_iso(agreement["valid_until"])
        if now_dt() < vu:
            continue
        # Check no non-terminal declarations
        blocked = any(
            d.get("agreement_id") == agreement["id"]
            and d.get("status") in DECLARATION_NON_TERMINAL
            for d in store.declarations.values()
        )
        if blocked:
            continue
        prev = agreement["status"]
        agreement["status"] = "EXPIRED"
        bump_version(agreement)
        emit_audit(
            "AGREEMENT",
            agreement["id"],
            "STATE_TRANSITION",
            "system",
            "system",
            {"from": prev, "to": "EXPIRED"},
        )
        n += 1
    return n


def _expire_queries() -> int:
    """QUERIED→REJECTED for declarations whose query_due_at has passed without response."""
    store = get_store()
    n = 0
    for declaration in store.declarations.values():
        if declaration.get("status") != "QUERIED":
            continue
        filing = _latest_filing(declaration["id"])
        if not filing or filing.get("response_type") != "QUERY":
            continue
        if filing.get("query_response_at") is not None:
            continue
        if filing.get("query_due_at") is None:
            continue
        if now_dt() < parse_iso(filing["query_due_at"]):
            continue
        # transition
        prev = declaration["status"]
        declaration["status"] = "REJECTED"
        declaration["rejection_reason_code"] = "OTHER"
        bump_version(declaration)
        # Create RejectionRecord
        rr = common_fields_append_only()
        rr.update(
            {
                "declaration_id": declaration["id"],
                "rejection_reason_code": "OTHER",
                "archived_at": format_iso(now_dt()),
                "free_text_note": "Auto-expired QUERY without response.",
                "prior_amendment_count": int(declaration.get("amendment_count", 0) or 0),
            }
        )
        store.rejection_records[rr["id"]] = rr
        emit_audit(
            "DECLARATION",
            declaration["id"],
            "STATE_TRANSITION",
            "system",
            "system",
            {"from": prev, "to": "REJECTED"},
        )
        n += 1
    return n


def _latest_filing(declaration_id: str):
    store = get_store()
    candidates = [
        f for f in store.filings.values() if f.get("declaration_id") == declaration_id
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda f: f.get("submitted_at") or "")
    return candidates[-1]
