"""TripRequest endpoints: create, get, list, schedule, assign, cancel,
reconcile, override, and trip-scoped list endpoints (legs/assignments/claims/
encounters)."""
from flask import Blueprint, request

from clock import clock
from db import db, new_common, touch
from errors import err
from helpers import (get_json_body, modality_rank, paginate, parse_dt,
                     parse_pagination, require_enum, require_number)
from middleware import get_user_id, require_roles
from response import ok_list, ok_object
from serializers import serialize, serialize_list
from services.cascades import cancel_trip_cascade, release_active_assignment
from services.calculations import (VARIANCE_TOLERANCE_CENTS, deadhead,
                                    reconciliation_variance)
from services.eligibility import covering_span_for

bp = Blueprint("trips", __name__)

MODALITY = {"AMBULATORY", "WHEELCHAIR", "STRETCHER"}
LOS = {"ROUTINE", "URGENT", "BARIATRIC"}


def get_trip_or_404(trip_id):
    t = db.trips.get(trip_id)
    if t is None:
        raise err("ERR_NOT_FOUND", "TripRequest not found")
    return t


def _has_active_assignment(trip_id):
    for a in db.assignments.values():
        if a["trip_id"] == trip_id and a["status"] == "ACTIVE":
            return True
    return False


@bp.route("/trips", methods=["POST"])
def create_trip():
    require_roles("Coordinator")
    body = get_json_body()
    if "member_id" not in body or body["member_id"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: member_id")
    member_id = body["member_id"]
    if member_id not in db.members:
        raise err("ERR_FK_NOT_FOUND", "member_id does not reference an existing Member")

    standing_order_id = body.get("standing_order_id")
    if standing_order_id is not None and standing_order_id not in db.standing_orders:
        raise err("ERR_FK_NOT_FOUND", "standing_order_id does not reference an existing StandingOrder")

    modality = require_enum(body, "modality", MODALITY)
    requested_los = require_enum(body, "requested_level_of_service", LOS)
    if "appointment_at" not in body or body["appointment_at"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: appointment_at")
    parse_dt(body["appointment_at"])
    scheduled_loaded_miles = require_number(body, "scheduled_loaded_miles")
    is_round_trip = body.get("is_round_trip", True)
    if not isinstance(is_round_trip, bool):
        raise err("ERR_INVALID_REQUEST", "is_round_trip must be a boolean")
    return_is_will_call = body.get("return_is_will_call", False)
    if not isinstance(return_is_will_call, bool):
        raise err("ERR_INVALID_REQUEST", "return_is_will_call must be a boolean")

    trip = new_common()
    trip.update({
        "member_id": member_id,
        "standing_order_id": standing_order_id,
        "modality": modality,
        "requested_level_of_service": requested_los,
        "appointment_at": body["appointment_at"],
        "is_round_trip": is_round_trip,
        "return_is_will_call": return_is_will_call,
        "trip_status": "DRAFT",
        "billing_status": "UNBILLED",
        "assigned_broker_id": None,
        "assigned_driver_id": None,
        "scheduled_loaded_miles": scheduled_loaded_miles,
        "claimed_cost_cents": 0,
        "encounter_cost_cents": 0,
        "reconciliation_variance_cents": 0,
    })
    db.trips[trip["id"]] = trip
    return ok_object(serialize(trip), status=201)


@bp.route("/trips/<trip_id>", methods=["GET"])
def get_trip(trip_id):
    require_roles("Coordinator", "Broker", "Auditor", "Driver")
    return ok_object(serialize(get_trip_or_404(trip_id)))


@bp.route("/trips", methods=["GET"])
def list_trips():
    require_roles("Coordinator", "Broker", "Auditor")
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    standing_order_id = request.args.get("standing_order_id")
    assigned_broker_id = request.args.get("assigned_broker_id")
    assigned_driver_id = request.args.get("assigned_driver_id")

    items = list(db.trips.values())
    if member_id is not None:
        items = [t for t in items if t["member_id"] == member_id]
    if standing_order_id is not None:
        items = [t for t in items if t.get("standing_order_id") == standing_order_id]
    if assigned_broker_id is not None:
        items = [t for t in items if t.get("assigned_broker_id") == assigned_broker_id]
    if assigned_driver_id is not None:
        items = [t for t in items if t.get("assigned_driver_id") == assigned_driver_id]
    items.sort(key=lambda t: (t["created_at"], t["_seq"]))
    page, total = paginate(items, limit, offset)
    return ok_list(serialize_list(page), limit, offset, total)


@bp.route("/trips/<trip_id>/schedule", methods=["POST"])
def schedule_trip(trip_id):
    require_roles("Coordinator")
    trip = get_trip_or_404(trip_id)
    # State: only DRAFT -> SCHEDULED is defined.
    if trip["trip_status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Trip is not DRAFT")
    member = db.members[trip["member_id"]]
    # Priority 7: eligibility gate precedes everything fiscal.
    if member["eligibility_status"] != "ELIGIBLE":
        raise err("ERR_MEMBER_INELIGIBLE", "Member is not ELIGIBLE")
    # Priority 8: modality within member mobility, and covering span LOS >= requested.
    if modality_rank(member["mobility_level"]) < modality_rank(trip["modality"]):
        raise err("ERR_LOS_NOT_AUTHORIZED", "Trip modality exceeds member mobility level")
    appt = parse_dt(trip["appointment_at"])
    span = covering_span_for(trip["member_id"], appt)
    if span is None:
        raise err("ERR_LOS_NOT_AUTHORIZED", "No covering eligibility span at appointment_at")
    from helpers import los_rank
    if los_rank(span["level_of_service"]) < los_rank(trip["requested_level_of_service"]):
        raise err("ERR_LOS_NOT_AUTHORIZED", "Covering span level_of_service below requested")

    trip["trip_status"] = "SCHEDULED"
    # Create legs (PRD 3.3).
    _create_leg(trip, "OUTBOUND", is_will_call=False)
    if trip["is_round_trip"]:
        _create_leg(trip, "RETURN", is_will_call=trip["return_is_will_call"])
    touch(trip)
    return ok_object(serialize(trip))


def _create_leg(trip, direction, is_will_call):
    leg = new_common()
    leg.update({
        "trip_id": trip["id"],
        "direction": direction,
        "is_will_call": is_will_call,
        "leg_status": "PENDING",
        "ready_called_at": None,
        "arrived_at": None,
        "picked_up_at": None,
        "dropped_off_at": None,
        "odometer_loaded_miles": 0,
        "dwell_minutes": 0,
    })
    db.legs[leg["id"]] = leg
    return leg


@bp.route("/trips/<trip_id>/assign", methods=["POST"])
def assign_trip(trip_id):
    require_roles("Broker")
    trip = get_trip_or_404(trip_id)
    body = get_json_body()

    # Single-active-assignment (PRD 3.4): a trip that already holds an ACTIVE
    # assignment rejects a second assign with ERR_ASSIGNMENT_EXISTS. This takes
    # precedence over the generic "not SCHEDULED" state check: an ASSIGNED trip
    # (which definitionally has an ACTIVE assignment) must surface
    # ERR_ASSIGNMENT_EXISTS, whereas a DRAFT trip (no active assignment) falls
    # through to ERR_INVALID_STATE.
    if _has_active_assignment(trip_id):
        raise err("ERR_ASSIGNMENT_EXISTS", "Trip already has an ACTIVE Assignment")

    # State (priority 5): only SCHEDULED -> ASSIGNED is defined.
    if trip["trip_status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Trip is not SCHEDULED")

    member = db.members[trip["member_id"]]
    # Priority 7: eligibility gate.
    if member["eligibility_status"] != "ELIGIBLE":
        raise err("ERR_MEMBER_INELIGIBLE", "Member is not ELIGIBLE")

    preferred_broker_id = body.get("preferred_broker_id")
    if preferred_broker_id is not None and preferred_broker_id not in db.brokers:
        raise err("ERR_FK_NOT_FOUND", "preferred_broker_id does not reference an existing Broker")

    # Priority 9: modality / county matching, reported as ERR_MODALITY_MISMATCH
    # when a specific preferred broker is examined and fails.
    # Priority 13: no candidate pair at all -> ERR_NO_BROKER_AVAILABLE.
    # Priority 14: OCC version check.

    selected = _select_broker_driver(trip, member, preferred_broker_id)
    # selected is (broker, driver). Selection raises the appropriate error.

    # OCC (priority 14): expected_trip_version is required and must match.
    if "expected_trip_version" not in body or body["expected_trip_version"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: expected_trip_version")
    expected = body["expected_trip_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "expected_trip_version must be an integer")
    if expected != trip["version"]:
        raise err("ERR_STALE_VERSION", "expected_trip_version does not match the trip's current version")

    broker, driver = selected
    raw_deadhead, _charge = deadhead(driver, member, broker)

    assignment = new_common()
    assignment.update({
        "trip_id": trip_id,
        "broker_id": broker["id"],
        "driver_id": driver["id"],
        "status": "ACTIVE",
        "deadhead_miles": raw_deadhead,
    })
    db.assignments[assignment["id"]] = assignment

    trip["trip_status"] = "ASSIGNED"
    trip["assigned_broker_id"] = broker["id"]
    trip["assigned_driver_id"] = driver["id"]
    driver["status"] = "ON_TRIP"
    touch(driver)
    touch(trip)  # increments version by 1
    return ok_object(serialize(trip))


def _broker_serves(broker, trip, member):
    """True if broker is ACTIVE, covers home_county, and max_modality suffices."""
    if broker["status"] != "ACTIVE":
        return False
    if member["home_county"] not in broker["covered_counties"]:
        return False
    if modality_rank(broker["max_modality"]) < modality_rank(trip["modality"]):
        return False
    return True


def _driver_serves(driver, broker, trip):
    if driver["broker_id"] != broker["id"]:
        return False
    if driver["status"] != "AVAILABLE":
        return False
    if modality_rank(driver["vehicle_modality"]) < modality_rank(trip["modality"]):
        return False
    return True


def _select_broker_driver(trip, member, preferred_broker_id):
    """Selection policy (PRD 3.4).

    If a preferred broker is supplied and explicitly fails the modality/county
    test, report ERR_MODALITY_MISMATCH. Otherwise fall back across eligible
    brokers; if no candidate pair exists, ERR_NO_BROKER_AVAILABLE.
    """
    if preferred_broker_id is not None:
        broker = db.brokers[preferred_broker_id]
        # Explicit preferred broker examined: a modality/county failure is a
        # specific mismatch (priority 9) rather than generic unavailability.
        if member["home_county"] not in broker["covered_counties"] or \
           modality_rank(broker["max_modality"]) < modality_rank(trip["modality"]):
            raise err("ERR_MODALITY_MISMATCH",
                      "Preferred broker modality below trip or does not cover home_county")
        if broker["status"] == "ACTIVE":
            driver = _pick_driver(broker, trip)
            if driver is not None:
                return broker, driver
            # Preferred broker valid on modality/county but no available driver of
            # sufficient modality: a specific driver-modality mismatch.
            # Distinguish: if the broker has any AVAILABLE driver at all but none of
            # sufficient modality -> ERR_MODALITY_MISMATCH; else fall through.
            if _has_available_driver_below_modality(broker, trip):
                raise err("ERR_MODALITY_MISMATCH",
                          "Preferred broker driver vehicle_modality below trip modality")
        # Preferred broker yielded no candidate; fall back across other brokers.

    # Fallback across all eligible brokers, by insertion order for determinism.
    brokers = sorted(db.brokers.values(), key=lambda b: (b["created_at"], b["_seq"]))
    for broker in brokers:
        if not _broker_serves(broker, trip, member):
            continue
        driver = _pick_driver(broker, trip)
        if driver is not None:
            return broker, driver
    raise err("ERR_NO_BROKER_AVAILABLE", "No candidate (Broker, Driver) pair satisfies the policy")


def _pick_driver(broker, trip):
    drivers = sorted(
        [d for d in db.drivers.values() if _driver_serves(d, broker, trip)],
        key=lambda d: (d["created_at"], d["_seq"]),
    )
    return drivers[0] if drivers else None


def _has_available_driver_below_modality(broker, trip):
    for d in db.drivers.values():
        if d["broker_id"] == broker["id"] and d["status"] == "AVAILABLE" and \
           modality_rank(d["vehicle_modality"]) < modality_rank(trip["modality"]):
            return True
    return False


@bp.route("/trips/<trip_id>/cancel", methods=["POST"])
def cancel_trip(trip_id):
    require_roles("Coordinator")
    trip = get_trip_or_404(trip_id)
    if trip["trip_status"] not in ("DRAFT", "SCHEDULED", "ASSIGNED"):
        raise err("ERR_INVALID_STATE", "Trip cannot be cancelled from its current state")
    cancel_trip_cascade(trip)
    return ok_object(serialize(trip))


@bp.route("/trips/<trip_id>/reconcile", methods=["POST"])
def reconcile_trip(trip_id):
    require_roles("Auditor")
    trip = get_trip_or_404(trip_id)
    # State (priority 5): reconcile is defined only from ENCOUNTERED.
    if trip["billing_status"] != "ENCOUNTERED":
        raise err("ERR_INVALID_STATE", "Trip billing_status is not ENCOUNTERED")
    # Priority 12: both a SUBMITTED Claim and an OPEN Encounter must exist.
    claim = _find_claim(trip_id, "SUBMITTED")
    encounter = _find_encounter(trip_id, "OPEN")
    if claim is None or encounter is None:
        raise err("ERR_RECON_INCOMPLETE", "Reconcile requires a SUBMITTED Claim and an OPEN Encounter")

    variance = reconciliation_variance(trip)
    trip["reconciliation_variance_cents"] = variance
    if abs(variance) > VARIANCE_TOLERANCE_CENTS:
        trip["billing_status"] = "DISPUTED"
        # Claim stays SUBMITTED, Encounter stays OPEN (manual review).
    else:
        trip["billing_status"] = "RECONCILED"
        claim["status"] = "RECONCILED"
        touch(claim)
        encounter["status"] = "RECONCILED"
        touch(encounter)
    touch(trip)
    return ok_object(serialize(trip))


@bp.route("/trips/<trip_id>/reconcile/override", methods=["POST"])
def reconcile_override(trip_id):
    require_roles("Auditor")
    trip = get_trip_or_404(trip_id)
    # State: override is defined only from DISPUTED.
    if trip["billing_status"] != "DISPUTED":
        raise err("ERR_INVALID_STATE", "Trip billing_status is not DISPUTED")
    trip["billing_status"] = "RECONCILED"
    claim = _find_claim(trip_id, "SUBMITTED")
    encounter = _find_encounter(trip_id, "OPEN")
    if claim is not None:
        claim["status"] = "RECONCILED"
        touch(claim)
    if encounter is not None:
        encounter["status"] = "RECONCILED"
        touch(encounter)
    touch(trip)
    return ok_object(serialize(trip))


def _find_claim(trip_id, status=None):
    for c in db.claims.values():
        if c["trip_id"] == trip_id and (status is None or c["status"] == status):
            return c
    return None


def _find_encounter(trip_id, status=None):
    for e in db.encounters.values():
        if e["trip_id"] == trip_id and (status is None or e["status"] == status):
            return e
    return None


# ---- trip-scoped lists ----

@bp.route("/trips/<trip_id>/legs", methods=["GET"])
def list_trip_legs(trip_id):
    require_roles("Coordinator", "Broker", "Auditor", "Driver")
    get_trip_or_404(trip_id)
    limit, offset = parse_pagination()
    items = [l for l in db.legs.values() if l["trip_id"] == trip_id]
    # OUTBOUND first then RETURN, then created_at ASC (PRD 4 endpoint note).
    dir_rank = {"OUTBOUND": 0, "RETURN": 1}
    items.sort(key=lambda l: (dir_rank.get(l["direction"], 2), l["created_at"], l["_seq"]))
    page, total = paginate(items, limit, offset)
    return ok_list(serialize_list(page), limit, offset, total)


@bp.route("/trips/<trip_id>/assignments", methods=["GET"])
def list_trip_assignments(trip_id):
    require_roles("Coordinator", "Broker", "Auditor")
    get_trip_or_404(trip_id)
    limit, offset = parse_pagination()
    items = [a for a in db.assignments.values() if a["trip_id"] == trip_id]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    page, total = paginate(items, limit, offset)
    return ok_list(serialize_list(page), limit, offset, total)


@bp.route("/trips/<trip_id>/claims", methods=["GET"])
def list_trip_claims(trip_id):
    require_roles("Coordinator", "Broker", "Auditor")
    get_trip_or_404(trip_id)
    limit, offset = parse_pagination()
    items = [c for c in db.claims.values() if c["trip_id"] == trip_id]
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    page, total = paginate(items, limit, offset)
    return ok_list(serialize_list(page), limit, offset, total)


@bp.route("/trips/<trip_id>/encounters", methods=["GET"])
def list_trip_encounters(trip_id):
    require_roles("Coordinator", "Auditor")
    get_trip_or_404(trip_id)
    limit, offset = parse_pagination()
    items = [e for e in db.encounters.values() if e["trip_id"] == trip_id]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    page, total = paginate(items, limit, offset)
    return ok_list(serialize_list(page), limit, offset, total)
