"""Inventory financing lines and reserves (PRD §3.6)."""

from flask import Blueprint, request

from db import DB
from errors import (
    ERR_FACILITY_LIMIT_EXCEEDED, ERR_INVALID_STATE, ERR_LOT_NOT_PLEDGEABLE,
    ERR_NOT_FOUND, err,
)
from middleware import (
    COMMON_SYS, D, base_fields, check_unknown_fields, get_json_body,
    is_number, paginate, pub, require_fields, require_role, sort_created,
    touch, v_int, v_num, v_string,
)
from response import success_list, success_object
from services import recompute_position, reserve_advance, reserve_collateral

bp = Blueprint("financing", __name__)

LINE_ALLOWED = {
    "lender_name", "facility_limit_usd", "advance_rate_pct",
    "utilized_usd", "collateral_value_usd", "financing_status",
} | COMMON_SYS

RESERVE_ALLOWED = {
    "green_lot_id", "reserved_lbs", "financing_line_id",
    "reserve_advance_usd", "reserve_status",
} | COMMON_SYS

READ_ROLES = ("RiskManager", "Trader")


def get_line_or_404(line_id):
    line = DB.financing_lines.get(line_id)
    if line is None:
        raise err(ERR_NOT_FOUND, "Financing line id does not exist")
    return line


def get_reserve_or_404(reserve_id):
    r = DB.financing_reserves.get(reserve_id)
    if r is None:
        raise err(ERR_NOT_FOUND, "Financing reserve id does not exist")
    return r


@bp.post("/roastery/financing-lines")
def create_financing_line():
    require_role("RiskManager")
    body = get_json_body()
    check_unknown_fields(body, LINE_ALLOWED)
    require_fields(body, ["lender_name", "facility_limit_usd", "advance_rate_pct"])
    lender = v_string(body, "lender_name")
    limit = v_num(body, "facility_limit_usd")
    rate = v_num(body, "advance_rate_pct", ge=0, le=1)
    line = base_fields()
    line.update({
        "lender_name": lender,
        "facility_limit_usd": limit,
        "advance_rate_pct": rate,
        "utilized_usd": 0.0,
        "collateral_value_usd": 0.0,
        "financing_status": "OPEN",
    })
    DB.financing_lines[line["id"]] = line
    return success_object(pub(line), status=201)


@bp.get("/roastery/financing-lines/<line_id>")
def get_financing_line(line_id):
    require_role(*READ_ROLES)
    return success_object(pub(get_line_or_404(line_id)))


@bp.post("/roastery/financing-lines/<line_id>/reserves")
def create_reserve(line_id):
    require_role("RiskManager")
    line = get_line_or_404(line_id)
    body = get_json_body()

    # Priority 5: body FK existence.
    lot_id = body.get("green_lot_id")
    lot = None
    if isinstance(lot_id, str):
        lot = DB.green_lots.get(lot_id)
    if lot is None and isinstance(lot_id, str):
        raise err(ERR_NOT_FOUND, "Green lot id does not exist")

    # Priority 6: a SUSPENDED (or CLOSED) line blocks new reserves.
    if line["financing_status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Financing line is not OPEN")

    reserved_raw = body.get("reserved_lbs")
    # Priority 14: facility headroom.
    if is_number(reserved_raw) and lot is not None:
        advance = reserve_advance(int(reserved_raw), lot, line)
        if D(line["utilized_usd"]) + D(advance) > D(line["facility_limit_usd"]):
            raise err(ERR_FACILITY_LIMIT_EXCEEDED,
                      "New reserve would push utilized_usd above facility_limit_usd")
    # Priority 21: pledgeability.
    if lot is not None and is_number(reserved_raw):
        if lot["lot_status"] != "RELEASED" or int(reserved_raw) > lot["available_lbs"]:
            raise err(ERR_LOT_NOT_PLEDGEABLE,
                      "Lot must be RELEASED and reserved_lbs must not exceed available_lbs")

    # Priorities 22/23: structural.
    check_unknown_fields(body, RESERVE_ALLOWED)
    require_fields(body, ["green_lot_id", "reserved_lbs"])
    reserved = v_int(body, "reserved_lbs", gt=0)
    if lot is None:
        raise err(ERR_NOT_FOUND, "Green lot id does not exist")

    advance = reserve_advance(reserved, lot, line)
    collateral = reserve_collateral(reserved, lot)

    r = base_fields()
    r.update({
        "financing_line_id": line["id"],
        "green_lot_id": lot["id"],
        "reserved_lbs": reserved,
        "reserve_advance_usd": advance,
        "reserve_status": "ACTIVE",
        "_collateral_usd": collateral,
    })
    DB.financing_reserves[r["id"]] = r

    lot["available_lbs"] -= reserved
    touch(lot)
    line["utilized_usd"] = float(D(line["utilized_usd"]) + D(advance))
    line["collateral_value_usd"] = float(D(line["collateral_value_usd"]) + D(collateral))
    touch(line)
    recompute_position()
    return success_object(pub(r), status=201)


@bp.post("/roastery/financing-reserves/<reserve_id>/release")
def release_reserve(reserve_id):
    require_role("RiskManager")
    r = get_reserve_or_404(reserve_id)
    get_json_body()
    if r["reserve_status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Release requires reserve_status ACTIVE")
    r["reserve_status"] = "RELEASED"
    touch(r)

    lot = DB.green_lots.get(r["green_lot_id"])
    if lot is not None:
        lot["available_lbs"] += r["reserved_lbs"]
        touch(lot)
    line = DB.financing_lines.get(r["financing_line_id"])
    if line is not None:
        line["utilized_usd"] = float(D(line["utilized_usd"]) - D(r["reserve_advance_usd"]))
        line["collateral_value_usd"] = float(
            D(line["collateral_value_usd"]) - D(r["_collateral_usd"]))
        touch(line)
    recompute_position()
    return success_object(pub(r))


@bp.post("/roastery/financing-lines/<line_id>/suspend")
def suspend_line(line_id):
    require_role("RiskManager")
    line = get_line_or_404(line_id)
    get_json_body()
    if line["financing_status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Suspend requires financing_status OPEN")
    line["financing_status"] = "SUSPENDED"
    touch(line)
    return success_object(pub(line))


@bp.post("/roastery/financing-lines/<line_id>/unsuspend")
def unsuspend_line(line_id):
    require_role("RiskManager")
    line = get_line_or_404(line_id)
    get_json_body()
    if line["financing_status"] != "SUSPENDED":
        raise err(ERR_INVALID_STATE, "Unsuspend requires financing_status SUSPENDED")
    line["financing_status"] = "OPEN"
    touch(line)
    return success_object(pub(line))


@bp.post("/roastery/financing-lines/<line_id>/close")
def close_line(line_id):
    require_role("RiskManager")
    line = get_line_or_404(line_id)
    get_json_body()
    if line["financing_status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Close requires financing_status OPEN")
    has_active = any(
        r["financing_line_id"] == line["id"] and r["reserve_status"] == "ACTIVE"
        for r in DB.financing_reserves.values()
    )
    if D(line["utilized_usd"]) != 0 or has_active:
        raise err(ERR_INVALID_STATE,
                  "Close requires zero utilization and no ACTIVE reserves")
    line["financing_status"] = "CLOSED"
    touch(line)
    return success_object(pub(line))


@bp.get("/roastery/financing-reserves/<reserve_id>")
def get_reserve(reserve_id):
    require_role(*READ_ROLES)
    return success_object(pub(get_reserve_or_404(reserve_id)))


@bp.get("/roastery/financing-reserves")
def list_reserves():
    require_role(*READ_ROLES)
    items = sort_created(DB.financing_reserves.values())
    line_id = request.args.get("financing_line_id")
    lot_id = request.args.get("green_lot_id")
    status = request.args.get("reserve_status")
    if line_id is not None:
        items = [r for r in items if r["financing_line_id"] == line_id]
    if lot_id is not None:
        items = [r for r in items if r["green_lot_id"] == lot_id]
    if status is not None:
        items = [r for r in items if r["reserve_status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([pub(r) for r in page], limit, offset, total)
