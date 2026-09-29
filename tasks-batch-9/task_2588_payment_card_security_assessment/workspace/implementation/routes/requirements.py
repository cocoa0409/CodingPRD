"""The requirement programme: requirements, testing, evidence and conclusions."""

from flask import Blueprint

import middleware as mw
from db import db, ordered
from errors import ApiError
from response import collection, single
from services import calc, derive, serialize

bp = Blueprint("requirements", __name__)

FAMILIES = tuple("R%d" % index for index in range(1, 13))
APPLICABILITIES = ("APPLICABLE", "NOT_APPLICABLE")
CONCLUSIONS = ("IN_PLACE", "NOT_IN_PLACE", "NOT_TESTED")
EVIDENCE_TYPES = ("DOCUMENT_REVIEW", "INTERVIEW", "OBSERVATION", "SYSTEM_CONFIG")
SUFFICIENCIES = ("SUFFICIENT", "INSUFFICIENT")
TARGET_REQUIRED_TYPES = ("OBSERVATION", "SYSTEM_CONFIG")


# --------------------------------------------------------------------------- #
# programme entry
# --------------------------------------------------------------------------- #
@bp.post("/engagements/<engagement_id>/requirement-assessments")
def add_requirement(engagement_id):
    mw.authenticate((mw.ROLE_LEAD, mw.ROLE_ASSESSOR))
    body = mw.json_body()
    requirement_ref = mw.v_str(body, "requirement_ref", allow_empty=False)
    requirement_family = mw.v_enum(body, "requirement_family", FAMILIES)
    testing_procedure_count = mw.v_int(body, "testing_procedure_count", minimum=1)
    applicability = mw.v_enum(body, "applicability", APPLICABILITIES)

    engagement = mw.fetch(db.engagements, engagement_id, "ERR_ENGAGEMENT_NOT_FOUND")
    derive.guard_frozen(engagement)

    for existing in derive.requirements_of(engagement_id):
        if existing.get("requirement_ref") == requirement_ref:
            raise ApiError("ERR_DUPLICATE_REQUIREMENT_REF")

    row = {
        "engagement_id": engagement_id,
        "requirement_ref": requirement_ref,
        "requirement_family": requirement_family,
        "testing_procedure_count": testing_procedure_count,
        "applicability": applicability,
        "test_status": "NOT_APPLICABLE" if applicability == "NOT_APPLICABLE" else "NOT_STARTED",
        "remediation_status": "NONE",
        "evidence_item_count": 0,
        "evidence_type_coverage": [],
        "evidence_completeness": False,
        "conclusion_rationale": None,
        "reopen_count": 0,
        "risk_points": calc.FAMILY_RISK_POINTS[requirement_family],
    }
    db.stamp_new(row)
    db.requirement_assessments[row["id"]] = row
    return single(serialize.requirement_assessment(row), 201)


@bp.get("/requirement-assessments")
def list_requirements():
    mw.authenticate(mw.ALL_ROLES)
    limit, offset = mw.pagination()
    payload = [serialize.requirement_assessment(row)
               for row in ordered(db.requirement_assessments.values())]
    payload = mw.apply_filters(payload, {
        "engagement_id": ("engagement_id", "str"),
        "requirement_family": ("requirement_family", "str"),
        "test_status": ("test_status", "str"),
        "remediation_status": ("remediation_status", "str"),
        "applicability": ("applicability", "str"),
    })
    return collection(mw.page(payload, limit, offset), limit, offset, len(payload))


@bp.get("/requirement-assessments/<row_id>")
def get_requirement(row_id):
    mw.authenticate(mw.ALL_ROLES)
    row = mw.fetch(db.requirement_assessments, row_id, "ERR_REQUIREMENT_NOT_FOUND")
    return single(serialize.requirement_assessment(row))


# --------------------------------------------------------------------------- #
# testing
# --------------------------------------------------------------------------- #
@bp.post("/requirement-assessments/<row_id>/start-testing")
def start_testing(row_id):
    mw.authenticate((mw.ROLE_LEAD, mw.ROLE_ASSESSOR))
    requirement = mw.fetch(db.requirement_assessments, row_id, "ERR_REQUIREMENT_NOT_FOUND")
    engagement = db.engagements.get(requirement.get("engagement_id"))
    derive.guard_frozen(engagement)

    if requirement.get("test_status") != "NOT_STARTED":
        raise ApiError("ERR_INVALID_REQUIREMENT_STATE")

    requirement["test_status"] = "IN_TESTING"
    db.touch(requirement)
    return single(serialize.requirement_assessment(requirement))


@bp.post("/requirement-assessments/<row_id>/conclusion")
def conclude_requirement(row_id):
    mw.authenticate((mw.ROLE_LEAD, mw.ROLE_ASSESSOR))
    body = mw.json_body()
    conclusion = mw.v_enum(body, "conclusion", CONCLUSIONS)
    conclusion_rationale = mw.v_str(body, "conclusion_rationale", allow_empty=False)

    requirement = mw.fetch(db.requirement_assessments, row_id, "ERR_REQUIREMENT_NOT_FOUND")
    engagement = db.engagements.get(requirement.get("engagement_id"))
    derive.guard_frozen(engagement)

    if requirement.get("test_status") != "IN_TESTING":
        raise ApiError("ERR_INVALID_REQUIREMENT_STATE")

    plan = derive.latest_plan(engagement["id"])
    if plan is None or plan.get("status") != "ACTIVE" or plan.get("plan_variant") != "FINAL":
        raise ApiError("ERR_SAMPLING_PLAN_STALE")

    if conclusion in ("IN_PLACE", "NOT_IN_PLACE") and not requirement.get("evidence_completeness"):
        raise ApiError("ERR_EVIDENCE_INCOMPLETE")

    requirement["test_status"] = conclusion
    requirement["conclusion_rationale"] = conclusion_rationale
    if conclusion == "NOT_IN_PLACE":
        if requirement.get("remediation_status") == "NONE":
            requirement["remediation_status"] = "GAP_OPEN"
        derive.mint_remediation_item(engagement, requirement, "REQUIREMENT_CONCLUSION")
    db.touch(requirement)
    db.touch(engagement)
    return single(serialize.requirement_assessment(requirement))


@bp.post("/requirement-assessments/<row_id>/reopen")
def reopen_requirement(row_id):
    user_id, _role = mw.authenticate((mw.ROLE_LEAD,))
    body = mw.json_body()
    mw.v_str(body, "reason", allow_empty=False)

    requirement = mw.fetch(db.requirement_assessments, row_id, "ERR_REQUIREMENT_NOT_FOUND")
    engagement = db.engagements.get(requirement.get("engagement_id"))
    mw.require_lead(engagement, user_id)
    derive.guard_frozen(engagement)

    if requirement.get("test_status") != "IN_PLACE":
        raise ApiError("ERR_INVALID_REQUIREMENT_STATE")

    requirement["test_status"] = "IN_TESTING"
    requirement["reopen_count"] = int(requirement.get("reopen_count") or 0) + 1
    if requirement.get("remediation_status") in ("NONE", "GAP_REMEDIATED"):
        requirement["remediation_status"] = "GAP_OPEN"
    derive.mint_remediation_item(engagement, requirement, "REQUIREMENT_REOPEN")
    db.touch(requirement)
    db.touch(engagement)
    return single(serialize.requirement_assessment(requirement))


# --------------------------------------------------------------------------- #
# evidence
# --------------------------------------------------------------------------- #
@bp.post("/requirement-assessments/<row_id>/evidence-items")
def append_evidence(row_id):
    user_id, _role = mw.authenticate((mw.ROLE_LEAD, mw.ROLE_ASSESSOR))
    body = mw.json_body()
    evidence_type = mw.v_enum(body, "evidence_type", EVIDENCE_TYPES)
    procedure_ref = mw.v_str(body, "procedure_ref", allow_empty=False)
    sufficiency = mw.v_enum(body, "sufficiency", SUFFICIENCIES)
    component_id = mw.v_id_ref(body, "component_id", required=False)
    interviewee_name = mw.v_str(body, "interviewee_name", required=False)
    interviewee_title = mw.v_str(body, "interviewee_title", required=False)
    note = mw.v_str(body, "note", required=False)

    requirement = mw.fetch(db.requirement_assessments, row_id, "ERR_REQUIREMENT_NOT_FOUND")
    engagement = db.engagements.get(requirement.get("engagement_id"))

    component = None
    if component_id is not None:
        component = mw.fetch(db.system_components, component_id, "ERR_COMPONENT_NOT_FOUND")
        if component.get("engagement_id") != requirement.get("engagement_id"):
            raise ApiError("ERR_CROSS_ENGAGEMENT_REFERENCE")

    derive.guard_frozen(engagement)

    if requirement.get("test_status") != "IN_TESTING":
        raise ApiError("ERR_INVALID_REQUIREMENT_STATE")

    if evidence_type in TARGET_REQUIRED_TYPES and component is None:
        raise ApiError("ERR_EVIDENCE_TARGET_REQUIRED")
    if evidence_type == "INTERVIEW" and (
            not interviewee_name or not interviewee_name.strip()
            or not interviewee_title or not interviewee_title.strip()):
        raise ApiError("ERR_INTERVIEWEE_REQUIRED")
    if component is not None and component.get("in_sample") is not True:
        raise ApiError("ERR_COMPONENT_NOT_IN_SAMPLE")

    row = {
        "requirement_assessment_id": requirement["id"],
        "engagement_id": requirement.get("engagement_id"),
        "evidence_type": evidence_type,
        "procedure_ref": procedure_ref,
        "component_id": component_id,
        "interviewee_name": interviewee_name,
        "interviewee_title": interviewee_title,
        "sufficiency": sufficiency,
        "collector_assessor_id": user_id,
        "collected_at": db.now_iso(),
        "note": note,
    }
    db.stamp_new(row, versioned=False)
    db.evidence_items[row["id"]] = row
    derive.refresh_evidence_derivation(requirement)
    return single(serialize.evidence_item(row), 201)


@bp.get("/evidence-items")
def list_evidence():
    mw.authenticate(mw.ALL_ROLES)
    limit, offset = mw.pagination()
    payload = [serialize.evidence_item(row) for row in ordered(db.evidence_items.values())]
    payload = mw.apply_filters(payload, {
        "requirement_assessment_id": ("requirement_assessment_id", "str"),
        "engagement_id": ("engagement_id", "str"),
        "component_id": ("component_id", "str"),
        "collector_assessor_id": ("collector_assessor_id", "str"),
        "evidence_type": ("evidence_type", "str"),
        "sufficiency": ("sufficiency", "str"),
    })
    return collection(mw.page(payload, limit, offset), limit, offset, len(payload))


@bp.get("/evidence-items/<row_id>")
def get_evidence(row_id):
    mw.authenticate(mw.ALL_ROLES)
    row = mw.fetch(db.evidence_items, row_id, "ERR_EVIDENCE_NOT_FOUND")
    return single(serialize.evidence_item(row))
