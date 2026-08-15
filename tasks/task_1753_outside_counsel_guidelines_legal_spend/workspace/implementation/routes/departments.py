"""LegalDepartment endpoints."""

from flask import Blueprint, request

import db
import errors
import helpers
import response as resp
from middleware import require_auth, ROLE_LEGAL_OPS, ROLE_FIRM_USER

bp = Blueprint("departments", __name__)


@bp.route("/legal-departments", methods=["POST"])
def create_department():
    require_auth([ROLE_LEGAL_OPS])
    body = helpers.get_body()
    helpers.require_fields(body, [
        "name", "annual_rate_increase_cap_pct", "partner_ratio_min_pct",
        "partner_ratio_max_pct", "guideline_notice_days", "acknowledgment_window_days",
    ])
    rec = db.base_resource({
        "name": body["name"],
        "annual_rate_increase_cap_pct": body["annual_rate_increase_cap_pct"],
        "partner_ratio_min_pct": body["partner_ratio_min_pct"],
        "partner_ratio_max_pct": body["partner_ratio_max_pct"],
        "guideline_notice_days": body["guideline_notice_days"],
        "acknowledgment_window_days": body["acknowledgment_window_days"],
    })
    db.legal_departments[rec["id"]] = rec
    return resp.success_object(resp.public(rec), 201)


@bp.route("/legal-departments/<deptId>", methods=["GET"])
def get_department(deptId):
    require_auth([ROLE_LEGAL_OPS, ROLE_FIRM_USER])
    dept = helpers.resolve_department(deptId)
    return resp.success_object(resp.public(dept))


@bp.route("/legal-departments", methods=["GET"])
def list_departments():
    require_auth([ROLE_LEGAL_OPS, ROLE_FIRM_USER])
    limit, offset = resp.parse_pagination(request.args)
    items, total = resp.paginate(list(db.legal_departments.values()), limit, offset)
    return resp.success_list(items, limit, offset, total)
