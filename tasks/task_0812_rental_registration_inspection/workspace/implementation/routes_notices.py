"""Tenant notice routes."""
from flask import Blueprint
from store import store, touch
from auth import require_role, body, require_fields, check_enum
from errors import err
from lookups import get_property, get_notice
from envelope import success
from serializers import notice_dict
from domain import create_notice, refresh_notice

bp = Blueprint("notices", __name__)

NOTICE_TYPES = {"LEAD_PAINT_DISCLOSURE", "INSPECTION_NOTICE", "VIOLATION_NOTICE", "CONDEMNATION_NOTICE"}


@bp.post("/tenant-notices")
def create_tenant_notice():
    require_role({"Registrar"})
    data = body()
    if data.get("property_id") is not None:
        get_property(data["property_id"])
    require_fields(data, ["property_id", "recipient_email", "recipient_unit", "notice_type"])
    check_enum(data["notice_type"], "notice_type", NOTICE_TYPES)
    e = create_notice(
        data["property_id"], data["notice_type"],
        recipient_email=data["recipient_email"], recipient_unit=data["recipient_unit"],
    )
    return success(notice_dict(e), status=201)


@bp.post("/tenant-notices/<nid>/acknowledge")
def acknowledge_notice(nid):
    require_role({"Tenant"})
    n = get_notice(nid)
    refresh_notice(n)  # lazily expire if past deadline
    if n["status"] == "ACKNOWLEDGED":
        raise err("ERR_INVALID_STATE", "Notice already acknowledged")
    if n["status"] == "EXPIRED":
        raise err("ERR_NOTICE_EXPIRED", "Notice acknowledgement window has passed")
    n["status"] = "ACKNOWLEDGED"
    n["acknowledged_at"] = store.now()
    touch(n)
    return success(notice_dict(n), status=200)
