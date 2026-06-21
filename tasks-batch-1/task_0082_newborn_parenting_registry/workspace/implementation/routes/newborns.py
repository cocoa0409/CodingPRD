"""Newborn clinical lifecycle (PRD §3.3, §3.4, §3.8) + audit-event listing."""

from flask import Blueprint, request

import db
import services
from errors import (
    APIError,
    ERR_DISCHARGE_PREREQUISITE,
    ERR_NICU_CRITERIA_MET,
    ERR_NICU_CRITERIA_NOT_MET,
    ERR_NO_ACTIVE_NICU_STAY,
    ERR_READINESS_BELOW_THRESHOLD,
    invalid_request,
    invalid_state,
    not_found,
    stale_version,
)
from helpers import (
    get_body,
    optional_field,
    paginate,
    parse_pagination,
    require_enum,
    require_field,
    sort_created_at_asc,
)
from middleware import require_roles
from response import ok_array, ok_object
from services import ACUITY_ORDER

bp = Blueprint("newborns", __name__)

REQUIRED_LEVELS = {"LEVEL_2", "LEVEL_3", "LEVEL_4"}
AUDIT_EVENT_TYPES = {
    "BIRTH_RECORDED", "NICU_ESCALATED", "NICU_BED_ASSIGNED", "STEP_DOWN",
    "DISCHARGED", "BAG_ISSUED", "DEPENDENT_ENROLLED", "SEP_EXPIRED",
    "FILING_SUBMITTED", "FILING_LATE_FLAGGED", "FOLLOWUP_ESCALATED",
}


def _get_newborn(newborn_id):
    n = db.newborns.get(newborn_id)
    if n is None:
        raise not_found("Newborn not found.")
    return n


@bp.get("/newborns/<newborn_id>")
def get_newborn(newborn_id):
    require_roles("AttendingNurse", "Neonatologist", "BenefitsCoordinator",
                  "VitalRecordsOfficer", "RegistrySupervisor")
    n = _get_newborn(newborn_id)
    services.refresh_readiness(n)
    return ok_object(db.public(n))


@bp.patch("/newborns/<newborn_id>")
def patch_newborn(newborn_id):
    require_roles("AttendingNurse", "VitalRecordsOfficer")
    n = _get_newborn(newborn_id)
    body = get_body()
    changed = False
    if "legal_name" in body:
        legal_name = optional_field(body, "legal_name", str, default=None)
        n["legal_name"] = legal_name
        changed = True
    if changed:
        db.stamp_update(n)
    services.refresh_readiness(n)
    return ok_object(db.public(n))


@bp.post("/newborns/<newborn_id>/room-in")
def room_in(newborn_id):
    require_roles("AttendingNurse")
    n = _get_newborn(newborn_id)
    if n["clinical_status"] != "BORN":
        raise invalid_state("Room-in requires clinical_status == BORN.")
    if services.meets_nicu_criteria(n):
        raise APIError(ERR_NICU_CRITERIA_MET,
                       "Newborn meets NICU clinical criteria and must be escalated.", 422)
    n["clinical_status"] = "ROOMING_IN"
    n["care_location"] = "MOTHER_ROOM"
    db.stamp_update(n)
    services.refresh_readiness(n)
    return ok_object(db.public(n))


@bp.post("/newborns/<newborn_id>/nicu-escalate")
def nicu_escalate(newborn_id):
    require_roles("Neonatologist")
    n = _get_newborn(newborn_id)
    body = get_body()
    required_level = require_field(body, "required_level", str)
    require_enum(required_level, "required_level", REQUIRED_LEVELS)
    admitted_at = require_field(body, "admitted_at", str)
    try:
        db.parse_iso(admitted_at)
    except ValueError as e:
        raise invalid_request(str(e))
    expected_newborn_version = require_field(body, "expected_newborn_version", int)

    # State first (priority 5): escalation defined from BORN or ROOMING_IN.
    if n["clinical_status"] not in ("BORN", "ROOMING_IN"):
        raise invalid_state("Escalation requires clinical_status BORN or ROOMING_IN.")

    # OCC (priority 6).
    if expected_newborn_version != n["version"]:
        raise stale_version("expected_newborn_version does not match the newborn's version.")

    # Business safety (priority 7): from BORN, the infant must meet criteria.
    if n["clinical_status"] == "BORN" and not services.meets_nicu_criteria(n):
        raise APIError(ERR_NICU_CRITERIA_NOT_MET,
                       "Newborn does not meet NICU clinical criteria.", 422)

    # Create the stay in PENDING_BED, then run the bed selector.
    stay = {
        "id": db.new_id(),
        "newborn_id": newborn_id,
        "nicu_bed_id": None,
        "required_level": required_level,
        "admitted_at": admitted_at,
        "discharged_at": None,
        "status": "PENDING_BED",
    }
    db.stamp_create(stay)
    db.nicu_stays[stay["id"]] = stay

    actor = request.headers.get("X-User-Role")
    services.append_audit("NICU_ESCALATED", actor, newborn_id,
                          {"nicu_stay_id": stay["id"], "required_level": required_level})

    bed = services.select_bed_for_stay(required_level)
    if bed is not None:
        services.occupy_bed(bed, stay)
        services.append_audit("NICU_BED_ASSIGNED", actor, newborn_id,
                              {"nicu_stay_id": stay["id"], "nicu_bed_id": bed["id"]})

    n["clinical_status"] = "NICU_ADMITTED"
    n["care_location"] = "NICU"
    db.stamp_update(n)
    services.refresh_readiness(n)

    return ok_object(db.public(stay), 201)


@bp.post("/newborns/<newborn_id>/step-down")
def step_down(newborn_id):
    require_roles("Neonatologist")
    n = _get_newborn(newborn_id)
    if n["clinical_status"] != "NICU_ADMITTED":
        raise invalid_state("Step-down requires clinical_status == NICU_ADMITTED.")
    stay = services.active_nicu_stay(newborn_id)
    if stay is None:
        raise APIError(ERR_NO_ACTIVE_NICU_STAY,
                       "Newborn has no ACTIVE (bedded) NICU stay to step down.", 422)

    actor = request.headers.get("X-User-Role")
    bed = db.nicu_beds.get(stay["nicu_bed_id"])

    # Close the stay, stamp its discharged_at.
    stay["status"] = "STEPPED_DOWN"
    stay["discharged_at"] = db.current_utc_iso()
    db.stamp_update(stay)

    # Free the bed.
    if bed is not None:
        bed["occupancy_status"] = "VACANT"
        bed["current_stay_id"] = None
        db.stamp_update(bed)

        # Promote the longest-waiting eligible PENDING_BED stay onto the freed bed.
        bed_acuity = ACUITY_ORDER[bed["acuity_level"]]
        waiting = [
            s for s in db.nicu_stays.values()
            if s["status"] == "PENDING_BED"
            and ACUITY_ORDER[s["required_level"]] <= bed_acuity
        ]
        if waiting:
            waiting.sort(key=lambda s: (db.parse_iso(s["admitted_at"]),
                                        s.get("created_at", ""), s.get("_seq", 0)))
            promoted = waiting[0]
            services.occupy_bed(bed, promoted)
            services.append_audit("NICU_BED_ASSIGNED", actor, promoted["newborn_id"],
                                  {"nicu_stay_id": promoted["id"], "nicu_bed_id": bed["id"]})

    n["clinical_status"] = "STEP_DOWN"
    n["care_location"] = "STEP_DOWN_UNIT"
    db.stamp_update(n)
    services.refresh_readiness(n)
    services.append_audit("STEP_DOWN", actor, newborn_id, {"nicu_stay_id": stay["id"]})

    return ok_object(db.public(n))


@bp.post("/newborns/<newborn_id>/mark-discharge-ready")
def mark_discharge_ready(newborn_id):
    require_roles("AttendingNurse")
    n = _get_newborn(newborn_id)
    if n["clinical_status"] not in ("ROOMING_IN", "STEP_DOWN"):
        raise invalid_state("Mark-discharge-ready requires ROOMING_IN or STEP_DOWN.")
    # From STEP_DOWN, the newborn must have no open stay.
    if n["clinical_status"] == "STEP_DOWN" and services.open_nicu_stays(newborn_id):
        raise invalid_state("Newborn still has an open NICU stay.")
    score = services.compute_discharge_readiness(n)
    n["discharge_readiness_score"] = score
    if score < 70:
        raise APIError(ERR_READINESS_BELOW_THRESHOLD,
                       "Recomputed discharge_readiness_score is below 70.", 422)
    n["clinical_status"] = "DISCHARGE_READY"
    db.stamp_update(n)
    return ok_object(db.public(n))


@bp.post("/newborns/<newborn_id>/discharge")
def discharge(newborn_id):
    require_roles("AttendingNurse")
    n = _get_newborn(newborn_id)
    if n["clinical_status"] != "DISCHARGE_READY":
        raise invalid_state("Discharge requires clinical_status == DISCHARGE_READY.")

    # Prerequisite (priority 10): exactly one ISSUED bag AND a SUBMITTED/ACCEPTED
    # BIRTH_CERTIFICATE filing.
    issued_bags = [
        b for b in db.discharge_bags.values()
        if b["newborn_id"] == newborn_id and b["status"] == "ISSUED"
    ]
    has_birth_cert = any(
        f["newborn_id"] == newborn_id
        and f["filing_type"] == "BIRTH_CERTIFICATE"
        and f["status"] in ("SUBMITTED", "ACCEPTED")
        for f in db.government_filings.values()
    )
    if len(issued_bags) != 1 or not has_birth_cert:
        raise APIError(ERR_DISCHARGE_PREREQUISITE,
                       "Discharge requires exactly one ISSUED bag and a "
                       "SUBMITTED/ACCEPTED birth-certificate filing.", 422)

    actor = request.headers.get("X-User-Role")
    n["clinical_status"] = "DISCHARGED"
    n["care_location"] = "RELEASED"
    n["discharged_at"] = db.current_utc_iso()
    db.stamp_update(n)
    services.refresh_readiness(n)

    # Close any STEPPED_DOWN stay (no further bed effects).
    for s in db.nicu_stays.values():
        if s["newborn_id"] == newborn_id and s["status"] == "STEPPED_DOWN":
            s["status"] = "CLOSED"
            db.stamp_update(s)

    # Spawn four FollowUpTasks in OPEN with computed due_at.
    for task_type in ("WEIGHT_CHECK", "JAUNDICE_CHECK", "FEEDING_CHECK", "SAFETY_CALL"):
        task = {
            "id": db.new_id(),
            "newborn_id": newborn_id,
            "task_type": task_type,
            "due_at": services.compute_followup_due(n["discharged_at"], task_type),
            "scheduled_at": None,
            "attempt_count": 0,
            "status": "OPEN",
        }
        db.stamp_create(task)
        db.follow_up_tasks[task["id"]] = task

    services.append_audit("DISCHARGED", actor, newborn_id,
                          {"discharged_at": n["discharged_at"]})
    return ok_object(db.public(n))


@bp.get("/newborns/<newborn_id>/audit-events")
def list_audit_events(newborn_id):
    require_roles("RegistrySupervisor", "AttendingNurse", "Neonatologist")
    _get_newborn(newborn_id)
    limit, offset = parse_pagination()
    event_type = request.args.get("event_type")
    rows = [e for e in db.audit_events.values() if e["newborn_id"] == newborn_id]
    if event_type is not None:
        require_enum(event_type, "event_type", AUDIT_EVENT_TYPES)
        rows = [r for r in rows if r["event_type"] == event_type]
    rows = sort_created_at_asc(rows)
    page, total, has_more = paginate(rows, limit, offset)
    return ok_array([db.public(r) for r in page], limit=limit, offset=offset,
                    total_count=total, has_more=has_more)
