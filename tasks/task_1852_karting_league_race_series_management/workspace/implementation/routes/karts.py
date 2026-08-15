"""Rental kart fleet management."""
from flask import Blueprint, request

from errors import raise_error, ERR_INVALID_STATE
from middleware import authorized, ANY_ROLE
from response import success_object, success_list
from services import core
from validate import json_body, v_str, v_enum, v_enum_list

bp = Blueprint("karts", __name__)

KART_STATUSES = {"AVAILABLE", "IN_MAINTENANCE", "RETIRED"}

_KART_TRANSITIONS = {
    ("AVAILABLE", "IN_MAINTENANCE"),
    ("IN_MAINTENANCE", "AVAILABLE"),
    ("AVAILABLE", "RETIRED"),
    ("IN_MAINTENANCE", "RETIRED"),
}


@bp.post("/karts")
def create_kart():
    authorized(["LeagueAdmin"])
    body = json_body()
    fleet_number = v_str(body, "fleet_number")
    eligible = v_enum_list(body, "eligible_class_codes", core.CLASS_CODES)
    kart = core.create_record("karts", {
        "fleet_number": fleet_number,
        "eligible_class_codes": list(eligible),
        "status": "AVAILABLE",
    })
    return success_object(core.serialize_kart(kart), 201)


@bp.get("/karts/<kart_id>")
def get_kart(kart_id):
    authorized(ANY_ROLE)
    kart = core.must_find("karts", kart_id, "kart not found")
    return success_object(core.serialize_kart(kart))


@bp.get("/karts")
def list_karts():
    authorized(ANY_ROLE)
    status_filter = request.args.get("status")
    items = list(core.db["karts"].values())
    if status_filter is not None:
        items = [k for k in items if k["status"] == status_filter]
    items = core.list_sorted(items)
    page, total, limit, offset = core.paginate(items)
    return success_list([core.serialize_kart(k) for k in page], total, limit, offset)


def _kart_has_active_reference(kart):
    """No-active-reference precondition: no entry in an active tech state and no
    practice booking in RESERVED/CHECKED_IN may reference the kart."""
    for en in core.db["entries"].values():
        if en.get("kart_id") == kart["id"] and en["status"] in core.ENTRY_ACTIVE_STATES:
            return True
    for b in core.db["bookings"].values():
        if b["kart_id"] == kart["id"] and b["status"] in ("RESERVED", "CHECKED_IN"):
            return True
    return False


@bp.patch("/karts/<kart_id>")
def patch_kart(kart_id):
    authorized(["LeagueAdmin"])
    body = json_body()
    target = v_enum(body, "status", KART_STATUSES)
    kart = core.must_find("karts", kart_id, "kart not found")
    if (kart["status"], target) not in _KART_TRANSITIONS:
        raise_error(
            ERR_INVALID_STATE,
            f"kart status transition {kart['status']} -> {target} is not permitted",
        )
    if target in ("IN_MAINTENANCE", "RETIRED") and _kart_has_active_reference(kart):
        raise_error(
            ERR_INVALID_STATE,
            "kart is referenced by an active entry or practice booking",
        )
    kart["status"] = target
    core.touch(kart)
    return success_object(core.serialize_kart(kart))
