"""SmartWayAudit endpoints (PRD §3.8)."""
from __future__ import annotations

import re
from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_AUDIT_QUARTER_INVALID,
    ERR_UNAUTHORIZED,
)
from middleware import require_auth, get_json_body, current_role, current_user_id
from response import ok_object, ok_array, paginate_params, slice_page, sort_default
from services.validation import (
    require_fields,
    require_string,
    lookup_path_or_404,
    lookup_fk_or_422,
    current_utc_dt,
)
from services.calculations import compute_smartway_audit, parse_quarter


bp = Blueprint("smartway_audits", __name__)

QUARTER_RE = re.compile(r"^[0-9]{4}Q[1-4]$")


@bp.post("/freight/smartway-audits")
def create_smartway_audit():
    require_auth(["BrokerOps"])()
    body = get_json_body()
    require_fields(body, ["shipper_id", "quarter_label"])
    lookup_fk_or_422(db.shippers, body["shipper_id"], "Shipper")
    quarter = body["quarter_label"]
    if not isinstance(quarter, str) or not QUARTER_RE.match(quarter):
        raise APIError(ERR_AUDIT_QUARTER_INVALID, 422, "quarter_label malformed")
    # Duplicate guard
    for existing in db.smartway_audits.values():
        if existing.get("shipper_id") == body["shipper_id"] and existing.get("quarter_label") == quarter:
            raise APIError(ERR_AUDIT_QUARTER_INVALID, 422, "Audit already exists for this shipper/quarter")
    # Quarter must already be complete
    _, qend = parse_quarter(quarter)
    if not (qend < current_utc_dt()):
        raise APIError(ERR_AUDIT_QUARTER_INVALID, 422, "Quarter is not yet complete")

    computed = compute_smartway_audit(body["shipper_id"], quarter)
    audit = {
        "shipper_id": body["shipper_id"],
        "quarter_label": quarter,
        "total_loads": computed["total_loads"],
        "smartway_loads": computed["smartway_loads"],
        "smartway_ratio": computed["smartway_ratio"],
        "compliance_status": computed["compliance_status"],
    }
    db.stamp_immutable(audit)
    db.smartway_audits[audit["id"]] = audit
    return ok_object(audit, 201)


def _audit_visible_to(audit, role: str, uid: str) -> bool:
    if role == "BrokerOps":
        return True
    if role == "Shipper":
        return audit.get("shipper_id") == uid
    return False


@bp.get("/freight/smartway-audits")
def list_audits():
    require_auth(["BrokerOps", "Shipper"])()
    limit, offset = paginate_params(request.args)
    shipper_filter = request.args.get("shipper_id")
    quarter_filter = request.args.get("quarter_label")
    compliance_filter = request.args.get("compliance_status")
    items = list(db.smartway_audits.values())
    role = current_role()
    uid = current_user_id()
    if role == "Shipper":
        items = [a for a in items if a.get("shipper_id") == uid]
    if shipper_filter:
        items = [a for a in items if a.get("shipper_id") == shipper_filter]
    if quarter_filter:
        items = [a for a in items if a.get("quarter_label") == quarter_filter]
    if compliance_filter:
        items = [a for a in items if a.get("compliance_status") == compliance_filter]
    items = sort_default(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)


@bp.get("/freight/shippers/<sid>/smartway-audits")
def list_audits_for_shipper(sid: str):
    require_auth(["BrokerOps", "Shipper"])()
    # priority 3: shipper existence first.
    lookup_path_or_404(db.shippers, sid, "Shipper")
    if current_role() == "Shipper" and current_user_id() != sid:
        raise APIError(ERR_UNAUTHORIZED, 403, "Shipper may only view own audits")
    limit, offset = paginate_params(request.args)
    quarter_filter = request.args.get("quarter_label")
    compliance_filter = request.args.get("compliance_status")
    items = [a for a in db.smartway_audits.values() if a.get("shipper_id") == sid]
    if quarter_filter:
        items = [a for a in items if a.get("quarter_label") == quarter_filter]
    if compliance_filter:
        items = [a for a in items if a.get("compliance_status") == compliance_filter]
    items = sort_default(items)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)
