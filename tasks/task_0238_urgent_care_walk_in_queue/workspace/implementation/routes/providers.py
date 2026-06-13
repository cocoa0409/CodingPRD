"""Provider endpoints (PRD §3.9)."""
from flask import Blueprint, request

import serialize
from db import db, stamp_create
from errors import err
from middleware import authorize
from response import ok_object, ok_array
from validation import get_json_body, parse_pagination, paginate, require_str
from routes.lookup import get_path

bp = Blueprint("providers", __name__)

READ_ROLES = ["ClinicManager", "FrontDeskClerk", "TriageNurse", "Provider"]
CREDENTIALS = {"MD", "DO", "NP", "PA"}


@bp.route("/clinics/<cid>/providers", methods=["POST"])
def create_provider(cid):
    authorize(["ClinicManager"])
    clinic = get_path("clinic", cid)
    body = get_json_body()
    require_str(body, "full_name")
    credential = body.get("credential")
    if credential not in CREDENTIALS:
        raise err("ERR_INVALID_REQUEST", "invalid credential")

    on_shift = body.get("on_shift", True)
    if not isinstance(on_shift, bool):
        raise err("ERR_INVALID_REQUEST", "on_shift must be boolean")
    max_concurrent = body.get("max_concurrent_visits", 2)
    if not isinstance(max_concurrent, int) or isinstance(max_concurrent, bool) or max_concurrent < 1:
        raise err("ERR_INVALID_REQUEST", "max_concurrent_visits must be an integer >= 1")

    provider = stamp_create({
        "clinic_id": clinic["id"],
        "full_name": body["full_name"],
        "credential": credential,
        "on_shift": on_shift,
        "max_concurrent_visits": max_concurrent,
    })
    db.providers[provider["id"]] = provider
    return ok_object(serialize.provider(provider), 201)


@bp.route("/clinics/<cid>/providers", methods=["GET"])
def list_clinic_providers(cid):
    authorize(READ_ROLES)
    clinic = get_path("clinic", cid)
    limit, offset = parse_pagination()
    items = [p for p in db.providers.values() if p["clinic_id"] == clinic["id"]]
    on_shift_filter = request.args.get("on_shift")
    if on_shift_filter is not None:
        want = on_shift_filter.lower() == "true"
        items = [p for p in items if p["on_shift"] == want]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    page = paginate(items, limit, offset)
    return ok_array([serialize.provider(p) for p in page], limit, offset, len(items))


@bp.route("/providers/<pid>", methods=["GET"])
def get_provider(pid):
    authorize(READ_ROLES)
    provider = get_path("provider", pid)
    return ok_object(serialize.provider(provider))
