"""Encounters — the entity carrying two parallel, independent state axes.

`clinical_status` (SCHEDULED / CLINICALLY_COMPLETE / CANCELLED) and
`billing_status` (BILLING_PENDING / BILLING_ROUTED / BILLING_CLOSED /
BILLING_VOID) are stored as two separate fields and advanced by two separate
endpoints.  complete-clinical never reads or writes billing_status and
submit-billing never reads or writes clinical_status; the only operation that
touches both is cancel, which collapses them together.
"""
from datetime import timedelta

from flask import Blueprint, g

import calc
import constants as C
import serialize
import svc_line
import validate as V
from auth import begin, parent_family_scope, require_membership_owner, require_physician_clinical_owner
from envelope import object_response
from errors import ApiError
from listing import paginated
from store import db, new_row, touch

bp = Blueprint("encounters", __name__)

ENCOUNTER_READ_ROLES = [
    C.ROLE_PRACTICE_ADMIN,
    C.ROLE_CARE_COORDINATOR,
    C.ROLE_PHYSICIAN,
    C.ROLE_BILLING_SPECIALIST,
    C.ROLE_PARENT,
]


def _membership_family(membership_id):
    membership = db.memberships.get(membership_id)
    return membership["family_id"] if membership else None


def _has_encounter_overlap(child_id, start, end):
    """CLOSED interval [started_at, started_at + 30min]; touching endpoints DO
    collide.  Only encounters whose clinical_status is SCHEDULED are visible."""
    for other in db.encounters.values():
        if other["child_id"] != child_id:
            continue
        if other["clinical_status"] != "SCHEDULED":
            continue
        if start <= other["ends_at"] and end >= other["started_at"]:
            return True
    return False


@bp.post("/peds/encounters")
def create_encounter():
    begin(
        [C.ROLE_CARE_COORDINATOR, C.ROLE_PRACTICE_ADMIN, C.ROLE_PHYSICIAN, C.ROLE_PARENT]
    )
    body = V.json_body()
    membership_id = V.req_string(body, "membership_id")                # RUNG 4 p9
    encounter_type = V.req_string(body, "encounter_type")
    modality = V.req_string(body, "modality")
    patient_state_code = V.req_string(body, "patient_state_code")
    V.req_string(body, "started_at")

    V.enum_member(encounter_type, C.ENCOUNTER_TYPES, "encounter_type")  # RUNG 4 p10
    V.enum_member(modality, C.MODALITIES, "modality")

    started_at = V.req_datetime(body, "started_at")                    # RUNG 5 p12

    membership = db.memberships.get(membership_id)                     # RUNG 6 p18
    if membership is None:
        raise ApiError("ERR_MEMBERSHIP_NOT_FOUND")

    require_membership_owner(membership)                               # RUNG 7 p19

    if membership["status"] != "ACTIVE":                               # RUNG 10 p23
        raise ApiError("ERR_MEMBERSHIP_NOT_ACTIVE")

    physician = db.physicians.get(membership["physician_id"])
    if modality == "TELEHEALTH":                                       # RUNG 13 p27
        codes = physician["licensed_state_codes"] if physician else []
        if patient_state_code not in codes:
            raise ApiError("ERR_LICENSURE_NOT_COVERED")
    if (                                                               # RUNG 13 p28
        modality == "TELEHEALTH"
        and encounter_type in C.TELEHEALTH_PROHIBITED_ENCOUNTER_TYPES
    ):
        raise ApiError("ERR_MODALITY_NOT_ALLOWED")
    if started_at > db.now():                                          # RUNG 13 p29
        raise ApiError("ERR_FUTURE_DATED", "started_at may not be after the current instant.")

    ends_at = started_at + timedelta(minutes=C.ENCOUNTER_DEFAULT_DURATION_MINUTES)
    if _has_encounter_overlap(membership["child_id"], started_at, ends_at):  # RUNG 14 p31
        raise ApiError("ERR_ENCOUNTER_OVERLAP")

    plan = db.plans.get(membership["plan_id"])
    after_hours, reason, surcharge = calc.after_hours_verdict(started_at, plan)

    encounter = new_row(
        db.encounters,
        {
            "membership_id": membership_id,
            "child_id": membership["child_id"],
            "encounter_type": encounter_type,
            "modality": modality,
            "patient_state_code": patient_state_code,
            "started_at": started_at,
            "ends_at": ends_at,
            "after_hours": after_hours,
            "after_hours_reason": reason,
            "surcharge_cents": surcharge,
            "clinical_status": "SCHEDULED",
            "billing_status": "BILLING_PENDING",
            "clinical_note": None,
            "cancel_reason": None,
        },
    )
    return object_response(serialize.encounter_json(encounter), 201)


@bp.get("/peds/encounters")
def list_encounters():
    begin(ENCOUNTER_READ_ROLES)
    clinical_status = V.enum_filter("clinical_status", C.CLINICAL_STATUSES)  # RUNG 4 p10
    billing_status = V.enum_filter("billing_status", C.BILLING_STATUSES)
    limit, offset = V.pagination()                                     # RUNG 4 p11
    membership_id = V.filter_value("membership_id")
    child_id = V.filter_value("child_id")
    scope = parent_family_scope()

    rows = []
    for encounter in db.encounters.values():
        if membership_id is not None and encounter["membership_id"] != membership_id:
            continue
        if child_id is not None and encounter["child_id"] != child_id:
            continue
        if clinical_status is not None and encounter["clinical_status"] != clinical_status:
            continue
        if billing_status is not None and encounter["billing_status"] != billing_status:
            continue
        if scope is not None and _membership_family(encounter["membership_id"]) != scope:
            continue
        rows.append(encounter)
    return paginated(rows, serialize.encounter_json, limit, offset)


@bp.get("/peds/encounters/<encounter_id>")
def read_encounter(encounter_id):
    begin(ENCOUNTER_READ_ROLES)
    encounter = db.encounters.get(encounter_id)                        # RUNG 3 p8
    if encounter is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    require_membership_owner(db.memberships.get(encounter["membership_id"]))  # RUNG 7
    return object_response(serialize.encounter_json(encounter), 200)


@bp.post("/peds/encounters/<encounter_id>/complete-clinical")
def complete_clinical(encounter_id):
    begin([C.ROLE_PHYSICIAN, C.ROLE_PRACTICE_ADMIN])
    encounter = db.encounters.get(encounter_id)                        # RUNG 3 p8
    if encounter is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    body = V.json_body()
    clinical_note = V.req_string(body, "clinical_note")                # RUNG 4 p9

    require_physician_clinical_owner(                                  # RUNG 7 p19
        db.memberships.get(encounter["membership_id"])
    )

    if encounter["clinical_status"] != "SCHEDULED":                    # RUNG 10 p22
        raise ApiError("ERR_INVALID_STATE", "The clinical axis is not SCHEDULED.")

    # Only the clinical axis moves; billing_status is neither read nor changed.
    encounter["clinical_status"] = "CLINICALLY_COMPLETE"
    encounter["clinical_note"] = clinical_note
    touch(encounter, g.touched)
    return object_response(serialize.encounter_json(encounter), 200)


@bp.post("/peds/encounters/<encounter_id>/submit-billing")
def submit_billing(encounter_id):
    begin([C.ROLE_BILLING_SPECIALIST, C.ROLE_PRACTICE_ADMIN])
    encounter = db.encounters.get(encounter_id)                        # RUNG 3 p8
    if encounter is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")

    if encounter["billing_status"] != "BILLING_PENDING":               # RUNG 10 p22
        raise ApiError("ERR_INVALID_STATE", "The billing axis is not BILLING_PENDING.")

    # Only the billing axis moves; clinical_status is neither read nor changed.
    encounter["billing_status"] = "BILLING_ROUTED"

    membership = db.memberships.get(encounter["membership_id"])
    plan = db.plans.get(membership["plan_id"]) if membership else None

    service_code = C.ENCOUNTER_SERVICE_CODE_MAP[encounter["encounter_type"]]
    svc_line.create_service_line(
        membership,
        service_code,
        C.SERVICE_BILLED_AMOUNT_CENTS[service_code],
        plan,
        g.user_id,
        encounter_id=encounter["id"],
    )

    if encounter["after_hours"]:
        waived = bool(plan and plan["after_hours_surcharge_waived"])
        svc_line.create_service_line(
            membership,
            "AFTER_HOURS_SURCHARGE",
            0 if waived else C.SERVICE_BILLED_AMOUNT_CENTS["AFTER_HOURS_SURCHARGE"],
            plan,
            g.user_id,
            encounter_id=encounter["id"],
        )

    svc_line.bubble_billing_axis(encounter)
    touch(encounter, g.touched)
    return object_response(serialize.encounter_json(encounter), 200)


@bp.post("/peds/encounters/<encounter_id>/cancel")
def cancel_encounter(encounter_id):
    begin([C.ROLE_CARE_COORDINATOR, C.ROLE_PRACTICE_ADMIN, C.ROLE_PHYSICIAN])
    encounter = db.encounters.get(encounter_id)                        # RUNG 3 p8
    if encounter is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    body = V.json_body()
    reason = V.req_string(body, "reason")                              # RUNG 4 p9

    require_physician_clinical_owner(                                  # RUNG 7 p19
        db.memberships.get(encounter["membership_id"])
    )

    if encounter["clinical_status"] not in ("SCHEDULED", "CLINICALLY_COMPLETE"):
        raise ApiError("ERR_INVALID_STATE", "The clinical axis cannot be cancelled.")
    if encounter["billing_status"] not in ("BILLING_PENDING", "BILLING_ROUTED"):
        raise ApiError("ERR_INVALID_STATE", "The billing axis cannot be voided.")  # p22

    encounter["clinical_status"] = "CANCELLED"
    encounter["cancel_reason"] = reason
    encounter["billing_status"] = "BILLING_VOID"
    touch(encounter, g.touched)
    svc_line.void_encounter_lines(encounter)
    return object_response(serialize.encounter_json(encounter), 200)
