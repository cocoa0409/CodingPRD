"""Post-test verification reports: drafting, the two reduction bases, issuance."""

from flask import Blueprint

import calc
import cascade
import lookup
import serialize
from envelope import array_response, object_response
from errors import ApiError
from guard import (ALL_ROLES, ROLE_QA_VERIFIER, authenticate, body, fk_candidate,
                   pagination, qenum, qstr, vid, vint, vstr)
from routes import PREFIX
from store import by_created, db, new_record, touch

bp = Blueprint("reports", __name__)


def _post_combustion_gate(project, program):
    """Rung 8(b).  Required whenever the program demands it and equally when the
    project has no program at all."""
    if project is None:
        return
    if program is not None and not program["combustion_safety_required"]:
        return
    ok_count, has_fail = lookup.combustion_coverage(project, "POST")
    if has_fail:
        raise ApiError("ERR_COMBUSTION_SPILLAGE_FAIL",
                       "A POST-phase combustion test on this project failed.")
    if ok_count < project["gas_appliance_count"]:
        raise ApiError("ERR_COMBUSTION_SAFETY_REQUIRED",
                       "POST-phase combustion coverage is incomplete.")


@bp.post(PREFIX + "/verification-reports")
def create_verification_report():
    authenticate((ROLE_QA_VERIFIER,))
    data = body()
    # --- rung 4 ---
    job_id = fk_candidate(data, "seal_job_id")
    if job_id is None:
        vid(data, "seal_job_id")
    job = lookup.seal_job_or_404(job_id)

    post_test_id = fk_candidate(data, "post_test_id")
    if post_test_id is None:
        vid(data, "post_test_id")
    post_test = lookup.leakage_test_or_404(post_test_id)

    # --- rung 5 ---
    expected = vint(data, "expected_seal_job_version", minimum=0)
    # --- rung 7 ---
    if expected != job["version"]:
        raise ApiError("ERR_STALE_SEAL_JOB_VERSION",
                       "expected_seal_job_version does not match the seal job.")
    # --- rung 9 ---
    if post_test["duct_system_id"] != job["duct_system_id"]:
        raise ApiError("ERR_PRE_TEST_SYSTEM_MISMATCH",
                       "The post-test belongs to a different duct system.")
    if post_test["phase"] != "POST" or post_test["status"] != "ACCEPTED":
        raise ApiError("ERR_TEST_PHASE_MISMATCH",
                       "The post-test must be an ACCEPTED POST-phase measurement.")

    system = db.duct_systems.get(job["duct_system_id"])
    project = lookup.project_of_system(system) if system is not None else None
    program = lookup.program_of_project(project) if project is not None else None
    pre_test = db.leakage_tests.get(job["pre_test_id"])

    pre_value = pre_test["normalized_leakage_cfm25"] if pre_test is not None else None
    post_value = post_test["normalized_leakage_cfm25"]
    system_basis = calc.reduction_pct(pre_value, post_value)

    candidates = []
    accepted_post = {}
    if project is not None:
        for candidate in lookup.duct_systems_of_project(project["id"]):
            if candidate["eligibility_status"] != "ELIGIBLE":
                continue
            if candidate.get("baseline_leakage_cfm25") is None:
                continue
            candidates.append(candidate)
            accepted_post[candidate["id"]] = lookup.latest_accepted_post_test(candidate["id"])
    cfm_reduced, whole_house = calc.whole_house_basis(candidates, accepted_post)

    threshold = program["min_reduction_pct"] if program is not None \
        else calc.GUARANTEE_DEFAULT_MIN_PCT

    # drafting supersedes any earlier draft on the same run
    for earlier in lookup.reports_of_job(job["id"]):
        if earlier["status"] != "DRAFT":
            continue
        earlier["status"] = "VOIDED"
        touch(earlier)

    row = new_record()
    row.update({
        "seal_job_id": job["id"],
        "post_test_id": post_test["id"],
        "status": "DRAFT",
        "pre_leakage_cfm25": pre_value,
        "post_leakage_cfm25": post_value,
        "reduction_pct_system_basis": system_basis,
        "reduction_pct_whole_house_basis": whole_house,
        "cfm_reduced_whole_house": cfm_reduced,
        "guarantee_threshold_pct": calc.rhu(threshold, 2),
        "guarantee_met": system_basis >= calc.dec(threshold),
        "issued_by_user_id": None,
        "issued_at": None,
        "signature_note": None,
        "correction_round": 0,
    })
    db.verification_reports[row["id"]] = row
    touch(job)
    return object_response(serialize.verification_report(row), 201)


@bp.get(PREFIX + "/verification-reports/<report_id>")
def read_verification_report(report_id):
    authenticate(ALL_ROLES)
    row = lookup.report_or_404(report_id)
    return object_response(serialize.verification_report(row))


@bp.get(PREFIX + "/verification-reports")
def list_verification_reports():
    authenticate(ALL_ROLES)
    seal_job_id = qstr("seal_job_id")
    post_test_id = qstr("post_test_id")
    status = qenum("status", calc.REPORT_STATUS)
    limit, offset = pagination()
    rows = []
    for row in by_created(db.rows("verification_reports")):
        if seal_job_id is not None and row["seal_job_id"] != seal_job_id:
            continue
        if post_test_id is not None and row["post_test_id"] != post_test_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    window = rows[offset:offset + limit]
    return array_response([serialize.verification_report(r) for r in window],
                          limit, offset, len(rows))


@bp.post(PREFIX + "/verification-reports/<report_id>/issue")
def issue_verification_report(report_id):
    user_id, _role = authenticate((ROLE_QA_VERIFIER,))
    report = lookup.report_or_404(report_id)
    job = db.seal_jobs.get(report["seal_job_id"])
    # --- rung 3: the run's own technician may not issue its report ---
    if job is not None and user_id == job["technician_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The run's technician cannot issue its verification report.")
    data = body()
    signature_note = vstr(data, "signature_note")
    # --- rung 6 ---
    if report["status"] not in ("DRAFT", "CORRECTION_REQUIRED"):
        raise ApiError("ERR_REPORT_INVALID_STATE",
                       "Issuance requires status DRAFT or CORRECTION_REQUIRED.")
    from_draft = report["status"] == "DRAFT"
    if from_draft and (job is None or job["status"] != "SEALED"):
        raise ApiError("ERR_SEAL_JOB_INVALID_STATE",
                       "Issuing a draft report requires the run to be SEALED.")

    system = db.duct_systems.get(job["duct_system_id"]) if job is not None else None
    project = lookup.project_of_system(system) if system is not None else None
    program = lookup.program_of_project(project) if project is not None else None
    # --- rung 8: post-phase coverage, then the safety hold ---
    if from_draft:
        _post_combustion_gate(project, program)
    if project is not None and project["status"] == "SAFETY_HOLD":
        raise ApiError("ERR_PROJECT_SAFETY_HOLD", "The project is on safety hold.")
    # --- rung 12 ---
    if not report["guarantee_met"]:
        raise ApiError("ERR_GUARANTEE_NOT_MET",
                       "The system-basis reduction does not meet the guarantee "
                       "threshold.")

    cascade.stamp_issuance(report, user_id, signature_note)
    touch(report)
    if job is not None:
        job["status"] = "VERIFIED"
        job["warranty_suspended"] = False
        touch(job)
        cascade.close_parent_retest(job)
    if system is not None and system["seal_status"] != "VERIFIED":
        system["seal_status"] = "VERIFIED"
        touch(system)
    return object_response(serialize.verification_report(report))
