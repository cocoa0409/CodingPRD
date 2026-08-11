"""ServiceZone endpoints (PRD §3.1)."""

from flask import Blueprint, request

from db import STORE
from errors import (ApiError, ERR_ZONE_NOT_FOUND, err_invalid_request,
                    err_invalid_state, err_not_found)
from middleware import require_roles
from response import success_list, success_object, parse_pagination
from services.core import (base_record, touch, zone_out, zone_status, parse_date)
from services.validate import (require_body, check_unknown_fields, req_str, req_int,
                               req_enum, req_date, opt_int, opt_date)

bp = Blueprint("zones", __name__)

ALL_ROLES = ("Anonymous", "Resident", "Driver", "FieldInspector", "RouteSupervisor",
             "BillingClerk", "ProgramAdmin", "OutreachCoordinator")


@bp.post("/service-zones")
def create_zone():
    require_roles("ProgramAdmin")
    data = require_body(request.get_json(silent=True))
    check_unknown_fields(data, {"name", "service_model", "season_start_date", "season_end_date",
                                "base_seasonal_fee_cents", "universal_flat_credit_cents",
                                "max_strikes_per_season"})
    name = req_str(data, "name")
    model = req_enum(data, "service_model", {"OPT_IN", "UNIVERSAL"})
    start = req_date(data, "season_start_date")
    end = req_date(data, "season_end_date")
    base_fee = req_int(data, "base_seasonal_fee_cents")
    flat_credit = req_int(data, "universal_flat_credit_cents")
    max_strikes = opt_int(data, "max_strikes_per_season", 3)
    if parse_date(end) < parse_date(start):
        raise err_invalid_request("season_end_date must be on or after season_start_date")

    z = base_record()
    z.update({
        "name": name, "service_model": model,
        "season_start_date": start, "season_end_date": end,
        "base_seasonal_fee_cents": base_fee,
        "universal_flat_credit_cents": flat_credit,
        "max_strikes_per_season": max_strikes,
    })
    STORE.zones[z["id"]] = z
    return success_object(zone_out(z), 201)


@bp.get("/service-zones")
def list_zones():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(STORE.zones.values())
    sm = request.args.get("service_model")
    st = request.args.get("status")
    if sm is not None:
        items = [z for z in items if z["service_model"] == sm]
    if st is not None:
        items = [z for z in items if zone_status(z) == st]
    items.sort(key=lambda z: (z["created_at"], z["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([zone_out(z) for z in page], limit, offset, total)


@bp.get("/service-zones/<zid>")
def get_zone(zid):
    require_roles(*ALL_ROLES)
    z = STORE.zones.get(zid)
    if not z:
        raise err_not_found(ERR_ZONE_NOT_FOUND, "Zone not found")
    return success_object(zone_out(z))


@bp.patch("/service-zones/<zid>")
def patch_zone(zid):
    require_roles("ProgramAdmin")
    z = STORE.zones.get(zid)
    if not z:
        raise err_not_found(ERR_ZONE_NOT_FOUND, "Zone not found")
    data = require_body(request.get_json(silent=True))
    check_unknown_fields(data, {"base_seasonal_fee_cents", "universal_flat_credit_cents",
                                "season_start_date", "season_end_date", "max_strikes_per_season"})

    # window fields only editable when OFF_SEASON (PRD §3.1)
    if "season_start_date" in data or "season_end_date" in data:
        if zone_status(z) != "OFF_SEASON":
            raise err_invalid_state("Season window may only be changed while OFF_SEASON")
        new_start = req_date(data, "season_start_date") if "season_start_date" in data else z["season_start_date"]
        new_end = req_date(data, "season_end_date") if "season_end_date" in data else z["season_end_date"]
        if parse_date(new_end) < parse_date(new_start):
            raise err_invalid_request("season_end_date must be on or after season_start_date")
        z["season_start_date"] = new_start
        z["season_end_date"] = new_end

    if "base_seasonal_fee_cents" in data:
        z["base_seasonal_fee_cents"] = req_int(data, "base_seasonal_fee_cents")
    if "universal_flat_credit_cents" in data:
        z["universal_flat_credit_cents"] = req_int(data, "universal_flat_credit_cents")
    if "max_strikes_per_season" in data:
        z["max_strikes_per_season"] = req_int(data, "max_strikes_per_season")

    touch(z)
    return success_object(zone_out(z))
