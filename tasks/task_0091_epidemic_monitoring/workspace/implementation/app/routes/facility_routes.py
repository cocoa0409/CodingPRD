"""IsolationFacility endpoints."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..errors import ApiError
from ..store import common_fields_create, get_store
from ._helpers import get_json_body, ok, with_lock


def register(app: Flask) -> None:
    app.add_url_rule(
        "/epi/facilities",
        view_func=require_auth("CDCSupervisor")(with_lock(create_facility)),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/facilities/<fac_id>",
        view_func=require_auth("CDCSupervisor", "CDCTracer")(with_lock(get_facility)),
        methods=["GET"],
    )


def create_facility():
    body = get_json_body()
    store = get_store()
    code = body.get("facility_code")
    district = body.get("district_code")
    capacity = body.get("capacity")
    if not code or not district or capacity is None:
        raise ApiError("ERR_INVALID_INPUT", "Missing required fields.")
    try:
        cap = int(capacity)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_INPUT", "capacity must be an integer.")
    if cap <= 0:
        raise ApiError("ERR_INVALID_INPUT", "capacity must be > 0.")
    for f in store.facilities.values():
        if f.get("facility_code") == code:
            raise ApiError("ERR_INVALID_INPUT", f"facility_code {code!r} already exists.")
    row = {
        **common_fields_create(),
        "facility_code": code,
        "district_code": district,
        "capacity": cap,
        "occupied": 0,
        "status": "OPEN",
    }
    store.facilities[row["id"]] = row
    return ok(row, status=201)


def get_facility(fac_id: str):
    store = get_store()
    f = store.facilities.get(fac_id)
    if not f:
        raise ApiError("ERR_NOT_FOUND", f"Facility {fac_id} not found.")
    return ok(f)
