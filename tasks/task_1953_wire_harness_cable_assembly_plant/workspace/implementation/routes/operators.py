"""Operators and workmanship-class certifications (PRD 3.3)."""
from flask import Blueprint, request

from db import db
from errors import (raise_error, ERR_INVALID_REQUEST, ERR_CERT_WINDOW_OVERLAP,
                    ERR_CERT_EXPIRY_NOT_FUTURE)
from middleware import authenticate, ALL_ROLES
from response import success_object
from services import (WORKMANSHIP_CLASSES, common_fields, touch,
                      ser_operator, ser_certification, paginated)
from util import CLOCK
from validate import get_body, req_str, req_enum, req_dt, require_path, require_fk

bp = Blueprint("operators", __name__)

QUALITY_MANAGER = {"QualityManager"}


@bp.route("/plant/operators", methods=["POST"])
def create_operator():
    body = get_body()
    operator_name = req_str(body, "operator_name")
    badge_no = req_str(body, "badge_no")
    authenticate(QUALITY_MANAGER)
    for o in db["operators"].values():
        if o["badge_no"] == badge_no:
            raise_error(ERR_INVALID_REQUEST, f"duplicate badge_no: {badge_no}")

    op = common_fields()
    op.update({
        "operator_name": operator_name,
        "badge_no": badge_no,
    })
    db["operators"][op["id"]] = op
    return success_object(ser_operator(op), 201)


@bp.route("/plant/operators/<oid>", methods=["GET"])
def get_operator(oid):
    authenticate(ALL_ROLES)
    op = require_path("operators", oid)
    return success_object(ser_operator(op), 200)


@bp.route("/plant/operator-certifications", methods=["POST"])
def create_certification():
    body = get_body()
    # Tier 1: fields, types, enums, and expires_at strictly after issued_at.
    operator_id = req_str(body, "operator_id")
    workmanship_class = req_enum(body, "workmanship_class", WORKMANSHIP_CLASSES)
    issued_at = req_dt(body, "issued_at")
    expires_at = req_dt(body, "expires_at")
    if expires_at <= issued_at:
        raise_error(ERR_INVALID_REQUEST, "expires_at must be strictly after issued_at")
    # Tiers 2-3
    authenticate(QUALITY_MANAGER)
    # Tier 4
    require_fk("operators", operator_id, "operator_id")
    # Tier 9: closed-interval overlap against non-REVOKED certs of the same
    # (operator, class); touching endpoints rejected.
    for c in db["operator_certifications"].values():
        if (c["operator_id"] == operator_id
                and c["workmanship_class"] == workmanship_class
                and c["revoked_at"] is None
                and issued_at <= c["expires_at"]
                and c["issued_at"] <= expires_at):
            raise_error(ERR_CERT_WINDOW_OVERLAP,
                        "certification window overlaps an existing non-REVOKED certification")
    # Tier 10: expiry must lie strictly in the future of the logical clock.
    if expires_at <= CLOCK.now():
        raise_error(ERR_CERT_EXPIRY_NOT_FUTURE,
                    "cannot issue an already-expired certification")

    cert = common_fields()
    cert.update({
        "operator_id": operator_id,
        "workmanship_class": workmanship_class,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "revoked_at": None,
    })
    db["operator_certifications"][cert["id"]] = cert
    return success_object(ser_certification(cert), 201)


@bp.route("/plant/operator-certifications/<cid>", methods=["GET"])
def get_certification(cid):
    authenticate(ALL_ROLES)
    cert = require_path("operator_certifications", cid)
    return success_object(ser_certification(cert), 200)


@bp.route("/plant/operator-certifications", methods=["GET"])
def list_certifications():
    authenticate(ALL_ROLES)
    items = list(db["operator_certifications"].values())
    operator_id = request.args.get("operator_id")
    if operator_id is not None:
        items = [c for c in items if c["operator_id"] == operator_id]
    workmanship_class = request.args.get("workmanship_class")
    if workmanship_class is not None:
        items = [c for c in items if c["workmanship_class"] == workmanship_class]
    return paginated(items, ser_certification)


@bp.route("/plant/operator-certifications/<cid>/revoke", methods=["POST"])
def revoke_certification(cid):
    get_body()
    authenticate(QUALITY_MANAGER)
    cert = require_path("operator_certifications", cid)
    if cert["revoked_at"] is not None:
        raise_error(ERR_INVALID_REQUEST, "certification is already revoked")
    cert["revoked_at"] = CLOCK.now()
    touch(cert)
    return success_object(ser_certification(cert), 200)
