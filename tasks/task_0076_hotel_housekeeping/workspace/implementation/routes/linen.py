"""Routes for /linen-types and /linen-movements."""

from flask import Blueprint, request, g

from db import DB, LOCK
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_LINEN_REPLACEMENT_NOT_DUE,
    ERR_LINEN_TYPE_NOT_FOUND,
    ERR_MOVEMENT_NOT_COLLECTED,
    ERR_MOVEMENT_NOT_FOUND,
    ERR_MOVEMENT_NOT_LOSS_REPORTED,
    ERR_ROOM_NOT_FOUND,
)
from middleware import auth_required
from response import success_response, list_response
from services.audit import append_audit
from services.common import (
    bump,
    require_body_dict,
    require_enum,
    require_field,
    stamp_create,
    stamp_subordinate,
)
from services.calculations import compute_linen_replacement_required
from services.pagination import parse_pagination, paginate
from services.serializers import (
    serialize_linen_movement,
    serialize_linen_type,
)
from services.time_util import now_utc, parse_iso


bp = Blueprint("linen", __name__)


REPLACEMENT_POLICIES = {"PER_STAY", "SCHEDULED", "ON_REQUEST"}


def get_movement_or_404(mid):
    m = DB["linen_movements"].get(mid)
    if m is None:
        raise_error(ERR_MOVEMENT_NOT_FOUND, "LinenMovement not found")
    return m


# --------------------------------------------------------------------------- #
# Linen types
# --------------------------------------------------------------------------- #
@bp.route("/linen-types", methods=["POST"])
@auth_required(["Supervisor"])
def create_linen_type():
    body = require_body_dict(request.get_json(silent=True))
    code = require_field(body, "code", str)
    display_name = require_field(body, "display_name", str)
    replacement_policy = require_enum(body, "replacement_policy", REPLACEMENT_POLICIES)
    scheduled_interval_days = body.get("scheduled_interval_days")
    par_per_room = require_field(body, "par_per_room", int)
    replacement_cost_cents = require_field(body, "replacement_cost_cents", int)

    if replacement_policy == "SCHEDULED":
        if not isinstance(scheduled_interval_days, int) or isinstance(scheduled_interval_days, bool) or scheduled_interval_days < 1:
            raise_error(ERR_INVALID_REQUEST,
                        "scheduled_interval_days is required (>=1) for SCHEDULED policy")
    else:
        if scheduled_interval_days is not None:
            raise_error(ERR_INVALID_REQUEST,
                        "scheduled_interval_days must be null for non-SCHEDULED policies")
    if isinstance(par_per_room, bool) or par_per_room < 0:
        raise_error(ERR_INVALID_REQUEST, "par_per_room must be a non-negative integer")
    if isinstance(replacement_cost_cents, bool) or replacement_cost_cents < 0:
        raise_error(ERR_INVALID_REQUEST, "replacement_cost_cents must be a non-negative integer")

    with LOCK:
        for lt in DB["linen_types"].values():
            if lt["code"] == code:
                raise_error(ERR_INVALID_REQUEST,
                            "code must be unique across linen types")
        lt = {
            "code": code,
            "display_name": display_name,
            "replacement_policy": replacement_policy,
            "scheduled_interval_days": scheduled_interval_days,
            "par_per_room": int(par_per_room),
            "replacement_cost_cents": int(replacement_cost_cents),
        }
        stamp_create(lt)
        DB["linen_types"][lt["id"]] = lt
    return success_response(serialize_linen_type(lt), http_status=201)


@bp.route("/linen-types", methods=["GET"])
@auth_required(["FrontDesk", "Supervisor", "Housekeeper", "Engineer"])
def list_linen_types():
    limit, offset = parse_pagination()
    items = list(DB["linen_types"].values())
    items.sort(key=lambda lt: lt["created_at"])
    page, total = paginate(items, limit, offset)
    return list_response(
        [serialize_linen_type(lt) for lt in page], total, limit, offset
    )


# --------------------------------------------------------------------------- #
# Linen movements
# --------------------------------------------------------------------------- #
@bp.route("/linen-movements", methods=["POST"])
@auth_required(["Housekeeper"])
def create_movement():
    body = require_body_dict(request.get_json(silent=True))
    room_id = require_field(body, "room_id", str)
    linen_type_id = require_field(body, "linen_type_id", str)
    collected_quantity = body.get("collected_quantity")
    cleaning_task_id = body.get("cleaning_task_id")

    if not isinstance(collected_quantity, int) or isinstance(collected_quantity, bool) or collected_quantity < 0:
        raise_error(ERR_INVALID_REQUEST,
                    "collected_quantity must be a non-negative integer")

    with LOCK:
        room = DB["rooms"].get(room_id)
        if room is None:
            raise_error(ERR_ROOM_NOT_FOUND, "Room not found")
        lt = DB["linen_types"].get(linen_type_id)
        if lt is None:
            raise_error(ERR_LINEN_TYPE_NOT_FOUND, "LinenType not found")
        task = None
        if cleaning_task_id is not None:
            task = DB["cleaning_tasks"].get(cleaning_task_id)
            if task is None:
                raise_error(ERR_INVALID_REQUEST, "cleaning_task_id does not exist")

        # SCHEDULED replacement window guard
        if lt["replacement_policy"] == "SCHEDULED":
            previous = [
                m for m in DB["linen_movements"].values()
                if m["room_id"] == room_id
                and m["linen_type_id"] == linen_type_id
                and m["status"] in {"SENT_TO_LAUNDRY", "RETURNED", "LOSS_REPORTED", "RESOLVED"}
            ]
            if previous:
                previous.sort(key=lambda m: parse_iso(m["created_at"]))
                last = previous[-1]
                last_created = parse_iso(last["created_at"])
                elapsed_seconds = (now_utc() - last_created).total_seconds()
                elapsed_days = int(elapsed_seconds // 86400)
                if elapsed_days < int(lt["scheduled_interval_days"]):
                    raise_error(ERR_LINEN_REPLACEMENT_NOT_DUE,
                                "Scheduled replacement interval has not elapsed")

        m = {
            "room_id": room_id,
            "linen_type_id": linen_type_id,
            "cleaning_task_id": cleaning_task_id,
            "collected_quantity": int(collected_quantity),
            "sent_to_laundry_quantity": 0,
            "returned_quantity": 0,
            "loss_quantity": 0,
            "damage_quantity": 0,
            "folio_charge_cents": None,
            "status": "COLLECTED",
        }
        stamp_subordinate(m)
        DB["linen_movements"][m["id"]] = m
    return success_response(serialize_linen_movement(m), http_status=201)


@bp.route("/linen-movements", methods=["GET"])
@auth_required(["Supervisor", "Housekeeper", "FrontDesk"])
def list_movements():
    limit, offset = parse_pagination()
    status = request.args.get("status")
    room_id = request.args.get("room_id")
    items = list(DB["linen_movements"].values())
    if status:
        items = [m for m in items if m["status"] == status]
    if room_id:
        items = [m for m in items if m["room_id"] == room_id]
    items.sort(key=lambda m: m["created_at"])
    page, total = paginate(items, limit, offset)
    return list_response(
        [serialize_linen_movement(m) for m in page], total, limit, offset
    )


@bp.route("/linen-movements/<mid>/handover-laundry", methods=["POST"])
@auth_required(["Housekeeper"])
def handover_movement(mid):
    with LOCK:
        m = get_movement_or_404(mid)
        if m["status"] != "COLLECTED":
            raise_error(ERR_MOVEMENT_NOT_COLLECTED,
                        "Movement is not in COLLECTED state")
        if int(m.get("collected_quantity", 0)) <= 0:
            raise_error(ERR_INVALID_REQUEST,
                        "collected_quantity must be > 0 to hand over")
        m["sent_to_laundry_quantity"] = int(m["collected_quantity"])
        m["status"] = "SENT_TO_LAUNDRY"
    return success_response(serialize_linen_movement(m))


@bp.route("/linen-movements/<mid>/resolve-loss-damage", methods=["POST"])
@auth_required(["Supervisor"])
def resolve_loss_damage(mid):
    with LOCK:
        m = get_movement_or_404(mid)
        if m["status"] != "LOSS_REPORTED":
            raise_error(ERR_MOVEMENT_NOT_LOSS_REPORTED,
                        "Movement is not in LOSS_REPORTED state")
        lt = DB["linen_types"].get(m["linen_type_id"])
        loss = int(m.get("loss_quantity", 0))
        damage = int(m.get("damage_quantity", 0))
        charge = (loss + damage) * int(lt["replacement_cost_cents"])
        m["folio_charge_cents"] = charge
        m["status"] = "RESOLVED"
    return success_response(serialize_linen_movement(m))
