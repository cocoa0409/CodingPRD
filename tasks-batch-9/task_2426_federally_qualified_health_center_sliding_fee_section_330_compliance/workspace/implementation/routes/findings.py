"""Operational site visit findings and their corrective action plans."""

from flask import Blueprint

import db
import serializers
from errors import ApiError
from middleware import ALL_ROLES, authorize
from response import object_response
from routes.common import listing, owner_ref, require, segregation, state
from services import cascade
from services import health_center as hc_svc
from validation import Field, add_days, pagination, parse_body

bp = Blueprint("findings", __name__)

MAX_CAP_SUBMIT_ROUNDS = 2

FINDING_FIELDS = [
    Field("health_center_id", "string"),
    Field("service_site_id", "string", nullable=True),
    Field("requirement_code", "string", required=True),
    Field("severity", "enum", required=True, enum=("CONDITION", "PROGRESS_REPORT_ONLY")),
    Field("finding_summary", "string", required=True),
    Field("cap_due_days", "integer", required=True, minimum=1),
]

PLAN_FIELDS = [
    Field("site_visit_finding_id", "string"),
    Field("narrative", "string", required=True),
    Field("milestone_count", "integer", required=True, minimum=1),
    Field("target_completion_date", "datetime", required=True),
]


def _plans_of(finding_id):
    return db.in_creation_order(
        [
            p
            for p in db.db.corrective_action_plans.values()
            if p["site_visit_finding_id"] == finding_id
        ]
    )


# --------------------------------------------------------------------------- #
# site visit findings
# --------------------------------------------------------------------------- #


@bp.post("/health-centers/<hc_id>/site-visit-findings")
def create_finding(hc_id):
    user_id = authorize("ProjectOfficer")
    body = parse_body(FINDING_FIELDS)
    require("health_centers", hc_id)
    owner_ref(body, "health_center_id", "health_centers", hc_id)

    site_id = body.get("service_site_id")
    site = require("service_sites", site_id) if site_id is not None else None

    # Rung 8 — the cited site must belong to the cited grantee.
    if site is not None and site["health_center_id"] != hc_id:
        raise ApiError("ERR_CROSS_GRANTEE_REFERENCE")

    row = db.base_row()
    row.update(
        {
            "health_center_id": hc_id,
            "service_site_id": site_id,
            "requirement_code": body["requirement_code"],
            "severity": body["severity"],
            "finding_summary": body["finding_summary"],
            "cap_due_days": body["cap_due_days"],
            "cap_due_at": add_days(row["created_at"], body["cap_due_days"]),
            "status": "OPEN",
            "escalated_at": None,
            "issued_by_user_id": user_id,
        }
    )
    # A new finding is OPEN, not ESCALATED, so no grantee counter moves yet.
    db.db.site_visit_findings[row["id"]] = row
    return object_response(serializers.site_visit_finding(row), 201)


@bp.get("/site-visit-findings/<finding_id>")
def read_finding(finding_id):
    authorize(*ALL_ROLES)
    return object_response(
        serializers.site_visit_finding(require("site_visit_findings", finding_id))
    )


@bp.get("/site-visit-findings")
def list_findings():
    authorize(*ALL_ROLES)
    limit, offset = pagination()
    return listing(
        db.all_rows("site_visit_findings"),
        serializers.site_visit_finding,
        limit,
        offset,
        specs=[
            ("health_center_id", "health_center_id", "string"),
            ("service_site_id", "service_site_id", "string"),
            ("status", "status", "string"),
            ("severity", "severity", "string"),
        ],
    )


# --------------------------------------------------------------------------- #
# corrective action plans
# --------------------------------------------------------------------------- #


@bp.post("/site-visit-findings/<finding_id>/corrective-action-plans")
def create_plan(finding_id):
    user_id = authorize("ComplianceOfficer")
    body = parse_body(PLAN_FIELDS)
    finding = require("site_visit_findings", finding_id)
    owner_ref(body, "site_visit_finding_id", "site_visit_findings", finding_id)

    # Rung 26 — the plan may not target a date past the finding's due instant.
    if body["target_completion_date"] > finding["cap_due_at"]:
        raise ApiError("ERR_CAP_TARGET_AFTER_DUE")

    row = db.base_row()
    row.update(
        {
            "site_visit_finding_id": finding_id,
            "narrative": body["narrative"],
            "milestone_count": body["milestone_count"],
            "target_completion_date": body["target_completion_date"],
            "status": "DRAFT",
            "submit_round": 0,
            "prepared_by_user_id": user_id,
            "adjudicated_by_user_id": None,
            "rejection_reason": None,
        }
    )
    db.db.corrective_action_plans[row["id"]] = row
    return object_response(serializers.corrective_action_plan(row), 201)


@bp.get("/corrective-action-plans/<plan_id>")
def read_plan(plan_id):
    authorize(*ALL_ROLES)
    return object_response(
        serializers.corrective_action_plan(require("corrective_action_plans", plan_id))
    )


@bp.get("/site-visit-findings/<finding_id>/corrective-action-plans")
def list_plans(finding_id):
    authorize(*ALL_ROLES)
    limit, offset = pagination()
    require("site_visit_findings", finding_id)
    return listing(
        _plans_of(finding_id),
        serializers.corrective_action_plan,
        limit,
        offset,
        specs=[("status", "status", "string")],
    )


@bp.post("/corrective-action-plans/<plan_id>/submit")
def submit_plan(plan_id):
    authorize("ComplianceOfficer")
    parse_body([])
    plan = require("corrective_action_plans", plan_id)
    finding = db.db.site_visit_findings.get(plan["site_visit_finding_id"])
    if finding is None:
        raise ApiError("ERR_SITE_VISIT_FINDING_NOT_FOUND")

    # Rung 11 applies to the plan and to the parent finding it must drive.
    state(plan, "status", ("DRAFT", "REJECTED"))
    state(finding, "status", ("OPEN", "ESCALATED"))

    looping = plan["status"] == "REJECTED"
    if looping and plan["submit_round"] >= MAX_CAP_SUBMIT_ROUNDS:
        raise ApiError("ERR_LOOP_LIMIT_EXCEEDED")

    if looping:
        plan["submit_round"] += 1
        plan["rejection_reason"] = None
        plan["adjudicated_by_user_id"] = None
    plan["status"] = "SUBMITTED"
    db.touch(plan)

    finding["status"] = "CAP_SUBMITTED"
    db.touch(finding)
    return object_response(serializers.corrective_action_plan(plan))


@bp.post("/corrective-action-plans/<plan_id>/adjudicate")
def adjudicate_plan(plan_id):
    user_id = authorize("ProjectOfficer")
    body = parse_body(
        [
            Field("decision", "enum", required=True, enum=("ACCEPT", "REJECT")),
            Field("rejection_reason", "string", nullable=True),
        ]
    )
    plan = require("corrective_action_plans", plan_id)
    finding = db.db.site_visit_findings.get(plan["site_visit_finding_id"])
    if finding is None:
        raise ApiError("ERR_SITE_VISIT_FINDING_NOT_FOUND")

    state(plan, "status", ("SUBMITTED",))
    state(finding, "status", ("CAP_SUBMITTED",))
    segregation(user_id, plan["prepared_by_user_id"])

    plan["adjudicated_by_user_id"] = user_id

    if body["decision"] == "ACCEPT":
        plan["status"] = "ACCEPTED"
        db.touch(plan)
        # Depth-4 compensating cascade: the finding resolves, the grantee's open
        # condition count drops, scope unfreezes and the parked rows come back.
        cascade.resolve_finding(finding)
        hc = db.db.health_centers.get(finding["health_center_id"])
        if hc is not None:
            hc_svc.bump(hc)
    else:
        plan["status"] = "REJECTED"
        plan["rejection_reason"] = body.get("rejection_reason")
        db.touch(plan)
        # A finding that had already escalated stays escalated.
        finding["status"] = "ESCALATED" if finding["escalated_at"] is not None else "OPEN"
        db.touch(finding)

    return object_response(serializers.corrective_action_plan(plan))
