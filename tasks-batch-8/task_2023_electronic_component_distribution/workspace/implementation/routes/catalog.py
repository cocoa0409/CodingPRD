"""ManufacturerLine and Part endpoints."""

from flask import Blueprint, request

import db
import errors as E
from errors import ApiError
from middleware import require_auth, require_role
from response import success
from services.helpers import (
    get_json_body,
    get_line_or_404,
    get_part_or_404,
    mint_id,
    opt_bool,
    opt_int,
    opt_str,
    paginate,
    pagination_params,
    req_enum,
    req_int,
    req_str,
    serialize_manufacturer_line,
    serialize_part,
    stamp_now,
)

bp = Blueprint("catalog", __name__)

_seq = 0


def _next_seq():
    global _seq
    _seq += 1
    return _seq


# ---------------------------------------------------------------------------
# ManufacturerLine
# ---------------------------------------------------------------------------

@bp.post("/manufacturer-lines")
def create_manufacturer_line():
    user_id, role = require_auth()
    require_role(user_id, role, {"DistributorAdmin"})
    body = get_json_body()
    line_code = req_str(body, "line_code")
    name = req_str(body, "name")
    sourcing_channel = req_enum(body, "sourcing_channel", {"FRANCHISED", "OPEN_MARKET"})
    ncnr = opt_bool(body, "ncnr", False)
    cancel_window_days = opt_int(body, "cancel_window_days", 30)
    reschedule_window_days = opt_int(body, "reschedule_window_days", 20)
    allocation_policy = opt_str(body, "allocation_policy", "BACKLOG_BASIS")
    if allocation_policy not in ("BACKLOG_BASIS", "USAGE_BASIS"):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "Invalid allocation_policy.")

    for existing in db.manufacturer_lines.values():
        if existing["line_code"] == line_code:
            raise ApiError(E.ERR_DUPLICATE_LINE_CODE, 409, "line_code already exists.")

    now = stamp_now()
    line = {
        "id": mint_id(),
        "line_code": line_code,
        "name": name,
        "sourcing_channel": sourcing_channel,
        "ncnr": ncnr,
        "cancel_window_days": cancel_window_days,
        "reschedule_window_days": reschedule_window_days,
        "allocation_policy": allocation_policy,
        "open_debit_balance_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": _next_seq(),
    }
    db.manufacturer_lines[line["id"]] = line
    return success(serialize_manufacturer_line(line), status=201)


@bp.get("/manufacturer-lines")
def list_manufacturer_lines():
    require_auth()
    limit, offset = pagination_params()
    items = sorted(db.manufacturer_lines.values(), key=lambda l: (l["created_at"], l["_seq"]))
    page, pag = paginate(items, limit, offset)
    return success(
        [serialize_manufacturer_line(l) for l in page],
        status=200,
        response_type="array",
        pagination=pag,
    )


@bp.get("/manufacturer-lines/<lineId>")
def get_manufacturer_line(lineId):
    require_auth()
    line = get_line_or_404(lineId)
    return success(serialize_manufacturer_line(line), status=200)


# ---------------------------------------------------------------------------
# Part
# ---------------------------------------------------------------------------

@bp.post("/parts")
def create_part():
    user_id, role = require_auth()
    require_role(user_id, role, {"DistributorAdmin"})
    body = get_json_body()
    manufacturer_line_id = req_str(body, "manufacturer_line_id")
    part_number = req_str(body, "part_number")
    msl_level = req_int(body, "msl_level")
    floor_life_hours = req_int(body, "floor_life_hours")
    date_code_limit_months = req_int(body, "date_code_limit_months")
    standard_cost_cents = req_int(body, "standard_cost_cents")
    book_price_cents = req_int(body, "book_price_cents")

    line = db.manufacturer_lines.get(manufacturer_line_id)
    if line is None:
        raise ApiError(E.ERR_MANUFACTURER_LINE_NOT_FOUND, 404, "Manufacturer line not found.")

    for existing in db.parts.values():
        if (
            existing["manufacturer_line_id"] == manufacturer_line_id
            and existing["part_number"] == part_number
        ):
            raise ApiError(
                E.ERR_DUPLICATE_PART_NUMBER,
                409,
                "part_number already exists within the manufacturer line.",
            )

    now = stamp_now()
    part = {
        "id": mint_id(),
        "manufacturer_line_id": manufacturer_line_id,
        "part_number": part_number,
        "msl_level": msl_level,
        "floor_life_hours": floor_life_hours,
        "date_code_limit_months": date_code_limit_months,
        "standard_cost_cents": standard_cost_cents,
        "book_price_cents": book_price_cents,
        "qty_on_hand": 0,
        "qty_reserved": 0,
        "open_demand_qty": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": _next_seq(),
    }
    db.parts[part["id"]] = part
    return success(serialize_part(part), status=201)


@bp.get("/parts")
def list_parts():
    require_auth()
    limit, offset = pagination_params()
    ml_id = request.args.get("manufacturer_line_id")
    items = [p for p in db.parts.values() if ml_id is None or p["manufacturer_line_id"] == ml_id]
    items.sort(key=lambda p: (p["created_at"], p["_seq"]))
    page, pag = paginate(items, limit, offset)
    return success(
        [serialize_part(p) for p in page],
        status=200,
        response_type="array",
        pagination=pag,
    )


@bp.get("/parts/<partId>")
def get_part(partId):
    require_auth()
    part = get_part_or_404(partId)
    return success(serialize_part(part), status=200)
