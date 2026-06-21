"""Single ContractVersion fetch (PRD §3.8)."""

from flask import Blueprint

from common import serialize
from db import db
from errors import resource_not_found
from middleware import require_roles
from response import success_object

bp = Blueprint("contract_versions", __name__)


@bp.route("/contract-versions/<vid>", methods=["GET"])
@require_roles("ContractManager", "ContractApprover", "RiskOfficer")
def get_contract_version(vid):
    version = db.contract_versions.get(vid)
    if not version:
        raise resource_not_found("Contract version not found.")
    return success_object(serialize(version), status=200)
