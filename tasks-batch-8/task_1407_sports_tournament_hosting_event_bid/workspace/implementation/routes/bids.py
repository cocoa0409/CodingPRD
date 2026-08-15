"""Bid and BidRequirement endpoints (PRD §3.1)."""

from flask import Blueprint, request

import services as svc
from db import STORE, base_entity, iso, now, touch
from errors import (ApiError, ERR_BID_ALREADY_ACTIVE, ERR_BID_NOT_EDITABLE,
                    ERR_BID_REQUIREMENTS_INCOMPLETE, ERR_BID_SCORE_BELOW_THRESHOLD,
                    ERR_REQUIREMENT_NOT_REVIEWABLE, ERR_REQUIREMENT_NOT_WAIVABLE,
                    ERR_SOD_VIOLATION, ERR_STALE_VERSION, already_terminal,
                    invalid_state, posture_forbids, raise_err)
from listing import list_response
from middleware import (get_body, opt_str, req_bool, req_enum, req_int, req_str,
                        require_any_authenticated, require_roles)
from response import ok

bp = Blueprint("bids", __name__, url_prefix="/api/v1")


def _check_bid_editable(bid):
    if bid["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise_err(ERR_BID_NOT_EDITABLE,
                  "Bid is not DRAFT or REVISION_REQUESTED; checklist and notes are locked.")


# ---------------------------------------------------------------------------
# Bids
# ---------------------------------------------------------------------------

@bp.post("/events/<id>/bids")
def create_bid(id):
    require_roles("CommissionAdmin")
    e = svc.get_or_404(STORE.events, id, "event")
    data = get_body()
    expected = req_int(data, "expected_event_version")
    notes = opt_str(data, "notes")
    if expected != e["version"]:
        raise_err(ERR_STALE_VERSION, "expected_event_version does not match the event's current version.")
    if e["posture"] not in ("BIDDING", "BID_LOST", "SETTLED"):
        posture_forbids("Bids may be created only while the event is BIDDING, BID_LOST, or SETTLED.")
    existing = svc.bids_of_event(e["id"])
    for b in existing:
        if b["status"] in ("SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED"):
            raise_err(ERR_BID_ALREADY_ACTIVE,
                      "The event already has a non-terminal bid in review; only a DRAFT bid is superseded.")
    for b in existing:
        if b["status"] == "DRAFT":
            b["status"] = "SUPERSEDED"
            touch(b)
    cycle = max([b["cycle_number"] for b in existing], default=0) + 1
    bid = base_entity()
    bid.update({
        "event_id": e["id"],
        "cycle_number": cycle,
        "status": "DRAFT",
        "notes": notes,
        "revision_count": 0,
        "submitted_at": None,
        "decided_at": None,
        "decided_by_user_id": None,
    })
    STORE.bids[bid["id"]] = bid
    # Renewal revival + active pointer; a single Event.version increment covers
    # both the creation and any posture revival.
    if e["posture"] in ("BID_LOST", "SETTLED"):
        e["posture"] = "BIDDING"
    e["active_bid_id"] = bid["id"]
    touch(e)
    return ok(svc.ser_bid(bid), status=201)


@bp.get("/events/<id>/bids")
def list_bids(id):
    require_any_authenticated()
    e = svc.get_or_404(STORE.events, id, "event")
    items = svc.bids_of_event(e["id"])
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items.sort(key=lambda b: (b["cycle_number"], b["_seq"]), reverse=True)
    return list_response(items, svc.ser_bid)


@bp.get("/bids/<id>")
def get_bid(id):
    require_any_authenticated()
    b = svc.get_or_404(STORE.bids, id, "bid")
    return ok(svc.ser_bid(b))


@bp.patch("/bids/<id>")
def patch_bid(id):
    require_roles("CommissionAdmin")
    b = svc.get_or_404(STORE.bids, id, "bid")
    data = get_body()
    expected = req_int(data, "expected_bid_version")
    notes = opt_str(data, "notes")
    if expected != b["version"]:
        raise_err(ERR_STALE_VERSION, "expected_bid_version does not match the bid's current version.")
    _check_bid_editable(b)
    if "notes" in data:
        b["notes"] = notes
    touch(b)
    return ok(svc.ser_bid(b))


@bp.post("/bids/<id>/submit")
def submit_bid(id):
    require_roles("CommissionAdmin")
    b = svc.get_or_404(STORE.bids, id, "bid")
    e = svc.get_or_404(STORE.events, b["event_id"], "event")
    if e["posture"] != "BIDDING":
        posture_forbids("Bid submission requires the event to be in BIDDING posture.")
    if b["status"] in svc.BID_TERMINAL:
        already_terminal("bid")
    if b["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        invalid_state("Only a DRAFT or REVISION_REQUESTED bid can be submitted.")
    reqs = svc.reqs_of_bid(b["id"])
    if any(r["is_mandatory"] and r["status"] != "VERIFIED" for r in reqs):
        raise_err(ERR_BID_REQUIREMENTS_INCOMPLETE,
                  "Every mandatory requirement must be VERIFIED before submission.")
    if any(r["status"] not in ("VERIFIED", "WAIVED") for r in reqs):
        raise_err(ERR_BID_REQUIREMENTS_INCOMPLETE,
                  "Every requirement must be VERIFIED or WAIVED before submission.")
    if b["status"] == "REVISION_REQUESTED":
        b["revision_count"] += 1
    b["status"] = "SUBMITTED"
    b["submitted_at"] = iso(now())
    touch(b)
    return ok(svc.ser_bid(b))


@bp.post("/bids/<id>/withdraw")
def withdraw_bid(id):
    require_roles("CommissionAdmin")
    b = svc.get_or_404(STORE.bids, id, "bid")
    if b["status"] in svc.BID_TERMINAL:
        already_terminal("bid")
    if b["status"] not in ("DRAFT", "SUBMITTED", "REVISION_REQUESTED"):
        invalid_state("A bid under review cannot be withdrawn.")
    b["status"] = "WITHDRAWN"
    touch(b)
    e = STORE.events.get(b["event_id"])
    if e is not None:
        e["active_bid_id"] = None  # per machine: cleared (no Event.version bump listed)
    return ok(svc.ser_bid(b))


@bp.post("/bids/<id>/review")
def review_bid(id):
    require_roles("SanctioningReviewer")
    b = svc.get_or_404(STORE.bids, id, "bid")
    if b["status"] in svc.BID_TERMINAL:
        already_terminal("bid")
    if b["status"] != "SUBMITTED":
        invalid_state("Only a SUBMITTED bid can move to UNDER_REVIEW.")
    b["status"] = "UNDER_REVIEW"
    touch(b)
    return ok(svc.ser_bid(b))


@bp.post("/bids/<id>/request-revision")
def request_revision(id):
    require_roles("SanctioningReviewer")
    b = svc.get_or_404(STORE.bids, id, "bid")
    data = get_body()
    req_str(data, "revision_notes")
    if b["status"] in svc.BID_TERMINAL:
        already_terminal("bid")
    if b["status"] != "UNDER_REVIEW":
        invalid_state("Only an UNDER_REVIEW bid can be sent back for revision.")
    b["status"] = "REVISION_REQUESTED"
    touch(b)
    return ok(svc.ser_bid(b))


@bp.post("/bids/<id>/decide")
def decide_bid(id):
    uid, _role = require_roles("SanctioningReviewer")
    b = svc.get_or_404(STORE.bids, id, "bid")
    data = get_body()
    decision = req_enum(data, "decision", {"AWARDED", "REJECTED"})
    if b["status"] in svc.BID_TERMINAL:
        already_terminal("bid")
    if b["status"] != "UNDER_REVIEW":
        invalid_state("Only an UNDER_REVIEW bid can be decided.")
    e = svc.get_or_404(STORE.events, b["event_id"], "event")
    if decision == "AWARDED":
        if svc.bid_review_score(b) < svc.AWARD_MIN_SCORE:
            raise_err(ERR_BID_SCORE_BELOW_THRESHOLD,
                      "Award requires a review_score of at least 80.")
        b["status"] = "AWARDED"
        b["decided_at"] = iso(now())
        b["decided_by_user_id"] = uid
        touch(b)
        # Cascade: event BIDDING -> AWARDED; other non-terminal bids superseded.
        if e["posture"] == "BIDDING":
            e["posture"] = "AWARDED"
        for other in svc.bids_of_event(e["id"]):
            if other["id"] != b["id"] and other["status"] in svc.BID_NONTERMINAL:
                other["status"] = "SUPERSEDED"
                touch(other)
        touch(e)
    else:
        b["status"] = "REJECTED"
        b["decided_at"] = iso(now())
        b["decided_by_user_id"] = uid
        touch(b)
        if e["posture"] == "BIDDING":
            e["posture"] = "BID_LOST"
        touch(e)
    return ok(svc.ser_bid(b))


# ---------------------------------------------------------------------------
# Bid requirements (checklist)
# ---------------------------------------------------------------------------

@bp.post("/bids/<id>/requirements")
def create_requirement(id):
    require_roles("CommissionAdmin")
    b = svc.get_or_404(STORE.bids, id, "bid")
    data = get_body()
    kind = req_enum(data, "kind", svc.REQUIREMENT_KINDS)
    is_mandatory = req_bool(data, "is_mandatory")
    weight_points = req_int(data, "weight_points", lo=1, hi=100)
    notes = opt_str(data, "notes")
    _check_bid_editable(b)
    r = base_entity()
    r.update({
        "bid_id": b["id"],
        "kind": kind,
        "is_mandatory": is_mandatory,
        "weight_points": weight_points,
        "notes": notes,
        "status": "PENDING",
        "evidence_uri": None,
        "evidence_submitted_by_user_id": None,
        "verified_by_user_id": None,
        "review_notes": None,
    })
    STORE.requirements[r["id"]] = r
    return ok(svc.ser_requirement(r), status=201)


@bp.get("/bids/<id>/requirements")
def list_requirements(id):
    require_any_authenticated()
    b = svc.get_or_404(STORE.bids, id, "bid")
    items = svc.reqs_of_bid(b["id"])
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return list_response(items, svc.ser_requirement)


@bp.get("/requirements/<id>")
def get_requirement(id):
    require_any_authenticated()
    r = svc.get_or_404(STORE.requirements, id, "requirement")
    return ok(svc.ser_requirement(r))


@bp.post("/requirements/<id>/evidence")
def submit_evidence(id):
    uid, _role = require_roles("CommissionAdmin")
    r = svc.get_or_404(STORE.requirements, id, "requirement")
    data = get_body()
    evidence_uri = req_str(data, "evidence_uri")
    opt_str(data, "notes")
    b = svc.get_or_404(STORE.bids, r["bid_id"], "bid")
    _check_bid_editable(b)
    if r["status"] in svc.REQ_TERMINAL:
        already_terminal("requirement")
    if r["status"] not in ("PENDING", "RETURNED"):
        invalid_state("Evidence may be submitted only on a PENDING or RETURNED requirement.")
    r["status"] = "EVIDENCE_SUBMITTED"
    r["evidence_uri"] = evidence_uri
    r["evidence_submitted_by_user_id"] = uid
    touch(r)
    return ok(svc.ser_requirement(r))


@bp.post("/requirements/<id>/verify")
def verify_requirement(id):
    uid, _role = require_roles("SanctioningReviewer")
    r = svc.get_or_404(STORE.requirements, id, "requirement")
    data = get_body()
    decision = req_enum(data, "decision", {"VERIFIED", "RETURNED"})
    review_notes = opt_str(data, "review_notes")
    if r["status"] in svc.REQ_TERMINAL:
        already_terminal("requirement")
    if r["status"] != "EVIDENCE_SUBMITTED":
        raise_err(ERR_REQUIREMENT_NOT_REVIEWABLE,
                  "Only an EVIDENCE_SUBMITTED requirement can be verified or returned.")
    if uid == r["evidence_submitted_by_user_id"]:
        raise_err(ERR_SOD_VIOLATION,
                  "A reviewer may not adjudicate evidence they submitted themselves.")
    if review_notes is not None:
        r["review_notes"] = review_notes
    if decision == "VERIFIED":
        r["status"] = "VERIFIED"
        r["verified_by_user_id"] = uid
    else:
        r["status"] = "RETURNED"
    touch(r)
    return ok(svc.ser_requirement(r))


@bp.post("/requirements/<id>/waive")
def waive_requirement(id):
    uid, _role = require_roles("SanctioningReviewer")
    r = svc.get_or_404(STORE.requirements, id, "requirement")
    data = get_body()
    waiver_reason = req_str(data, "waiver_reason")
    b = svc.get_or_404(STORE.bids, r["bid_id"], "bid")
    _check_bid_editable(b)
    if r["status"] in svc.REQ_TERMINAL:
        already_terminal("requirement")
    if r["status"] != "PENDING":
        raise_err(ERR_REQUIREMENT_NOT_REVIEWABLE,
                  "Only a PENDING requirement can be waived.")
    if r["is_mandatory"]:
        raise_err(ERR_REQUIREMENT_NOT_WAIVABLE,
                  "Mandatory requirements can never be waived.")
    r["status"] = "WAIVED"
    r["review_notes"] = waiver_reason
    touch(r)
    return ok(svc.ser_requirement(r))
