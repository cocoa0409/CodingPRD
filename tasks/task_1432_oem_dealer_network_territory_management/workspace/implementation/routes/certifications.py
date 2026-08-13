"""Certification endpoints: register, decide (verify/reject), expire."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_DATE_RANGE,
    ERR_DEALER_NOT_FOUND,
    ERR_CERTIFICATION_NOT_FOUND,
    ERR_DEALER_IDENTITY_MISMATCH,
    ERR_CERT_INVALID_STATE,
    ERR_CERT_NOT_YET_EXPIRED,
)
from middleware import require_roles
from response import success_object, success_list
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_date,
    parse_pagination,
    require_date,
    require_enum,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("certifications", __name__)


def get_certification_or_404(certification_id: str) -> dict:
    cert = db.certifications.get(certification_id)
    if cert is None:
        raise_err(ERR_CERTIFICATION_NOT_FOUND, "Certification id does not exist")
    return cert


@bp.route("/certifications", methods=["POST"])
@require_roles("DealerUser")
def create_certification(_user_id: str, _role: str):
    body = get_json_body()
    dealer_id = require_string(body, "dealer_id")
    cert_code = require_string(body, "cert_code")
    earned_on = require_date(body, "earned_on")
    expires_on = require_date(body, "expires_on")
    # Priority 3 input format: end strictly after start.
    if parse_date(expires_on, "expires_on") <= parse_date(earned_on, "earned_on"):
        raise_err(ERR_INVALID_DATE_RANGE, "expires_on must be strictly after earned_on")

    # Priority 4 existence.
    if dealer_id not in db.dealers:
        raise_err(ERR_DEALER_NOT_FOUND, "Dealer id does not exist")

    # Priority 5 ownership.
    if dealer_id != _user_id:
        raise_err(ERR_DEALER_IDENTITY_MISMATCH, "DealerUser body dealer_id != X-User-ID")

    cert = {
        "dealer_id": dealer_id,
        "cert_code": cert_code,
        "earned_on": earned_on,
        "expires_on": expires_on,
        "status": "PENDING_VERIFICATION",
    }
    db.stamp_new(cert)
    db.certifications[cert["id"]] = cert
    return success_object(serialize(cert), 201)


@bp.route("/certifications", methods=["GET"])
@require_roles("Any")
def list_certifications(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.certifications.values()))
    items = apply_filters(items, ["dealer_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/certifications/<certification_id>", methods=["GET"])
@require_roles("Any")
def get_certification(certification_id: str, _user_id: str, _role: str):
    cert = get_certification_or_404(certification_id)
    return success_object(serialize(cert))


@bp.route("/certifications/<certification_id>/decide", methods=["POST"])
@require_roles("OemAuditor")
def decide_certification(certification_id: str, _user_id: str, _role: str):
    body = get_json_body()
    decision = require_enum(body, "decision", {"VERIFY", "REJECT"})
    cert = get_certification_or_404(certification_id)
    if cert["status"] != "PENDING_VERIFICATION":
        raise_err(ERR_CERT_INVALID_STATE, "decide requires certification PENDING_VERIFICATION")
    cert["status"] = "ACTIVE" if decision == "VERIFY" else "REJECTED"
    db.touch(cert)
    return success_object(serialize(cert))


@bp.route("/certifications/<certification_id>/expire", methods=["POST"])
@require_roles("OemAuditor")
def expire_certification(certification_id: str, _user_id: str, _role: str):
    cert = get_certification_or_404(certification_id)
    # Priority 6 state.
    if cert["status"] != "ACTIVE":
        raise_err(ERR_CERT_INVALID_STATE, "expire requires certification ACTIVE")
    # Priority 9 temporal: current logical date must be past expires_on.
    if db.clock_date() <= parse_date(cert["expires_on"], "expires_on"):
        raise_err(ERR_CERT_NOT_YET_EXPIRED, "Expire requires current logical date > expires_on")
    cert["status"] = "EXPIRED"
    db.touch(cert)
    return success_object(serialize(cert))
