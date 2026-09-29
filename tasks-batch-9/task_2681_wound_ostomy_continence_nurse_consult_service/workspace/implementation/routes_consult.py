"""ConsultRequest lifecycle (10 endpoints).

Cyclic legs implemented here:
  TRIAGED -> RETURNED_FOR_INFO -> REQUESTED -> TRIAGED   (revision loop)
  ASSIGNED -> ESCALATED -> ASSIGNED                      (escalation loop)
"""

import calc
import services
from core import (
    MAX_REVISIONS,
    READ_ROLES,
    ROLE_DIRECTOR,
    ROLE_UNIT_CHARGE,
    ROLE_WOC_NURSE,
    F,
    apply_filters,
    authorize,
    bump,
    chrono,
    dt_of,
    fail,
    filters,
    insert,
    must,
    new_row,
    now,
    ok,
    ok_list,
    pagination,
    paginate,
    parse_input,
    public,
    public_list,
    rows_of,
    store,
)
from flask import Blueprint

bp = Blueprint("consult", __name__)

CONSULT_TYPES = ("WOUND", "OSTOMY", "INCONTINENCE")
REPORTED_STAGES = ("NONE", "MUCOSAL", "STAGE_1", "STAGE_2", "STAGE_3",
                   "STAGE_4", "DTI", "UNSTAGEABLE")
CONSULT_STATUSES = ("REQUESTED", "TRIAGED", "RETURNED_FOR_INFO", "ASSIGNED",
                    "ASSESSED", "PLAN_ACTIVE", "ESCALATED", "CLOSED", "CANCELLED")
BANDS = ("P1", "P2", "P3")
CASE_CLOSEABLE_FOR_CONSULT = ("CLASSIFIED_POA", "RCA_COMPLETE", "CLOSED",
                              "RECLASSIFIED")


def require_admitted(patient):
    if patient.get("status") != "ADMITTED":
        fail("ERR_PATIENT_DISCHARGED")


def require_consult_state(consult, allowed):
    if consult.get("status") not in allowed:
        fail("ERR_CONSULT_INVALID_STATE")


@bp.post("/consult-requests")
def create_consult():
    authorize(ROLE_UNIT_CHARGE)
    body = parse_input([
        F("patient_id", "id", required=True),
        F("requesting_unit_id", "id", required=True),
        F("consult_type", "enum", required=True, enum=CONSULT_TYPES),
        F("reported_stage", "enum", required=True, enum=REPORTED_STAGES),
        F("clinical_note", "string", required=True, min_len=1, max_len=2000),
    ])
    patient = must("patients", body["patient_id"])
    must("units", body["requesting_unit_id"])
    if body["requesting_unit_id"] != patient.get("unit_id"):
        fail("ERR_ENTITY_LINK_MISMATCH",
             "requesting_unit_id must equal the patient's unit_id.")
    require_admitted(patient)
    consult = new_row(
        "consult",
        patient_id=body["patient_id"],
        requesting_unit_id=body["requesting_unit_id"],
        assigned_nurse_id=None,
        consult_type=body["consult_type"],
        reported_stage=body["reported_stage"],
        clinical_note=body["clinical_note"],
        status="REQUESTED",
        acuity_score=None,
        acuity_variant=None,
        priority_band=None,
        sla_due_at=None,
        revision_count=0,
        protocol_hold=False,
        triaged_at=None,
        escalation_count=0,
        closing_summary=None,
    )
    insert("consult_requests", consult)
    return ok(public(consult), 201)


@bp.get("/consult-requests")
def list_consults():
    authorize(*READ_ROLES)
    limit, offset = pagination()
    active = filters({
        "patient_id": None,
        "requesting_unit_id": None,
        "assigned_nurse_id": None,
        "status": CONSULT_STATUSES,
        "priority_band": BANDS,
    })
    rows = chrono(apply_filters(rows_of("consult_requests"), active))
    page, total = paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)


@bp.get("/consult-requests/<consult_id>")
def get_consult(consult_id):
    authorize(*READ_ROLES)
    return ok(public(must("consult_requests", consult_id)))


@bp.post("/consult-requests/<consult_id>/triage")
def triage_consult(consult_id):
    authorize(ROLE_WOC_NURSE)
    parse_input([])
    consult = must("consult_requests", consult_id)
    require_consult_state(consult, ("REQUESTED",))
    patient = store("patients").get(consult["patient_id"])
    require_admitted(patient)
    consult["triaged_at"] = now()
    services.apply_acuity(consult, patient, consult.get("reported_stage"),
                          calc.VARIANT_INTAKE, None)
    consult["status"] = "TRIAGED"
    bump(consult)
    return ok(public(consult))


@bp.post("/consult-requests/<consult_id>/return")
def return_consult(consult_id):
    authorize(ROLE_WOC_NURSE)
    parse_input([F("reason", "string", required=True, min_len=1, max_len=2000)])
    consult = must("consult_requests", consult_id)
    require_consult_state(consult, ("TRIAGED",))
    if int(consult.get("revision_count") or 0) >= MAX_REVISIONS:
        fail("ERR_REVISION_LIMIT_REACHED")
    consult["status"] = "RETURNED_FOR_INFO"
    consult["sla_due_at"] = None
    bump(consult)
    return ok(public(consult))


@bp.post("/consult-requests/<consult_id>/resubmit")
def resubmit_consult(consult_id):
    authorize(ROLE_UNIT_CHARGE)
    body = parse_input([
        F("clinical_note", "string", required=True, min_len=1, max_len=2000),
        F("reported_stage", "enum", required=True, enum=REPORTED_STAGES),
    ])
    consult = must("consult_requests", consult_id)
    require_consult_state(consult, ("RETURNED_FOR_INFO",))
    if int(consult.get("revision_count") or 0) >= MAX_REVISIONS:
        fail("ERR_REVISION_LIMIT_REACHED")
    consult["clinical_note"] = body["clinical_note"]
    consult["reported_stage"] = body["reported_stage"]
    consult["revision_count"] = int(consult.get("revision_count") or 0) + 1
    consult["status"] = "REQUESTED"
    consult["acuity_score"] = None
    consult["acuity_variant"] = None
    consult["priority_band"] = None
    consult["triaged_at"] = None
    consult["sla_due_at"] = None
    bump(consult)
    return ok(public(consult))


@bp.post("/consult-requests/<consult_id>/assign")
def assign_consult(consult_id):
    authorize(ROLE_DIRECTOR)
    body = parse_input([F("assigned_nurse_id", "id", required=True)])
    consult = must("consult_requests", consult_id)
    nurse = must("woc_nurses", body["assigned_nurse_id"])
    require_consult_state(consult, ("TRIAGED", "ESCALATED"))
    patient = store("patients").get(consult["patient_id"])
    require_admitted(patient)
    if nurse.get("certification_status") not in ("CANDIDATE", "CERTIFIED"):
        fail("ERR_NURSE_NOT_CERTIFIED")
    previous_nurse_id = consult.get("assigned_nurse_id")
    same_nurse = previous_nurse_id == nurse["id"]
    if not same_nurse:
        if int(nurse.get("active_consult_load") or 0) >= int(nurse.get("max_consult_load") or 0):
            fail("ERR_NURSE_LOAD_EXCEEDED")
    if not same_nurse:
        if previous_nurse_id:
            previous = store("woc_nurses").get(previous_nurse_id)
            if previous is not None:
                previous["active_consult_load"] = max(
                    0, int(previous.get("active_consult_load") or 0) - 1)
                bump(previous)
        nurse["active_consult_load"] = int(nurse.get("active_consult_load") or 0) + 1
        bump(nurse)
    consult["assigned_nurse_id"] = nurse["id"]
    consult["status"] = "ASSIGNED"
    bump(consult)
    return ok(public(consult))


@bp.post("/consult-requests/<consult_id>/escalate")
def escalate_consult(consult_id):
    authorize(ROLE_WOC_NURSE, ROLE_DIRECTOR)
    parse_input([F("reason", "string", required=True, min_len=1, max_len=2000)])
    consult = must("consult_requests", consult_id)
    require_consult_state(consult, ("ASSIGNED",))
    due = consult.get("sla_due_at")
    if due is None or dt_of(now()) <= dt_of(due):
        fail("ERR_CONSULT_INVALID_STATE",
             "The SLA clock has not yet passed for this consult.")
    consult["escalation_count"] = int(consult.get("escalation_count") or 0) + 1
    consult["status"] = "ESCALATED"
    bump(consult)
    return ok(public(consult))


@bp.post("/consult-requests/<consult_id>/close")
def close_consult(consult_id):
    authorize(ROLE_WOC_NURSE)
    body = parse_input([
        F("closing_summary", "string", required=True, min_len=1, max_len=2000),
    ])
    consult = must("consult_requests", consult_id)
    require_consult_state(consult, ("PLAN_ACTIVE",))
    assessment_ids = {a["id"] for a in rows_of("skin_assessments")
                      if a.get("consult_request_id") == consult_id}
    for case in rows_of("pressure_injury_cases"):
        if case.get("skin_assessment_id") not in assessment_ids:
            continue
        if case.get("status") not in CASE_CLOSEABLE_FOR_CONSULT:
            fail("ERR_RCA_NOT_COMPLETE")
    consult["closing_summary"] = body["closing_summary"]
    consult["status"] = "CLOSED"
    nurse_id = consult.get("assigned_nurse_id")
    if nurse_id:
        nurse = store("woc_nurses").get(nurse_id)
        if nurse is not None:
            nurse["active_consult_load"] = max(
                0, int(nurse.get("active_consult_load") or 0) - 1)
            nurse["mentored_consult_count"] = int(nurse.get("mentored_consult_count") or 0) + 1
            services.recompute_eligibility(nurse)
            bump(nurse)
    bump(consult)
    return ok(public(consult))


@bp.post("/consult-requests/<consult_id>/cancel")
def cancel_consult(consult_id):
    authorize(ROLE_UNIT_CHARGE, ROLE_DIRECTOR)
    parse_input([F("reason", "string", required=True, min_len=1, max_len=2000)])
    consult = must("consult_requests", consult_id)
    if consult.get("status") in ("CLOSED", "CANCELLED"):
        fail("ERR_CONSULT_INVALID_STATE")
    services.cancel_cascade(consult)
    return ok(public(consult))
