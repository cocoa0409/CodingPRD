from flask import Blueprint, request
from db import fee_schedules, shelters, gen_id, now_iso, parse_iso
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_DATES,
    ERR_SHELTER_NOT_FOUND,
    ERR_FEE_SCHEDULE_NOT_FOUND,
)
from middleware import require_roles, parse_pagination
from response import success_response, list_response
from services.fee_service import serialize_fee_schedule

fee_schedules_bp = Blueprint("fee_schedules", __name__)

VALID_FEE_TYPES = {"ADOPTION_BASE", "BOARDING_DAILY", "SPECIAL_NEEDS_SURCHARGE", "LOYALTY_DISCOUNT_PCT"}
VALID_SPECIES = {"DOG", "CAT", "RABBIT", "BIRD", "OTHER", "ALL"}


@fee_schedules_bp.route("/petcare/fee-schedules", methods=["POST"])
def create_fee_schedule():
    require_roles("ShelterManager")
    body = request.get_json(silent=True) or {}

    shelter_id = body.get("shelter_id")
    fee_type = body.get("fee_type")
    species = body.get("species")
    amount_cents = body.get("amount_cents")
    effective_from = body.get("effective_from")
    effective_to = body.get("effective_to")

    if not shelter_id:
        raise_error(ERR_INVALID_REQUEST, "shelter_id is required")
    if shelter_id not in shelters:
        raise_error(ERR_SHELTER_NOT_FOUND, "Shelter not found")
    if fee_type not in VALID_FEE_TYPES:
        raise_error(ERR_INVALID_REQUEST, "fee_type is invalid")
    if species not in VALID_SPECIES:
        raise_error(ERR_INVALID_REQUEST, "species is invalid")
    if not isinstance(amount_cents, int) or isinstance(amount_cents, bool) or amount_cents < 0:
        raise_error(ERR_INVALID_REQUEST, "amount_cents must be a non-negative integer")
    if fee_type == "LOYALTY_DISCOUNT_PCT" and amount_cents > 100:
        raise_error(ERR_INVALID_REQUEST, "LOYALTY_DISCOUNT_PCT must be between 0 and 100")
    if not effective_from:
        raise_error(ERR_INVALID_REQUEST, "effective_from is required")

    eff_from_dt = parse_iso(effective_from)
    if eff_from_dt is None:
        raise_error(ERR_INVALID_DATES, "Invalid effective_from")
    eff_to_dt = parse_iso(effective_to) if effective_to else None
    if effective_to and eff_to_dt is None:
        raise_error(ERR_INVALID_DATES, "Invalid effective_to")
    if eff_to_dt is not None and eff_to_dt <= eff_from_dt:
        raise_error(ERR_INVALID_DATES, "effective_to must be strictly greater than effective_from")

    sid = gen_id()
    ts = now_iso()
    schedule = {
        "id": sid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "shelter_id": shelter_id,
        "fee_type": fee_type,
        "species": species,
        "amount_cents": amount_cents,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }
    fee_schedules[sid] = schedule
    return success_response(serialize_fee_schedule(schedule), status_code=201)


@fee_schedules_bp.route("/petcare/fee-schedules", methods=["GET"])
def list_fee_schedules():
    require_roles("ShelterManager", "CaseWorker")
    limit, offset = parse_pagination()
    shelter_id = request.args.get("shelter_id")
    fee_type = request.args.get("fee_type")
    species = request.args.get("species")
    active_filter = request.args.get("is_currently_active")
    items = []
    for s in fee_schedules.values():
        if shelter_id and s["shelter_id"] != shelter_id:
            continue
        if fee_type and s["fee_type"] != fee_type:
            continue
        if species and s["species"] != species:
            continue
        if active_filter is not None:
            serialized = serialize_fee_schedule(s)
            active_bool = serialized["is_currently_active"]
            requested = active_filter.lower() in ("true", "1", "yes")
            if active_bool != requested:
                continue
        items.append(s)
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return list_response([serialize_fee_schedule(x) for x in page], total, limit, offset)


@fee_schedules_bp.route("/petcare/fee-schedules/<sid>", methods=["GET"])
def get_fee_schedule(sid):
    require_roles("ShelterManager", "CaseWorker")
    s = fee_schedules.get(sid)
    if not s:
        raise_error(ERR_FEE_SCHEDULE_NOT_FOUND, "Fee schedule not found")
    return success_response(serialize_fee_schedule(s))
