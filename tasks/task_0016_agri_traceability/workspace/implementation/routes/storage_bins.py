"""Storage bin endpoints."""

from flask import Blueprint

from middleware import require_roles
from response import success
from services import storage_bin as svc


bp = Blueprint("storage_bins", __name__)


@bp.route("/storage-bins", methods=["POST"])
@require_roles("LogisticsOperator")
def create():
    data = svc.create_bin()
    return success(data, status_code=201)


@bp.route("/storage-bins/<bin_id>", methods=["GET"])
@require_roles("LogisticsOperator", "Grower", "RegulatoryOfficer")
def get_one(bin_id):
    return success(svc.get_bin(bin_id))
