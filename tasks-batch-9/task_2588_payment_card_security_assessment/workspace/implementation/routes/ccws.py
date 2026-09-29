"""Compensating control worksheets and the remediation ledger."""

from flask import Blueprint

import middleware as mw
from db import db, ordered
from errors import ApiError
from response import collection, single
from services import calc, derive, serialize

bp = Blueprint("ccws", __name__)

NARRATIVE_FIELDS = ("constraint_text", "objective_text", "identified_risk_text",
                    "validation_text", "maintenance_text")
CCW_DECISIONS = ("ACCEPT", "REJECT")
RETEST_OUTCOMES = ("PASS", "FAIL")


def guard_independence(engagement, user_id):
    """The reviewer may be neither the lead nor an evidence collector (rung 11)."""
    if engagement.get("lead_assessor_id") == user_id:
        raise ApiError("ERR_INDEPENDENCE_VIOLATION")
    for item in derive.evidence_of_engagement(engagement["id"]):
        if item.get("collector_assessor_id") == user_id:
            raise ApiError("ERR_INDEPENDENCE_VIOLATION")


def _refresh_rigor(worksheet, requirement):
    figures = calc.ccw_rigor(
        worksheet.get("control_refs"),
        worksheet.get("monitoring_interval_days"),
        requirement.get("risk_points"),
    )
    worksheet.update(figures)


# --------------------------------------------------------------------------- #
# drafting
# --------------------------------------------------------------------------- #
@bp.post("/requirement-assessments/<requirement_id>/ccws")
def draft_ccw(requirement_id):
    user_id, _role = mw.authenticate((mw.ROLE_LEAD,))
    body = mw.json_body()
    narratives = dict((field, mw.v_str(body, field)) for field in NARRATIVE_FIELDS)
    control_refs = mw.v_str_array(body, "control_refs", min_items=1)
    monitoring_interval_days = mw.v_int(body, "monitoring_interval_days", minimum=1)
    expected_version = mw.v_int(body, "expected_requirement_assessment_version")

    requirement = mw.fetch(db.requirement_assessments, requirement_id,
                           "ERR_REQUIREMENT_NOT_FOUND")
    engagement = db.engagements.get(requirement.get("engagement_id"))
    mw.require_lead(engagement, user_id)
    derive.guard_frozen(engagement)

    if requirement.get("test_status") != "NOT_IN_PLACE":
        raise ApiError("ERR_INVALID_REQUIREMENT_STATE")

    if expected_version != requirement.get("version"):
        raise ApiError("ERR_STALE_REQUIREMENT_VERSION")

    for existing in derive.ccws_of_requirement(requirement_id):
        if existing.get("status") in ("DRAFT", "REJECTED"):
            existing["status"] = "SUPERSEDED"
            db.touch(existing)

    row = {
        "requirement_assessment_id": requirement_id,
        "engagement_id": requirement.get("engagement_id"),
        "control_refs": control_refs,
        "monitoring_interval_days": monitoring_interval_days,
        "status": "DRAFT",
        "reviewer_note": None,
        "decided_at": None,
    }
    row.update(narratives)
    db.stamp_new(row)
    _refresh_rigor(row, requirement)
    db.ccws[row["id"]] = row

    db.touch(requirement)
    return single(serialize.ccw(row), 201)


@bp.get("/ccws")
def list_ccws():
    mw.authenticate(mw.ALL_ROLES)
    limit, offset = mw.pagination()
    payload = [serialize.ccw(row) for row in ordered(db.ccws.values())]
    payload = mw.apply_filters(payload, {
        "requirement_assessment_id": ("requirement_assessment_id", "str"),
        "engagement_id": ("engagement_id", "str"),
        "status": ("status", "str"),
        "thin_control_capped": ("thin_control_capped", "bool"),
    })
    return collection(mw.page(payload, limit, offset), limit, offset, len(payload))


@bp.get("/ccws/<row_id>")
def get_ccw(row_id):
    mw.authenticate(mw.ALL_ROLES)
    row = mw.fetch(db.ccws, row_id, "ERR_CCW_NOT_FOUND")
    return single(serialize.ccw(row))


# --------------------------------------------------------------------------- #
# submission
# --------------------------------------------------------------------------- #
@bp.post("/ccws/<row_id>/submit")
def submit_ccw(row_id):
    user_id, _role = mw.authenticate((mw.ROLE_LEAD,))
    worksheet = mw.fetch(db.ccws, row_id, "ERR_CCW_NOT_FOUND")
    requirement = db.requirement_assessments.get(worksheet.get("requirement_assessment_id"))
    engagement = db.engagements.get(worksheet.get("engagement_id"))
    mw.require_lead(engagement, user_id)
    derive.guard_frozen(engagement)

    if worksheet.get("status") != "DRAFT":
        raise ApiError("ERR_INVALID_CCW_STATE")
    if requirement.get("test_status") != "NOT_IN_PLACE":
        raise ApiError("ERR_INVALID_REQUIREMENT_STATE")

    for field in NARRATIVE_FIELDS:
        value = worksheet.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ApiError("ERR_CCW_SECTION_INCOMPLETE")
    if not worksheet.get("control_refs"):
        raise ApiError("ERR_CCW_SECTION_INCOMPLETE")

    _refresh_rigor(worksheet, requirement)
    worksheet["status"] = "SUBMITTED"
    db.touch(worksheet)
    return single(serialize.ccw(worksheet))


# --------------------------------------------------------------------------- #
# decision
# --------------------------------------------------------------------------- #
@bp.post("/ccws/<row_id>/decision")
def decide_ccw(row_id):
    user_id, _role = mw.authenticate((mw.ROLE_QA,))
    body = mw.json_body()
    decision = mw.v_enum(body, "decision", CCW_DECISIONS)
    reviewer_note = mw.v_str(body, "reviewer_note", allow_empty=False)

    worksheet = mw.fetch(db.ccws, row_id, "ERR_CCW_NOT_FOUND")
    requirement = db.requirement_assessments.get(worksheet.get("requirement_assessment_id"))
    engagement = db.engagements.get(worksheet.get("engagement_id"))
    mw.require_qa_reviewer(engagement, user_id)

    if worksheet.get("status") != "SUBMITTED":
        raise ApiError("ERR_INVALID_CCW_STATE")
    if decision == "ACCEPT" and requirement.get("test_status") != "NOT_IN_PLACE":
        raise ApiError("ERR_INVALID_REQUIREMENT_STATE")

    guard_independence(engagement, user_id)

    if decision == "REJECT":
        worksheet["status"] = "REJECTED"
        worksheet["reviewer_note"] = reviewer_note
        worksheet["decided_at"] = db.now_iso()
        db.touch(worksheet)
        return single(serialize.ccw(worksheet))

    if int(worksheet.get("monitoring_interval_days")) > calc.CCW_MONITORING_CEILING:
        raise ApiError("ERR_CCW_MONITORING_INTERVAL_TOO_LONG")
    if calc.dec(worksheet.get("rigor_score")) < calc.CCW_RIGOR_FLOOR:
        raise ApiError("ERR_CCW_RIGOR_INSUFFICIENT")

    component_sample_size, facility_sample_size = derive.plan_sample_sizes(engagement["id"])
    hours, total = calc.assessment_fee(
        engagement.get("merchant_level"), component_sample_size, facility_sample_size,
        derive.accepted_ccw_count(engagement["id"]) + 1)
    derive.enforce_budget(engagement, total)

    # --- cascade C ------------------------------------------------------------
    worksheet["status"] = "ACCEPTED"
    worksheet["reviewer_note"] = reviewer_note
    worksheet["decided_at"] = db.now_iso()
    db.touch(worksheet)

    requirement["test_status"] = "IN_PLACE_WITH_CCW"
    if requirement.get("remediation_status") == "GAP_OPEN":
        requirement["remediation_status"] = "GAP_ACCEPTED_CCW"
    db.touch(requirement)

    for item in derive.remediations_of_requirement(requirement["id"]):
        if item.get("status") in derive.OPEN_GAP_STATUSES:
            item["status"] = "CLOSED_BY_CCW"
            item["closed_at"] = db.now_iso()
            db.touch(item)

    derive.store_fee(engagement, hours, total)
    db.touch(engagement)
    return single(serialize.ccw(worksheet))


# --------------------------------------------------------------------------- #
# remediation ledger
# --------------------------------------------------------------------------- #
@bp.get("/remediation-items")
def list_remediation_items():
    mw.authenticate(mw.ALL_ROLES)
    limit, offset = mw.pagination()
    payload = [serialize.remediation_item(row)
               for row in ordered(db.remediation_items.values())]
    payload = mw.apply_filters(payload, {
        "engagement_id": ("engagement_id", "str"),
        "requirement_assessment_id": ("requirement_assessment_id", "str"),
        "source_scan_finding_id": ("source_scan_finding_id", "str"),
        "status": ("status", "str"),
        "severity": ("severity", "str"),
        "source": ("source", "str"),
    })
    return collection(mw.page(payload, limit, offset), limit, offset, len(payload))


@bp.get("/remediation-items/<row_id>")
def get_remediation_item(row_id):
    mw.authenticate(mw.ALL_ROLES)
    row = mw.fetch(db.remediation_items, row_id, "ERR_REMEDIATION_ITEM_NOT_FOUND")
    return single(serialize.remediation_item(row))


@bp.post("/remediation-items/<row_id>/assign")
def assign_remediation_item(row_id):
    user_id, _role = mw.authenticate((mw.ROLE_LEAD,))
    body = mw.json_body()
    owner_reference = mw.v_str(body, "owner_reference", allow_empty=False)
    due_raw, _due_day = mw.v_day(body, "due_date")

    item = mw.fetch(db.remediation_items, row_id, "ERR_REMEDIATION_ITEM_NOT_FOUND")
    engagement = db.engagements.get(item.get("engagement_id"))
    mw.require_lead(engagement, user_id)
    derive.guard_frozen(engagement)

    if item.get("status") not in ("OPEN", "RETEST_FAILED"):
        raise ApiError("ERR_INVALID_REMEDIATION_STATE")

    item["owner_reference"] = owner_reference
    item["due_date"] = due_raw
    item["status"] = "IN_PROGRESS"
    db.touch(item)
    return single(serialize.remediation_item(item))


@bp.post("/remediation-items/<row_id>/retest")
def retest_remediation_item(row_id):
    mw.authenticate((mw.ROLE_LEAD, mw.ROLE_ASSESSOR))
    body = mw.json_body()
    outcome = mw.v_enum(body, "outcome", RETEST_OUTCOMES)
    mw.v_str(body, "note", required=False)

    item = mw.fetch(db.remediation_items, row_id, "ERR_REMEDIATION_ITEM_NOT_FOUND")
    engagement = db.engagements.get(item.get("engagement_id"))
    requirement = db.requirement_assessments.get(item.get("requirement_assessment_id"))
    derive.guard_frozen(engagement)

    if item.get("status") != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_REMEDIATION_STATE")

    item["retest_count"] = int(item.get("retest_count") or 0) + 1
    if outcome == "FAIL":
        item["status"] = "RETEST_FAILED"
        db.touch(item)
        return single(serialize.remediation_item(item))

    # --- cascade D ------------------------------------------------------------
    item["status"] = "RETEST_PASSED"
    item["closed_at"] = db.now_iso()
    db.touch(item)

    if requirement is not None:
        remaining = [row for row in derive.remediations_of_requirement(requirement["id"])
                     if row.get("status") in derive.OPEN_GAP_STATUSES]
        if not remaining:
            changed = False
            if requirement.get("remediation_status") == "GAP_OPEN":
                requirement["remediation_status"] = "GAP_REMEDIATED"
                changed = True
            if requirement.get("test_status") == "IN_TESTING":
                requirement["test_status"] = "IN_PLACE"
                changed = True
            if changed:
                db.touch(requirement)
    db.touch(engagement)
    return single(serialize.remediation_item(item))
