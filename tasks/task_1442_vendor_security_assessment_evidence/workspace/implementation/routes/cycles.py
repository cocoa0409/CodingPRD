"""AssessmentCycle lifecycle (PRD §3.3, §3.4, §3.5, §3.7): OCC-guarded
creation, issuance with template version pinning, questionnaire scoring with
its pass/fail branch, evidence-review completion with its three-way branch,
remediation resolution, and SecurityApprover verdicts.
"""
from flask import Blueprint, g, request

import calc
import db
import errors
import helpers
import util
from errors import ApiError
from middleware import (body, paginate, require_roles, scope_vendor_or_403,
                        vc_vendor_id)
from response import ok, ok_list
from serializers import serialize

bp = Blueprint("cycles", __name__, url_prefix="/vsa")

CYCLE_CREATE_ALLOWED_POSTURES = ("ONBOARDING", "APPROVED", "CONDITIONAL", "SUSPENDED")
# ASSESSING is included so the system-created DRAFT cycle that alert
# escalation or the reassessment-due sweep installs as active_cycle_id
# remains issuable — otherwise an escalated vendor would be wedged in
# ASSESSING with a DRAFT cycle it can never issue.
ISSUE_ALLOWED_POSTURES = ("ONBOARDING", "APPROVED", "CONDITIONAL", "ASSESSING")


def _resolve(vid, cid):
    vendor = helpers.get_vendor(vid)
    scope_vendor_or_403(vid)
    cycle = helpers.get_cycle_for_vendor(vendor, cid)
    return vendor, cycle


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


@bp.post("/vendors/<vid>/cycles")
@require_roles("RiskAnalyst")
def create_cycle(vid):
    vendor = helpers.get_vendor(vid)
    data = body()
    # OCC (priority 6): stale expected_vendor_version -> 412.
    if "expected_vendor_version" in data and data["expected_vendor_version"] is not None:
        expected = data["expected_vendor_version"]
        if not _is_int(expected):
            raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                           "expected_vendor_version must be an integer")
        if expected != vendor["version"]:
            raise ApiError(errors.ERR_STALE_VENDOR_VERSION, 412,
                           "Vendor version has advanced beyond expected_vendor_version")
    # Schema (priority 8): both fields are non-optional inputs.
    if "expected_vendor_version" not in data or data["expected_vendor_version"] is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "expected_vendor_version is required")
    template_id = data.get("template_id")
    if not isinstance(template_id, str) or not template_id:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "template_id is required")
    # Uniqueness (priority 9): at most one non-terminal cycle per vendor.
    if helpers.non_terminal_cycle(vendor) is not None:
        raise ApiError(errors.ERR_CYCLE_ALREADY_ACTIVE, 409,
                       "Vendor already has a non-terminal assessment cycle")
    # Posture gate (priority 14).
    if vendor["posture"] not in CYCLE_CREATE_ALLOWED_POSTURES:
        raise ApiError(errors.ERR_VENDOR_POSTURE_BLOCKS, 422,
                       "Vendor posture %s does not permit new assessment work"
                       % vendor["posture"])
    cycle = {
        "vendor_id": vid,
        "template_id": template_id,
        "template_version": None,
        "tier_at_issue": None,
        "status": "DRAFT",
        "issued_at": None,
        "response_due_at": None,
        "questionnaire_score": None,
        "evidence_score": None,
        "composite_score": None,
        "open_exception_count": 0,
        "acceptance_required": False,
        "_evidence_review_completed_by": None,
    }
    helpers.stamp_new("cycles", cycle)
    db.cycles[cycle["id"]] = cycle
    vendor["active_cycle_id"] = cycle["id"]
    helpers.touch("vendors", vendor)
    return ok(serialize("cycle", cycle), 201)


@bp.get("/vendors/<vid>/cycles")
@require_roles("RiskAnalyst", "SecurityApprover", "VendorContact")
def list_vendor_cycles(vid):
    helpers.get_vendor(vid)
    scope_vendor_or_403(vid)
    items = helpers.vendor_cycles(vid)
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, limit, offset, total = paginate(items)
    return ok_list([serialize("cycle", c) for c in page], limit, offset, total)


def _scope_cycle(cycle):
    if g.role == "VendorContact" and vc_vendor_id() != cycle["vendor_id"]:
        raise ApiError(errors.ERR_FORBIDDEN, 403,
                       "VendorContact scope is limited to its own vendor")


def _get_cycle(cid):
    cycle = db.cycles.get(cid)
    if cycle is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "AssessmentCycle %s not found" % cid)
    _scope_cycle(cycle)
    return cycle


@bp.get("/cycles/<cid>")
@require_roles("RiskAnalyst", "SecurityApprover", "VendorContact")
def get_cycle(cid):
    return ok(serialize("cycle", _get_cycle(cid)))


@bp.get("/cycles/<cid>/responses")
@require_roles("RiskAnalyst", "SecurityApprover", "VendorContact")
def list_cycle_responses(cid):
    _get_cycle(cid)
    items = [r for r in db.responses.values() if r["cycle_id"] == cid]
    page, limit, offset, total = paginate(items)
    return ok_list([serialize("response", r) for r in page], limit, offset, total)


@bp.get("/cycles/<cid>/evidence")
@require_roles("RiskAnalyst", "SecurityApprover", "VendorContact")
def list_cycle_evidence(cid):
    _get_cycle(cid)
    items = [a for a in db.artifacts.values() if a["cycle_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, limit, offset, total = paginate(items)
    return ok_list([serialize("artifact", a) for a in page], limit, offset, total)


@bp.get("/cycles/<cid>/exceptions")
@require_roles("RiskAnalyst", "SecurityApprover", "VendorContact")
def list_cycle_exceptions(cid):
    _get_cycle(cid)
    items = helpers.cycle_exceptions(cid)
    items = _filter_exceptions(items)
    page, limit, offset, total = paginate(items)
    return ok_list([serialize("exception", e) for e in page], limit, offset, total)


def _filter_exceptions(items):
    status = request.args.get("status")
    severity = request.args.get("severity")
    artifact = request.args.get("evidence_artifact_id")
    cycle_id = request.args.get("cycle_id")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    if severity is not None:
        items = [e for e in items if e["severity"] == severity]
    if artifact is not None:
        items = [e for e in items if (e.get("evidence_artifact_id") or "") == artifact]
    if cycle_id is not None:
        items = [e for e in items if e["cycle_id"] == cycle_id]
    return items


@bp.get("/cycles/<cid>/remediation-plans")
@require_roles("RiskAnalyst", "SecurityApprover", "VendorContact")
def list_cycle_plans(cid):
    _get_cycle(cid)
    items = helpers.cycle_plans(cid)
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, limit, offset, total = paginate(items)
    return ok_list([serialize("plan", p) for p in page], limit, offset, total)


@bp.get("/cycles/<cid>/risk-acceptances")
@require_roles("RiskAnalyst", "SecurityApprover")
def list_cycle_acceptances(cid):
    _get_cycle(cid)
    items = helpers.cycle_acceptances(cid)
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, limit, offset, total = paginate(items)
    return ok_list([serialize("acceptance", r) for r in page], limit, offset, total)


@bp.get("/cycles/<cid>/addenda")
@require_roles("RiskAnalyst", "SecurityApprover", "VendorContact")
def list_cycle_addenda(cid):
    _get_cycle(cid)
    items = helpers.cycle_addenda(cid)
    page, limit, offset, total = paginate(items)
    return ok_list([serialize("addendum", a) for a in page], limit, offset, total)


@bp.post("/vendors/<vid>/cycles/<cid>/issue")
@require_roles("RiskAnalyst")
def issue_cycle(vid, cid):
    vendor, cycle = _resolve(vid, cid)
    if cycle["status"] != "DRAFT":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Only a DRAFT cycle can be issued")
    if vendor["posture"] not in ISSUE_ALLOWED_POSTURES:
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Vendor posture %s does not permit issuance" % vendor["posture"])
    if vendor.get("active_cycle_id") != cid:
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Cycle is not the vendor's active cycle")
    # Re-run tier assignment and snapshot it (PRD §3.3).
    helpers.reassign_tier(vendor)
    cycle["tier_at_issue"] = vendor["current_tier"]
    template = _resolve_template_for_issue(cycle)
    # Version pinning: identity + published_version frozen for this cycle.
    cycle["template_id"] = template["id"]
    cycle["template_version"] = template["published_version"]
    cycle["issued_at"] = util.iso(util.now())
    cycle["response_due_at"] = util.iso(
        calc.response_due(util.now(), cycle["tier_at_issue"]))
    cycle["status"] = "ISSUED"
    vendor["posture"] = "ASSESSING"
    helpers.touch("cycles", cycle)
    helpers.touch("vendors", vendor)
    helpers.refresh_risk(vendor)
    return ok(serialize("cycle", cycle))


def _resolve_template_for_issue(cycle):
    """Pinned template must be PUBLISHED at issue time; a system-created cycle
    without a template picks the highest-priority eligible PUBLISHED template
    (highest published_version, earliest created wins ties)."""
    tid = cycle.get("template_id")
    if tid:
        template = db.templates.get(tid)
        if template is None or template["status"] != "PUBLISHED":
            raise ApiError(errors.ERR_TEMPLATE_NOT_PUBLISHED, 422,
                           "Cycle template is not PUBLISHED at issue time")
        return template
    tier = cycle["tier_at_issue"]
    eligible = [t for t in db.templates.values()
                if t["status"] == "PUBLISHED" and tier in t.get("applies_to_tiers", [])]
    if not eligible:
        raise ApiError(errors.ERR_TEMPLATE_NOT_PUBLISHED, 422,
                       "No PUBLISHED template is eligible for %s" % tier)
    eligible.sort(key=lambda t: (-t["published_version"], t["_seq"]))
    return eligible[0]


def _submitted_response(cycle):
    for r in db.responses.values():
        if r["cycle_id"] == cycle["id"] and r["status"] == "SUBMITTED":
            return r
    return None


@bp.post("/vendors/<vid>/cycles/<cid>/score")
@require_roles("RiskAnalyst")
def score_cycle(vid, cid):
    vendor, cycle = _resolve(vid, cid)
    if cycle["status"] != "RESPONSE_RECEIVED":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Cycle is not awaiting scoring")
    response = _submitted_response(cycle)
    if response is None:
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "No SUBMITTED response exists for this cycle")
    template = db.templates.get(cycle.get("template_id"))
    raw, score = calc.questionnaire_final(template, response)
    response["raw_score"] = util.num(raw)
    cycle["questionnaire_score"] = util.num(score)
    threshold = calc.PASS_THRESHOLD[cycle["tier_at_issue"]]
    if score >= threshold:
        response["status"] = "ACCEPTED"
        cycle["status"] = "SCORED"
    else:
        # Fail branch: workflow outcome, not an error (PRD §3.4).
        response["status"] = "RETURNED"
        response["revision_count"] += 1
    helpers.touch("responses", response)
    helpers.touch("cycles", cycle)
    return ok(serialize("cycle", cycle))


@bp.post("/vendors/<vid>/cycles/<cid>/evidence-review/complete")
@require_roles("RiskAnalyst")
def complete_evidence_review(vid, cid):
    vendor, cycle = _resolve(vid, cid)
    if cycle["status"] != "EVIDENCE_REVIEW":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Cycle is not in EVIDENCE_REVIEW")
    artifacts = helpers.cycle_artifacts(cid)
    if any(a["status"] in ("RECEIVED", "UNDER_REVIEW") for a in artifacts):
        raise ApiError(errors.ERR_EVIDENCE_PENDING_REVIEW, 422,
                       "Evidence artifacts remain in RECEIVED or UNDER_REVIEW")
    cycle["_evidence_review_completed_by"] = g.user_id
    cycle["evidence_score"] = util.num(calc.evidence_review_score(cycle))
    cycle["composite_score"] = util.num(calc.composite_cycle_score(cycle))
    calc.recompute_acceptance_required(cycle)
    if cycle["open_exception_count"] > 0:
        # Remediation path: generate the required contract addendum (§3.7).
        cycle["status"] = "REMEDIATION"
        addendum = {
            "vendor_id": vid,
            "cycle_id": cid,
            "clause_set": calc.addendum_clause_set(cycle),
            "status": "REQUIRED",
            "signed_at": None,
            "waived_reason": None,
        }
        helpers.stamp_new("addenda", addendum)
        db.addenda[addendum["id"]] = addendum
        helpers.touch("cycles", cycle)
        return ok(serialize("cycle", cycle))
    if cycle["acceptance_required"]:
        cycle["status"] = "RISK_ACCEPTANCE_REVIEW"
        helpers.touch("cycles", cycle)
        return ok(serialize("cycle", cycle))
    # Clean pass attempt (PRD §3.5).
    if any(a["status"] != "REVIEWED_CLEAN" for a in artifacts):
        raise ApiError(errors.ERR_OPEN_ITEMS_OUTSTANDING, 422,
                       "Not all artifacts were reviewed clean")
    threshold = calc.PASS_THRESHOLD[cycle["tier_at_issue"]]
    if util.dec(cycle["composite_score"]) < threshold:
        raise ApiError(errors.ERR_SCORE_BELOW_THRESHOLD, 422,
                       "Composite score is below the tier pass threshold")
    if any(a["status"] in ("REQUIRED", "DRAFTED")
           for a in helpers.cycle_addenda(cid)):
        raise ApiError(errors.ERR_OPEN_ITEMS_OUTSTANDING, 422,
                       "An outstanding contract addendum blocks approval")
    cycle["status"] = "APPROVED"
    _approve_vendor_side_effects(vendor, conditional=False)
    helpers.touch("cycles", cycle)
    return ok(serialize("cycle", cycle))


def _approve_vendor_side_effects(vendor, conditional):
    """Shared approval cascade: posture, cadence-derived next_reassessment_due
    (halved for CONDITIONAL), TIER_CADENCE schedule event, risk refresh."""
    now = util.now()
    policy = helpers.active_policy() or {}
    months = policy.get(
        "tier%s_reassessment_months" % vendor["current_tier"][-1], 12)
    if conditional:
        months = months // 2
    previous_due = (util.parse_dt(vendor["next_reassessment_due"])
                    if vendor.get("next_reassessment_due") else None)
    new_due = util.add_months(now, months)
    vendor["posture"] = "CONDITIONAL" if conditional else "APPROVED"
    vendor["next_reassessment_due"] = util.iso(new_due)
    vendor["active_cycle_id"] = None
    helpers.append_schedule(vendor["id"], "TIER_CADENCE", previous_due, new_due, None)
    helpers.touch("vendors", vendor)
    helpers.refresh_risk(vendor)


@bp.post("/vendors/<vid>/cycles/<cid>/remediation/resolve")
@require_roles("RiskAnalyst")
def resolve_remediation(vid, cid):
    vendor, cycle = _resolve(vid, cid)
    if cycle["status"] != "REMEDIATION":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Cycle is not in REMEDIATION")
    plans = helpers.cycle_plans(cid)
    if (any(p["status"] not in ("VERIFIED", "REJECTED") for p in plans)
            or cycle["open_exception_count"] != 0):
        raise ApiError(errors.ERR_OPEN_ITEMS_OUTSTANDING, 422,
                       "Remediation cannot resolve with undecided plans or open exceptions")
    cycle["composite_score"] = util.num(calc.composite_cycle_score(cycle))
    calc.recompute_acceptance_required(cycle)
    cycle["status"] = "RISK_ACCEPTANCE_REVIEW"
    helpers.touch("cycles", cycle)
    return ok(serialize("cycle", cycle))


@bp.post("/vendors/<vid>/cycles/<cid>/approve")
@require_roles("SecurityApprover")
def approve_cycle(vid, cid):
    vendor, cycle = _resolve(vid, cid)
    if cycle["status"] != "RISK_ACCEPTANCE_REVIEW":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Cycle is not in RISK_ACCEPTANCE_REVIEW")
    # Segregation of duties: approver != analyst who completed evidence review.
    if g.user_id == cycle.get("_evidence_review_completed_by"):
        raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 422,
                       "Cycle approver must differ from the evidence-review completer")
    if cycle["open_exception_count"] != 0:
        raise ApiError(errors.ERR_OPEN_ITEMS_OUTSTANDING, 422,
                       "Open exceptions block cycle approval")
    if any(r["status"] not in ("APPROVED", "REJECTED")
           for r in helpers.cycle_acceptances(cid)):
        raise ApiError(errors.ERR_OPEN_ITEMS_OUTSTANDING, 422,
                       "Undecided risk acceptances block cycle approval")
    if any(a["status"] in ("REQUIRED", "DRAFTED")
           for a in helpers.cycle_addenda(cid)):
        raise ApiError(errors.ERR_ADDENDUM_OUTSTANDING, 422,
                       "A REQUIRED or DRAFTED contract addendum blocks cycle approval")
    conditional = any(r["status"] == "APPROVED"
                      for r in helpers.cycle_acceptances(cid))
    cycle["status"] = "APPROVED"
    _approve_vendor_side_effects(vendor, conditional=conditional)
    helpers.touch("cycles", cycle)
    return ok(serialize("cycle", cycle))


@bp.post("/vendors/<vid>/cycles/<cid>/reject")
@require_roles("SecurityApprover")
def reject_cycle(vid, cid):
    vendor, cycle = _resolve(vid, cid)
    if cycle["status"] != "RISK_ACCEPTANCE_REVIEW":
        raise ApiError(errors.ERR_INVALID_STATE, 409,
                       "Cycle is not in RISK_ACCEPTANCE_REVIEW")
    cycle["status"] = "REJECTED"
    vendor["posture"] = "SUSPENDED"
    vendor["active_cycle_id"] = None
    helpers.touch("cycles", cycle)
    helpers.touch("vendors", vendor)
    helpers.refresh_risk(vendor)
    return ok(serialize("cycle", cycle))
