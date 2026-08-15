"""Dispute endpoints (PRD 3.8)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_VALIDATION, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_NOT_OWN_RESOURCE, ERR_DISPUTE_SUBJECT_MISMATCH,
    ERR_SEGREGATION_OF_DUTIES, ERR_RATE_NOT_FOUND,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_response
from services.core import new_record, touch, public
from services.ledger import (
    resolve_rate, reverse_capture, create_replacement_capture,
    void_statement_cascade,
)
from validate import get_body, req_str, req_enum, require_path_resource

bp = Blueprint("disputes", __name__)

DISPUTE_READ_ROLES = ["CompAnalyst", "CompCommittee", "Physician"]
OPEN_DISPUTE_STATUSES = ("FILED", "UNDER_REVIEW", "DATA_CORRECTION")


def _subject_for(body):
    """Best-effort subject resolution for the early ownership check."""
    subject_type = body.get("subject_type")
    if subject_type == "CAPTURE":
        sid = body.get("subject_capture_id")
        if isinstance(sid, str):
            return db["production_captures"].get(sid)
    elif subject_type == "STATEMENT":
        sid = body.get("subject_statement_id")
        if isinstance(sid, str):
            return db["comp_statements"].get(sid)
    return None


@bp.post("/disputes")
def create_dispute():
    caller = authorized(["Physician"])
    body = get_body()
    # Priority 3 (ownership) is evaluated before existence/shape when the
    # subject resolves: a Physician reaching for another physician's subject is
    # refused with ERR_NOT_OWN_RESOURCE (PRD 3.8).
    subj = _subject_for(body)
    if subj is not None:
        agr = db["physician_agreements"].get(subj["agreement_id"])
        owner = agr["physician_id"] if agr else None
        if owner != caller.user_id:
            raise_error(ERR_NOT_OWN_RESOURCE,
                        "a Physician may file disputes only on its own agreement's subjects")
    # Priority 14: payload shape
    subject_type = req_enum(body, "subject_type", {"CAPTURE", "STATEMENT"})
    reason = req_str(body, "reason")
    if body.get("subject_capture_id") is not None and not isinstance(body.get("subject_capture_id"), str):
        raise_error(ERR_VALIDATION, "subject_capture_id must be a string")
    if body.get("subject_statement_id") is not None and not isinstance(body.get("subject_statement_id"), str):
        raise_error(ERR_VALIDATION, "subject_statement_id must be a string")
    # Priority 29: subject consistency (missing or unresolvable subject)
    if subject_type == "CAPTURE":
        sid = body.get("subject_capture_id")
        subj = db["production_captures"].get(sid) if isinstance(sid, str) else None
        if subj is None:
            raise_error(ERR_DISPUTE_SUBJECT_MISMATCH,
                        "subject_capture_id is required and must reference an existing capture")
    else:
        sid = body.get("subject_statement_id")
        subj = db["comp_statements"].get(sid) if isinstance(sid, str) else None
        if subj is None:
            raise_error(ERR_DISPUTE_SUBJECT_MISMATCH,
                        "subject_statement_id is required and must reference an existing statement")
    agr = db["physician_agreements"][subj["agreement_id"]]
    if agr["physician_id"] != caller.user_id:
        raise_error(ERR_DISPUTE_SUBJECT_MISMATCH,
                    "the subject belongs to a different physician's agreement")
    rec = new_record("disputes", {
        "filer_physician_id": caller.user_id,
        "agreement_id": subj["agreement_id"],
        "subject_type": subject_type,
        "subject_capture_id": sid if subject_type == "CAPTURE" else None,
        "subject_statement_id": sid if subject_type == "STATEMENT" else None,
        "reason": reason,
        "corrected_units": None,
        "corrected_cpt_code": None,
        "status": "FILED",
        "resolution": None,
        "resolver_user_id": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/disputes")
def list_disputes():
    caller = authorized(DISPUTE_READ_ROLES)
    filer = request.args.get("filer_physician_id")
    if caller.role == "Physician":
        if filer is not None and filer != caller.user_id:
            raise_error(ERR_NOT_OWN_RESOURCE, "a Physician may list only its own disputes")
        filer = caller.user_id
    filters = {
        "agreement_id": request.args.get("agreement_id"),
        "filer_physician_id": filer,
        "status": request.args.get("status"),
    }
    return list_response("disputes", filters)


@bp.get("/disputes/<rid>")
def get_dispute(rid):
    caller = authorized(DISPUTE_READ_ROLES)
    rec = db["disputes"].get(rid)
    if rec is not None and caller.role == "Physician" and rec["filer_physician_id"] != caller.user_id:
        raise_error(ERR_NOT_OWN_RESOURCE, "a Physician may read only its own disputes")
    if rec is None:
        raise_error(ERR_NOT_FOUND, f"dispute not found: {rid}")
    return success_object(public(rec))


@bp.post("/disputes/<rid>/start-review")
def start_review(rid):
    authorized(["CompAnalyst"])
    d = require_path_resource("disputes", rid)
    if d["status"] not in ("FILED", "DATA_CORRECTION"):
        raise_error(ERR_INVALID_STATE,
                    "start-review requires status FILED or DATA_CORRECTION")
    if d["status"] == "DATA_CORRECTION":
        # Cycling back clears the recorded correction (PRD 3.8)
        d["corrected_units"] = None
        d["corrected_cpt_code"] = None
    d["status"] = "UNDER_REVIEW"
    touch("disputes", d)
    return success_object(public(d))


@bp.post("/disputes/<rid>/request-correction")
def request_correction(rid):
    authorized(["CompAnalyst"])
    d = require_path_resource("disputes", rid)
    if d["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, "request-correction requires status UNDER_REVIEW")
    if d["subject_type"] != "CAPTURE":
        raise_error(ERR_INVALID_STATE, "data corrections apply to capture subjects only")
    body = get_body()
    cu = body.get("corrected_units")
    if cu is not None and (isinstance(cu, bool) or not isinstance(cu, int) or cu < 1):
        raise_error(ERR_VALIDATION, "corrected_units must be an integer >= 1")
    cc = body.get("corrected_cpt_code")
    if cc is not None and (not isinstance(cc, str) or not cc):
        raise_error(ERR_VALIDATION, "corrected_cpt_code must be a non-empty string")
    d["corrected_units"] = cu
    d["corrected_cpt_code"] = cc
    d["status"] = "DATA_CORRECTION"
    touch("disputes", d)
    return success_object(public(d))


@bp.post("/disputes/<rid>/resolve")
def resolve_dispute(rid):
    caller = authorized(["CompCommittee"])
    d = require_path_resource("disputes", rid)
    # State guard first, then segregation of duties, then rate coverage (PRD 3.8)
    if d["status"] not in ("UNDER_REVIEW", "DATA_CORRECTION"):
        raise_error(ERR_INVALID_STATE,
                    "resolve requires status UNDER_REVIEW or DATA_CORRECTION")
    body = get_body()
    resolution = req_enum(body, "resolution", {"ACCEPTED", "REJECTED"})

    subject = None
    if d["subject_type"] == "CAPTURE":
        subject = db["production_captures"].get(d["subject_capture_id"])
    else:
        subject = db["comp_statements"].get(d["subject_statement_id"])
    if subject is None:
        raise_error(ERR_NOT_FOUND, "dispute subject no longer exists")

    if resolution == "ACCEPTED" and d["subject_type"] == "CAPTURE":
        # The credit reversal requires the subject to be CREDITED
        if subject["credit_status"] != "CREDITED":
            raise_error(ERR_INVALID_STATE, "subject capture is not CREDITED")
        if (subject["created_by_user_id"] is not None
                and caller.user_id == subject["created_by_user_id"]):
            raise_error(ERR_SEGREGATION_OF_DUTIES,
                        "dispute resolver must differ from the subject capture's creator")
        if d["status"] == "DATA_CORRECTION" and d["corrected_cpt_code"] is not None:
            agr = db["physician_agreements"][d["agreement_id"]]
            if resolve_rate(agr["plan_id"], d["corrected_cpt_code"],
                            subject["service_date"]) is None:
                raise_error(ERR_RATE_NOT_FOUND,
                            "no CptRate row covers the corrected CPT code on the original service date")
    if resolution == "ACCEPTED" and d["subject_type"] == "STATEMENT":
        if subject["status"] != "FINALIZED":
            raise_error(ERR_INVALID_STATE, "subject statement is not FINALIZED")

    # Side effects
    if resolution == "ACCEPTED":
        if d["subject_type"] == "CAPTURE":
            reverse_capture(subject, d["reason"])
            if d["status"] == "DATA_CORRECTION":
                agr = db["physician_agreements"][d["agreement_id"]]
                create_replacement_capture(subject, agr,
                                           d["corrected_units"], d["corrected_cpt_code"])
        else:
            subject["status"] = "VOIDED"
            touch("comp_statements", subject)
            void_statement_cascade(subject)
        d["resolution"] = "ACCEPTED"
        d["status"] = "RESOLVED_ACCEPTED"
    else:
        d["resolution"] = "REJECTED"
        d["status"] = "RESOLVED_REJECTED"
    d["resolver_user_id"] = caller.user_id
    touch("disputes", d)
    return success_object(public(d))
