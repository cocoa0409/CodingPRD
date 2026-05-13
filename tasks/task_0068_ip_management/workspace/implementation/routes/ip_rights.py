"""IPRight + nested resources endpoints."""
from flask import Blueprint, request, g

import db
from errors import APIError, ERR_NOT_FOUND, ERR_INVALID_STATE
from middleware import require_roles
from response import success, success_list
from services import serializers, ip_right_logic
from services.common import check_version, get_or_404
from utils import get_pagination, paginate

bp = Blueprint("ip_rights", __name__)


@bp.route("/ip-rights", methods=["POST"])
@require_roles("IPManager")
def create_ip_right():
    body = request.get_json(silent=True) or {}
    with db.lock():
        right = ip_right_logic.create_ip_right(body, g.user_role, g.user_id)
    return success(serializers.serialize_ip_right(right), 201)


@bp.route("/ip-rights", methods=["GET"])
@require_roles("IPManager", "FinanceManager", "Counsel", "Admin")
def list_ip_rights():
    limit, offset = get_pagination(request.args)
    status = request.args.get("status")
    ip_type = request.args.get("ip_type")
    business_unit_id = request.args.get("business_unit_id")
    items = list(db.ip_rights.values())
    if status:
        items = [r for r in items if r["status"] == status]
    if ip_type:
        items = [r for r in items if r["ip_type"] == ip_type]
    if business_unit_id:
        items = [r for r in items if r["business_unit_id"] == business_unit_id]
    items.sort(key=lambda r: r["created_at"])
    window, total = paginate(items, limit, offset)
    data = [serializers.serialize_ip_right(r) for r in window]
    return success_list(data, limit, offset, total)


@bp.route("/ip-rights/<right_id>", methods=["GET"])
@require_roles("IPManager", "FinanceManager", "Counsel", "Admin")
def get_ip_right(right_id):
    right = get_or_404(db.ip_rights, right_id)
    return success(serializers.serialize_ip_right(right))


@bp.route("/ip-rights/<right_id>/materials-ready", methods=["POST"])
@require_roles("IPManager")
def materials_ready(right_id):
    body = request.get_json(silent=True) or {}
    with db.lock():
        right = get_or_404(db.ip_rights, right_id)
        check_version(right, body)
        ip_right_logic.materials_ready(right, g.user_role, g.user_id)
    return success(serializers.serialize_ip_right(right))


@bp.route("/ip-rights/<right_id>/jurisdiction-filings", methods=["POST"])
@require_roles("IPManager")
def create_filing(right_id):
    body = request.get_json(silent=True) or {}
    with db.lock():
        right = get_or_404(db.ip_rights, right_id)
        filing = ip_right_logic.create_jurisdiction_filing(right, body, g.user_role, g.user_id)
    return success(serializers.serialize_jurisdiction_filing(filing), 201)


@bp.route("/jurisdiction-filings/<filing_id>/register", methods=["POST"])
@require_roles("IPManager")
def register_filing(filing_id):
    body = request.get_json(silent=True) or {}
    with db.lock():
        filing = get_or_404(db.jurisdiction_filings, filing_id)
        right = ip_right_logic.register_filing(filing, body, g.user_role, g.user_id)
    return success(serializers.serialize_ip_right(right))


@bp.route("/ip-rights/<right_id>/office-actions", methods=["POST"])
@require_roles("IPManager")
def open_office_action(right_id):
    body = request.get_json(silent=True) or {}
    with db.lock():
        right = get_or_404(db.ip_rights, right_id)
        oa = ip_right_logic.open_office_action(right, body, g.user_role, g.user_id)
    return success(serializers.serialize_office_action(oa), 201)


@bp.route("/office-actions/<oa_id>/respond", methods=["POST"])
@require_roles("InternalAgent", "ExternalAgent")
def respond_office_action(oa_id):
    body = request.get_json(silent=True) or {}
    with db.lock():
        oa = get_or_404(db.office_actions, oa_id)
        check_version(oa, body)
        ip_right_logic.respond_office_action(oa, g.user_role, g.user_id)
    return success(serializers.serialize_office_action(oa))


@bp.route("/office-actions/<oa_id>/abandon", methods=["POST"])
@require_roles("IPManager")
def abandon_office_action(oa_id):
    with db.lock():
        oa = get_or_404(db.office_actions, oa_id)
        ip_right_logic.abandon_office_action(oa, g.user_role, g.user_id)
    return success(serializers.serialize_office_action(oa))
