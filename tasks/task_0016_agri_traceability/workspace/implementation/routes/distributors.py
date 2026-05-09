"""Distributor endpoints."""

from flask import Blueprint, request

from middleware import require_roles
from response import paginated, success
from services import distributor as svc


bp = Blueprint("distributors", __name__)


@bp.route("/distributors", methods=["POST"])
@require_roles("RegulatoryOfficer")
def create():
    data = svc.create_distributor()
    return success(data, status_code=201)


@bp.route("/distributors", methods=["GET"])
@require_roles("RegulatoryOfficer", "LogisticsOperator")
def list_():
    items, limit, offset, total = svc.list_distributors(request.args)
    return paginated(items, limit, offset, total)
