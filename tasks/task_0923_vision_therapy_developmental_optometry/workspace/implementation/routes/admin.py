"""Patients, payers, therapists, rooms and the logical clock."""

from flask import Blueprint, request

import calc
import cascades
import config
import lookup
import serialize
from auth import authenticate
from envelope import created, ok
from errors import ApiError
from store import (base_row, clock, db, latest, now, now_iso, ordered, parse_date,
                   parse_instant, touch)
from validate import json_body

bp = Blueprint("admin", __name__)
P = config.API_PREFIX


# ------------------------------------------------------------- patients ----
@bp.post(P + "/patients")
def create_patient():
    authenticate([config.ROLE_FRONT_DESK, config.ROLE_CLINIC_ADMIN])
    b = json_body()
    full_name = b.str_req("full_name")
    date_of_birth = b.date_req("date_of_birth")
    b.enum_shape_req("diagnosis_category")
    guardian_name = b.str_opt("guardian_name")
    diagnosis = b.enum_req("diagnosis_category", config.DIAGNOSIS_CATEGORIES)

    row = base_row()
    row.update({
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "diagnosis_category": diagnosis,
        "guardian_name": guardian_name,
        "clinical_status": "INTAKE",
        "discharge_reason": None,
        "discharged_at": None,
        "discharged_by_user_id": None,
    })
    db.patients[row["id"]] = row
    return created(serialize.patient(row))


@bp.get(P + "/patients/<id>")
def get_patient(id):
    caller = authenticate(config.READ_ROLES_WITH_PATIENT)
    row = db.patients.get(id)
    if caller.is_patient and row is not None and row["id"] != caller.user_id:
        raise ApiError("ERR_UNAUTHORIZED", "A PatientUser may only read their own record.")
    row = lookup.patient_or_404(id)
    return ok(serialize.patient(row))


def _most_recent_plan(patient_id):
    rows = [p for p in db.plans.values() if p["patient_id"] == patient_id]
    return latest(rows) if rows else None


def _discharge_precondition_holds(patient, reason):
    plan = _most_recent_plan(patient["id"])
    if reason == "GOALS_MET":
        return plan is not None and bool(plan["discharge_ready"])
    if reason == "PLATEAU":
        return plan is not None and plan["progress_state"] == "PLATEAU"
    if reason == "NON_COMPLIANCE":
        return plan is not None and calc.D(plan["home_compliance_pct"]) < calc.D(
            config.PHASE_ADVANCE_COMPLIANCE_PCT)
    if reason == "TRANSFERRED":
        return any(r["patient_id"] == patient["id"] and r["direction"] == "OUTBOUND"
                   and r["status"] == "ACCEPTED" for r in db.referrals.values())
    # LOST_TO_FOLLOW_UP
    sessions = [s for s in db.sessions.values() if s["patient_id"] == patient["id"]]
    if not any(s["schedule_status"] == "NO_SHOW" for s in sessions):
        return False
    from datetime import timedelta
    cutoff = now() - timedelta(days=config.LOST_TO_FOLLOWUP_DAYS)
    for s in sessions:
        if s["schedule_status"] not in ("COMPLETED", "ATTESTED"):
            continue
        performed = parse_instant(s.get("performed_at"))
        if performed is not None and performed >= cutoff:
            return False
    return True


@bp.post(P + "/patients/<id>/discharge")
def discharge_patient(id):
    caller = authenticate([config.ROLE_OPTOMETRIST])
    b = json_body()
    b.enum_shape_req("discharge_reason")                                   # rung 3
    reason = b.enum_req("discharge_reason", config.DISCHARGE_REASONS)      # rung 4
    patient = lookup.patient_or_404(id)                                    # rung 5
    # rung 12 deliberately does NOT apply: discharge sits outside the gate.
    if patient["clinical_status"] != "ACTIVE":                             # rung 14
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE patient may be discharged.")
    for loan in db.kit_loans.values():                                     # rung 27
        if loan["patient_id"] == id and loan["status"] in ("CHECKED_OUT", "RECALLED"):
            raise ApiError("ERR_LOAN_OUTSTANDING")
    if not _discharge_precondition_holds(patient, reason):                 # rung 35
        raise ApiError("ERR_DISCHARGE_CRITERIA_NOT_MET")

    patient["clinical_status"] = "DISCHARGED"
    patient["discharge_reason"] = reason
    patient["discharged_at"] = now_iso()
    patient["discharged_by_user_id"] = caller.user_id
    touch(patient)
    cascades.discharge_cascade(patient)
    return ok(serialize.patient(patient))


# --------------------------------------------------------------- payers ----
@bp.post(P + "/payers")
def create_payer():
    authenticate([config.ROLE_CLINIC_ADMIN])
    b = json_body()
    name = b.str_req("name")
    b.enum_shape_req("payer_type")
    timed = b.num_req("allowed_amount_timed_unit")
    flat = b.num_req("allowed_amount_flat_session")
    evaluation = b.num_req("allowed_amount_evaluation")
    coinsurance = b.num_req("coinsurance_rate", minimum=0.0, maximum=1.0)
    freq = b.int_req("frequency_limit_months")
    payer_type = b.enum_req("payer_type", config.PAYER_TYPES)

    row = base_row()
    row.update({
        "name": name,
        "payer_type": payer_type,
        "allowed_amount_timed_unit": calc.f2(timed),
        "allowed_amount_flat_session": calc.f2(flat),
        "allowed_amount_evaluation": calc.f2(evaluation),
        "coinsurance_rate": coinsurance,
        "frequency_limit_months": freq,
    })
    db.payers[row["id"]] = row
    return created(serialize.payer(row))


@bp.get(P + "/payers/<id>")
def get_payer(id):
    authenticate(config.READ_ROLES)
    return ok(serialize.payer(lookup.payer_or_404(id)))


# ---------------------------------------------------------- therapists ----
@bp.post(P + "/therapists")
def create_therapist():
    authenticate([config.ROLE_CLINIC_ADMIN])
    b = json_body()
    full_name = b.str_req("full_name")
    b.enum_shape_req("credential")
    expires = b.instant_req("credential_expires_at")
    npi = b.str_opt("npi")
    credential = b.enum_req("credential", config.CREDENTIALS)

    row = base_row()
    row.update({
        "full_name": full_name,
        "credential": credential,
        "credential_expires_at": expires,
        "npi": npi,
    })
    db.therapists[row["id"]] = row
    return created(serialize.therapist(row))


@bp.get(P + "/therapists/<id>")
def get_therapist(id):
    authenticate(config.READ_ROLES)
    return ok(serialize.therapist(lookup.therapist_or_404(id)))


# ---------------------------------------------------------------- rooms ----
@bp.post(P + "/rooms")
def create_room():
    authenticate([config.ROLE_CLINIC_ADMIN])
    b = json_body()
    name = b.str_req("name")
    b.enum_shape_req("equipment_class")
    equipment_class = b.enum_req("equipment_class", config.EQUIPMENT_CLASSES)

    row = base_row()
    row.update({"name": name, "equipment_class": equipment_class})
    db.rooms[row["id"]] = row
    return created(serialize.room(row))


# -------------------------------------------------------- logical clock ----
@bp.post(P + "/_clock/set_current_utc")
def set_clock():
    authenticate([config.ROLE_CLINIC_ADMIN])
    b = json_body()
    raw = b.instant_req("to_iso8601")
    moment = parse_instant(raw)
    clock.set(raw, moment)
    today = moment.date()

    for auth_row in ordered(db.authorizations):
        end = parse_date(auth_row["window_end_date"])
        if end is not None and today > end and auth_row["status"] in ("ACTIVE", "EXHAUSTED"):
            auth_row["status"] = "EXPIRED"
            touch(auth_row)

    for cov in ordered(db.coverages):
        end = parse_date(cov["effective_end_date"])
        if end is not None and today > end and cov["status"] == "ACTIVE":
            cov["status"] = "TERMINATED"
            touch(cov)

    return ok({"current_utc": clock.raw})
