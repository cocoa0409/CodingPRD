"""Audit endpoints (PRD 3.9)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_STATE,
    ERR_AUDIT_WINDOW_CLOSED,
    ERR_AUDIT_ALREADY_ACTIVE,
    ERR_AUDIT_REOPEN_LIMIT,
)
from response import success_object
from routes.helpers import get_one, list_response, public, scoped_mutation_auth
from services.calculations import audit_cost_bearer
from services.core import new_record, touch
from util import CLOCK, parse_datetime
from validate import (
    get_body, req_int, req_str, require_path_resource, require_ref,
)

bp = Blueprint("audits", __name__)

AUDITABLE_STATEMENT_STATES = {"ISSUED", "DISPUTED", "ACKNOWLEDGED", "FINALIZED"}
AUDIT_WINDOW_DAYS = 365


@bp.post("/audits")
def create_audit():
    body = get_body()
    artist_id = req_str(body, "artist_id")
    caller = scoped_mutation_auth(["Artist"], body_artist_id=artist_id)
    scope_statement_id = req_str(body, "scope_statement_id")

    require_ref("artists", artist_id, "artist_id")
    stmt = require_ref("statements", scope_statement_id, "scope_statement_id")

    if stmt["status"] not in AUDITABLE_STATEMENT_STATES:
        raise_error(ERR_INVALID_STATE, f"cannot audit a {stmt['status']} statement")
    issued_at = parse_datetime(stmt["issued_at"]) if stmt.get("issued_at") else None
    if issued_at is None:
        raise_error(ERR_INVALID_STATE, "statement has no issued_at")
    if issued_at < CLOCK.now() - timedelta(days=AUDIT_WINDOW_DAYS):
        raise_error(ERR_AUDIT_WINDOW_CLOSED,
                    "scope statement was issued more than 365 days before the clock")
    for a in db["audits"].values():
        if a["scope_statement_id"] == scope_statement_id and a["status"] != "CLOSED":
            raise_error(ERR_AUDIT_ALREADY_ACTIVE, "another audit on this statement is not CLOSED")

    rec = new_record("audits", {
        "artist_id": artist_id,
        "scope_statement_id": scope_statement_id,
        "source_dispute_id": None,
        "status": "REQUESTED",
        "findings_underpayment_cents": None,
        "audit_cost_cents": None,
        "cost_bearer": None,
        "underpayment_applied": False,
        "cost_applied": False,
        "reopen_count": 0,
    })
    return success_object(public(rec), status=201)


@bp.get("/audits/<rid>")
def get_audit(rid):
    return get_one("audits", rid)


@bp.get("/audits")
def list_audits():
    filters = {
        "artist_id": request.args.get("artist_id"),
        "scope_statement_id": request.args.get("scope_statement_id"),
        "source_dispute_id": request.args.get("source_dispute_id"),
        "status": request.args.get("status"),
    }
    return list_response("audits", filters)


@bp.post("/audits/<rid>/begin")
def begin_audit(rid):
    caller = scoped_mutation_auth(["Auditor"], "audits", rid)
    a = require_path_resource("audits", rid)
    if a["status"] != "REQUESTED":
        raise_error(ERR_INVALID_STATE, "begin requires REQUESTED")
    a["status"] = "IN_PROGRESS"
    touch(a)
    return success_object(public(a))


@bp.post("/audits/<rid>/issue-findings")
def issue_findings(rid):
    caller = scoped_mutation_auth(["Auditor"], "audits", rid)
    body = get_body()
    a = require_path_resource("audits", rid)
    findings = req_int(body, "findings_underpayment_cents", non_negative=True)
    cost = req_int(body, "audit_cost_cents", non_negative=True)
    if a["status"] != "IN_PROGRESS":
        raise_error(ERR_INVALID_STATE, "issue-findings requires IN_PROGRESS")
    stmt = db["statements"].get(a["scope_statement_id"])
    base = stmt["net_payable_cents"] if stmt is not None else 0
    a["findings_underpayment_cents"] = findings
    a["audit_cost_cents"] = cost
    a["cost_bearer"] = audit_cost_bearer(base, findings)
    a["status"] = "FINDINGS_ISSUED"
    touch(a)
    return success_object(public(a))


@bp.post("/audits/<rid>/reopen")
def reopen_audit(rid):
    caller = scoped_mutation_auth(["Artist"], "audits", rid)
    a = require_path_resource("audits", rid)
    if a["status"] != "FINDINGS_ISSUED":
        raise_error(ERR_INVALID_STATE, "reopen requires FINDINGS_ISSUED")
    if a["reopen_count"] >= 2:
        raise_error(ERR_AUDIT_REOPEN_LIMIT, "audit has already been reopened twice")
    a["reopen_count"] += 1
    a["status"] = "IN_PROGRESS"
    touch(a)
    return success_object(public(a))


@bp.post("/audits/<rid>/close")
def close_audit(rid):
    caller = scoped_mutation_auth(["Auditor", "FirmAdmin"], "audits", rid)
    a = require_path_resource("audits", rid)
    if a["status"] != "FINDINGS_ISSUED":
        raise_error(ERR_INVALID_STATE, "close requires FINDINGS_ISSUED")
    a["status"] = "CLOSED"
    touch(a)
    return success_object(public(a))
