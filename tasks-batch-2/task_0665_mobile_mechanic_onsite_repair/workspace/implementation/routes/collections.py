"""Standalone collection/fetch endpoints for part-lines and inspection-findings."""
from flask import Blueprint, request

import db
import errors
import response
from middleware import authenticate, require_role, parse_pagination, paginate
from services import models

bp = Blueprint("collections", __name__)


def _sorted(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


# ---- part-lines ----
@bp.route("/part-lines/<pid>", methods=["GET"])
def get_part_line(pid):
    uid, role = authenticate()
    require_role(role, {"PlatformAdmin", "Customer", "Mechanic", "Dispatcher"})
    pl = db.store.part_lines.get(pid)
    if pl is None:
        raise errors.not_found("Part line not found.")
    if role == "Customer":
        sr = db.store.service_requests.get(pl["service_request_id"])
        if sr is None or uid != sr["customer_id"]:
            raise errors.not_owner("Customer may only read its own part lines.")
    return response.success(models.serialize(pl), 200)


@bp.route("/part-lines", methods=["GET"])
def list_part_lines():
    _uid, role = authenticate()
    require_role(role, {"PlatformAdmin", "Mechanic", "Dispatcher"})
    limit, offset = parse_pagination()
    catalog_filter = request.args.get("catalog_part_id")
    sr_filter = request.args.get("service_request_id")
    items = list(db.store.part_lines.values())
    if catalog_filter is not None:
        items = [p for p in items if p["catalog_part_id"] == catalog_filter]
    if sr_filter is not None:
        items = [p for p in items if p["service_request_id"] == sr_filter]
    items = _sorted(items)
    page, total = paginate(items, limit, offset)
    return response.success_list([models.serialize(p) for p in page], limit, offset, total)


# ---- inspection-findings ----
@bp.route("/inspection-findings/<fid>", methods=["GET"])
def get_finding(fid):
    uid, role = authenticate()
    require_role(role, {"PlatformAdmin", "Customer", "Mechanic", "Dispatcher"})
    f = db.store.inspection_findings.get(fid)
    if f is None:
        raise errors.not_found("Inspection finding not found.")
    if role == "Customer":
        sr = db.store.service_requests.get(f["service_request_id"])
        if sr is None or uid != sr["customer_id"]:
            raise errors.not_owner("Customer may only read its own findings.")
    return response.success(models.serialize(f), 200)


@bp.route("/inspection-findings", methods=["GET"])
def list_findings():
    _uid, role = authenticate()
    require_role(role, {"PlatformAdmin", "Mechanic", "Dispatcher"})
    limit, offset = parse_pagination()
    visit_filter = request.args.get("job_visit_id")
    part_filter = request.args.get("recommended_part_id")
    sr_filter = request.args.get("service_request_id")
    items = list(db.store.inspection_findings.values())
    if visit_filter is not None:
        items = [f for f in items if f["job_visit_id"] == visit_filter]
    if part_filter is not None:
        items = [f for f in items if f.get("recommended_part_id") == part_filter]
    if sr_filter is not None:
        items = [f for f in items if f["service_request_id"] == sr_filter]
    items = _sorted(items)
    page, total = paginate(items, limit, offset)
    return response.success_list([models.serialize(f) for f in page], limit, offset, total)
