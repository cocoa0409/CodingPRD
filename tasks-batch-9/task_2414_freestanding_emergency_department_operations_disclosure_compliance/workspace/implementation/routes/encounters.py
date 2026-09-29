"""Registration, the disclosure decision, screening, observation, discharge and
ancillary orders."""

from datetime import timedelta

from flask import Blueprint

import constants as C
from db import base_row, db, touch
from domain import (
    ancillary_view,
    append_ledger,
    code_in_scope,
    disclosed_estimate_cents,
    effective_posture,
    effective_restricted_codes,
    encounter_view,
    fire_disclosure_defect,
    get_ancillary,
    get_encounter,
    get_facility,
    observation_beds_occupied,
    record_defect,
    rows_of,
)
from errors import ApiError
from response import created, ok, ok_list, paginate
from validate import (
    auth,
    body,
    pagination,
    query_enum,
    query_str,
    req_bool,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("encounters", __name__)

READ_ROLES = (
    "FacilityAdministrator",
    "ComplianceOfficer",
    "RegistrationClerk",
    "EmergencyPhysician",
)
ANCILLARY_READ_ROLES = ("EmergencyPhysician", "ComplianceOfficer", "FacilityAdministrator")


# --- registration ---------------------------------------------------------


@bp.post("/facilities/<fid>/encounters")
def register_encounter(fid):
    user_id, _ = auth("RegistrationClerk")
    data = body()
    patient_reference = req_str(data, "patient_reference", 1, 64)
    acuity_level = req_int(data, "acuity_level", minimum=1, maximum=5)
    service_line = req_enum(data, "presenting_service_line", C.SERVICE_LINES)

    facility = get_facility(fid)

    if effective_posture(facility) == "SUSPENDED":
        raise ApiError("ERR_FACILITY_POSTURE_BLOCKED")
    template_id = facility["current_published_template_id"]
    if template_id is None:
        raise ApiError("ERR_NO_PUBLISHED_DISCLOSURE")
    template = db.templates[template_id]

    arrival_at = db.clock
    encounter = base_row()
    encounter.update(
        {
            "facility_id": facility["id"],
            "pinned_disclosure_template_id": template["id"],
            "patient_reference": patient_reference,
            "acuity_level": acuity_level,
            "presenting_service_line": service_line,
            "arrival_at": arrival_at,
            "registered_by_user_id": user_id,
            "clinical_state": "ARRIVED",
            "disclosure_state": "DISCLOSURE_PRESENTED",
            "disclosure_decided_by_user_id": None,
            "disclosed_estimate_cents": disclosed_estimate_cents(template, acuity_level),
            "mse_start_deadline_at": arrival_at
            + timedelta(minutes=C.MSE_START_DEADLINE_MINUTES),
            "mse_started_at": None,
            "mse_completed_at": None,
            "mse_physician_user_id": None,
            "mse_timeliness": "PENDING",
            "stabilization_status": "NOT_ASSESSED",
            "observation_bed_held": False,
            "observation_started_at": None,
        }
    )
    db.encounters[encounter["id"]] = encounter

    append_ledger(
        facility,
        "DISCLOSURE_PRESENTED",
        "INFO",
        "ENCOUNTER",
        encounter["id"],
        "Patient-facing disclosure presented at registration.",
        defect_counted=False,
    )
    return created(encounter_view(encounter))


@bp.get("/encounters/<eid>")
def read_encounter(eid):
    auth(*READ_ROLES)
    return ok(encounter_view(get_encounter(eid)))


@bp.get("/encounters")
def list_encounters():
    auth(*READ_ROLES)
    facility_id = query_str("facility_id")
    template_id = query_str("pinned_disclosure_template_id")
    clinical_state = query_enum("clinical_state", C.CLINICAL_STATES)
    disclosure_state = query_enum("disclosure_state", C.DISCLOSURE_STATES)
    limit, offset = pagination()

    rows = rows_of(db.encounters)
    if facility_id is not None:
        rows = [r for r in rows if r["facility_id"] == facility_id]
    if template_id is not None:
        rows = [r for r in rows if r["pinned_disclosure_template_id"] == template_id]
    if clinical_state is not None:
        rows = [r for r in rows if r["clinical_state"] == clinical_state]
    if disclosure_state is not None:
        rows = [r for r in rows if r["disclosure_state"] == disclosure_state]
    page = paginate(rows, limit, offset)
    return ok_list([encounter_view(r) for r in page], limit, offset, len(rows))


# --- disclosure dimension -------------------------------------------------


@bp.post("/encounters/<eid>/disclosure-decision")
def record_disclosure_decision(eid):
    user_id, _ = auth("RegistrationClerk")
    data = body()
    decision = req_enum(data, "decision", C.DISCLOSURE_DECISIONS)
    req_str(data, "waiver_reason", 1, 500, required=False)

    encounter = get_encounter(eid)
    facility = db.facilities[encounter["facility_id"]]

    if encounter["disclosure_state"] != "DISCLOSURE_PRESENTED":
        raise ApiError("ERR_DISCLOSURE_DECISION_ALREADY_RECORDED")
    if decision == "EMERGENT_WAIVER":
        if user_id == encounter["registered_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        if encounter["acuity_level"] < C.EMERGENT_WAIVER_MIN_ACUITY:
            raise ApiError("ERR_WAIVER_NOT_EMERGENT")

    encounter["disclosure_decided_by_user_id"] = user_id
    if decision == "ACKNOWLEDGED":
        encounter["disclosure_state"] = "DISCLOSURE_ACKNOWLEDGED"
        touch(encounter)
        append_ledger(
            facility,
            "DISCLOSURE_ACKNOWLEDGED",
            "INFO",
            "ENCOUNTER",
            encounter["id"],
            "Patient acknowledged the facility-fee and network-status disclosure.",
            defect_counted=False,
        )
    elif decision == "EMERGENT_WAIVER":
        encounter["disclosure_state"] = "DISCLOSURE_WAIVED_EMERGENT"
        touch(encounter)
        append_ledger(
            facility,
            "EMERGENT_WAIVER_RECORDED",
            "INFO",
            "ENCOUNTER",
            encounter["id"],
            "Emergent waiver recorded for a high-acuity presentation.",
            defect_counted=False,
        )
    else:
        encounter["disclosure_state"] = "DISCLOSURE_REFUSED"
        touch(encounter)
        record_defect(
            facility,
            "DISCLOSURE_REFUSED",
            "MAJOR",
            "ENCOUNTER",
            encounter["id"],
            "Patient refused to acknowledge the facility-fee disclosure.",
        )
    return ok(encounter_view(encounter))


# --- clinical dimension ---------------------------------------------------


@bp.post("/encounters/<eid>/begin-mse")
def begin_mse(eid):
    user_id, _ = auth("EmergencyPhysician")
    data = body()
    req_str(data, "screening_note", 1, 1000, required=False)

    encounter = get_encounter(eid)
    facility = db.facilities[encounter["facility_id"]]

    if encounter["clinical_state"] != "ARRIVED":
        raise ApiError("ERR_INVALID_ENCOUNTER_STATE")

    started_at = db.clock
    encounter["clinical_state"] = "MSE_IN_PROGRESS"
    encounter["mse_started_at"] = started_at
    encounter["mse_physician_user_id"] = user_id
    late = started_at > encounter["mse_start_deadline_at"]
    encounter["mse_timeliness"] = "LATE" if late else "ON_TIME"
    touch(encounter)

    if late:
        record_defect(
            facility,
            "SCREENING_DELAY",
            "MAJOR",
            "ENCOUNTER",
            encounter["id"],
            "Medical screening examination began after the statutory deadline.",
        )
    return ok(encounter_view(encounter))


@bp.post("/encounters/<eid>/complete-mse")
def complete_mse(eid):
    auth("EmergencyPhysician")
    data = body()
    stabilization_status = req_enum(data, "stabilization_status", C.STABILIZATION_STATUSES)
    if stabilization_status == "NOT_ASSESSED":
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'stabilization_status' must be STABLE or UNSTABLE",
        )

    encounter = get_encounter(eid)
    if encounter["clinical_state"] != "MSE_IN_PROGRESS":
        raise ApiError("ERR_INVALID_ENCOUNTER_STATE")

    encounter["clinical_state"] = "MSE_COMPLETE"
    encounter["mse_completed_at"] = db.clock
    encounter["stabilization_status"] = stabilization_status
    touch(encounter)
    return ok(encounter_view(encounter))


@bp.post("/encounters/<eid>/observation")
def admit_observation(eid):
    auth("EmergencyPhysician")
    data = body()
    req_str(data, "observation_plan_note", 1, 1000, required=False)

    encounter = get_encounter(eid)
    facility = db.facilities[encounter["facility_id"]]

    state = encounter["clinical_state"]
    if state in ("ARRIVED", "MSE_IN_PROGRESS"):
        # Step 9 defers to step 12 for the pre-screening source states.
        raise ApiError("ERR_MSE_NOT_COMPLETE")
    if state != "MSE_COMPLETE":
        raise ApiError("ERR_INVALID_ENCOUNTER_STATE")
    if encounter["stabilization_status"] == "NOT_ASSESSED":
        raise ApiError("ERR_STABILIZATION_REQUIRED")
    if effective_posture(facility) == "SUSPENDED":
        raise ApiError("ERR_FACILITY_POSTURE_BLOCKED")
    if observation_beds_occupied(facility) >= facility["observation_bed_count"]:
        raise ApiError("ERR_OBSERVATION_CAPACITY_EXCEEDED")

    encounter["clinical_state"] = "OBSERVATION"
    encounter["observation_bed_held"] = True
    if encounter["observation_started_at"] is None:
        encounter["observation_started_at"] = db.clock
    touch(encounter)
    touch(facility)
    return ok(encounter_view(encounter))


@bp.post("/encounters/<eid>/discharge")
def discharge(eid):
    auth("EmergencyPhysician")
    data = body()
    req_bool(data, "discharge_instructions_ack", required=False)

    encounter = get_encounter(eid)
    facility = db.facilities[encounter["facility_id"]]

    if encounter["clinical_state"] not in ("MSE_COMPLETE", "OBSERVATION"):
        raise ApiError("ERR_INVALID_ENCOUNTER_STATE")
    if encounter["stabilization_status"] != "STABLE":
        raise ApiError("ERR_STABILIZATION_REQUIRED")

    encounter["clinical_state"] = "DISCHARGED"
    encounter["observation_bed_held"] = False
    touch(encounter)
    touch(facility)
    fire_disclosure_defect(facility, encounter)
    return ok(encounter_view(encounter))


# --- ancillary orders -----------------------------------------------------


@bp.post("/encounters/<eid>/ancillary-orders")
def create_ancillary_order(eid):
    auth("EmergencyPhysician")
    data = body()
    category = req_enum(data, "category", C.ANCILLARY_CATEGORIES)
    code = req_enum(data, "code", C.ALL_ANCILLARY_CODES)
    if code not in C.CATEGORY_CODES[category]:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Code '%s' does not belong to category '%s'" % (code, category),
        )
    quantity = req_int(data, "quantity", minimum=1)

    encounter = get_encounter(eid)
    facility = db.facilities[encounter["facility_id"]]

    if encounter["clinical_state"] in C.TERMINAL_CLINICAL_STATES:
        raise ApiError("ERR_INVALID_ENCOUNTER_STATE")

    posture = effective_posture(facility)
    if posture == "SUSPENDED":
        raise ApiError("ERR_FACILITY_POSTURE_BLOCKED")
    if posture == "RESTRICTED" and code in effective_restricted_codes(facility):
        raise ApiError("ERR_FACILITY_POSTURE_BLOCKED")
    if not code_in_scope(facility, category, code):
        raise ApiError("ERR_OUT_OF_SCOPE_SERVICE")

    unit_charge = C.ANCILLARY_UNIT_CHARGE_CENTS[code]
    order = base_row()
    order.update(
        {
            "encounter_id": encounter["id"],
            "category": category,
            "code": code,
            "quantity": quantity,
            "unit_charge_cents": unit_charge,
            "line_total_cents": unit_charge * quantity,
            "status": "ORDERED",
        }
    )
    db.ancillary_orders[order["id"]] = order
    return created(ancillary_view(order))


@bp.get("/encounters/<eid>/ancillary-orders")
def list_ancillary_orders(eid):
    auth(*ANCILLARY_READ_ROLES)
    status = query_enum("status", C.ANCILLARY_STATUSES)
    category = query_enum("category", C.ANCILLARY_CATEGORIES)
    limit, offset = pagination()

    encounter = get_encounter(eid)
    rows = rows_of(db.ancillary_orders, encounter_id=encounter["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    page = paginate(rows, limit, offset)
    return ok_list([ancillary_view(r) for r in page], limit, offset, len(rows))


@bp.get("/ancillary-orders/<oid>")
def read_ancillary_order(oid):
    auth(*ANCILLARY_READ_ROLES)
    return ok(ancillary_view(get_ancillary(oid)))


@bp.post("/ancillary-orders/<oid>/resolve")
def resolve_ancillary_order(oid):
    auth("EmergencyPhysician")
    data = body()
    outcome = req_enum(data, "outcome", C.ANCILLARY_OUTCOMES)
    req_str(data, "result_note", 1, 1000, required=False)

    order = get_ancillary(oid)
    if order["status"] != "ORDERED":
        raise ApiError("ERR_INVALID_ANCILLARY_ORDER_STATE")

    order["status"] = outcome
    touch(order)
    return ok(ancillary_view(order))
