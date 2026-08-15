"""Routes: retail contracts and weekly settlement."""

from datetime import timedelta, date
from decimal import Decimal

from flask import Blueprint

from db import store
from errors import raise_error
from middleware import require_roles, ALL_ROLES
from response import success, list_response
from util import (get_body, get_body_optional, pagination_params, parse_date,
                  req_int, req_str, req_enum, dec, q2)
from services.core import (
    stamp_new, touch, logical_now,
    get_contract, ser_contract, ser_shipment,
    week_bounds_for_contract, recompute_contract_week_reserved,
    cancel_shipment_cascade, WEEKDAYS,
)
from services.calculations import (
    first_week_start_on_or_after, fill_rates, penalty_for_week, week_stats,
)

bp = Blueprint("contracts", __name__)


def _q(name):
    from flask import request
    v = request.args.get(name)
    return v if v not in (None, "") else None


@bp.post("/contracts")
def create_contract():
    require_roles("ContractsManager")
    fields = {"retailer_name", "crop_id", "weekly_commitment_lb", "price_per_pound_cents",
              "penalty_cents_per_short_lb", "fill_rate_threshold", "week_start_day",
              "start_date", "end_date"}
    body = get_body(fields, fields)
    crop_id = body["crop_id"]
    if not isinstance(crop_id, str):
        raise_error("ERR_INVALID_REQUEST", "crop_id must be a string")
    crop = store.crops.get(crop_id)
    if crop is None:
        raise_error("ERR_NOT_FOUND", "Crop not found")
    retailer = req_str(body["retailer_name"], "retailer_name")
    commitment = req_int(body["weekly_commitment_lb"], "weekly_commitment_lb")
    price = req_int(body["price_per_pound_cents"], "price_per_pound_cents")
    penalty = req_int(body["penalty_cents_per_short_lb"], "penalty_cents_per_short_lb")
    threshold = dec(body["fill_rate_threshold"], "fill_rate_threshold")
    week_start_day = req_enum(body["week_start_day"], "week_start_day", set(WEEKDAYS.keys()))
    start_date = parse_date(body["start_date"], "start_date")
    end_date = parse_date(body["end_date"], "end_date")
    # reference coherence (priority 8)
    if crop["crop_status"] == "RETIRED":
        raise_error("ERR_CROP_RETIRED", "Crop is RETIRED")
    # temporal (priority 9)
    if end_date <= start_date:
        raise_error("ERR_CONTRACT_WINDOW_INVALID", "end_date must be after start_date")
    # fiscal floors (priority 12)
    if commitment < 0 or penalty < 0:
        raise_error("ERR_INVALID_REQUEST", "money fields must be non-negative")
    if threshold < 0:
        raise_error("ERR_INVALID_REQUEST", "fill_rate_threshold must be non-negative")
    if price < crop["floor_price_cents_per_lb"]:
        raise_error("ERR_PRICE_BELOW_FLOOR", "price below crop floor")
    contract = stamp_new({
        "retailer_name": retailer, "crop_id": crop["id"],
        "weekly_commitment_lb": commitment,
        "price_per_pound_cents": price,
        "penalty_cents_per_short_lb": penalty,
        "fill_rate_threshold": threshold,
        "week_start_day": week_start_day,
        "start_date": start_date, "end_date": end_date,
        "contract_status": "ACTIVE",
        "next_unsettled_week_start": first_week_start_on_or_after(week_start_day, start_date),
        "consecutive_short_weeks": 0,
        "week_reserved_lb": Decimal("0"),
    })
    store.contracts[contract["id"]] = contract
    recompute_contract_week_reserved(contract)
    return success(ser_contract(contract), status=201)


@bp.get("/contracts")
def list_contracts():
    require_roles(*ALL_ROLES)
    limit, offset = pagination_params()
    items = list(store.contracts.values())
    crop_id = _q("crop_id")
    status = _q("contract_status")
    if crop_id is not None:
        items = [c for c in items if c["crop_id"] == crop_id]
    if status is not None:
        items = [c for c in items if c["contract_status"] == status]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    return list_response(items, ser_contract, limit, offset)


@bp.get("/contracts/<cid>")
def get_contract_route(cid):
    require_roles(*ALL_ROLES)
    contract = get_contract(cid)
    recompute_contract_week_reserved(contract)
    return success(ser_contract(contract))


@bp.get("/contracts/<cid>/shipments")
def list_contract_shipments(cid):
    require_roles(*ALL_ROLES)
    contract = get_contract(cid)
    limit, offset = pagination_params()
    items = [s for s in store.shipments.values() if s["contract_id"] == contract["id"]]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    return list_response(items, ser_shipment, limit, offset)


@bp.get("/contracts/<cid>/week-summary")
def contract_week_summary(cid):
    require_roles("FarmManager", "ContractsManager")
    contract = get_contract(cid)
    from flask import request
    raw = request.args.get("week_start_date")
    if raw is None:
        raise_error("ERR_INVALID_REQUEST", "week_start_date is required")
    week_start = parse_date(raw, "week_start_date")
    shipped, reserved, provisional, final = fill_rates(contract, week_start)
    settled = False
    nus = contract.get("next_unsettled_week_start")
    if isinstance(nus, str):
        nus = date.fromisoformat(nus)
    if nus is not None and week_start < nus:
        settled = True
    penalty = 0
    if settled:
        # Reconstruct penalty from recorded settlements if available
        penalty = contract.get("settled_penalties", {}).get(week_start.isoformat(), 0)
    else:
        # preview penalty as if settled now (using current consecutive_short_weeks)
        penalty, _ = penalty_for_week(contract, shipped)
    return success({
        "week_start_date": week_start.isoformat(),
        "shipped_lb": float(shipped),
        "reserved_lb": float(reserved),
        "provisional_fill_rate": float(provisional),
        "final_fill_rate": float(final),
        "penalty_cents": penalty,
        "settled": settled,
    })


@bp.post("/contracts/<cid>/suspend")
def suspend_contract(cid):
    require_roles("ContractsManager")
    get_body_optional(set())
    contract = get_contract(cid)
    if contract["contract_status"] != "ACTIVE":
        raise_error("ERR_INVALID_STATE_TRANSITION", "Contract not ACTIVE")
    for s in store.shipments.values():
        if s["contract_id"] == cid and s["shipment_status"] == "PACKED":
            raise_error("ERR_SHIPMENT_IN_FLIGHT", "PACKED shipment exists")
    contract["contract_status"] = "SUSPENDED"
    touch(contract)
    return success(ser_contract(contract))


@bp.post("/contracts/<cid>/reinstate")
def reinstate_contract(cid):
    require_roles("ContractsManager")
    get_body_optional(set())
    contract = get_contract(cid)
    if contract["contract_status"] != "SUSPENDED":
        raise_error("ERR_INVALID_STATE_TRANSITION", "Contract not SUSPENDED")
    contract["contract_status"] = "ACTIVE"
    touch(contract)
    return success(ser_contract(contract))


@bp.post("/contracts/<cid>/terminate")
def terminate_contract(cid):
    require_roles("ContractsManager")
    get_body_optional(set())
    contract = get_contract(cid)
    if contract["contract_status"] not in ("ACTIVE", "SUSPENDED"):
        raise_error("ERR_INVALID_STATE_TRANSITION", "Contract not ACTIVE/SUSPENDED")
    # cascade: open shipments -> CANCELED -> lines RELEASED -> batch pools recomputed
    for s in list(store.shipments.values()):
        if s["contract_id"] == cid and s["shipment_status"] in ("RESERVED", "PACKED"):
            cancel_shipment_cascade(s, "CANCELED")
    contract["contract_status"] = "TERMINATED"
    touch(contract)
    return success(ser_contract(contract))


@bp.post("/contracts/<cid>/settle-week")
def settle_week(cid):
    require_roles("ContractsManager")
    body = get_body({"week_start_date"}, {"week_start_date"})
    contract = get_contract(cid)
    if contract["contract_status"] not in ("ACTIVE", "SUSPENDED"):
        raise_error("ERR_INVALID_STATE_TRANSITION", "Contract not ACTIVE/SUSPENDED")
    week_start = parse_date(body["week_start_date"], "week_start_date")
    nus = contract.get("next_unsettled_week_start")
    if isinstance(nus, str):
        nus = date.fromisoformat(nus)
    if nus is None or week_start != nus:
        raise_error("ERR_WEEK_NOT_SETTLABLE", "week_start_date must equal next_unsettled_week_start")
    week_end = week_start + timedelta(days=7)
    now_date = logical_now().date()
    if now_date < week_end:
        raise_error("ERR_WEEK_NOT_SETTLABLE", "Week has not fully ended")
    # sweep: open shipments with ship_date in week -> EXPIRED
    for s in list(store.shipments.values()):
        if s["contract_id"] != cid:
            continue
        if s["shipment_status"] not in ("RESERVED", "PACKED"):
            continue
        sd = s["ship_date"]
        if isinstance(sd, str):
            sd = date.fromisoformat(sd)
        if week_start <= sd < week_end:
            cancel_shipment_cascade(s, "EXPIRED")
    # FINAL fill rate + penalty
    shipped, _reserved = week_stats(contract, week_start)
    penalty, was_short = penalty_for_week(contract, shipped)
    if was_short:
        contract["consecutive_short_weeks"] = contract.get("consecutive_short_weeks", 0) + 1
    else:
        contract["consecutive_short_weeks"] = 0
    contract.setdefault("settled_penalties", {})[week_start.isoformat()] = penalty
    contract["next_unsettled_week_start"] = week_start + timedelta(days=7)
    # completion: final week settled past end_date and all weeks through end_date settled
    if week_end > contract["end_date"] and now_date > contract["end_date"]:
        # all weeks through end_date settled if next unsettled week starts after end_date
        if contract["next_unsettled_week_start"] > contract["end_date"]:
            contract["contract_status"] = "COMPLETED"
    touch(contract)
    return success(ser_contract(contract))
