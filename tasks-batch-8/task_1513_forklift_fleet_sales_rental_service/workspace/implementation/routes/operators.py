"""Operator and certification endpoints."""
from flask import Blueprint

import clock
import store
from auth import authenticate, authorize, ALL_ROLES
from errors import raise_err, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_INVALID_STATE
from util import (
    body_json, req_str, req_datetime, new_record, bump,
    success_object, list_response, get_or_404,
)
import services

bp = Blueprint("operators", __name__)


@bp.post("/fleet/operators")
def create_operator():
    _, role = authenticate()
    authorize(role, ["TrainingRegistrar"])
    body = body_json()
    customer_id = req_str(body, "customer_id")
    full_name = req_str(body, "full_name")
    badge_number = req_str(body, "badge_number")
    get_or_404(store.customers, customer_id, "Customer")
    rec = new_record()
    rec.update({
        "customer_id": customer_id,
        "full_name": full_name,
        "badge_number": badge_number,
    })
    store.operators[rec["id"]] = rec
    return success_object(services.serialize_operator(rec), 201)


@bp.get("/fleet/operators/<oid>")
def get_operator(oid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    op = get_or_404(store.operators, oid, "Operator")
    return success_object(services.serialize_operator(op), 200)


@bp.post("/fleet/operators/<oid>/certifications")
def issue_certification(oid):
    _, role = authenticate()
    authorize(role, ["TrainingRegistrar"])
    body = body_json()
    cert_class = req_str(body, "cert_class")
    if cert_class not in ("SIT_DOWN", "STAND_UP", "ORDER_PICKER"):
        raise_err(ERR_INVALID_REQUEST, "cert_class must be SIT_DOWN, STAND_UP, or ORDER_PICKER")
    expires_at = req_datetime(body, "expires_at")
    op = get_or_404(store.operators, oid, "Operator")
    if expires_at <= clock.now():
        raise_err(ERR_INVALID_REQUEST, "expires_at must be after the logical clock")
    rec = new_record()
    rec.update({
        "operator_id": op["id"],
        "cert_class": cert_class,
        "issued_at": clock.now(),
        "expires_at": expires_at,
        "renewed_count": 0,
        "status": "ACTIVE",
    })
    store.certifications[rec["id"]] = rec
    return success_object(services.serialize_certification(rec), 201)


@bp.get("/fleet/operators/<oid>/certifications")
def list_certifications(oid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    op = get_or_404(store.operators, oid, "Operator")
    certs = [c for c in store.certifications.values() if c["operator_id"] == op["id"]]
    return list_response(certs, services.serialize_certification)


@bp.post("/fleet/certifications/<cid>/renew")
def renew_certification(cid):
    _, role = authenticate()
    authorize(role, ["TrainingRegistrar"])
    body = body_json()
    new_expires_at = req_datetime(body, "new_expires_at")
    cert = get_or_404(store.certifications, cid, "Certification")
    if new_expires_at <= clock.now():
        raise_err(ERR_INVALID_REQUEST, "new_expires_at must be after the logical clock")
    if cert["status"] not in ("ACTIVE", "EXPIRED"):
        raise_err(ERR_INVALID_STATE, "Only ACTIVE or EXPIRED certifications may be renewed")
    cert["expires_at"] = new_expires_at
    cert["renewed_count"] = cert.get("renewed_count", 0) + 1
    cert["status"] = "ACTIVE"
    bump(cert)
    return success_object(services.serialize_certification(cert), 200)


@bp.post("/fleet/certifications/<cid>/revoke")
def revoke_certification(cid):
    _, role = authenticate()
    authorize(role, ["TrainingRegistrar"])
    cert = get_or_404(store.certifications, cid, "Certification")
    if cert["status"] not in ("ACTIVE", "EXPIRED"):
        raise_err(ERR_INVALID_STATE, "Only ACTIVE or EXPIRED certifications may be revoked")
    cert["status"] = "REVOKED"
    bump(cert)
    return success_object(services.serialize_certification(cert), 200)
