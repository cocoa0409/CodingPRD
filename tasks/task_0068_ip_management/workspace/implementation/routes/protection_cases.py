"""Protection-case endpoints."""
from flask import Blueprint, request, g

import db
from middleware import require_roles
from response import success
from services import protection_logic, serializers
from services.common import check_version, get_or_404

bp = Blueprint("protection_cases", __name__)


@bp.route("/protection-cases", methods=["POST"])
@require_roles("Counsel")
def create_case():
    body = request.get_json(silent=True) or {}
    with db.lock():
        case = protection_logic.create_case(body, g.user_role, g.user_id)
    return success(serializers.serialize_protection_case(case), 201)


@bp.route("/protection-cases/<cid>/evidence", methods=["POST"])
@require_roles("Counsel", "InternalAgent", "ExternalAgent")
def add_evidence(cid):
    body = request.get_json(silent=True) or {}
    with db.lock():
        case = get_or_404(db.protection_cases, cid)
        ev = protection_logic.add_evidence(case, body, g.user_role, g.user_id)
    return success(serializers.serialize_evidence(ev), 201)


@bp.route("/protection-cases/<cid>/route", methods=["POST"])
@require_roles("Counsel")
def route_case(cid):
    body = request.get_json(silent=True) or {}
    with db.lock():
        case = get_or_404(db.protection_cases, cid)
        check_version(case, body)
        protection_logic.route_case(case, body, g.user_role, g.user_id)
    return success(serializers.serialize_protection_case(case))


@bp.route("/protection-cases/<cid>/resolve", methods=["POST"])
@require_roles("Counsel")
def resolve_case(cid):
    body = request.get_json(silent=True) or {}
    with db.lock():
        case = get_or_404(db.protection_cases, cid)
        check_version(case, body)
        protection_logic.resolve_case(case, body, g.user_role, g.user_id)
    return success(serializers.serialize_protection_case(case))


@bp.route("/protection-cases/<cid>/close", methods=["POST"])
@require_roles("Counsel")
def close_case(cid):
    body = request.get_json(silent=True) or {}
    with db.lock():
        case = get_or_404(db.protection_cases, cid)
        check_version(case, body)
        protection_logic.close_case(case, g.user_role, g.user_id)
    return success(serializers.serialize_protection_case(case))
