"""DocketAudit routes (PRD §3.9): half-open audit windows, creation-time
variance computation, resolve/close outcomes."""

import re
from datetime import date

from flask import Blueprint

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

import db as dbmod
import serialize
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_CLIENT_SUSPENDED,
    ERR_AUDIT_WINDOW_OVERLAP,
)
from middleware import require_roles, get_json_body, ALL_ROLES
from response import success_object, success_list_all
from services.common import (
    new_id, stamp_new, bump, get_application, get_audit,
    client_of_application, check_allowed_fields, req_str, req_date,
    ensure_transition, ENTRY_TYPES,
)
from services import calc

bp = Blueprint("audits", __name__)

AUDIT_NONTERMINAL = {"OPEN", "VARIANCE_FOUND"}


def _parse_register_entries(body):
    rows = body.get("register_entries")
    if not isinstance(rows, list):
        raise_err(ERR_INVALID_REQUEST, "register_entries must be an array")
    parsed = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            raise_err(ERR_INVALID_REQUEST, f"register_entries[{idx}] must be an object")
        extra = [k for k in row.keys() if k not in ("entry_type", "due_date")]
        if extra:
            raise_err(ERR_INVALID_REQUEST, f"register_entries[{idx}] has undeclared field(s)")
        entry_type = row.get("entry_type")
        if entry_type not in ENTRY_TYPES:
            raise_err(ERR_INVALID_REQUEST, f"register_entries[{idx}].entry_type is not a declared entry type")
        due = row.get("due_date")
        if not isinstance(due, str) or not _DATE_RE.match(due):
            raise_err(ERR_INVALID_REQUEST, f"register_entries[{idx}].due_date must be an ISO YYYY-MM-DD date string")
        try:
            due_date = date.fromisoformat(due)
        except ValueError:
            raise_err(ERR_INVALID_REQUEST, f"register_entries[{idx}].due_date is not a valid date")
        parsed.append({"entry_type": entry_type, "due_date": due_date})
    return parsed


@bp.post("/applications/<application_id>/audits")
def create_audit(application_id):
    require_roles(["DocketingClerk", "DocketingManager"])
    app = get_application(application_id)
    body = get_json_body()
    check_allowed_fields(body, {"window_start", "window_end", "register_entries"})
    window_start = req_date(body, "window_start")
    window_end = req_date(body, "window_end")
    register_entries = _parse_register_entries(body)
    if window_start >= window_end:
        raise_err(ERR_INVALID_REQUEST, "window_start must be strictly earlier than window_end")
    # Business order: audit-window overlap (13), then suspended client (24).
    for other in dbmod.DB["audits"].values():
        if (
            other["application_id"] == app["id"]
            and other["status"] in AUDIT_NONTERMINAL
            and window_start < other["window_end"]
            and other["window_start"] < window_end
        ):
            raise_err(ERR_AUDIT_WINDOW_OVERLAP, "Audit window intersects a non-terminal audit")
    client = client_of_application(app)
    if client["status"] == "SUSPENDED":
        raise_err(ERR_CLIENT_SUSPENDED, "Client is SUSPENDED")
    variances = calc.audit_variances(app["id"], window_start, window_end, register_entries)
    rec = stamp_new({
        "id": new_id(),
        "application_id": app["id"],
        "window_start": window_start,
        "window_end": window_end,
        "register_entries": register_entries,
        "variances": variances,
        "resolution_note": None,
        "status": "VARIANCE_FOUND" if variances else "OPEN",
    })
    dbmod.DB["audits"][rec["id"]] = rec
    return success_object(serialize.audit(rec), 201)


@bp.get("/applications/<application_id>/audits")
def list_application_audits(application_id):
    require_roles(ALL_ROLES)
    app = get_application(application_id)
    items = [a for a in dbmod.DB["audits"].values() if a["application_id"] == app["id"]]
    items.sort(key=lambda r: r["created_at"])
    return success_list_all([serialize.audit(r) for r in items])


@bp.get("/audits/<audit_id>")
def get_audit_route(audit_id):
    require_roles(ALL_ROLES)
    return success_object(serialize.audit(get_audit(audit_id)))


@bp.post("/audits/<audit_id>/resolve")
def resolve_audit(audit_id):
    require_roles(["DocketingManager"])
    rec = get_audit(audit_id)
    body = get_json_body()
    check_allowed_fields(body, {"resolution_note"})
    resolution_note = req_str(body, "resolution_note")
    ensure_transition(rec, {"VARIANCE_FOUND"}, "audits", "DocketAudit")
    rec["status"] = "RESOLVED"
    rec["resolution_note"] = resolution_note
    bump(rec)
    return success_object(serialize.audit(rec))


@bp.post("/audits/<audit_id>/close")
def close_audit(audit_id):
    require_roles(["DocketingManager"])
    rec = get_audit(audit_id)
    ensure_transition(rec, {"OPEN"}, "audits", "DocketAudit")
    rec["status"] = "CLOSED_CLEAN"
    bump(rec)
    return success_object(serialize.audit(rec))
