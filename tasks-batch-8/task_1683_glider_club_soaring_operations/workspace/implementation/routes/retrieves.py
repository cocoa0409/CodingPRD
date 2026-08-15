"""RetrieveRequest endpoints."""

import uuid
from decimal import Decimal

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_MEMBER_NOT_ACTIVE,
    ERR_REFERENTIAL_INTEGRITY,
    ERR_RESOURCE_NOT_FOUND,
    ERR_RETRIEVE_FLIGHT_NOT_LANDED_OUT,
    ERR_RETRIEVE_NOT_ASSIGNED,
    ERR_RETRIEVE_NOT_REQUESTED,
)
from middleware import auth, forbid, require_role
from response import success
from services import retrieve_cost_split, ser_retrieve, touch
from util import get_body, need_number, need_str, paginate, sort_items, to_decimal

bp = Blueprint("retrieves", __name__)

NON_TERMINAL = ("REQUESTED", "CREW_ASSIGNED")


def _get_retrieve_or_404(rid):
    retrieve = db.STORE["retrieves"].get(rid)
    if retrieve is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "RetrieveRequest not found")
    return retrieve


@bp.post("/soaring/retrieves")
def create_retrieve():
    user_id, role = auth()
    require_role(role, ["Member", "DutyOfficer", "ClubAdmin"])
    body = get_body()
    flight_id = need_str(body, "flight_id")
    distance_km = need_number(body, "distance_km")
    flight = db.STORE["flights"].get(flight_id)
    if flight is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Flight not found")
    reservation = db.STORE["reservations"].get(flight["reservation_id"])
    if role == "Member" and (reservation is None or reservation["member_id"] != user_id):
        forbid("A Member may only file retrieves for their own flights")
    if to_decimal(distance_km) <= 0:
        raise ApiError(
            ERR_REFERENTIAL_INTEGRITY, 422, "distance_km must be greater than 0"
        )
    if flight["status"] not in ("LANDED", "RECONCILED"):
        raise ApiError(
            ERR_RETRIEVE_FLIGHT_NOT_LANDED_OUT, 409,
            "Retrieve requires the flight to be LANDED or RECONCILED",
        )
    for other in db.STORE["retrieves"].values():
        if other["flight_id"] == flight_id and other["status"] in NON_TERMINAL:
            raise ApiError(
                ERR_RETRIEVE_FLIGHT_NOT_LANDED_OUT, 409,
                "A non-terminal retrieve already exists for this flight",
            )
    pilot_share, club_share = retrieve_cost_split(distance_km)
    record = {
        "id": str(uuid.uuid4()),
        "flight_id": flight_id,
        "distance_km": distance_km,
        "status": "REQUESTED",
        "pilot_share_cents": pilot_share,
        "club_share_cents": club_share,
        "crew_member_id": None,
        "created_at": db.now(),
        "updated_at": db.now(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.STORE["retrieves"][record["id"]] = record
    flight["retrieve_id"] = record["id"]
    touch(flight)
    return success(ser_retrieve(record), "object", 201)


@bp.get("/soaring/retrieves")
def list_retrieves():
    auth()
    items = list(db.STORE["retrieves"].values())
    for param in ("flight_id", "crew_member_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [r for r in items if r.get(param) == value]
    page, meta = paginate(sort_items(items))
    return success([ser_retrieve(r) for r in page], "array", 200, meta)


@bp.get("/soaring/retrieves/<rid>")
def get_retrieve(rid):
    auth()
    return success(ser_retrieve(_get_retrieve_or_404(rid)), "object", 200)


@bp.post("/soaring/retrieves/<rid>/assign-crew")
def assign_crew(rid):
    _, role = auth()
    require_role(role, ["DutyOfficer", "ClubAdmin"])
    retrieve = _get_retrieve_or_404(rid)
    body = get_body()
    crew_member_id = need_str(body, "crew_member_id")
    crew = db.STORE["members"].get(crew_member_id)
    if crew is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Crew member not found")
    if retrieve["status"] != "REQUESTED":
        raise ApiError(
            ERR_RETRIEVE_NOT_REQUESTED, 409,
            "assign-crew requires retrieve status REQUESTED",
        )
    if crew["status"] != "ACTIVE":
        raise ApiError(
            ERR_MEMBER_NOT_ACTIVE, 409, "The crew member is not ACTIVE"
        )
    retrieve["crew_member_id"] = crew_member_id
    retrieve["status"] = "CREW_ASSIGNED"
    touch(retrieve)
    return success(ser_retrieve(retrieve), "object", 200)


@bp.post("/soaring/retrieves/<rid>/complete")
def complete_retrieve(rid):
    _, role = auth()
    require_role(role, ["DutyOfficer", "ClubAdmin"])
    retrieve = _get_retrieve_or_404(rid)
    if retrieve["status"] != "CREW_ASSIGNED":
        raise ApiError(
            ERR_RETRIEVE_NOT_ASSIGNED, 409,
            "complete requires retrieve status CREW_ASSIGNED",
        )
    retrieve["status"] = "COMPLETED"
    touch(retrieve)
    flight = db.STORE["flights"].get(retrieve["flight_id"])
    reservation = (
        db.STORE["reservations"].get(flight["reservation_id"]) if flight else None
    )
    pilot = (
        db.STORE["members"].get(reservation["member_id"]) if reservation else None
    )
    if pilot is not None:
        pilot["account_balance_cents"] += retrieve["pilot_share_cents"]
        touch(pilot)
    return success(ser_retrieve(retrieve), "object", 200)


@bp.post("/soaring/retrieves/<rid>/cancel")
def cancel_retrieve(rid):
    _, role = auth()
    require_role(role, ["DutyOfficer", "ClubAdmin"])
    retrieve = _get_retrieve_or_404(rid)
    if retrieve["status"] != "REQUESTED":
        raise ApiError(
            ERR_RETRIEVE_NOT_REQUESTED, 409,
            "cancel requires retrieve status REQUESTED",
        )
    retrieve["status"] = "CANCELLED"
    touch(retrieve)
    return success(ser_retrieve(retrieve), "object", 200)
