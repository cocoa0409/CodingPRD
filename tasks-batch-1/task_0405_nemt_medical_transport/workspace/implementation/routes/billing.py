"""Claim and Encounter endpoints, plus standalone Assignment reads (PRD 3.7-3.9)."""
from flask import Blueprint, request

from db import db, new_common, touch
from errors import err
from helpers import (get_json_body, paginate, parse_pagination)
from middleware import get_user_id, require_roles
from response import ok_list, ok_object
from serializers import serialize, serialize_list
from services.calculations import (claimed_cost_forward,
                                    encounter_cost_chronological)

bp = Blueprint("billing", __name__)


# ---- Assignment reads ----

@bp.route("/assignments/<assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    require_roles("Coordinator", "Broker", "Auditor")
    a = db.assignments.get(assignment_id)
    if a is None:
        raise err("ERR_NOT_FOUND", "Assignment not found")
    return ok_object(serialize(a))


@bp.route("/assignments", methods=["GET"])
def list_assignments():
    require_roles("Coordinator", "Broker", "Auditor")
    limit, offset = parse_pagination()
    trip_id = request.args.get("trip_id")
    broker_id = request.args.get("broker_id")
    driver_id = request.args.get("driver_id")
    items = list(db.assignments.values())
    if trip_id is not None:
        items = [a for a in items if a["trip_id"] == trip_id]
    if broker_id is not None:
        items = [a for a in items if a["broker_id"] == broker_id]
    if driver_id is not None:
        items = [a for a in items if a["driver_id"] == driver_id]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    page, total = paginate(items, limit, offset)
    return ok_list(serialize_list(page), limit, offset, total)


# ---- Claim ----

@bp.route("/claims", methods=["POST"])
def create_claim():
    require_roles("Broker")
    body = get_json_body()
    if "trip_id" not in body or body["trip_id"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: trip_id")
    trip_id = body["trip_id"]
    trip = db.trips.get(trip_id)
    if trip is None:
        raise err("ERR_FK_NOT_FOUND", "trip_id does not reference an existing TripRequest")

    # State (priority 5): billing axis must be UNBILLED, and lifecycle COMPLETED.
    if trip["billing_status"] != "UNBILLED":
        raise err("ERR_INVALID_STATE", "Trip billing_status is not UNBILLED")
    if trip["trip_status"] != "COMPLETED":
        raise err("ERR_INVALID_STATE", "Trip lifecycle is not COMPLETED")

    # Ownership (priority 6): the broker submitting a claim must be the trip's
    # assigned broker. Per PRD 2.1 the Broker's X-User-ID is an opaque operator
    # identifier the server does NOT match against any stored record, so this
    # check is only enforceable when the caller supplies a broker id that maps to
    # a real Broker row; an opaque id is accepted (the entity-backed ownership
    # comparison applies to Drivers only).
    uid = get_user_id()
    if uid in db.brokers and trip.get("assigned_broker_id") != uid:
        raise err("ERR_NOT_OWNER", "Acting broker is not the trip's assigned broker")

    # Priority 12: no existing claim for this trip.
    for c in db.claims.values():
        if c["trip_id"] == trip_id:
            raise err("ERR_RECON_INCOMPLETE", "A Claim already exists for this trip")

    cost = claimed_cost_forward(trip)
    trip["claimed_cost_cents"] = cost
    trip["billing_status"] = "CLAIMED"
    touch(trip)

    claim = new_common()
    claim.update({
        "trip_id": trip_id,
        "broker_id": trip["assigned_broker_id"],
        "billed_cents": cost,
        "status": "SUBMITTED",
    })
    db.claims[claim["id"]] = claim
    return ok_object(serialize(claim), status=201)


@bp.route("/claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    require_roles("Coordinator", "Broker", "Auditor")
    c = db.claims.get(claim_id)
    if c is None:
        raise err("ERR_NOT_FOUND", "Claim not found")
    return ok_object(serialize(c))


@bp.route("/claims", methods=["GET"])
def list_claims():
    require_roles("Coordinator", "Broker", "Auditor")
    limit, offset = parse_pagination()
    trip_id = request.args.get("trip_id")
    broker_id = request.args.get("broker_id")
    items = list(db.claims.values())
    if trip_id is not None:
        items = [c for c in items if c["trip_id"] == trip_id]
    if broker_id is not None:
        items = [c for c in items if c["broker_id"] == broker_id]
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    page, total = paginate(items, limit, offset)
    return ok_list(serialize_list(page), limit, offset, total)


# ---- Encounter ----

@bp.route("/encounters", methods=["POST"])
def create_encounter():
    require_roles("Auditor")
    body = get_json_body()
    if "trip_id" not in body or body["trip_id"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: trip_id")
    trip_id = body["trip_id"]
    trip = db.trips.get(trip_id)
    if trip is None:
        raise err("ERR_FK_NOT_FOUND", "trip_id does not reference an existing TripRequest")

    # State (priority 5): billing axis must be CLAIMED, lifecycle COMPLETED.
    if trip["billing_status"] != "CLAIMED":
        raise err("ERR_INVALID_STATE", "Trip billing_status is not CLAIMED")
    if trip["trip_status"] != "COMPLETED":
        raise err("ERR_INVALID_STATE", "Trip lifecycle is not COMPLETED")

    # Priority 12: no existing encounter for this trip.
    for e in db.encounters.values():
        if e["trip_id"] == trip_id:
            raise err("ERR_RECON_INCOMPLETE", "An Encounter already exists for this trip")

    cost = encounter_cost_chronological(trip)
    trip["encounter_cost_cents"] = cost
    trip["billing_status"] = "ENCOUNTERED"
    touch(trip)

    encounter = new_common()
    encounter.update({
        "trip_id": trip_id,
        "captured_cents": cost,
        "status": "OPEN",
    })
    db.encounters[encounter["id"]] = encounter
    return ok_object(serialize(encounter), status=201)


@bp.route("/encounters/<encounter_id>", methods=["GET"])
def get_encounter(encounter_id):
    require_roles("Coordinator", "Auditor")
    e = db.encounters.get(encounter_id)
    if e is None:
        raise err("ERR_NOT_FOUND", "Encounter not found")
    return ok_object(serialize(e))
