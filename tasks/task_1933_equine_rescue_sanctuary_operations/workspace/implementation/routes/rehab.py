from datetime import timedelta

from flask import Blueprint

import db
import services
from auth import (
    authenticate,
    ROLE_SANCTUARY_DIRECTOR,
    ROLE_INTAKE_COORDINATOR,
    ROLE_VETERINARIAN,
    ROLE_FARRIER,
    ROLE_ADOPTION_OFFICER,
)
from errors import (
    raise_err,
    ERR_HORSE_NOT_FOUND,
    ERR_PRACTITIONER_NOT_FOUND,
    ERR_REHAB_PLAN_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STALE_HORSE_VERSION,
    ERR_HORSE_NOT_RESIDENT,
    ERR_QUARANTINE_SERVICE_RESTRICTED,
    ERR_APPOINTMENT_OVERLAP,
    ERR_SERVICE_SPECIALTY_MISMATCH,
    ERR_PLAN_HAS_OPEN_APPOINTMENTS,
    ERR_FORBIDDEN,
)
from response import ok_object, ok_list
from serializers import serialize, serialize_many
from util import (
    as_bool,
    as_enum,
    as_int,
    as_str,
    body,
    get_path_or_404,
    opt_bool,
    opt_str,
    pagination_args,
    parse_dt,
    parse_query_bool,
    query_str,
    require_present,
    sorted_page,
)

bp = Blueprint("rehab", __name__)

SPECIALTIES = {"VETERINARIAN", "FARRIER"}
SERVICE_TYPES = {"VET_EXAM", "VET_PROCEDURE", "DENTAL", "FARRIER_TRIM", "FARRIER_SHOEING"}
VET_SERVICES = {"VET_EXAM", "VET_PROCEDURE", "DENTAL"}
FARRIER_SERVICES = {"FARRIER_TRIM", "FARRIER_SHOEING"}
BUFFER = timedelta(minutes=15)

PLAN_READ_ROLES = [ROLE_SANCTUARY_DIRECTOR, ROLE_INTAKE_COORDINATOR, ROLE_VETERINARIAN]
PRACT_READ_ROLES = [
    ROLE_SANCTUARY_DIRECTOR,
    ROLE_INTAKE_COORDINATOR,
    ROLE_VETERINARIAN,
    ROLE_FARRIER,
    ROLE_ADOPTION_OFFICER,
]
APPT_ROLES = [ROLE_SANCTUARY_DIRECTOR, ROLE_INTAKE_COORDINATOR, ROLE_VETERINARIAN, ROLE_FARRIER]


# --------------------------------------------------------------------------
# Rehabilitation plans
# --------------------------------------------------------------------------
@bp.post("/rescue-ops/rehabilitation-plans")
def create_plan():
    authenticate([ROLE_VETERINARIAN])
    data = body()
    horse_id = data.get("horse_id")
    if horse_id is not None and horse_id not in db.horses:
        raise_err(ERR_HORSE_NOT_FOUND, "horse_id does not reference an existing horse")
    horse_id = require_present(data, "horse_id")
    goals = as_str(require_present(data, "goals"), "goals")
    target_bcs = as_int(
        require_present(data, "target_body_condition_score"), "target_body_condition_score"
    )
    if target_bcs < 1 or target_bcs > 9:
        raise_err(ERR_INVALID_REQUEST, "target_body_condition_score must be in 1..9")
    planned_weeks = as_int(require_present(data, "planned_weeks"), "planned_weeks")
    if planned_weeks < 1 or planned_weeks > 52:
        raise_err(ERR_INVALID_REQUEST, "planned_weeks must be in 1..52")
    expected = as_int(require_present(data, "expected_horse_version"), "expected_horse_version")

    horse = db.horses[horse_id]
    if expected != horse["version"]:
        raise_err(ERR_STALE_HORSE_VERSION, "expected_horse_version is stale")
    if horse["status"] != "REHABILITATION":
        raise_err(ERR_INVALID_STATE, "Horse is not in REHABILITATION")

    for plan in db.rehab_plans.values():
        if plan["horse_id"] == horse_id and plan["status"] in ("DRAFT", "ACTIVE"):
            plan["status"] = "SUPERSEDED"
            services.touch(plan)
    rec = services.new_entity(
        {
            "horse_id": horse_id,
            "goals": goals,
            "target_body_condition_score": target_bcs,
            "planned_weeks": planned_weeks,
            "status": "DRAFT",
            "completed_visit_count": 0,
            "activated_at": None,
        }
    )
    db.rehab_plans[rec["id"]] = rec
    services.touch(horse)
    return ok_object(serialize(rec), 201)


@bp.get("/rescue-ops/rehabilitation-plans")
def list_plans():
    authenticate(PLAN_READ_ROLES)
    limit, offset = pagination_args()
    filters = []
    for param in ("horse_id", "status"):
        value = query_str(param)
        if value is not None:
            filters.append((param, value))
    rows, total = sorted_page(db.rehab_plans.values(), filters, limit, offset)
    return ok_list(serialize_many(rows), limit, offset, total)


@bp.get("/rescue-ops/rehabilitation-plans/<plan_id>")
def get_plan(plan_id):
    authenticate(PLAN_READ_ROLES)
    return ok_object(serialize(get_path_or_404(db.rehab_plans, plan_id)))


@bp.post("/rescue-ops/rehabilitation-plans/<plan_id>/activate")
def activate_plan(plan_id):
    authenticate([ROLE_VETERINARIAN])
    plan = get_path_or_404(db.rehab_plans, plan_id)
    if plan["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Plan is not in DRAFT")
    horse = db.horses[plan["horse_id"]]
    if horse["status"] != "REHABILITATION":
        raise_err(ERR_INVALID_STATE, "Horse is not in REHABILITATION")
    if any(
        p["horse_id"] == plan["horse_id"] and p["status"] == "ACTIVE" and p["id"] != plan["id"]
        for p in db.rehab_plans.values()
    ):
        raise_err(ERR_INVALID_STATE, "Horse already has an ACTIVE rehabilitation plan")
    import clock

    plan["status"] = "ACTIVE"
    plan["activated_at"] = clock.now()
    services.touch(plan)
    return ok_object(serialize(plan))


@bp.post("/rescue-ops/rehabilitation-plans/<plan_id>/complete")
def complete_plan(plan_id):
    authenticate([ROLE_VETERINARIAN])
    plan = get_path_or_404(db.rehab_plans, plan_id)
    if plan["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Plan is not ACTIVE")
    if any(
        a["rehab_plan_id"] == plan["id"] and a["status"] in ("REQUESTED", "CONFIRMED")
        for a in db.appointments.values()
    ):
        raise_err(ERR_PLAN_HAS_OPEN_APPOINTMENTS, "Plan has open linked appointments")
    plan["status"] = "COMPLETED"
    services.touch(plan)
    return ok_object(serialize(plan))


# --------------------------------------------------------------------------
# Practitioners
# --------------------------------------------------------------------------
@bp.post("/rescue-ops/practitioners")
def create_practitioner():
    authenticate([ROLE_SANCTUARY_DIRECTOR])
    data = body()
    name = as_str(require_present(data, "name"), "name")
    specialty = as_enum(require_present(data, "specialty"), "specialty", SPECIALTIES)
    active = opt_bool(data, "active", True)
    rec = services.new_entity({"name": name, "specialty": specialty, "active": active})
    db.practitioners[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/rescue-ops/practitioners")
def list_practitioners():
    authenticate(PRACT_READ_ROLES)
    limit, offset = pagination_args()
    filters = []
    value = query_str("specialty")
    if value is not None:
        filters.append(("specialty", value))
    active = parse_query_bool("active")
    if active is not None:
        filters.append(("active", active))
    rows, total = sorted_page(db.practitioners.values(), filters, limit, offset)
    return ok_list(serialize_many(rows), limit, offset, total)


@bp.get("/rescue-ops/practitioners/<pract_id>")
def get_practitioner(pract_id):
    authenticate(PRACT_READ_ROLES)
    return ok_object(serialize(get_path_or_404(db.practitioners, pract_id)))


@bp.patch("/rescue-ops/practitioners/<pract_id>")
def patch_practitioner(pract_id):
    authenticate([ROLE_SANCTUARY_DIRECTOR])
    pract = get_path_or_404(db.practitioners, pract_id)
    data = body()
    new_active = pract["active"]
    if "active" in data and data["active"] is not None:
        new_active = as_bool(data["active"], "active")
    if "name" in data and data["name"] is not None:
        pract["name"] = as_str(data["name"], "name")
    deactivating = pract["active"] and new_active is False
    pract["active"] = new_active
    services.touch(pract)
    if deactivating:
        services.practitioner_deactivation_cascade(pract["id"])
    return ok_object(serialize(pract))


# --------------------------------------------------------------------------
# Care service appointments
# --------------------------------------------------------------------------
@bp.post("/rescue-ops/care-service-appointments")
def create_appointment():
    authenticate([ROLE_INTAKE_COORDINATOR, ROLE_VETERINARIAN, ROLE_FARRIER])
    data = body()
    # Tier 5: body FK existence.
    for field, store, err in (
        ("horse_id", db.horses, ERR_HORSE_NOT_FOUND),
        ("practitioner_id", db.practitioners, ERR_PRACTITIONER_NOT_FOUND),
        ("rehab_plan_id", db.rehab_plans, ERR_REHAB_PLAN_NOT_FOUND),
    ):
        value = data.get(field)
        if value is not None and value not in store:
            raise_err(err, f"{field} does not reference an existing resource")
    # Tier 6: shape.
    horse_id = require_present(data, "horse_id")
    practitioner_id = require_present(data, "practitioner_id")
    service_type = as_enum(require_present(data, "service_type"), "service_type", SERVICE_TYPES)
    start = parse_dt(require_present(data, "scheduled_start"), "scheduled_start")
    end = parse_dt(require_present(data, "scheduled_end"), "scheduled_end")
    if end <= start:
        raise_err(ERR_INVALID_REQUEST, "scheduled_end must be after scheduled_start")
    rehab_plan_id = data.get("rehab_plan_id")

    # Tier 8: state (inactive practitioner cannot be booked).
    pract = db.practitioners[practitioner_id]
    if not pract["active"]:
        raise_err(ERR_INVALID_STATE, "Practitioner is inactive")
    # Tier 9: horse posture.
    horse = db.horses[horse_id]
    if horse["status"] in ("ADOPTED", "DECEASED"):
        raise_err(ERR_HORSE_NOT_RESIDENT, "Horse is not a resident")
    # Tier 11: quarantine service restriction.
    if horse["status"] == "QUARANTINE" and service_type != "VET_EXAM":
        raise_err(ERR_QUARANTINE_SERVICE_RESTRICTED, "Only VET_EXAM may be booked in quarantine")
    # Tier 14: practitioner overlap / 15-minute buffer.
    for other in db.appointments.values():
        if other["practitioner_id"] != practitioner_id:
            continue
        if other["status"] not in ("REQUESTED", "CONFIRMED"):
            continue
        if start < other["scheduled_end"] + BUFFER and other["scheduled_start"] < end + BUFFER:
            raise_err(
                ERR_APPOINTMENT_OVERLAP,
                "Appointment overlaps or sits within 15 minutes of another booking",
            )
    # Tier 23: specialty match.
    if service_type in VET_SERVICES and pract["specialty"] != "VETERINARIAN":
        raise_err(ERR_SERVICE_SPECIALTY_MISMATCH, "Service requires a VETERINARIAN")
    if service_type in FARRIER_SERVICES and pract["specialty"] != "FARRIER":
        raise_err(ERR_SERVICE_SPECIALTY_MISMATCH, "Service requires a FARRIER")

    rec = services.new_entity(
        {
            "horse_id": horse_id,
            "practitioner_id": practitioner_id,
            "rehab_plan_id": rehab_plan_id,
            "service_type": service_type,
            "scheduled_start": start,
            "scheduled_end": end,
            "status": "REQUESTED",
            "billing_status": "UNBILLED",
            "actual_cost_cents": None,
            "cancellation_reason": None,
        }
    )
    db.appointments[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/rescue-ops/care-service-appointments")
def list_appointments():
    authenticate(APPT_ROLES)
    limit, offset = pagination_args()
    filters = []
    for param in ("horse_id", "practitioner_id", "rehab_plan_id", "status"):
        value = query_str(param)
        if value is not None:
            filters.append((param, value))
    rows, total = sorted_page(db.appointments.values(), filters, limit, offset)
    return ok_list(serialize_many(rows), limit, offset, total)


@bp.get("/rescue-ops/care-service-appointments/<appt_id>")
def get_appointment(appt_id):
    authenticate(APPT_ROLES)
    return ok_object(serialize(get_path_or_404(db.appointments, appt_id)))


@bp.post("/rescue-ops/care-service-appointments/<appt_id>/confirm")
def confirm_appointment(appt_id):
    user_id, _ = authenticate([ROLE_VETERINARIAN, ROLE_FARRIER])
    appt = get_path_or_404(db.appointments, appt_id)
    if appt["status"] != "REQUESTED":
        raise_err(ERR_INVALID_STATE, "Appointment is not REQUESTED")
    if user_id != appt["practitioner_id"]:
        raise_err(ERR_FORBIDDEN, "Only the booked practitioner may confirm")
    pract = db.practitioners[appt["practitioner_id"]]
    if not pract["active"]:
        raise_err(ERR_INVALID_STATE, "Practitioner is inactive")
    horse = db.horses[appt["horse_id"]]
    if horse["status"] in ("ADOPTED", "DECEASED", "END_OF_LIFE_REVIEW"):
        raise_err(ERR_HORSE_NOT_RESIDENT, "Horse is not confirmable in its current posture")
    appt["status"] = "CONFIRMED"
    services.touch(appt)
    return ok_object(serialize(appt))


@bp.post("/rescue-ops/care-service-appointments/<appt_id>/complete")
def complete_appointment(appt_id):
    user_id, _ = authenticate([ROLE_VETERINARIAN, ROLE_FARRIER])
    appt = get_path_or_404(db.appointments, appt_id)
    data = body()
    cost = data.get("actual_cost_cents")
    if cost is not None:
        cost = as_int(cost, "actual_cost_cents")
        if cost < 0:
            raise_err(ERR_INVALID_REQUEST, "actual_cost_cents must be >= 0")
    if appt["status"] != "CONFIRMED":
        raise_err(ERR_INVALID_STATE, "Appointment is not CONFIRMED")
    if user_id != appt["practitioner_id"]:
        raise_err(ERR_FORBIDDEN, "Only the booked practitioner may complete")
    if cost is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field 'actual_cost_cents'")
    appt["status"] = "COMPLETED"
    appt["billing_status"] = "BILLED"
    appt["actual_cost_cents"] = cost
    services.touch(appt)
    if appt["rehab_plan_id"]:
        plan = db.rehab_plans.get(appt["rehab_plan_id"])
        if plan is not None and plan["status"] == "ACTIVE":
            plan["completed_visit_count"] += 1
            services.touch(plan)
    return ok_object(serialize(appt))


@bp.post("/rescue-ops/care-service-appointments/<appt_id>/cancel")
def cancel_appointment(appt_id):
    authenticate([ROLE_INTAKE_COORDINATOR, ROLE_VETERINARIAN])
    appt = get_path_or_404(db.appointments, appt_id)
    data = body()
    reason = opt_str(data, "cancellation_reason")
    if appt["status"] not in ("REQUESTED", "CONFIRMED"):
        raise_err(ERR_INVALID_STATE, "Appointment cannot be cancelled from its current state")
    appt["status"] = "CANCELLED"
    if reason is not None:
        appt["cancellation_reason"] = reason
    services.touch(appt)
    return ok_object(serialize(appt))
