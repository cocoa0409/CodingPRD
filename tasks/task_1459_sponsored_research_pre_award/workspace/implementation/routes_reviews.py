"""Routes: compliance reviews, subrecipient commitments, negotiation offers,
award handoffs."""

from datetime import timedelta

from flask import Blueprint

from db import store, mint, touch
from errors import (ApiError, bad_request, not_found, ERR_NOT_OWNER,
                    ERR_PROPOSAL_STATE, ERR_REVIEW_STATE, ERR_OFFER_STATE,
                    ERR_HANDOFF_STATE, ERR_COMMITMENT_STATE,
                    ERR_DUPLICATE_REVIEW, ERR_COI_INCOMPLETE,
                    ERR_COMPLIANCE_DISAPPROVED, ERR_COMPLIANCE_EXPIRED,
                    ERR_COMPLIANCE_PENDING, ERR_STALE_SNAPSHOT,
                    ERR_RATE_NOT_FINAL, ERR_SUBREC_NOT_VERIFIED,
                    ERR_SUBREC_DOCS, ERR_SUBREC_HIGH_RISK,
                    ERR_COST_SHARE_INADEQUATE, ERR_STALE_VERSION)
from middleware import authenticate, require_roles
from response import ok_object, ok_list, parse_pagination
from serializers import (proposal_out, review_out, sub_commitment_out,
                         offer_out, handoff_out)
from services import (ACTIVITY_TO_RATE_TYPE, REVIEW_VALIDITY_DEFAULTS,
                      ENHANCED_AMOUNT_THRESHOLD_CENTS, ENHANCED_SURCHARGE,
                      reviews_of_proposal, subs_of_proposal,
                      offers_of_proposal, handoff_of_proposal,
                      recompute_posture, return_for_revision_effects,
                      bubble_handoff_blocked, risk_score_standard,
                      risk_tier_of, select_rate_agreement, applied_rate,
                      compute_indirect, compute_cost_share)
from utils import (json_body, req_field, opt_field, as_str, as_int, as_bool,
                   as_enum, as_number, fmt_dt)

bp = Blueprint("reviews", __name__)

REVIEW_TYPES = ["IRB", "IACUC", "EXPORT_CONTROL", "CONFLICT_OF_INTEREST"]
OFFER_ORIGINS = ["SPONSOR", "INSTITUTION"]

ACTIVE_REVIEW_STATES = ("PENDING", "INFO_REQUESTED", "APPROVED")
RETURNABLE_PROPOSAL_STATES = {"ROUTED", "INSTITUTIONALLY_APPROVED",
                              "SUBMITTED", "JIT_REQUESTED", "NEGOTIATING"}


def _get_proposal_or_404(pid):
    p = store.proposals.get(pid)
    if p is None:
        raise not_found("Proposal not found")
    return p


def _get_review_or_404(rid):
    r = store.compliance_reviews.get(rid)
    if r is None:
        raise not_found("Compliance review not found")
    return r


def _get_sub_or_404(sid):
    s = store.subrecipient_commitments.get(sid)
    if s is None:
        raise not_found("Subrecipient commitment not found")
    return s


def _paginate(items, serializer):
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    page = ordered[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, len(ordered))


# ---------------------------------------------------------------------------
# Compliance reviews
# ---------------------------------------------------------------------------

@bp.post("/pre-award/proposals/<pid>/compliance-reviews")
def create_review(pid):
    require_roles(["ComplianceOfficer"])
    p = _get_proposal_or_404(pid)
    body = json_body()
    review_type = as_enum(req_field(body, "review_type"), "review_type",
                          REVIEW_TYPES)
    disclosure = as_bool(opt_field(body, "disclosure_complete", False),
                         "disclosure_complete")
    for other in reviews_of_proposal(pid):
        if other["review_type"] == review_type and \
                other["status"] in ACTIVE_REVIEW_STATES:
            raise ApiError(ERR_DUPLICATE_REVIEW, 409,
                           "An active review of this type already exists for "
                           "the proposal")
    rec = mint({
        "proposal_id": pid,
        "review_type": review_type,
        "disclosure_complete": disclosure,
        "approved_until_at": None,
        "validity_days": None,
        "status": "PENDING",
        "_approved_until_dt": None,
    })
    store.compliance_reviews[rec["id"]] = rec
    recompute_posture(p)
    return ok_object(review_out(rec), 201)


@bp.get("/pre-award/proposals/<pid>/compliance-reviews")
def list_reviews(pid):
    authenticate()
    _get_proposal_or_404(pid)
    return _paginate(reviews_of_proposal(pid), review_out)


@bp.post("/pre-award/compliance-reviews/<rid>/request-info")
def request_info(rid):
    require_roles(["ComplianceOfficer"])
    r = _get_review_or_404(rid)
    body = json_body()
    as_str(req_field(body, "question"), "question")
    if r["status"] != "PENDING":
        raise ApiError(ERR_REVIEW_STATE, 409,
                       "Only a PENDING review can be moved to INFO_REQUESTED")
    r["status"] = "INFO_REQUESTED"
    touch(r)
    p = store.proposals.get(r["proposal_id"])
    if p is not None:
        recompute_posture(p)
    return ok_object(review_out(r), 200)


@bp.post("/pre-award/compliance-reviews/<rid>/respond")
def respond_review(rid):
    user_id, _ = require_roles(["PI"])
    r = _get_review_or_404(rid)
    p = store.proposals.get(r["proposal_id"])
    if p is None:
        raise not_found("Proposal not found")
    if p["pi_id"] != user_id:
        raise ApiError(ERR_NOT_OWNER, 403,
                       "Only the owning PI may respond to this review")
    if r["status"] not in ("INFO_REQUESTED", "EXPIRED"):
        raise ApiError(ERR_REVIEW_STATE, 409,
                       "Only an INFO_REQUESTED or EXPIRED review can be "
                       "responded to")
    body = json_body()
    if "disclosure_complete" in body and body["disclosure_complete"] is not None:
        r["disclosure_complete"] = as_bool(body["disclosure_complete"],
                                           "disclosure_complete")
    if "response_note" in body and body["response_note"] is not None:
        as_str(body["response_note"], "response_note")
    if r["status"] == "EXPIRED":
        r["approved_until_at"] = None
        r["validity_days"] = None
        r["_approved_until_dt"] = None
    r["status"] = "PENDING"
    touch(r)
    recompute_posture(p)
    return ok_object(review_out(r), 200)


@bp.post("/pre-award/compliance-reviews/<rid>/approve")
def approve_review(rid):
    require_roles(["ComplianceOfficer"])
    r = _get_review_or_404(rid)
    if r["status"] != "PENDING":
        raise ApiError(ERR_REVIEW_STATE, 409,
                       "Only a PENDING review can be approved")
    if r["review_type"] == "CONFLICT_OF_INTEREST" and \
            not r["disclosure_complete"]:
        raise ApiError(ERR_COI_INCOMPLETE, 422,
                       "A conflict-of-interest review requires a complete "
                       "disclosure before approval")
    body = json_body()
    override = opt_field(body, "validity_days", None)
    if override is not None:
        override = as_int(override, "validity_days")
        if override < 0:
            raise bad_request("Field 'validity_days' must be >= 0")
        validity = override
    else:
        validity = REVIEW_VALIDITY_DEFAULTS[r["review_type"]]
    until = store.clock + timedelta(days=validity)
    r["validity_days"] = validity
    r["approved_until_at"] = fmt_dt(until)
    r["_approved_until_dt"] = until
    r["status"] = "APPROVED"
    touch(r)
    p = store.proposals.get(r["proposal_id"])
    if p is not None:
        recompute_posture(p)
    return ok_object(review_out(r), 200)


@bp.post("/pre-award/compliance-reviews/<rid>/disapprove")
def disapprove_review(rid):
    require_roles(["ComplianceOfficer"])
    r = _get_review_or_404(rid)
    body = json_body()
    as_str(req_field(body, "reason"), "reason")
    if r["status"] not in ("PENDING", "INFO_REQUESTED"):
        raise ApiError(ERR_REVIEW_STATE, 409,
                       "Only a PENDING or INFO_REQUESTED review can be "
                       "disapproved")
    r["status"] = "DISAPPROVED"
    touch(r)
    p = store.proposals.get(r["proposal_id"])
    if p is not None:
        recompute_posture(p)
        if p["status"] in RETURNABLE_PROPOSAL_STATES:
            p["status"] = "RETURNED_FOR_REVISION"
            p["revision_count"] += 1
            return_for_revision_effects(p)
        bubble_handoff_blocked(p)
        touch(p)
    return ok_object(review_out(r), 200)


# ---------------------------------------------------------------------------
# Subrecipient commitments
# ---------------------------------------------------------------------------

@bp.post("/pre-award/proposals/<pid>/subrecipient-commitments")
def create_sub_commitment(pid):
    require_roles(["PreAwardAnalyst"])
    _get_proposal_or_404(pid)
    body = json_body()
    org_id = as_str(req_field(body, "subrecipient_org_id"),
                    "subrecipient_org_id")
    amount = as_int(req_field(body, "subaward_amount_cents"),
                    "subaward_amount_cents")
    if amount <= 0:
        raise bad_request("Field 'subaward_amount_cents' must be > 0")
    sow = as_bool(opt_field(body, "statement_of_work_received", False),
                  "statement_of_work_received")
    budget = as_bool(opt_field(body, "budget_received", False),
                     "budget_received")
    ack = as_bool(opt_field(body, "enhanced_monitoring_acknowledged", False),
                  "enhanced_monitoring_acknowledged")
    if org_id not in store.subrecipient_orgs:
        raise not_found("Subrecipient organization not found")
    rec = mint({
        "proposal_id": pid,
        "subrecipient_org_id": org_id,
        "subaward_amount_cents": amount,
        "statement_of_work_received": sow,
        "budget_received": budget,
        "enhanced_monitoring_acknowledged": ack,
        "verified_risk_snapshot_score": None,
        "monitoring_level": None,
        "status": "DRAFT",
    })
    store.subrecipient_commitments[rec["id"]] = rec
    return ok_object(sub_commitment_out(rec), 201)


@bp.get("/pre-award/proposals/<pid>/subrecipient-commitments")
def list_sub_commitments(pid):
    authenticate()
    _get_proposal_or_404(pid)
    return _paginate(subs_of_proposal(pid), sub_commitment_out)


@bp.post("/pre-award/subrecipient-commitments/<sid>/verify")
def verify_sub_commitment(sid):
    require_roles(["SubrecipientManager"])
    s = _get_sub_or_404(sid)
    if s["status"] not in ("DRAFT", "STALE"):
        raise ApiError(ERR_COMMITMENT_STATE, 409,
                       "Only a DRAFT or STALE commitment can be verified")
    if not s["statement_of_work_received"] or not s["budget_received"]:
        raise ApiError(ERR_SUBREC_DOCS, 422,
                       "Both the statement of work and the budget must be "
                       "received before verification")
    org = store.subrecipient_orgs.get(s["subrecipient_org_id"])
    if org is None:
        raise not_found("Subrecipient organization not found")
    if org["risk_tier"] == "HIGH" and not s["enhanced_monitoring_acknowledged"]:
        raise ApiError(ERR_SUBREC_HIGH_RISK, 422,
                       "Verification of a HIGH-risk organization requires "
                       "enhanced monitoring acknowledgement")
    score = risk_score_standard(org)
    if s["subaward_amount_cents"] >= ENHANCED_AMOUNT_THRESHOLD_CENTS:
        score += ENHANCED_SURCHARGE
    tier = risk_tier_of(score)
    s["verified_risk_snapshot_score"] = score
    s["monitoring_level"] = "ENHANCED" if tier == "HIGH" else "STANDARD"
    s["status"] = "VERIFIED"
    touch(s)
    return ok_object(sub_commitment_out(s), 200)


@bp.post("/pre-award/subrecipient-commitments/<sid>/void")
def void_sub_commitment(sid):
    require_roles(["SubrecipientManager"])
    s = _get_sub_or_404(sid)
    if s["status"] not in ("DRAFT", "VERIFIED", "STALE"):
        raise ApiError(ERR_COMMITMENT_STATE, 409,
                       "Only a DRAFT, VERIFIED, or STALE commitment can be "
                       "voided")
    s["status"] = "VOIDED"
    touch(s)
    return ok_object(sub_commitment_out(s), 200)


# ---------------------------------------------------------------------------
# Negotiation offers
# ---------------------------------------------------------------------------

@bp.post("/pre-award/proposals/<pid>/negotiation-offers")
def create_offer(pid):
    require_roles(["OSPDirector"])
    p = _get_proposal_or_404(pid)
    body = json_body()
    expected = as_int(req_field(body, "expected_proposal_version"),
                      "expected_proposal_version")
    origin = as_enum(req_field(body, "origin"), "origin", OFFER_ORIGINS)
    offered_total = as_int(req_field(body, "offered_total_cents"),
                           "offered_total_cents")
    if offered_total <= 0:
        raise bad_request("Field 'offered_total_cents' must be > 0")
    offered_rate = opt_field(body, "offered_fa_rate_pct", None)
    if offered_rate is not None:
        offered_rate = as_number(offered_rate, "offered_fa_rate_pct")
    note = opt_field(body, "note", None)
    if note is not None:
        note = as_str(note, "note")
    if expected != p["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_proposal_version does not match the "
                       "proposal's current version")
    if p["status"] not in ("SUBMITTED", "JIT_REQUESTED", "NEGOTIATING"):
        raise ApiError(ERR_PROPOSAL_STATE, 409,
                       "Negotiation rounds may only open from SUBMITTED, "
                       "JIT_REQUESTED, or NEGOTIATING")
    for other in offers_of_proposal(pid):
        if other["status"] == "PROPOSED":
            other["status"] = "VOIDED"
            touch(other)
    rec = mint({
        "proposal_id": pid,
        "round_index": len(offers_of_proposal(pid)) + 1,
        "origin": origin,
        "offered_total_cents": offered_total,
        "offered_fa_rate_pct": offered_rate,
        "note": note,
        "status": "PROPOSED",
    })
    store.negotiation_offers[rec["id"]] = rec
    if p["status"] != "NEGOTIATING":
        p["status"] = "NEGOTIATING"
    touch(p)
    return ok_object(offer_out(rec), 201)


@bp.get("/pre-award/proposals/<pid>/negotiation-offers")
def list_offers(pid):
    authenticate()
    _get_proposal_or_404(pid)
    return _paginate(offers_of_proposal(pid), offer_out)


def _get_offer_or_404(oid):
    o = store.negotiation_offers.get(oid)
    if o is None:
        raise not_found("Negotiation offer not found")
    return o


@bp.post("/pre-award/negotiation-offers/<oid>/accept")
def accept_offer(oid):
    require_roles(["OSPDirector"])
    o = _get_offer_or_404(oid)
    if o["status"] != "PROPOSED":
        raise ApiError(ERR_OFFER_STATE, 409,
                       "Only a PROPOSED offer can be accepted")
    p = store.proposals.get(o["proposal_id"])
    if p is None or p["status"] != "NEGOTIATING":
        raise ApiError(ERR_PROPOSAL_STATE, 409,
                       "The offer's proposal is not NEGOTIATING")
    o["status"] = "ACCEPTED"
    touch(o)
    p["status"] = "AWARDED"
    p["awarded_total_cents"] = o["offered_total_cents"]
    touch(p)
    handoff = mint({
        "proposal_id": p["id"],
        "budget_verified": False,
        "compliance_verified": False,
        "subrecipient_verified": False,
        "final_indirect_cents": None,
        "final_total_cents": None,
        "handoff_at": None,
        "status": "DRAFT",
    })
    store.award_handoffs[handoff["id"]] = handoff
    return ok_object(offer_out(o), 200)


@bp.post("/pre-award/negotiation-offers/<oid>/decline")
def decline_offer(oid):
    require_roles(["OSPDirector"])
    o = _get_offer_or_404(oid)
    if o["status"] != "PROPOSED":
        raise ApiError(ERR_OFFER_STATE, 409,
                       "Only a PROPOSED offer can be declined")
    p = store.proposals.get(o["proposal_id"])
    if p is None or p["status"] != "NEGOTIATING":
        raise ApiError(ERR_PROPOSAL_STATE, 409,
                       "The offer's proposal is not NEGOTIATING")
    o["status"] = "DECLINED"
    touch(o)
    from services import terminal_cleanup
    p["status"] = "DECLINED"
    terminal_cleanup(p)
    touch(p)
    return ok_object(offer_out(o), 200)


# ---------------------------------------------------------------------------
# Award handoff
# ---------------------------------------------------------------------------

@bp.get("/pre-award/proposals/<pid>/award-handoffs")
def list_handoffs(pid):
    authenticate()
    _get_proposal_or_404(pid)
    h = handoff_of_proposal(pid)
    items = [h] if h is not None else []
    return _paginate(items, handoff_out)


@bp.post("/pre-award/award-handoffs/<hid>/mark-ready")
def mark_ready(hid):
    require_roles(["OSPDirector"])
    h = store.award_handoffs.get(hid)
    if h is None:
        raise not_found("Award handoff not found")
    if h["status"] not in ("DRAFT", "BLOCKED"):
        raise ApiError(ERR_HANDOFF_STATE, 409,
                       "Only a DRAFT or BLOCKED handoff can be marked ready")
    p = store.proposals.get(h["proposal_id"])
    if p is None or p["status"] != "AWARDED":
        raise ApiError(ERR_PROPOSAL_STATE, 409,
                       "The handoff's proposal is not AWARDED")
    reviews = reviews_of_proposal(p["id"])
    if any(r["status"] == "DISAPPROVED" for r in reviews):
        raise ApiError(ERR_COMPLIANCE_DISAPPROVED, 409,
                       "A review of the proposal is DISAPPROVED")
    for r in reviews:
        if r["status"] == "EXPIRED":
            raise ApiError(ERR_COMPLIANCE_EXPIRED, 409,
                           "A review of the proposal is EXPIRED")
        if r["status"] == "APPROVED" and r["_approved_until_dt"] is not None \
                and r["_approved_until_dt"] < store.clock:
            raise ApiError(ERR_COMPLIANCE_EXPIRED, 409,
                           "A review approval has lapsed")
    if any(r["status"] in ("PENDING", "INFO_REQUESTED") for r in reviews):
        raise ApiError(ERR_COMPLIANCE_PENDING, 409,
                       "A review of the proposal is still pending")
    if p["pinned_budget_snapshot_id"] != p["current_snapshot_id"]:
        raise ApiError(ERR_STALE_SNAPSHOT, 409,
                       "The pinned budget snapshot is no longer current")
    opp = store.funding_opportunities[p["opportunity_id"]]
    rate_type = ACTIVITY_TO_RATE_TYPE[p["activity_code"]]
    agreement, _ = select_rate_agreement(rate_type, p["_start"], "FINAL_BASIS")
    if agreement is None:
        raise ApiError(ERR_RATE_NOT_FINAL, 409,
                       "No FINAL rate agreement covers project_start_on")
    for s in subs_of_proposal(p["id"]):
        if s["status"] != "VOIDED" and s["status"] != "VERIFIED":
            raise ApiError(ERR_SUBREC_NOT_VERIFIED, 409,
                           "A non-voided subrecipient commitment is not "
                           "VERIFIED")
    # FINAL_BASIS recomputation over the pinned snapshot's base portions.
    snap = store.budget_snapshots.get(p["pinned_budget_snapshot_id"])
    base_portions = [(e["budget_line_id"], e["base_portion_cents"])
                     for e in snap["per_line_indirect"]] if snap else []
    applied = applied_rate(agreement["rate_pct"], opp)
    _, _, final_indirect, _ = compute_indirect(p, applied,
                                               base_portions=base_portions)
    final_total = p["total_direct_cents"] + final_indirect
    _, _, adequate, _ = compute_cost_share(p, request_total_cents=final_total)
    if not adequate:
        raise ApiError(ERR_COST_SHARE_INADEQUATE, 422,
                       "Cost share is inadequate under the final-basis totals")
    h["final_indirect_cents"] = final_indirect
    h["final_total_cents"] = final_total
    h["budget_verified"] = True
    h["compliance_verified"] = True
    h["subrecipient_verified"] = True
    h["status"] = "READY"
    touch(h)
    return ok_object(handoff_out(h), 200)


@bp.post("/pre-award/award-handoffs/<hid>/handoff")
def complete_handoff(hid):
    require_roles(["OSPDirector"])
    h = store.award_handoffs.get(hid)
    if h is None:
        raise not_found("Award handoff not found")
    if h["status"] != "READY":
        raise ApiError(ERR_HANDOFF_STATE, 409,
                       "Only a READY handoff can be completed")
    p = store.proposals.get(h["proposal_id"])
    h["status"] = "HANDED_OFF"
    h["handoff_at"] = fmt_dt(store.clock)
    touch(h)
    if p is not None:
        p["status"] = "SETUP_COMPLETE"
        touch(p)
    return ok_object(handoff_out(h), 200)
