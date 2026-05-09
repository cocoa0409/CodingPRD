"""Pesticide registry endpoints."""

from flask import Blueprint, request

from common import get_json_body
from middleware import require_roles
from response import paginated, success
from services import registry as svc


bp = Blueprint("registry", __name__)


@bp.route("/pesticide-registry", methods=["POST"])
@require_roles("RegulatoryOfficer")
def create():
    body = get_json_body()
    data = svc.create_registry(body)
    return success(data, status_code=201)


@bp.route("/pesticide-registry", methods=["GET"])
@require_roles("RegulatoryOfficer", "Grower", "Inspector")
def list_():
    items, limit, offset, total = svc.list_registry(request.args)
    return paginated(items, limit, offset, total)


@bp.route("/pesticide-registry/<registration_no>/prohibit", methods=["PATCH"])
@require_roles("RegulatoryOfficer")
def prohibit(registration_no):
    data = svc.prohibit_registry(registration_no)
    return success(data, status_code=200)
