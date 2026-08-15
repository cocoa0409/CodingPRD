"""Impact assessments: assignment (OCC), scoring, acceptance cascade (PRD §3.4)."""

from decimal import Decimal

from flask import Blueprint, request

from db import new_id, now_clock, stamp_new, store, touch
from errors import (ApiError, ERR_CHANGE_NOT_TRIAGED_APPLICABLE,
                    ERR_OWNER_SUSPENDED, ERR_STALE_CHANGE_VERSION,
                    invalid_state, not_resource_owner)
from middleware import (auth_context, get_body, get_or_404, req_dt, req_int,
                        req_str, require_roles)
from response import paginate, success_object
from serializers import (ACTIVE_ASSESSMENT_STATUSES, assessment_to_api,
                         created_sorted)
from services.audit import append_audit
from services.calculations import CRITICALITY_POINTS, confirmed_impact
from services.cascades import create_escalation, recompute_gap

bp = Blueprint("impact_assessments", __name__)

NON_TERMINAL = ("ASSIGNED", "IN_PROGRESS", "RETURNED", "SUBMITTED")


def _owner_suspended(owner_id):
    open_count = sum(
        1 for e in store.escalations.values()
        if e["business_owner_id"] == owner_id and e["status"] in ("OPEN", "ACKNOWLEDGED"))
    return open_count >= 3


@bp.post("/compliance/impact-assessments")
def create_assessment():
    user_id, role = auth_context()
    require_roles(role, ("ComplianceOfficer",))
    body = get_body()
    change_id = req_str(body, "regulatory_change_id")
    owner_id = req_str(body, "business_owner_id")
    due_date = req_dt(body, "due_date")
    expected_version = req_int(body, "expected_regulatory_change_version")

    # Priority 3: body FK existence.
    change = get_or_404(store.regulatory_changes, change_id, "regulatory change")
    owner = get_or_404(store.business_owners, owner_id, "business owner")

    # OCC on the change (listed first among domain checks for this endpoint).
    if expected_version != change["version"]:
        raise ApiError(ERR_STALE_CHANGE_VERSION, 412,
                       "expected_regulatory_change_version != current "
                       "RegulatoryChange.version")

    # Priority 5: owner suspension.
    if _owner_suspended(owner["id"]):
        raise ApiError(ERR_OWNER_SUSPENDED, 403,
                       "Assignee BusinessOwner has assignment_suspended == true")

    # Priority 6: temporal.
    if not due_date > now_clock():
        from errors import ERR_DEADLINE_IN_PAST
        raise ApiError(ERR_DEADLINE_IN_PAST, 422,
                       "due_date is not strictly after the logical clock")

    # Priority 8: referential state.
    if change["status"] != "TRIAGED_APPLICABLE":
        raise ApiError(ERR_CHANGE_NOT_TRIAGED_APPLICABLE, 409,
                       "Referenced change is not TRIAGED_APPLICABLE")

    # Supersede any prior non-terminal assessment of this change.
    predecessor_id = None
    for prior in store.assessments.values():
        if (prior["regulatory_change_id"] == change["id"]
                and prior["status"] in NON_TERMINAL):
            prior["status"] = "SUPERSEDED"
            touch(prior)
            predecessor_id = prior["id"]

    assessment = stamp_new({
        "id": new_id(),
        "regulatory_change_id": change["id"],
        "business_owner_id": owner["id"],
        "due_date": due_date,
        "likelihood_score": None,
        "severity_score": None,
        "affected_business_lines": None,
        "findings_summary": None,
        "impact_rating_raw": None,
        "impact_tier": None,
        "sla_breached": False,
        "status": "ASSIGNED",
        "supersedes_assessment_id": predecessor_id,
        "return_count": 0,
        "submitted_at": None,
    })
    store.assessments[assessment["id"]] = assessment

    change["business_owner_id"] = owner["id"]
    touch(change)

    append_audit(user_id, role, "POST /compliance/impact-assessments",
                 "ImpactAssessment", assessment["id"])
    return success_object(assessment_to_api(assessment), status=201)


@bp.get("/compliance/impact-assessments")
def list_assessments():
    auth_context()
    items = created_sorted(store.assessments.values())
    for param in ("regulatory_change_id", "business_owner_id", "status",
                  "supersedes_assessment_id"):
        value = request.args.get(param)
        if value is not None:
            items = [a for a in items if a[param] == value]
    return paginate(items, assessment_to_api)


@bp.get("/compliance/impact-assessments/<assessment_id>")
def get_assessment(assessment_id):
    auth_context()
    assessment = get_or_404(store.assessments, assessment_id, "impact assessment")
    return success_object(assessment_to_api(assessment))


def _owned_assessment(assessment_id, user_id):
    assessment = get_or_404(store.assessments, assessment_id, "impact assessment")
    if assessment["business_owner_id"] != user_id:
        raise not_resource_owner()
    return assessment


@bp.post("/compliance/impact-assessments/<assessment_id>/start")
def start_assessment(assessment_id):
    user_id, role = auth_context()
    require_roles(role, ("BusinessOwner",))
    assessment = _owned_assessment(assessment_id, user_id)
    if assessment["status"] not in ("ASSIGNED", "RETURNED"):
        raise invalid_state("start requires status ASSIGNED or RETURNED")
    assessment["status"] = "IN_PROGRESS"
    touch(assessment)
    append_audit(user_id, role, "POST /compliance/impact-assessments/{id}/start",
                 "ImpactAssessment", assessment["id"])
    return success_object(assessment_to_api(assessment))


@bp.post("/compliance/impact-assessments/<assessment_id>/submit")
def submit_assessment(assessment_id):
    user_id, role = auth_context()
    require_roles(role, ("BusinessOwner",))
    body = get_body()
    likelihood = req_int(body, "likelihood_score", minimum=1, maximum=5)
    severity = req_int(body, "severity_score", minimum=1, maximum=5)
    lines = req_int(body, "affected_business_lines", minimum=1)
    findings = req_str(body, "findings_summary")

    assessment = _owned_assessment(assessment_id, user_id)
    if assessment["status"] != "IN_PROGRESS":
        raise invalid_state("submit requires status IN_PROGRESS")

    raw, tier = confirmed_impact(likelihood, severity, lines)
    clock = now_clock()
    assessment["likelihood_score"] = likelihood
    assessment["severity_score"] = severity
    assessment["affected_business_lines"] = lines
    assessment["findings_summary"] = findings
    assessment["impact_rating_raw"] = raw
    assessment["impact_tier"] = tier
    assessment["submitted_at"] = clock
    assessment["sla_breached"] = clock > assessment["due_date"]
    assessment["status"] = "SUBMITTED"
    touch(assessment)
    append_audit(user_id, role, "POST /compliance/impact-assessments/{id}/submit",
                 "ImpactAssessment", assessment["id"])
    return success_object(assessment_to_api(assessment))


@bp.post("/compliance/impact-assessments/<assessment_id>/accept")
def accept_assessment(assessment_id):
    user_id, role = auth_context()
    require_roles(role, ("ComplianceManager",))
    assessment = get_or_404(store.assessments, assessment_id, "impact assessment")
    if assessment["status"] != "SUBMITTED":
        raise invalid_state("accept requires status SUBMITTED")

    assessment["status"] = "ACCEPTED"
    touch(assessment)

    # Cascade link 0: stamp the confirmed risk tier onto the change.
    change = store.regulatory_changes.get(assessment["regulatory_change_id"])
    if change is not None:
        change["risk_tier"] = assessment["impact_tier"]
        touch(change)

    # Cascade link 1+2: GapAnalysis per ACTIVE obligation, scores computed now.
    # Cascade link 3: zero-coverage HIGH/CRITICAL gaps spawn escalations.
    active_obligations = [
        o for o in created_sorted(store.obligations.values())
        if o["regulatory_change_id"] == assessment["regulatory_change_id"]
        and o["status"] == "ACTIVE"
    ]
    for obligation in active_obligations:
        gap = stamp_new({
            "id": new_id(),
            "impact_assessment_id": assessment["id"],
            "obligation_id": obligation["id"],
            "requirement_points": CRITICALITY_POINTS[obligation["criticality"]],
            "covered_points": Decimal("0"),
            "residual_gap_points": Decimal("0"),
            "status": "OPEN",
            "confirmed_by_user_id": None,
            "confirmed_at": None,
        })
        store.gap_analyses[gap["id"]] = gap
        recompute_gap(gap)
        if (gap["residual_gap_points"] == gap["requirement_points"]
                and obligation["criticality"] in ("HIGH", "CRITICAL")):
            create_escalation("OBLIGATION", obligation["id"], "ZERO_COVERAGE", None)

    append_audit(user_id, role, "POST /compliance/impact-assessments/{id}/accept",
                 "ImpactAssessment", assessment["id"])
    return success_object(assessment_to_api(assessment))


@bp.post("/compliance/impact-assessments/<assessment_id>/return")
def return_assessment(assessment_id):
    user_id, role = auth_context()
    require_roles(role, ("ComplianceManager",))
    body = get_body()
    req_str(body, "comments")

    assessment = get_or_404(store.assessments, assessment_id, "impact assessment")
    if assessment["status"] != "SUBMITTED":
        raise invalid_state("return requires status SUBMITTED")
    assessment["status"] = "RETURNED"
    assessment["return_count"] += 1
    touch(assessment)
    append_audit(user_id, role, "POST /compliance/impact-assessments/{id}/return",
                 "ImpactAssessment", assessment["id"])
    return success_object(assessment_to_api(assessment))
