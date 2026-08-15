"""Membership levels and premiums (config)."""

from flask import Blueprint, request

import db
import response
import validators as v
from errors import ApiError, ERR_DUPLICATE_CODE, ERR_NOT_FOUND
from middleware import require_roles

bp = Blueprint("levels_premiums", __name__)

ALL_ROLES = ("StationAdmin", "MembershipCoordinator", "PhoneVolunteer")


# --- Membership levels ---

@bp.route("/station/membership-levels", methods=["POST"])
def create_level():
    body = v.get_json_body()
    require_roles("StationAdmin")
    code = v.req_str(body, "code")
    min_annual = v.req_int(body, "min_annual_cents", min_val=0)
    min_sustainer = v.req_int(body, "min_monthly_sustainer_cents", min_val=0)
    premium_eligible = v.opt_bool(body, "premium_eligible", default=True)
    active = v.opt_bool(body, "active", default=True)

    if code in db.membership_levels_by_code:
        raise ApiError(ERR_DUPLICATE_CODE[0], f"MembershipLevel.code '{code}' already exists", ERR_DUPLICATE_CODE[1])

    ent = db.new_entity()
    ent.update({
        "code": code,
        "min_annual_cents": min_annual,
        "min_monthly_sustainer_cents": min_sustainer,
        "premium_eligible": premium_eligible,
        "active": active,
    })
    db.membership_levels[ent["id"]] = ent
    db.membership_levels_by_code[code] = ent["id"]
    return response.success_object(ent, status=201)


@bp.route("/station/membership-levels", methods=["GET"])
def list_levels():
    require_roles(*ALL_ROLES)
    limit, offset = v.parse_pagination(request.args)
    items = list(db.membership_levels.values())
    active_q = request.args.get("active")
    if active_q is not None:
        if active_q.lower() == "true":
            items = [m for m in items if m["active"]]
        elif active_q.lower() == "false":
            items = [m for m in items if not m["active"]]
        else:
            v.invalid("Query parameter 'active' must be 'true' or 'false'")
    items = v.sort_created(items)
    page, total = v.paginate(items, limit, offset)
    return response.success_list(page, limit, offset, total)


# --- Premiums ---

@bp.route("/station/premiums", methods=["POST"])
def create_premium():
    body = v.get_json_body()
    require_roles("StationAdmin")
    sku = v.req_str(body, "sku")
    title = v.req_str(body, "title")
    fmv = v.req_int(body, "fair_market_value_cents", min_val=0)
    level_code = v.req_str(body, "membership_level_code")
    active = v.opt_bool(body, "active", default=True)

    if sku in db.premiums_by_sku:
        raise ApiError(ERR_DUPLICATE_CODE[0], f"Premium.sku '{sku}' already exists", ERR_DUPLICATE_CODE[1])
    # FK validation: membership_level_code must exist
    if level_code not in db.membership_levels_by_code:
        raise ApiError(ERR_NOT_FOUND[0], f"MembershipLevel '{level_code}' not found", ERR_NOT_FOUND[1])

    ent = db.new_entity()
    ent.update({
        "sku": sku,
        "title": title,
        "fair_market_value_cents": fmv,
        "membership_level_code": level_code,
        "active": active,
    })
    db.premiums[ent["id"]] = ent
    db.premiums_by_sku[sku] = ent["id"]
    return response.success_object(ent, status=201)


@bp.route("/station/premiums/<pid>", methods=["GET"])
def get_premium(pid):
    require_roles(*ALL_ROLES)
    ent = db.premiums.get(pid)
    if ent is None:
        v.not_found(f"Premium '{pid}' not found")
    return response.success_object(ent)


# --- Inventory lots ---

@bp.route("/station/premiums/<pid>/lots", methods=["POST"])
def create_lot(pid):
    body = v.get_json_body()
    require_roles("MembershipCoordinator")
    premium = db.premiums.get(pid)
    if premium is None:
        v.not_found(f"Premium '{pid}' not found")
    received_at = v.req_dt(body, "received_at")
    unit_cost = v.req_int(body, "unit_cost_cents", min_val=0)
    total_qty = v.req_int(body, "total_qty", min_val=1)

    ent = db.new_entity()
    ent.update({
        "premium_id": pid,
        "received_at": db.iso(received_at),
        "unit_cost_cents": unit_cost,
        "total_qty": total_qty,
        "available_qty": total_qty,
        "reserved_qty": 0,
        "committed_qty": 0,
        "written_off_qty": 0,
    })
    db.lots[ent["id"]] = ent
    return response.success_object(ent, status=201)


@bp.route("/station/premiums/<pid>/lots", methods=["GET"])
def list_lots(pid):
    require_roles("StationAdmin", "MembershipCoordinator")
    if pid not in db.premiums:
        v.not_found(f"Premium '{pid}' not found")
    limit, offset = v.parse_pagination(request.args)
    items = [l for l in db.lots.values() if l["premium_id"] == pid]
    items = v.sort_created(items)
    page, total = v.paginate(items, limit, offset)
    return response.success_list(page, limit, offset, total)
