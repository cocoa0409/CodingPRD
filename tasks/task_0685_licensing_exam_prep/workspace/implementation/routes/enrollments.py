"""Enrollment aggregate routes (PRD §3.2-§3.7)."""
from flask import Blueprint, request

from db import db, stamp_create, touch
from response import success, list_success
from middleware import get_auth, require_role, pagination_params, paginate
from services import validate as V
from services.serialize import public, public_list
from services.calc import round_half_up_div
from services.lookups import (
    get_enrollment, get_learner, get_license_program, get_subscription_plan,
    get_ce_bundle, get_installment_scoped, assert_owner,
)
from services import enrollment_service as ES
from clock import clock
from errors import raise_err
import errors

bp = Blueprint("enrollments", __name__)


# --------------------------------------------------------------------------- #
# Create / read
# --------------------------------------------------------------------------- #
@bp.post("/enrollments")
def create_enrollment():
    user_id, role = get_auth()
    require_role(role, {"Learner"})
    data = V.body()
    learner_id = V.as_str(V.require(data, "learner_id"), "learner_id")
    license_program_id = V.as_str(V.require(data, "license_program_id"),
                                  "license_program_id")
    subscription_plan_id = V.as_str(V.require(data, "subscription_plan_id"),
                                    "subscription_plan_id")
    financed = V.as_bool(V.opt(data, "financed", False), "financed")
    ce_bundle_id = V.opt(data, "ce_bundle_id", None)

    # existence (priority 3) — validated left-to-right; program lookup raises 404
    learner = get_learner(learner_id)
    get_license_program(license_program_id)
    plan = get_subscription_plan(subscription_plan_id)
    # ownership (priority 4): learner_id must equal acting learner
    if learner["id"] != user_id:
        raise_err(errors.ERR_NOT_RESOURCE_OWNER, "not the resource owner")

    bundle = None
    if ce_bundle_id is not None:
        ce_bundle_id = V.as_str(ce_bundle_id, "ce_bundle_id")
        bundle = get_ce_bundle(ce_bundle_id)

    # referential compatibility (priority 8): any supplied CE bundle whose program
    # differs from the enrollment's program is rejected.
    if bundle is not None and bundle["license_program_id"] != license_program_id:
        raise_err(errors.ERR_REFERENCE_INCOMPATIBLE,
                  "CE bundle program does not match enrollment program")
    # When the plan does not include CE, ce_bundle_id stays null (PRD §3.2).
    if not plan["includes_ce"]:
        ce_bundle_id = None
        bundle = None

    rec = {
        "learner_id": learner_id,
        "license_program_id": license_program_id,
        "subscription_plan_id": subscription_plan_id,
        "ce_bundle_id": ce_bundle_id,
        "financed": financed,
        "financing_total_due_cents": plan["total_price_cents"],
        "financing_paid_cents": 0,
        "financing_balance_cents": plan["total_price_cents"],
        "questions_answered_total": 0,
        "completed_mock_count": 0,
        "readiness_score": 0,
        "projected_readiness_score": 0,
        "exam_outcome": "PENDING",
        "guarantee_eligible": False,
        "status": "DRAFT",
    }
    stamp_create(rec)
    db.enrollments[rec["id"]] = rec
    # materialize installment schedule (calc financing_schedule)
    ES.build_installments(rec, plan)
    return success(public(rec), status=201)


@bp.get("/enrollments/<eid>")
def get_enrollment_route(eid):
    user_id, role = get_auth()
    require_role(role, {"Learner", "ContentAdmin", "ExamProctor"})
    rec = get_enrollment(eid)
    if role == "Learner":
        assert_owner(rec, user_id)
    return success(public(rec))


@bp.get("/enrollments/<eid>/analytics")
def enrollment_analytics(eid):
    user_id, role = get_auth()
    require_role(role, {"Learner", "ContentAdmin", "ExamProctor"})
    rec = get_enrollment(eid)
    if role == "Learner":
        assert_owner(rec, user_id)
    return success(public(rec))


@bp.get("/enrollments")
def list_enrollments():
    user_id, role = get_auth()
    require_role(role, {"Learner", "ContentAdmin", "ExamProctor"})
    limit, offset = pagination_params()
    rows = list(db.enrollments.values())
    for key in ("learner_id", "license_program_id", "subscription_plan_id",
                "ce_bundle_id"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r.get(key) == val]
    rows.sort(key=lambda r: r["_seq"])
    window, total, has_more = paginate(rows, limit, offset)
    return list_success(public_list(window), limit, offset, total, has_more)


# --------------------------------------------------------------------------- #
# activate
# --------------------------------------------------------------------------- #
@bp.post("/enrollments/<eid>/activate")
def activate_enrollment(eid):
    user_id, role = get_auth()
    require_role(role, {"Learner"})
    enr = get_enrollment(eid)
    assert_owner(enr, user_id)
    if enr["status"] != "DRAFT":
        raise_err(errors.ERR_INVALID_STATE, "enrollment not in DRAFT")
    program = db.license_programs[enr["license_program_id"]]
    plan = db.subscription_plans[enr["subscription_plan_id"]]
    # preconditions
    if program["status"] != "PUBLISHED":
        raise_err(errors.ERR_PROGRAM_NOT_PUBLISHED, "program not PUBLISHED")
    if plan["status"] != "ACTIVE":
        raise_err(errors.ERR_PLAN_ARCHIVED, "plan archived")
    if enr["financed"]:
        first = next((i for i in ES.installments_of(eid)
                      if i["sequence_no"] == 1), None)
        if first is None or first["status"] != "PAID":
            raise_err(errors.ERR_DOWN_PAYMENT_UNPAID, "down payment unpaid")
    # side effects: materialize StudyPlanDomains (mastery=50, weight copied)
    for d in program["domain_weights"]:
        dom = {
            "enrollment_id": eid,
            "domain_code": d["domain_code"],
            "weight": d["weight"],
            "mastery": 50,
        }
        stamp_create(dom)
        db.study_plan_domains[dom["id"]] = dom
    enr["financing_total_due_cents"] = plan["total_price_cents"]
    ES.recompute_ledger(enr)
    ES.recompute_readiness(enr)
    enr["status"] = "ACTIVE"
    touch(enr)
    return success(public(enr))


# --------------------------------------------------------------------------- #
# restructure-financing (OCC-guarded)
# --------------------------------------------------------------------------- #
@bp.post("/enrollments/<eid>/restructure-financing")
def restructure_financing(eid):
    user_id, role = get_auth()
    require_role(role, {"Learner"})
    enr = get_enrollment(eid)
    assert_owner(enr, user_id)
    data = V.body()
    new_months = V.as_int(V.require(data, "new_financing_months"),
                          "new_financing_months", minimum=1, maximum=24)
    expected = V.as_int(V.require(data, "expected_enrollment_version"),
                        "expected_enrollment_version")
    # OCC check (priority 6) — before state check (priority 7)
    if expected != enr["version"]:
        raise_err(errors.ERR_STALE_ENROLLMENT_VERSION, "stale enrollment version")
    if enr["status"] not in ("DRAFT", "ACTIVE"):
        raise_err(errors.ERR_INVALID_STATE, "enrollment not in DRAFT/ACTIVE")
    plan = db.subscription_plans[enr["subscription_plan_id"]]
    # void prior DUE installments
    for i in ES.installments_of(eid):
        if i["status"] == "DUE":
            i["status"] = "VOID"
            touch(i)
    # regenerate schedule with the new month count
    plan_view = dict(plan)
    plan_view["financing_months"] = new_months
    ES.build_installments(enr, plan_view)
    ES.recompute_ledger(enr)
    touch(enr)
    return success(public(enr))


# --------------------------------------------------------------------------- #
# withdraw
# --------------------------------------------------------------------------- #
@bp.post("/enrollments/<eid>/withdraw")
def withdraw_enrollment(eid):
    user_id, role = get_auth()
    require_role(role, {"Learner"})
    enr = get_enrollment(eid)
    assert_owner(enr, user_id)
    if enr["status"] not in ("DRAFT", "ACTIVE"):
        raise_err(errors.ERR_INVALID_STATE, "enrollment not in DRAFT/ACTIVE")
    was_active = enr["status"] == "ACTIVE"
    if was_active and enr["exam_outcome"] != "PENDING":
        raise_err(errors.ERR_EXAM_ALREADY_CERTIFIED, "exam already certified")
    ES.void_due_installments(eid)
    if was_active:
        ES.drop_joined_memberships(eid)
    ES.recompute_ledger(enr)
    enr["status"] = "WITHDRAWN"
    touch(enr)
    return success(public(enr))


# --------------------------------------------------------------------------- #
# certify-exam
# --------------------------------------------------------------------------- #
@bp.post("/enrollments/<eid>/certify-exam")
def certify_exam(eid):
    user_id, role = get_auth()
    require_role(role, {"ExamProctor"})
    enr = get_enrollment(eid)
    data = V.body()
    outcome = V.as_enum(V.require(data, "outcome"), "outcome", {"PASS", "FAIL"})
    # PRD §3.5: certification is permitted only while exam_outcome is still PENDING;
    # a second certification attempt is rejected with ERR_EXAM_ALREADY_CERTIFIED.
    # This already-certified check takes precedence over the generic state check so a
    # repeat certification on a FAILED/PASSED enrollment surfaces the specific error.
    if enr["exam_outcome"] != "PENDING":
        raise_err(errors.ERR_EXAM_ALREADY_CERTIFIED, "exam already certified")
    if enr["status"] != "ACTIVE":
        raise_err(errors.ERR_INVALID_STATE, "enrollment not ACTIVE")
    plan = db.subscription_plans[enr["subscription_plan_id"]]

    if outcome == "PASS":
        if enr["financing_balance_cents"] > 0:
            raise_err(errors.ERR_BALANCE_OUTSTANDING, "balance outstanding")
        enr["exam_outcome"] = "PASS"
        enr["status"] = "PASSED"
        ES.drop_joined_memberships(eid)
        touch(enr)
    else:  # FAIL
        enr["exam_outcome"] = "FAIL"
        enr["guarantee_eligible"] = ES.guarantee_eligible(enr, plan)
        enr["status"] = "FAILED"
        touch(enr)
    return success(public(enr))


# --------------------------------------------------------------------------- #
# Installments
# --------------------------------------------------------------------------- #
@bp.get("/enrollments/<eid>/installments")
def list_installments(eid):
    user_id, role = get_auth()
    require_role(role, {"Learner", "ContentAdmin"})
    enr = get_enrollment(eid)
    if role == "Learner":
        assert_owner(enr, user_id)
    limit, offset = pagination_params()
    rows = ES.installments_of(eid)  # already sorted by sequence_no ASC
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    window, total, has_more = paginate(rows, limit, offset)
    return list_success(public_list(window), limit, offset, total, has_more)


@bp.post("/enrollments/<eid>/installments/<iid>/pay")
def pay_installment(eid, iid):
    user_id, role = get_auth()
    require_role(role, {"Learner"})
    enr = get_enrollment(eid)
    inst = get_installment_scoped(eid, iid)
    assert_owner(enr, user_id)
    # paying permitted only while enrollment in DRAFT or ACTIVE
    if enr["status"] not in ("DRAFT", "ACTIVE"):
        raise_err(errors.ERR_INVALID_STATE, "enrollment not in DRAFT/ACTIVE")
    if inst["status"] != "DUE":
        raise_err(errors.ERR_INVALID_STATE, "installment not DUE")
    inst["status"] = "PAID"
    touch(inst)
    ES.recompute_ledger(enr)
    touch(enr)
    return success(public(inst))


# --------------------------------------------------------------------------- #
# Study-plan domains
# --------------------------------------------------------------------------- #
@bp.get("/enrollments/<eid>/domains")
def list_domains(eid):
    user_id, role = get_auth()
    require_role(role, {"Learner", "ContentAdmin", "ExamProctor"})
    enr = get_enrollment(eid)
    if role == "Learner":
        assert_owner(enr, user_id)
    limit, offset = pagination_params()
    rows = ES.domains_of(eid)
    rows.sort(key=lambda r: r["_seq"])
    window, total, has_more = paginate(rows, limit, offset)
    return list_success(public_list(window), limit, offset, total, has_more)


# --------------------------------------------------------------------------- #
# Practice sessions
# --------------------------------------------------------------------------- #
@bp.post("/enrollments/<eid>/practice-sessions")
def create_practice_session(eid):
    user_id, role = get_auth()
    require_role(role, {"Learner"})
    enr = get_enrollment(eid)
    assert_owner(enr, user_id)
    data = V.body()
    domain_code = V.as_str(V.require(data, "domain_code"), "domain_code")
    answered_count = V.as_int(V.require(data, "answered_count"),
                              "answered_count", minimum=0)
    correct_count = V.as_int(V.require(data, "correct_count"),
                             "correct_count", minimum=0)
    if correct_count > answered_count:
        raise_err(errors.ERR_INVALID_REQUEST, "correct_count > answered_count")
    # referential: domain_code must match a StudyPlanDomain of the enrollment (pri 8)
    domain = next((d for d in ES.domains_of(eid)
                   if d["domain_code"] == domain_code), None)
    if domain is None:
        raise_err(errors.ERR_REFERENCE_INCOMPATIBLE,
                  "domain_code not a study-plan domain of the enrollment")
    # empty batch rejected (priority 13)
    if answered_count == 0:
        raise_err(errors.ERR_EMPTY_SESSION, "answered_count == 0")
    batch_pct = round_half_up_div(100 * correct_count, answered_count)
    rec = {
        "enrollment_id": eid,
        "domain_code": domain_code,
        "answered_count": answered_count,
        "correct_count": correct_count,
        "batch_pct": batch_pct,
        "status": "COMPLETED",
    }
    stamp_create(rec)
    db.practice_sessions[rec["id"]] = rec
    # EWMA mastery update on the matching domain
    ES.apply_mastery_update(domain, batch_pct)
    touch(domain)
    # counters + readiness recompute, re-version enrollment
    enr["questions_answered_total"] += answered_count
    ES.recompute_readiness(enr)
    touch(enr)
    return success(public(rec), status=201)


@bp.get("/enrollments/<eid>/practice-sessions")
def list_practice_sessions(eid):
    user_id, role = get_auth()
    require_role(role, {"Learner", "ContentAdmin", "ExamProctor"})
    enr = get_enrollment(eid)
    if role == "Learner":
        assert_owner(enr, user_id)
    limit, offset = pagination_params()
    rows = ES.practice_sessions_of(eid)
    domain_code = request.args.get("domain_code")
    if domain_code is not None:
        rows = [r for r in rows if r["domain_code"] == domain_code]
    rows.sort(key=lambda r: r["_seq"])
    window, total, has_more = paginate(rows, limit, offset)
    return list_success(public_list(window), limit, offset, total, has_more)


# --------------------------------------------------------------------------- #
# Mock exams
# --------------------------------------------------------------------------- #
@bp.post("/enrollments/<eid>/mock-exams")
def create_mock_exam(eid):
    user_id, role = get_auth()
    require_role(role, {"Learner"})
    enr = get_enrollment(eid)
    assert_owner(enr, user_id)
    data = V.body()
    raw_score = V.as_int(V.require(data, "raw_score"), "raw_score", minimum=0)
    item_count = V.as_int(V.require(data, "item_count"), "item_count", minimum=1)
    plan = db.subscription_plans[enr["subscription_plan_id"]]
    # is_overage: count prior COMPLETED mocks BEFORE this attempt
    prior_completed = sum(1 for m in ES.mocks_of(eid) if m["status"] == "COMPLETED")
    is_overage = prior_completed >= plan["included_mock_credits"]
    scaled_score = round_half_up_div(100 * raw_score, item_count)
    rec = {
        "enrollment_id": eid,
        "raw_score": raw_score,
        "item_count": item_count,
        "scaled_score": scaled_score,
        "is_overage": is_overage,
        "completed_at": clock.now_iso(),
        "status": "COMPLETED",
    }
    stamp_create(rec)
    db.mock_exams[rec["id"]] = rec
    enr["completed_mock_count"] += 1
    ES.recompute_readiness(enr)
    touch(enr)
    return success(public(rec), status=201)


@bp.get("/enrollments/<eid>/mock-exams")
def list_mock_exams(eid):
    user_id, role = get_auth()
    require_role(role, {"Learner", "ContentAdmin", "ExamProctor"})
    enr = get_enrollment(eid)
    if role == "Learner":
        assert_owner(enr, user_id)
    limit, offset = pagination_params()
    rows = ES.mocks_of(eid)
    rows.sort(key=lambda r: r["_seq"])
    window, total, has_more = paginate(rows, limit, offset)
    return list_success(public_list(window), limit, offset, total, has_more)


# --------------------------------------------------------------------------- #
# CE awards
# --------------------------------------------------------------------------- #
@bp.post("/enrollments/<eid>/ce-awards")
def create_ce_award(eid):
    user_id, role = get_auth()
    require_role(role, {"Learner"})
    enr = get_enrollment(eid)
    assert_owner(enr, user_id)
    data = V.body()
    modules_completed = V.as_int(V.require(data, "modules_completed"),
                                 "modules_completed", minimum=1)
    bundle_id = enr["ce_bundle_id"]
    if bundle_id is None:
        # No CE bundle linked: cannot accrue CE.
        raise_err(errors.ERR_REFERENCE_INCOMPATIBLE, "enrollment has no CE bundle")
    bundle = db.ce_bundles[bundle_id]
    # prior awards of this enrollment, ordered by modules_completed
    prior = [a for a in db.ce_credit_awards.values() if a["enrollment_id"] == eid]
    prior.sort(key=lambda a: a["modules_completed"])
    prior_modules = prior[-1]["modules_completed"] if prior else 0
    prior_cumulative = prior[-1]["cumulative_credits"] if prior else 0
    # strictly increasing & within bundle total (priority 14)
    if modules_completed <= prior_modules or modules_completed > bundle["modules_total"]:
        raise_err(errors.ERR_CE_MODULE_REGRESSION, "CE module regression")
    cumulative = round_half_up_div(
        bundle["ce_credits_total"] * modules_completed, bundle["modules_total"]
    )
    credits_awarded = cumulative - prior_cumulative
    rec = {
        "enrollment_id": eid,
        "ce_bundle_id": bundle_id,
        "modules_completed": modules_completed,
        "credits_awarded": credits_awarded,
        "cumulative_credits": cumulative,
    }
    stamp_create(rec)
    db.ce_credit_awards[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.get("/enrollments/<eid>/ce-awards")
def list_ce_awards(eid):
    user_id, role = get_auth()
    require_role(role, {"Learner", "ContentAdmin"})
    enr = get_enrollment(eid)
    if role == "Learner":
        assert_owner(enr, user_id)
    limit, offset = pagination_params()
    rows = [a for a in db.ce_credit_awards.values() if a["enrollment_id"] == eid]
    rows.sort(key=lambda r: r["_seq"])
    window, total, has_more = paginate(rows, limit, offset)
    return list_success(public_list(window), limit, offset, total, has_more)
