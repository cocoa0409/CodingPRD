"""Control remediation records and their verification cycle (PRD 3.9)."""

from flask import Blueprint

import calc
from common import (
    F, R_ADMIN, R_ANALYST, R_AUDITOR, READ6,
    authenticate, db, fail, get_case, get_remediation, get_body, matches, new_row, now,
    ok, pagination, paginate, qs, require_state, sorted_rows, touch, validate,
)
from serializers import remediation_json

bp = Blueprint("remediations", __name__)

TERMINAL = ("VERIFIED",)
ROOT_CAUSES = ("RATE_TABLE_STALE", "JURISDICTION_MAPPING_ERROR", "THIRD_PARTY_FEED_ERROR",
               "MANUAL_ENTRY_ERROR", "DEPOSIT_SCHEDULING_ERROR")
GAP_CLASSES = ("PROCESS_CONTROL", "SYSTEM_CONTROL", "THIRD_PARTY_FAILURE")

REMEDIATION_CREATE = {
    "correction_case_id": F("string", True),
    "root_cause_code": F("string", True, enum=ROOT_CAUSES),
    "control_gap_class": F("string", True, enum=GAP_CLASSES),
    "owner_user_id": F("string", True, min_len=1, max_len=120),
    "target_date": F("datetime", True),
}


def _case_of(remediation):
    return db.correction_cases.get(remediation["correction_case_id"])


def _remediation_employer(remediation):
    case = _case_of(remediation)
    return db.employers.get(case["employer_id"]) if case else None


@bp.post("/control-remediations")
def create_remediation():
    authenticate((R_ADMIN, R_AUDITOR))
    body = get_body()
    case = None
    if isinstance(body.get("correction_case_id"), str) and body["correction_case_id"]:
        case = get_case(body["correction_case_id"])
    data = validate(body, REMEDIATION_CREATE)

    row = new_row({
        "correction_case_id": case["id"],
        "root_cause_code": data["root_cause_code"],
        "control_gap_class": data["control_gap_class"],
        "owner_user_id": data["owner_user_id"],
        "target_date": data["target_date"],
        "evidence_reference": None,
        "verified_by_user_id": None,
        "verification_round": 0,
        "status": "OPEN",
        "verified_at": None,
    })
    db.control_remediations[row["id"]] = row
    calc.sync_employer(db.employers.get(case["employer_id"]))
    return ok(remediation_json(row), 201)


@bp.get("/control-remediations/<control_remediation_id>")
def read_remediation(control_remediation_id):
    actor = authenticate(READ6)
    row = get_remediation(control_remediation_id)
    employer = _remediation_employer(row)
    actor.require_employer(employer["id"] if employer else None)
    return ok(remediation_json(row))


@bp.get("/control-remediations")
def list_remediations():
    actor = authenticate(READ6)
    limit, offset = pagination()
    filters = {
        "correction_case_id": qs("correction_case_id"),
        "root_cause_code": qs("root_cause_code"),
        "control_gap_class": qs("control_gap_class"),
        "status": qs("status"),
    }
    rows = [r for r in sorted_rows(db.control_remediations.values()) if matches(r, filters)]
    if actor.role == "EmployerRep":
        kept = []
        for row in rows:
            employer = _remediation_employer(row)
            if employer is not None and employer["id"] == actor.user_id:
                kept.append(row)
        rows = kept
    return paginate(rows, limit, offset, remediation_json)


@bp.post("/control-remediations/<control_remediation_id>/assign")
def assign_remediation(control_remediation_id):
    authenticate((R_ADMIN, R_AUDITOR))
    row = get_remediation(control_remediation_id)
    body = get_body()
    data = validate(body, {
        "owner_user_id": F("string", True, min_len=1, max_len=120),
        "target_date": F("datetime", False),
    })

    require_state(row["status"], ("OPEN", "VERIFICATION_FAILED"), TERMINAL)

    row["owner_user_id"] = data["owner_user_id"]
    if "target_date" in data:
        row["target_date"] = data["target_date"]
    touch(row)
    return ok(remediation_json(row))


@bp.post("/control-remediations/<control_remediation_id>/submit-verification")
def submit_verification(control_remediation_id):
    authenticate((R_ADMIN, R_AUDITOR, R_ANALYST))
    row = get_remediation(control_remediation_id)
    body = get_body()
    data = validate(body, {"evidence_reference": F("string", True, min_len=1, max_len=500)})

    require_state(row["status"], ("OPEN", "VERIFICATION_FAILED"), TERMINAL)
    if row["status"] == "OPEN" and not row["owner_user_id"]:
        fail("ERR_INVALID_STATE",
             "an unowned remediation cannot be submitted for verification")

    row["evidence_reference"] = data["evidence_reference"]
    row["verification_round"] += 1
    row["status"] = "SUBMITTED_FOR_VERIFICATION"
    touch(row)
    return ok(remediation_json(row))


@bp.post("/control-remediations/<control_remediation_id>/verify")
def verify_remediation(control_remediation_id):
    actor = authenticate((R_ADMIN, R_AUDITOR))
    row = get_remediation(control_remediation_id)
    body = get_body()
    data = validate(body, {
        "passed": F("boolean", True),
        "verification_note": F("string", False, max_len=2000),
    })

    require_state(row["status"], ("SUBMITTED_FOR_VERIFICATION",), TERMINAL)
    if actor.user_id == row["owner_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES_VIOLATION",
             "the owner may not verify their own remediation")

    if data["passed"]:
        row["status"] = "VERIFIED"
        row["verified_by_user_id"] = actor.user_id
        row["verified_at"] = now()
    else:
        row["status"] = "VERIFICATION_FAILED"
        row["verified_by_user_id"] = None
        row["verified_at"] = None
    touch(row)

    calc.sync_employer(_remediation_employer(row))
    return ok(remediation_json(row))
