"""Conformance testing endpoints (PRD 3.2)."""
from flask import Blueprint, request

from db import commit, create, db, snapshot, touch
from errors import ApiError
from middleware import HIE_ADMIN, PARTICIPANT_ADMIN, authenticate, require_scope
from response import entity, entity_created, paginate, pagination
from services import repo
from services.conformance import (
    CONSECUTIVE_FAILURE_LIMIT,
    FAILURE_CATEGORIES,
    PROFILES,
    evaluate,
)
from services.counters import recompute_passed_profiles
from validate import (
    body,
    before,
    opt_enum_list,
    req_dt,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("conformance", __name__)

TERMINAL_TEST_STATES = ("PASSED", "WAIVED")


@bp.route("/hie/participants/<pid>/conformance-tests", methods=["POST"])
def book_run(pid):
    actor = authenticate((HIE_ADMIN, PARTICIPANT_ADMIN))
    require_scope(actor, pid)
    payload = body()
    profile = req_enum(payload, "profile", PROFILES)
    start_raw, start_dt = req_dt(payload, "scheduled_start")
    end_raw, end_dt = req_dt(payload, "scheduled_end")
    before(start_dt, end_dt, "scheduled_end must be strictly after scheduled_start.")

    participant = repo.must("participants", pid)

    prior = repo.where("conformance_tests", participant_id=pid, profile=profile)
    for test in prior:
        if test["status"] == "PASSED":
            raise ApiError("ERR_CONFORMANCE_PROFILE_ALREADY_PASSED")

    row = create(
        db.conformance_tests,
        "ConformanceTest",
        {
            "participant_id": pid,
            "profile": profile,
            "attempt_number": len(prior) + 1,
            "scheduled_start": start_raw,
            "scheduled_end": end_raw,
            "status": "RUNNING",
            "assertions_total": None,
            "assertions_passed": None,
            "pass_rate": None,
            "failure_categories": [],
            "critical_failure": False,
            "waiver_reason": None,
            "executed_by_user_id": actor.user_id,
        },
    )
    participant["conformance_attempt_count"] = (
        int(participant["conformance_attempt_count"] or 0) + 1
    )
    touch(participant)
    return entity_created(row)


@bp.route("/hie/conformance-tests/<tid>/results", methods=["POST"])
def record_results(tid):
    actor = authenticate((HIE_ADMIN,))
    payload = body()
    total = req_int(payload, "assertions_total", minimum=1)
    passed = req_int(payload, "assertions_passed", minimum=0, maximum=total)
    categories = opt_enum_list(payload, "failure_categories", FAILURE_CATEGORIES, [])

    test = repo.must("conformance_tests", tid)
    if test["status"] in TERMINAL_TEST_STATES:
        raise ApiError("ERR_TERMINAL_STATE")
    if test["status"] != "RUNNING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    participant = repo.must("participants", test["participant_id"])
    if participant["onboarding_status"] != "CONFORMANCE_TESTING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    pass_rate, critical, outcome = evaluate(total, passed, categories)
    test["assertions_total"] = total
    test["assertions_passed"] = passed
    test["failure_categories"] = list(categories)
    test["pass_rate"] = pass_rate
    test["critical_failure"] = critical
    test["status"] = outcome
    test["executed_by_user_id"] = actor.user_id
    touch(test)

    if outcome == "PASSED":
        recompute_passed_profiles(participant, test["profile"])
        participant["consecutive_failed_attempts"] = 0
    else:
        participant["consecutive_failed_attempts"] = (
            int(participant["consecutive_failed_attempts"] or 0) + 1
        )
        if (
            participant["consecutive_failed_attempts"] >= CONSECUTIVE_FAILURE_LIMIT
            and participant["onboarding_status"] == "CONFORMANCE_TESTING"
        ):
            participant["onboarding_status"] = "REMEDIATION"
            participant["remediation_count"] = (
                int(participant["remediation_count"] or 0) + 1
            )
    touch(participant)
    return entity(test)


@bp.route("/hie/conformance-tests/<tid>/waiver", methods=["POST"])
def waive_run(tid):
    authenticate((HIE_ADMIN,))
    payload = body()
    reason = req_str(payload, "waiver_reason")

    test = repo.must("conformance_tests", tid)
    if test["status"] in TERMINAL_TEST_STATES:
        raise ApiError("ERR_TERMINAL_STATE")
    if test["status"] != "FAILED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if test["critical_failure"]:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    participant = repo.must("participants", test["participant_id"])
    test["status"] = "WAIVED"
    test["waiver_reason"] = reason
    touch(test)
    recompute_passed_profiles(participant, test["profile"])
    participant["consecutive_failed_attempts"] = 0
    touch(participant)
    return entity(test)


@bp.route("/hie/conformance-tests/<tid>", methods=["GET"])
def read_run(tid):
    authenticate((HIE_ADMIN, PARTICIPANT_ADMIN))
    return entity(repo.must("conformance_tests", tid))


@bp.route("/hie/participants/<pid>/conformance-tests", methods=["GET"])
def list_runs(pid):
    authenticate((HIE_ADMIN, PARTICIPANT_ADMIN))
    limit, offset = pagination()
    repo.must("participants", pid)
    rows = repo.where("conformance_tests", participant_id=pid)
    profile = request.args.get("profile")
    status = request.args.get("status")
    if profile:
        rows = [r for r in rows if r["profile"] == profile]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, limit, offset)
