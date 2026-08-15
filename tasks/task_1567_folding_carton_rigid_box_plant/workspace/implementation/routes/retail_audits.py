"""RetailReadyAudit endpoints (PRD §3.7): verdict, submit, brand decision, revise."""

from flask import Blueprint

import calc
import db
from errors import (
    ApiError,
    ERR_AUDIT_NON_COMPLIANT,
    ERR_CUSTOMER_OWNERSHIP_MISMATCH,
    ERR_INVALID_STATE_TRANSITION,
)
from middleware import ALL_ROLES, authenticate
from response import ok_object
from routes.common import (
    fk_exists,
    get_body,
    get_or_404,
    list_response,
    req_enum,
    req_int,
    req_str,
    ser_plain,
)
from util import touch

bp = Blueprint("retail_audits", __name__)

ORIENTATIONS = ("LENGTHWISE", "WIDTHWISE")

AUDIT_FIELDS = (
    "orientation", "case_w_cin", "case_h_cin", "case_d_cin", "case_weight_g",
    "cases_per_layer", "layers", "case_count",
)


def _read_audit_inputs(data):
    orientation = req_enum(data, "orientation", ORIENTATIONS)
    case_w_cin = req_int(data, "case_w_cin", 1)
    case_h_cin = req_int(data, "case_h_cin", 1)
    case_d_cin = req_int(data, "case_d_cin", 1)
    case_weight_g = req_int(data, "case_weight_g", 1)
    cases_per_layer = req_int(data, "cases_per_layer", 1)
    layers = req_int(data, "layers", 1)
    case_count = req_int(data, "case_count", 1)
    return {
        "orientation": orientation,
        "case_w_cin": case_w_cin,
        "case_h_cin": case_h_cin,
        "case_d_cin": case_d_cin,
        "case_weight_g": case_weight_g,
        "cases_per_layer": cases_per_layer,
        "layers": layers,
        "case_count": case_count,
    }


def _verdict_of(rec):
    return calc.retail_compliance_verdict(
        rec["orientation"], rec["case_w_cin"], rec["case_h_cin"], rec["case_d_cin"],
        rec["case_weight_g"], rec["cases_per_layer"], rec["layers"], rec["case_count"],
    )


@bp.post("/plant/retail-audits")
def create_retail_audit():
    authenticate(("KittingLead",))
    data = get_body()
    fk_exists(db.jobs, data, "job_id")
    job_id = req_str(data, "job_id")
    retailer_code = req_str(data, "retailer_code")
    inputs = _read_audit_inputs(data)

    rec = db.new_record()
    rec.update({"job_id": job_id, "retailer_code": retailer_code})
    rec.update(inputs)
    rec["verdict"] = _verdict_of(rec)
    rec["status"] = "DRAFT"
    db.retail_audits[rec["id"]] = rec
    return ok_object(ser_plain(rec), 201)


@bp.get("/plant/retail-audits")
def list_retail_audits():
    authenticate(ALL_ROLES)
    return list_response(
        db.retail_audits.values(),
        ser_plain,
        [("job_id", "job_id", "str"), ("status", "status", "str")],
    )


@bp.get("/plant/retail-audits/<auditId>")
def get_retail_audit(auditId):
    authenticate(ALL_ROLES)
    return ok_object(ser_plain(get_or_404(db.retail_audits, auditId)))


@bp.post("/plant/retail-audits/<auditId>/submit")
def submit_retail_audit(auditId):
    authenticate(("KittingLead",))
    rec = get_or_404(db.retail_audits, auditId)
    if rec["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Only a DRAFT audit can be submitted")
    if rec["verdict"] != "COMPLIANT":
        raise ApiError(ERR_AUDIT_NON_COMPLIANT, 409,
                       "Audit verdict is NON_COMPLIANT")
    rec["status"] = "SUBMITTED"
    touch(rec)
    return ok_object(ser_plain(rec))


def _brand_decide(auditId, to_status):
    user_id, _role = authenticate(("BrandQuality",))
    rec = get_or_404(db.retail_audits, auditId)
    job = db.jobs[rec["job_id"]]
    if user_id != job["customer_id"]:
        raise ApiError(ERR_CUSTOMER_OWNERSHIP_MISMATCH, 403,
                       "X-User-ID must equal the job's customer_id")
    if rec["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Only a SUBMITTED audit can be decided")
    rec["status"] = to_status
    touch(rec)
    return ok_object(ser_plain(rec))


@bp.post("/plant/retail-audits/<auditId>/certify")
def certify_retail_audit(auditId):
    return _brand_decide(auditId, "CERTIFIED")


@bp.post("/plant/retail-audits/<auditId>/reject")
def reject_retail_audit(auditId):
    return _brand_decide(auditId, "REJECTED")


@bp.post("/plant/retail-audits/<auditId>/revise")
def revise_retail_audit(auditId):
    authenticate(("KittingLead",))
    rec = get_or_404(db.retail_audits, auditId)
    data = get_body()
    inputs = _read_audit_inputs(data)
    if rec["status"] != "REJECTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Only a REJECTED audit can be revised")
    for field in AUDIT_FIELDS:
        rec[field] = inputs[field]
    rec["verdict"] = _verdict_of(rec)
    rec["status"] = "DRAFT"
    touch(rec)
    return ok_object(ser_plain(rec))
