"""Common helpers: pagination, lookup, OCC, audit, outbox."""

from __future__ import annotations

from typing import Any, Callable, Iterable

from flask import g, request

from db import db, gen_id, now_iso_z
from errors import (
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    raise_api_error,
)


# ---------- Body helpers ----------

def get_json_body() -> dict:
    """Extract JSON body; return {} if missing/empty (for endpoints with no required input)."""
    if request.method == "GET":
        return {}
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise_api_error(ERR_INVALID_REQUEST, "Body must be valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_api_error(ERR_INVALID_REQUEST, "Body must be a JSON object.")
    return body


def require_field(body: dict, key: str, *, type_=None, allow_empty: bool = False):
    if key not in body or body[key] is None:
        raise_api_error(ERR_INVALID_REQUEST, f"Missing required field '{key}'.")
    val = body[key]
    if type_ is not None and not isinstance(val, type_):
        raise_api_error(ERR_INVALID_REQUEST, f"Field '{key}' has invalid type.")
    if not allow_empty and isinstance(val, (str, list)) and len(val) == 0:
        raise_api_error(ERR_INVALID_REQUEST, f"Field '{key}' must be non-empty.")
    return val


def optional_field(body: dict, key: str, default=None, *, type_=None):
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if type_ is not None and not isinstance(val, type_):
        raise_api_error(ERR_INVALID_REQUEST, f"Field '{key}' has invalid type.")
    return val


def require_int(body: dict, key: str, *, allow_negative: bool = False, required: bool = True, default=None):
    if key not in body or body[key] is None:
        if required:
            raise_api_error(ERR_INVALID_REQUEST, f"Missing required field '{key}'.")
        return default
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise_api_error(ERR_INVALID_REQUEST, f"Field '{key}' must be an integer.")
    if not allow_negative and val < 0:
        raise_api_error(ERR_INVALID_REQUEST, f"Field '{key}' must be non-negative.")
    return val


# ---------- Lookup helpers ----------

def get_insurer_or_404(insurer_id: str) -> dict:
    ins = db.insurers.get(insurer_id)
    if not ins:
        raise_api_error(ERR_NOT_FOUND, f"Insurer {insurer_id} not found.")
    return ins


def get_policy_or_404(insurer_id: str, policy_id: str) -> dict:
    pol = db.policies.get(policy_id)
    if not pol or pol.get("insurer_id") != insurer_id:
        raise_api_error(ERR_NOT_FOUND, f"Policy {policy_id} not found.")
    return pol


def get_ticket_or_404(insurer_id: str, ticket_id: str) -> dict:
    t = db.tickets.get(ticket_id)
    if not t or t.get("insurer_id") != insurer_id:
        raise_api_error(ERR_NOT_FOUND, f"Ticket {ticket_id} not found.")
    return t


def get_flight_or_404(insurer_id: str, flight_id: str) -> dict:
    f = db.flights.get(flight_id)
    if not f or f.get("insurer_id") != insurer_id:
        raise_api_error(ERR_NOT_FOUND, f"Flight {flight_id} not found.")
    return f


def get_claim_or_404(insurer_id: str, claim_id: str) -> dict:
    c = db.claims.get(claim_id)
    if not c or c.get("insurer_id") != insurer_id:
        raise_api_error(ERR_NOT_FOUND, f"Claim {claim_id} not found.")
    return c


def get_batch_or_404(insurer_id: str, batch_id: str) -> dict:
    b = db.payout_batches.get(batch_id)
    if not b or b.get("insurer_id") != insurer_id:
        raise_api_error(ERR_NOT_FOUND, f"PayoutBatch {batch_id} not found.")
    return b


def get_case_or_404(insurer_id: str, case_id: str) -> dict:
    c = db.manual_review_cases.get(case_id)
    if not c or c.get("insurer_id") != insurer_id:
        raise_api_error(ERR_NOT_FOUND, f"ManualReviewCase {case_id} not found.")
    return c


def get_outbox_or_404(insurer_id: str, event_id: str) -> dict:
    e = db.outbox_events.get(event_id)
    if not e or e.get("insurer_id") != insurer_id:
        raise_api_error(ERR_NOT_FOUND, f"OutboxEvent {event_id} not found.")
    return e


# ---------- Optimistic concurrency ----------

def check_version(body: dict, obj: dict):
    """Compare body['version'] to obj['version']; mismatch → ERR_INVALID_STATE."""
    if "version" in body and body["version"] is not None:
        if not isinstance(body["version"], int) or isinstance(body["version"], bool):
            raise_api_error(ERR_INVALID_REQUEST, "Field 'version' must be an integer.")
        if body["version"] != obj.get("version"):
            raise_api_error(ERR_INVALID_STATE, "Version mismatch (optimistic concurrency).")


# ---------- Pagination ----------

def parse_pagination() -> tuple[int, int]:
    try:
        limit = int(request.args.get("limit", "10"))
    except (TypeError, ValueError):
        raise_api_error(ERR_INVALID_REQUEST, "limit must be an integer.")
    try:
        offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        raise_api_error(ERR_INVALID_REQUEST, "offset must be an integer.")
    if limit < 1 or limit > 100:
        raise_api_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100.")
    if offset < 0:
        raise_api_error(ERR_INVALID_REQUEST, "offset must be >= 0.")
    return limit, offset


def paginate(items: list, limit: int, offset: int) -> tuple[list, int]:
    total = len(items)
    return items[offset : offset + limit], total


# ---------- Audit & Outbox ----------

def append_audit(insurer_id: str, subject_type: str, subject_id: str, action: str, details: dict):
    log = {
        "id": gen_id(),
        "insurer_id": insurer_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "action": action,
        "actor_role": getattr(g, "user_role", "system"),
        "actor_id": getattr(g, "user_id", "system"),
        "details": details,
        "created_at": now_iso_z(),
    }
    db.audit_logs[log["id"]] = log
    return log


def emit_outbox(insurer_id: str, target_system: str, event_type: str, subject_type: str, subject_id: str, payload: dict):
    ev = {
        "id": gen_id(),
        "insurer_id": insurer_id,
        "target_system": target_system,
        "event_type": event_type,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "payload": payload,
        "dispatch_status": "PENDING",
        "created_at": now_iso_z(),
    }
    db.outbox_events[ev["id"]] = ev
    return ev


# ---------- Sort ----------

def sort_by_created_at(items: Iterable[dict]) -> list:
    return sorted(items, key=lambda x: (x.get("created_at", ""), x.get("id", "")))
