"""Return-to-sport progressions and clearance documents (PRD 3.9 / 2.11)."""

from flask import Blueprint

import response
import serializers
from db import create, now_iso, ordered, parse_date, store, today, touch
from errors import ApiError
from middleware import (body_json, guard, pagination, query_enum, query_str,
                        resolve_acting_staff, slice_page, v_date, v_enum,
                        v_int, v_string)
from routes.common import (get_athlete, get_clearance_document,
                           get_injury_record, get_rts_plan, require_state)
from routes.testing import new_test_session
from services import calc, domain

bp = Blueprint("medical", __name__)

PLAN_STATUSES = ("STAGE_ACTIVE", "STAGE_TESTING", "MEDICAL_REVIEW", "CLEARED", "ABORTED")
PLAN_TERMINAL = ("CLEARED", "ABORTED")
PLAN_OPEN = ("STAGE_ACTIVE", "STAGE_TESTING", "MEDICAL_REVIEW")
DOCUMENT_TYPES = ("STAGE_CLEARANCE", "FULL_RELEASE", "MEDICAL_HOLD_RELEASE")
DOCUMENT_STATUSES = ("PENDING", "SIGNED", "EXPIRED", "REVOKED")
DOCUMENT_TERMINAL = ("EXPIRED", "REVOKED")
DECISIONS = ("PASS", "FAIL")


# ------------------------------------------------------------------- plans ----
@bp.post("/rts-plans")
def create_plan():
    guard("MedicalProvider")
    body = body_json()
    athlete = get_athlete(body.get("athlete_id"))
    injury = get_injury_record(body.get("injury_record_id"))
    target_stage_count = v_int(
        body, "target_stage_count", required=False, minimum=3, maximum=5, default=4
    )

    if injury["athlete_id"] != athlete["id"]:
        raise ApiError(
            "ERR_INVALID_STATE", "The injury record does not belong to the named athlete"
        )
    if not injury["rts_required"]:
        raise ApiError(
            "ERR_INVALID_STATE", "The injury record does not require a return-to-sport progression"
        )
    if injury["status"] != "ACTIVE_REHAB":
        raise ApiError("ERR_INVALID_STATE", "The injury record is not in ACTIVE_REHAB")
    for plan in ordered(store.rts_plans):
        if plan["injury_record_id"] == injury["id"] and plan["status"] in PLAN_OPEN:
            raise ApiError(
                "ERR_INVALID_STATE",
                "A non-terminal plan already exists for this injury record",
            )

    record = create(
        store.rts_plans,
        {
            "athlete_id": athlete["id"],
            "injury_record_id": injury["id"],
            "target_stage_count": target_stage_count,
            "current_stage": 1,
            "stage_attempts": 0,
            "total_failed_attempts": 0,
            "active_stage_test_id": None,
            "status": "STAGE_ACTIVE",
            "cleared_at": None,
        },
    )
    if athlete["training_clearance"] == "CLEARED":
        athlete["training_clearance"] = "RESTRICTED"
        touch(athlete)
    domain.recompute_athlete_sessions(athlete)
    return response.created(serializers.rts_plan(record))


@bp.get("/rts-plans/<rts_plan_id>")
def read_plan(rts_plan_id):
    ctx = guard("PerformanceDirector", "Coach", "MedicalProvider", "Athlete", "Guardian")
    plan = get_rts_plan(rts_plan_id)
    resolve_acting_staff(ctx)
    athlete = store.athletes.get(plan["athlete_id"])
    if athlete is not None:
        domain.enforce_athlete_scope(ctx, athlete)
    return response.ok(serializers.rts_plan(plan))


@bp.get("/rts-plans")
def list_plans():
    ctx = guard("PerformanceDirector", "Coach", "MedicalProvider")
    resolve_acting_staff(ctx)
    limit, offset = pagination()
    athlete_id = query_str("athlete_id")
    injury_record_id = query_str("injury_record_id")
    status = query_enum("status", PLAN_STATUSES)
    active_stage_test_id = query_str("active_stage_test_id")

    rows = ordered(store.rts_plans)
    if athlete_id:
        rows = [r for r in rows if r["athlete_id"] == athlete_id]
    if injury_record_id:
        rows = [r for r in rows if r["injury_record_id"] == injury_record_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if active_stage_test_id:
        rows = [r for r in rows if r["active_stage_test_id"] == active_stage_test_id]
    page, total = slice_page(rows, limit, offset)
    return response.ok_list([serializers.rts_plan(r) for r in page], limit, offset, total)


@bp.post("/rts-plans/<rts_plan_id>/stage-test")
def open_stage_test(rts_plan_id):
    ctx = guard("Coach")
    plan = get_rts_plan(rts_plan_id)
    staff = resolve_acting_staff(ctx)
    body_json()

    require_state(plan, "status", ("STAGE_ACTIVE",), PLAN_TERMINAL, "ReturnToSportPlan")
    domain.credential_gate(staff)

    session = new_test_session(
        plan["athlete_id"], "PERFORMANCE_BATTERY", staff["id"], rts_plan_id=plan["id"]
    )
    plan["status"] = "STAGE_TESTING"
    plan["active_stage_test_id"] = session["id"]
    touch(plan)
    return response.created(serializers.test_session(session))


def _stage_clearance_gate(plan):
    reference = today()
    expired_seen = False
    for document in ordered(store.clearance_documents):
        if document["rts_plan_id"] != plan["id"]:
            continue
        if document["document_type"] != "STAGE_CLEARANCE":
            continue
        if document["stage_number"] != plan["current_stage"]:
            continue
        if document["status"] == "SIGNED":
            expires_on = parse_date(document["expires_on"])
            if expires_on is None or expires_on >= reference:
                return
            expired_seen = True
        elif document["status"] == "EXPIRED":
            expired_seen = True
    if expired_seen:
        raise ApiError(
            "ERR_CLEARANCE_EXPIRED",
            "The stage clearance for this stage has expired",
        )
    raise ApiError(
        "ERR_STAGE_CLEARANCE_MISSING",
        "A signed, unrevoked stage clearance is required for this stage",
    )


@bp.post("/rts-plans/<rts_plan_id>/stage-decision")
def stage_decision(rts_plan_id):
    ctx = guard("MedicalProvider")
    plan = get_rts_plan(rts_plan_id)
    body = body_json()
    decision = v_enum(body, "decision", DECISIONS)

    require_state(plan, "status", ("STAGE_TESTING",), PLAN_TERMINAL, "ReturnToSportPlan")
    stage_test = store.test_sessions.get(plan["active_stage_test_id"])
    if stage_test is None or stage_test["status"] != "FINALIZED":
        raise ApiError(
            "ERR_INVALID_STATE", "The plan's active stage test has not been finalized"
        )
    if ctx.user_id and stage_test["administered_by_staff_id"] == ctx.user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The staff member who administered the stage test may not judge it",
        )

    if decision == "PASS":
        _stage_clearance_gate(plan)
        if plan["current_stage"] < plan["target_stage_count"]:
            plan["current_stage"] += 1
            plan["stage_attempts"] = 0
            plan["status"] = "STAGE_ACTIVE"
        else:
            plan["status"] = "MEDICAL_REVIEW"
    else:
        plan["stage_attempts"] += 1
        plan["total_failed_attempts"] += 1
        if plan["stage_attempts"] >= calc.RTS_MAX_STAGE_ATTEMPTS:
            plan["status"] = "MEDICAL_REVIEW"
        else:
            plan["status"] = "STAGE_ACTIVE"
    plan["active_stage_test_id"] = None
    touch(plan)
    return response.ok(serializers.rts_plan(plan))


@bp.post("/rts-plans/<rts_plan_id>/abort")
def abort_plan(rts_plan_id):
    guard("MedicalProvider")
    plan = get_rts_plan(rts_plan_id)
    body = body_json()
    v_string(body, "abort_reason", required=False, max_len=500)

    require_state(plan, "status", PLAN_OPEN, PLAN_TERMINAL, "ReturnToSportPlan")
    plan["status"] = "ABORTED"
    plan["active_stage_test_id"] = None
    touch(plan)

    athlete = store.athletes.get(plan["athlete_id"])
    if athlete is not None:
        domain.place_on_medical_hold(athlete)
        domain.recompute_athlete_sessions(athlete)
    return response.ok(serializers.rts_plan(plan))


# ------------------------------------------------------- clearance documents ----
@bp.post("/clearance-documents")
def create_document():
    guard("MedicalProvider")
    body = body_json()
    athlete = get_athlete(body.get("athlete_id"))
    plan = None
    if body.get("rts_plan_id") is not None:
        plan = get_rts_plan(body.get("rts_plan_id"))

    document_type = v_enum(body, "document_type", DOCUMENT_TYPES)
    stage_number = body.get("stage_number")
    if stage_number is not None:
        stage_number = v_int(body, "stage_number", minimum=1)
    expires_on = v_date(body, "expires_on")

    if document_type == "STAGE_CLEARANCE":
        if plan is None:
            raise ApiError(
                "ERR_INVALID_REQUEST", "a STAGE_CLEARANCE requires a non-null rts_plan_id"
            )
        if stage_number is None:
            raise ApiError(
                "ERR_INVALID_REQUEST", "a STAGE_CLEARANCE requires a stage_number of at least 1"
            )
    elif document_type == "FULL_RELEASE":
        if plan is None:
            raise ApiError(
                "ERR_INVALID_REQUEST", "a FULL_RELEASE requires a non-null rts_plan_id"
            )
        if stage_number is not None:
            raise ApiError("ERR_INVALID_REQUEST", "a FULL_RELEASE must carry a null stage_number")
    else:
        if plan is not None:
            raise ApiError(
                "ERR_INVALID_REQUEST", "a MEDICAL_HOLD_RELEASE must carry a null rts_plan_id"
            )
        if stage_number is not None:
            raise ApiError(
                "ERR_INVALID_REQUEST", "a MEDICAL_HOLD_RELEASE must carry a null stage_number"
            )

    record = create(
        store.clearance_documents,
        {
            "athlete_id": athlete["id"],
            "rts_plan_id": plan["id"] if plan else None,
            "document_type": document_type,
            "stage_number": stage_number,
            "expires_on": expires_on.isoformat(),
            "provider_license_id": None,
            "signed_at": None,
            "status": "PENDING",
            "_revoked_by": None,
        },
    )
    return response.created(serializers.clearance_document(record))


@bp.get("/clearance-documents/<clearance_document_id>")
def read_document(clearance_document_id):
    ctx = guard("PerformanceDirector", "Coach", "MedicalProvider", "Athlete", "Guardian")
    document = get_clearance_document(clearance_document_id)
    resolve_acting_staff(ctx)
    athlete = store.athletes.get(document["athlete_id"])
    if athlete is not None:
        domain.enforce_athlete_scope(ctx, athlete)
    return response.ok(serializers.clearance_document(document))


@bp.get("/clearance-documents")
def list_documents():
    ctx = guard("PerformanceDirector", "Coach", "MedicalProvider")
    resolve_acting_staff(ctx)
    limit, offset = pagination()
    athlete_id = query_str("athlete_id")
    rts_plan_id = query_str("rts_plan_id")
    status = query_enum("status", DOCUMENT_STATUSES)
    document_type = query_enum("document_type", DOCUMENT_TYPES)

    rows = ordered(store.clearance_documents)
    if athlete_id:
        rows = [r for r in rows if r["athlete_id"] == athlete_id]
    if rts_plan_id:
        rows = [r for r in rows if r["rts_plan_id"] == rts_plan_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if document_type:
        rows = [r for r in rows if r["document_type"] == document_type]
    page, total = slice_page(rows, limit, offset)
    return response.ok_list(
        [serializers.clearance_document(r) for r in page], limit, offset, total
    )


def _sign_segregation(document, ctx):
    plan = store.rts_plans.get(document["rts_plan_id"]) if document["rts_plan_id"] else None
    if plan is None or not ctx.user_id:
        return
    stage_test = store.test_sessions.get(plan["active_stage_test_id"])
    if stage_test is not None and stage_test["administered_by_staff_id"] == ctx.user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The staff member who administered the stage test may not sign its clearance",
        )
    for other in ordered(store.clearance_documents):
        if other["rts_plan_id"] != plan["id"]:
            continue
        if other["status"] == "REVOKED" and other.get("_revoked_by") == ctx.user_id:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                "A provider who revoked a document on this plan may not sign for it",
            )


def _apply_full_release(document):
    plan = store.rts_plans.get(document["rts_plan_id"])
    if plan is None or plan["status"] != "MEDICAL_REVIEW":
        raise ApiError(
            "ERR_INVALID_STATE",
            "A FULL_RELEASE may only be signed against a plan in MEDICAL_REVIEW",
        )
    plan["status"] = "CLEARED"
    plan["cleared_at"] = now_iso()
    plan["active_stage_test_id"] = None
    touch(plan)

    injury = store.injury_records.get(plan["injury_record_id"])
    if injury is not None and injury["status"] == "ACTIVE_REHAB":
        injury["status"] = "RESOLVED"
        touch(injury)

    athlete = store.athletes.get(plan["athlete_id"])
    if athlete is not None:
        if athlete["training_clearance"] == "RESTRICTED" and domain.open_rts_plan(athlete["id"]) is None:
            athlete["training_clearance"] = "CLEARED"
            touch(athlete)
        domain.recompute_athlete_sessions(athlete)


def _apply_medical_hold_release(document):
    athlete = store.athletes.get(document["athlete_id"])
    if athlete is None or athlete["training_clearance"] != "MEDICAL_HOLD":
        return
    risk = athlete["injury_risk_score"]
    if risk is None or calc.D(risk) < calc.RESTRICTED_RISK_THRESHOLD:
        athlete["training_clearance"] = "CLEARED"
    else:
        athlete["training_clearance"] = "RESTRICTED"
    touch(athlete)
    domain.recompute_athlete_sessions(athlete)


@bp.post("/clearance-documents/<clearance_document_id>/sign")
def sign_document(clearance_document_id):
    ctx = guard("MedicalProvider")
    document = get_clearance_document(clearance_document_id)
    body = body_json()
    license_id = v_string(body, "provider_license_id", required=False, max_len=120)

    require_state(document, "status", ("PENDING",), DOCUMENT_TERMINAL, "ClearanceDocument")
    _sign_segregation(document, ctx)
    expires_on = parse_date(document["expires_on"])
    if expires_on is not None and expires_on < today():
        raise ApiError("ERR_CLEARANCE_EXPIRED", "The document's expires_on has already passed")

    if document["document_type"] == "FULL_RELEASE":
        _apply_full_release(document)

    document["status"] = "SIGNED"
    document["signed_at"] = now_iso()
    document["provider_license_id"] = license_id
    touch(document)

    if document["document_type"] == "MEDICAL_HOLD_RELEASE":
        _apply_medical_hold_release(document)
    return response.ok(serializers.clearance_document(document))


@bp.post("/clearance-documents/<clearance_document_id>/revoke")
def revoke_document(clearance_document_id):
    ctx = guard("MedicalProvider")
    document = get_clearance_document(clearance_document_id)
    body = body_json()
    v_string(body, "revoke_reason", required=False, max_len=500)

    require_state(
        document, "status", ("PENDING", "SIGNED"), DOCUMENT_TERMINAL, "ClearanceDocument"
    )
    was_signed = document["status"] == "SIGNED"
    document["status"] = "REVOKED"
    document["_revoked_by"] = ctx.user_id
    touch(document)

    if was_signed:
        athlete = store.athletes.get(document["athlete_id"])
        if athlete is not None and domain.open_rts_plan(athlete["id"]) is not None:
            domain.cancel_forward_book(athlete, "ATHLETE_SUSPENDED")
    return response.ok(serializers.clearance_document(document))
