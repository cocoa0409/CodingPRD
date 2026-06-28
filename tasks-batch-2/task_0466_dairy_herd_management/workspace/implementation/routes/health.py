"""HealthTreatment routes (PRD §3.9)."""
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
from util import iso_format
import clock
import validators as V

bp = Blueprint("health", __name__)

ALL_ROLES = ("HerdManager", "ParlorTech", "Veterinarian", "CoopSettlementAgent", "Auditor")


@bp.route("/herds/health-treatments", methods=["POST"])
@require_roles("Veterinarian", "HerdManager")
def create_treatment():
    body = V.require_json_object()
    animal_id = V.require_fk(body, "animal_id")
    drug_name = V.require_str(body, "drug_name")
    administered_at = V.require_datetime(body, "administered_at")
    milk_withhold_hours = V.require_int(body, "milk_withhold_hours", minimum=0)
    meat_withdrawal_hours = V.require_int(body, "meat_withdrawal_hours", minimum=0)
    animal = V.get_or_404("animal", animal_id)
    with db.lock:
        milk_until = administered_at + timedelta(hours=milk_withhold_hours)
        meat_until = administered_at + timedelta(hours=meat_withdrawal_hours)
        rec = make_record({
            "animal_id": animal_id,
            "herd_id": animal["herd_id"],
            "drug_name": drug_name,
            "administered_at": body["administered_at"],
            "milk_withhold_hours": milk_withhold_hours,
            "meat_withdrawal_hours": meat_withdrawal_hours,
            "milk_withhold_until": iso_format(milk_until),
            "meat_withdrawal_until": iso_format(meat_until),
            "status": "ACTIVE",
        })
        rec["_milk_withhold_until_dt"] = milk_until
        rec["_meat_withdrawal_until_dt"] = meat_until
        db.health_treatments[rec["id"]] = rec
        # Animal.milk_eligible = false if milk_withhold_until > current clock
        if milk_until > clock.now():
            animal["milk_eligible"] = False
            touch(animal)
        return object_response(serializers.health_treatment_out(rec), 201)


@bp.route("/herds/health-treatments", methods=["GET"])
@require_roles("HerdManager", "Veterinarian", "CoopSettlementAgent", "Auditor")
def list_treatments():
    items = list(db.health_treatments.values())
    animal_id = request.args.get("animal_id")
    herd_id = request.args.get("herd_id")
    if animal_id is not None:
        items = [r for r in items if r["animal_id"] == animal_id]
    if herd_id is not None:
        items = [r for r in items if r["herd_id"] == herd_id]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items, request.args)
    return array_response([serializers.health_treatment_out(r) for r in page], limit, offset, total)


@bp.route("/herds/health-treatments/<treatment_id>", methods=["GET"])
@require_roles("HerdManager", "Veterinarian", "CoopSettlementAgent", "Auditor")
def get_treatment(treatment_id):
    rec = V.get_or_404("treatment", treatment_id)
    return object_response(serializers.health_treatment_out(rec), 200)


@bp.route("/herds/health-treatments/<treatment_id>/clear", methods=["POST"])
@require_roles("Veterinarian")
def clear_treatment(treatment_id):
    rec = V.get_or_404("treatment", treatment_id)
    with db.lock:
        if rec["status"] != "ACTIVE":
            raise err(errors.ERR_TREATMENT_NOT_ACTIVE, "Treatment is not ACTIVE")
        now = clock.now()
        if now < rec["_milk_withhold_until_dt"] or now < rec["_meat_withdrawal_until_dt"]:
            raise err(errors.ERR_WITHHOLD_NOT_ELAPSED,
                      "A withhold window has not yet elapsed")
        rec["status"] = "CLEARED"
        touch(rec)
        # recompute Animal.milk_eligible (excluding this now-cleared treatment)
        animal = db.animals.get(rec["animal_id"])
        if animal is not None:
            domain.recompute_milk_eligible(animal, exclude_treatment_id=rec["id"])
            touch(animal)
        return object_response(serializers.health_treatment_out(rec), 200)


@bp.route("/herds/health-treatments/<treatment_id>/void", methods=["POST"])
@require_roles("Veterinarian")
def void_treatment(treatment_id):
    rec = V.get_or_404("treatment", treatment_id)
    with db.lock:
        if rec["status"] != "ACTIVE":
            raise err(errors.ERR_TREATMENT_NOT_ACTIVE, "Treatment is not ACTIVE")
        rec["status"] = "VOIDED"
        touch(rec)
        # recompute Animal.milk_eligible immediately (excluding voided treatment)
        animal = db.animals.get(rec["animal_id"])
        if animal is not None:
            domain.recompute_milk_eligible(animal, exclude_treatment_id=rec["id"])
            touch(animal)
        return object_response(serializers.health_treatment_out(rec), 200)
