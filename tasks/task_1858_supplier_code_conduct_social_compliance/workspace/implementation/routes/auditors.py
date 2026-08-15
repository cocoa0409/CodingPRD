"""Auditor endpoints."""
from flask import Blueprint, request
import db
from middleware import require_roles, ALL_BUSINESS_ROLES
from response import success_object
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_AUDITOR_HAS_OPEN_AUDITS,
)
from services.utils import new_uuid

bp = Blueprint("auditors", __name__)


def serialize(a):
    return {
        "id": a["id"],
        "full_name": a["full_name"],
        "firm_name": a["firm_name"],
        "certifications": a["certifications"],
        "country_codes_covered": a["country_codes_covered"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


@bp.route("/auditors", methods=["POST"])
def create_auditor():
    require_roles("AuditCoordinator")
    body = request.get_json(silent=True) or {}
    full_name = body.get("full_name")
    firm_name = body.get("firm_name")
    certifications = body.get("certifications")
    country_codes_covered = body.get("country_codes_covered")
    if not isinstance(full_name, str) or not full_name:
        raise_err(ERR_INVALID_REQUEST, "full_name is required")
    if not isinstance(firm_name, str) or not firm_name:
        raise_err(ERR_INVALID_REQUEST, "firm_name is required")
    if not isinstance(certifications, list):
        raise_err(ERR_INVALID_REQUEST, "certifications must be an array")
    if not isinstance(country_codes_covered, list):
        raise_err(ERR_INVALID_REQUEST, "country_codes_covered must be an array")
    a = {
        "id": new_uuid(),
        "full_name": full_name,
        "firm_name": firm_name,
        "certifications": list(certifications),
        "country_codes_covered": list(country_codes_covered),
        "status": "ACTIVE",
        "created_at": db.get_clock(),
        "updated_at": db.get_clock(),
        "version": 1,
    }
    db.auditors[a["id"]] = a
    return success_object(serialize(a), 201)


@bp.route("/auditors/<aid>", methods=["GET"])
def get_auditor(aid):
    require_roles(*ALL_BUSINESS_ROLES)
    a = db.auditors.get(aid)
    if not a:
        raise_err(ERR_NOT_FOUND, "auditor not found")
    return success_object(serialize(a))


@bp.route("/auditors/<aid>/deactivate", methods=["POST"])
def deactivate_auditor(aid):
    require_roles("AuditCoordinator")
    a = db.auditors.get(aid)
    if not a:
        raise_err(ERR_NOT_FOUND, "auditor not found")
    # Check open audits
    for audit in db.audits.values():
        if audit["auditor_id"] == aid and audit["status"] in ("SCHEDULED", "IN_PROGRESS", "REPORT_SUBMITTED"):
            raise_err(ERR_AUDITOR_HAS_OPEN_AUDITS,
                      "auditor has open audits assigned")
    if a["status"] != "ACTIVE":
        # Already inactive — but spec says deactivate transitions ACTIVE->INACTIVE;
        # a second deactivate is a no-op success? Spec doesn't forbid; safest is treat
        # INACTIVE as already deactivated: return as-is.
        return success_object(serialize(a))
    a["status"] = "INACTIVE"
    a["version"] += 1
    a["updated_at"] = db.get_clock()
    return success_object(serialize(a))
