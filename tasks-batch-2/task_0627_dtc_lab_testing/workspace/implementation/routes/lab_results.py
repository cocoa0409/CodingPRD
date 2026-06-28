"""Lab results: acknowledge-critical, release, amend (PRD §3.8)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import require_role
from response import success, list_success
from services.common import (
    serialize, serialize_list, get_json, require_found, require_number, paginate,
)
from services.orders import line_terminal_cascade
from services.results import final_flag, mint_referral, open_referral_for_result

bp = Blueprint("lab_results", __name__)


@bp.route("/catalog/lab-results", methods=["GET"])
def list_lab_results():
    user_id, role = require_role(["LabTech", "CatalogAdmin", "Patient"])
    rows = db.sorted_rows(db.all_rows("lab_results"))
    specimen_id = request.args.get("specimen_id")
    order_line_id = request.args.get("order_line_id")
    patient_id = request.args.get("patient_id")
    if specimen_id:
        rows = [r for r in rows if r["specimen_id"] == specimen_id]
    if order_line_id:
        rows = [r for r in rows if r["order_line_id"] == order_line_id]
    if patient_id:
        rows = [r for r in rows if r["patient_id"] == patient_id]
    if role == "Patient":
        rows = [r for r in rows if r["patient_id"] == user_id]
    page, limit, offset, total = paginate(rows)
    return list_success(serialize_list(page), limit, offset, total)


@bp.route("/catalog/lab-results/<rid>", methods=["GET"])
def get_lab_result(rid):
    user_id, role = require_role(["LabTech", "CatalogAdmin", "Patient"])
    rec = require_found("lab_results", rid)
    if role == "Patient" and user_id != rec["patient_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Not the owning patient")
    return success(serialize(rec))


@bp.route("/catalog/lab-results/<rid>/acknowledge-critical", methods=["POST"])
def acknowledge_critical(rid):
    require_role(["LabTech"])
    rec = require_found("lab_results", rid)
    rec["critical_acknowledged"] = True
    db.touch(rec)
    return success(serialize(rec))


def _offering_for_result(result):
    line = db.get("order_lines", result["order_line_id"])
    if line is None:
        return {}
    return db.get("test_offerings", line["test_offering_id"]) or {}


def _do_referral_cascade(result):
    """Mint an OPEN referral when final_flag is ABNORMAL/CRITICAL and the patient
    has consented (PRD §3.8). Skipped silently when consent is absent."""
    if result["final_flag"] not in ("ABNORMAL", "CRITICAL"):
        return
    patient = db.get("patients", result["patient_id"])
    if patient is None or not patient.get("consent_share_results"):
        return
    if open_referral_for_result(result["id"]) is None:
        mint_referral(result)


@bp.route("/catalog/lab-results/<rid>/release", methods=["POST"])
def release(rid):
    user_id, role = require_role(["LabTech"])
    result = require_found("lab_results", rid)

    # Releasable only from PROCESSING or PENDING_CRITICAL_CALLBACK.
    if result["status"] not in ("PROCESSING", "PENDING_CRITICAL_CALLBACK"):
        raise err("ERR_RESULT_NOT_RELEASABLE", "Result not releasable")
    # A CRITICAL provisional must be acknowledged first.
    if result["provisional_flag"] == "CRITICAL" and not result.get("critical_acknowledged"):
        raise err("ERR_CRITICAL_CALLBACK_REQUIRED", "Critical callback required")
    # Segregation of duties.
    specimen = db.get("specimens", result["specimen_id"])
    if specimen is not None and user_id == specimen.get("collected_by_user_id"):
        raise err("ERR_SOD_COLLECTOR_CANNOT_RELEASE", "Collector cannot release")

    offering = _offering_for_result(result)
    result["final_flag"] = final_flag(result, offering)
    result["status"] = "RELEASED"
    db.touch(result)

    # Cascade hop 1: OrderLine -> RESULTED; Specimen -> RESULTED.
    line = db.get("order_lines", result["order_line_id"])
    if line is not None and line["status"] == "COLLECTED":
        line["status"] = "RESULTED"
        db.touch(line)
    if specimen is not None:
        specimen["status"] = "RESULTED"
        db.touch(specimen)

    # Cascade hop 2: invoice recompute + fulfillment bubble.
    order = db.get("orders", line["order_id"]) if line else None
    if order is not None:
        line_terminal_cascade(order)

    # Cascade hop 3: telehealth referral (consent permitting).
    _do_referral_cascade(result)

    return success(serialize(result))


@bp.route("/catalog/lab-results/<rid>/amend", methods=["POST"])
def amend(rid):
    require_role(["LabTech"])
    result = require_found("lab_results", rid)
    body = get_json()
    analyzer_value = require_number(body, "analyzer_value")

    # Amend only from RELEASED.
    if result["status"] != "RELEASED":
        raise err("ERR_RESULT_NOT_AMENDABLE", "Result not amendable")

    result["analyzer_value"] = analyzer_value
    offering = _offering_for_result(result)
    from services.results import provisional_flag
    result["provisional_flag"] = provisional_flag(analyzer_value, offering)
    result["final_flag"] = final_flag(result, offering)
    result["status"] = "AMENDED"
    db.touch(result)

    # Escalated to ABNORMAL/CRITICAL and no open referral -> mint (consent permitting).
    _do_referral_cascade(result)
    return success(serialize(result))
