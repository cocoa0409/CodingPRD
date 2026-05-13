"""Stops endpoints."""
from flask import Blueprint, request

import db
from errors import err
from middleware import require_auth, get_pagination, get_json_body
from response import success, success_list
from services.stops import validate_stop_input, code_is_unique_for_active


bp = Blueprint("stops", __name__)


def _serialize(s):
    return {k: v for k, v in s.items() if not k.startswith("_")}


@bp.route("/shuttle/stops", methods=["POST"])
@require_auth(roles={"Dispatcher"})
def create_stop():
    body = get_json_body()
    validate_stop_input(body)

    s = {
        "code": body["code"],
        "name": body["name"],
        "latitude": float(body["latitude"]),
        "longitude": float(body["longitude"]),
        "has_shelter": bool(body.get("has_shelter", False)),
        "amenities": list(body.get("amenities", [])),
        "capacity_reference": int(body["capacity_reference"]),
        "status": "DRAFT",
    }
    db.stamp_create(s)
    db.stops[s["id"]] = s
    return success(_serialize(s), status=201)


@bp.route("/shuttle/stops", methods=["GET"])
@require_auth(roles={"Dispatcher", "Driver", "Employee", "Auditor"})
def list_stops():
    limit, offset = get_pagination()
    status_filter = request.args.get("status")
    items = list(db.stops.values())
    if status_filter:
        items = [s for s in items if s.get("status") == status_filter]
    items.sort(key=lambda s: s.get("_seq", 0))
    page = items[offset:offset + limit]
    return success_list([_serialize(s) for s in page], limit, offset, len(items))


@bp.route("/shuttle/stops/<sid>/activate", methods=["POST"])
@require_auth(roles={"Dispatcher"})
def activate_stop(sid):
    s = db.stops.get(sid)
    if not s:
        raise err("ERR_NOT_FOUND", "Stop not found")
    cur = s.get("status")
    if cur not in ("DRAFT", "OFFSHELF"):
        raise err("ERR_INVALID_STATE",
                  f"Cannot activate a stop in status {cur}")

    if s.get("latitude") is None or s.get("longitude") is None or \
            s.get("capacity_reference") is None:
        raise err("ERR_INVALID_STATE",
                  "Stop missing coordinates or capacity_reference")

    # Code uniqueness among ACTIVE
    if not code_is_unique_for_active(s["code"], exclude_id=s["id"]):
        raise err("ERR_INVALID_STATE",
                  f"Another ACTIVE stop already uses code {s['code']}")

    s["status"] = "ACTIVE"
    db.stamp_update(s)
    return success(_serialize(s))


@bp.route("/shuttle/stops/<sid>/offshelf", methods=["POST"])
@require_auth(roles={"Dispatcher"})
def offshelf_stop(sid):
    s = db.stops.get(sid)
    if not s:
        raise err("ERR_NOT_FOUND", "Stop not found")
    if s.get("status") != "ACTIVE":
        raise err("ERR_INVALID_STATE",
                  f"Cannot off-shelf a stop in status {s.get('status')}")

    # Cannot off-shelf if referenced by any ACTIVE route
    for r in db.routes.values():
        if r.get("status") != "ACTIVE":
            continue
        if r.get("start_stop_id") == sid or r.get("end_stop_id") == sid:
            raise err("ERR_INVALID_STATE",
                      "Stop is referenced by an ACTIVE route")
        if sid in (r.get("intermediate_stop_ids") or []):
            raise err("ERR_INVALID_STATE",
                      "Stop is referenced by an ACTIVE route")

    s["status"] = "OFFSHELF"
    db.stamp_update(s)
    return success(_serialize(s))
