"""Household endpoints (PRD §3.1)."""

from flask import Blueprint, request

from db import STORE
from errors import (ERR_HOUSEHOLD_NOT_FOUND, ERR_ZONE_NOT_FOUND,
                    err_not_found, err_resident_not_owner)
from middleware import require_roles
from response import success_list, success_object, parse_pagination
from services.core import base_record, household_out
from services.validate import require_body, check_unknown_fields, req_str

bp = Blueprint("households", __name__)


@bp.post("/households")
def create_household():
    require_roles("Anonymous")
    data = require_body(request.get_json(silent=True))
    check_unknown_fields(data, {"address_line", "zone_id"})
    address = req_str(data, "address_line")
    zone_id = req_str(data, "zone_id")
    if zone_id not in STORE.zones:
        raise err_not_found(ERR_ZONE_NOT_FOUND, "Zone not found")

    h = base_record()
    h.update({
        "address_line": address,
        "zone_id": zone_id,
        "credit_balance_cents": 0,
        "compost_entitlement_gallons": 0.0,
    })
    STORE.households[h["id"]] = h
    return success_object(household_out(h), 201)


@bp.get("/households")
def list_households():
    require_roles("ProgramAdmin", "BillingClerk", "RouteSupervisor")
    limit, offset = parse_pagination(request.args)
    items = list(STORE.households.values())
    zid = request.args.get("zone_id")
    if zid is not None:
        items = [h for h in items if h["zone_id"] == zid]
    items.sort(key=lambda h: (h["created_at"], h["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([household_out(h) for h in page], limit, offset, total)


@bp.get("/households/<hid>")
def get_household(hid):
    user_id, role = require_roles("Resident", "ProgramAdmin", "BillingClerk", "RouteSupervisor")
    h = STORE.households.get(hid)
    if not h:
        raise err_not_found(ERR_HOUSEHOLD_NOT_FOUND, "Household not found")
    if role == "Resident" and user_id != h["id"]:
        raise err_resident_not_owner()
    return success_object(household_out(h))
