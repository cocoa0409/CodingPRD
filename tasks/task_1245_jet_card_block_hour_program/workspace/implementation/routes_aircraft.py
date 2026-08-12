"""Aircraft endpoints."""

from flask import Blueprint, request

from httpkit import (
    authenticate, err_invalid_request, err_not_found, get_body, paginate,
    require_roles, respond_object, sorted_items,
)
from serializers import aircraft_json
from services import new_common
from store import db

bp = Blueprint("aircraft", __name__)

CATEGORIES = ["LIGHT", "MIDSIZE", "SUPER_MID", "HEAVY"]


def get_aircraft_or_404(aircraft_id):
    a = db.aircraft.get(aircraft_id)
    if a is None:
        raise err_not_found(f"Aircraft {aircraft_id} does not exist")
    return a


@bp.post("/aircraft")
def create_aircraft():
    data = get_body([
        {"name": "tail_number", "type": "string", "required": True},
        {"name": "category", "type": "enum", "values": CATEGORIES, "required": True},
        {"name": "home_base_icao", "type": "string", "required": True},
        {"name": "seats", "type": "integer", "required": True},
        {"name": "reposition_rate_cents_per_nm", "type": "integer", "required": True},
    ])
    authenticate()
    require_roles("Ops")
    for existing in db.aircraft.values():
        if existing["tail_number"] == data["tail_number"]:
            raise err_invalid_request("tail_number must be unique")
    a = new_common()
    a.update({
        "tail_number": data["tail_number"],
        "category": data["category"],
        "home_base_icao": data["home_base_icao"],
        "seats": data["seats"],
        "aircraft_status": "AVAILABLE",
        "reposition_rate_cents_per_nm": data["reposition_rate_cents_per_nm"],
    })
    db.aircraft[a["id"]] = a
    return respond_object(aircraft_json(a), 201)


@bp.get("/aircraft/<aircraftId>")
def get_aircraft(aircraftId):
    authenticate()
    require_roles("Ops", "Member")
    a = get_aircraft_or_404(aircraftId)
    return respond_object(aircraft_json(a))


@bp.get("/aircraft")
def list_aircraft():
    authenticate()
    require_roles("Ops")
    items = sorted_items(db.aircraft.values())
    flt_cat = request.args.get("category")
    if flt_cat is not None:
        items = [a for a in items if a["category"] == flt_cat]
    flt_status = request.args.get("aircraft_status")
    if flt_status is not None:
        items = [a for a in items if a["aircraft_status"] == flt_status]
    return paginate([aircraft_json(a) for a in items])


# --- FK reverse-reachability read -------------------------------------------

@bp.get("/aircraft/<id>/trip_requests")
def list_aircraft_trip_requests(id):
    from flask import g
    from serializers import trip_json
    authenticate()
    require_roles("Ops", "Member")
    get_aircraft_or_404(id)
    items = sorted_items(
        t for t in db.trips.values() if t["dispatched_aircraft_id"] == id)
    if g.role == "Member":
        items = [t for t in items
                 if db.cards.get(t["card_id"], {}).get("member_id") == g.user_id]
    return paginate([trip_json(t) for t in items])
