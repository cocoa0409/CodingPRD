"""Complaint endpoints."""
from flask import Blueprint, request

from db import store, now, new_id
from errors import (err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_UNAUTHORIZED, ERR_ESCALATION_NOT_WARRANTED)
from middleware import authorized
from response import ok, paginate
from services import (ser_complaint, get_or_404, stamp_new, touch,
                      COMPLAINT_TYPES, SEVERITIES)
from util import get_body, require_fields, check_enum

bp = Blueprint("complaints", __name__)

COMPLAINT_READ = ("COMPLAINT_HANDLER", "QA_MANAGER")


@bp.post("/complaints")
@authorized("COMPLAINT_HANDLER")
def create_complaint(_user_id=None, _role=None):
    body = get_body()
    formula = None
    batch = None
    if body.get("product_formula_id") is not None:
        formula = get_or_404(store.formulas, body["product_formula_id"], "Formula")
    if body.get("batch_id") is not None:
        batch = get_or_404(store.batches, body["batch_id"], "ProductionBatch")
    require_fields(body, ["complainant_name", "complainant_contact", "product_formula_id",
                          "complaint_type", "severity", "description"])
    ctype = check_enum(body["complaint_type"], COMPLAINT_TYPES, "complaint_type")
    severity = check_enum(body["severity"], SEVERITIES, "severity")
    is_adverse = ctype in ("ADVERSE_EVENT", "ILLNESS") or severity == "CRITICAL"
    rec = stamp_new({
        "id": new_id(),
        "complaint_ref": store.next_ref("C"),
        "complainant_name": body["complainant_name"],
        "complainant_contact": body["complainant_contact"],
        "product_formula_id": formula["id"],
        "batch_id": batch["id"] if batch else None,
        "complaint_type": ctype,
        "severity": severity,
        "description": body["description"],
        "status": "RECEIVED",
        "is_adverse_event": is_adverse,
        "escalated_at": None,
        "resolution": None,
        "resolved_at": None,
    })
    store.complaints[rec["id"]] = rec
    return ok(ser_complaint(rec), 201)


@bp.get("/complaints")
@authorized(*COMPLAINT_READ)
def list_complaints(_user_id=None, _role=None):
    records = list(store.complaints.values())
    for param, field in (("status", "status"), ("severity", "severity"),
                         ("complaint_type", "complaint_type"),
                         ("product_formula_id", "product_formula_id"),
                         ("batch_id", "batch_id")):
        v = request.args.get(param)
        if v is not None:
            records = [c for c in records if c.get(field) == v]
    return paginate(records, ser_complaint)


@bp.get("/complaints/<cid>")
@authorized(*COMPLAINT_READ)
def get_complaint(cid, _user_id=None, _role=None):
    return ok(ser_complaint(get_or_404(store.complaints, cid, "Complaint")))


@bp.post("/complaints/<cid>/start-investigation")
@authorized("COMPLAINT_HANDLER")
def start_investigation(cid, _user_id=None, _role=None):
    rec = get_or_404(store.complaints, cid, "Complaint")
    if rec["status"] != "RECEIVED":
        raise err(ERR_INVALID_STATE,
                  "Complaint in status %s cannot start investigation" % rec["status"])
    rec["status"] = "INVESTIGATING"
    touch(rec)
    return ok(ser_complaint(rec))


@bp.post("/complaints/<cid>/escalate")
@authorized("COMPLAINT_HANDLER")
def escalate_complaint(cid, _user_id=None, _role=None):
    rec = get_or_404(store.complaints, cid, "Complaint")
    if rec["status"] != "INVESTIGATING":
        raise err(ERR_INVALID_STATE,
                  "Complaint in status %s cannot be escalated" % rec["status"])
    if not (rec["is_adverse_event"] or rec["severity"] in ("HIGH", "CRITICAL")):
        raise err(ERR_ESCALATION_NOT_WARRANTED,
                  "Complaint does not meet escalation criteria")
    body = get_body()
    require_fields(body, ["escalation_reason"])
    rec["status"] = "ESCALATED"
    rec["escalated_at"] = now()
    # flag linked batch for potential recall review
    if rec.get("batch_id"):
        batch = store.batches.get(rec["batch_id"])
        if batch is not None and batch["status"] == "RELEASED":
            batch["_recall_review_flagged"] = True
    touch(rec)
    return ok(ser_complaint(rec))


@bp.post("/complaints/<cid>/resolve")
@authorized("COMPLAINT_HANDLER", "QA_MANAGER")
def resolve_complaint(cid, _user_id=None, _role=None):
    rec = get_or_404(store.complaints, cid, "Complaint")
    if rec["status"] not in ("INVESTIGATING", "ESCALATED"):
        raise err(ERR_INVALID_STATE,
                  "Complaint in status %s cannot be resolved" % rec["status"])
    if rec["status"] == "ESCALATED" and _role != "QA_MANAGER":
        raise err(ERR_UNAUTHORIZED,
                  "An ESCALATED complaint may be resolved only by a QA_MANAGER")
    body = get_body()
    if rec["status"] == "ESCALATED" and rec.get("batch_id"):
        reviewed = any(s["batch_id"] == rec["batch_id"] for s in store.scopes.values())
        if not reviewed and not body.get("no_recall_decision"):
            raise err(ERR_INVALID_STATE,
                      "Linked batch must be reviewed for recall linkage before resolution")
    require_fields(body, ["resolution"])
    rec["status"] = "RESOLVED"
    rec["resolution"] = body["resolution"]
    rec["resolved_at"] = now()
    touch(rec)
    return ok(ser_complaint(rec))


@bp.post("/complaints/<cid>/close")
@authorized("COMPLAINT_HANDLER")
def close_complaint(cid, _user_id=None, _role=None):
    rec = get_or_404(store.complaints, cid, "Complaint")
    if rec["status"] != "RESOLVED":
        raise err(ERR_INVALID_STATE,
                  "Complaint in status %s cannot be closed" % rec["status"])
    if rec.get("resolved_at") is None:
        raise err(ERR_INVALID_STATE, "Complaint has no resolved_at timestamp")
    rec["status"] = "CLOSED"
    touch(rec)
    return ok(ser_complaint(rec))
