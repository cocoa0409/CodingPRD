"""Engagement lifecycle endpoints."""
from flask import Blueprint, g

import db
from lib import (
    ApiError,
    body_dict,
    forbidden,
    get_or_404,
    invalid_state,
    list_ok,
    ok,
    opt_int,
    optional_body,
    pagination_params,
    req_int,
    req_str,
    require_role,
)
from services import (
    NONTERMINAL_ENG_STATUSES,
    active_engagement_count,
    engagement_view,
    recompute_case,
    terminate_engagement,
)

bp = Blueprint("engagements", __name__)

READ_ROLES = ("PlatformAdmin", "CaseManager", "BillingReviewer", "Expert")


def _expert_owns(eng):
    if g.user_role == "Expert" and eng["expert_id"] != g.user_id:
        forbidden("experts may access only their own engagements")


@bp.post("/litigation/engagements")
def create_engagement():
    b = body_dict()
    request_id = req_str(b, "engagement_request_id")
    expert_id = req_str(b, "expert_id")
    rate = req_int(b, "hourly_rate_cents", minimum=1)
    retainer = req_int(b, "retainer_cents", minimum=0)
    cap = req_int(b, "expense_cap_cents", minimum=0)
    require_role("CaseManager")
    req = get_or_404(db.engagement_requests, request_id, "engagement request")
    expert = get_or_404(db.experts, expert_id, "expert")
    # Seven business-safety gates, pinned order (PRD 3.3).
    cc = next(
        (
            c
            for c in db.conflict_checks.values()
            if c["engagement_request_id"] == request_id and c["expert_id"] == expert_id
        ),
        None,
    )
    if cc is None or cc["status"] not in ("CLEARED", "WAIVED"):
        raise ApiError(
            "ERR_CONFLICT_NOT_CLEARED",
            409,
            "conflict check for this expert is not CLEARED or WAIVED",
        )
    cr = next(
        (
            r
            for r in db.credential_reviews.values()
            if r["engagement_request_id"] == request_id and r["expert_id"] == expert_id
        ),
        None,
    )
    if cr is None or cr["status"] not in ("PASSED", "PASSED_WITH_CONDITIONS"):
        raise ApiError(
            "ERR_CREDENTIAL_NOT_PASSED",
            409,
            "credential review for this expert has not passed",
        )
    if expert["roster_status"] != "ACTIVE":
        raise ApiError(
            "ERR_EXPERT_ROSTER_INELIGIBLE",
            422,
            "expert roster status is not ACTIVE",
        )
    if expert["daubert_exclusion_count"] >= 3:
        raise ApiError(
            "ERR_EXPERT_DAUBERT_BARRED",
            422,
            "expert has three or more Daubert exclusions",
        )
    if req["status"] != "READY":
        invalid_state("engagement request is not READY")
    case_id = req["case_id"]
    if any(
        e["case_id"] == case_id
        and e["expert_id"] == expert_id
        and e["status"] in NONTERMINAL_ENG_STATUSES
        for e in db.engagements.values()
    ):
        raise ApiError(
            "ERR_DUPLICATE_CASE_ENGAGEMENT",
            409,
            "a non-terminal engagement already exists for this (case, expert)",
        )
    if active_engagement_count(expert_id) >= expert["max_concurrent_engagements"]:
        raise ApiError(
            "ERR_EXPERT_CAPACITY_FULL",
            422,
            "expert is at max_concurrent_engagements",
        )
    rec = db.base_record()
    rec.update(
        engagement_request_id=request_id,
        case_id=case_id,
        expert_id=expert_id,
        status="DRAFT",
        hourly_rate_cents=rate,
        retainer_cents=retainer,
        expense_cap_cents=cap,
        negotiation_round_count=0,
        nda_executed=False,
        retainer_funded_cents=0,
        retainer_drawn_cents=0,
        retainer_refunded_cents=0,
        expenses_approved_cents=0,
        created_by_user_id=g.user_id,
    )
    db.engagements[rec["id"]] = rec
    req["status"] = "FILLED"
    db.touch(req)
    return ok(engagement_view(rec), 201)


@bp.get("/litigation/engagements")
def list_engagements():
    limit, offset = pagination_params()
    require_role(*READ_ROLES)
    from flask import request as _req

    recs = list(db.engagements.values())
    if g.user_role == "Expert":
        recs = [e for e in recs if e["expert_id"] == g.user_id]
    for f in ("case_id", "expert_id", "engagement_request_id", "status"):
        v = _req.args.get(f)
        if v is not None:
            recs = [e for e in recs if e[f] == v]
    return list_ok([engagement_view(e) for e in recs], limit, offset)


@bp.get("/litigation/engagements/<eid>")
def get_engagement(eid):
    require_role(*READ_ROLES)
    eng = get_or_404(db.engagements, eid, "engagement")
    _expert_owns(eng)
    return ok(engagement_view(eng))


@bp.post("/litigation/engagements/<eid>/propose")
def propose(eid):
    b = optional_body()
    require_role("CaseManager")
    eng = get_or_404(db.engagements, eid, "engagement")
    if eng["status"] not in ("DRAFT", "NEGOTIATING"):
        invalid_state("only a DRAFT or NEGOTIATING engagement can be proposed")
    if eng["status"] == "NEGOTIATING" and "hourly_rate_cents" in b:
        # counter-offer acceptance loop: optional revised rate replaces the offer
        eng["hourly_rate_cents"] = req_int(b, "hourly_rate_cents", minimum=1)
    eng["status"] = "PROPOSED"
    db.touch(eng)
    return ok(engagement_view(eng))


@bp.post("/litigation/engagements/<eid>/counter")
def counter(eid):
    b = body_dict()
    req_int(b, "counter_rate_cents", minimum=1)
    require_role("Expert")
    eng = get_or_404(db.engagements, eid, "engagement")
    if eng["expert_id"] != g.user_id:
        forbidden("only the engaged expert may counter")
    if eng["status"] != "PROPOSED":
        invalid_state("only a PROPOSED engagement can be countered")
    eng["status"] = "NEGOTIATING"
    eng["negotiation_round_count"] += 1
    db.touch(eng)
    return ok(engagement_view(eng))


@bp.post("/litigation/engagements/<eid>/sign")
def sign(eid):
    require_role("Expert")
    eng = get_or_404(db.engagements, eid, "engagement")
    if eng["expert_id"] != g.user_id:
        forbidden("only the engaged expert may sign")
    if eng["status"] != "PROPOSED":
        invalid_state("only a PROPOSED engagement can be signed")
    eng["status"] = "SIGNED"
    eng["nda_executed"] = True
    db.touch(eng)
    case = db.cases.get(eng["case_id"])
    if case is not None and case["status"] == "SOURCING":
        case["status"] = "ENGAGED"
        db.touch(case)
    return ok(engagement_view(eng))


@bp.post("/litigation/engagements/<eid>/fund-retainer")
def fund_retainer(eid):
    b = body_dict()
    amount = req_int(b, "amount_cents", minimum=0)
    require_role("CaseManager")
    eng = get_or_404(db.engagements, eid, "engagement")
    if eng["status"] != "SIGNED":
        invalid_state("only a SIGNED engagement can be funded")
    if eng["retainer_funded_cents"] + amount > eng["retainer_cents"]:
        raise ApiError(
            "ERR_RETAINER_OVERFUND",
            422,
            "funding would exceed retainer_cents",
        )
    eng["retainer_funded_cents"] += amount
    if eng["retainer_funded_cents"] == eng["retainer_cents"]:
        eng["status"] = "ACTIVE"  # SIGNED and ACTIVE both count; active count unchanged
    db.touch(eng)
    recompute_case(eng["case_id"])
    return ok(engagement_view(eng))


@bp.post("/litigation/engagements/<eid>/amend")
def amend(eid):
    b = body_dict()
    expected = req_int(b, "expected_engagement_version")
    req_str(b, "reason")
    rate = opt_int(b, "hourly_rate_cents", None, minimum=1)
    retainer = opt_int(b, "retainer_cents", None, minimum=0)
    cap = opt_int(b, "expense_cap_cents", None, minimum=0)
    require_role("CaseManager")
    eng = get_or_404(db.engagements, eid, "engagement")
    if eng["status"] in ("CLOSED", "TERMINATED"):
        invalid_state("terms of a terminal engagement cannot be amended")
    if expected != eng["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            412,
            "expected_engagement_version does not match the engagement's current version",
        )
    if rate is not None:
        eng["hourly_rate_cents"] = rate
    if retainer is not None:
        eng["retainer_cents"] = retainer
    if cap is not None:
        eng["expense_cap_cents"] = cap
    db.touch(eng)
    recompute_case(eng["case_id"])
    return ok(engagement_view(eng))


@bp.post("/litigation/engagements/<eid>/terminate")
def terminate(eid):
    b = body_dict()
    req_str(b, "reason")
    require_role("CaseManager")
    eng = get_or_404(db.engagements, eid, "engagement")
    if eng["status"] not in ("SIGNED", "ACTIVE"):
        invalid_state("only a SIGNED or ACTIVE engagement can be terminated")
    terminate_engagement(eng)
    return ok(engagement_view(eng))


@bp.post("/litigation/engagements/<eid>/close")
def close_engagement(eid):
    require_role("CaseManager")
    eng = get_or_404(db.engagements, eid, "engagement")
    if eng["status"] != "ACTIVE":
        invalid_state("only an ACTIVE engagement can be closed")
    blocking_reports = any(
        r["engagement_id"] == eid
        and r["status"] in ("DRAFT", "IN_REVIEW", "REVISION_REQUESTED", "FINALIZED")
        for r in db.reports.values()
    )
    blocking_schedules = any(
        s["engagement_id"] == eid and s["status"] in ("PROPOSED", "CONFIRMED")
        for s in db.schedules.values()
    )
    blocking_invoices = any(
        i["engagement_id"] == eid and i["status"] not in ("PAID", "REJECTED")
        for i in db.invoices.values()
    )
    if blocking_reports or blocking_schedules or blocking_invoices:
        raise ApiError(
            "ERR_ENGAGEMENT_NOT_CLOSABLE",
            409,
            "non-terminal reports, schedules, or invoices block closing",
        )
    eng["status"] = "CLOSED"
    db.touch(eng)
    recompute_case(eng["case_id"])
    return ok(engagement_view(eng))
