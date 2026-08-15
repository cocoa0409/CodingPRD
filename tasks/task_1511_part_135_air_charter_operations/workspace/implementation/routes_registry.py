"""Registry endpoints: AircraftOwner, Aircraft, CrewMember."""

from flask import Blueprint, g, request

from httpkit import (
    ALL_ROLES, authenticate, ensure_empty_body, err, err_forbidden,
    err_invalid_request, get_body, paginate, require_positive, require_roles,
    respond_object, sorted_items,
)
from serializers import aircraft_json, crew_member_json, owner_json, statement_json
from services import (
    CATEGORIES, get_aircraft_or_404, get_crew_member_or_404, get_owner_or_404,
    has_open_grounding_finding, new_common, touch,
)
from store import db

bp = Blueprint("registry", __name__)


# ---------------------------------------------------------------------------
# AircraftOwner
# ---------------------------------------------------------------------------

@bp.post("/charter/aircraft-owners")
def create_owner():
    authenticate()
    require_roles("OpsAdmin")
    data = get_body([
        {"name": "name", "type": "string", "required": True},
        {"name": "contact_email", "type": "string", "required": True},
        {"name": "revenue_share_pct", "type": "number", "required": True},
        {"name": "guarantee_cents_per_block_min", "type": "integer", "required": False},
    ])
    pct = data["revenue_share_pct"]
    if pct < 0 or pct > 100:
        raise err_invalid_request("revenue_share_pct must be between 0 and 100")
    guarantee = data["guarantee_cents_per_block_min"]
    if guarantee is None:
        guarantee = 0
    if guarantee < 0:
        raise err_invalid_request("guarantee_cents_per_block_min must be >= 0")
    o = new_common()
    o.update({
        "name": data["name"],
        "contact_email": data["contact_email"],
        "revenue_share_pct": pct,
        "guarantee_cents_per_block_min": guarantee,
    })
    db.owners[o["id"]] = o
    return respond_object(owner_json(o), 201)


@bp.get("/charter/aircraft-owners")
def list_owners():
    authenticate()
    require_roles(*ALL_ROLES)
    return paginate([owner_json(o) for o in sorted_items(db.owners.values())])


@bp.get("/charter/aircraft-owners/<owner_id>")
def get_owner(owner_id):
    authenticate()
    require_roles(*ALL_ROLES)
    return respond_object(owner_json(get_owner_or_404(owner_id)))


# ---------------------------------------------------------------------------
# Aircraft
# ---------------------------------------------------------------------------

@bp.post("/charter/aircraft")
def create_aircraft():
    authenticate()
    require_roles("OpsAdmin")
    data = get_body([
        {"name": "owner_id", "type": "string", "required": True},
        {"name": "tail_number", "type": "string", "required": True},
        {"name": "category", "type": "enum", "values": CATEGORIES, "required": True},
        {"name": "home_base_icao", "type": "string", "required": True},
        {"name": "seats", "type": "integer", "required": True},
        {"name": "hourly_rate_cents", "type": "integer", "required": True},
        {"name": "on_ops_spec", "type": "boolean", "required": True},
        {"name": "initial_airframe_minutes", "type": "integer", "required": True},
        {"name": "next_check_due_minutes", "type": "integer", "required": True},
    ])
    require_positive(data["seats"], "seats")
    if data["hourly_rate_cents"] < 0:
        raise err_invalid_request("hourly_rate_cents must be >= 0")
    if data["initial_airframe_minutes"] < 0:
        raise err_invalid_request("initial_airframe_minutes must be >= 0")
    if data["next_check_due_minutes"] < 0:
        raise err_invalid_request("next_check_due_minutes must be >= 0")
    get_owner_or_404(data["owner_id"])
    a = new_common()
    a.update({
        "owner_id": data["owner_id"],
        "tail_number": data["tail_number"],
        "category": data["category"],
        "home_base_icao": data["home_base_icao"],
        "seats": data["seats"],
        "hourly_rate_cents": data["hourly_rate_cents"],
        "on_ops_spec": data["on_ops_spec"],
        "initial_airframe_minutes": data["initial_airframe_minutes"],
        "total_airframe_minutes": data["initial_airframe_minutes"],
        "next_check_due_minutes": data["next_check_due_minutes"],
        "status": "AVAILABLE",
    })
    db.aircraft[a["id"]] = a
    return respond_object(aircraft_json(a), 201)


@bp.get("/charter/aircraft")
def list_aircraft():
    authenticate()
    require_roles(*ALL_ROLES)
    items = sorted_items(db.aircraft.values())
    flt_owner = request.args.get("owner_id")
    if flt_owner is not None:
        items = [a for a in items if a["owner_id"] == flt_owner]
    flt_cat = request.args.get("category")
    if flt_cat is not None:
        items = [a for a in items if a["category"] == flt_cat]
    flt_status = request.args.get("status")
    if flt_status is not None:
        items = [a for a in items if a["status"] == flt_status]
    return paginate([aircraft_json(a) for a in items])


@bp.get("/charter/aircraft/<aircraft_id>")
def get_aircraft(aircraft_id):
    authenticate()
    require_roles(*ALL_ROLES)
    return respond_object(aircraft_json(get_aircraft_or_404(aircraft_id)))


@bp.post("/charter/aircraft/<aircraft_id>/ground")
def ground_aircraft(aircraft_id):
    authenticate()
    require_roles("ComplianceOfficer")
    ensure_empty_body()
    a = get_aircraft_or_404(aircraft_id)
    if a["status"] not in ("AVAILABLE", "MAINTENANCE_HOLD"):
        raise err("ERR_INVALID_STATE", 409,
                  "Only an AVAILABLE or MAINTENANCE_HOLD aircraft can be grounded")
    a["status"] = "GROUNDED"
    touch(a)
    # Cascade link 2: release TENTATIVE and CONFIRMED assignments on this tail.
    affected_trips = []
    for asg in db.aircraft_assignments.values():
        if asg["aircraft_id"] == a["id"] and asg["status"] in ("TENTATIVE", "CONFIRMED"):
            was_confirmed = asg["status"] == "CONFIRMED"
            asg["status"] = "RELEASED"
            touch(asg)
            if was_confirmed:
                affected_trips.append(asg["trip_request_id"])
    # Cascade link 3: BOOKED trips that lost their confirmed aircraft fall
    # back to QUOTED (a new aircraft must be confirmed before dispatch).
    for trip_id in affected_trips:
        trip = db.trips.get(trip_id)
        if trip is not None and trip["status"] == "BOOKED":
            trip["status"] = "QUOTED"
            touch(trip)
    return respond_object(aircraft_json(a))


@bp.post("/charter/aircraft/<aircraft_id>/return-to-service")
def return_aircraft_to_service(aircraft_id):
    authenticate()
    require_roles("ComplianceOfficer")
    ensure_empty_body()
    a = get_aircraft_or_404(aircraft_id)
    if a["status"] != "GROUNDED":
        raise err("ERR_AIRCRAFT_NOT_GROUNDED", 409,
                  "Return-to-service requires the aircraft to be GROUNDED")
    if has_open_grounding_finding(a["id"]):
        raise err("ERR_GROUNDING_FINDING_OPEN", 422,
                  "An OPEN grounding compliance finding blocks return-to-service")
    a["status"] = "AVAILABLE"
    touch(a)
    return respond_object(aircraft_json(a))


# ---------------------------------------------------------------------------
# CrewMember
# ---------------------------------------------------------------------------

@bp.post("/charter/crew-members")
def create_crew_member():
    authenticate()
    require_roles("OpsAdmin")
    data = get_body([
        {"name": "name", "type": "string", "required": True},
        {"name": "base_icao", "type": "string", "required": True},
        {"name": "qualified_categories", "type": "enum_array",
         "values": CATEGORIES, "required": True},
    ])
    c = new_common()
    c.update({
        "name": data["name"],
        "base_icao": data["base_icao"],
        "qualified_categories": list(data["qualified_categories"]),
        "status": "ACTIVE",
    })
    db.crew_members[c["id"]] = c
    return respond_object(crew_member_json(c), 201)


@bp.get("/charter/crew-members")
def list_crew_members():
    authenticate()
    require_roles(*ALL_ROLES)
    items = sorted_items(db.crew_members.values())
    flt_status = request.args.get("status")
    if flt_status is not None:
        items = [c for c in items if c["status"] == flt_status]
    return paginate([crew_member_json(c) for c in items])


@bp.get("/charter/crew-members/<crew_member_id>")
def get_crew_member(crew_member_id):
    authenticate()
    require_roles(*ALL_ROLES)
    return respond_object(crew_member_json(get_crew_member_or_404(crew_member_id)))


@bp.patch("/charter/crew-members/<crew_member_id>")
def patch_crew_member(crew_member_id):
    authenticate()
    require_roles("OpsAdmin")
    data = get_body([
        {"name": "status", "type": "enum",
         "values": ["ACTIVE", "SUSPENDED"], "required": True},
    ])
    c = get_crew_member_or_404(crew_member_id)
    c["status"] = data["status"]
    touch(c)
    return respond_object(crew_member_json(c))


# ---------------------------------------------------------------------------
# OwnerStatement reads scoped to an owner (AircraftOwner may read own only)
# ---------------------------------------------------------------------------

@bp.get("/charter/aircraft-owners/<owner_id>/owner-statements")
def list_owner_statements(owner_id):
    authenticate()
    require_roles("OpsAdmin", "AircraftOwner")
    if g.role == "AircraftOwner" and g.user_id != owner_id:
        raise err_forbidden("An AircraftOwner may read only its own statements")
    get_owner_or_404(owner_id)
    items = sorted_items(s for s in db.statements.values()
                         if s["owner_id"] == owner_id)
    return paginate([statement_json(s) for s in items])
