"""UseAuditFinding endpoints: file/list/get/cure."""
from flask import Blueprint, request

import db
from auth import ALL_ROLES, require_ownership, require_roles
from envelope import success_list, success_obj
from errors import (
    ApiError,
    ERR_AIRPORT_NOT_ACTIVE,
    ERR_CURE_WINDOW_EXPIRED,
    ERR_ENVIRONMENTAL_STILL_LAPSED,
    ERR_FINDING_NOT_APPLICABLE,
    ERR_FINDING_NOT_OPEN,
    ERR_INSURANCE_STILL_LAPSED,
    ERR_INVALID_REQUEST,
    ERR_LEASE_NOT_AUDITABLE,
    ERR_NOT_FOUND,
)
from routes.leases import get_lease_or_404
from services.core import (
    FINDING_TYPES,
    covering_certificate,
    covering_env_record,
    file_finding,
    touch,
)
from timeutil import parse_iso
from validators import body, paginate, pagination

bp = Blueprint("findings", __name__)


def get_finding_or_404(finding_id):
    finding = db.findings.get(finding_id)
    if finding is None:
        raise ApiError(ERR_NOT_FOUND, "Audit finding not found", 404)
    return finding


@bp.post("/leases/<lid>/audit-findings")
def file_audit_finding(lid):
    require_roles("ComplianceOfficer")
    lease = get_lease_or_404(lid)
    airport = db.airports[lease["airport_id"]]
    if airport["status"] != "ACTIVE":
        raise ApiError(ERR_AIRPORT_NOT_ACTIVE, "Airport is SUSPENDED", 409)
    if lease["status"] not in ("ACTIVE", "DELINQUENT"):
        raise ApiError(ERR_LEASE_NOT_AUDITABLE, "Audit findings require lease ACTIVE or DELINQUENT", 409)
    data = body()
    finding_type = data.get("finding_type")
    if not isinstance(finding_type, str) or finding_type not in FINDING_TYPES:
        raise ApiError(ERR_INVALID_REQUEST, "finding_type must be a valid enumeration value", 400)
    if finding_type == "UNAUTHORIZED_SUBLEASE" and lease["sublease_allowed"]:
        raise ApiError(ERR_FINDING_NOT_APPLICABLE, "UNAUTHORIZED_SUBLEASE does not apply to a sublease-allowed lease", 422)
    finding = file_finding(lease, finding_type, db.clock_now())
    return success_obj(db.public(finding), 201)


@bp.get("/leases/<lid>/audit-findings")
def list_lease_findings(lid):
    require_roles(*ALL_ROLES)
    lease = get_lease_or_404(lid)
    items = [f for f in db.findings.values() if f["lease_id"] == lease["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [f for f in items if f["status"] == status]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([db.public(f) for f in page], limit, offset, total)


@bp.get("/audit-findings/<fid>")
def get_finding(fid):
    require_roles(*ALL_ROLES)
    return success_obj(db.public(get_finding_or_404(fid)), 200)


@bp.post("/audit-findings/<fid>/cure")
def cure_finding(fid):
    uid, _role = require_roles("Tenant")
    finding = get_finding_or_404(fid)
    require_ownership(finding["lease_id"], uid)
    if finding["status"] != "OPEN":
        raise ApiError(ERR_FINDING_NOT_OPEN, "Finding must be OPEN to cure", 409)
    now = db.clock_now()
    # Curable strictly before the deadline; exactly at the deadline rejects.
    if now >= parse_iso(finding["cure_deadline"]):
        raise ApiError(ERR_CURE_WINDOW_EXPIRED, "Cure window has closed", 409)
    if finding["finding_type"] == "INSURANCE_LAPSE":
        if covering_certificate(finding["lease_id"], now) is None:
            raise ApiError(ERR_INSURANCE_STILL_LAPSED, "No covering VALID insurance certificate", 422)
    elif finding["finding_type"] == "ENVIRONMENTAL_LAPSE":
        if covering_env_record(finding["lease_id"], now) is None:
            raise ApiError(ERR_ENVIRONMENTAL_STILL_LAPSED, "No covering APPROVED environmental record", 422)

    from timeutil import iso_z
    finding["status"] = "CURED"
    finding["cured_at"] = iso_z(now)
    touch(finding)
    lease = db.leases.get(finding["lease_id"])
    if lease is not None and lease["status"] == "CURE_PERIOD":
        still_open = any(
            f for f in db.findings.values()
            if f["lease_id"] == lease["id"] and f["status"] == "OPEN"
        )
        if not still_open:
            lease["status"] = "ACTIVE"
            touch(lease)
    return success_obj(db.public(finding), 200)
