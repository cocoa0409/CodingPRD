"""ProfessionalJudgmentCase endpoints (PRD 3.5) with SoD and OCC."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_FIELD_CONSTRAINT,
    ERR_SEGREGATION_OF_DUTIES, ERR_STALE_PJ_VERSION,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_response
from services.core import new_record, public, touch, current_isir
from services.packaging import maybe_mark_needs_repack
from validate import (
    get_body, req_str, req_int, req_enum, opt_bool,
    require_path_resource, deferred_body_ref,
)

bp = Blueprint("pj", __name__)

DIRECTOR_OFFICER = ["AidDirector", "AidOfficer"]
ADJUSTMENT_TYPES = ("EFC_ADJUSTMENT", "COA_ADJUSTMENT", "DEPENDENCY_OVERRIDE")


@bp.post("/pj-cases")
def create_pj_case():
    authorized(["AidOfficer"])
    body = get_body()
    # Rung 4: body foreign keys (absent keys defer to the rung-9 shape check).
    student = deferred_body_ref("students", body, "student_id")
    aid_year = deferred_body_ref("aid_years", body, "aid_year_id")
    # Rung 9: shape.
    req_str(body, "student_id")
    req_str(body, "aid_year_id")
    adjustment_type = req_enum(body, "adjustment_type", ADJUSTMENT_TYPES)
    delta = req_int(body, "requested_delta_cents")
    justification = req_str(body, "justification")
    if len(justification) < 20:
        raise_error(ERR_INVALID_REQUEST,
                    "justification must be at least twenty characters")
    documentation_complete = opt_bool(body, "documentation_complete", False)
    # Rung 10: the delta's sign must match the adjustment type.
    if adjustment_type == "EFC_ADJUSTMENT" and delta > 0:
        raise_error(ERR_FIELD_CONSTRAINT,
                    "an EFC adjustment may only lower the EFC: requested_delta_cents "
                    "must be zero or negative")
    if adjustment_type == "COA_ADJUSTMENT" and delta <= 0:
        raise_error(ERR_FIELD_CONSTRAINT,
                    "a COA adjustment's requested_delta_cents must be strictly positive")
    if adjustment_type == "DEPENDENCY_OVERRIDE" and delta != 0:
        raise_error(ERR_FIELD_CONSTRAINT,
                    "a dependency override's requested_delta_cents must be exactly zero")
    rec = new_record("pj_cases", {
        "student_id": student["id"],
        "aid_year_id": aid_year["id"],
        "adjustment_type": adjustment_type,
        "requested_delta_cents": delta,
        "justification": justification,
        "documentation_complete": documentation_complete,
        "status": "SUBMITTED",
        "reviewed_by_user_id": None,
        "decided_by_user_id": None,
        "applied_efc_delta_cents": 0,
        "applied_coa_delta_cents": 0,
    })
    return success_object(public(rec), status=201)


@bp.get("/pj-cases")
def list_pj_cases():
    authorized(DIRECTOR_OFFICER)
    return list_response("pj_cases", {
        "student_id": request.args.get("student_id"),
        "aid_year_id": request.args.get("aid_year_id"),
        "status": request.args.get("status"),
    })


@bp.get("/pj-cases/<rid>")
def get_pj_case(rid):
    authorized(DIRECTOR_OFFICER)
    rec = require_path_resource("pj_cases", rid)
    return success_object(public(rec))


@bp.post("/pj-cases/<rid>/begin-review")
def begin_review(rid):
    caller = authorized(["AidOfficer"])
    case = require_path_resource("pj_cases", rid)
    if case["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE,
                    f"case is {case['status']}, expected SUBMITTED")
    case["status"] = "UNDER_REVIEW"
    case["reviewed_by_user_id"] = caller.user_id
    touch(case)
    return success_object(public(case))


@bp.post("/pj-cases/<rid>/approve")
def approve(rid):
    caller = authorized(["AidDirector"])
    case = require_path_resource("pj_cases", rid)
    # Rung 5: state legality and the approval guards that are transition
    # preconditions (PRD 3.5 "Approval is guarded more heavily").
    if case["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE,
                    f"case is {case['status']}, expected UNDER_REVIEW")
    if not case["documentation_complete"]:
        raise_error(ERR_INVALID_STATE,
                    "documentation_complete must be true before approval")
    # Rung 7: segregation of duties — the deciding caller must differ from
    # reviewed_by_user_id.
    if caller.user_id == case["reviewed_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "the deciding caller must differ from the reviewing officer")
    # Rung 9: the OCC field must be carried by the request.
    body = get_body()
    expected = req_int(body, "expected_pj_version")
    # Type-specific approval guards.
    student = db.students.get(case["student_id"])
    if case["adjustment_type"] == "EFC_ADJUSTMENT":
        isir = current_isir(case["student_id"], case["aid_year_id"])
        official = isir["efc_official_cents"] if isir is not None else 0
        if official + case["requested_delta_cents"] < 0:
            raise_error(ERR_INVALID_STATE,
                        "the requested delta would push the official EFC below zero")
    elif case["adjustment_type"] == "COA_ADJUSTMENT":
        if case["requested_delta_cents"] <= 0:
            raise_error(ERR_INVALID_STATE,
                        "a COA adjustment's delta must be positive")
    elif case["adjustment_type"] == "DEPENDENCY_OVERRIDE":
        if student is None or student["dependency_status"] != "DEPENDENT":
            raise_error(ERR_INVALID_STATE,
                        "a dependency override requires the student to be DEPENDENT")
    # Rung 14: optimistic concurrency.
    if expected != case["version"]:
        raise_error(ERR_STALE_PJ_VERSION,
                    "expected_pj_version does not match the case's current version")

    # --- apply the decision -------------------------------------------------
    case["decided_by_user_id"] = caller.user_id
    if case["adjustment_type"] == "EFC_ADJUSTMENT":
        case["applied_efc_delta_cents"] = case["requested_delta_cents"]
    elif case["adjustment_type"] == "COA_ADJUSTMENT":
        case["applied_coa_delta_cents"] = case["requested_delta_cents"]
    case["status"] = "APPROVED"
    touch(case)
    if case["adjustment_type"] == "DEPENDENCY_OVERRIDE" and student is not None:
        student["dependency_status"] = "INDEPENDENT"
        touch(student)
    # Drift against a package's frozen snapshots flags needs_repack (PRD 3.5).
    maybe_mark_needs_repack(case["student_id"], case["aid_year_id"])
    return success_object(public(case))


@bp.post("/pj-cases/<rid>/deny")
def deny(rid):
    caller = authorized(["AidDirector"])
    case = require_path_resource("pj_cases", rid)
    if case["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE,
                    f"case is {case['status']}, expected UNDER_REVIEW")
    if caller.user_id == case["reviewed_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "the deciding caller must differ from the reviewing officer")
    case["status"] = "DENIED"
    case["decided_by_user_id"] = caller.user_id
    touch(case)
    return success_object(public(case))
