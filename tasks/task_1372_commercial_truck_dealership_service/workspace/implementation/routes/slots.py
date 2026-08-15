"""FactoryBuildSlot endpoints (PRD §3.2)."""
from flask import Blueprint, request

from db import store, stamp_new
from errors import err_not_found, err_invalid
from helpers import (body, req_str, req_enum, req_int, parse_build_month,
                     paginate, sort_created, apply_filters)
from middleware import caller, ALL_ROLES
from response import success, success_list
from serializers import factory_build_slot as ser

bp = Blueprint("slots", __name__)

VOCATION_GROUPS = {"STANDARD", "SEVERE"}


@bp.post("/dealership/factory-build-slots")
def create_slot():
    caller(["SalesManager"])
    data = body()
    build_month = req_str(data, "build_month")
    parse_build_month(build_month)  # validates YYYY-MM shape
    group = req_enum(data, "vocation_group", VOCATION_GROUPS)
    capacity = req_int(data, "capacity", minimum=1)
    # (build_month, vocation_group) unique among pools -> ERR_INVALID_REQUEST.
    for s in store.factory_build_slots.values():
        if s["build_month"] == build_month and s["vocation_group"] == group:
            raise err_invalid(
                "A slot pool already exists for this build_month and vocation_group")
    slot = {
        "build_month": build_month,
        "vocation_group": group,
        "capacity": capacity,
        "held_count": 0,
        "committed_count": 0,
        "status": "OPEN",
    }
    stamp_new(slot)
    store.factory_build_slots[slot["id"]] = slot
    return success(ser(slot), status=201)


@bp.get("/dealership/factory-build-slots")
def list_slots():
    caller(ALL_ROLES)
    items = apply_filters(sort_created(store.factory_build_slots.values()), [
        ("build_month", request.args.get("build_month")),
        ("status", request.args.get("status")),
    ])
    page, meta = paginate(items)
    return success_list([ser(s) for s in page], meta)


@bp.get("/dealership/factory-build-slots/<rid>")
def get_slot(rid):
    caller(ALL_ROLES)
    slot = store.factory_build_slots.get(rid)
    if slot is None:
        raise err_not_found("FACTORY_BUILD_SLOT")
    return success(ser(slot))
