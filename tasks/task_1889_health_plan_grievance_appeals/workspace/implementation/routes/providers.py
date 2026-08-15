"""Provider endpoints (PRD section 3.1)."""

import re

from flask import Blueprint

import db
import errors
from auth import require_roles
from envelope import success_object
from serializers import provider_out
from services import get_or_404
from validate import get_body, opt_bool, opt_enum, req_enum, req_str

bp = Blueprint("providers", __name__)

NPI_RE = re.compile(r"^\d{10}$")
CONTRACT_STATUSES = {"CONTRACTED", "NON_CONTRACTED"}


@bp.route("/appeals/providers", methods=["POST"])
@require_roles({"PlatformAdmin"})
def create_provider(_user_id, _role):
    body = get_body()
    npi = req_str(body, "npi")
    if not NPI_RE.match(npi):
        raise errors.validation("npi must be exactly 10 digits")
    legal_name = req_str(body, "legal_name")
    contract_status = req_enum(body, "contract_status", CONTRACT_STATUSES)
    w9_on_file = opt_bool(body, "w9_on_file", False)
    for p in db.providers.values():
        if p["npi"] == npi:
            raise errors.validation("npi must be unique")
    p = db.make_common()
    p.update({
        "npi": npi,
        "legal_name": legal_name,
        "contract_status": contract_status,
        "w9_on_file": w9_on_file,
    })
    db.providers[p["id"]] = p
    return success_object(provider_out(p), status=201)


@bp.route("/appeals/providers/<pid>", methods=["GET"])
@require_roles({"PlatformAdmin", "IntakeSpecialist", "CaseAnalyst",
                "ComplianceOfficer", "ClaimsProcessor"})
def get_provider(pid, _user_id, _role):
    p = get_or_404(db.providers, pid, "provider")
    return success_object(provider_out(p))


@bp.route("/appeals/providers/<pid>", methods=["PATCH"])
@require_roles({"PlatformAdmin"})
def patch_provider(pid, _user_id, _role):
    p = get_or_404(db.providers, pid, "provider")
    body = get_body()
    if "w9_on_file" in body:
        p["w9_on_file"] = opt_bool(body, "w9_on_file", p["w9_on_file"])
    if "contract_status" in body:
        p["contract_status"] = opt_enum(body, "contract_status",
                                        CONTRACT_STATUSES, p["contract_status"])
    db.touch(p)
    return success_object(provider_out(p))
