"""Routes: TEFRA direction attestations."""
from flask import Blueprint, request

from store import db
from errors import ApiError
from envelope import ok, ok_list
from validate import auth, get_body, check_body, sort_and_page, apply_filters
import serializers as ser

bp = Blueprint("attestations", __name__, url_prefix="/anesthesia-ops")

ALL = ["GroupAdministrator", "Scheduler", "AttendingAnesthesiologist", "CRNA",
       "BillingSpecialist", "ComplianceAuditor"]

STEP_FIELDS = [
    "step_preanesthetic_exam",
    "step_prescribes_plan",
    "step_participates_key_portions",
    "step_ensures_qualified_personnel",
    "step_monitors_course",
    "step_available_for_emergencies",
    "step_post_anesthesia_care",
]


def _get_attestation(att_id):
    rec = db.attestations.get(att_id)
    if rec is None:
        raise ApiError("ERR_ATTESTATION_NOT_FOUND", 404, "Attestation not found")
    return rec


@bp.post("/attestations")
def create_attestation():
    uid, role = auth(["Scheduler", "AttendingAnesthesiologist"])
    body = get_body()
    check_body(body, {
        "case_id": {"kind": "str", "req": True},
        "physician_id": {"kind": "str", "req": True},
    })
    case = db.cases.get(body["case_id"])
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND", 404, "Case not found")
    physician = db.providers.get(body["physician_id"])
    if physician is None:
        raise ApiError("ERR_PROVIDER_NOT_FOUND", 404, "Provider not found")
    if physician["provider_type"] != "ANESTHESIOLOGIST":
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "physician_id must reference an ANESTHESIOLOGIST")
    if role == "AttendingAnesthesiologist" and uid != body["physician_id"]:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "A physician may create attestations only for themselves")
    for a in db.attestations.values():
        if a["case_id"] == body["case_id"] and a["physician_id"] == body["physician_id"]:
            raise ApiError("ERR_DUPLICATE_ATTESTATION", 409,
                           "An attestation already exists for this case and physician")
    fields = {f: False for f in STEP_FIELDS}
    rec = db.new_record(case_id=body["case_id"], physician_id=body["physician_id"],
                        submitted_count=0, rejection_reason=None,
                        status="IN_PROGRESS", **fields)
    db.attestations[rec["id"]] = rec
    return ok(ser.attestation(rec), 201)


@bp.get("/attestations")
def list_attestations():
    auth(ALL)
    items = apply_filters(db.attestations.values(), request.args,
                          ["case_id", "physician_id", "status"])
    page, limit, offset, total = sort_and_page(items, request.args)
    return ok_list([ser.attestation(r) for r in page], limit, offset, total)


@bp.get("/attestations/<att_id>")
def get_attestation(att_id):
    auth(ALL)
    return ok(ser.attestation(_get_attestation(att_id)))


@bp.post("/attestations/<att_id>/submit")
def submit_attestation(att_id):
    uid, _ = auth(["AttendingAnesthesiologist"])
    body = get_body()
    spec = {f: {"kind": "bool", "req": True} for f in STEP_FIELDS}
    check_body(body, spec)
    rec = _get_attestation(att_id)
    if uid != rec["physician_id"]:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", 403,
                       "Only the attesting physician may submit")
    if rec["status"] not in ("IN_PROGRESS", "REJECTED"):
        raise ApiError("ERR_ATTESTATION_NOT_SUBMITTABLE", 409,
                       "Submit requires status IN_PROGRESS or REJECTED")
    if not all(body[f] is True for f in STEP_FIELDS):
        raise ApiError("ERR_TEFRA_STEPS_INCOMPLETE", 422,
                       "All seven TEFRA step booleans must be true")
    for f in STEP_FIELDS:
        rec[f] = body[f]
    rec["status"] = "SUBMITTED"
    rec["submitted_count"] += 1
    rec["rejection_reason"] = None
    db.bump(rec)
    return ok(ser.attestation(rec))


@bp.post("/attestations/<att_id>/verify")
def verify_attestation(att_id):
    uid, _ = auth(["AttendingAnesthesiologist"])
    get_body()
    rec = _get_attestation(att_id)
    if uid == rec["physician_id"]:
        raise ApiError("ERR_SELF_REVIEW_FORBIDDEN", 403,
                       "The attesting physician cannot review their own attestation")
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_ATTESTATION_NOT_SUBMITTED", 409,
                       "Verify requires status SUBMITTED")
    rec["status"] = "VERIFIED"
    db.bump(rec)
    return ok(ser.attestation(rec))


@bp.post("/attestations/<att_id>/reject")
def reject_attestation(att_id):
    uid, _ = auth(["AttendingAnesthesiologist"])
    body = get_body()
    check_body(body, {"rejection_reason": {"kind": "str", "req": True}})
    rec = _get_attestation(att_id)
    if uid == rec["physician_id"]:
        raise ApiError("ERR_SELF_REVIEW_FORBIDDEN", 403,
                       "The attesting physician cannot review their own attestation")
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_ATTESTATION_NOT_SUBMITTED", 409,
                       "Reject requires status SUBMITTED")
    rec["status"] = "REJECTED"
    rec["rejection_reason"] = body["rejection_reason"]
    db.bump(rec)
    return ok(ser.attestation(rec))
