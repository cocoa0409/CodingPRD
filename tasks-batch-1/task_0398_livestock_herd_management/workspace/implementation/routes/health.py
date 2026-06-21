"""Health treatments: record (with clearance computation + withhold), get/list,
and void (compensating)."""
from flask import Blueprint, request
from datetime import timedelta

import errors
from db import db
from clock import clock
from middleware import authenticate, require_role
from response import object_response, array_response
from util import (get_json_body, as_str, as_enum, as_int, date_field,
                  parse_pagination, paginate)
from services.common import base_record, get_or_404, touch
from services import serializers as S
from services import domain

bp = Blueprint("health", __name__)

ROUTES = {"INJECTION_IM", "INJECTION_SC", "ORAL", "TOPICAL_POUR_ON", "INTRAMAMMARY"}
ACTIVE_STATES = ("ACTIVE", "SUSPENDED")


@bp.route("/health-treatments", methods=["POST"])
def create_treatment():
    role = authenticate()
    require_role(role, {"Veterinarian"})
    body = get_json_body()

    animal_id = as_str(body, "animal_id")
    animal = get_or_404(db.animals, animal_id)
    drug_id = as_str(body, "drug_product_id")
    drug = get_or_404(db.drug_products, drug_id)

    # shape validation
    route = as_enum(body, "route", ROUTES)
    dose_count = as_int(body, "dose_count", required=False, default=1, ge=1)
    first_dose_on = date_field(body, "first_dose_on")
    last_dose_on = date_field(body, "last_dose_on")

    # state: animal must be ACTIVE or SUSPENDED
    if animal["life_status"] not in ACTIVE_STATES:
        raise errors.ApiError(errors.ERR_ANIMAL_NOT_ACTIVE, 409,
                              "animal must be ACTIVE or SUSPENDED for a treatment")

    # route must be a key in the product's route_withdrawals (priority 9)
    if route not in drug["route_withdrawals"]:
        raise errors.ApiError(errors.ERR_ROUTE_NOT_PERMITTED, 422,
                              "route not permitted for this drug product")

    # dose dates coherent (priority 15): not future, last >= first
    today = clock.today()
    if first_dose_on > today or last_dose_on > today or last_dose_on < first_dose_on:
        raise errors.ApiError(errors.ERR_DOSE_DATES_INVALID, 422,
                              "dose dates invalid")

    wd_days = drug["route_withdrawals"][route]
    clearance_date = last_dose_on + timedelta(days=wd_days)

    rec = base_record()
    rec.update({
        "animal_id": animal_id,
        "drug_product_id": drug_id,
        "route": route,
        "dose_count": dose_count,
        "first_dose_on": first_dose_on,
        "last_dose_on": last_dose_on,
        "clearance_date": clearance_date,
    })

    # status from withdrawal duration / clock
    if wd_days == 0 or clearance_date <= today:
        rec["status"] = "CLEARED"
        db.health_treatments[rec["id"]] = rec
    else:
        rec["status"] = "WITHDRAWAL_ACTIVE"
        db.health_treatments[rec["id"]] = rec
        # drive animal residue dimension -> WITHHELD, push meat_clear_on later
        prev = animal.get("meat_clear_on")
        animal["meat_clearance_status"] = "WITHHELD"
        animal["meat_clear_on"] = clearance_date if prev is None else max(prev, clearance_date)
        touch(animal)

    domain.append_trace(animal_id, "TREATMENT", "HealthTreatment", rec["id"],
                        last_dose_on,
                        {"drug_product_id": drug_id, "route": route,
                         "clearance_date": rec["clearance_date"].isoformat()})

    return object_response(S.health_treatment_out(rec), 201)


@bp.route("/health-treatments/<tid>", methods=["GET"])
def get_treatment(tid):
    role = authenticate()
    require_role(role, {"Veterinarian", "HerdManager", "Auditor"})
    t = get_or_404(db.health_treatments, tid)
    return object_response(S.health_treatment_out(t), 200)


@bp.route("/health-treatments", methods=["GET"])
def list_treatments():
    role = authenticate()
    require_role(role, {"Veterinarian", "HerdManager", "Auditor"})
    limit, offset = parse_pagination()
    animal_id = request.args.get("animal_id")
    drug_id = request.args.get("drug_product_id")
    items = list(db.health_treatments.values())
    if animal_id is not None:
        items = [t for t in items if t["animal_id"] == animal_id]
    if drug_id is not None:
        items = [t for t in items if t["drug_product_id"] == drug_id]
    items.sort(key=lambda t: (t["created_at"], t["_seq"]))
    window, total = paginate(items, limit, offset)
    return array_response([S.health_treatment_out(t) for t in window], limit, offset, total)


@bp.route("/health-treatments/<tid>/void", methods=["POST"])
def void_treatment(tid):
    role = authenticate()
    require_role(role, {"Veterinarian"})
    t = get_or_404(db.health_treatments, tid)
    if t["status"] != "WITHDRAWAL_ACTIVE":
        raise errors.invalid_state("only WITHDRAWAL_ACTIVE treatments may be voided")
    t["status"] = "VOIDED"
    touch(t)

    # recompute the animal's clearance from remaining non-voided future treatments
    animal = db.animals.get(t["animal_id"])
    if animal is not None:
        if domain.rederive_clearance_for_animal(animal):
            touch(animal)

    return object_response(S.health_treatment_out(t), 200)
