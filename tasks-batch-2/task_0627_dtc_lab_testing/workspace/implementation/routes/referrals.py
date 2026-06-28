"""Telehealth referrals (PRD §3.8)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import require_role
from response import success, list_success
from services.common import (
    serialize, serialize_list, get_json, require_found, require_str, paginate,
)
from services.results import mint_referral

bp = Blueprint("referrals", __name__)


@bp.route("/catalog/telehealth-referrals", methods=["POST"])
def create_referral():
    require_role(["LabTech", "CatalogAdmin"])
    body = get_json()
    lab_result_id = require_str(body, "lab_result_id")
    result = require_found("lab_results", lab_result_id)

    # Manual creation against a released abnormal/critical result; consent gated.
    patient = db.get("patients", result["patient_id"])
    if patient is None or not patient.get("consent_share_results"):
        raise err("ERR_CONSENT_REQUIRED", "Patient has not consented to share results")

    ref = mint_referral(result)
    return success(serialize(ref), status=201)


@bp.route("/catalog/telehealth-referrals", methods=["GET"])
def list_referrals():
    user_id, role = require_role(["LabTech", "CatalogAdmin", "Patient"])
    rows = db.sorted_rows(db.all_rows("telehealth_referrals"))
    lab_result_id = request.args.get("lab_result_id")
    patient_id = request.args.get("patient_id")
    if lab_result_id:
        rows = [r for r in rows if r["lab_result_id"] == lab_result_id]
    if patient_id:
        rows = [r for r in rows if r["patient_id"] == patient_id]
    if role == "Patient":
        rows = [r for r in rows if r["patient_id"] == user_id]
    page, limit, offset, total = paginate(rows)
    return list_success(serialize_list(page), limit, offset, total)


@bp.route("/catalog/telehealth-referrals/<rid>", methods=["GET"])
def get_referral(rid):
    user_id, role = require_role(["LabTech", "CatalogAdmin", "Patient"])
    rec = require_found("telehealth_referrals", rid)
    if role == "Patient" and user_id != rec["patient_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Not the owning patient")
    return success(serialize(rec))


@bp.route("/catalog/telehealth-referrals/<rid>/schedule", methods=["POST"])
def schedule_referral(rid):
    user_id, role = require_role(["Patient", "CatalogAdmin"])
    rec = require_found("telehealth_referrals", rid)
    if role == "Patient" and user_id != rec["patient_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Not the owning patient")
    # OPEN -> SCHEDULED (PRD §3.8). No catalog error is defined for this
    # transition, so it is applied when the referral is OPEN.
    rec["status"] = "SCHEDULED"
    db.touch(rec)
    return success(serialize(rec))
