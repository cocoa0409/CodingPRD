"""Restraint and seclusion episodes (PRD §3.6)."""

from datetime import timedelta

from flask import Blueprint

import calc
import cascades
import serializers
from auth import ANY_ROLE, ATTENDING_PSYCHIATRIST, CHARGE_NURSE, context
from envelope import list_response, object_response
from errors import fail
from store import base_row, db, ordered, touch
from validation import apply_filters, body, filters, pagination, vbool, venum, vint, vstr

bp = Blueprint("restraints", __name__)

INTERVENTION_TYPES = ("PHYSICAL_HOLD", "MECHANICAL_RESTRAINT", "SECLUSION")
CHECK_TYPES = ("CIRCULATION", "HYDRATION_OFFERED", "TOILETING", "VITALS")
FACE_TO_FACE_WINDOW_MINUTES = 60


def _require_episode(episode_id):
    row = db.restraints.get(episode_id)
    if row is None:
        fail("ERR_REFERENCED_RESOURCE_NOT_FOUND", "restraint episode not found")
    return row


def _unit_of(episode):
    admission = db.admissions.get(episode["admission_id"])
    if admission is None:
        return None
    return db.units.get(admission["unit_id"])


@bp.post("/behavioral-health/restraints")
def create_restraint():
    user_id, _role = context((ATTENDING_PSYCHIATRIST,))
    data = body()
    admission_id = vstr(data, "admission_id")
    intervention_type = venum(data, "intervention_type", INTERVENTION_TYPES)
    ordered_duration_minutes = vint(data, "ordered_duration_minutes", minimum=1)
    clinical_justification = vstr(data, "clinical_justification")

    admission = db.admissions.get(admission_id)
    if admission is None:
        fail("ERR_ADMISSION_NOT_FOUND", "admission not found")
    patient = db.patients.get(admission["patient_id"]) or {}
    ceiling = calc.restraint_duration_ceiling(bool(patient.get("is_minor")), intervention_type)
    if ordered_duration_minutes > ceiling:
        fail(
            "ERR_RESTRAINT_DURATION_EXCEEDS_LIMIT",
            f"ordered_duration_minutes exceeds the {ceiling} minute ceiling",
        )

    unit = db.units.get(admission["unit_id"])
    if intervention_type == "SECLUSION":
        licensed = unit["seclusion_room_count"] if unit is not None else 0
        if calc.live_seclusion_count(admission["unit_id"]) >= licensed:
            fail("ERR_SECLUSION_CAPACITY_EXCEEDED", "the unit has no free licensed seclusion room")

    started_at = db.now()
    row = base_row()
    row.update(
        {
            "admission_id": admission_id,
            "ordered_by_clinician_id": user_id,
            "face_to_face_clinician_id": None,
            "intervention_type": intervention_type,
            "ordered_duration_minutes": ordered_duration_minutes,
            "clinical_justification": clinical_justification,
            "started_at": started_at,
            "authorized_until_at": started_at + timedelta(minutes=ordered_duration_minutes),
            "face_to_face_deadline_at": started_at
            + timedelta(minutes=FACE_TO_FACE_WINDOW_MINUTES),
            "face_to_face_at": None,
            "released_at": None,
            "actual_duration_minutes": None,
            "monitoring_interval_minutes": calc.monitoring_interval_minutes(intervention_type),
            "required_check_count": None,
            "monitoring_check_log": [],
            "grid_satisfied_slot_count": None,
            "grid_compliance_pct": None,
            "raw_compliance_pct": None,
            "status": "ORDERED",
            "debrief_completed_at": None,
            "patient_participated_in_debrief": None,
            "staff_participants_count": None,
        }
    )
    db.restraints[row["id"]] = row
    if intervention_type == "SECLUSION":
        cascades.recompute_unit_by_id(admission["unit_id"], allow_promotion=False)
    return object_response(serializers.restraint(row), 201)


@bp.post("/behavioral-health/restraints/<episode_id>/face-to-face")
def face_to_face(episode_id):
    user_id, _role = context((ATTENDING_PSYCHIATRIST,))
    body()
    episode = _require_episode(episode_id)
    if episode["status"] != "ORDERED":
        fail("ERR_RESTRAINT_INVALID_STATE", "the episode is not in ORDERED")
    if (
        episode["intervention_type"] in ("MECHANICAL_RESTRAINT", "SECLUSION")
        and episode["ordered_by_clinician_id"] == user_id
    ):
        fail("ERR_SEGREGATION_OF_DUTIES", "the ordering clinician may not perform this review")
    if db.now() > episode["face_to_face_deadline_at"]:
        fail("ERR_FACE_TO_FACE_WINDOW_CLOSED", "the face-to-face window has closed")

    episode["status"] = "ACTIVE"
    episode["face_to_face_at"] = db.now()
    episode["face_to_face_clinician_id"] = user_id
    touch(episode)
    return object_response(serializers.restraint(episode))


@bp.post("/behavioral-health/restraints/<episode_id>/monitoring-checks")
def append_monitoring_check(episode_id):
    user_id, _role = context((CHARGE_NURSE,))
    data = body()
    check_type = venum(data, "check_type", CHECK_TYPES)
    note = vstr(data, "note", required=False, allow_empty=True)

    episode = _require_episode(episode_id)
    if episode["status"] not in ("ORDERED", "ACTIVE"):
        fail("ERR_RESTRAINT_INVALID_STATE", "the episode does not accept monitoring checks")

    episode["monitoring_check_log"].append(
        {
            "recorded_at": db.now(),
            "check_type": check_type,
            "recorded_by_clinician_id": user_id,
            "note": note,
        }
    )
    touch(episode)
    return object_response(serializers.restraint(episode))


@bp.post("/behavioral-health/restraints/<episode_id>/release")
def release_restraint(episode_id):
    context((CHARGE_NURSE, ATTENDING_PSYCHIATRIST))
    body()
    episode = _require_episode(episode_id)
    if episode["status"] != "ACTIVE":
        fail("ERR_RESTRAINT_INVALID_STATE", "only an ACTIVE episode may be released")

    released_at = db.now()
    elapsed = released_at - episode["started_at"]
    # Whole minutes with any partial minute discarded.
    actual = int(elapsed.total_seconds() // 60)
    if actual < 0:
        actual = 0
    cascades.finalize_episode(episode, released_at, actual, "RELEASED")

    admission = db.admissions.get(episode["admission_id"])
    if admission is not None:
        cascades.recompute_admission_staffing(admission)
        if episode["intervention_type"] == "SECLUSION":
            cascades.recompute_unit_by_id(admission["unit_id"], allow_promotion=False)
    return object_response(serializers.restraint(episode))


@bp.post("/behavioral-health/restraints/<episode_id>/debrief")
def debrief_restraint(episode_id):
    context((ATTENDING_PSYCHIATRIST, CHARGE_NURSE))
    data = body()
    participated = vbool(data, "patient_participated_in_debrief")
    staff_count = vint(data, "staff_participants_count", minimum=1)
    vstr(data, "debrief_note")

    episode = _require_episode(episode_id)
    if episode["status"] != "RELEASED":
        fail("ERR_RESTRAINT_INVALID_STATE", "only a RELEASED episode may be debriefed")
    if episode["grid_compliance_pct"] != 100.0:
        fail("ERR_MONITORING_INCOMPLETE", "interval-grid monitoring compliance is below 100.0")

    episode["status"] = "DEBRIEFED"
    episode["debrief_completed_at"] = db.now()
    episode["patient_participated_in_debrief"] = participated
    episode["staff_participants_count"] = staff_count
    touch(episode)
    return object_response(serializers.restraint(episode))


@bp.get("/behavioral-health/restraints/<episode_id>")
def get_restraint(episode_id):
    context(ANY_ROLE)
    return object_response(serializers.restraint(_require_episode(episode_id)))


@bp.get("/behavioral-health/restraints")
def list_restraints():
    context(ANY_ROLE)
    limit, offset = pagination()
    rows = apply_filters(
        list(db.restraints.values()),
        filters("admission_id", "ordered_by_clinician_id", "face_to_face_clinician_id", "status"),
    )
    rows = ordered(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_response([serializers.restraint(r) for r in page], limit, offset, total)


_ = _unit_of
