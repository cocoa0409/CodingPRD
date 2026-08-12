"""Identity anchors: contractors, homeowners, subcontractors (PRD §3.1)."""
from flask import Blueprint

from db import stores, new_id, next_seq, now_ts
from response import ok
from serializers import ser_contractor, ser_homeowner, ser_subcontractor, ser_site_log
from services import TRADES
from validation import auth, require_role, get_body, v_str, v_enum
from routes.common import get_or_404, new_entity, list_response

bp = Blueprint("anchors", __name__)


@bp.post("/api/contractors")
def create_contractor():
    role, uid = auth()
    require_role(role, "PlatformAdmin")
    body = get_body()
    name = v_str(body, "name")
    license_no = v_str(body, "license_no")
    e = new_entity({"name": name, "license_no": license_no})
    stores["contractors"][e["id"]] = e
    return ok(ser_contractor(e), 201)


@bp.post("/api/homeowners")
def create_homeowner():
    role, uid = auth()
    require_role(role, "PlatformAdmin", "Contractor")
    body = get_body()
    e = new_entity({
        "name": v_str(body, "name"),
        "email": v_str(body, "email"),
        "phone": v_str(body, "phone"),
    })
    stores["homeowners"][e["id"]] = e
    return ok(ser_homeowner(e), 201)


@bp.post("/api/subcontractors")
def create_subcontractor():
    role, uid = auth()
    require_role(role, "PlatformAdmin")
    body = get_body()
    e = new_entity({
        "name": v_str(body, "name"),
        "trade": v_enum(body, "trade", TRADES),
    })
    stores["subcontractors"][e["id"]] = e
    return ok(ser_subcontractor(e), 201)


@bp.get("/api/subcontractors/<sub_id>")
def get_subcontractor(sub_id):
    auth()
    e = get_or_404("subcontractors", sub_id, "Subcontractor")
    return ok(ser_subcontractor(e))


@bp.get("/api/subcontractors/<sub_id>/site-logs")
def list_subcontractor_site_logs(sub_id):
    auth()
    get_or_404("subcontractors", sub_id, "Subcontractor")
    logs = [l for l in stores["site_logs"].values() if l["subcontractor_id"] == sub_id]
    return list_response(logs, ser_site_log)
