"""Bid lifecycle, evaluation scoring, committee, award."""

import hashlib
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from flask import g

from clock import clock, parse_iso
from db import bump_version, common_fields_create, db, light_fields_create
from errors import (
    ERR_BID_ALREADY_EVALUATED,
    ERR_BID_EXCEEDS_CEILING,
    ERR_COMMITTEE_SIZE_INVALID,
    ERR_CONFLICT_OF_INTEREST,
    ERR_DEADLINE_PASSED,
    ERR_DUPLICATE_BID,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND,
    ERR_SUPPLIER_BLACKLISTED,
    ERR_TENDER_VERSION_MISMATCH,
    ERR_VALIDATION,
    raise_error,
)
from services.audit import append_audit
from services.project import get_project_or_404
from services.supplier import (
    get_supplier_or_ref_404,
    is_currently_blacklisted,
    prescreen_eligibility,
)


NON_TERMINAL_BID_STATUSES = {"SUBMITTED", "OPENED", "EVALUATED", "AWARDED"}


def get_bid_or_404(bid_id: str) -> dict:
    b = db.bids.get(bid_id)
    if not b:
        raise_error(ERR_NOT_FOUND, f"bid '{bid_id}' not found")
    return b


def get_committee_or_404(committee_id: str) -> dict:
    c = db.committees.get(committee_id)
    if not c:
        raise_error(ERR_NOT_FOUND, f"committee '{committee_id}' not found")
    return c


def get_award_or_404(award_id: str) -> dict:
    a = db.awards.get(award_id)
    if not a:
        raise_error(ERR_NOT_FOUND, f"award '{award_id}' not found")
    return a


def _round_half_up_2(x) -> float:
    """Round to two decimal places using ROUND_HALF_UP."""
    d = Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


def submit_bid(project_id: str, body: dict):
    project = get_project_or_404(project_id)
    supplier_id = body.get("supplier_id")
    if not isinstance(supplier_id, str) or not supplier_id:
        raise_error(ERR_VALIDATION, "supplier_id is required")
    # X-User-ID must match supplier_id (supplier role check)
    actor_id = getattr(g, "user_id", None)
    if actor_id != supplier_id:
        raise_error(ERR_FORBIDDEN, "supplier may only submit bids for themselves")
    supplier = get_supplier_or_ref_404(supplier_id)
    # Auth + reference + state: project must be BIDDING_OPEN
    if project["project_status"] != "BIDDING_OPEN":
        raise_error(ERR_INVALID_STATE, "project must be BIDDING_OPEN")
    # Blacklist check (priority 8)
    if is_currently_blacklisted(supplier):
        raise_error(ERR_SUPPLIER_BLACKLISTED, "supplier is blacklisted")
    # Deadline check (priority 9)
    try:
        deadline = parse_iso(project["bid_submission_deadline"])
    except Exception:
        raise_error(ERR_VALIDATION, "invalid bid_submission_deadline")
    if not (clock.now() < deadline):
        raise_error(ERR_DEADLINE_PASSED, "bid submission deadline has passed")
    # Tender version match (priority 14)
    doc_id = db.tender_by_project.get(project_id)
    if not doc_id:
        raise_error(ERR_INVALID_STATE, "no tender on project")
    doc = db.tender_documents[doc_id]
    if doc["doc_status"] != "PUBLISHED":
        raise_error(ERR_INVALID_STATE, "tender not PUBLISHED")
    tdv = body.get("tender_document_version")
    if isinstance(tdv, bool) or not isinstance(tdv, int):
        raise_error(ERR_VALIDATION, "tender_document_version must be integer")
    if tdv != doc["version"]:
        raise_error(ERR_TENDER_VERSION_MISMATCH, "tender_document_version mismatch")
    # Bid price
    bpc = body.get("bid_price_cents")
    if isinstance(bpc, bool) or not isinstance(bpc, int) or bpc <= 0:
        raise_error(ERR_VALIDATION, "bid_price_cents must be positive integer")
    if bpc > int(project["estimated_value_cents"]):
        raise_error(ERR_BID_EXCEEDS_CEILING, "bid exceeds estimated_value_cents ceiling")
    tsr = body.get("technical_score_raw", 0)
    if tsr is None:
        tsr = 0
    if isinstance(tsr, bool) or not isinstance(tsr, (int, float)):
        raise_error(ERR_VALIDATION, "technical_score_raw must be number")
    # bound by max_technical_score if present
    ec = doc.get("evaluation_criteria") or {}
    mts = ec.get("max_technical_score")
    if tsr < 0:
        raise_error(ERR_VALIDATION, "technical_score_raw must be >= 0")
    if mts is not None and tsr > float(mts):
        raise_error(ERR_VALIDATION, "technical_score_raw must be <= max_technical_score")
    # Duplicate-bid check (non-terminal bid for (project_id, supplier_id))
    for b in db.bids.values():
        if b["project_id"] == project_id and b["supplier_id"] == supplier_id and b["bid_status"] in NON_TERMINAL_BID_STATUSES:
            raise_error(ERR_DUPLICATE_BID, "duplicate non-terminal bid exists")
    bid = {
        "id": db.new_id(),
        **common_fields_create(),
        "project_id": project_id,
        "supplier_id": supplier_id,
        "tender_document_version": tdv,
        "bid_price_cents": int(bpc),
        "technical_score_raw": tsr,
        "bid_status": "SUBMITTED",
        "prescreen_passed": prescreen_eligibility(supplier, project),
        "final_score": None,
    }
    db.bids[bid["id"]] = bid
    return bid


def withdraw_bid(bid_id: str):
    bid = get_bid_or_404(bid_id)
    actor_id = getattr(g, "user_id", None)
    if actor_id != bid["supplier_id"]:
        raise_error(ERR_FORBIDDEN, "only the bid's supplier may withdraw")
    if bid["bid_status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, "bid must be SUBMITTED to withdraw")
    project = get_project_or_404(bid["project_id"])
    try:
        deadline = parse_iso(project["bid_submission_deadline"])
    except Exception:
        raise_error(ERR_VALIDATION, "invalid bid_submission_deadline")
    if not (clock.now() < deadline):
        raise_error(ERR_DEADLINE_PASSED, "bid submission deadline has passed")
    bid["bid_status"] = "WITHDRAWN"
    bump_version(bid)
    return bid


# ---------------------------------------------------------------------------
# Committee formation (deterministic selection)
# ---------------------------------------------------------------------------


def _coi_violation_form_committee(project_id: str) -> bool:
    """Same X-User-ID must not have appeared as both ProcurementOfficer and EvaluationExpert on this project's audit history."""
    actor_id = getattr(g, "user_id", None)
    actor_role = getattr(g, "user_role", None)
    if actor_id is None:
        return False
    # walk audit log entries whose target_type relates to this project
    seen_officer = seen_expert = False
    for log in db.audit_logs:
        if log.get("payload", {}).get("project_id") != project_id and log.get("target_type") not in {"EVALUATION", "AWARD", "TENDER", "COMPLAINT", "CONTRACT"}:
            continue
        if log.get("actor_id") != actor_id:
            continue
        # only entries on this project
        if log.get("payload", {}).get("project_id") not in (None, project_id):
            continue
        if log.get("actor_role") == "ProcurementOfficer":
            seen_officer = True
        if log.get("actor_role") == "EvaluationExpert":
            seen_expert = True
    if actor_role == "ProcurementOfficer" and seen_expert:
        return True
    if actor_role == "EvaluationExpert" and seen_officer:
        return True
    return False


def form_committee(project_id: str, body: dict):
    project = get_project_or_404(project_id)
    # PRD §3.7: "Before evaluation can begin, the officer forms an
    # EvaluationCommittee." PRD does not pin a specific source state, so
    # we admit any state strictly before EVALUATING (i.e., any pre-
    # ceremony state). Note: PRD §3.7's ceremony transition requires
    # committee to already be FORMED, which is only useful if the
    # committee can be created during PRESCREEN_OPEN / BIDDING_OPEN /
    # BIDDING_CLOSED.
    if project["project_status"] not in {
        "PRESCREEN_OPEN", "BIDDING_OPEN", "BIDDING_CLOSED",
    }:
        raise_error(ERR_INVALID_STATE, "project not in a state where committee can be formed")
    if project_id in db.committee_by_project:
        raise_error(ERR_INVALID_STATE, "committee already exists for project")
    # CoI check on the four guarded endpoints (priority 7)
    if _coi_violation_form_committee(project_id):
        raise_error(ERR_CONFLICT_OF_INTEREST, "actor has prior conflicting role on this project")
    requested_size = body.get("requested_size")
    selection_seed = body.get("selection_seed")
    if isinstance(requested_size, bool) or not isinstance(requested_size, int):
        raise_error(ERR_COMMITTEE_SIZE_INVALID, "requested_size must be integer")
    if requested_size not in {3, 5, 7, 9}:
        raise_error(ERR_COMMITTEE_SIZE_INVALID, "requested_size must be in {3,5,7,9}")
    if not isinstance(selection_seed, str) or not selection_seed:
        raise_error(ERR_VALIDATION, "selection_seed must be non-empty string")
    # PRD §3.7's form-committee payload is "requested_size + selection_seed"
    # only. The "eligible pool of experts" is an internal property of the
    # system (PRD does not pin its source). We synthesise a deterministic
    # pool of synthetic expert ids that is comfortably larger than the
    # legal maximum requested_size (9) and exclude any expert who has a
    # CoI tie to a bidder on this project.
    POOL_BASE = "expert-pool-"
    POOL_SIZE = 32  # comfortably > 9 and stable across calls
    eligible_pool = [f"{POOL_BASE}{i:03d}" for i in range(POOL_SIZE)]
    excluded = set(body.get("excluded_expert_ids") or [])
    # Also exclude any expert id that equals a project bidder's supplier_id (bid principal)
    for b in db.bids.values():
        if b["project_id"] == project_id and b["bid_status"] in {"SUBMITTED", "OPENED", "EVALUATED", "AWARDED", "LOST", "DISQUALIFIED"}:
            excluded.add(b["supplier_id"])
    eligible = [eid for eid in eligible_pool if eid not in excluded]
    if len(eligible) < requested_size:
        raise_error(ERR_COMMITTEE_SIZE_INVALID, "insufficient eligible experts after CoI exclusion")
    # Deterministic ordering: sort by sha256(seed || "|" || expert.id) hex ascending
    def keyfn(eid):
        h = hashlib.sha256()
        h.update(selection_seed.encode("utf-8"))
        h.update(b"|")
        h.update(eid.encode("utf-8"))
        return h.hexdigest()
    sorted_pool = sorted(eligible, key=keyfn)
    picked = sorted_pool[:requested_size]
    members = [
        {"expert_id": eid, "selected_at": clock.now_iso(), "conflict_cleared": True}
        for eid in picked
    ]
    committee = {
        "id": db.new_id(),
        **light_fields_create(),
        "project_id": project_id,
        "members": members,
        "selection_seed": selection_seed,
        "committee_status": "FORMED",
    }
    db.committees[committee["id"]] = committee
    db.committee_by_project[project_id] = committee["id"]
    return committee


def finalize_committee(committee_id: str):
    c = get_committee_or_404(committee_id)
    if c["committee_status"] != "EVALUATING":
        raise_error(ERR_INVALID_STATE, "committee must be EVALUATING")
    # Every Bid with bid_status IN {OPENED, EVALUATED} must be EVALUATED
    for bid in db.bids.values():
        if bid["project_id"] == c["project_id"] and bid["bid_status"] == "OPENED":
            raise_error(ERR_INVALID_STATE, "not all opened bids are evaluated")
    c["committee_status"] = "FINALIZED"
    return c


# ---------------------------------------------------------------------------
# Bid-opening ceremony
# ---------------------------------------------------------------------------


def open_bid_ceremony(project_id: str):
    project = get_project_or_404(project_id)
    if project["project_status"] != "BIDDING_CLOSED":
        raise_error(ERR_INVALID_STATE, "project must be BIDDING_CLOSED")
    try:
        opening = parse_iso(project["bid_opening_at"])
    except Exception:
        raise_error(ERR_VALIDATION, "invalid bid_opening_at")
    if not (clock.now() >= opening):
        raise_error(ERR_INVALID_STATE, "bid_opening_at not yet reached")
    cid = db.committee_by_project.get(project_id)
    if not cid:
        raise_error(ERR_INVALID_STATE, "no committee formed")
    committee = db.committees[cid]
    if committee["committee_status"] != "FORMED":
        raise_error(ERR_INVALID_STATE, "committee must be FORMED")
    # Count SUBMITTED bids
    submitted = [b for b in db.bids.values() if b["project_id"] == project_id and b["bid_status"] == "SUBMITTED"]
    if len(submitted) < 3:
        raise_error(ERR_INVALID_STATE, "need at least 3 SUBMITTED bids to open ceremony")
    # Transition
    project["project_status"] = "EVALUATING"
    bump_version(project)
    # Move SUBMITTED prescreen-passing bids to OPENED
    for b in submitted:
        if b.get("prescreen_passed"):
            b["bid_status"] = "OPENED"
            bump_version(b)
    committee["committee_status"] = "EVALUATING"
    append_audit("EVALUATION", project_id, "BID_CEREMONY_RECORDED", {
        "project_id": project_id,
        "committee_id": committee["id"],
    })
    return project


# ---------------------------------------------------------------------------
# Record evaluation
# ---------------------------------------------------------------------------


def _coi_violation_record_eval(project_id: str) -> bool:
    actor_id = getattr(g, "user_id", None)
    actor_role = getattr(g, "user_role", None)
    if actor_id is None:
        return False
    if actor_role == "Supplier":
        return True  # Supplier cannot be a Regulator/Expert
    # Same X-User-ID must not have appeared as ProcurementOfficer on this project's audit history
    for log in db.audit_logs:
        if log.get("actor_id") != actor_id:
            continue
        if log.get("payload", {}).get("project_id") not in (None, project_id):
            continue
        if log.get("actor_role") == "ProcurementOfficer":
            return True
    return False


def record_evaluation(bid_id: str, body: dict):
    bid = get_bid_or_404(bid_id)
    project = get_project_or_404(bid["project_id"])
    # CoI check (priority 7)
    if _coi_violation_record_eval(project["id"]):
        raise_error(ERR_CONFLICT_OF_INTEREST, "actor has CoI on this project")
    cid = db.committee_by_project.get(project["id"])
    if not cid:
        raise_error(ERR_INVALID_STATE, "no committee on project")
    committee = db.committees[cid]
    if committee["committee_status"] != "EVALUATING":
        raise_error(ERR_INVALID_STATE, "committee must be EVALUATING")
    # Actor must be a committee member
    actor_id = getattr(g, "user_id", None)
    member_ids = {m["expert_id"] for m in committee.get("members", [])}
    if actor_id not in member_ids:
        raise_error(ERR_FORBIDDEN, "actor is not a member of this committee")
    # Bid state CAS OPENED -> EVALUATED
    if bid["bid_status"] == "EVALUATED":
        raise_error(ERR_BID_ALREADY_EVALUATED, "bid already evaluated")
    if bid["bid_status"] != "OPENED":
        raise_error(ERR_INVALID_STATE, "bid must be OPENED to record evaluation")
    # technical_score_raw override
    tsr_override = body.get("technical_score_raw")
    if tsr_override is not None:
        if isinstance(tsr_override, bool) or not isinstance(tsr_override, (int, float)):
            raise_error(ERR_VALIDATION, "technical_score_raw must be number")
        doc_id = db.tender_by_project.get(project["id"])
        doc = db.tender_documents.get(doc_id) if doc_id else None
        if doc:
            mts = (doc.get("evaluation_criteria") or {}).get("max_technical_score")
            if mts is not None and tsr_override > float(mts):
                raise_error(ERR_VALIDATION, "technical_score_raw exceeds max_technical_score")
        if tsr_override < 0:
            raise_error(ERR_VALIDATION, "technical_score_raw must be >= 0")
        bid["technical_score_raw"] = tsr_override
    # Compute final_score
    bid["bid_status"] = "EVALUATED"
    bid["final_score"] = _compute_final_score(bid, project)
    bump_version(bid)
    append_audit("EVALUATION", bid["id"], "EVALUATION_SCORE_RECORDED", {
        "project_id": project["id"],
        "bid_id": bid["id"],
        "final_score": bid["final_score"],
    })
    return bid


def _compute_final_score(bid: dict, project: dict):
    em = project["evaluation_method"]
    if em == "LOWEST_PRICE":
        return int(bid["bid_price_cents"])
    # COMPREHENSIVE_SCORING
    doc_id = db.tender_by_project.get(project["id"])
    doc = db.tender_documents[doc_id]
    ec = doc["evaluation_criteria"]
    # lowest bid price among OPENED or EVALUATED bids on project (inclusive of self)
    relevant = [
        b for b in db.bids.values()
        if b["project_id"] == project["id"] and b["bid_status"] in {"OPENED", "EVALUATED"}
    ]
    # include self (which is mid-transition to EVALUATED)
    if bid["id"] not in {b["id"] for b in relevant}:
        relevant = relevant + [bid]
    lowest = min(b["bid_price_cents"] for b in relevant)
    price_sub = _round_half_up_2(100.0 * lowest / bid["bid_price_cents"])
    mts = float(ec.get("max_technical_score") or 1)
    tech_sub = _round_half_up_2(100.0 * float(bid.get("technical_score_raw") or 0) / mts)
    supplier = db.suppliers.get(bid["supplier_id"])
    supplier_quals = set((supplier.get("qualifications") or []) if supplier else [])
    doc_quals = set(doc.get("qualification_requirements") or [])
    intersection = len(supplier_quals & doc_quals)
    denom = max(1, len(doc_quals))
    qual_sub = _round_half_up_2(100.0 * intersection / denom)
    wp = float(ec.get("weight_price"))
    wt = float(ec.get("weight_technical"))
    wq = float(ec.get("weight_qualification"))
    weighted = wp * price_sub + wt * tech_sub + wq * qual_sub
    return _round_half_up_2(weighted)


# ---------------------------------------------------------------------------
# Decide award
# ---------------------------------------------------------------------------


def _pick_winner(project: dict):
    em = project["evaluation_method"]
    evaluated = [b for b in db.bids.values() if b["project_id"] == project["id"] and b["bid_status"] == "EVALUATED"]
    if not evaluated:
        return None
    if em == "LOWEST_PRICE":
        # smaller is better; tie-break = earliest created_at
        evaluated.sort(key=lambda b: (b["final_score"], b["created_at"]))
        return evaluated[0]
    # COMPREHENSIVE_SCORING: higher final_score; tie-break smaller bid_price, then earliest created_at
    evaluated.sort(key=lambda b: (-float(b["final_score"]), b["bid_price_cents"], b["created_at"]))
    return evaluated[0]


def decide_award(project_id: str):
    project = get_project_or_404(project_id)
    if project["project_status"] != "EVALUATING":
        raise_error(ERR_INVALID_STATE, "project must be EVALUATING")
    cid = db.committee_by_project.get(project_id)
    if not cid:
        raise_error(ERR_INVALID_STATE, "no committee")
    committee = db.committees[cid]
    if committee["committee_status"] != "FINALIZED":
        raise_error(ERR_INVALID_STATE, "committee must be FINALIZED")
    winner = _pick_winner(project)
    if not winner:
        raise_error(ERR_INVALID_STATE, "no EVALUATED bid to award")
    # snapshot tender version at award time
    doc_id = db.tender_by_project.get(project_id)
    doc = db.tender_documents[doc_id]
    award = {
        "id": db.new_id(),
        **common_fields_create(),
        "project_id": project_id,
        "winning_bid_id": winner["id"],
        "award_status": "DECIDED",
        "published_at": None,
        "award_amount_cents": int(winner["bid_price_cents"]),
    }
    db.awards[award["id"]] = award
    db.award_by_project[project_id] = award["id"]
    db.award_tender_version[award["id"]] = int(doc["version"])
    project["project_status"] = "AWARDED"
    bump_version(project)
    # winner -> AWARDED, others EVALUATED -> LOST
    for b in db.bids.values():
        if b["project_id"] == project_id and b["bid_status"] == "EVALUATED":
            if b["id"] == winner["id"]:
                b["bid_status"] = "AWARDED"
            else:
                b["bid_status"] = "LOST"
            bump_version(b)
    append_audit("AWARD", award["id"], "AWARD_DECIDED", {
        "project_id": project_id,
        "award_id": award["id"],
        "winning_bid_id": winner["id"],
        "award_amount_cents": award["award_amount_cents"],
    })
    return award


def publish_award(award_id: str):
    a = get_award_or_404(award_id)
    if a["award_status"] != "DECIDED":
        raise_error(ERR_INVALID_STATE, "award must be DECIDED to publish")
    a["award_status"] = "PUBLISHED"
    a["published_at"] = clock.now_iso()
    bump_version(a)
    return a
