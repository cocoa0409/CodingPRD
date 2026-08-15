"""TripRequest endpoints: create, read, lifecycle actions, settle, preview."""

from flask import Blueprint, g, request

from httpkit import (
    authenticate, err, err_constraint, err_invalid_state, err_stale_version,
    err_unauthorized, get_body, ignore_body, paginate, require_roles,
    respond_object, sorted_items,
)
from serializers import trip_json
from services import (
    TRIP_KINDS, accrue_duty, cascade_trip_terminal, compute_allocation,
    compute_sifl, get_business_unit, get_passenger, get_trip, legs_of_trip,
    new_common, run_assignment, touch,
)
from store import db

bp = Blueprint("trips", __name__)

MGR = "FlightDeptManager"
DISP = "Dispatcher"
FIN = "FinanceAdmin"
EXEC = "ExecutiveRequester"

TRIP_READ_ROLES = (MGR, DISP, FIN, EXEC)


def _check_requester_ownership(trip):
    """ExecutiveRequester acts only on trips whose requester_id is the acting
    PassengerProfile (PRD 2.1 ownership rule)."""
    if g.role == EXEC and trip["requester_id"] != g.user_id:
        raise err_unauthorized(
            "An ExecutiveRequester may act only on their own trip requests")


# ---------------------------------------------------------------------------
# Create / read
# ---------------------------------------------------------------------------

@bp.post("/flight-ops/trip-requests")
def create_trip():
    authenticate()
    require_roles(EXEC)
    data = get_body([
        {"name": "requester_id", "type": "string", "required": True},
        {"name": "charge_bu_id", "type": "string", "required": True},
        {"name": "trip_kind", "type": "enum", "values": TRIP_KINDS, "required": True},
        {"name": "purpose", "type": "string", "required": True},
        {"name": "requested_departure_utc", "type": "datetime", "required": True},
        {"name": "requested_return_utc", "type": "datetime", "required": True},
        {"name": "passenger_ids", "type": "string_array", "required": True},
        {"name": "personal_use_flag", "type": "boolean", "required": False},
    ])
    # Body FK resolution (priority 4).
    get_passenger(data["requester_id"], fk=True)
    get_business_unit(data["charge_bu_id"], fk=True)
    for pid in data["passenger_ids"]:
        get_passenger(pid, fk=True)
    # Roster and timestamp constraints (priority 12).
    if len(data["passenger_ids"]) < 1:
        raise err_constraint("passenger_ids must contain at least one entry")
    if data["requester_id"] not in data["passenger_ids"]:
        raise err_constraint("passenger_ids must include requester_id")
    if not data["requested_return_utc"] > data["requested_departure_utc"]:
        raise err_constraint(
            "requested_return_utc must be strictly after requested_departure_utc")
    t = new_common()
    t.update({
        "requester_id": data["requester_id"],
        "charge_bu_id": data["charge_bu_id"],
        "trip_kind": data["trip_kind"],
        "purpose": data["purpose"],
        "requested_departure_utc": data["requested_departure_utc"],
        "requested_return_utc": data["requested_return_utc"],
        "passenger_ids": list(data["passenger_ids"]),
        "max_priority_tier": None,
        "approval_status": "DRAFT",
        "assignment_status": "UNASSIGNED",
        "personal_use_flag": bool(data["personal_use_flag"]),
        "personal_use_approved_by": None,
        "assigned_by_user_id": None,
        "dispatched_by_user_id": None,
        "sifl_imputed_income_cents": 0,
        "allocated_cost_cents": 0,
        "settlement_status": "UNSETTLED",
    })
    db.trips[t["id"]] = t
    return respond_object(trip_json(t), 201)


@bp.get("/flight-ops/trip-requests")
def list_trips():
    authenticate()
    require_roles(*TRIP_READ_ROLES)
    items = sorted_items(db.trips.values())
    for param in ("approval_status", "assignment_status", "requester_id",
                  "charge_bu_id"):
        val = request.args.get(param)
        if val is not None:
            items = [t for t in items if t[param] == val]
    return paginate([trip_json(t) for t in items])


@bp.get("/flight-ops/trip-requests/<trip_id>")
def read_trip(trip_id):
    authenticate()
    require_roles(*TRIP_READ_ROLES)
    return respond_object(trip_json(get_trip(trip_id)))


# ---------------------------------------------------------------------------
# Approval axis
# ---------------------------------------------------------------------------

@bp.post("/flight-ops/trip-requests/<trip_id>/submit")
def submit_trip(trip_id):
    authenticate()
    require_roles(EXEC)
    ignore_body()
    t = get_trip(trip_id)
    _check_requester_ownership(t)
    if t["approval_status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT trip can be submitted")
    if not any(lg["status"] == "PLANNED" for lg in legs_of_trip(t["id"])):
        raise err_invalid_state("A trip needs at least one PLANNED leg to submit")
    # Side effect: recompute max_priority_tier from the roster.
    best = None
    for pid in t["passenger_ids"]:
        pax = db.passengers.get(pid)
        if pax is None:
            continue
        if best is None or pax["priority_tier"] < best:
            best = pax["priority_tier"]
    t["max_priority_tier"] = best
    t["approval_status"] = "SUBMITTED"
    touch(t)
    return respond_object(trip_json(t))


@bp.post("/flight-ops/trip-requests/<trip_id>/approve")
def approve_trip(trip_id):
    authenticate()
    require_roles(MGR)
    ignore_body()
    t = get_trip(trip_id)
    if t["approval_status"] != "SUBMITTED":
        raise err_invalid_state("Only a SUBMITTED trip can be approved")
    now = db.now()
    for lg in legs_of_trip(t["id"]):
        if not lg["scheduled_departure_utc"] > now:
            raise err_invalid_state(
                "Every leg's scheduled_departure_utc must lie in the future")
    t["approval_status"] = "APPROVED"
    touch(t)
    # Side effect: the selector attempts an assignment pass over every PLANNED
    # leg. The attempt is advisory only -- assignments persist solely through
    # the dispatcher-run assign-aircraft action.
    return respond_object(trip_json(t))


@bp.post("/flight-ops/trip-requests/<trip_id>/reject")
def reject_trip(trip_id):
    authenticate()
    require_roles(MGR)
    ignore_body()
    t = get_trip(trip_id)
    if t["approval_status"] != "SUBMITTED":
        raise err_invalid_state("Only a SUBMITTED trip can be rejected")
    t["approval_status"] = "REJECTED"
    touch(t)
    # Cascade: every PLANNED leg drops to CANCELLED; services still
    # REQUESTED/CONFIRMED are cancelled with them.
    cascade_trip_terminal(t, only_planned_legs=True)
    return respond_object(trip_json(t))


# ---------------------------------------------------------------------------
# Assignment axis
# ---------------------------------------------------------------------------

def _read_occ_version():
    data = get_body([
        {"name": "expected_trip_request_version", "type": "integer", "required": True},
    ])
    return data["expected_trip_request_version"]


@bp.post("/flight-ops/trip-requests/<trip_id>/assign-aircraft")
def assign_aircraft(trip_id):
    authenticate()
    require_roles(DISP)
    t = get_trip(trip_id)
    expected = _read_occ_version()
    if not (t["approval_status"] == "APPROVED"
            and t["assignment_status"] == "UNASSIGNED"):
        raise err_invalid_state(
            "Aircraft assignment requires an APPROVED, UNASSIGNED trip")
    if not any(lg["status"] == "PLANNED" for lg in legs_of_trip(t["id"])):
        raise err_invalid_state("At least one PLANNED leg is required")
    if expected != t["version"]:
        raise err_stale_version()
    picks = run_assignment(t)
    for lg, aircraft in picks:
        lg["aircraft_id"] = aircraft["id"]
        lg["status"] = "AIRCRAFT_ASSIGNED"
        touch(lg)
    t["assigned_by_user_id"] = g.user_id
    t["assignment_status"] = "ASSIGNED"
    touch(t)
    return respond_object(trip_json(t))


@bp.post("/flight-ops/trip-requests/<trip_id>/dispatch")
def dispatch_trip(trip_id):
    authenticate()
    require_roles(DISP)
    ignore_body()
    t = get_trip(trip_id)
    if t["assignment_status"] != "ASSIGNED":
        raise err_invalid_state("Only an ASSIGNED trip can be dispatched")
    for lg in legs_of_trip(t["id"]):
        if lg["status"] not in ("CREWED", "RELEASED", "COMPLETED"):
            raise err_invalid_state(
                "Every leg must be CREWED or beyond before dispatch")
    if t["personal_use_flag"]:
        # Segregation of duties (priority 13) precedes personal-use approval
        # (priority 14) per PRD 2.6 business-tier ordering.
        if g.user_id == t["assigned_by_user_id"]:
            raise err("ERR_SEGREGATION_OF_DUTIES", 422,
                      "The dispatcher who assigned a personal-use trip cannot dispatch it")
        if not t["personal_use_approved_by"]:
            raise err("ERR_PERSONAL_USE_NOT_APPROVED", 422,
                      "Personal use requires FinanceAdmin approval before dispatch")
    t["dispatched_by_user_id"] = g.user_id
    t["assignment_status"] = "DISPATCHED"
    touch(t)
    accrue_duty(t)
    return respond_object(trip_json(t))


@bp.post("/flight-ops/trip-requests/<trip_id>/cancel")
def cancel_trip(trip_id):
    authenticate()
    require_roles(DISP, EXEC, MGR)
    ignore_body()
    t = get_trip(trip_id)
    _check_requester_ownership(t)
    if t["approval_status"] == "REJECTED":
        raise err_invalid_state("A REJECTED trip is terminal")
    if t["assignment_status"] not in ("UNASSIGNED", "ASSIGNED"):
        raise err_invalid_state(
            "Only an UNASSIGNED or ASSIGNED trip can be cancelled")
    t["assignment_status"] = "CANCELLED"
    touch(t)
    cascade_trip_terminal(t, only_planned_legs=False)
    return respond_object(trip_json(t))


@bp.post("/flight-ops/trip-requests/<trip_id>/approve-personal-use")
def approve_personal_use(trip_id):
    authenticate()
    require_roles(FIN)
    ignore_body()
    t = get_trip(trip_id)
    t["personal_use_approved_by"] = g.user_id
    touch(t)
    return respond_object(trip_json(t))


@bp.post("/flight-ops/trip-requests/<trip_id>/settle")
def settle_trip(trip_id):
    authenticate()
    require_roles(FIN)
    t = get_trip(trip_id)
    expected = _read_occ_version()
    if not (t["settlement_status"] == "UNSETTLED"
            and t["assignment_status"] == "COMPLETED"):
        raise err_invalid_state(
            "Settle requires a COMPLETED, not-yet-settled trip")
    if expected != t["version"]:
        raise err_stale_version()
    if t["personal_use_flag"] and g.user_id == t["personal_use_approved_by"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", 422,
                  "The FinanceAdmin who approved personal use cannot settle the trip")
    # Final SIFL variant: COMPLETED legs only, persisted.
    sifl_total, _ = compute_sifl(t, lambda lg: lg["status"] == "COMPLETED")
    allocated = compute_allocation(t)
    t["sifl_imputed_income_cents"] = sifl_total
    t["allocated_cost_cents"] = allocated
    t["settlement_status"] = "SETTLED"
    touch(t)
    bu = db.business_units.get(t["charge_bu_id"])
    over_budget = False
    if bu is not None:
        bu["allocated_cents"] += allocated
        touch(bu)
        over_budget = bu["allocated_cents"] > bu["annual_flight_budget_cents"]
    out = trip_json(t)
    out["over_budget"] = over_budget
    return respond_object(out)


@bp.get("/flight-ops/trip-requests/<trip_id>/sifl-preview")
def sifl_preview(trip_id):
    authenticate()
    require_roles(FIN, MGR)
    t = get_trip(trip_id)
    # Provisional variant: all legs regardless of status, nothing persisted.
    total, count = compute_sifl(t, lambda lg: True)
    return respond_object({
        "provisional_sifl_cents": total,
        "leg_count_included": count,
    })
