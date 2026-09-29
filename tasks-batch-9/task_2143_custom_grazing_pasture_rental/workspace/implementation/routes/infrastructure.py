"""Water and fence infrastructure tickets."""
from flask import Blueprint, request

from common import (authenticate, body_of, req_dt_str, req_enum, req_int,
                    req_str)
from derive import (infrastructure_allocation, recompute_pasture,
                    sorted_records)
from envelope import created, listing, ok, pagination, public, public_list
from errors import ApiError
from store import db, new_record, touch

bp = Blueprint("infrastructure", __name__)

ALL_ROLES = ("Grazier", "CattleOwner", "RangeConsultant", "PlatformAdmin")
ASSET_TYPES = ("WATER", "FENCE")
SEVERITIES = ("CRITICAL", "MAJOR", "MINOR")
REPAIR_PARTIES = ("GRAZIER", "OWNER")
CAUSES = ("WEAR", "STORM", "LIVESTOCK_DAMAGE", "NEGLECT")


def get_ticket(ticket_id):
    ticket = db.tickets.get(ticket_id)
    if ticket is None:
        raise ApiError("ERR_TICKET_NOT_FOUND", "Infrastructure ticket does not exist.")
    return ticket


@bp.post("/grazing/infrastructure-tickets")
def open_ticket():
    actor = authenticate(("Grazier", "CattleOwner"))
    body = body_of()

    # priority 5 — body identifiers resolve
    pasture_id = body.get("pasture_id")
    if pasture_id is not None and (not isinstance(pasture_id, str) or pasture_id not in db.pastures):
        raise ApiError("ERR_PASTURE_NOT_FOUND", "pasture_id does not resolve.")
    contract_id = body.get("contract_id")
    if contract_id is not None and (not isinstance(contract_id, str) or contract_id not in db.contracts):
        raise ApiError("ERR_CONTRACT_NOT_FOUND", "contract_id does not resolve.")

    pasture_id = req_str(body, "pasture_id")
    contract_id = req_str(body, "contract_id")
    asset_type = req_enum(body, "asset_type", ASSET_TYPES)
    severity = req_enum(body, "severity", SEVERITIES)
    description = req_str(body, "description")
    reported_at = req_dt_str(body, "reported_at")

    pasture = db.pastures[pasture_id]
    contract = db.contracts[contract_id]
    if actor.is_grazier and pasture["grazier_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "The pasture belongs to another grazier.")
    if actor.is_owner and contract["cattle_owner_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "The contract belongs to another cattle owner.")

    rec = new_record()
    rec.update({
        "pasture_id": pasture_id,
        "contract_id": contract_id,
        "asset_type": asset_type,
        "severity": severity,
        "description": description,
        "reported_at": reported_at,
        "cause": None,
        "repair_party": None,
        "repair_cost_cents": 0,
        "repair_completed_at": None,
        "responsible_party": None,
        "owner_share_cents": 0,
        "grazier_share_cents": 0,
        "status": "OPEN",
    })
    db.tickets[rec["id"]] = rec
    recompute_pasture(pasture)
    return created(public(rec))


@bp.get("/grazing/infrastructure-tickets/<ticket_id>")
def read_ticket(ticket_id):
    authenticate(ALL_ROLES)
    return ok(public(get_ticket(ticket_id)))


@bp.get("/grazing/infrastructure-tickets")
def list_tickets():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = sorted_records(db.tickets.values())
    for field in ("pasture_id", "contract_id", "status", "severity"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    return listing(public_list(rows), limit, offset)


@bp.post("/grazing/infrastructure-tickets/<ticket_id>/assign")
def assign_ticket(ticket_id):
    actor = authenticate(("Grazier",))
    ticket = get_ticket(ticket_id)
    body = body_of()
    repair_party = req_enum(body, "repair_party", REPAIR_PARTIES)

    pasture = db.pastures[ticket["pasture_id"]]
    if pasture["grazier_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Only the pasture's grazier may assign a repair.")

    if ticket["status"] != "OPEN":
        raise ApiError("ERR_TICKET_INVALID_STATE", "Assignment is only declared from OPEN.")

    ticket["repair_party"] = repair_party
    ticket["status"] = "ASSIGNED_GRAZIER" if repair_party == "GRAZIER" else "ASSIGNED_OWNER"
    touch(ticket)
    recompute_pasture(pasture)
    return ok(public(ticket))


@bp.post("/grazing/infrastructure-tickets/<ticket_id>/complete")
def complete_ticket(ticket_id):
    actor = authenticate(("Grazier", "CattleOwner"))
    ticket = get_ticket(ticket_id)
    body = body_of()
    repair_cost_cents = req_int(body, "repair_cost_cents", minv=0)
    cause = req_enum(body, "cause", CAUSES)
    completed_at = req_dt_str(body, "completed_at")

    pasture = db.pastures[ticket["pasture_id"]]
    contract = db.contracts[ticket["contract_id"]]
    if actor.is_grazier and pasture["grazier_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "The pasture belongs to another grazier.")
    if actor.is_owner and contract["cattle_owner_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "The contract belongs to another cattle owner.")

    branch = ticket["status"]
    if actor.is_grazier and branch != "ASSIGNED_GRAZIER":
        raise ApiError("ERR_TICKET_INVALID_STATE",
                       "A grazier completes only a ticket assigned to the grazier.")
    if actor.is_owner and branch != "ASSIGNED_OWNER":
        raise ApiError("ERR_TICKET_INVALID_STATE",
                       "A cattle owner completes only a ticket assigned to the owner.")

    ticket["repair_cost_cents"] = repair_cost_cents
    ticket["cause"] = cause
    ticket["repair_completed_at"] = completed_at
    infrastructure_allocation(ticket, contract, branch)
    ticket["status"] = "REPAIRED"
    touch(ticket)
    recompute_pasture(pasture)
    return ok(public(ticket))
