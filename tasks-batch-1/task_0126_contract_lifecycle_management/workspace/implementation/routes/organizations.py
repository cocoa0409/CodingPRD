"""Organization endpoints (PRD §3.1)."""

from flask import Blueprint

from common import (get_json_body, optional_int, require_field, serialize,
                    stamp_new)
from db import db
from errors import resource_not_found, validation_range
from middleware import require_roles
from response import success_object

bp = Blueprint("organizations", __name__)


@bp.route("/organizations", methods=["POST"])
@require_roles("PlatformAdmin")
def create_organization():
    body = get_json_body()
    name = require_field(body, "name", types=str)

    risk_threshold = optional_int(body, "risk_appetite_threshold", default=60)
    lead_days = optional_int(body, "auto_renew_lead_days", default=30)

    if risk_threshold < 0 or risk_threshold > 100:
        raise validation_range("risk_appetite_threshold must be in [0,100].")
    if lead_days <= 0:
        raise validation_range("auto_renew_lead_days must be > 0.")

    org = {
        "name": name,
        "risk_appetite_threshold": risk_threshold,
        "auto_renew_lead_days": lead_days,
    }
    stamp_new(org)
    db.organizations[org["id"]] = org
    return success_object(serialize(org), status=201)


@bp.route("/organizations/<oid>", methods=["GET"])
@require_roles("PlatformAdmin", "ClauseLibrarian", "ContractManager",
               "ContractApprover", "RiskOfficer")
def get_organization(oid):
    org = db.organizations.get(oid)
    if not org:
        raise resource_not_found("Organization not found.")
    return success_object(serialize(org), status=200)
