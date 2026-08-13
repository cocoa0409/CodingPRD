"""Timekeeper endpoints (PRD §3.1)."""
from flask import Blueprint

import db
import util
from middleware import get_context, require_roles
from response import success_object, success_list

bp = Blueprint("timekeepers", __name__)

ROLE_TITLES = {"ASSOCIATE", "PARTNER", "OF_COUNSEL", "PARALEGAL"}


@bp.post("/firms/<firmId>/timekeepers")
def create_timekeeper(firmId):
    ctx = get_context()
    require_roles(ctx, "FirmAdmin")
    firm = util.get_firm(firmId)
    data = util.body()
    util.require_fields(data, ["full_name", "bar_number", "role_title", "standard_rate_cents"])
    full_name = util.check_string(data, "full_name")
    bar_number = util.check_string(data, "bar_number")
    role_title = util.check_enum(data, "role_title", ROLE_TITLES)
    rate = util.check_int(data, "standard_rate_cents")

    tk = util.new_resource()
    tk.update({
        "firm_id": firm["id"],
        "full_name": full_name,
        "bar_number": bar_number,
        "role_title": role_title,
        "standard_rate_cents": rate,
        "status": "ACTIVE",
    })
    db.timekeepers[tk["id"]] = tk
    return success_object(tk, 201)


@bp.get("/firms/timekeepers/<timekeeperId>")
def get_timekeeper(timekeeperId):
    ctx = get_context()
    require_roles(ctx, "FirmAdmin", "PricingAnalyst", "BillingPartner",
                  "ManagingPartner", "Timekeeper")
    tk = util.get_timekeeper_flat(timekeeperId)
    return success_object(tk, 200)


@bp.get("/firms/timekeepers")
def list_timekeepers():
    ctx = get_context()
    require_roles(ctx, "FirmAdmin", "PricingAnalyst", "BillingPartner",
                  "ManagingPartner", "Timekeeper")
    filters = util.query_filters(["firm_id", "status", "role_title"])
    items = util.apply_filters(list(db.timekeepers.values()), filters)
    window, meta = util.paginate(items)
    return success_list(window, meta, 200)
