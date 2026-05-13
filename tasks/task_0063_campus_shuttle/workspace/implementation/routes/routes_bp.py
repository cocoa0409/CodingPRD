"""Routes endpoints."""
from flask import Blueprint, request, g

import db
from errors import err
from middleware import require_auth, get_pagination, get_json_body
from response import success, success_list
from services.routes_svc import (
    validate_route_input_create, validate_fk_stops,
    publish_route, retire_route, _CODE_RE,
)
from services.util import occ_check, validate_peak_windows


bp = Blueprint("routes", __name__)


def _serialize_route(r):
    return {k: v for k, v in r.items() if not k.startswith("_")}


@bp.route("/shuttle/routes", methods=["POST"])
@require_auth(roles={"Dispatcher"})
def create_route():
    body = get_json_body()
    validate_route_input_create(body)
    # Body FK exists check
    validate_fk_stops(body)

    r = {
        "code": body["code"],
        "name": body["name"],
        "start_stop_id": body["start_stop_id"],
        "end_stop_id": body["end_stop_id"],
        "intermediate_stop_ids": list(body.get("intermediate_stop_ids", [])),
        "status": "DRAFT",
        "version_number": 1,
        "peak_frequency_minutes": body["peak_frequency_minutes"],
        "offpeak_frequency_minutes": body["offpeak_frequency_minutes"],
        "peak_windows": list(body.get("peak_windows", [])),
        "estimated_distance_km": None,
        "estimated_duration_minutes": None,
    }
    db.stamp_create(r)
    db.routes[r["id"]] = r
    return success(_serialize_route(r), status=201)


@bp.route("/shuttle/routes", methods=["GET"])
@require_auth(roles={"Dispatcher", "Driver", "Employee", "Auditor"})
def list_routes():
    limit, offset = get_pagination()
    status_filter = request.args.get("status")
    items = list(db.routes.values())
    if status_filter:
        items = [r for r in items if r.get("status") == status_filter]
    items.sort(key=lambda r: r.get("_seq", 0))
    page = items[offset:offset + limit]
    return success_list([_serialize_route(r) for r in page],
                        limit, offset, len(items))


@bp.route("/shuttle/routes/<rid>", methods=["GET"])
@require_auth(roles={"Dispatcher", "Driver", "Employee", "Auditor"})
def get_route(rid):
    r = db.routes.get(rid)
    if not r:
        raise err("ERR_NOT_FOUND", "Route not found")
    return success(_serialize_route(r))


@bp.route("/shuttle/routes/<rid>", methods=["PATCH"])
@require_auth(roles={"Dispatcher"})
def patch_route(rid):
    r = db.routes.get(rid)
    if not r:
        raise err("ERR_NOT_FOUND", "Route not found")
    if r.get("status") != "DRAFT":
        raise err("ERR_INVALID_STATE",
                  f"Cannot edit a {r.get('status')} route; create a new version")

    body = get_json_body()

    # Body FK existence
    fk_payload = {}
    if "start_stop_id" in body:
        fk_payload["start_stop_id"] = body["start_stop_id"]
    if "end_stop_id" in body:
        fk_payload["end_stop_id"] = body["end_stop_id"]
    if "intermediate_stop_ids" in body:
        fk_payload["intermediate_stop_ids"] = body["intermediate_stop_ids"]
    if fk_payload:
        validate_fk_stops(fk_payload)

    # OCC
    occ_check(r, body)

    # Validate frequency windows if any of the three are touched
    new_pf = body.get("peak_frequency_minutes", r["peak_frequency_minutes"])
    new_of = body.get("offpeak_frequency_minutes", r["offpeak_frequency_minutes"])
    new_pw = body.get("peak_windows", r["peak_windows"])
    if any(k in body for k in ("peak_frequency_minutes",
                                "offpeak_frequency_minutes",
                                "peak_windows")):
        validate_peak_windows(new_pw, new_pf, new_of)

    if "name" in body:
        r["name"] = body["name"]
    if "start_stop_id" in body:
        r["start_stop_id"] = body["start_stop_id"]
    if "end_stop_id" in body:
        r["end_stop_id"] = body["end_stop_id"]
    if "intermediate_stop_ids" in body:
        r["intermediate_stop_ids"] = list(body["intermediate_stop_ids"])
    if "peak_frequency_minutes" in body:
        r["peak_frequency_minutes"] = body["peak_frequency_minutes"]
    if "offpeak_frequency_minutes" in body:
        r["offpeak_frequency_minutes"] = body["offpeak_frequency_minutes"]
    if "peak_windows" in body:
        r["peak_windows"] = list(body["peak_windows"])

    db.stamp_update(r)
    return success(_serialize_route(r))


@bp.route("/shuttle/routes/<rid>/publish", methods=["POST"])
@require_auth(roles={"Dispatcher"})
def publish(rid):
    r = db.routes.get(rid)
    if not r:
        raise err("ERR_NOT_FOUND", "Route not found")
    res = publish_route(r, actor_role=g.user_role, actor_id=g.user_id)
    return success(_serialize_route(res))


@bp.route("/shuttle/routes/<rid>/retire", methods=["POST"])
@require_auth(roles={"Dispatcher"})
def retire(rid):
    r = db.routes.get(rid)
    if not r:
        raise err("ERR_NOT_FOUND", "Route not found")
    res = retire_route(r, actor_role=g.user_role, actor_id=g.user_id)
    return success(_serialize_route(res))


@bp.route("/shuttle/routes/<rid>/versions", methods=["GET"])
@require_auth(roles={"Dispatcher", "Auditor"})
def list_versions(rid):
    r = db.routes.get(rid)
    if not r:
        raise err("ERR_NOT_FOUND", "Route not found")
    limit, offset = get_pagination()
    code = r.get("code")
    versions = [rv for rv in db.route_versions.values()
                if rv.get("route_code") == code]
    versions.sort(key=lambda rv: rv.get("version_number", 0))
    page = versions[offset:offset + limit]
    return success_list([_serialize_route(rv) for rv in page],
                        limit, offset, len(versions))
