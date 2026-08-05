"""Patients, referrals and surrogate designations (PRD 3.1, 3.2, 3.12)."""

from decimal import Decimal

from flask import Blueprint

import calc
import cascades
import config
from envelope import created, listing, ok
from errors import (
    ERR_REFERRAL_INELIGIBLE, ERR_REREFERRAL_LIMIT, ERR_VALIDATION, api_error,
)
from ladder import (
    apply_filters, auth, field, fk, freeze_gate, pagination, paginate,
    path_row, query_filters, raw_body, state, touch, validate,
)
from store import ordered, store

bp = Blueprint("patients", __name__)


def _patient_row(data):
    return store.new_row({
        "mrn": data["mrn"],
        "full_name": data["full_name"],
        "date_of_birth": data["date_of_birth"],
        "jurisdiction_code": data["jurisdiction_code"],
        "attending_clinician_user_id": data["attending_clinician_user_id"],
        "opioid_status": data["opioid_status"] or "OPIOID_NAIVE",
        "capacity_status": "HAS_CAPACITY",
        "program_status": "REFERRED",
        "code_status": "FULL_CODE",
        "code_status_rank": config.CODE_STATUS_RANKS["FULL_CODE"],
        "records_frozen": False,
        "deceased_at": None,
        "active_daily_mme": Decimal("0.0"),
        "acp_minutes_claimed": 0,
        "acp_paid_cents_ytd": 0,
        "open_symptom_count": 0,
    })


@bp.post("/palliative/patients")
def register_patient():
    auth([config.ROLE_INTAKE, config.ROLE_ADMIN])
    body = raw_body()
    data = validate(body, [
        field("mrn", "string", required=True, nonempty=True),
        field("full_name", "string", required=True),
        field("date_of_birth", "date", required=True),
        field("jurisdiction_code", "enum", required=True, enum=config.JURISDICTION_CODES),
        field("attending_clinician_user_id", "string", required=True),
        field("opioid_status", "enum", enum=config.OPIOID_STATUSES),
    ])
    for existing in store.patients.values():
        if existing["mrn"] == data["mrn"]:
            raise api_error(ERR_VALIDATION, "mrn must be unique across all patients.")
    patient = _patient_row(data)
    store.patients[patient["id"]] = patient
    return created(patient)


@bp.get("/palliative/patients/<pid>")
def read_patient(pid):
    auth([config.ROLE_INTAKE, config.ROLE_PHYSICIAN, config.ROLE_NURSE,
          config.ROLE_SOCIAL, config.ROLE_CHAPLAIN, config.ROLE_DIRECTOR,
          config.ROLE_ONCALL, config.ROLE_BILLING, config.ROLE_ADMIN])
    return ok(path_row(store.patients, pid))


@bp.post("/palliative/patients/<pid>/capacity-determinations")
def capacity_determination(pid):
    auth([config.ROLE_PHYSICIAN, config.ROLE_ADMIN])
    patient = path_row(store.patients, pid)
    body = raw_body()
    data = validate(body, [
        field("capacity_status", "enum", required=True, enum=config.CAPACITY_STATUSES),
        field("determination_note", "string", required=True),
    ])
    freeze_gate(patient)
    patient["capacity_status"] = data["capacity_status"]
    touch(patient)
    cascades.capacity_cascade(patient)
    return ok(patient)


@bp.post("/palliative/patients/<pid>/death-events")
def death_event(pid):
    auth([config.ROLE_PHYSICIAN, config.ROLE_ADMIN])
    patient = path_row(store.patients, pid)
    body = raw_body()
    validate(body, [field("pronouncing_clinician_user_id", "string", required=True)])
    freeze_gate(patient)
    state(patient["program_status"] in ("ACTIVE", "HOSPICE_ELECTED"))
    patient["program_status"] = "DECEASED"
    patient["records_frozen"] = True
    patient["deceased_at"] = store.now()
    touch(patient)
    cascades.death_cascade(patient)
    return ok(patient)


# ------------------------------------------------------------------ referrals
@bp.post("/palliative/referrals")
def create_referral():
    auth([config.ROLE_INTAKE, config.ROLE_ADMIN])
    body = raw_body()
    data = validate(body, [
        field("patient_id", "string", required=True),
        field("source", "enum", required=True, enum=config.REFERRAL_SOURCES),
        field("prognosis_months", "integer", required=True, lo=1, hi=24),
        field("serious_illness_criteria_count", "integer", required=True, lo=0, hi=5),
    ])
    patient = fk(store.patients, data["patient_id"])
    freeze_gate(patient)
    variant, score = calc.referral_triage_score(
        data["source"], data["prognosis_months"], data["serious_illness_criteria_count"])
    referral = store.new_row({
        "patient_id": patient["id"],
        "source": data["source"],
        "prognosis_months": data["prognosis_months"],
        "serious_illness_criteria_count": data["serious_illness_criteria_count"],
        "triage_variant": variant,
        "triage_score": score,
        "status": "RECEIVED",
        "decline_reason_code": None,
        "re_referral_count": 0,
    })
    store.referrals[referral["id"]] = referral
    return created(referral)


@bp.post("/palliative/referrals/<rid>/decision")
def decide_referral(rid):
    auth([config.ROLE_INTAKE, config.ROLE_ADMIN])
    referral = path_row(store.referrals, rid)
    body = raw_body()
    data = validate(body, [
        field("decision", "enum", required=True, enum=config.REFERRAL_DECISIONS),
        field("decline_reason_code", "enum", enum=config.DECLINE_REASON_CODES),
    ])
    decision = data["decision"]
    if decision == "DECLINE" and data["decline_reason_code"] is None:
        raise api_error(ERR_VALIDATION, "decline_reason_code is required for a DECLINE decision.")
    patient = store.patients.get(referral["patient_id"])
    freeze_gate(patient)
    if decision in ("ACCEPT", "DECLINE"):
        state(referral["status"] == "RECEIVED")
    else:
        state(referral["status"] == "DECLINED")
    if decision == "ACCEPT" and referral["triage_score"] < config.REFERRAL_ACCEPT_MIN_SCORE:
        raise api_error(ERR_REFERRAL_INELIGIBLE)
    if decision == "RE_REFER" and referral["re_referral_count"] >= config.MAX_REREFERRALS:
        raise api_error(ERR_REREFERRAL_LIMIT)

    if decision == "ACCEPT":
        referral["status"] = "ACCEPTED"
        touch(referral)
        if patient is not None and patient["program_status"] == "REFERRED":
            patient["program_status"] = "ACTIVE"
            touch(patient)
    elif decision == "DECLINE":
        referral["status"] = "DECLINED"
        referral["decline_reason_code"] = data["decline_reason_code"]
        touch(referral)
    else:
        referral["status"] = "RECEIVED"
        referral["re_referral_count"] += 1
        referral["decline_reason_code"] = None
        variant, score = calc.referral_triage_score(
            referral["source"], referral["prognosis_months"],
            referral["serious_illness_criteria_count"])
        referral["triage_variant"] = variant
        referral["triage_score"] = score
        touch(referral)
    return ok(referral)


@bp.get("/palliative/patients/<pid>/referrals")
def list_patient_referrals(pid):
    auth([config.ROLE_INTAKE, config.ROLE_PHYSICIAN, config.ROLE_SOCIAL, config.ROLE_ADMIN])
    patient = path_row(store.patients, pid)
    limit, offset = pagination()
    rows = ordered([r for r in store.referrals.values() if r["patient_id"] == patient["id"]])
    page, total = paginate(rows, limit, offset)
    return listing(page, limit, offset, total)


# ---------------------------------------------------------------- surrogates
@bp.post("/palliative/surrogates")
def create_surrogate():
    auth([config.ROLE_SOCIAL, config.ROLE_ADMIN])
    body = raw_body()
    data = validate(body, [
        field("patient_id", "string", required=True),
        field("person_user_id", "string", required=True),
        field("person_name", "string", required=True),
        field("relationship", "enum", required=True, enum=config.RELATIONSHIPS),
        field("is_beneficiary", "boolean", default=False),
    ])
    patient = fk(store.patients, data["patient_id"])
    freeze_gate(patient)
    row = store.new_row({
        "patient_id": patient["id"],
        "person_user_id": data["person_user_id"],
        "person_name": data["person_name"],
        "relationship": data["relationship"],
        "hierarchy_rank": config.SURROGATE_RANKS[data["relationship"]],
        "is_beneficiary": bool(data["is_beneficiary"]),
        "status": "PROPOSED",
    })
    store.surrogates[row["id"]] = row
    return created(row)


@bp.post("/palliative/surrogates/<sid>/status")
def surrogate_status(sid):
    auth([config.ROLE_SOCIAL, config.ROLE_ADMIN])
    row = path_row(store.surrogates, sid)
    body = raw_body()
    data = validate(body, [
        field("target_status", "enum", required=True, enum=config.SURROGATE_TARGET_STATUSES),
    ])
    freeze_gate(store.patients.get(row["patient_id"]))
    target = data["target_status"]
    if target == "ACTIVE":
        state(row["status"] == "PROPOSED")
    else:
        state(row["status"] in ("PROPOSED", "ACTIVE"))
    row["status"] = target
    touch(row)
    return ok(row)


@bp.get("/palliative/patients/<pid>/surrogates")
def list_patient_surrogates(pid):
    auth([config.ROLE_SOCIAL, config.ROLE_PHYSICIAN, config.ROLE_ADMIN])
    patient = path_row(store.patients, pid)
    limit, offset = pagination()
    rows = [r for r in store.surrogates.values() if r["patient_id"] == patient["id"]]
    rows = apply_filters(ordered(rows), query_filters(["status"]))
    page, total = paginate(rows, limit, offset)
    return listing(page, limit, offset, total)
