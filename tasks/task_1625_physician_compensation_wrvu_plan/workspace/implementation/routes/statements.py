"""CompStatement endpoints (PRD 3.7)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_DUPLICATE_RESOURCE,
    ERR_STATEMENT_PERIOD_ORDER, ERR_SEGREGATION_OF_DUTIES, ERR_OPEN_DISPUTES,
    ERR_NOT_OWN_RESOURCE,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_response
from services.core import new_record, touch, public
from services.ledger import (
    compute_statement_fields, recompute_lifetime_paid, void_statement_cascade,
)
from validate import get_body, req_int, req_str, require_path_resource

bp = Blueprint("statements", __name__)

STATEMENT_READ_ROLES = ["CompAnalyst", "CompCommittee", "Physician"]


def _check_statement_ownership(caller, stmt):
    if caller.role != "Physician":
        return
    agr = db["physician_agreements"].get(stmt["agreement_id"])
    if agr is None or agr["physician_id"] != caller.user_id:
        raise_error(ERR_NOT_OWN_RESOURCE, "a Physician may read only its own statements")


@bp.post("/physician-agreements/<rid>/comp-statements")
def generate_statement(rid):
    caller = authorized(["CompAnalyst"])
    agr = require_path_resource("physician_agreements", rid)
    body = get_body()
    period_year = req_int(body, "period_year")
    period_month = req_int(body, "period_month", minimum=1, maximum=12)
    # Priority 21 (duplicate) precedes priority 26 (chronology) — PRD 3.7
    for s in db["comp_statements"].values():
        if (s["agreement_id"] == agr["id"]
                and (s["period_year"], s["period_month"]) == (period_year, period_month)):
            raise_error(ERR_DUPLICATE_RESOURCE,
                        "a statement already exists for this agreement and period")
    for s in db["comp_statements"].values():
        if (s["agreement_id"] == agr["id"]
                and (s["period_year"], s["period_month"]) >= (period_year, period_month)):
            raise_error(ERR_STATEMENT_PERIOD_ORDER,
                        "statement periods must be strictly later than every existing period")
    # Pinned evaluation order (statement_net_settlement): snapshot the pending
    # true-up adjustment first and reset it; never recomputed from this statement.
    trueup_snapshot = agr["pending_trueup_adjustment_cents"]
    agr["pending_trueup_adjustment_cents"] = 0
    touch("physician_agreements", agr)
    draw_snapshot = agr["period_draw_cents"]
    fields = compute_statement_fields(agr, period_year, period_month,
                                      trueup_snapshot, draw_snapshot)
    rec = new_record("comp_statements", {
        "agreement_id": agr["id"],
        "period_year": period_year,
        "period_month": period_month,
        **fields,
        "status": "DRAFT",
        "created_by_user_id": caller.user_id,
    })
    return success_object(public(rec), status=201)


@bp.get("/physician-agreements/<rid>/comp-statements")
def list_statements(rid):
    caller = authorized(STATEMENT_READ_ROLES)
    agr = db["physician_agreements"].get(rid)
    if agr is not None and caller.role == "Physician" and agr["physician_id"] != caller.user_id:
        raise_error(ERR_NOT_OWN_RESOURCE, "a Physician may read only its own statements")
    if agr is None:
        raise_error(ERR_NOT_FOUND, f"agreement not found: {rid}")
    filters = {"agreement_id": rid, "status": request.args.get("status")}
    return list_response("comp_statements", filters)


@bp.get("/comp-statements/<rid>")
def get_statement(rid):
    caller = authorized(STATEMENT_READ_ROLES)
    rec = db["comp_statements"].get(rid)
    if rec is not None:
        _check_statement_ownership(caller, rec)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"statement not found: {rid}")
    return success_object(public(rec))


@bp.post("/comp-statements/<rid>/submit-review")
def submit_statement_review(rid):
    authorized(["CompAnalyst"])
    stmt = require_path_resource("comp_statements", rid)
    if stmt["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "only a DRAFT statement can be submitted for review")
    stmt["status"] = "UNDER_REVIEW"
    touch("comp_statements", stmt)
    return success_object(public(stmt))


@bp.post("/comp-statements/<rid>/finalize")
def finalize_statement(rid):
    caller = authorized(["CompCommittee"])
    stmt = require_path_resource("comp_statements", rid)
    # State guard, then segregation of duties, then open disputes (PRD 3.7)
    if stmt["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, "finalize requires status UNDER_REVIEW")
    if caller.user_id == stmt["created_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "statement finalizer must differ from the statement creator")
    agr = db["physician_agreements"][stmt["agreement_id"]]
    for d in db["disputes"].values():
        if d["agreement_id"] == agr["id"] and d["status"] in ("FILED", "UNDER_REVIEW", "DATA_CORRECTION"):
            raise_error(ERR_OPEN_DISPUTES,
                        "an open dispute on this agreement blocks finalization")
    stmt["status"] = "FINALIZED"
    touch("comp_statements", stmt)
    # Cascade down: lock included captures VALIDATED -> LOCKED
    for cid in stmt["capture_ids"]:
        c = db["production_captures"].get(cid)
        if c is not None and c["capture_status"] == "VALIDATED":
            c["capture_status"] = "LOCKED"
            touch("production_captures", c)
    recompute_lifetime_paid(agr)
    touch("physician_agreements", agr)
    return success_object(public(stmt))


@bp.post("/comp-statements/<rid>/void")
def void_statement(rid):
    authorized(["CompCommittee"])
    stmt = require_path_resource("comp_statements", rid)
    if stmt["status"] != "FINALIZED":
        raise_error(ERR_INVALID_STATE, "only a FINALIZED statement can be voided")
    body = get_body()
    req_str(body, "reason")
    stmt["status"] = "VOIDED"
    touch("comp_statements", stmt)
    void_statement_cascade(stmt)
    return success_object(public(stmt))


@bp.get("/comp-statements/<rid>/disputes")
def list_statement_disputes(rid):
    caller = authorized(STATEMENT_READ_ROLES)
    rec = db["comp_statements"].get(rid)
    if rec is not None:
        _check_statement_ownership(caller, rec)
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"statement not found: {rid}")
    return list_response("disputes", {"subject_statement_id": rid})
