"""Routes: legal reviews, outcome decisions, employee rebuttals,
consistency reviews, rating-cycle outcome links."""

from flask import Blueprint, request

from core import (
    db, auth, require_role, ok_object, list_response, body, require_field,
    min_len, enum_field, new_record, touch, public, parse_dt, days, ALL_ROLES,
    E_FORBIDDEN, E_NOT_FOUND, E_PARENT_MISMATCH, E_STALE_VERSION,
    E_INVALID_STATE, E_SOD, E_INVALID_REQUEST, E_PIP_NOT_ACTIVE,
    E_PLAN_STILL_RUNNING, E_ATTAINMENT_BELOW, E_EXTENSION_LIMIT,
    E_LEGAL_REVIEW_REQUIRED, E_LEGAL_OVERRIDE_NOT_ALLOWED,
    E_REBUTTAL_WINDOW_CLOSED, E_REBUTTAL_NOT_SUBJECT, E_COHORT_TOO_SMALL,
    err,
)
from business import (
    legal_risk_score, attainment_ratio, apply_approved_outcome_closure,
    pending_rebuttal, close_pip, compute_cohort, disparity_score,
    rating_alignment, latest_approved_decision, REBUTTAL_WINDOW_DAYS,
)
from routes_pips import resolve_pip

bp = Blueprint("outcome_routes", __name__)

LEGAL_READERS = ["HRSystemAdmin", "HRBusinessPartner", "HRDirector", "LegalCounsel"]
RISK_FACTOR_CODES = {
    "PROTECTED_CLASS", "RECENT_LEAVE", "WHISTLEBLOWER_HISTORY",
    "PRIOR_COMPLAINT", "RETALIATION_WINDOW", "DOCUMENTATION_GAP",
}
RECOMMENDATIONS = {"PROCEED", "PROCEED_WITH_CAUTION", "HOLD", "REJECT"}
OUTCOMES = {"SUCCESS", "EXTENSION", "TERMINATION"}
PIP_CLOSED = ("CLOSED_SUCCESS", "CLOSED_FAILED", "CLOSED_TERMINATED",
              "CLOSED_WITHDRAWN")


# ---------------------------------------------------------------------------
# Resolvers
# ---------------------------------------------------------------------------

def resolve_legal_review(ou_id, emp_id, pip_id, review_id):
    ou, emp, pip = resolve_pip(ou_id, emp_id, pip_id)
    r = db.legal_reviews.get(review_id)
    if r is None:
        err(E_NOT_FOUND, "legal review not found")
    if r["pip_id"] != pip["id"]:
        err(E_PARENT_MISMATCH, "legal review does not belong to PIP")
    return ou, emp, pip, r


def resolve_decision(ou_id, emp_id, pip_id, decision_id):
    ou, emp, pip = resolve_pip(ou_id, emp_id, pip_id)
    d = db.decisions.get(decision_id)
    if d is None:
        err(E_NOT_FOUND, "outcome decision not found")
    if d["pip_id"] != pip["id"]:
        err(E_PARENT_MISMATCH, "outcome decision does not belong to PIP")
    return ou, emp, pip, d


def resolve_rebuttal_rec(ou_id, emp_id, pip_id, rebuttal_id):
    ou, emp, pip = resolve_pip(ou_id, emp_id, pip_id)
    r = db.rebuttals.get(rebuttal_id)
    if r is None:
        err(E_NOT_FOUND, "rebuttal not found")
    if r["pip_id"] != pip["id"]:
        err(E_PARENT_MISMATCH, "rebuttal does not belong to PIP")
    return ou, emp, pip, r


def resolve_consistency(ou_id, review_id):
    from routes_core import resolve_ou
    ou = resolve_ou(ou_id)
    r = db.consistency.get(review_id)
    if r is None:
        err(E_NOT_FOUND, "consistency review not found")
    if r["hr_org_unit_id"] != ou["id"]:
        err(E_PARENT_MISMATCH, "consistency review does not belong to org unit")
    return ou, r


def _legal_ok_for_termination(pip):
    for r in db.legal_reviews.values():
        if r["pip_id"] != pip["id"]:
            continue
        if r["status"] == "OVERRIDDEN":
            return True
        if r["status"] == "SUBMITTED" and r.get("recommendation") != "REJECT":
            return True
    return False


# ---------------------------------------------------------------------------
# Legal reviews
# ---------------------------------------------------------------------------

@bp.post("/hr-org-units/<ouId>/employees/<empId>/pips/<pipId>/legal-reviews")
def create_legal_review(ouId, empId, pipId):
    uid, role = auth()
    require_role(role, ["HRBusinessPartner"])
    ou, emp, pip = resolve_pip(ouId, empId, pipId)
    b = body()
    counsel_id = require_field(b, "assigned_counsel_id")
    if not isinstance(counsel_id, str):
        err(E_INVALID_REQUEST, "assigned_counsel_id must be a string")
    concern = db.concerns.get(pip["concern_id"])
    if counsel_id == pip["issuing_hrbp_id"] or \
            (concern is not None and counsel_id == concern["raised_by_manager_id"]):
        err(E_SOD, "assigned counsel must be neither the issuing HRBP nor the "
                   "raising manager")
    rec = new_record()
    rec.update({
        "pip_id": pip["id"],
        "requested_by_hrbp_id": uid,
        "assigned_counsel_id": counsel_id,
        "risk_score": None,
        "risk_factors": None,
        "recommendation": None,
        "rationale": None,
        "status": "REQUESTED",
        "submitted_at": None,
        "decided_by_director_id": None,
    })
    db.legal_reviews[rec["id"]] = rec
    return ok_object(public(rec), 201)


@bp.get("/hr-org-units/<ouId>/employees/<empId>/pips/<pipId>/legal-reviews")
def list_legal_reviews(ouId, empId, pipId):
    uid, role = auth()
    require_role(role, LEGAL_READERS)
    ou, emp, pip = resolve_pip(ouId, empId, pipId)
    filters = {"status": request.args.get("status")}
    records = [r for r in db.legal_reviews.values() if r["pip_id"] == pip["id"]]
    return list_response(records, filters)


@bp.post("/hr-org-units/<ouId>/employees/<empId>/pips/<pipId>/legal-reviews/<reviewId>/claim")
def claim_legal_review(ouId, empId, pipId, reviewId):
    uid, role = auth()
    require_role(role, ["LegalCounsel"])
    ou, emp, pip, r = resolve_legal_review(ouId, empId, pipId, reviewId)
    if r["status"] != "REQUESTED":
        err(E_INVALID_STATE, "legal review is not REQUESTED")
    if r["assigned_counsel_id"] != uid:
        err(E_FORBIDDEN, "only the assigned counsel may claim this review")
    r["status"] = "IN_REVIEW"
    touch(r)
    return ok_object(public(r))


@bp.post("/hr-org-units/<ouId>/employees/<empId>/pips/<pipId>/legal-reviews/<reviewId>/submit")
def submit_legal_review(ouId, empId, pipId, reviewId):
    uid, role = auth()
    require_role(role, ["LegalCounsel"])
    ou, emp, pip, r = resolve_legal_review(ouId, empId, pipId, reviewId)
    if r["status"] != "IN_REVIEW":
        err(E_INVALID_STATE, "legal review is not IN_REVIEW")
    if r["assigned_counsel_id"] != uid:
        err(E_FORBIDDEN, "only the assigned counsel may submit this review")
    b = body()
    if "risk_factors" not in b or "recommendation" not in b or "rationale" not in b \
            or b.get("risk_factors") is None or b.get("recommendation") is None \
            or b.get("rationale") is None:
        err(E_INVALID_REQUEST, "risk_factors, recommendation and rationale are required")
    risk_factors = b["risk_factors"]
    if not isinstance(risk_factors, list) or \
            any(f not in RISK_FACTOR_CODES for f in risk_factors):
        err(E_INVALID_REQUEST, "risk_factors contains an unknown factor code")
    recommendation = enum_field(b["recommendation"], RECOMMENDATIONS, "recommendation")
    rationale = min_len(b["rationale"], 40, "rationale")
    r["risk_factors"] = list(risk_factors)
    r["recommendation"] = recommendation
    r["rationale"] = rationale
    r["risk_score"] = legal_risk_score(risk_factors)
    r["status"] = "SUBMITTED"
    r["submitted_at"] = ou["current_utc"]
    touch(r)
    if recommendation == "REJECT":
        for d in db.decisions.values():
            if d["pip_id"] == pip["id"] and d["status"] == "PROPOSED":
                d["status"] = "SUPERSEDED"
                touch(d)
    return ok_object(public(r))


@bp.post("/hr-org-units/<ouId>/employees/<empId>/pips/<pipId>/legal-reviews/<reviewId>/override")
def override_legal_review(ouId, empId, pipId, reviewId):
    uid, role = auth()
    require_role(role, ["HRDirector"])
    ou, emp, pip, r = resolve_legal_review(ouId, empId, pipId, reviewId)
    if r["status"] != "SUBMITTED":
        err(E_INVALID_STATE, "legal review is not SUBMITTED")
    if r["recommendation"] != "REJECT":
        err(E_LEGAL_OVERRIDE_NOT_ALLOWED,
            "only REJECT recommendations may be overridden")
    r["status"] = "OVERRIDDEN"
    r["decided_by_director_id"] = uid
    touch(r)
    return ok_object(public(r))


# ---------------------------------------------------------------------------
# Outcome decisions
# ---------------------------------------------------------------------------

def _apply_outcome_guards(pip, proposed_outcome, final_ratio):
    """The three outcome guards applied at proposal and approval time."""
    if proposed_outcome == "SUCCESS":
        if final_ratio is None or final_ratio < 0.80:
            err(E_ATTAINMENT_BELOW,
                "SUCCESS requires final_attainment_ratio >= 0.80")
    elif proposed_outcome == "EXTENSION":
        if pip["extension_count"] >= 1:
            err(E_EXTENSION_LIMIT, "extension allowance already consumed")
    elif proposed_outcome == "TERMINATION":
        if not _legal_ok_for_termination(pip):
            err(E_LEGAL_REVIEW_REQUIRED,
                "TERMINATION requires a completed legal review without a "
                "standing REJECT recommendation")


@bp.post("/hr-org-units/<ouId>/employees/<empId>/pips/<pipId>/outcome-decisions")
def propose_outcome(ouId, empId, pipId):
    uid, role = auth()
    require_role(role, ["HRBusinessPartner"])
    ou, emp, pip = resolve_pip(ouId, empId, pipId)
    b = body()
    proposed = enum_field(require_field(b, "proposed_outcome"), OUTCOMES,
                          "proposed_outcome")
    rationale = min_len(require_field(b, "rationale"), 40, "rationale")
    if pip["status"] in PIP_CLOSED:
        err(E_INVALID_STATE, "PIP is already closed")
    if uid == pip["issuing_hrbp_id"] and \
            ou["pip_policy_version"] == pip["policy_version_at_issuance"]:
        err(E_SOD, "the proposer must differ from the plan's issuing HRBP")
    final_ratio = attainment_ratio(pip, "FINAL")
    _apply_outcome_guards(pip, proposed, final_ratio)
    # Freeze the final figure on the plan
    pip["final_attainment_ratio"] = final_ratio
    touch(pip)
    # New proposal supersedes any standing PROPOSED decision
    for d in db.decisions.values():
        if d["pip_id"] == pip["id"] and d["status"] == "PROPOSED":
            d["status"] = "SUPERSEDED"
            touch(d)
    rec = new_record()
    rec.update({
        "pip_id": pip["id"],
        "proposed_by_hrbp_id": uid,
        "proposed_outcome": proposed,
        "final_attainment_ratio_at_decision": final_ratio,
        "rationale": rationale,
        "status": "PROPOSED",
        "decided_at": None,
        "decided_by_director_id": None,
    })
    db.decisions[rec["id"]] = rec
    return ok_object(public(rec), 201)


@bp.get("/hr-org-units/<ouId>/employees/<empId>/pips/<pipId>/outcome-decisions")
def list_outcomes(ouId, empId, pipId):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    ou, emp, pip = resolve_pip(ouId, empId, pipId)
    filters = {"status": request.args.get("status")}
    records = [d for d in db.decisions.values() if d["pip_id"] == pip["id"]]
    return list_response(records, filters)


@bp.post("/hr-org-units/<ouId>/employees/<empId>/pips/<pipId>/outcome-decisions/<decisionId>/approve")
def approve_outcome(ouId, empId, pipId, decisionId):
    uid, role = auth()
    require_role(role, ["HRDirector"])
    ou, emp, pip, d = resolve_decision(ouId, empId, pipId, decisionId)
    b = body()
    # OCC before any business rule, when present
    if "expected_pip_version" in b and b["expected_pip_version"] is not None:
        if b["expected_pip_version"] != pip["version"]:
            err(E_STALE_VERSION, "expected_pip_version does not match pip.version")
    if d["status"] != "PROPOSED":
        err(E_INVALID_STATE, "outcome decision is not PROPOSED")
    if d["proposed_by_hrbp_id"] == uid:
        err(E_SOD, "the approving director must not be the proposer")
    if pip["status"] not in ("ACTIVE", "EXTENDED"):
        err(E_PIP_NOT_ACTIVE, "PIP is not ACTIVE or EXTENDED")
    _apply_outcome_guards(pip, d["proposed_outcome"], pip.get("final_attainment_ratio"))
    if parse_dt(ou["current_utc"]) < parse_dt(pip["end_date"]):
        err(E_PLAN_STILL_RUNNING, "the plan window has not ended")
    d["status"] = "APPROVED"
    d["decided_at"] = ou["current_utc"]
    d["decided_by_director_id"] = uid
    touch(d)
    closes_at = parse_dt(d["decided_at"]) + days(REBUTTAL_WINDOW_DAYS)
    pip["rebuttal_window_closes_at"] = _fmt_like_decided(closes_at, d["decided_at"])
    if d["proposed_outcome"] == "EXTENSION":
        if pip["extension_count"] >= 1:
            close_pip(pip, ou, "FAILED")
        else:
            template = db.templates.get(pip["template_id"])
            half = template["duration_days"] // 2
            new_end = parse_dt(pip["end_date"]) + days(half)
            pip["end_date"] = _fmt_like_decided(new_end, pip["end_date"])
            pip["extension_count"] += 1
            # EXTENDED is transient; the plan immediately re-enters ACTIVE
            pip["status"] = "ACTIVE"
    # SUCCESS / TERMINATION closures are deferred until the 5-day rebuttal
    # window resolves (clock sweep) or a rebuttal resolves (§3.6/§3.7).
    touch(pip)
    return ok_object(public(d))


def _fmt_like_decided(dt, ref):
    from core import fmt_like
    return fmt_like(dt, ref)


@bp.post("/hr-org-units/<ouId>/employees/<empId>/pips/<pipId>/outcome-decisions/<decisionId>/reject")
def reject_outcome(ouId, empId, pipId, decisionId):
    uid, role = auth()
    require_role(role, ["HRDirector"])
    ou, emp, pip, d = resolve_decision(ouId, empId, pipId, decisionId)
    if d["status"] != "PROPOSED":
        err(E_INVALID_STATE, "outcome decision is not PROPOSED")
    if d["proposed_by_hrbp_id"] == uid:
        err(E_SOD, "the rejecting director must not be the proposer")
    d["status"] = "REJECTED"
    d["decided_at"] = ou["current_utc"]
    d["decided_by_director_id"] = uid
    touch(d)
    return ok_object(public(d))


# ---------------------------------------------------------------------------
# Employee rebuttals
# ---------------------------------------------------------------------------

@bp.post("/hr-org-units/<ouId>/employees/<empId>/pips/<pipId>/rebuttals")
def create_rebuttal(ouId, empId, pipId):
    uid, role = auth()
    require_role(role, ["Employee"])
    ou, emp, pip = resolve_pip(ouId, empId, pipId)
    b = body()
    decision_id = require_field(b, "outcome_decision_id")
    rebuttal_body = min_len(require_field(b, "body"), 100, "body")
    if uid != pip["employee_id"]:
        err(E_REBUTTAL_NOT_SUBJECT, "only the plan's subject employee may rebut")
    decision = db.decisions.get(decision_id) if isinstance(decision_id, str) else None
    if decision is None or decision["pip_id"] != pip["id"] \
            or decision["status"] != "APPROVED":
        err(E_INVALID_REQUEST, "outcome_decision_id must name an APPROVED decision "
                               "of this PIP")
    now = parse_dt(ou["current_utc"])
    if now > parse_dt(decision["decided_at"]) + days(REBUTTAL_WINDOW_DAYS):
        err(E_REBUTTAL_WINDOW_CLOSED, "the rebuttal window has closed")
    rec = new_record()
    rec.update({
        "pip_id": pip["id"],
        "outcome_decision_id": decision["id"],
        "submitted_by_employee_id": uid,
        "body": rebuttal_body,
        "status": "SUBMITTED",
        "reviewed_by_hrbp_id": None,
        "resolution": None,
        "resolution_rationale": None,
    })
    db.rebuttals[rec["id"]] = rec
    return ok_object(public(rec), 201)


@bp.get("/hr-org-units/<ouId>/employees/<empId>/pips/<pipId>/rebuttals")
def list_rebuttals(ouId, empId, pipId):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    ou, emp, pip = resolve_pip(ouId, empId, pipId)
    filters = {"status": request.args.get("status")}
    records = [r for r in db.rebuttals.values() if r["pip_id"] == pip["id"]]
    return list_response(records, filters)


@bp.post("/hr-org-units/<ouId>/employees/<empId>/pips/<pipId>/rebuttals/<rebuttalId>/start-review")
def start_rebuttal_review(ouId, empId, pipId, rebuttalId):
    uid, role = auth()
    require_role(role, ["HRBusinessPartner"])
    ou, emp, pip, r = resolve_rebuttal_rec(ouId, empId, pipId, rebuttalId)
    if r["status"] != "SUBMITTED":
        err(E_INVALID_STATE, "rebuttal is not SUBMITTED")
    decision = db.decisions.get(r["outcome_decision_id"])
    if uid == pip["issuing_hrbp_id"] or \
            (decision is not None and uid == decision["proposed_by_hrbp_id"]):
        err(E_SOD, "the reviewing HRBP must be neither the issuing HRBP nor "
                   "the outcome proposer")
    r["status"] = "UNDER_REVIEW"
    r["reviewed_by_hrbp_id"] = uid
    touch(r)
    return ok_object(public(r))


@bp.post("/hr-org-units/<ouId>/employees/<empId>/pips/<pipId>/rebuttals/<rebuttalId>/resolve")
def resolve_rebuttal(ouId, empId, pipId, rebuttalId):
    uid, role = auth()
    require_role(role, ["HRBusinessPartner"])
    ou, emp, pip, r = resolve_rebuttal_rec(ouId, empId, pipId, rebuttalId)
    if r["status"] != "UNDER_REVIEW":
        err(E_INVALID_STATE, "rebuttal is not UNDER_REVIEW")
    if r["reviewed_by_hrbp_id"] != uid:
        err(E_FORBIDDEN, "only the reviewing HRBP may resolve this rebuttal")
    b = body()
    resolution = enum_field(require_field(b, "resolution"),
                            {"UPHELD", "OVERRULED"}, "resolution")
    rationale = min_len(require_field(b, "resolution_rationale"), 40,
                        "resolution_rationale")
    r["status"] = resolution
    r["resolution"] = resolution
    r["resolution_rationale"] = rationale
    touch(r)
    # Outcome reversal / finalization
    decision = db.decisions.get(r["outcome_decision_id"])
    if decision is not None and decision["status"] == "APPROVED" \
            and pip["status"] in ("ACTIVE", "EXTENDED"):
        outcome = decision["proposed_outcome"]
        if resolution == "UPHELD":
            if outcome in ("SUCCESS", "TERMINATION"):
                close_pip(pip, ou, outcome)
        else:  # OVERRULED
            if outcome == "SUCCESS":
                close_pip(pip, ou, "FAILED")
            elif outcome == "TERMINATION":
                close_pip(pip, ou, "FAILED")  # termination rescinded
    return ok_object(public(r))


# ---------------------------------------------------------------------------
# Rating-cycle outcome links (read-only)
# ---------------------------------------------------------------------------

@bp.get("/hr-org-units/<ouId>/employees/<empId>/pips/<pipId>/rating-cycle-outcome-links")
def list_links(ouId, empId, pipId):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    ou, emp, pip = resolve_pip(ouId, empId, pipId)
    filters = {"rating_cycle_id": request.args.get("rating_cycle_id")}
    records = [l for l in db.links.values() if l["pip_id"] == pip["id"]]
    return list_response(records, filters)


# ---------------------------------------------------------------------------
# Consistency reviews
# ---------------------------------------------------------------------------

@bp.post("/hr-org-units/<ouId>/consistency-reviews")
def create_consistency_review(ouId):
    uid, role = auth()
    require_role(role, ["HRBusinessPartner"])
    from routes_core import resolve_ou
    ou = resolve_ou(ouId)
    b = body()
    target_pip_id = require_field(b, "target_pip_id")
    target = db.pips.get(target_pip_id) if isinstance(target_pip_id, str) else None
    if target is None:
        err(E_NOT_FOUND, "target PIP not found")
    target_emp = db.employees.get(target["employee_id"])
    if target_emp is None or target_emp["hr_org_unit_id"] != ou["id"]:
        err(E_PARENT_MISMATCH, "target PIP does not belong to this org unit")
    cohort_rows = compute_cohort(ou, target)
    if len(cohort_rows) < 3:
        err(E_COHORT_TOO_SMALL, "fewer than 3 comparable closed PIPs")
    rec = new_record()
    rec.update({
        "hr_org_unit_id": ou["id"],
        "target_pip_id": target["id"],
        "cohort_pip_ids": [p["id"] for p, _ in cohort_rows],
        "cohort_size": len(cohort_rows),
        "outcome_disparity_score": disparity_score(target, cohort_rows),
        "rating_alignment_score": rating_alignment(target["id"]),
        "status": "OPEN",
        "opened_by_hrbp_id": uid,
        "adjudicated_by_director_id": None,
        "adjudication_notes": None,
    })
    db.consistency[rec["id"]] = rec
    return ok_object(public(rec), 201)


@bp.get("/hr-org-units/<ouId>/consistency-reviews")
def list_consistency_reviews(ouId):
    uid, role = auth()
    require_role(role, LEGAL_READERS)
    from routes_core import resolve_ou
    ou = resolve_ou(ouId)
    filters = {"status": request.args.get("status")}
    records = [r for r in db.consistency.values() if r["hr_org_unit_id"] == ou["id"]]
    return list_response(records, filters)


@bp.get("/hr-org-units/<ouId>/consistency-reviews/<reviewId>")
def get_consistency_review(ouId, reviewId):
    uid, role = auth()
    require_role(role, LEGAL_READERS)
    ou, r = resolve_consistency(ouId, reviewId)
    return ok_object(public(r))


@bp.post("/hr-org-units/<ouId>/consistency-reviews/<reviewId>/adjudicate")
def adjudicate_consistency_review(ouId, reviewId):
    uid, role = auth()
    require_role(role, ["HRDirector"])
    ou, r = resolve_consistency(ouId, reviewId)
    if r["status"] != "OPEN":
        err(E_INVALID_STATE, "consistency review is not OPEN")
    if r["opened_by_hrbp_id"] == uid:
        err(E_SOD, "the adjudicating director must not be the opening HRBP")
    if r["cohort_size"] < 3:
        err(E_COHORT_TOO_SMALL, "cohort has fewer than 3 comparable closed PIPs")
    b = body()
    adjudication = enum_field(require_field(b, "adjudication"),
                              {"CONSISTENT", "INCONSISTENT"}, "adjudication")
    notes = min_len(require_field(b, "adjudication_notes"), 40,
                    "adjudication_notes")
    r["status"] = "ADJUDICATED_" + adjudication
    r["adjudicated_by_director_id"] = uid
    r["adjudication_notes"] = notes
    touch(r)
    return ok_object(public(r))
