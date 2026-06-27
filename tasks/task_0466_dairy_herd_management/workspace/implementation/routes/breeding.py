"""BreedingEvent and CalvingEvent routes (PRD §3.5, §3.6)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import serializers
import domain
from errors import err
from middleware import require_roles
from records import make_record, touch
from response import object_response, array_response
from domain import paginate, sorted_by_creation
from util import parse_datetime, iso_format
from calculations import PREG_CHECK_WINDOW_DAYS, VWP_DAYS
import clock
import validators as V

bp = Blueprint("breeding", __name__)

ALL_ROLES = ("HerdManager", "ParlorTech", "Veterinarian", "CoopSettlementAgent", "Auditor")


# ---------------------------------------------------------------------------
# BreedingEvent (PRD §3.5)
# ---------------------------------------------------------------------------
@bp.route("/herds/breeding-events", methods=["POST"])
@require_roles("Veterinarian", "HerdManager")
def create_breeding_event():
    body = V.require_json_object()
    animal_id = V.require_fk(body, "animal_id")
    service_date = V.require_datetime(body, "service_date")
    sire_code = V.require_str(body, "sire_code")
    animal = V.get_or_404("animal", animal_id)
    with db.lock:
        # priority 11: no existing BRED/CONFIRMED_PREGNANT service
        for ev in db.breeding_events.values():
            if ev["animal_id"] == animal_id and ev["status"] in ("BRED", "CONFIRMED_PREGNANT"):
                raise err(errors.ERR_OPEN_SERVICE_EXISTS,
                          "Animal already has an open or confirmed service")
        # priority 11.5: VWP — service_date must be >= prior.service_date + 30d
        # for every prior non-voided service (status OPEN or SERVED_OUT).
        for ev in db.breeding_events.values():
            if ev["animal_id"] != animal_id:
                continue
            if ev["status"] not in ("OPEN", "SERVED_OUT"):
                continue
            prior_date = parse_datetime(ev["service_date"])
            if service_date < prior_date + timedelta(days=VWP_DAYS):
                raise err(errors.ERR_SERVICE_WITHIN_VWP,
                          "service_date falls within VWP of a prior service")
        confirm_due_at = service_date + timedelta(days=PREG_CHECK_WINDOW_DAYS)
        rec = make_record({
            "animal_id": animal_id,
            "herd_id": animal["herd_id"],
            "service_date": body["service_date"],
            "sire_code": sire_code,
            "confirm_due_at": iso_format(confirm_due_at),
            "status": "BRED",
        })
        rec["_confirm_due_at_dt"] = confirm_due_at
        db.breeding_events[rec["id"]] = rec
        return object_response(serializers.breeding_event_out(rec), 201)


@bp.route("/herds/breeding-events", methods=["GET"])
@require_roles("HerdManager", "Veterinarian", "CoopSettlementAgent", "Auditor")
def list_breeding_events():
    items = list(db.breeding_events.values())
    animal_id = request.args.get("animal_id")
    herd_id = request.args.get("herd_id")
    if animal_id is not None:
        items = [r for r in items if r["animal_id"] == animal_id]
    if herd_id is not None:
        items = [r for r in items if r["herd_id"] == herd_id]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items, request.args)
    return array_response([serializers.breeding_event_out(r) for r in page], limit, offset, total)


@bp.route("/herds/breeding-events/<breeding_id>", methods=["GET"])
@require_roles("HerdManager", "Veterinarian", "CoopSettlementAgent", "Auditor")
def get_breeding_event(breeding_id):
    rec = V.get_or_404("breeding", breeding_id)
    return object_response(serializers.breeding_event_out(rec), 200)


@bp.route("/herds/breeding-events/<breeding_id>/confirm", methods=["POST"])
@require_roles("Veterinarian")
def confirm_breeding(breeding_id):
    rec = V.get_or_404("breeding", breeding_id)
    with db.lock:
        if rec["status"] != "BRED":
            raise err(errors.ERR_BREEDING_NOT_PENDING, "Breeding event is not BRED")
        if clock.now() > rec["_confirm_due_at_dt"]:
            raise err(errors.ERR_PREG_CHECK_WINDOW_ELAPSED,
                      "Pregnancy-check window has elapsed")
        rec["status"] = "CONFIRMED_PREGNANT"
        touch(rec)
        return object_response(serializers.breeding_event_out(rec), 200)


@bp.route("/herds/breeding-events/<breeding_id>/mark-open", methods=["POST"])
@require_roles("Veterinarian")
def mark_open_breeding(breeding_id):
    rec = V.get_or_404("breeding", breeding_id)
    with db.lock:
        if rec["status"] != "BRED":
            raise err(errors.ERR_BREEDING_NOT_PENDING, "Breeding event is not BRED")
        rec["status"] = "OPEN"
        touch(rec)
        return object_response(serializers.breeding_event_out(rec), 200)


# ---------------------------------------------------------------------------
# CalvingEvent — the central cascade (PRD §3.6)
# ---------------------------------------------------------------------------
@bp.route("/herds/calving-events", methods=["POST"])
@require_roles("HerdManager")
def create_calving_event():
    body = V.require_json_object()
    animal_id = V.require_fk(body, "animal_id")
    breeding_event_id = V.require_fk(body, "breeding_event_id")
    calving_date = V.require_datetime(body, "calving_date")
    # existence: animal (path-equivalent body FK) then breeding event
    animal = V.get_or_404("animal", animal_id)
    breeding = V.get_or_404("breeding", breeding_event_id)
    with db.lock:
        # state (priority 5): animal must be breedable for calving (HEIFER/DRY)
        if animal["status"] not in ("HEIFER", "DRY"):
            raise err(errors.ERR_ANIMAL_NOT_BREEDABLE_STATE,
                      "Animal is not in HEIFER or DRY state")
        # state: breeding event must be CONFIRMED_PREGNANT
        if breeding["status"] != "CONFIRMED_PREGNANT":
            raise err(errors.ERR_BREEDING_NOT_CONFIRMED,
                      "Breeding event is not CONFIRMED_PREGNANT")
        # cross-herd referential (priority 8): breeding event must belong to
        # the same animal.
        if breeding["animal_id"] != animal_id:
            raise err(errors.ERR_CROSS_HERD_REFERENCE,
                      "Breeding event belongs to a different animal")

        # Cascade (in order):
        # step 0: breeding event CONFIRMED_PREGNANT -> SERVED_OUT
        breeding["status"] = "SERVED_OUT"
        touch(breeding)
        # step 1: animal parity += 1, status -> ACTIVE
        animal["parity"] = animal["parity"] + 1
        animal["status"] = "ACTIVE"
        # step 2: prior OPEN/DRY lactation -> CLOSED, record closed_lactation_id
        closed_lactation_id = None
        prior = domain.open_or_dry_lactation(animal_id)
        if prior is not None:
            prior["status"] = "CLOSED"
            touch(prior)
            closed_lactation_id = prior["id"]
        # step 3: open new lactation at calving_date
        new_calving_id = None  # placeholder; calving id assigned below
        # Build calving record first so we can link calving_event_id on lactation
        calving = make_record({
            "animal_id": animal_id,
            "herd_id": animal["herd_id"],
            "breeding_event_id": breeding_event_id,
            "calving_date": body["calving_date"],
            "opened_lactation_id": None,
            "closed_lactation_id": closed_lactation_id,
        })
        new_lac = make_record({
            "animal_id": animal_id,
            "herd_id": animal["herd_id"],
            "parity": animal["parity"],
            "calving_event_id": calving["id"],
            "start_date": body["calving_date"],
            "dry_off_date": None,
            "cumulative_milk_lbs": 0,
            "projected_305d_milk_lbs": 0,
            "status": "OPEN",
        })
        db.lactations[new_lac["id"]] = new_lac
        calving["opened_lactation_id"] = new_lac["id"]
        db.calving_events[calving["id"]] = calving
        # finalize animal
        touch(animal)
        # step 4: herd active_animal_count recomputed (bump herd version)
        domain.bump_herd_for_count(animal["herd_id"])
        return object_response(serializers.calving_event_out(calving), 201)


@bp.route("/herds/calving-events", methods=["GET"])
@require_roles("HerdManager", "Veterinarian", "CoopSettlementAgent", "Auditor")
def list_calving_events():
    items = list(db.calving_events.values())
    animal_id = request.args.get("animal_id")
    herd_id = request.args.get("herd_id")
    breeding_event_id = request.args.get("breeding_event_id")
    opened = request.args.get("opened_lactation_id")
    closed = request.args.get("closed_lactation_id")
    if animal_id is not None:
        items = [r for r in items if r["animal_id"] == animal_id]
    if herd_id is not None:
        items = [r for r in items if r["herd_id"] == herd_id]
    if breeding_event_id is not None:
        items = [r for r in items if r["breeding_event_id"] == breeding_event_id]
    if opened is not None:
        items = [r for r in items if r.get("opened_lactation_id") == opened]
    if closed is not None:
        items = [r for r in items if r.get("closed_lactation_id") == closed]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items, request.args)
    return array_response([serializers.calving_event_out(r) for r in page], limit, offset, total)


@bp.route("/herds/calving-events/<calving_id>", methods=["GET"])
@require_roles("HerdManager", "Veterinarian", "CoopSettlementAgent", "Auditor")
def get_calving_event(calving_id):
    if calving_id not in db.calving_events:
        raise err(errors.ERR_ANIMAL_NOT_FOUND, "calving event not found")
    return object_response(serializers.calving_event_out(db.calving_events[calving_id]), 200)
