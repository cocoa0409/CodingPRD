"""BerthWindow endpoints with half-open overlap scheduling."""
from flask import Blueprint, request

import db
from errors import invalid_request, invalid_state, not_found, raise_err
from middleware import require_roles, ANY_ROLE
from response import ok_list, ok_object
from services import domain
from services.serializers import serialize, serialize_many
from utils import new_entity, paginate, pagination_args, parse_dt, sort_created, touch

bp = Blueprint("berth_windows", __name__)


def _get_or_404(wid):
    ent = domain.get("berth_windows", wid)
    if ent is None:
        not_found("berth window")
    return ent


@bp.post("/berth-windows")
def create_berth_window():
    require_roles(["AgencyOps"])
    body = request.get_json(silent=True) or {}
    call = None
    pcid = body.get("port_call_id")
    if isinstance(pcid, str):
        call = domain.get("port_calls", pcid)
        if call is None:
            not_found("port call")
    start_at = parse_dt(body.get("start_at"))
    end_at = parse_dt(body.get("end_at"))
    # Temporal: half-open window must be strictly ordered
    if start_at is not None and end_at is not None and not start_at < end_at:
        raise_err("ERR_WINDOW_INVALID", "start_at must be strictly before end_at")
    if call is not None:
        domain.require_call_editable(call)
    if (call is None
            or not isinstance(body.get("berth_code"), str) or not body.get("berth_code")
            or start_at is None or end_at is None):
        invalid_request("port_call_id, berth_code, start_at and end_at are required")
    ent = new_entity("berth_windows", {
        "port_call_id": pcid,
        "berth_code": body["berth_code"],
        "start_at": start_at,
        "end_at": end_at,
        "status": "REQUESTED",
        "occupied_at": None,
        "released_at": None,
    })
    return ok_object(serialize(ent), status=201)


@bp.get("/berth-windows")
def list_berth_windows():
    require_roles(ANY_ROLE)
    items = list(domain.all_of("berth_windows"))
    for param in ("port_call_id", "berth_code", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [w for w in items if w[param] == value]
    items = sort_created(items)
    limit, offset = pagination_args(request.args)
    page, total, has_more = paginate(items, limit, offset)
    return ok_list(serialize_many(page), total, limit, offset, has_more)


@bp.get("/berth-windows/<wid>")
def get_berth_window(wid):
    require_roles(ANY_ROLE)
    return ok_object(serialize(_get_or_404(wid)))


@bp.post("/berth-windows/<wid>/confirm")
def confirm_berth_window(wid):
    require_roles(["PortAuthority"])
    ent = _get_or_404(wid)
    if ent["status"] != "REQUESTED":
        invalid_state("Only a REQUESTED berth window can be confirmed")
    # Half-open overlap against committed windows on the same berth_code
    for other in domain.all_of("berth_windows"):
        if (other["id"] == ent["id"] or other["berth_code"] != ent["berth_code"]
                or other["status"] not in ("CONFIRMED", "OCCUPIED")):
            continue
        if other["start_at"] < ent["end_at"] and ent["start_at"] < other["end_at"]:
            raise_err("ERR_BERTH_WINDOW_OVERLAP",
                      "The window overlaps a committed window on the same berth_code")
    call = domain.get("port_calls", ent["port_call_id"])
    if call is not None:
        domain.require_call_editable(call)
    ent["status"] = "CONFIRMED"
    touch(ent)
    return ok_object(serialize(ent))


@bp.post("/berth-windows/<wid>/occupy")
def occupy_berth_window(wid):
    require_roles(["AgencyOps"])
    ent = _get_or_404(wid)
    if ent["status"] != "CONFIRMED":
        invalid_state("Only a CONFIRMED berth window can be occupied")
    if db.now() < ent["start_at"]:
        raise_err("ERR_WINDOW_NOT_STARTED", "The berth window has not started yet")
    hm_ok = any(
        n["port_call_id"] == ent["port_call_id"]
        and n["authority_type"] == "HARBOR_MASTER"
        and n["status"] == "ACKNOWLEDGED"
        for n in domain.all_of("authority_notifications"))
    if not hm_ok:
        raise_err("ERR_HM_ACK_OUTSTANDING",
                  "The HARBOR_MASTER notification is not ACKNOWLEDGED for this call")
    ent["status"] = "OCCUPIED"
    ent["occupied_at"] = db.now()
    touch(ent)
    return ok_object(serialize(ent))


@bp.post("/berth-windows/<wid>/release")
def release_berth_window(wid):
    require_roles(["AgencyOps"])
    ent = _get_or_404(wid)
    if ent["status"] != "OCCUPIED":
        invalid_state("Only an OCCUPIED berth window can be released")
    ent["status"] = "RELEASED"
    ent["released_at"] = db.now()
    touch(ent)
    return ok_object(serialize(ent))


@bp.post("/berth-windows/<wid>/cancel")
def cancel_berth_window(wid):
    require_roles(["AgencyOps"])
    ent = _get_or_404(wid)
    if ent["status"] not in ("REQUESTED", "CONFIRMED"):
        invalid_state("Only a REQUESTED or CONFIRMED berth window can be cancelled")
    ent["status"] = "CANCELLED"
    touch(ent)
    return ok_object(serialize(ent))
