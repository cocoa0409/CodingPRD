"""Business-unit endpoints."""
from flask import Blueprint, request, g

import db
from errors import APIError, ERR_BAD_REQUEST
from middleware import require_roles
from response import success, success_list
from services import audit, serializers
from services.common import make_versioned, touch, check_version, get_or_404
from utils import get_str, get_int, get_pagination, paginate

bp = Blueprint("business_units", __name__)


@bp.route("/business-units", methods=["POST"])
@require_roles("Admin")
def create_business_unit():
    body = request.get_json(silent=True) or {}
    code = get_str(body, "code", required=True, pattern=r"^[A-Z0-9_]{2,16}$")
    name = get_str(body, "name", required=True)
    annual_budget = get_int(body, "annual_budget_cents", required=True, min_value=0)

    with db.lock():
        if code in db.business_unit_codes:
            raise APIError(ERR_BAD_REQUEST, 422, "Duplicate business unit code")
        bu = make_versioned({
            "code": code,
            "name": name,
            "annual_budget_cents": annual_budget,
            "status": "ACTIVE",
        })
        db.business_units[bu["id"]] = bu
        db.business_unit_codes.add(code)
        audit.emit("BusinessUnit", bu["id"], g.user_role, g.user_id,
                   "STATUS_CHANGE", from_state=None, to_state="ACTIVE")
    return success(serializers.serialize_business_unit(bu), 201)


@bp.route("/business-units", methods=["GET"])
@require_roles("Admin", "FinanceManager", "IPManager", "Counsel")
def list_business_units():
    limit, offset = get_pagination(request.args)
    status_filter = request.args.get("status")
    items = list(db.business_units.values())
    if status_filter:
        items = [b for b in items if b["status"] == status_filter]
    items.sort(key=lambda b: b["created_at"])
    window, total = paginate(items, limit, offset)
    data = [serializers.serialize_business_unit(b) for b in window]
    return success_list(data, limit, offset, total)


@bp.route("/business-units/<bu_id>", methods=["GET"])
@require_roles("Admin", "FinanceManager", "IPManager", "Counsel")
def get_business_unit(bu_id):
    bu = get_or_404(db.business_units, bu_id)
    return success(serializers.serialize_business_unit(bu))


@bp.route("/business-units/<bu_id>/archive", methods=["POST"])
@require_roles("Admin")
def archive_business_unit(bu_id):
    body = request.get_json(silent=True) or {}
    with db.lock():
        bu = get_or_404(db.business_units, bu_id)
        check_version(bu, body)
        prior = bu["status"]
        bu["status"] = "ARCHIVED"
        touch(bu)
        audit.emit("BusinessUnit", bu["id"], g.user_role, g.user_id,
                   "STATUS_CHANGE", from_state=prior, to_state="ARCHIVED")
    return success(serializers.serialize_business_unit(bu))
