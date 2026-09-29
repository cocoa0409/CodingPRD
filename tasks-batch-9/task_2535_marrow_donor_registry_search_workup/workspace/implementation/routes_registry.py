"""Registries, collection centres and the logical clock (PRD 3.1, 2.4)."""

from flask import Blueprint

import serializers
import validate as v
from auth import (ROLE_CENTER, ROLE_COORDINATOR, ROLE_DIRECTOR, ROLE_LIAISON,
                  ROLE_OPS, authenticate)
from envelope import success
from errors import ApiError
from guards import find
from store import db, fmt_instant, new_row, touch

bp = Blueprint("registry_core", __name__)

COOPERATION_STATUSES = ("ACTIVE", "SUSPENDED", "TERMINATED")


@bp.get("/registry/registries/<rid>")
def get_registry(rid):
    authenticate(ROLE_OPS, ROLE_COORDINATOR, ROLE_DIRECTOR, ROLE_LIAISON,
                 ROLE_CENTER)
    row = find(db.registries, rid, "ERR_REGISTRY_NOT_FOUND")
    return success(serializers.registry_dict(row))


@bp.post("/registry/registries")
def create_registry():
    authenticate(ROLE_OPS)
    body = v.read_body()
    code = v.req_str(body, "code", 1, 16, v.CODE_RE)
    name = v.req_str(body, "name", 1, 120)
    country_code = v.req_str(body, "country_code", 2, 2, v.COUNTRY_RE)
    currency_code = v.req_str(body, "currency_code", 3, 3, v.CURRENCY_RE)
    fx_rate = v.req_num(body, "fx_rate_to_usd", gt=0, max_dp=4)
    is_domestic = v.req_bool(body, "is_domestic")
    tier = v.req_int(body, "cooperation_tier", 1, 3)
    hours = v.req_int(body, "ct_response_deadline_hours", 1, 720)
    cooperation = v.opt_enum(body, "cooperation_status", COOPERATION_STATUSES,
                             "ACTIVE")

    for existing in db.registries.values():
        if existing["code"] == code:
            raise ApiError("ERR_REGISTRY_CODE_ALREADY_EXISTS")

    row = new_row(
        code=code,
        name=name,
        country_code=country_code,
        currency_code=currency_code,
        fx_rate_to_usd=fx_rate,
        is_domestic=is_domestic,
        cooperation_status=cooperation,
        cooperation_tier=tier,
        ct_response_deadline_hours=hours,
    )
    db.registries[row["id"]] = row
    return success(serializers.registry_dict(row), 201)


@bp.patch("/registry/registries/<rid>")
def patch_registry(rid):
    authenticate(ROLE_OPS)
    body = v.read_body()
    cooperation = v.opt_enum(body, "cooperation_status", COOPERATION_STATUSES)
    tier = v.opt_int(body, "cooperation_tier", 1, 3)
    fx_rate = v.opt_num(body, "fx_rate_to_usd", gt=0, max_dp=4)
    hours = v.opt_int(body, "ct_response_deadline_hours", 1, 720)
    row = find(db.registries, rid, "ERR_REGISTRY_NOT_FOUND")
    if cooperation is not None:
        row["cooperation_status"] = cooperation
    if tier is not None:
        row["cooperation_tier"] = tier
    if fx_rate is not None:
        row["fx_rate_to_usd"] = fx_rate
    if hours is not None:
        row["ct_response_deadline_hours"] = hours
    touch(row)
    return success(serializers.registry_dict(row))


@bp.get("/registry/collection-centers/<cid>")
def get_center(cid):
    authenticate(ROLE_OPS, ROLE_CENTER, ROLE_DIRECTOR, ROLE_COORDINATOR)
    row = find(db.centers, cid, "ERR_COLLECTION_CENTER_NOT_FOUND")
    return success(serializers.center_dict(row))


@bp.post("/registry/collection-centers")
def create_center():
    authenticate(ROLE_OPS)
    body = v.read_body()
    name = v.req_str(body, "name", 1, 120)
    country_code = v.req_str(body, "country_code", 2, 2, v.COUNTRY_RE)
    capacity = v.req_int(body, "concurrent_collection_capacity", 1, 5)
    row = new_row(
        name=name,
        country_code=country_code,
        concurrent_collection_capacity=capacity,
    )
    db.centers[row["id"]] = row
    return success(serializers.center_dict(row), 201)


@bp.post("/_clock/set_current_utc")
def set_clock():
    """Test-driving endpoint (PRD 2.4): nothing else ever reads wall time."""
    authenticate(ROLE_OPS)
    body = v.read_body()
    target = v.req_instant(body, "to_iso8601")
    previous = db.clock
    db.clock = target
    return success({
        "current_utc": fmt_instant(db.clock),
        "previous_utc": fmt_instant(previous),
    })
