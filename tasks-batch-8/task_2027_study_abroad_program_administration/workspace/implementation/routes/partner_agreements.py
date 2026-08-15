"""Partner agreement endpoints."""

from flask import Blueprint, request
import db
from db import new_id, now_iso
from middleware import get_auth, require_role
from response import success_object
from utils import require_string, require_number, parse_dt
from errors import not_found, invalid_request, invalid_state, ApiError, ERR_AGREEMENT_NOT_ACTIVE

bp = Blueprint("partner_agreements", __name__)


@bp.route("/api/v1/partner-agreements", methods=["POST"])
def create_partner_agreement():
    user_id, role = get_auth()
    require_role(role, ["ProgramCoordinator"])

    body = request.get_json(silent=True) or {}
    host_institution = require_string(body, "host_institution")
    country_code = require_string(body, "country_code")
    effective_from = require_string(body, "effective_from")
    effective_to = require_string(body, "effective_to")
    credit_conversion_factor = require_number(body, "credit_conversion_factor")

    insurance_required = body.get("insurance_required", False)
    if not isinstance(insurance_required, bool):
        raise invalid_request("insurance_required must be a boolean")

    ef = parse_dt(effective_from, "effective_from")
    et = parse_dt(effective_to, "effective_to")
    if not ef < et:
        raise invalid_request("effective_from must be strictly before effective_to")

    if not (credit_conversion_factor > 0):
        raise invalid_request("credit_conversion_factor must be > 0")

    ts = now_iso()
    rec = {
        "id": new_id(),
        "host_institution": host_institution,
        "country_code": country_code,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "credit_conversion_factor": credit_conversion_factor,
        "insurance_required": insurance_required,
        "status": "DRAFT",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.partner_agreements[rec["id"]] = rec
    return success_object(rec, 201)


@bp.route("/api/v1/partner-agreements/<id>/activate", methods=["POST"])
def activate_partner_agreement(id):
    user_id, role = get_auth()
    require_role(role, ["ProgramCoordinator"])

    rec = db.partner_agreements.get(id)
    if not rec:
        raise not_found("PartnerAgreement not found")

    if rec["status"] != "DRAFT":
        raise invalid_state("PartnerAgreement is not in DRAFT status")

    rec["status"] = "ACTIVE"
    rec["version"] += 1
    rec["updated_at"] = now_iso()
    return success_object(rec, 200)
