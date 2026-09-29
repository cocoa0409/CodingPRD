"""Engagement lifecycle: creation, amendment, QA nomination, scope lock, plans."""

from datetime import timedelta

from flask import Blueprint

import middleware as mw
from db import db, fmt_day, ordered, parse_day
from errors import ApiError
from response import collection, single
from services import calc, derive, serialize

bp = Blueprint("engagements", __name__)

MERCHANT_LEVELS = ("L1", "L2", "L3", "L4")
COOLDOWN_DAYS = 3


# --------------------------------------------------------------------------- #
# shared assessor guards
# --------------------------------------------------------------------------- #
def guard_segregation(lead_id, qa_id):
    if qa_id is not None and qa_id == lead_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")


def guard_qa_qualified(qa_row):
    if qa_row is not None and not qa_row.get("qa_qualified"):
        raise ApiError("ERR_QA_NOT_QUALIFIED")


def guard_active(assessor_row):
    if assessor_row is not None and assessor_row.get("status") != "ACTIVE":
        raise ApiError("ERR_ASSESSOR_NOT_ACTIVE")


def guard_certified(assessor_row):
    if assessor_row is not None and derive.certification_status(assessor_row) != "ACTIVE":
        raise ApiError("ERR_ASSESSOR_CERTIFICATION_EXPIRED")


def guard_window(lead_id, start_day, end_day, exclude_engagement_id=None):
    """The lead's window, widened by a 3-day cooldown on both sides, must not
    intersect another engagement they lead (PRD section 3.2)."""
    cooldown = timedelta(days=COOLDOWN_DAYS)
    for other in db.engagements.values():
        if other["id"] == exclude_engagement_id:
            continue
        if other.get("lead_assessor_id") != lead_id:
            continue
        if other.get("status") == "REASSESSMENT_PLANNED":
            continue
        other_start = parse_day(other.get("fieldwork_start_date"))
        other_end = parse_day(other.get("fieldwork_end_date"))
        if other_start is None or other_end is None:
            continue
        if start_day <= other_end + cooldown and other_start <= end_day + cooldown:
            raise ApiError("ERR_ASSESSOR_WINDOW_CONFLICT")


# --------------------------------------------------------------------------- #
# creation / reads
# --------------------------------------------------------------------------- #
@bp.post("/engagements")
def create_engagement():
    mw.authenticate((mw.ROLE_ADMIN, mw.ROLE_LEAD))
    body = mw.json_body()
    client_legal_name = mw.v_str(body, "client_legal_name", allow_empty=False)
    merchant_level = mw.v_enum(body, "merchant_level", MERCHANT_LEVELS)
    assessment_year = mw.v_int(body, "assessment_year")
    acquirer_name = mw.v_str(body, "acquirer_name", allow_empty=False)
    start_raw, start_day = mw.v_day(body, "fieldwork_start_date")
    end_raw, end_day = mw.v_day(body, "fieldwork_end_date")
    budget = mw.v_number(body, "approved_budget_amount", exclusive_minimum=0)
    lead_assessor_id = mw.v_id_ref(body, "lead_assessor_id")
    qa_reviewer_id = mw.v_id_ref(body, "qa_reviewer_id", required=False)
    if end_day < start_day:
        raise ApiError("ERR_INVALID_REQUEST",
                       "fieldwork_end_date must not precede fieldwork_start_date.")

    lead = mw.fetch(db.assessors, lead_assessor_id, "ERR_ASSESSOR_NOT_FOUND")
    qa = None
    if qa_reviewer_id is not None:
        qa = mw.fetch(db.assessors, qa_reviewer_id, "ERR_ASSESSOR_NOT_FOUND")

    guard_segregation(lead_assessor_id, qa_reviewer_id)
    guard_qa_qualified(qa)
    guard_active(lead)
    guard_active(qa)
    guard_certified(lead)
    guard_certified(qa)
    guard_window(lead_assessor_id, start_day, end_day)

    row = {
        "client_legal_name": client_legal_name,
        "merchant_level": merchant_level,
        "assessment_year": assessment_year,
        "acquirer_name": acquirer_name,
        "fieldwork_start_date": start_raw,
        "fieldwork_end_date": end_raw,
        "approved_budget_amount": calc.money(budget),
        "lead_assessor_id": lead_assessor_id,
        "qa_reviewer_id": qa_reviewer_id,
        "status": "SCOPING",
        "scope_locked": False,
        "estimated_hours": 0,
        "assessment_fee_total": calc.money(0),
        "reassessment_due_date": None,
        "next_assessment_start_date": None,
        "attested_at": None,
    }
    db.stamp_new(row)
    hours, total = calc.assessment_fee(merchant_level, 0, 0, 0)
    derive.store_fee(row, hours, total)
    db.engagements[row["id"]] = row
    return single(serialize.engagement(row), 201)


@bp.get("/engagements")
def list_engagements():
    mw.authenticate(mw.ALL_ROLES)
    limit, offset = mw.pagination()
    payload = [serialize.engagement(row) for row in ordered(db.engagements.values())]
    payload = mw.apply_filters(payload, {
        "status": ("status", "str"),
        "posture": ("posture", "str"),
        "lead_assessor_id": ("lead_assessor_id", "str"),
        "qa_reviewer_id": ("qa_reviewer_id", "str"),
        "merchant_level": ("merchant_level", "str"),
        "assessment_year": ("assessment_year", "int"),
    })
    return collection(mw.page(payload, limit, offset), limit, offset, len(payload))


@bp.get("/engagements/<row_id>")
def get_engagement(row_id):
    mw.authenticate(mw.ALL_ROLES)
    row = mw.fetch(db.engagements, row_id, "ERR_ENGAGEMENT_NOT_FOUND")
    return single(serialize.engagement(row))


@bp.get("/engagements/<row_id>/summary")
def get_engagement_summary(row_id):
    mw.authenticate(mw.ALL_ROLES)
    row = mw.fetch(db.engagements, row_id, "ERR_ENGAGEMENT_NOT_FOUND")
    return single(serialize.engagement_summary(row))


# --------------------------------------------------------------------------- #
# amendment
# --------------------------------------------------------------------------- #
@bp.patch("/engagements/<row_id>")
def patch_engagement(row_id):
    user_id, _role = mw.authenticate((mw.ROLE_LEAD,))
    body = mw.json_body()
    budget = mw.v_number(body, "approved_budget_amount", required=False, exclusive_minimum=0)
    acquirer_name = mw.v_str(body, "acquirer_name", required=False, allow_empty=False)
    start_raw, start_day = mw.v_day(body, "fieldwork_start_date", required=False)
    end_raw, end_day = mw.v_day(body, "fieldwork_end_date", required=False)
    qa_reviewer_id = mw.v_id_ref(body, "qa_reviewer_id", required=False)

    engagement = mw.fetch(db.engagements, row_id, "ERR_ENGAGEMENT_NOT_FOUND")

    resolved_start = start_day or parse_day(engagement.get("fieldwork_start_date"))
    resolved_end = end_day or parse_day(engagement.get("fieldwork_end_date"))
    if resolved_end < resolved_start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "fieldwork_end_date must not precede fieldwork_start_date.")

    qa = None
    if qa_reviewer_id is not None:
        qa = mw.fetch(db.assessors, qa_reviewer_id, "ERR_ASSESSOR_NOT_FOUND")

    mw.require_lead(engagement, user_id)
    derive.guard_frozen(engagement)

    guard_segregation(engagement.get("lead_assessor_id"), qa_reviewer_id)
    guard_active(qa)

    if start_day is not None or end_day is not None:
        guard_window(engagement.get("lead_assessor_id"), resolved_start, resolved_end,
                     exclude_engagement_id=engagement["id"])

    ceiling = calc.money(budget) if budget is not None else calc.dec(
        engagement.get("approved_budget_amount"))
    hours, total = derive.projected_fee(engagement)
    derive.enforce_budget(engagement, total, ceiling)

    if budget is not None:
        engagement["approved_budget_amount"] = calc.money(budget)
    if acquirer_name is not None:
        engagement["acquirer_name"] = acquirer_name
    if start_raw is not None:
        engagement["fieldwork_start_date"] = start_raw
    if end_raw is not None:
        engagement["fieldwork_end_date"] = end_raw
    if qa_reviewer_id is not None:
        engagement["qa_reviewer_id"] = qa_reviewer_id
    derive.store_fee(engagement, hours, total)
    db.touch(engagement)
    return single(serialize.engagement(engagement))


# --------------------------------------------------------------------------- #
# QA reviewer nomination
# --------------------------------------------------------------------------- #
@bp.post("/engagements/<row_id>/qa-reviewer")
def nominate_qa_reviewer(row_id):
    user_id, _role = mw.authenticate((mw.ROLE_LEAD,))
    body = mw.json_body()
    qa_reviewer_id = mw.v_id_ref(body, "qa_reviewer_id")

    engagement = mw.fetch(db.engagements, row_id, "ERR_ENGAGEMENT_NOT_FOUND")
    qa = mw.fetch(db.assessors, qa_reviewer_id, "ERR_ASSESSOR_NOT_FOUND")

    mw.require_lead(engagement, user_id)

    guard_segregation(engagement.get("lead_assessor_id"), qa_reviewer_id)
    guard_qa_qualified(qa)
    guard_active(qa)
    guard_certified(qa)

    engagement["qa_reviewer_id"] = qa_reviewer_id
    db.touch(engagement)
    return single(serialize.engagement(engagement))


# --------------------------------------------------------------------------- #
# scope lock
# --------------------------------------------------------------------------- #
@bp.post("/engagements/<row_id>/scope-lock")
def scope_lock(row_id):
    user_id, _role = mw.authenticate((mw.ROLE_LEAD,))
    engagement = mw.fetch(db.engagements, row_id, "ERR_ENGAGEMENT_NOT_FOUND")
    mw.require_lead(engagement, user_id)
    derive.guard_restricted(engagement)
    if engagement.get("status") != "SCOPING":
        raise ApiError("ERR_INVALID_ENGAGEMENT_STATE")

    has_validated_cde = any(
        segment.get("segment_class") == "CDE"
        and segment.get("segmentation_status") == "VALIDATED"
        for segment in derive.segments_of(engagement["id"])
    )
    if not has_validated_cde:
        raise ApiError("ERR_NO_CDE_SEGMENT")

    plan = derive.active_plan(engagement["id"])
    if plan is None or plan.get("plan_variant") != "FINAL":
        raise ApiError("ERR_SAMPLING_PLAN_STALE")

    engagement["scope_locked"] = True
    engagement["status"] = "FIELDWORK"
    db.touch(engagement)
    return single(serialize.engagement(engagement))


# --------------------------------------------------------------------------- #
# reassessment plan
# --------------------------------------------------------------------------- #
@bp.post("/engagements/<row_id>/reassessment-plan")
def reassessment_plan(row_id):
    user_id, _role = mw.authenticate((mw.ROLE_LEAD,))
    body = mw.json_body()
    target_year = mw.v_int(body, "target_year")
    planned_raw, planned_day = mw.v_day(body, "planned_start_date")

    engagement = mw.fetch(db.engagements, row_id, "ERR_ENGAGEMENT_NOT_FOUND")
    mw.require_lead(engagement, user_id)
    if engagement.get("status") != "SUBMITTED":
        raise ApiError("ERR_INVALID_ENGAGEMENT_STATE")

    if target_year != int(engagement.get("assessment_year")) + 1:
        raise ApiError("ERR_INVALID_REASSESSMENT_YEAR")
    if planned_day < db.today():
        raise ApiError("ERR_INVALID_REASSESSMENT_YEAR")

    engagement["next_assessment_start_date"] = planned_raw
    engagement["status"] = "REASSESSMENT_PLANNED"
    db.touch(engagement)
    return single(serialize.engagement(engagement))


_ = fmt_day
