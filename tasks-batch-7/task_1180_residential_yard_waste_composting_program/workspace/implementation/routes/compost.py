"""CompostGivebackEvent + CompostClaim endpoints (PRD §3.8)."""

import math
from decimal import Decimal

from flask import Blueprint, request

from db import STORE
from errors import (ApiError, ERR_ENTITLEMENT_EXCEEDED, ERR_GIVEBACK_EVENT_NOT_FOUND,
                    ERR_GIVEBACK_EVENT_NOT_OPEN, ERR_HOUSEHOLD_NOT_FOUND,
                    ERR_INSUFFICIENT_INVENTORY, ERR_PER_HOUSEHOLD_CAP_EXCEEDED,
                    ERR_ZONE_NOT_FOUND,
                    err_invalid_request, err_invalid_state, err_not_found,
                    err_resident_not_owner)
from middleware import require_roles
from response import success_list, success_object, parse_pagination
from services.core import (base_record, touch, giveback_event_out, claim_out,
                           giveback_event_status, household_remaining_entitlement,
                           parse_date)
from services.validate import require_body, check_unknown_fields, req_str, req_int, req_date

bp = Blueprint("compost", __name__)

READ_ROLES = ("Resident", "ProgramAdmin", "BillingClerk", "RouteSupervisor")
CLAIM_READ_ROLES = ("Resident", "BillingClerk", "ProgramAdmin")


# ---- CompostGivebackEvent ----

@bp.post("/giveback-events")
def create_giveback_event():
    require_roles("ProgramAdmin")
    data = require_body(request.get_json(silent=True))
    check_unknown_fields(data, {"zone_id", "event_date", "per_household_cap_gallons"})
    zone_id = req_str(data, "zone_id")
    event_date = req_date(data, "event_date")
    cap = req_int(data, "per_household_cap_gallons")
    if cap < 0:
        raise err_invalid_request("per_household_cap_gallons must be >= 0")

    zone = STORE.zones.get(zone_id)
    if not zone:
        raise err_not_found(ERR_ZONE_NOT_FOUND, "Zone not found")

    # initial inventory: floor(zone ACCEPTED delivery lbs in season x 0.025)
    season_start = parse_date(zone["season_start_date"])
    season_end = parse_date(zone["season_end_date"])
    zone_route_ids = {r["id"] for r in STORE.routes.values() if r["zone_id"] == zone_id}
    zone_accepted_lbs = 0
    for d in STORE.deliveries.values():
        if d["status"] != "ACCEPTED":
            continue
        if d["route_id"] not in zone_route_ids:
            continue
        dd = parse_date(d["delivery_date"])
        if season_start <= dd <= season_end:
            zone_accepted_lbs += d["accepted_weight_lbs"]
    initial = math.floor(zone_accepted_lbs * 0.5 / 20)

    e = base_record()
    e.update({
        "zone_id": zone_id, "event_date": event_date,
        "per_household_cap_gallons": cap,
        "initial_inventory_gallons": initial,
        "remaining_gallons": initial,
    })
    STORE.giveback_events[e["id"]] = e
    return success_object(giveback_event_out(e), 201)


@bp.get("/giveback-events")
def list_giveback_events():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(STORE.giveback_events.values())
    zid = request.args.get("zone_id")
    st = request.args.get("status")
    if zid is not None:
        items = [e for e in items if e["zone_id"] == zid]
    if st is not None:
        items = [e for e in items if giveback_event_status(e) == st]
    items.sort(key=lambda e: (e["created_at"], e["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([giveback_event_out(e) for e in page], limit, offset, total)


@bp.get("/giveback-events/<eid>")
def get_giveback_event(eid):
    require_roles(*READ_ROLES)
    e = STORE.giveback_events.get(eid)
    if not e:
        raise err_not_found(ERR_GIVEBACK_EVENT_NOT_FOUND, "Giveback event not found")
    return success_object(giveback_event_out(e))


# ---- CompostClaim ----

@bp.post("/compost-claims")
def create_claim():
    user_id, role = require_roles("Resident")
    data = require_body(request.get_json(silent=True))
    check_unknown_fields(data, {"giveback_event_id", "household_id", "gallons"})
    event_id = req_str(data, "giveback_event_id")
    household_id = req_str(data, "household_id")
    gallons = req_int(data, "gallons")
    if gallons < 1:
        raise err_invalid_request("gallons must be >= 1")

    # Resident ownership
    if user_id != household_id:
        raise err_resident_not_owner()

    # Body FK existence
    event = STORE.giveback_events.get(event_id)
    if not event:
        raise err_not_found(ERR_GIVEBACK_EVENT_NOT_FOUND, "Giveback event not found")
    hh = STORE.households.get(household_id)
    if not hh:
        raise err_not_found(ERR_HOUSEHOLD_NOT_FOUND, "Household not found")

    # state: event OPEN
    if giveback_event_status(event) != "OPEN":
        raise ApiError(ERR_GIVEBACK_EVENT_NOT_OPEN, "Giveback event is not OPEN", 409)

    # quota ladder (fixed order): entitlement -> per-household cap -> inventory
    remaining_ent = household_remaining_entitlement(household_id)
    if Decimal(gallons) > remaining_ent:
        raise ApiError(ERR_ENTITLEMENT_EXCEEDED,
                       "Claim exceeds household remaining compost entitlement", 422)

    claimed = sum(c["gallons"] for c in STORE.claims.values()
                  if c["giveback_event_id"] == event_id and c["household_id"] == household_id
                  and c["status"] == "FULFILLED")
    if claimed + gallons > event["per_household_cap_gallons"]:
        raise ApiError(ERR_PER_HOUSEHOLD_CAP_EXCEEDED,
                       "Claim would exceed the per-household cap at this event", 422)

    if gallons > event["remaining_gallons"]:
        raise ApiError(ERR_INSUFFICIENT_INVENTORY,
                       "Claim exceeds remaining event inventory", 409)

    snapshot = float(Decimal(str(hh.get("compost_entitlement_gallons", 0))))
    c = base_record()
    c.update({
        "giveback_event_id": event_id, "household_id": household_id,
        "gallons": gallons, "status": "FULFILLED",
        "entitlement_snapshot_gallons": snapshot,
    })
    STORE.claims[c["id"]] = c
    event["remaining_gallons"] -= gallons
    touch(event)
    return success_object(claim_out(c), 201)


@bp.get("/compost-claims")
def list_claims():
    require_roles(*CLAIM_READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(STORE.claims.values())
    eid = request.args.get("giveback_event_id")
    hid = request.args.get("household_id")
    st = request.args.get("status")
    if eid is not None:
        items = [c for c in items if c["giveback_event_id"] == eid]
    if hid is not None:
        items = [c for c in items if c["household_id"] == hid]
    if st is not None:
        items = [c for c in items if c["status"] == st]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([claim_out(c) for c in page], limit, offset, total)


@bp.get("/compost-claims/<cid>")
def get_claim(cid):
    require_roles(*CLAIM_READ_ROLES)
    c = STORE.claims.get(cid)
    if not c:
        raise err_not_found()
    return success_object(claim_out(c))


@bp.post("/compost-claims/<cid>/void")
def void_claim(cid):
    require_roles("BillingClerk")
    c = STORE.claims.get(cid)
    if not c:
        raise err_not_found()
    if c["status"] != "FULFILLED":
        raise err_invalid_state("Claim is not FULFILLED")
    c["status"] = "VOIDED"
    touch(c)
    event = STORE.giveback_events.get(c["giveback_event_id"])
    if event:
        event["remaining_gallons"] += c["gallons"]
        touch(event)
    return success_object(claim_out(c))
