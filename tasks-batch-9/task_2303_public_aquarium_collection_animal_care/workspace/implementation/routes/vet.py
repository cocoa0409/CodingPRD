"""VeterinaryCase opening, reads and the four-branch closure."""

from flask import Blueprint

import db
import middleware as M
import response
import serializers as S
import validators as V
from errors import ApiError
from services import calc, engine

bp = Blueprint("vet", __name__)

CASE_TYPES = ("PREVENTIVE_EXAM", "TREATMENT", "NECROPSY")
OUTCOMES = ("RESOLVED", "CHRONIC_MANAGED", "MORTALITY_REFERRED", "NECROPSY_FINALIZED")
SEVERITIES = ("NONE", "MINOR", "MAJOR", "CRITICAL")

CASE_COMPUTED = ("status", "outcome", "findings_severity", "opened_by_user_id",
                 "closed_by_user_id", "closed_at")
CLOSURE_COMPUTED = ("status", "opened_by_user_id", "closed_by_user_id", "closed_at")

TREATMENT_ENTRY_STATES = ("HEALTHY", "UNDER_TREATMENT", "CRITICAL_CARE")
OPEN_CLINICAL_TYPES = ("TREATMENT", "PREVENTIVE_EXAM")


def _outcome_legal(case, outcome, severity):
    if outcome == "RESOLVED":
        return case["case_type"] in ("PREVENTIVE_EXAM", "TREATMENT") and severity in ("NONE",
                                                                                     "MINOR")
    if outcome == "CHRONIC_MANAGED":
        return case["case_type"] == "TREATMENT" and severity in ("MINOR", "MAJOR")
    if outcome == "MORTALITY_REFERRED":
        return severity == "CRITICAL"
    return case["case_type"] == "NECROPSY" and severity is not None


def _other_open_clinical_cases(specimen_id, exclude_id):
    return [
        c for c in db.db.veterinary_cases.values()
        if c["specimen_id"] == specimen_id
        and c["id"] != exclude_id
        and c["status"] == "OPEN"
        and c["case_type"] in OPEN_CLINICAL_TYPES
    ]


@bp.route("/aquarium/veterinary-cases", methods=["POST"])
def create_case():
    user_id, _role = M.authenticate({M.VET})
    body = M.json_body()
    specimen = M.fetch_body_fk(body, "specimen_id", "specimens")

    V.reject_computed(body, CASE_COMPUTED)
    V.as_id(body, "specimen_id", required=True)
    case_type = V.as_enum(body, "case_type", CASE_TYPES, required=True)
    opened_at = V.as_dt(body, "opened_at", required=True)
    treatment_start_at = V.as_dt(body, "treatment_start_at")
    withdrawal_days = V.as_int(body, "withdrawal_days", minimum=0, maximum=90)
    diagnosis_code = V.as_str(body, "diagnosis_code")

    if case_type == "TREATMENT":
        if treatment_start_at is None:
            V.bad("Field 'treatment_start_at' is required for a TREATMENT case")
        if withdrawal_days is None:
            V.bad("Field 'withdrawal_days' is required for a TREATMENT case")
    else:
        if treatment_start_at is not None:
            V.bad("Field 'treatment_start_at' is only allowed on a TREATMENT case")
        if withdrawal_days is not None:
            V.bad("Field 'withdrawal_days' is only allowed on a TREATMENT case")

    if opened_at > db.db.clock:
        raise ApiError("ERR_TIMESTAMP_IN_FUTURE")

    if case_type == "TREATMENT":
        if specimen["health_status"] not in TREATMENT_ENTRY_STATES:
            raise ApiError("ERR_INVALID_STATE")
        conflict = calc.find_withdrawal_conflict(
            specimen["id"], treatment_start_at, withdrawal_days)
        if conflict is not None:
            raise ApiError("ERR_TREATMENT_WITHDRAWAL_ACTIVE")

    row = db.new_row()
    row.update({
        "specimen_id": specimen["id"],
        "case_type": case_type,
        "opened_at": opened_at,
        "treatment_start_at": treatment_start_at,
        "withdrawal_days": withdrawal_days,
        "diagnosis_code": diagnosis_code,
        "status": "OPEN",
        "outcome": None,
        "findings_severity": None,
        "opened_by_user_id": user_id,
        "closed_by_user_id": None,
        "closed_at": None,
    })
    db.insert("veterinary_cases", row)

    if case_type == "TREATMENT":
        specimen["health_status"] = "UNDER_TREATMENT"
        engine.refresh_withdrawal(specimen)
        engine.refresh_welfare_rolling(specimen)
        db.touch(specimen)

    return response.object_response(S.veterinary_case(row), 201)


@bp.route("/aquarium/veterinary-cases/<row_id>", methods=["GET"])
def get_case(row_id):
    M.authenticate(M.NON_LIAISON)
    row = M.fetch("veterinary_cases", row_id)
    return response.object_response(S.veterinary_case(row))


@bp.route("/aquarium/veterinary-cases/<row_id>/closure", methods=["POST"])
def close_case(row_id):
    user_id, _role = M.authenticate({M.VET})
    case = M.fetch("veterinary_cases", row_id)
    body = M.json_body()
    V.reject_computed(body, CLOSURE_COMPUTED)
    outcome = V.as_enum(body, "outcome", OUTCOMES, required=True)
    severity = V.as_enum(body, "findings_severity", SEVERITIES, required=True)
    V.as_str(body, "note")

    if case["status"] == "CLOSED":
        raise ApiError("ERR_ENTITY_TERMINAL")
    if not _outcome_legal(case, outcome, severity):
        raise ApiError("ERR_INVALID_ACTION")
    if outcome == "NECROPSY_FINALIZED" and user_id == case["opened_by_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION")

    specimen = db.db.specimens.get(case["specimen_id"])

    case["status"] = "CLOSED"
    case["outcome"] = outcome
    case["findings_severity"] = severity
    case["closed_by_user_id"] = user_id
    case["closed_at"] = db.db.clock
    db.touch(case)

    if specimen is not None:
        specimen_dirty = engine.refresh_withdrawal(specimen)

        if outcome == "RESOLVED":
            others = _other_open_clinical_cases(specimen["id"], case["id"])
            if not others:
                if specimen["health_status"] == "UNDER_TREATMENT":
                    specimen["health_status"] = "HEALTHY"
                    specimen_dirty = True
                elif (specimen["health_status"] == "CRITICAL_CARE"
                        and case["case_type"] == "PREVENTIVE_EXAM" and severity == "NONE"):
                    specimen["health_status"] = "HEALTHY"
                    specimen_dirty = True
            if engine.refresh_welfare_rolling(specimen):
                specimen_dirty = True
            if case["case_type"] == "PREVENTIVE_EXAM" and severity == "NONE":
                quarantine = engine.active_quarantine_case(specimen["id"])
                if quarantine is not None:
                    db.touch(quarantine)
        elif outcome == "CHRONIC_MANAGED":
            if engine.refresh_welfare_rolling(specimen):
                specimen_dirty = True
        elif outcome == "MORTALITY_REFERRED":
            specimen["health_status"] = "CRITICAL_CARE"
            specimen_dirty = True
            engine.critical_care_coupling(specimen)
        else:
            specimen["health_status"] = "NECROPSY_COMPLETE"
            specimen_dirty = True

        if specimen_dirty:
            db.touch(specimen)

    return response.object_response(S.veterinary_case(case))
