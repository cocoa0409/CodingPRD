"""International repatriation documentation (PRD §3.7)."""

from flask import Blueprint

import services
from core import (
    ERR_DOC_EXPIRED, ERR_DOCS_INCOMPLETE, ERR_DUPLICATE_REPATRIATION_CASE,
    ERR_INVALID_STATE, db, fail, get_body, list_response, must_exist,
    ok_object, require_roles, stamp_new, touch, v_dt, v_enum, v_str,
)
from serialize import ser_repatriation_case

bp = Blueprint("repatriation", __name__)

ALL_ROLES = ("OpsAdmin", "Dispatcher", "MedicalDirector", "FlightCrew",
             "BillingSpecialist", "QaReviewer")

DOC_TYPES = {"PASSPORT", "VISA", "FIT_TO_FLY", "CUSTOMS_PRECLEARANCE"}
CASE_STATUSES = {"COLLECTING", "READY_TO_FLY"}


@bp.route("/air-ambulance/repatriation-cases", methods=["POST"])
def create_case():
    require_roles("Dispatcher")
    body = get_body()
    if body.get("mission_id") is not None:
        must_exist(db.missions, body["mission_id"], "Mission")
    mission_id = v_str(body, "mission_id")
    if any(c["mission_id"] == mission_id for c in db.repatriation_cases.values()):
        fail(ERR_DUPLICATE_REPATRIATION_CASE, 409,
             "A repatriation case already exists for this mission")
    rec = stamp_new({
        "mission_id": mission_id,
        "destination_country": v_str(body, "destination_country"),
        "receiving_facility": v_str(body, "receiving_facility"),
        "documents": [],
        "status": "COLLECTING",
    })
    db.repatriation_cases[rec["id"]] = rec
    return ok_object(ser_repatriation_case(rec), 201)


@bp.route("/air-ambulance/repatriation-cases/<rid>", methods=["GET"])
def get_case(rid):
    require_roles(*ALL_ROLES)
    rec = must_exist(db.repatriation_cases, rid, "RepatriationCase")
    return ok_object(ser_repatriation_case(rec))


@bp.route("/air-ambulance/repatriation-cases", methods=["GET"])
def list_cases():
    require_roles(*ALL_ROLES)
    return list_response(
        db.repatriation_cases.values(), ser_repatriation_case,
        {"mission_id": "mission_id", "status": "status"},
    )


@bp.route("/air-ambulance/repatriation-cases/<rid>/documents", methods=["POST"])
def append_document(rid):
    require_roles("Dispatcher")
    rec = must_exist(db.repatriation_cases, rid, "RepatriationCase")
    body = get_body()
    doc_type = v_enum(body, "doc_type", DOC_TYPES)
    doc_number = v_str(body, "document_number")
    issued_raw, issued = v_dt(body, "issued_iso")
    expires_raw = body.get("expires_iso")
    expires = None
    if expires_raw is not None:
        expires_raw, expires = v_dt(body, "expires_iso")
    doc = {
        "doc_type": doc_type,
        "document_number": doc_number,
        "issued_iso": issued_raw,
        "_issued_dt": issued,
    }
    if expires_raw is not None:
        doc["expires_iso"] = expires_raw
        doc["_expires_dt"] = expires
    rec["documents"].append(doc)
    touch(rec)
    return ok_object(ser_repatriation_case(rec), 201)


@bp.route("/air-ambulance/repatriation-cases/<rid>/verify", methods=["POST"])
def verify_case(rid):
    require_roles("MedicalDirector")
    rec = must_exist(db.repatriation_cases, rid, "RepatriationCase")
    get_body()
    if rec["status"] != "COLLECTING":
        fail(ERR_INVALID_STATE, 409,
             "RepatriationCase status %s cannot be verified" % rec["status"])
    # validity runs BEFORE completeness so an expired document surfaces ahead
    # of a missing one
    if not services.documents_valid(rec):
        fail(ERR_DOC_EXPIRED, 422, "A required document is expired or too old")
    if not services.documents_complete(rec):
        fail(ERR_DOCS_INCOMPLETE, 422,
             "All four document types must be present")
    rec["status"] = "READY_TO_FLY"
    touch(rec)
    return ok_object(ser_repatriation_case(rec))
