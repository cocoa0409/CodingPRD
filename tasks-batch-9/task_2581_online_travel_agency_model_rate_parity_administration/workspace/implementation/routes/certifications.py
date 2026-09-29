"""Certification: content-quality and connectivity adjudication (PRD 3.1)."""
from flask import Blueprint

import auth
import calc
import cascade
import clock
import response
import store
import validate
from errors import ApiError
from store import db, touch

from routes import common

bp = Blueprint("certifications", __name__)

PROTOCOLS = ("OTA_2011B", "JSON_V2", "GDS_EDIFACT")
DECISIONS = ("CERTIFY", "PROVISIONAL", "REJECT")
STATUSES = ("SUBMITTED", "IN_REVIEW", "CERTIFIED", "PROVISIONAL", "REJECTED",
            "REMEDIATION_SUBMITTED", "EXPIRED", "REVOKED")
LIVE_STATUSES = ("CERTIFIED", "PROVISIONAL")
CERT_CONTENT_PASS = 0
CERT_CONNECTIVITY_PASS = 0


@bp.post("/suppliers/<supplier_id>/certifications")
def create_certification(supplier_id):
    actor = auth.authenticate(("SupplierUser", "CommercialManager"))
    auth.require_supplier_scope(actor, supplier_id)
    supplier = common.find("suppliers", supplier_id)
    data = validate.body()
    claimed = validate.num_req(data, "content_score_claimed", 0, 100)
    protocol = validate.enum_req(data, "connectivity_protocol", PROTOCOLS)
    payload_ref = validate.str_req(data, "sample_payload_ref")
    common.guard_offboarded(supplier)
    certification = store.new_row("certifications", {
        "supplier_id": supplier["id"],
        "content_score_claimed": claimed,
        "connectivity_protocol": protocol,
        "sample_payload_ref": payload_ref,
        "content_score": None,
        "connectivity_score": None,
        "decision": None,
        "status": "SUBMITTED",
        "remediation_rounds": 0,
        "expires_at": None,
        "reviewed_by_user_id": None,
        "revocation_reason": None,
    })
    return response.obj(certification, 201)


@bp.get("/certifications/<certification_id>")
def read_certification(certification_id):
    auth.authenticate(auth.ALL_ROLES)
    return response.obj(common.find("certifications", certification_id), 200)


@bp.get("/certifications")
def list_certifications():
    auth.authenticate(auth.ALL_ROLES)
    supplier_id = validate.filter_str("supplier_id")
    status = validate.filter_enum("status", STATUSES)
    decision = validate.filter_enum("decision", DECISIONS)
    rows = []
    for row in db["certifications"].values():
        if supplier_id is not None and row["supplier_id"] != supplier_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if decision is not None and row["decision"] != decision:
            continue
        rows.append(row)
    return common.paged(rows)


@bp.post("/certifications/<certification_id>/start-review")
def start_review(certification_id):
    auth.authenticate(("ComplianceOfficer",))
    certification = common.find("certifications", certification_id)
    data = validate.body()
    validate.str_opt(data, "note")
    supplier = db["suppliers"].get(certification["supplier_id"])
    if certification["status"] not in ("SUBMITTED", "REMEDIATION_SUBMITTED"):
        raise ApiError("ERR_CERT_NOT_REVIEWABLE")
    common.guard_offboarded(supplier)
    certification["status"] = "IN_REVIEW"
    touch(certification)
    return response.obj(certification, 200)


@bp.post("/certifications/<certification_id>/decide")
def decide(certification_id):
    actor = auth.authenticate(("ComplianceOfficer",))
    certification = common.find("certifications", certification_id)
    data = validate.body()
    decision = validate.enum_req(data, "decision", DECISIONS)
    content_score = validate.num_req(data, "content_score", 0, 100)
    connectivity_score = validate.num_req(data, "connectivity_score", 0, 100)
    validate.str_opt(data, "note")
    supplier = db["suppliers"].get(certification["supplier_id"])
    if certification["status"] != "IN_REVIEW":
        raise ApiError("ERR_CERT_NOT_DECIDED")
    common.guard_offboarded(supplier)
    certification["content_score"] = content_score
    certification["connectivity_score"] = connectivity_score
    certification["decision"] = decision
    certification["reviewed_by_user_id"] = actor.user_id
    if decision == "CERTIFY":
        certification["status"] = "CERTIFIED"
        certification["expires_at"] = clock.iso(clock.plus_days(clock.now(), calc.CERT_VALID_DAYS))
    elif decision == "PROVISIONAL":
        certification["status"] = "PROVISIONAL"
        certification["expires_at"] = clock.iso(
            clock.plus_days(clock.now(), calc.PROVISIONAL_VALID_DAYS))
    else:
        certification["status"] = "REJECTED"
        certification["expires_at"] = None
    touch(certification)
    if decision in ("CERTIFY", "PROVISIONAL") and supplier is not None:
        supplier["certification_level"] = "CERTIFIED" if decision == "CERTIFY" else "PROVISIONAL"
        supplier["content_score"] = content_score
        supplier["connectivity_score"] = connectivity_score
        supplier["_backing_cert_id"] = certification["id"]
        if supplier["visibility_status"] == "PENDING_CERT":
            supplier["visibility_status"] = "ACTIVE"
        touch(supplier)
    return response.obj(certification, 200)


@bp.post("/certifications/<certification_id>/remediate")
def remediate(certification_id):
    actor = auth.authenticate(("SupplierUser",))
    certification = common.find("certifications", certification_id)
    auth.require_supplier_scope(actor, certification["supplier_id"])
    data = validate.body()
    claimed = validate.num_req(data, "content_score_claimed", 0, 100)
    payload_ref = validate.str_req(data, "sample_payload_ref")
    validate.str_opt(data, "note")
    supplier = db["suppliers"].get(certification["supplier_id"])
    if certification["status"] != "REJECTED":
        raise ApiError("ERR_CERT_NOT_REJECTED")
    common.guard_offboarded(supplier)
    if certification["remediation_rounds"] >= calc.CERT_MAX_REMEDIATION_ROUNDS:
        raise ApiError("ERR_REMEDIATION_LIMIT")
    certification["status"] = "REMEDIATION_SUBMITTED"
    certification["content_score_claimed"] = claimed
    certification["sample_payload_ref"] = payload_ref
    certification["remediation_rounds"] += 1
    touch(certification)
    return response.obj(certification, 200)


@bp.post("/certifications/<certification_id>/revoke")
def revoke(certification_id):
    auth.authenticate(("ComplianceOfficer",))
    certification = common.find("certifications", certification_id)
    data = validate.body()
    reason = validate.str_req(data, "revocation_reason")
    supplier = db["suppliers"].get(certification["supplier_id"])
    if certification["status"] not in LIVE_STATUSES:
        raise ApiError("ERR_CERT_NOT_DECIDED")
    common.guard_offboarded(supplier)
    backing = supplier is not None and supplier.get("_backing_cert_id") == certification["id"]
    certification["status"] = "REVOKED"
    certification["revocation_reason"] = reason
    touch(certification)
    if backing:
        cascade.suspend_supplier(supplier, "CERTIFICATION_REVOKED")
    return response.obj(certification, 200)
