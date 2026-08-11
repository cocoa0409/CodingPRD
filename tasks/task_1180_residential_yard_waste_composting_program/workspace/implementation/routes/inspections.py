"""ContaminationInspection endpoints (PRD §3.5)."""

from flask import Blueprint, request

from db import STORE
from errors import (ApiError, ERR_DUPLICATE_INSPECTION, ERR_TICKET_NOT_FOUND,
                    ERR_TICKET_NOT_SCHEDULED,
                    err_invalid_request, err_not_found)
from middleware import require_roles
from response import success_list, success_object, parse_pagination
from services.core import (light_record, inspection_out,
                           suspend_subscription, touch, parse_date, VIOLATION_CODES)
from services.validate import require_body, check_unknown_fields, req_str, opt_str

bp = Blueprint("inspections", __name__)

READ_ROLES = ("FieldInspector", "RouteSupervisor", "ProgramAdmin", "Resident", "BillingClerk")


@bp.post("/contamination-inspections")
def create_inspection():
    user_id, role = require_roles("FieldInspector")
    data = require_body(request.get_json(silent=True))
    check_unknown_fields(data, {"pickup_ticket_id", "result", "violation_codes", "notes"})
    ticket_id = req_str(data, "pickup_ticket_id")
    result = req_str(data, "result")
    if result not in ("PASSED", "TAGGED_WARNING", "TAGGED_REJECTED"):
        raise err_invalid_request("result must be PASSED | TAGGED_WARNING | TAGGED_REJECTED")
    if "violation_codes" not in data or data["violation_codes"] is None:
        raise err_invalid_request("violation_codes is required")
    codes = data["violation_codes"]
    if not isinstance(codes, list) or any(not isinstance(c, str) for c in codes):
        raise err_invalid_request("violation_codes must be a list of strings")
    for c in codes:
        if c not in VIOLATION_CODES:
            raise err_invalid_request(f"Unknown violation code: {c}")
    if result == "PASSED":
        if len(codes) != 0:
            raise err_invalid_request("violation_codes must be empty when result is PASSED")
    else:
        if len(codes) == 0:
            raise err_invalid_request("violation_codes must be non-empty for TAGGED_* results")
    notes = opt_str(data, "notes", None)

    # body FK existence
    ticket = STORE.tickets.get(ticket_id)
    if not ticket:
        raise err_not_found(ERR_TICKET_NOT_FOUND, "Ticket not found")

    # state: ticket must be SCHEDULED
    if ticket["status"] != "SCHEDULED":
        raise ApiError(ERR_TICKET_NOT_SCHEDULED, "Ticket is not SCHEDULED", 409)

    # uniqueness: one inspection per ticket
    for i in STORE.inspections.values():
        if i["pickup_ticket_id"] == ticket_id:
            raise ApiError(ERR_DUPLICATE_INSPECTION,
                           "Ticket already has a contamination inspection", 409)

    insp = light_record()
    insp.update({
        "pickup_ticket_id": ticket_id,
        "result": result,
        "violation_codes": codes,
        "notes": notes,
        "inspector_user_id": user_id,
    })
    STORE.inspections[insp["id"]] = insp

    if result == "TAGGED_REJECTED":
        ticket["status"] = "REJECTED_CONTAMINATION"
        touch(ticket)
        sub = STORE.subscriptions.get(ticket["subscription_id"])
        if sub:
            # strikes_this_season is a stored counter: +1 per TAGGED_REJECTED
            # (PRD §3.5), reset to zero by a successful cure — it is NOT
            # derived from the inspection log, or the reset could never hold.
            sub["strikes_this_season"] += 1
            strikes = sub["strikes_this_season"]
            hh = STORE.households.get(sub["household_id"])
            zone = STORE.zones.get(hh["zone_id"]) if hh else None
            max_strikes = zone["max_strikes_per_season"] if zone else 3
            if strikes >= max_strikes and sub["status"] == "ACTIVE":
                suspend_subscription(sub)
            else:
                touch(sub)

    return success_object(inspection_out(insp), 201)


@bp.get("/contamination-inspections")
def list_inspections():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(STORE.inspections.values())
    tid = request.args.get("pickup_ticket_id")
    res = request.args.get("result")
    if tid is not None:
        items = [i for i in items if i["pickup_ticket_id"] == tid]
    if res is not None:
        items = [i for i in items if i["result"] == res]
    items.sort(key=lambda i: (i["created_at"], i["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([inspection_out(i) for i in page], limit, offset, total)


@bp.get("/contamination-inspections/<iid>")
def get_inspection(iid):
    require_roles(*READ_ROLES)
    i = STORE.inspections.get(iid)
    if not i:
        raise err_not_found()
    return success_object(inspection_out(i))
