from datetime import timedelta

from flask import Blueprint

import calc
import db
import services
from auth import (
    authenticate,
    ROLE_SANCTUARY_DIRECTOR,
    ROLE_INTAKE_COORDINATOR,
    ROLE_VETERINARIAN,
    ROLE_FARRIER,
    ROLE_ADOPTION_OFFICER,
    ROLE_BARN_MANAGER,
    ROLE_VOLUNTEER_COORDINATOR,
    ROLE_ADOPTER,
    ROLE_SPONSOR,
)
from errors import (
    raise_err,
    ERR_HORSE_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_QUARANTINE_ACTIVE,
    ERR_BONDED_PAIR_VIOLATION,
)
from response import ok_object, ok_list
from serializers import serialize, serialize_many
from util import (
    body,
    get_path_or_404,
    minute_floor,
    opt_int,
    opt_str,
    pagination_args,
    parse_dt,
    query_str,
    require_present,
    as_enum,
    as_int,
    sorted_page,
)
import clock

bp = Blueprint("horses", __name__)

SEXES = {"MARE", "GELDING", "STALLION"}
BREED_CLASSES = {"LIGHT", "DRAFT", "PONY"}
TRAINING_LEVELS = {"UNHANDLED", "GREEN", "TRAINED_RIDDEN"}
READ_ROLES = [
    ROLE_SANCTUARY_DIRECTOR,
    ROLE_INTAKE_COORDINATOR,
    ROLE_VETERINARIAN,
    ROLE_FARRIER,
    ROLE_ADOPTION_OFFICER,
    ROLE_BARN_MANAGER,
    ROLE_VOLUNTEER_COORDINATOR,
    ROLE_ADOPTER,
    ROLE_SPONSOR,
]


def _check_companion_exists(data):
    companion_id = data.get("bonded_companion_id")
    if companion_id is not None and companion_id not in db.horses:
        raise_err(ERR_HORSE_NOT_FOUND, "bonded_companion_id does not reference an existing horse")


def _check_bonded_release(horse):
    if horse["bonded_companion_id"]:
        companion = db.horses.get(horse["bonded_companion_id"])
        if companion is None or companion["status"] not in ("ADOPTABLE", "ADOPTION_PENDING"):
            raise_err(
                ERR_BONDED_PAIR_VIOLATION,
                "Bonded companion must be ADOPTABLE or ADOPTION_PENDING",
            )


def _has_completed_medical_pass(horse_id, within_days=None):
    now = clock.now()
    for e in db.evaluations.values():
        if (
            e["horse_id"] == horse_id
            and e["status"] == "COMPLETED"
            and e["evaluation_type"] == "MEDICAL"
            and e["outcome"] == "PASS"
        ):
            if within_days is None:
                return True
            if minute_floor(e["evaluation_date"]) >= minute_floor(now - timedelta(days=within_days)):
                return True
    return False


@bp.post("/rescue-ops/horses")
def create_horse():
    authenticate([ROLE_INTAKE_COORDINATOR])
    data = body()
    _check_companion_exists(data)
    name = require_present(data, "name")
    sex = as_enum(require_present(data, "sex"), "sex", SEXES)
    breed_class = as_enum(require_present(data, "breed_class"), "breed_class", BREED_CLASSES)
    weight = as_int(require_present(data, "estimated_weight_lbs"), "estimated_weight_lbs")
    if weight <= 0:
        raise_err(ERR_INVALID_REQUEST, "estimated_weight_lbs must be > 0")
    age = as_int(require_present(data, "age_years"), "age_years")
    if age < 0:
        raise_err(ERR_INVALID_REQUEST, "age_years must be >= 0")
    bcs = as_int(require_present(data, "body_condition_score"), "body_condition_score")
    if bcs < 1 or bcs > 9:
        raise_err(ERR_INVALID_REQUEST, "body_condition_score must be in 1..9")
    training = as_enum(require_present(data, "training_level"), "training_level", TRAINING_LEVELS)
    temperament = opt_int(data, "temperament_score", 5)
    if temperament < 1 or temperament > 10:
        raise_err(ERR_INVALID_REQUEST, "temperament_score must be in 1..10")
    intake_reason = opt_str(data, "intake_reason")
    bonded = data.get("bonded_companion_id")
    if bonded is not None and not isinstance(bonded, str):
        raise_err(ERR_INVALID_REQUEST, "bonded_companion_id must be a string")

    horse = services.new_entity(
        {
            "name": name,
            "sex": sex,
            "breed_class": breed_class,
            "estimated_weight_lbs": weight,
            "age_years": age,
            "body_condition_score": bcs,
            "temperament_score": temperament,
            "training_level": training,
            "intake_reason": intake_reason,
            "bonded_companion_id": bonded,
            "status": "QUARANTINE",
            "prior_status": None,
            "current_location": "QUARANTINE_STALL",
            "active_application_id": None,
            "daily_feed_ration_lbs": calc.daily_ration(weight, bcs),
        }
    )
    db.horses[horse["id"]] = horse
    services.create_protocol(horse["id"], 14, "INTAKE")
    return ok_object(serialize(horse), 201)


@bp.get("/rescue-ops/horses")
def list_horses():
    authenticate(READ_ROLES)
    limit, offset = pagination_args()
    filters = []
    for param in ("status", "current_location", "bonded_companion_id", "active_application_id"):
        value = query_str(param)
        if value is not None:
            filters.append((param, value))
    rows, total = sorted_page(db.horses.values(), filters, limit, offset)
    return ok_list(serialize_many(rows), limit, offset, total)


@bp.get("/rescue-ops/horses/<horse_id>")
def get_horse(horse_id):
    authenticate(READ_ROLES)
    return ok_object(serialize(get_path_or_404(db.horses, horse_id)))


@bp.patch("/rescue-ops/horses/<horse_id>")
def patch_horse(horse_id):
    authenticate([ROLE_INTAKE_COORDINATOR, ROLE_VETERINARIAN])
    horse = get_path_or_404(db.horses, horse_id)
    data = body()
    if "bonded_companion_id" in data and data["bonded_companion_id"] is not None:
        if data["bonded_companion_id"] not in db.horses:
            raise_err(ERR_HORSE_NOT_FOUND, "bonded_companion_id does not reference an existing horse")

    new_weight = horse["estimated_weight_lbs"]
    new_bcs = horse["body_condition_score"]
    if "estimated_weight_lbs" in data and data["estimated_weight_lbs"] is not None:
        new_weight = as_int(data["estimated_weight_lbs"], "estimated_weight_lbs")
        if new_weight <= 0:
            raise_err(ERR_INVALID_REQUEST, "estimated_weight_lbs must be > 0")
    if "body_condition_score" in data and data["body_condition_score"] is not None:
        new_bcs = as_int(data["body_condition_score"], "body_condition_score")
        if new_bcs < 1 or new_bcs > 9:
            raise_err(ERR_INVALID_REQUEST, "body_condition_score must be in 1..9")
    updates = {}
    if "temperament_score" in data and data["temperament_score"] is not None:
        t = as_int(data["temperament_score"], "temperament_score")
        if t < 1 or t > 10:
            raise_err(ERR_INVALID_REQUEST, "temperament_score must be in 1..10")
        updates["temperament_score"] = t
    if "training_level" in data and data["training_level"] is not None:
        updates["training_level"] = as_enum(data["training_level"], "training_level", TRAINING_LEVELS)
    if "bonded_companion_id" in data:
        bonded = data["bonded_companion_id"]
        if bonded is not None and not isinstance(bonded, str):
            raise_err(ERR_INVALID_REQUEST, "bonded_companion_id must be a string")
        updates["bonded_companion_id"] = bonded

    if horse["status"] == "DECEASED":
        raise_err(ERR_INVALID_STATE, "DECEASED is terminal; the horse record is locked")

    ration_changed = (
        new_weight != horse["estimated_weight_lbs"] or new_bcs != horse["body_condition_score"]
    )
    horse["estimated_weight_lbs"] = new_weight
    horse["body_condition_score"] = new_bcs
    horse.update(updates)
    if ration_changed:
        horse["daily_feed_ration_lbs"] = calc.daily_ration(new_weight, new_bcs)
    services.touch(horse)
    return ok_object(serialize(horse))


@bp.post("/rescue-ops/horses/<horse_id>/release-quarantine")
def release_quarantine(horse_id):
    authenticate([ROLE_INTAKE_COORDINATOR])
    horse = get_path_or_404(db.horses, horse_id)
    data = body()
    target = as_enum(
        require_present(data, "target_status"),
        "target_status",
        {"REHABILITATION", "ADOPTABLE"},
    )
    if horse["status"] != "QUARANTINE":
        raise_err(ERR_INVALID_STATE, "Horse is not in QUARANTINE")
    if services.active_protocol_for(horse["id"]) is not None:
        raise_err(ERR_QUARANTINE_ACTIVE, "Quarantine protocol is still ACTIVE")
    if target == "ADOPTABLE":
        if not _has_completed_medical_pass(horse["id"]):
            raise_err(ERR_INVALID_STATE, "No COMPLETED MEDICAL evaluation with outcome PASS")
        _check_bonded_release(horse)
    horse["status"] = target
    horse["current_location"] = "REHAB_PADDOCK" if target == "REHABILITATION" else "MAIN_PASTURE"
    services.touch(horse)
    return ok_object(serialize(horse))


@bp.post("/rescue-ops/horses/<horse_id>/graduate-rehabilitation")
def graduate_rehabilitation(horse_id):
    authenticate([ROLE_VETERINARIAN])
    horse = get_path_or_404(db.horses, horse_id)
    if horse["status"] != "REHABILITATION":
        raise_err(ERR_INVALID_STATE, "Horse is not in REHABILITATION")
    plans = [p for p in db.rehab_plans.values() if p["horse_id"] == horse["id"]]
    has_completed = any(p["status"] == "COMPLETED" for p in plans)
    has_open = any(p["status"] in ("DRAFT", "ACTIVE") for p in plans)
    if not has_completed or has_open:
        raise_err(
            ERR_INVALID_STATE,
            "Requires a COMPLETED rehabilitation plan and none in DRAFT or ACTIVE",
        )
    if not _has_completed_medical_pass(horse["id"], within_days=30):
        raise_err(
            ERR_INVALID_STATE,
            "No COMPLETED MEDICAL PASS evaluation within 30 days",
        )
    _check_bonded_release(horse)
    horse["status"] = "ADOPTABLE"
    horse["current_location"] = "MAIN_PASTURE"
    services.touch(horse)
    return ok_object(serialize(horse))


@bp.post("/rescue-ops/horses/<horse_id>/designate-sanctuary")
def designate_sanctuary(horse_id):
    authenticate([ROLE_SANCTUARY_DIRECTOR])
    horse = get_path_or_404(db.horses, horse_id)
    data = body()
    require_present(data, "reason")
    if horse["status"] != "REHABILITATION":
        raise_err(ERR_INVALID_STATE, "Horse is not in REHABILITATION")
    horse["status"] = "SANCTUARY"
    horse["current_location"] = "SANCTUARY_PASTURE"
    services.touch(horse)
    return ok_object(serialize(horse))


@bp.post("/rescue-ops/horses/<horse_id>/quarantine")
def requarantine(horse_id):
    authenticate([ROLE_INTAKE_COORDINATOR])
    horse = get_path_or_404(db.horses, horse_id)
    data = body()
    min_days = as_int(require_present(data, "min_days"), "min_days")
    if min_days < 1 or min_days > 60:
        raise_err(ERR_INVALID_REQUEST, "min_days must be in 1..60")
    reason = require_present(data, "reason")
    if horse["status"] not in ("REHABILITATION", "ADOPTABLE", "SANCTUARY"):
        raise_err(ERR_INVALID_STATE, "Horse posture does not allow re-quarantine")
    if services.active_protocol_for(horse["id"]) is not None:
        raise_err(ERR_QUARANTINE_ACTIVE, "Horse already has an ACTIVE quarantine protocol")
    proto = services.create_protocol(horse["id"], min_days, reason)
    horse["status"] = "QUARANTINE"
    horse["current_location"] = "QUARANTINE_STALL"
    services.requarantine_appointment_cascade(horse["id"])
    services.touch(horse)
    return ok_object(serialize(proto), 201)
