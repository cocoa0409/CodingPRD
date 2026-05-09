"""QR code endpoints."""

from flask import Blueprint, request

from middleware import require_roles
from response import success
from services import qr as svc


bp = Blueprint("qr", __name__)


@bp.route("/harvest-records/<harvest_id>/qr-code", methods=["POST"])
@require_roles("Grower")
def mint(harvest_id):
    data = svc.mint_qr(harvest_id)
    return success(data, status_code=201)


@bp.route("/qr-codes/<qr_value>/trace", methods=["GET", "POST"])
@require_roles("Consumer", "RegulatoryOfficer", "Distributor")
def trace(qr_value):
    return success(svc.trace_qr(qr_value, request.args))
