"""Rebate claims: the frozen payable amount, the inspector spot check, payment."""

from flask import Blueprint

import calc
import cascade
import lookup
import serialize
from envelope import array_response, object_response
from errors import ApiError
from guard import (ALL_ROLES, ROLE_PROGRAM_ADMIN, ROLE_UTILITY_INSPECTOR, authenticate,
                   body, fk_candidate, pagination, qenum, qstr, vid, vnum, vstr)
from routes import PREFIX
from store import by_created, db, new_record, touch

bp = Blueprint("claims", __name__)


def _project_of_report(report):
    job = db.seal_jobs.get(report["seal_job_id"])
    if job is None:
        return None
    system = db.duct_systems.get(job["duct_system_id"])
    if system is None:
        return None
    return lookup.project_of_system(system)


def _assert_reduction_and_budget(program, claim_payable, report):
    """Rung 12 (b) then (c)."""
    if calc.dec(report["reduction_pct_whole_house_basis"]) \
            < calc.dec(program["min_reduction_pct"]):
        raise ApiError("ERR_REBATE_REDUCTION_BELOW_PROGRAM_MINIMUM",
                       "The whole-house reduction is below the program minimum.")
    if claim_payable > lookup.remaining_budget(program):
        raise ApiError("ERR_PROGRAM_BUDGET_EXCEEDED",
                       "The payable amount exceeds the program's remaining budget.")


@bp.post(PREFIX + "/rebate-claims")
def create_rebate_claim():
    authenticate((ROLE_PROGRAM_ADMIN,))
    data = body()
    # --- rung 4 ---
    report_id = fk_candidate(data, "verification_report_id")
    if report_id is None:
        vid(data, "verification_report_id")
    report = lookup.report_or_404(report_id)

    program_id = fk_candidate(data, "utility_program_id")
    if program_id is None:
        vid(data, "utility_program_id")
    program = lookup.program_or_404(program_id)

    # --- rung 5 ---
    bundle_ref = vstr(data, "documentation_bundle_ref")
    # --- rung 6 ---
    if report["status"] != "ISSUED":
        raise ApiError("ERR_REPORT_INVALID_STATE",
                       "A claim may only be built on an ISSUED verification report.")
    project = _project_of_report(report)
    # --- rung 8 ---
    if project is not None and project["status"] == "SAFETY_HOLD":
        raise ApiError("ERR_PROJECT_SAFETY_HOLD", "The project is on safety hold.")
    # --- rung 9 ---
    if project is None or not project.get("utility_program_id") \
            or project["utility_program_id"] != program["id"]:
        raise ApiError("ERR_PROGRAM_MISMATCH",
                       "utility_program_id does not match the project's program.")

    # --- rung 12: the reduction gate first, then the money it unlocks ---
    money = calc.rebate_payable_amount(program, project, report)
    _assert_reduction_and_budget(program, money["payable_cents"], report)

    row = new_record()
    row.update({
        "verification_report_id": report["id"],
        "utility_program_id": program["id"],
        "documentation_bundle_ref": bundle_ref,
        "status": "SUBMITTED",
        "inspector_user_id": None,
        "spot_check_leakage_cfm": None,
        "spot_check_pressure_pa": None,
        "spot_check_cfm25": None,
        "inspector_variance_pct": None,
        "inspector_outcome": "PENDING",
        "resubmission_count": 0,
        "payment_reference": None,
    })
    row.update(money)
    db.rebate_claims[row["id"]] = row
    touch(program)
    return object_response(serialize.rebate_claim(row), 201)


@bp.get(PREFIX + "/rebate-claims/<claim_id>")
def read_rebate_claim(claim_id):
    authenticate(ALL_ROLES)
    row = lookup.claim_or_404(claim_id)
    return object_response(serialize.rebate_claim(row))


@bp.get(PREFIX + "/rebate-claims")
def list_rebate_claims():
    authenticate(ALL_ROLES)
    report_id = qstr("verification_report_id")
    program_id = qstr("utility_program_id")
    status = qenum("status", calc.CLAIM_STATUS)
    limit, offset = pagination()
    rows = []
    for row in by_created(db.rows("rebate_claims")):
        if report_id is not None and row["verification_report_id"] != report_id:
            continue
        if program_id is not None and row["utility_program_id"] != program_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    window = rows[offset:offset + limit]
    return array_response([serialize.rebate_claim(r) for r in window],
                          limit, offset, len(rows))


@bp.post(PREFIX + "/rebate-claims/<claim_id>/inspector-verification")
def inspector_verification(claim_id):
    user_id, _role = authenticate((ROLE_UTILITY_INSPECTOR,))
    claim = lookup.claim_or_404(claim_id)
    report = db.verification_reports.get(claim["verification_report_id"])
    # --- rung 3: the verifier who issued the report cannot spot-check it ---
    if report is not None and report.get("issued_by_user_id") is not None \
            and user_id == report["issued_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The verifier who issued the report cannot perform the "
                       "inspector spot check.")
    data = body()
    # --- rung 5 ---
    leakage = vnum(data, "spot_check_leakage_cfm", minimum=0)
    pressure = vnum(data, "spot_check_pressure_pa", exclusive_minimum=0)
    # --- rung 6 ---
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_INVALID_STATE",
                       "The spot check is legal only from SUBMITTED.")
    if report is None or report["status"] != "ISSUED":
        raise ApiError("ERR_REPORT_INVALID_STATE",
                       "The spot check requires the report to be ISSUED.")

    spot_cfm25, variance, outcome = calc.inspector_spot_check(
        leakage, pressure, report["post_leakage_cfm25"])
    program = db.utility_programs.get(claim["utility_program_id"])

    claim["inspector_user_id"] = user_id
    claim["spot_check_leakage_cfm"] = leakage
    claim["spot_check_pressure_pa"] = pressure
    claim["spot_check_cfm25"] = spot_cfm25
    claim["inspector_variance_pct"] = variance
    claim["inspector_outcome"] = outcome
    if outcome == "PASS":
        claim["status"] = "APPROVED"
        touch(claim)
    else:
        # hop 1 on the claim, then hops 2 and 3 on the report and its run
        claim["status"] = "RETURNED_FOR_CORRECTION"
        touch(claim)
        cascade.inspector_failure_cascade(report, program)
    return object_response(serialize.rebate_claim(claim))


@bp.post(PREFIX + "/rebate-claims/<claim_id>/resubmit")
def resubmit_rebate_claim(claim_id):
    authenticate((ROLE_PROGRAM_ADMIN,))
    claim = lookup.claim_or_404(claim_id)
    data = body()
    bundle_ref = vstr(data, "documentation_bundle_ref")
    # --- rung 6 ---
    if claim["status"] != "RETURNED_FOR_CORRECTION":
        raise ApiError("ERR_CLAIM_INVALID_STATE",
                       "Resubmission is legal only from RETURNED_FOR_CORRECTION.")
    report = db.verification_reports.get(claim["verification_report_id"])
    if report is None or report["status"] != "ISSUED":
        raise ApiError("ERR_REPORT_INVALID_STATE",
                       "Resubmission requires the report to have been re-issued.")
    project = _project_of_report(report)
    # --- rung 8 ---
    if project is not None and project["status"] == "SAFETY_HOLD":
        raise ApiError("ERR_PROJECT_SAFETY_HOLD", "The project is on safety hold.")
    # --- rung 12: nothing is recomputed, but both gates are re-applied ---
    program = db.utility_programs.get(claim["utility_program_id"])
    if program is not None:
        _assert_reduction_and_budget(program, claim["payable_cents"], report)

    claim["status"] = "SUBMITTED"
    claim["resubmission_count"] = claim["resubmission_count"] + 1
    claim["documentation_bundle_ref"] = bundle_ref
    claim["inspector_outcome"] = "PENDING"
    claim["spot_check_leakage_cfm"] = None
    claim["spot_check_pressure_pa"] = None
    claim["spot_check_cfm25"] = None
    claim["inspector_variance_pct"] = None
    claim["inspector_user_id"] = None
    touch(claim)
    if program is not None:
        touch(program)
    return object_response(serialize.rebate_claim(claim))


@bp.post(PREFIX + "/rebate-claims/<claim_id>/pay")
def pay_rebate_claim(claim_id):
    authenticate((ROLE_PROGRAM_ADMIN,))
    claim = lookup.claim_or_404(claim_id)
    data = body()
    payment_reference = vstr(data, "payment_reference")
    # --- rung 6 ---
    if claim["status"] != "APPROVED":
        raise ApiError("ERR_CLAIM_INVALID_STATE", "Payment is legal only from APPROVED.")
    program = db.utility_programs.get(claim["utility_program_id"])
    if program is not None and program["requires_inspector_verification"] \
            and claim["inspector_outcome"] != "PASS":
        raise ApiError("ERR_CLAIM_INVALID_STATE",
                       "The program requires a passing inspector spot check before "
                       "payment.")

    claim["status"] = "PAID"
    claim["payment_reference"] = payment_reference
    touch(claim)
    if program is not None:
        touch(program)
    return object_response(serialize.rebate_claim(claim))
