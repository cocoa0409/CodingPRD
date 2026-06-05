"""Traveler and Approver routes."""
from flask import Blueprint

from common import (get_json_body, require_fields, require_string,
                    require_nonneg_int, paginate, list_response)
from db import store, base_fields
from middleware import require_roles
from response import success
from services import get_or_404

bp = Blueprint("users", __name__)


def _traveler_view(t):
    return dict(t)


def _approver_view(a):
    return dict(a)


# ---- Traveler ----

@bp.route("/travelers", methods=["POST"])
@require_roles("FinanceAdmin")
def create_traveler():
    body = get_json_body()
    require_fields(body, ["email", "full_name", "home_office_state", "manager_id"])
    email = require_string(body, "email")
    full_name = require_string(body, "full_name")
    home_office_state = require_string(body, "home_office_state")
    manager_id = require_string(body, "manager_id")
    # FK: manager_id must resolve to an existing Approver
    get_or_404(store.approvers, manager_id)
    t = base_fields()
    t.update({
        "email": email,
        "full_name": full_name,
        "home_office_state": home_office_state,
        "manager_id": manager_id,
        "status": "ACTIVE",
    })
    store.travelers[t["id"]] = t
    return success(_traveler_view(t), status=201)


@bp.route("/travelers/<traveler_id>", methods=["GET"])
@require_roles("FinanceAdmin", "Traveler", "Approver")
def get_traveler(traveler_id):
    t = get_or_404(store.travelers, traveler_id)
    return success(_traveler_view(t))


@bp.route("/travelers", methods=["GET"])
@require_roles("FinanceAdmin", "Approver")
def list_travelers():
    from flask import request
    limit, offset = paginate()
    items = list(store.travelers.values())
    manager_id = request.args.get("manager_id")
    if manager_id is not None:
        items = [t for t in items if t["manager_id"] == manager_id]
    page, pagination = list_response(items, limit, offset)
    return success([_traveler_view(t) for t in page], pagination=pagination)


# ---- Approver ----

@bp.route("/approvers", methods=["POST"])
@require_roles("FinanceAdmin")
def create_approver():
    body = get_json_body()
    require_fields(body, ["email", "full_name", "approval_limit_cents"])
    email = require_string(body, "email")
    full_name = require_string(body, "full_name")
    approval_limit = require_nonneg_int(body, "approval_limit_cents")
    a = base_fields()
    a.update({
        "email": email,
        "full_name": full_name,
        "approval_limit_cents": approval_limit,
        "status": "ACTIVE",
    })
    store.approvers[a["id"]] = a
    return success(_approver_view(a), status=201)


@bp.route("/approvers/<approver_id>", methods=["GET"])
@require_roles("FinanceAdmin", "Approver")
def get_approver(approver_id):
    a = get_or_404(store.approvers, approver_id)
    return success(_approver_view(a))
