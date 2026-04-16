"""Boarding reservation routes."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request, g

from db import store, new_id, now_dt, lock, parse_dt
from middleware import auth_required
from response import success_object, success_array
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_ANIMAL_NOT_BOARDABLE,
    ERR_VACCINATION_NON_COMPLIANT,
    ERR_SHELTER_AT_CAPACITY,
    ERR_TOO_EARLY_FOR_CHECKIN,
    ERR_FEE_NOT_SETTLED,
    ERR_RESERVATION_NOT_FOUND,
    ERR_ANIMAL_NOT_FOUND,
)
from services.validation import (
    get_json_body, require_field, pagination,
    get_shelter_or_404, get_animal_or_404, get_reservation_or_404,
    parse_required_dt,
)
from services.serializers import serialize_reservation
from services.compliance import compute_compliance, write_incident
from services.pricing import (
    compute_boarding_quote, compute_final_total,
    PEAK_UTILIZATION,
)

bp = Blueprint("boarding", __name__)

EARLY_CHECKIN_GRACE_HOURS = 24


def _count_reserved(shelter_id):
    return sum(1 for r in store.reservations.values()
               if r["shelter_id"] == shelter_id and r["status"] in ("RESERVED", "ACTIVE"))


@bp.route("/shelters/<sid>/boarding-reservations", methods=["POST"])
@auth_required(allowed_roles={"BoardingCoordinator", "Adopter"})
def create_reservation(sid):
    shelter = get_shelter_or_404(sid)
    body = get_json_body(required=True)
    animal_id = require_field(body, "animal_id", types=str)
    owner_id = require_field(body, "owner_id", types=str)
    check_in = parse_required_dt(body, "check_in_date")
    check_out = parse_required_dt(body, "check_out_date")
    # nights
    delta = check_out - check_in
    # Whole days
    if delta.total_seconds() <= 0:
        raise_err(ERR_INVALID_REQUEST, "check_out_date must be after check_in_date")
    nights = int(delta.days) if delta == timedelta(days=delta.days) else None
    # Fallback: use total seconds / 86400 floor
    if nights is None:
        nights = int(delta.total_seconds() // 86400)
    if nights < 1:
        raise_err(ERR_INVALID_REQUEST, "nights must be >= 1")
    animal = get_animal_or_404(animal_id)
    if animal["shelter_id"] != sid:
        raise_err(ERR_ANIMAL_NOT_BOARDABLE, "Animal not in this shelter")
    # Shelter suspended
    if shelter["status"] == "SUSPENDED":
        raise_err(ERR_SHELTER_AT_CAPACITY, "Shelter suspended")
    # Boardability
    if animal["status"] in ("ADOPTED", "RETIRED"):
        raise_err(ERR_ANIMAL_NOT_BOARDABLE, f"Animal status {animal['status']}")
    # Vaccination compliance
    comp = compute_compliance(animal_id)
    if comp["status"] != "COMPLIANT":
        write_incident(animal_id, "BOARDING_BLOCKED",
                       "POST /shelters/{sid}/boarding-reservations",
                       f"missing={comp['missing']} expired={comp['expired']}")
        raise_err(ERR_VACCINATION_NON_COMPLIANT, "Vaccination non-compliant")
    # Capacity
    with lock:
        reserved = _count_reserved(sid)
        if reserved >= shelter["boarding_capacity"]:
            raise_err(ERR_SHELTER_AT_CAPACITY, "No available slots")
        reserved_after = reserved + 1
        quoted = compute_boarding_quote(shelter, animal, nights, reserved_after)
        # Determine if peak surcharge applied (store flag for final_total recompute)
        capacity = Decimal(str(shelter["boarding_capacity"]))
        util = Decimal(reserved_after) / capacity if capacity > 0 else Decimal("0")
        had_peak = util >= PEAK_UTILIZATION
        rid = new_id()
        now = now_dt()
        rec = {
            "id": rid,
            "shelter_id": sid,
            "animal_id": animal_id,
            "owner_id": owner_id,
            "check_in_date": check_in,
            "check_out_date": check_out,
            "nights": nights,
            "quoted_total": quoted,
            "final_total": None,
            "had_peak_surcharge": had_peak,
            "status": "RESERVED",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        store.reservations[rid] = rec
    return success_object(serialize_reservation(rec), status_code=201)


@bp.route("/shelters/<sid>/boarding-reservations", methods=["GET"])
@auth_required(allowed_roles={"Any"})
def list_reservations(sid):
    get_shelter_or_404(sid)
    limit, offset = pagination()
    status_f = request.args.get("status")
    animal_f = request.args.get("animal_id")
    recs = [r for r in store.reservations.values() if r["shelter_id"] == sid]
    if status_f:
        recs = [r for r in recs if r["status"] == status_f]
    if animal_f:
        recs = [r for r in recs if r["animal_id"] == animal_f]
    recs.sort(key=lambda r: r["created_at"])
    total = len(recs)
    page = recs[offset: offset + limit]
    return success_array([serialize_reservation(r) for r in page], limit, offset, total)


def _get_reservation_scoped(sid, rid):
    get_shelter_or_404(sid)
    r = get_reservation_or_404(rid)
    if r["shelter_id"] != sid:
        raise_err(ERR_RESERVATION_NOT_FOUND, "Reservation not in this shelter")
    return r


@bp.route("/shelters/<sid>/boarding-reservations/<rid>/check-in", methods=["POST"])
@auth_required(allowed_roles={"BoardingCoordinator"})
def check_in(sid, rid):
    r = _get_reservation_scoped(sid, rid)
    if r["status"] != "RESERVED":
        raise_err(ERR_INVALID_STATE, f"Cannot check-in from {r['status']}")
    # Time gate
    earliest = r["check_in_date"] - timedelta(hours=EARLY_CHECKIN_GRACE_HOURS)
    if now_dt() < earliest:
        raise_err(ERR_TOO_EARLY_FOR_CHECKIN, "Too early for check-in")
    comp = compute_compliance(r["animal_id"])
    if comp["status"] != "COMPLIANT":
        write_incident(r["animal_id"], "BOARDING_BLOCKED",
                       "POST /shelters/{sid}/boarding-reservations/{rid}/check-in",
                       f"missing={comp['missing']} expired={comp['expired']}")
        raise_err(ERR_VACCINATION_NON_COMPLIANT, "Vaccination non-compliant")
    with lock:
        now = now_dt()
        r["status"] = "ACTIVE"
        r["updated_at"] = now
        r["version"] += 1
        animal = store.animals.get(r["animal_id"])
        if animal and animal["status"] == "AVAILABLE":
            animal["status"] = "BOARDING_ONLY"
            animal["updated_at"] = now
            animal["version"] += 1
            animal["_boarded_by"] = r["id"]
    return success_object(serialize_reservation(r))


@bp.route("/shelters/<sid>/boarding-reservations/<rid>/check-out", methods=["POST"])
@auth_required(allowed_roles={"BoardingCoordinator"})
def check_out(sid, rid):
    r = _get_reservation_scoped(sid, rid)
    if r["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, f"Cannot check-out from {r['status']}")
    with lock:
        now = now_dt()
        # Recompute nights using now as actual check-out date
        check_in = r["check_in_date"]
        delta = now - check_in
        # Whole days via ceil of seconds/86400? PRD says whole-day difference. We'll use floor of days,
        # but clamp minimum to 1 so final_total is sensible.
        secs = delta.total_seconds()
        nights = max(1, int(secs // 86400)) if secs > 0 else 1
        animal = store.animals.get(r["animal_id"])
        shelter = store.shelters.get(r["shelter_id"])
        if animal and shelter:
            final_total = compute_final_total(shelter, animal, nights, r.get("had_peak_surcharge", False))
        else:
            final_total = r["quoted_total"]
        r["nights"] = nights
        r["final_total"] = final_total
        r["status"] = "COMPLETED"
        r["updated_at"] = now
        r["version"] += 1
        # Animal -> AVAILABLE if BOARDING_ONLY solely due to this reservation
        if animal and animal.get("status") == "BOARDING_ONLY" and animal.get("_boarded_by") == r["id"]:
            # Check there are no other active/reserved reservations for this animal
            other = [x for x in store.reservations.values()
                     if x["id"] != r["id"] and x["animal_id"] == animal["id"]
                     and x["status"] in ("RESERVED", "ACTIVE")]
            if not other:
                animal["status"] = "AVAILABLE"
                animal["updated_at"] = now
                animal["version"] += 1
                animal.pop("_boarded_by", None)
    return success_object(serialize_reservation(r))


@bp.route("/shelters/<sid>/boarding-reservations/<rid>/settle", methods=["POST"])
@auth_required(allowed_roles={"FinanceOfficer"})
def settle(sid, rid):
    r = _get_reservation_scoped(sid, rid)
    if r["status"] != "COMPLETED":
        raise_err(ERR_INVALID_STATE, f"Cannot settle from {r['status']}")
    # Completed settlement exists?
    ok = any(
        s["subject_type"] == "BOARDING" and s["subject_id"] == r["id"] and s["status"] == "COMPLETED"
        for s in store.settlements.values()
    )
    if not ok:
        raise_err(ERR_FEE_NOT_SETTLED, "Fee not settled")
    with lock:
        r["status"] = "SETTLED"
        r["updated_at"] = now_dt()
        r["version"] += 1
    return success_object(serialize_reservation(r))


@bp.route("/shelters/<sid>/boarding-reservations/<rid>/cancel", methods=["POST"])
@auth_required(allowed_roles={"BoardingCoordinator", "Adopter"})
def cancel(sid, rid):
    r = _get_reservation_scoped(sid, rid)
    if r["status"] not in ("RESERVED", "ACTIVE"):
        raise_err(ERR_INVALID_STATE, f"Cannot cancel from {r['status']}")
    with lock:
        now = now_dt()
        prev_status = r["status"]
        r["status"] = "CANCELLED"
        r["updated_at"] = now
        r["version"] += 1
        # Fail pending settlements
        for s in store.settlements.values():
            if (s["subject_type"] == "BOARDING" and s["subject_id"] == r["id"]
                    and s["status"] == "PENDING"):
                s["status"] = "FAILED"
                s["updated_at"] = now
                s["version"] += 1
        # Animal BOARDING_ONLY release
        animal = store.animals.get(r["animal_id"])
        if (animal and animal.get("status") == "BOARDING_ONLY"
                and animal.get("_boarded_by") == r["id"]):
            other = [x for x in store.reservations.values()
                     if x["id"] != r["id"] and x["animal_id"] == animal["id"]
                     and x["status"] in ("RESERVED", "ACTIVE")]
            if not other:
                animal["status"] = "AVAILABLE"
                animal["updated_at"] = now
                animal["version"] += 1
                animal.pop("_boarded_by", None)
    return success_object(serialize_reservation(r))
