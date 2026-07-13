"""Drivers (PRD §3.1)."""
import re

from flask import Blueprint, g, request

import response
from db import base_record, db
from errors import err
from middleware import (body, check_fleet, is_fleet_manager, opt_enum, paginate, query_enum,
                        req_str, require_roles)
from services import serialize
from services.store import DRIVER_STATUSES, get_account, get_driver

bp = Blueprint("drivers", __name__)

PIN_RE = re.compile(r"^\d{4}$")


@bp.post("/drivers")
@require_roles("FleetManager")
def create_driver():
    data = body()
    fleet_account_id = req_str(data, "fleet_account_id")
    full_name = req_str(data, "full_name")
    pin = req_str(data, "pin")
    if not PIN_RE.match(pin):
        raise err("ERR_VALIDATION", "Field 'pin' must be exactly 4 digits.")
    status = opt_enum(data, "status", DRIVER_STATUSES, "ACTIVE")

    account = get_account(fleet_account_id)
    check_fleet(account["id"])

    record = base_record()
    record.update({
        "fleet_account_id": fleet_account_id,
        "full_name": full_name,
        "pin": pin,
        "status": status,
    })
    db.drivers[record["id"]] = record
    return response.created(serialize.driver(record))


@bp.get("/drivers/<driver_id>")
@require_roles("FleetManager", "ProgramAdmin")
def fetch_driver(driver_id):
    driver = get_driver(driver_id)
    check_fleet(driver["fleet_account_id"])
    return response.ok(serialize.driver(driver))


@bp.get("/drivers")
@require_roles("FleetManager", "ProgramAdmin")
def list_drivers():
    account_filter = request.args.get("fleet_account_id")
    status_filter = query_enum("status", DRIVER_STATUSES)

    if is_fleet_manager():
        if account_filter is not None and account_filter != g.user_id:
            raise err("ERR_FORBIDDEN_FLEET")
        account_filter = g.user_id

    records = list(db.drivers.values())
    if account_filter is not None:
        records = [d for d in records if d["fleet_account_id"] == account_filter]
    if status_filter is not None:
        records = [d for d in records if d["status"] == status_filter]

    page, total, limit, offset = paginate(records)
    return response.listing([serialize.driver(d) for d in page], limit, offset, total)
