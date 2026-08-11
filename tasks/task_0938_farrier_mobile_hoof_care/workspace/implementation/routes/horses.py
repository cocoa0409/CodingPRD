"""Horses and their four limb states (PRD 3.1)."""

from flask import Blueprint, request

from core.auth import authenticate, require_client_owner
from core.constants import (
    LIMBS,
    MAX_ROUTINE_CYCLE_WEEKS,
    MIN_ROUTINE_CYCLE_WEEKS,
)
from core.envelope import ok_list, paginate, read_pagination
from core.errors import ApiError
from core.store import db, order_key
from core.validate import body, in_range, opt_bool, opt_int, opt_str, req_int, req_str
from domain.lookup import guard_horse, must, must_ref
from domain.serializers import serialize_many

from ._common import ALL_ROLES, listing, single

bp = Blueprint("horses", __name__)


def _limb_states(horse):
    rows = [l for l in db.limb_states.values() if l["horse_id"] == horse["id"]]
    rows.sort(key=lambda row: LIMBS.index(row["limb"]))
    return rows


@bp.post("/horses")
def create_horse():
    authenticate(("PlatformAdmin", "ClientUser"))
    data = body()
    raw_client_id = data.get("client_id")
    if isinstance(raw_client_id, str):
        require_client_owner(raw_client_id)
    else:
        require_client_owner(None)
    must_ref("barns", data.get("barn_id"))
    must_ref("clients", data.get("client_id"))

    client_id = req_str(data, "client_id")
    barn_id = req_str(data, "barn_id")
    name = req_str(data, "name")
    cycle = req_int(data, "routine_cycle_weeks")
    shoe_size_code = req_str(data, "shoe_size_code")
    requires_sedation = opt_bool(data, "requires_sedation", default=False)
    in_range(cycle, MIN_ROUTINE_CYCLE_WEEKS, MAX_ROUTINE_CYCLE_WEEKS, "routine_cycle_weeks")

    horse = db.mint(
        "horses",
        {
            "client_id": client_id,
            "barn_id": barn_id,
            "name": name,
            "routine_cycle_weeks": cycle,
            "requires_sedation": requires_sedation,
            "shoe_size_code": shoe_size_code,
            "lifecycle_status": "ACTIVE",
            "hold_status": "CLEAR",
            "active_prescription_id": None,
            "next_due_on": None,
            "last_completed_on": None,
        },
    )
    for limb in LIMBS:
        db.mint(
            "limb_states",
            {
                "horse_id": horse["id"],
                "limb": limb,
                "shoeing_state": "BAREFOOT",
                "current_sku_code": None,
                "last_serviced_on": None,
                "consecutive_reset_count": 0,
            },
        )
    return single(horse, 201)


@bp.get("/horses")
def list_horses():
    return listing(
        "horses",
        {
            "client_id": "client_id",
            "barn_id": "barn_id",
            "active_prescription_id": "active_prescription_id",
            "hold_status": "hold_status",
        },
        ALL_ROLES,
    )


@bp.get("/horses/<horse_id>")
def read_horse(horse_id):
    authenticate(ALL_ROLES)
    horse = must("horses", horse_id)
    guard_horse(horse)
    return single(horse)


@bp.patch("/horses/<horse_id>")
def patch_horse(horse_id):
    authenticate(("PlatformAdmin", "ClientUser"))
    horse = must("horses", horse_id)
    guard_horse(horse)
    data = body()
    cycle = opt_int(data, "routine_cycle_weeks")
    sedation = opt_bool(data, "requires_sedation")
    size_code = opt_str(data, "shoe_size_code")
    if cycle is not None:
        in_range(cycle, MIN_ROUTINE_CYCLE_WEEKS, MAX_ROUTINE_CYCLE_WEEKS, "routine_cycle_weeks")
        horse["routine_cycle_weeks"] = cycle
    if sedation is not None:
        horse["requires_sedation"] = sedation
    if size_code is not None:
        horse["shoe_size_code"] = size_code
    # Amending the cycle does not retroactively move an already-computed
    # next_due_on; the new figure takes effect at the next recomputation.
    db.touch(horse)
    return single(horse)


@bp.post("/horses/<horse_id>/retire")
def retire_horse(horse_id):
    authenticate(("PlatformAdmin", "ClientUser"))
    horse = must("horses", horse_id)
    guard_horse(horse)
    if horse["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    blocking = [
        a
        for a in db.appointments.values()
        if a["horse_id"] == horse["id"]
        and a["status"] in ("SCHEDULED", "CONFIRMED", "IN_PROGRESS")
    ]
    if blocking:
        raise ApiError("ERR_INVALID_STATE")
    horse["lifecycle_status"] = "RETIRED"
    horse["next_due_on"] = None
    unrouted = [
        a
        for a in db.appointments.values()
        if a["horse_id"] == horse["id"] and a["status"] == "UNROUTED"
    ]
    for appointment in sorted(unrouted, key=order_key):
        appointment["status"] = "CANCELLED_ADVANCE"
        appointment["cancellation_fee_cents"] = 0
        db.touch(appointment)
    db.touch(horse)
    return single(horse)


@bp.post("/horses/<horse_id>/reinstate")
def reinstate_horse(horse_id):
    authenticate(("PlatformAdmin", "ClientUser"))
    horse = must("horses", horse_id)
    guard_horse(horse)
    if horse["lifecycle_status"] != "RETIRED":
        raise ApiError("ERR_INVALID_STATE")
    horse["lifecycle_status"] = "ACTIVE"
    horse["next_due_on"] = None
    db.touch(horse)
    return single(horse)


@bp.get("/horses/<horse_id>/limb-states")
def list_limb_states(horse_id):
    authenticate(ALL_ROLES)
    horse = must("horses", horse_id)
    guard_horse(horse)
    limit, offset = read_pagination()
    rows = _limb_states(horse)
    wanted = request.args.get("limb")
    if wanted is not None:
        rows = [r for r in rows if r["limb"] == wanted]
    page, total = paginate(rows, limit, offset)
    return ok_list(serialize_many(page), total, limit, offset)
