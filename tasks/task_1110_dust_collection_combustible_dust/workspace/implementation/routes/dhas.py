"""DHA endpoints."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_NO_COMBUSTIBLE_DUST,
    ERR_NOT_FOUND,
    ERR_SOD_VIOLATION,
    ERR_STALE_VERSION,
)
from middleware import require_roles
from response import success_object
from services import calculations as calc
from services.common import (
    get_site_or_404,
    init_common,
    paginate,
    parse_body,
    require_fields,
    serialize,
    touch,
    validate_str,
)

bp = Blueprint("dhas", __name__)

READ_ROLES = ("ComplianceEngineer", "ComplianceManager", "InspectorUser")
REVIEW_PERIOD_DAYS = 365


def _get_dha(site_id, dha_id):
    site = get_site_or_404(site_id)
    dha = db.dhas.get(dha_id)
    if dha is None or dha["site_id"] != site["id"]:
        raise ApiError(ERR_NOT_FOUND, f"DHA {dha_id} not found", 404)
    return site, dha


@bp.route("/api/sites/<id>/dhas", methods=["POST"])
def create_dha(id):
    user_id, _ = require_roles("ComplianceEngineer")
    site = get_site_or_404(id)
    body = parse_body()
    require_fields(body, ["title", "author_id"])
    validate_str(body, "title")
    validate_str(body, "author_id")

    dha = {
        "site_id": site["id"],
        "title": body["title"],
        "author_id": body["author_id"],
        "approver_id": None,
        "status": "DRAFT",
        "review_due_at": None,
        "review_due_at_dt": None,
        "overdue": False,
    }
    init_common(dha)
    db.dhas[dha["id"]] = dha
    db.dha_samples[dha["id"]] = []
    calc.dha_kst_rollup(dha)
    calc.dha_risk_score(dha, site)
    return success_object(serialize(dha), 201)


@bp.route("/api/sites/<id>/dhas", methods=["GET"])
def list_dhas(id):
    require_roles(*READ_ROLES)
    site = get_site_or_404(id)
    items = [d for d in db.dhas.values() if d["site_id"] == site["id"]]
    filters = {}
    if request.args.get("status") is not None:
        filters["status"] = "status"
    return paginate(items, filters)


@bp.route("/api/sites/<id>/dhas/<dha_id>", methods=["GET"])
def get_dha(id, dha_id):
    require_roles(*READ_ROLES)
    _, dha = _get_dha(id, dha_id)
    return success_object(serialize(dha), 200)


@bp.route("/api/sites/<id>/dhas/<dha_id>/samples/<sample_id>", methods=["POST"])
def link_sample(id, dha_id, sample_id):
    require_roles("ComplianceEngineer")
    site, dha = _get_dha(id, dha_id)
    sample = db.dust_samples.get(sample_id)
    if sample is None or sample["site_id"] != site["id"]:
        raise ApiError(ERR_NOT_FOUND, f"DustSample {sample_id} not found", 404)
    linked = db.dha_samples.setdefault(dha["id"], [])
    if sample_id not in linked:
        linked.append(sample_id)
    calc.dha_kst_rollup(dha)
    calc.dha_risk_score(dha, site)
    touch(dha)
    return success_object(serialize(dha), 200)


@bp.route("/api/sites/<id>/dhas/<dha_id>/samples/<sample_id>", methods=["DELETE"])
def unlink_sample(id, dha_id, sample_id):
    require_roles("ComplianceEngineer")
    site, dha = _get_dha(id, dha_id)
    sample = db.dust_samples.get(sample_id)
    if sample is None or sample["site_id"] != site["id"]:
        raise ApiError(ERR_NOT_FOUND, f"DustSample {sample_id} not found", 404)
    linked = db.dha_samples.setdefault(dha["id"], [])
    if sample_id in linked:
        linked.remove(sample_id)
    calc.dha_kst_rollup(dha)
    calc.dha_risk_score(dha, site)
    touch(dha)
    return success_object(serialize(dha), 200)


@bp.route("/api/sites/<id>/dhas/<dha_id>/submit", methods=["POST"])
def submit_dha(id, dha_id):
    user_id, _ = require_roles("ComplianceEngineer")
    site, dha = _get_dha(id, dha_id)
    if dha["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "DHA is not in DRAFT", 409)
    if dha["author_id"] != user_id:
        raise ApiError(ERR_SOD_VIOLATION, "Only the author may submit the DHA", 422)
    dha["status"] = "SUBMITTED"
    touch(dha)
    return success_object(serialize(dha), 200)


@bp.route("/api/sites/<id>/dhas/<dha_id>/approve", methods=["POST"])
def approve_dha(id, dha_id):
    user_id, _ = require_roles("ComplianceManager")
    site, dha = _get_dha(id, dha_id)
    if dha["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, "DHA is not SUBMITTED", 409)
    if dha["author_id"] == user_id:
        raise ApiError(ERR_SOD_VIOLATION, "Approver must differ from author", 422)
    if dha.get("kst_class_highest", "ST0") == "ST0":
        raise ApiError(ERR_NO_COMBUSTIBLE_DUST, "No combustible dust sample linked", 422)

    # OCC check — runs after all other validations
    body = parse_body()
    expected = body.get("expected_site_version")
    if expected is not None:
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise ApiError(ERR_STALE_VERSION, "expected_site_version mismatch", 412)
        if expected != site["version"]:
            raise ApiError(ERR_STALE_VERSION, "expected_site_version mismatch", 412)

    dha["approver_id"] = user_id
    review_due = db.now_dt() + timedelta(days=REVIEW_PERIOD_DAYS)
    dha["review_due_at_dt"] = review_due
    dha["review_due_at"] = db.iso(review_due)
    dha["overdue"] = False
    dha["status"] = "APPROVED"
    touch(dha)

    # Supersede any other APPROVED DHA on this site
    for other in db.dhas.values():
        if other["site_id"] == site["id"] and other["id"] != dha["id"] and other["status"] == "APPROVED":
            other["status"] = "SUPERSEDED"
            touch(other)

    site["last_dha_id"] = dha["id"]
    calc.site_posture_derivation(site)
    touch(site)
    return success_object(serialize(dha), 200)


@bp.route("/api/sites/<id>/dhas/<dha_id>/reject", methods=["POST"])
def reject_dha(id, dha_id):
    require_roles("ComplianceManager")
    site, dha = _get_dha(id, dha_id)
    if dha["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, "DHA is not SUBMITTED", 409)
    dha["status"] = "REJECTED"
    touch(dha)
    return success_object(serialize(dha), 200)


@bp.route("/api/sites/<id>/dhas/<dha_id>/revise", methods=["POST"])
def revise_dha(id, dha_id):
    user_id, _ = require_roles("ComplianceEngineer")
    site, dha = _get_dha(id, dha_id)
    if dha["status"] != "REJECTED":
        raise ApiError(ERR_INVALID_STATE, "DHA is not REJECTED", 409)
    if dha["author_id"] != user_id:
        raise ApiError(ERR_SOD_VIOLATION, "Only the author may revise the DHA", 422)
    dha["status"] = "DRAFT"
    touch(dha)
    return success_object(serialize(dha), 200)
