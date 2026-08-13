"""Patient case endpoints: intake, listing, final coding, close."""
from flask import Blueprint, request

import db
from calc import (
    agreed_indicators,
    applicable_targets,
    compute_priority,
    target_unmet,
)
from errors import raise_error
from helpers import (
    body_ref,
    dec4,
    get_or_404,
    list_page,
    make_record,
    num4,
    require_program_active,
    touch,
    validate_weight,
)
from middleware import (
    check_known_fields,
    get_json_body,
    require_fields,
    require_roles,
    validate_integer,
    validate_period,
    validate_string,
)
from response import success_list, success_object
from serializers import case_out, reconciliation_out, review_out

bp = Blueprint("cases", __name__)

LIST_ROLES = {"CDIManager", "CDISpecialist", "HIMCoder", "ComplianceAuditor"}
GET_ROLES = LIST_ROLES | {"Provider"}


@bp.route("/api/patient-cases", methods=["POST"])
def create_case():
    require_roles({"HIMCoder"})
    body = get_json_body()
    check_known_fields(body, {
        "cdi_program_id", "mrn", "admission_period", "discharge_period",
        "attending_provider_id", "initial_drg_code", "initial_drg_weight",
    })
    require_fields(body, [
        "cdi_program_id", "mrn", "admission_period", "discharge_period",
        "attending_provider_id", "initial_drg_code", "initial_drg_weight",
    ])
    program = body_ref(body, "cdi_program_id", db.programs, "program")
    mrn = validate_string(body["mrn"], "mrn")
    admission_period = validate_period(body["admission_period"], "admission_period")
    discharge_period = validate_period(body["discharge_period"], "discharge_period")
    if discharge_period < admission_period:
        raise_error(
            "ERR_INVALID_REQUEST",
            "discharge_period must be >= admission_period",
        )
    provider = body_ref(body, "attending_provider_id", db.providers, "provider")
    if provider["cdi_program_id"] != program["id"]:
        raise_error(
            "ERR_INVALID_REQUEST",
            "attending_provider_id does not belong to the case's program",
        )
    initial_drg_code = validate_string(body["initial_drg_code"], "initial_drg_code")
    initial_drg_weight = validate_weight(body["initial_drg_weight"], "initial_drg_weight")
    require_program_active(program)
    for c in db.cases.values():
        if c["cdi_program_id"] == program["id"] and c["mrn"] == mrn:
            raise_error(
                "ERR_INVALID_REQUEST",
                f"mrn {mrn!r} already registered in this program",
            )
    case = make_record(db.cases, {
        "cdi_program_id": program["id"],
        "mrn": mrn,
        "admission_period": admission_period,
        "discharge_period": discharge_period,
        "attending_provider_id": provider["id"],
        "initial_drg_code": initial_drg_code,
        "initial_drg_weight": initial_drg_weight,
        "working_drg_code": initial_drg_code,
        "working_drg_weight": initial_drg_weight,
        "working_soi": 1,
        "working_rom": 1,
        "priority_score": 0.0,
        "reconciliation_status": "NOT_REQUIRED",
        "status": "OPEN",
        "_finalized_period": None,
    })
    # Residual variant at creation (no open queries): base opportunity is 0.
    compute_priority(case)
    return success_object(case_out(case), status=201)


@bp.route("/api/patient-cases", methods=["GET"])
def list_cases():
    require_roles(LIST_ROLES)
    program_id = request.args.get("cdi_program_id")
    status = request.args.get("status")
    attending = request.args.get("attending_provider_id")
    min_raw = request.args.get("priority_score_min")
    min_score = None
    if min_raw is not None:
        try:
            min_score = float(min_raw)
        except (TypeError, ValueError):
            raise_error("ERR_INVALID_REQUEST", "priority_score_min must be a number")
    items = list(db.cases.values())
    if program_id is not None:
        items = [c for c in items if c["cdi_program_id"] == program_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if attending is not None:
        items = [c for c in items if c["attending_provider_id"] == attending]
    if min_score is not None:
        items = [c for c in items if c["priority_score"] >= min_score]
    page, limit, offset, total = list_page(items)
    return success_list([case_out(c) for c in page], limit, offset, total)


@bp.route("/api/patient-cases/<caseId>", methods=["GET"])
def get_case(caseId):
    require_roles(GET_ROLES)
    case = get_or_404(db.cases, caseId, "case")
    return success_object(case_out(case))


@bp.route("/api/patient-cases/<caseId>/reviews", methods=["GET"])
def list_case_reviews(caseId):
    require_roles(LIST_ROLES)
    get_or_404(db.cases, caseId, "case")
    status = request.args.get("status")
    items = [r for r in db.reviews.values() if r["patient_case_id"] == caseId]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, limit, offset, total = list_page(items)
    return success_list([review_out(r) for r in page], limit, offset, total)


@bp.route("/api/patient-cases/<caseId>/reconciliations", methods=["GET"])
def list_case_reconciliations(caseId):
    require_roles(LIST_ROLES)
    get_or_404(db.cases, caseId, "case")
    status = request.args.get("status")
    items = [e for e in db.reconciliations.values() if e["patient_case_id"] == caseId]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    page, limit, offset, total = list_page(items)
    return success_list([reconciliation_out(e) for e in page], limit, offset, total)


@bp.route("/api/patient-cases/<caseId>/finalize-coding", methods=["POST"])
def finalize_coding(caseId):
    user_id, _ = require_roles({"HIMCoder"})
    case = get_or_404(db.cases, caseId, "case")
    program = db.programs.get(case["cdi_program_id"])
    require_program_active(program)
    # State precondition (priority 5).
    if case["status"] not in ("OPEN", "UNDER_REVIEW", "RECONCILED"):
        raise_error(
            "ERR_INVALID_STATE",
            f"Case in {case['status']} cannot be finalized",
        )
    body = get_json_body()
    check_known_fields(
        body, {"coder_drg_code", "coder_drg_weight", "expected_case_version"}
    )
    # OCC (PRD 2.8): expected_case_version is non-optional.
    if "expected_case_version" not in body or body["expected_case_version"] is None:
        raise_error("ERR_INVALID_REQUEST", "expected_case_version is required")
    expected = validate_integer(body["expected_case_version"], "expected_case_version")
    if expected != case["version"]:
        raise_error(
            "ERR_STALE_VERSION",
            "expected_case_version does not match the case's current version",
        )
    require_fields(body, ["coder_drg_code", "coder_drg_weight"])
    coder_code = validate_string(body["coder_drg_code"], "coder_drg_code")
    coder_weight = validate_weight(body["coder_drg_weight"], "coder_drg_weight")
    # Business rules in PRD 3.7 order.
    now_p = program["current_period_index"]
    if now_p < case["discharge_period"]:
        raise_error(
            "ERR_CASE_NOT_DISCHARGED",
            "current_period_index has not reached the case's discharge_period",
        )
    for r in db.reviews.values():
        if r["patient_case_id"] == case["id"] and r["status"] in (
            "DRAFT", "ACTIVE", "ON_HOLD",
        ):
            raise_error(
                "ERR_OPEN_REVIEW_EXISTS",
                "A review in DRAFT/ACTIVE/ON_HOLD blocks final coding",
            )
    for q in db.queries.values():
        if q["patient_case_id"] == case["id"] and q["status"] in ("SENT", "ESCALATED"):
            raise_error(
                "ERR_UNRESOLVED_QUERY_EXISTS",
                "A query in SENT/ESCALATED blocks final coding",
            )
    if coder_code != case["working_drg_code"] or dec4(coder_weight) != dec4(
        case["working_drg_weight"]
    ):
        # Mismatch: open a ReconciliationEvent and reject the finalization.
        make_record(db.reconciliations, {
            "patient_case_id": case["id"],
            "cdi_program_id": case["cdi_program_id"],
            "coder_user_id": user_id,
            "coder_drg_code": coder_code,
            "coder_drg_weight": num4(coder_weight),
            "cdi_drg_code": case["working_drg_code"],
            "cdi_drg_weight": case["working_drg_weight"],
            "resolution_note": None,
            "status": "OPEN",
        })
        case["reconciliation_status"] = "PENDING"
        if case["status"] == "OPEN":
            case["status"] = "UNDER_REVIEW"
        touch(case)
        raise_error(
            "ERR_DRG_MISMATCH",
            "Coder DRG differs from the case's working DRG; reconciliation opened",
        )
    agreed = agreed_indicators(case)
    for target in applicable_targets(program["id"], case["working_drg_code"], now_p):
        if target_unmet(target, case, agreed):
            raise_error(
                "ERR_DENIAL_TARGET_UNMET",
                "An active DenialRiskTarget is not satisfied by this case",
            )
    case["status"] = "FINAL_CODED"
    case["_finalized_period"] = now_p
    touch(case)
    return success_object(case_out(case))


@bp.route("/api/patient-cases/<caseId>/close", methods=["POST"])
def close_case(caseId):
    require_roles({"CDIManager"})
    case = get_or_404(db.cases, caseId, "case")
    get_json_body()
    program = db.programs.get(case["cdi_program_id"])
    require_program_active(program)
    if case["status"] != "FINAL_CODED":
        raise_error("ERR_INVALID_STATE", "Only a FINAL_CODED case can be closed")
    case["status"] = "CLOSED"
    touch(case)
    return success_object(case_out(case))
