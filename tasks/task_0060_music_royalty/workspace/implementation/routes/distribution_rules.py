"""Distribution rule routes."""

from flask import Blueprint, request

from middleware import require_role
from response import success_response, list_response
from services import distribution_rule as svc

bp = Blueprint("distribution_rules", __name__)


@bp.route("/distribution-rules", methods=["POST"])
def create():
    require_role("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    data = svc.create_rule(body)
    return success_response(data, status_code=201)


@bp.route("/distribution-rules", methods=["GET"])
def list_all():
    require_role("PlatformAdmin", "FinanceOps")
    items, total, limit, offset = svc.list_rules(request.args)
    return list_response(items, total, limit, offset)
