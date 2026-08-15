from datetime import timedelta

from flask import Blueprint, request

import errors as E
import response
from db import store, new_record, touch, serialize, now
from errors import ApiError
from middleware import require_auth
from routes.util import body, get_or_404, list_response, is_intlike
from services.domain import cadence_days, schedule_checkin, cancel_scheduled_checkins

bp = Blueprint("plans", __name__)

PLAN_READ_ROLES = ["CaseManager", "BITChair", "DeanOfStudents", "PrivacyOfficer"]


@bp.post("/bit/intervention-plans")
def create_plan():
    uid, _ = require_auth(["CaseManager"])
    b = body()
    case_id = b.get("case_id")
    case = None
    if isinstance(case_id, str):
        case = store.cases.get(case_id)
        if case is None:
            raise ApiError(E.ERR_NOT_FOUND, 404, f"care case not found: {case_id}")

    # Rank 4: optimistic concurrency on the case.
    ecv = b.get("expected_case_version")
    if is_intlike(ecv) and case is not None and ecv != case["version"]:
        raise ApiError(
            E.ERR_STALE_CASE_VERSION,
            412,
            "expected_case_version does not match the CareCase current version",
        )

    # Rank 5: state — INTAKE is a distinct failure from other non-workable states.
    if case is not None:
        if case["status"] == "INTAKE":
            raise ApiError(
                E.ERR_CASE_NOT_TRIAGEABLE, 409, "plan creation requires case TRIAGED or PLAN_ACTIVE"
            )
        if case["status"] not in ("TRIAGED", "PLAN_ACTIVE"):
            raise ApiError(
                E.ERR_CASE_NOT_PLAN_ACTIVE,
                409,
                "plan creation requires case TRIAGED or PLAN_ACTIVE",
            )

    # Rank 9: required fields / objectives, then open-plan exclusion.
    if case is None:
        raise ApiError(E.ERR_VALIDATION, 400, "case_id is required")
    if not is_intlike(ecv):
        raise ApiError(E.ERR_VALIDATION, 400, "expected_case_version is required")
    objectives = b.get("objectives")
    if (
        not isinstance(objectives, list)
        or len(objectives) == 0
        or not all(isinstance(o, str) for o in objectives)
    ):
        raise ApiError(E.ERR_VALIDATION, 400, "objectives must be a non-empty list of strings")
    success_criteria = b.get("success_criteria")
    if not isinstance(success_criteria, str) or not success_criteria:
        raise ApiError(E.ERR_VALIDATION, 400, "success_criteria is required")
    if any(
        p["case_id"] == case["id"] and p["status"] in ("DRAFT", "PENDING_APPROVAL")
        for p in store.plans.values()
    ):
        raise ApiError(
            E.ERR_OPEN_PLAN_EXISTS,
            409,
            "a DRAFT or PENDING_APPROVAL plan already exists for the case",
        )

    rec = new_record()
    rec.update(
        {
            "case_id": case["id"],
            "drafted_by": uid,
            "supersedes_plan_id": None,
            "objectives": objectives,
            "success_criteria": success_criteria,
            "reentry_conditions": [],
            "revision_note": None,
            "status": "DRAFT",
        }
    )
    store.plans[rec["id"]] = rec

    if case["status"] == "TRIAGED":
        case["status"] = "PLAN_DRAFTING"
    touch(case)
    return response.obj(serialize(rec), 201)


@bp.get("/bit/intervention-plans/<pid>")
def get_plan(pid):
    require_auth(PLAN_READ_ROLES)
    rec = get_or_404(store.plans, pid, "intervention plan")
    return response.obj(serialize(rec))


@bp.get("/bit/intervention-plans")
def list_plans():
    require_auth(PLAN_READ_ROLES)
    q = request.args
    return list_response(
        store.plans,
        [
            ("case_id", q.get("case_id")),
            ("drafted_by", q.get("drafted_by")),
            ("supersedes_plan_id", q.get("supersedes_plan_id")),
            ("status", q.get("status")),
        ],
    )


@bp.post("/bit/intervention-plans/<pid>/submit")
def submit_plan(pid):
    uid, _ = require_auth(["CaseManager"])
    rec = get_or_404(store.plans, pid, "intervention plan")
    # Rank 5 state before rank 7 ownership.
    if rec["status"] != "DRAFT":
        raise ApiError(E.ERR_PLAN_NOT_DRAFT, 409, "submit requires plan DRAFT")
    if rec["drafted_by"] != uid:
        raise ApiError(E.ERR_FORBIDDEN, 403, "only the drafting case manager may submit the plan")
    rec["status"] = "PENDING_APPROVAL"
    touch(rec)
    return response.obj(serialize(rec))


@bp.post("/bit/intervention-plans/<pid>/approve")
def approve_plan(pid):
    uid, _ = require_auth(["BITChair"])
    rec = get_or_404(store.plans, pid, "intervention plan")
    case = store.cases.get(rec["case_id"])
    if rec["status"] != "PENDING_APPROVAL":
        raise ApiError(
            E.ERR_PLAN_NOT_PENDING_APPROVAL, 409, "approve requires plan PENDING_APPROVAL"
        )
    if case is None or case["status"] not in ("PLAN_DRAFTING", "PLAN_ACTIVE"):
        raise ApiError(
            E.ERR_CASE_STATE_BLOCKS_PLAN_APPROVAL,
            409,
            "approve requires the case in PLAN_DRAFTING or PLAN_ACTIVE",
        )
    if uid == rec["drafted_by"]:
        raise ApiError(
            E.ERR_SEGREGATION_OF_DUTIES, 403, "plan approver must differ from its drafter"
        )

    # Supersede the prior ACTIVE plan, if any.
    prior_active = None
    for p in store.plans.values():
        if p["case_id"] == rec["case_id"] and p["status"] == "ACTIVE" and p["id"] != rec["id"]:
            prior_active = p
            break
    if prior_active is not None:
        prior_active["status"] = "SUPERSEDED"
        touch(prior_active)
        rec["supersedes_plan_id"] = prior_active["id"]

    rec["status"] = "ACTIVE"
    touch(rec)

    case["status"] = "PLAN_ACTIVE"
    touch(case)

    # Cadence reset: cancel every SCHEDULED check-in, then schedule one fresh one.
    cancel_scheduled_checkins(case["id"])
    schedule_checkin(
        case["id"], now() + timedelta(days=cadence_days(case["current_risk_tier"]))
    )
    return response.obj(serialize(rec))


@bp.post("/bit/intervention-plans/<pid>/return")
def return_plan(pid):
    require_auth(["BITChair"])
    rec = get_or_404(store.plans, pid, "intervention plan")
    if rec["status"] != "PENDING_APPROVAL":
        raise ApiError(
            E.ERR_PLAN_NOT_PENDING_APPROVAL, 409, "return requires plan PENDING_APPROVAL"
        )
    revision_note = body().get("revision_note")
    if not isinstance(revision_note, str) or not revision_note:
        raise ApiError(E.ERR_VALIDATION, 400, "revision_note is required")
    rec["revision_note"] = revision_note
    rec["status"] = "DRAFT"
    touch(rec)
    return response.obj(serialize(rec))
