"""Animal roster and the veterinary health cycle (PRD §3.2)."""
from flask import Blueprint

from db import store
from errors import (
    raise_err, ERR_ANIMAL_NOT_FOUND, ERR_INVALID_STATE,
)
from middleware import require
from response import ok
from serializers import (
    ser_animal, ser_health_record, ser_booking_animal,
)
from services.cascade import recompute_cert_expiry, remove_animal_attachments
from util import (
    body_json, bump, new_common, new_immutable, paginate,
    v_dt, v_enum, v_int, v_str,
)

bp = Blueprint("animals", __name__)

SPECIES = {"GOAT", "SHEEP", "PONY", "RABBIT", "CHICKEN", "REPTILE"}
WEIGHT_CLASSES = {"SMALL", "MEDIUM", "LARGE"}
ANIMAL_STATUSES = {"AVAILABLE", "QUARANTINE", "RETIRED"}


def get_animal_or_404(animal_id):
    animal = store.animals.get(animal_id)
    if animal is None:
        raise_err(ERR_ANIMAL_NOT_FOUND, "Animal not found")
    return animal


@bp.post("/petting-zoo/animals")
def create_animal():
    require({"Operator"})
    body = body_json()
    animal = new_common()
    animal.update({
        "name": v_str(body, "name"),
        "species": v_enum(body, "species", SPECIES),
        "weight_class": v_enum(body, "weight_class", WEIGHT_CLASSES),
        "temperament_tier": v_int(body, "temperament_tier", minimum=1, maximum=3),
        "base_event_fee_cents": v_int(body, "base_event_fee_cents"),
        "rest_buffer_hours": v_int(body, "rest_buffer_hours", required=False, default=4),
        "status": "AVAILABLE",
        "current_health_cert_expires_at": None,
    })
    store.animals[animal["id"]] = animal
    return ok(ser_animal(animal), status=201)


@bp.get("/petting-zoo/animals")
def list_animals():
    require({"Coordinator", "Operator", "Veterinarian"})
    from flask import request
    animals = list(store.animals.values())
    species = request.args.get("species")
    if species is not None:
        animals = [a for a in animals if a["species"] == species]
    weight_class = request.args.get("weight_class")
    if weight_class is not None:
        animals = [a for a in animals if a["weight_class"] == weight_class]
    status = request.args.get("status")
    if status is not None:
        animals = [a for a in animals if a["status"] == status]
    data, meta = paginate(animals, ser_animal)
    return ok(data, pagination=meta)


@bp.get("/petting-zoo/animals/<animal_id>")
def get_animal(animal_id):
    require({"Coordinator", "Operator", "Veterinarian"})
    return ok(ser_animal(get_animal_or_404(animal_id)))


@bp.post("/petting-zoo/animals/<animal_id>/retire")
def retire_animal(animal_id):
    require({"Operator"})
    animal = get_animal_or_404(animal_id)
    if animal["status"] == "RETIRED":
        raise_err(ERR_INVALID_STATE, "Animal is already RETIRED")
    if animal["status"] == "AVAILABLE":
        # Same attachment-removal cascade as quarantine, reason RETIRED,
        # but no booking auto-cancellation.
        remove_animal_attachments(animal, "RETIRED", auto_cancel=False)
    animal["status"] = "RETIRED"
    bump(animal)
    return ok(ser_animal(animal))


@bp.post("/petting-zoo/animals/<animal_id>/health-records")
def create_health_record(animal_id):
    require({"Veterinarian"})
    body = body_json()
    exam_date = v_dt(body, "exam_date")
    result = v_enum(body, "result", {"PASS", "FAIL"})
    valid_until = v_dt(body, "valid_until", required=False, default=None)
    notes = v_str(body, "notes", required=False, default="")
    animal = get_animal_or_404(animal_id)
    if animal["status"] == "RETIRED":
        # RETIRED is terminal; a retired animal accepts no further transitions.
        raise_err(ERR_INVALID_STATE, "Animal is RETIRED")

    record = new_immutable()
    record.update({
        "animal_id": animal_id,
        "exam_date": exam_date,
        "result": result,
        "valid_until": valid_until,  # ignored for FAIL results
        "notes": notes,
    })
    store.health_records[record["id"]] = record

    if result == "PASS":
        recompute_cert_expiry(animal)
        if animal["status"] == "QUARANTINE":
            animal["status"] = "AVAILABLE"
        bump(animal)
    else:  # FAIL -> quarantine cascade
        if animal["status"] == "AVAILABLE":
            animal["status"] = "QUARANTINE"
        # Cascade link 2 (+ possible link 3 auto-cancel).
        remove_animal_attachments(animal, "QUARANTINE", auto_cancel=True)
        bump(animal)
    return ok(ser_health_record(record), status=201)


@bp.get("/petting-zoo/animals/<animal_id>/health-records")
def list_health_records(animal_id):
    require({"Veterinarian", "Coordinator", "Operator"})
    get_animal_or_404(animal_id)
    records = [h for h in store.health_records.values() if h["animal_id"] == animal_id]
    data, meta = paginate(records, ser_health_record)
    return ok(data, pagination=meta)


@bp.get("/petting-zoo/animals/<animal_id>/booking-animals")
def list_animal_booking_animals(animal_id):
    require({"Coordinator", "Operator"})
    get_animal_or_404(animal_id)
    bas = [ba for ba in store.booking_animals.values() if ba["animal_id"] == animal_id]
    data, meta = paginate(bas, ser_booking_animal)
    return ok(data, pagination=meta)
