"""Provider endpoints."""

from flask import Blueprint, request

from db import stores
from errors import raise_err, ERR_DUPLICATE_OUR_PLAN
from helpers import base_record, get_or_404, body, req_str, paginate
from middleware import require_roles
from response import success

bp = Blueprint("providers", __name__)


@bp.route("/cob/providers", methods=["POST"])
def create_provider():
    require_roles("PlatformAdmin")
    data = body()
    npi = req_str(data, "npi")
    legal_name = req_str(data, "legal_name")
    tin = req_str(data, "tin")
    for p in stores["providers"].values():
        if p.get("npi") == npi:
            raise_err(ERR_DUPLICATE_OUR_PLAN, "npi unique")
    rec = base_record()
    rec.update({
        "npi": npi,
        "legal_name": legal_name,
        "tin": tin,
        "status": "ACTIVE",
    })
    stores["providers"][rec["id"]] = rec
    return success(rec, status=201)


@bp.route("/cob/providers/<pid>", methods=["GET"])
def get_provider(pid):
    require_roles("PlatformAdmin", "ClaimsExaminer", "RecoverySpecialist", "COBAnalyst")
    rec = get_or_404(stores["providers"], pid, "provider")
    return success(rec)


@bp.route("/cob/providers", methods=["GET"])
def list_providers():
    require_roles("PlatformAdmin", "ClaimsExaminer", "RecoverySpecialist", "COBAnalyst")
    npi = request.args.get("npi")
    items = list(stores["providers"].values())
    if npi:
        items = [p for p in items if p.get("npi") == npi]
    return paginate(items)
