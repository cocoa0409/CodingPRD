"""Admissions, the safety search, placement, discharge planning and discharge (PRD §3.5, §3.8)."""

from flask import Blueprint

import calc
import cascades
import serializers
from auth import (
    ANY_ROLE,
    ATTENDING_PSYCHIATRIST,
    CHARGE_NURSE,
    INTAKE_CLINICIAN,
    RIGHTS_ADVOCATE_ROLE,
    context,
)
from envelope import list_response, object_response
from errors import fail
from store import base_row, db, ordered, touch
from validation import (
    apply_filters,
    body,
    filters,
    pagination,
    vbool,
    vdt,
    venum,
    vint,
    vstr,
)

bp = Blueprint("admissions", __name__)

LEGAL_STATUSES = ("VOLUNTARY", "INVOLUNTARY")
SEARCH_TYPES = ("VISUAL", "WANDED", "FULL_BODY_WITH_CONSENT")
SEARCH_OUTCOMES = ("COMPLETED", "REFUSED")
REQUESTED_BY = ("PATIENT", "GUARDIAN")
DECISIONS = ("GRANT", "DENY")
OPEN_PETITION_STATES = ("FILED", "HEARING_SCHEDULED", "CONTINUED")
ACTIVE_PLACEMENT_STATES = ("PENDING_PLACEMENT", "PLACED")
DISCHARGEABLE_STATES = ("PLACED", "DISCHARGE_READY")
OPEN_EPISODE_STATES = ("ORDERED", "ACTIVE", "RELEASED")


def _patient_active_hold(patient_id):
    for hold in ordered(list(db.holds.values())):
        if hold["patient_id"] == patient_id and hold["status"] == "ACTIVE":
            return hold
    return None


def _active_capacity_determination(admission_id):
    for row in ordered(list(db.capacity_determinations.values())):
        if row["admission_id"] == admission_id and row["status"] == "ACTIVE":
            return row
    return None


def _require_admission(admission_id):
    row = db.admissions.get(admission_id)
    if row is None:
        fail("ERR_ADMISSION_NOT_FOUND", "admission not found")
    return row


# --------------------------------------------------------------------------- #
# Admission creation and reads
# --------------------------------------------------------------------------- #
@bp.post("/behavioral-health/admissions")
def create_admission():
    user_id, _role = context((INTAKE_CLINICIAN,))
    data = body()
    patient_id = vstr(data, "patient_id")
    evaluation_id = vstr(data, "evaluation_id")
    unit_id = vstr(data, "unit_id")
    requested_legal_status = venum(data, "requested_legal_status", LEGAL_STATUSES)

    patient = db.patients.get(patient_id)
    if patient is None:
        fail("ERR_PATIENT_NOT_FOUND", "patient not found")
    unit = db.units.get(unit_id)
    if unit is None:
        fail("ERR_UNIT_NOT_FOUND", "unit not found")
    evaluation = db.evaluations.get(evaluation_id)
    if evaluation is None:
        fail("ERR_EVALUATION_NOT_FOUND", "evaluation not found")
    if evaluation["status"] != "SIGNED":
        fail("ERR_EVALUATION_NOT_SIGNED", "the anchoring evaluation is not signed")
    if evaluation["recommended_status"] not in ("VOLUNTARY", "INVOLUNTARY_HOLD"):
        fail("ERR_CLINICAL_CRITERIA_NOT_MET", "the evaluation does not support an admission")
    if requested_legal_status == "INVOLUNTARY" and _patient_active_hold(patient_id) is None:
        fail("ERR_NO_ACTIVE_HOLD", "an involuntary admission requires an ACTIVE hold")

    row = base_row()
    row.update(
        {
            "patient_id": patient_id,
            "evaluation_id": evaluation_id,
            "unit_id": unit_id,
            "bed_id": None,
            "admitting_clinician_id": user_id,
            "search_performed_by_clinician_id": None,
            "search_witness_clinician_id": None,
            "legal_status": requested_legal_status,
            "placement_status": "PENDING_PLACEMENT",
            "acuity_tier": evaluation["acuity_tier"],
            "admitted_at": db.now(),
            "placed_at": None,
            "discharged_at": None,
            "safety_search_status": "PENDING",
            "search_type": None,
            "search_items_secured_count": 0,
            "contraband_found": False,
            "capacity_present": None,
            "discharge_plan_status": "NOT_STARTED",
            "follow_up_provider_name": None,
            "follow_up_appointment_at": None,
            "follow_up_guarantee_days": None,
            "follow_up_guarantee_deadline_at": None,
            "observation_staff_quarter_hours": 0,
            "rights_violation_flag": False,
            "discharge_summary": None,
        }
    )
    db.admissions[row["id"]] = row
    return object_response(serializers.admission(row), 201)


@bp.get("/behavioral-health/admissions/<admission_id>")
def get_admission(admission_id):
    context(ANY_ROLE)
    return object_response(serializers.admission(_require_admission(admission_id)))


@bp.get("/behavioral-health/admissions")
def list_admissions():
    context(ANY_ROLE)
    limit, offset = pagination()
    rows = apply_filters(
        list(db.admissions.values()),
        filters(
            "patient_id",
            "unit_id",
            "bed_id",
            "evaluation_id",
            "admitting_clinician_id",
            "search_performed_by_clinician_id",
            "search_witness_clinician_id",
            "legal_status",
            "placement_status",
        ),
    )
    rows = ordered(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_response([serializers.admission(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------- #
# Safety search
# --------------------------------------------------------------------------- #
@bp.post("/behavioral-health/admissions/<admission_id>/safety-search")
def safety_search(admission_id):
    user_id, _role = context((CHARGE_NURSE, INTAKE_CLINICIAN))
    data = body()
    search_type = venum(data, "search_type", SEARCH_TYPES)
    witness_id = vstr(data, "search_witness_clinician_id")
    items_secured = vint(data, "search_items_secured_count", required=False, minimum=0, default=0)
    contraband_found = vbool(data, "contraband_found", required=False, default=False)
    outcome = venum(data, "outcome", SEARCH_OUTCOMES)

    admission = _require_admission(admission_id)
    if db.clinicians.get(witness_id) is None:
        fail("ERR_REFERENCED_RESOURCE_NOT_FOUND", "search witness clinician not found")
    if admission["placement_status"] not in ACTIVE_PLACEMENT_STATES:
        fail("ERR_ADMISSION_NOT_DISCHARGEABLE", "the admission is not in an active placement state")
    if witness_id == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES", "the search witness must differ from the performer")

    admission["search_type"] = search_type
    admission["search_witness_clinician_id"] = witness_id
    admission["search_items_secured_count"] = items_secured
    admission["contraband_found"] = contraband_found
    admission["search_performed_by_clinician_id"] = user_id
    admission["safety_search_status"] = "COMPLETED" if outcome == "COMPLETED" else "REFUSED"
    touch(admission)
    return object_response(serializers.admission(admission))


# --------------------------------------------------------------------------- #
# Placement
# --------------------------------------------------------------------------- #
def _posture_admits(unit, admission, role, override_reason):
    posture = unit["posture"]
    if posture == "CLOSED":
        return False
    if posture == "RESTRICTED":
        return bool(
            override_reason
            and role == ATTENDING_PSYCHIATRIST
            and admission["acuity_tier"] == "HIGH"
        )
    return unit["effective_available_bed_count"] >= 1


@bp.post("/behavioral-health/admissions/<admission_id>/place")
def place_admission(admission_id):
    _user_id, role = context((CHARGE_NURSE, ATTENDING_PSYCHIATRIST))
    data = body()
    if data.get("posture_override_reason") is not None and role != ATTENDING_PSYCHIATRIST:
        fail("ERR_UNAUTHORIZED", "only an AttendingPsychiatrist may supply posture_override_reason")

    unit_id = vstr(data, "unit_id")
    expected_unit_version = vint(data, "expected_unit_version")
    bed_id = vstr(data, "bed_id", required=False)
    override_reason = vstr(data, "posture_override_reason", required=False)

    unit = db.units.get(unit_id)
    if unit is None:
        fail("ERR_UNIT_NOT_FOUND", "unit not found")
    admission = _require_admission(admission_id)
    bed = None
    if bed_id is not None:
        bed = db.beds.get(bed_id)
        if bed is None:
            fail("ERR_REFERENCED_RESOURCE_NOT_FOUND", "bed not found")
    if expected_unit_version != unit["version"]:
        fail("ERR_STALE_UNIT_VERSION", "expected_unit_version does not match the unit's version")
    if admission["placement_status"] != "PENDING_PLACEMENT":
        fail("ERR_ADMISSION_NOT_PLACEABLE", "the admission is not pending placement")
    if admission["safety_search_status"] != "COMPLETED":
        fail("ERR_SAFETY_SEARCH_INCOMPLETE", "the safety search is not COMPLETED")

    patient = db.patients.get(admission["patient_id"]) or {}
    if bed is not None:
        if bed["unit_id"] == unit_id and not calc.cohort_ok(unit, bed, patient):
            fail("ERR_ROOM_COHORT_VIOLATION", "the target bed breaches a cohort rule")
        if (
            bed["unit_id"] != unit_id
            or bed["status"] != "AVAILABLE"
            or not calc.bed_type_ok(bed, admission)
        ):
            fail("ERR_BED_NOT_ELIGIBLE", "the named bed is not eligible for this admission")

    if not _posture_admits(unit, admission, role, override_reason):
        fail("ERR_UNIT_POSTURE_BLOCKED", "the unit's posture does not admit this placement")

    if bed is None:
        bed = calc.select_bed(unit, admission, patient)
        if bed is None:
            fail("ERR_NO_ELIGIBLE_BED", "no eligible bed is available on this unit")

    cascades.occupy_bed(admission, bed)
    cascades.recompute_unit(unit, allow_promotion=False)
    return object_response(serializers.admission(admission))


# --------------------------------------------------------------------------- #
# Voluntary conversion
# --------------------------------------------------------------------------- #
@bp.post("/behavioral-health/admissions/<admission_id>/convert-to-voluntary")
def convert_to_voluntary(admission_id):
    context((ATTENDING_PSYCHIATRIST,))
    data = body()
    conversion_note = vstr(data, "conversion_note")

    admission = _require_admission(admission_id)
    hold = _patient_active_hold(admission["patient_id"])
    if hold is None:
        fail("ERR_HOLD_NOT_ACTIVE", "the patient has no ACTIVE hold to convert")
    if admission["placement_status"] not in ACTIVE_PLACEMENT_STATES:
        fail("ERR_ADMISSION_NOT_DISCHARGEABLE", "the admission is not in an active placement state")
    determination = _active_capacity_determination(admission_id)
    if determination is None or not determination["capacity_present"]:
        fail("ERR_CAPACITY_LACKING", "an ACTIVE determination of present capacity is required")
    if any(
        p["hold_id"] == hold["id"] and p["status"] in OPEN_PETITION_STATES
        for p in db.petitions.values()
    ):
        fail("ERR_PETITION_PENDING", "an open petition blocks a bedside conversion")

    hold["status"] = "CONVERTED_VOLUNTARY"
    hold["closure_reason"] = conversion_note
    touch(hold)
    patient = db.patients.get(admission["patient_id"])
    if patient is not None:
        cascades.recompute_patient_hold_count(patient)
    admission["legal_status"] = "VOLUNTARY"
    touch(admission)
    return object_response(serializers.admission(admission))


# --------------------------------------------------------------------------- #
# Discharge planning
# --------------------------------------------------------------------------- #
@bp.post("/behavioral-health/admissions/<admission_id>/discharge-plan")
def discharge_plan(admission_id):
    context((ATTENDING_PSYCHIATRIST, CHARGE_NURSE))
    data = body()
    provider_name = vstr(data, "follow_up_provider_name")
    appointment_at = vdt(data, "follow_up_appointment_at")

    admission = _require_admission(admission_id)
    if admission["placement_status"] not in ACTIVE_PLACEMENT_STATES:
        fail("ERR_ADMISSION_NOT_DISCHARGEABLE", "the admission is not in an active placement state")

    patient = db.patients.get(admission["patient_id"]) or {}
    now = db.now()
    days = calc.follow_up_guarantee_days(admission, patient)
    deadline = calc.follow_up_guarantee_deadline(now, days)
    if appointment_at <= now or appointment_at > deadline:
        fail("ERR_FOLLOW_UP_WINDOW_EXCEEDED", "the appointment falls outside the guarantee window")

    admission["follow_up_provider_name"] = provider_name
    admission["follow_up_appointment_at"] = appointment_at
    admission["follow_up_guarantee_days"] = days
    admission["follow_up_guarantee_deadline_at"] = deadline
    admission["discharge_plan_status"] = "APPOINTMENT_SECURED"
    touch(admission)
    return object_response(serializers.admission(admission))


# --------------------------------------------------------------------------- #
# Physical discharge
# --------------------------------------------------------------------------- #
@bp.post("/behavioral-health/admissions/<admission_id>/discharge")
def discharge_admission(admission_id):
    context((ATTENDING_PSYCHIATRIST,))
    data = body()
    discharge_summary = vstr(data, "discharge_summary")

    admission = _require_admission(admission_id)
    if admission["placement_status"] not in DISCHARGEABLE_STATES:
        fail("ERR_ADMISSION_NOT_DISCHARGEABLE", "the admission is not dischargeable")
    if any(
        e["admission_id"] == admission_id and e["status"] in OPEN_EPISODE_STATES
        for e in db.restraints.values()
    ):
        fail("ERR_OPEN_RESTRAINT_EPISODE", "an unresolved restraint episode blocks discharge")
    if admission["legal_status"] != "VOLUNTARY":
        fail("ERR_ACTIVE_HOLD_BLOCKS_DISCHARGE", "an involuntary admission may not be discharged")
    if admission["discharge_plan_status"] != "APPOINTMENT_SECURED" or (
        admission["follow_up_appointment_at"] is None
        or admission["follow_up_appointment_at"] <= db.now()
    ):
        fail("ERR_DISCHARGE_PLAN_INCOMPLETE", "the discharge plan is missing or stale")

    admission["placement_status"] = "DISCHARGED"
    admission["discharged_at"] = db.now()
    admission["discharge_summary"] = discharge_summary
    touch(admission)

    bed = db.beds.get(admission["bed_id"]) if admission["bed_id"] else None
    unit_id = bed["unit_id"] if bed is not None else admission["unit_id"]
    if bed is not None and bed["status"] == "OCCUPIED":
        bed["status"] = "AVAILABLE"
        touch(bed)
    cascades.recompute_unit_by_id(unit_id)
    return object_response(serializers.admission(admission))


# --------------------------------------------------------------------------- #
# Discharge requests
# --------------------------------------------------------------------------- #
@bp.post("/behavioral-health/discharge-requests")
def create_discharge_request():
    user_id, _role = context((CHARGE_NURSE, RIGHTS_ADVOCATE_ROLE))
    data = body()
    admission_id = vstr(data, "admission_id")
    requested_by = venum(data, "requested_by", REQUESTED_BY)

    admission = _require_admission(admission_id)
    if admission["placement_status"] not in ACTIVE_PLACEMENT_STATES:
        fail("ERR_ADMISSION_NOT_DISCHARGEABLE", "the admission is not in an active placement state")
    if any(
        d["admission_id"] == admission_id and d["status"] == "PENDING"
        for d in db.discharge_requests.values()
    ):
        fail("ERR_DUPLICATE_DISCHARGE_REQUEST", "a discharge request for this admission is pending")

    requested_at = db.now()
    row = base_row()
    row.update(
        {
            "admission_id": admission_id,
            "recorded_by_clinician_id": user_id,
            "responding_clinician_id": None,
            "requested_by": requested_by,
            "requested_at": requested_at,
            "response_deadline_at": calc.discharge_request_response_deadline(requested_at),
            "decision": "PENDING",
            "status": "PENDING",
            "response_note": None,
        }
    )
    db.discharge_requests[row["id"]] = row
    return object_response(serializers.discharge_request(row), 201)


@bp.post("/behavioral-health/discharge-requests/<request_id>/respond")
def respond_discharge_request(request_id):
    user_id, _role = context((ATTENDING_PSYCHIATRIST,))
    data = body()
    decision = venum(data, "decision", DECISIONS)
    response_note = vstr(data, "response_note")

    row = db.discharge_requests.get(request_id)
    if row is None:
        fail("ERR_REFERENCED_RESOURCE_NOT_FOUND", "discharge request not found")
    if row["status"] != "PENDING":
        fail("ERR_DISCHARGE_REQUEST_NOT_PENDING", "the discharge request is not pending")

    admission = db.admissions.get(row["admission_id"])
    if decision == "DENY":
        if admission is None or _patient_active_hold(admission["patient_id"]) is None:
            fail("ERR_NO_ACTIVE_HOLD", "a denial requires the patient to be under an ACTIVE hold")
    else:
        if admission is None or admission["legal_status"] != "VOLUNTARY":
            fail(
                "ERR_ACTIVE_HOLD_BLOCKS_DISCHARGE",
                "release may not be granted while the patient is held involuntarily",
            )

    row["decision"] = decision
    row["response_note"] = response_note
    row["responding_clinician_id"] = user_id
    row["status"] = "GRANTED_DISCHARGE" if decision == "GRANT" else "DENIED_HOLD_INITIATED"
    touch(row)
    if decision == "GRANT":
        cascades.advance_placement_on_grant(admission)
    return object_response(serializers.discharge_request(row))


@bp.get("/behavioral-health/discharge-requests/<request_id>")
def get_discharge_request(request_id):
    context(ANY_ROLE)
    row = db.discharge_requests.get(request_id)
    if row is None:
        fail("ERR_REFERENCED_RESOURCE_NOT_FOUND", "discharge request not found")
    return object_response(serializers.discharge_request(row))


@bp.get("/behavioral-health/discharge-requests")
def list_discharge_requests():
    context(ANY_ROLE)
    limit, offset = pagination()
    rows = apply_filters(
        list(db.discharge_requests.values()),
        filters("admission_id", "recorded_by_clinician_id", "responding_clinician_id", "status"),
    )
    rows = ordered(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_response([serializers.discharge_request(r) for r in page], limit, offset, total)
