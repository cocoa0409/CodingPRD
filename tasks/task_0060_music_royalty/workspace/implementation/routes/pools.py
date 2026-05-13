"""Royalty pool and distribution routes."""

from flask import Blueprint, request

from middleware import require_role
from response import success_response, list_response
from services import royalty_pool as svc

bp = Blueprint("pools", __name__)


@bp.route("/pools", methods=["POST"])
def create():
    require_role("FinanceOps")
    body = request.get_json(silent=True) or {}
    data = svc.create_pool(body)
    return success_response(data, status_code=201)


@bp.route("/pools/<pool_id>", methods=["PATCH"])
def patch(pool_id):
    require_role("FinanceOps")
    body = request.get_json(silent=True) or {}
    data = svc.patch_pool(pool_id, body)
    return success_response(data)


@bp.route("/pools/<pool_id>/close", methods=["POST"])
def close(pool_id):
    require_role("FinanceOps")
    body = request.get_json(silent=True) or {}
    data = svc.close_pool(pool_id, body)
    return success_response(data)


@bp.route("/pools/<pool_id>/finalize", methods=["POST"])
def finalize(pool_id):
    require_role("FinanceOps")
    body = request.get_json(silent=True) or {}
    data = svc.finalize_pool(pool_id, body)
    return success_response(data)


@bp.route("/pools/<pool_id>", methods=["GET"])
def get(pool_id):
    require_role("PlatformAdmin", "FinanceOps")
    data = svc.get_pool(pool_id)
    return success_response(data)


@bp.route("/pools/<pool_id>/distributions", methods=["GET"])
def list_distributions(pool_id):
    require_role("PlatformAdmin", "FinanceOps", "RightsHolder")
    items, total, limit, offset = svc.list_distributions(pool_id, request.args)
    return list_response(items, total, limit, offset)


@bp.route("/distributions/<distribution_id>/forfeit", methods=["POST"])
def forfeit(distribution_id):
    require_role("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    data = svc.forfeit_distribution(distribution_id, body)
    return success_response(data)
