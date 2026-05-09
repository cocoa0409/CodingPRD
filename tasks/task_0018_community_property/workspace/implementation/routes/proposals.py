"""Proposal lifecycle: DRAFT -> OPEN -> TALLIED_PASSED/FAILED -> PUBLISHED, plus
vote casting and CANCELLED."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, g

import db
from errors import (
    APIError,
    ERR_DUPLICATE_VOTE,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND,
    ERR_VALIDATION,
    ERR_VOTER_NOT_ELIGIBLE,
    ERR_VOTING_CLOSED,
    ERR_VOTING_WINDOW_INVALID,
)
from middleware import require_roles
from response import success
from services.audit import write_audit
from services.common import bump, snapshot, stamp_create
from utils import (
    get_body,
    iso_format,
    parse_iso,
    require_field,
    round2_dec,
    to_decimal,
)

bp = Blueprint("proposals", __name__)

VALID_VOTING_METHODS = {"PER_HOUSEHOLD", "PER_AREA"}
VALID_CHOICES = {"YES", "NO", "ABSTAIN"}


def _get_or_404(pid):
    p = db.proposals.get(pid)
    if p is None:
        raise APIError(ERR_NOT_FOUND, f"Proposal {pid} not found.", 404)
    return p


@bp.post("/proposals")
@require_roles("CommitteeChair")
def create_proposal():
    body = get_body()
    title = require_field(body, "title")
    voting_method = require_field(body, "voting_method")
    voting_starts_at = require_field(body, "voting_starts_at")
    voting_ends_at = require_field(body, "voting_ends_at")
    pass_threshold_pct = body.get("pass_threshold_pct", 0.6667)

    if voting_method not in VALID_VOTING_METHODS:
        raise APIError(ERR_VALIDATION, "Invalid voting_method.", 422)
    threshold_d = to_decimal(pass_threshold_pct)
    if threshold_d < to_decimal("0.5") or threshold_d > to_decimal("1"):
        raise APIError(ERR_VALIDATION, "pass_threshold_pct must be in [0.5, 1.0].", 422)

    starts = parse_iso(voting_starts_at, field="voting_starts_at")
    ends = parse_iso(voting_ends_at, field="voting_ends_at")
    if starts >= ends:
        raise APIError(ERR_VOTING_WINDOW_INVALID, "voting_starts_at must be before voting_ends_at.", 422)

    proposal = {
        "title": title,
        "voting_method": voting_method,
        "pass_threshold_pct": float(threshold_d),
        "voting_starts_at": iso_format(starts),
        "voting_ends_at": iso_format(ends),
        "status": "DRAFT",
        "eligible_weight_total": 0.0,
        "yes_weight": 0.0,
        "no_weight": 0.0,
        "published_at": None,
    }
    stamp_create(proposal)
    db.proposals[proposal["id"]] = proposal
    return success(proposal, status=201)


@bp.post("/proposals/<pid>/open")
@require_roles("CommitteeChair")
def open_proposal(pid):
    p = _get_or_404(pid)
    if p["status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, "Proposal is not DRAFT.", 409)
    starts = parse_iso(p["voting_starts_at"], field="voting_starts_at")
    ends = parse_iso(p["voting_ends_at"], field="voting_ends_at")
    if starts >= ends:
        raise APIError(ERR_VOTING_WINDOW_INVALID, "Voting window invalid.", 422)
    if db.now() >= ends:
        raise APIError(ERR_VOTING_WINDOW_INVALID, "voting_ends_at already past.", 422)

    # Snapshot eligible voter list: for each ELIGIBLE owner, every property they
    # own contributes weight (1.0 per household, area_sqm per area).
    eligibility: dict[tuple[str, str], float] = {}
    total_weight = Decimal("0")
    for owner in db.owners.values():
        if owner.get("voting_status") != "ELIGIBLE":
            continue
        owner_props = [p2 for p2 in db.properties.values() if p2.get("owner_id") == owner["id"]]
        for prop in owner_props:
            if p["voting_method"] == "PER_HOUSEHOLD":
                weight = Decimal("1")
            else:  # PER_AREA
                weight = to_decimal(prop["area_sqm"])
            eligibility[(owner["id"], prop["id"])] = float(weight)
            total_weight += weight

    db.proposal_eligibility[pid] = eligibility
    p["eligible_weight_total"] = float(total_weight)
    p["status"] = "OPEN"
    bump(p)
    write_audit(
        subject_kind="PROPOSAL",
        subject_id=pid,
        action="PROPOSAL_OPENED",
        before={},
        after=snapshot(p),
    )
    return success(p)


@bp.post("/proposals/<pid>/votes")
@require_roles("Owner")
def cast_vote(pid):
    p = _get_or_404(pid)
    body = get_body()
    property_id = require_field(body, "property_id")
    choice = require_field(body, "choice")

    if choice not in VALID_CHOICES:
        raise APIError(ERR_VALIDATION, "Invalid choice.", 422)

    prop = db.properties.get(property_id)
    if prop is None:
        raise APIError(ERR_REFERENCE_NOT_FOUND, f"Property {property_id} not found.", 404)

    # State precondition first (priority 6)
    if p["status"] != "OPEN":
        raise APIError(ERR_INVALID_STATE, "Proposal is not OPEN.", 409)

    # Owner must own the property
    if prop.get("owner_id") != g.user_id:
        raise APIError(ERR_FORBIDDEN, "Owner does not own the property.", 403)

    eligibility = db.proposal_eligibility.get(pid, {})
    key = (g.user_id, property_id)

    # Priority 7: voter eligibility (was on frozen list)
    if key not in eligibility:
        raise APIError(ERR_VOTER_NOT_ELIGIBLE, "Voter not on the eligible list.", 403)

    # Priority 8: vote uniqueness
    with db.mutation_lock:
        for v in db.votes.values():
            if v.get("proposal_id") == pid and v.get("property_id") == property_id:
                raise APIError(ERR_DUPLICATE_VOTE, "Vote already cast for this property.", 409)

        # Priority 20: voting window
        starts = parse_iso(p["voting_starts_at"], field="voting_starts_at")
        ends = parse_iso(p["voting_ends_at"], field="voting_ends_at")
        now = db.now()
        if not (starts <= now < ends):
            raise APIError(ERR_VOTING_CLOSED, "Voting is not currently open.", 409)

        weight = eligibility[key]
        vote = {
            "id": db.new_id(),
            "created_at": iso_format(db.now()),
            "proposal_id": pid,
            "voter_owner_id": g.user_id,
            "property_id": property_id,
            "choice": choice,
            "weight": float(weight),
        }
        # Vote has no version/updated_at (PRD §2.4).
        db.votes[vote["id"]] = vote

        if choice == "YES":
            p["yes_weight"] = float(round2_dec(to_decimal(p.get("yes_weight", 0)) + to_decimal(weight)))
        elif choice == "NO":
            p["no_weight"] = float(round2_dec(to_decimal(p.get("no_weight", 0)) + to_decimal(weight)))
        bump(p)

    write_audit(
        subject_kind="VOTE",
        subject_id=vote["id"],
        action="VOTE_CAST",
        before={},
        after=snapshot(vote),
    )
    return success(vote, status=201)


@bp.post("/proposals/<pid>/tally")
@require_roles("CommitteeChair")
def tally(pid):
    p = _get_or_404(pid)
    if p["status"] != "OPEN":
        raise APIError(ERR_INVALID_STATE, "Proposal is not OPEN.", 409)
    ends = parse_iso(p["voting_ends_at"], field="voting_ends_at")
    if db.now() < ends:
        raise APIError(ERR_INVALID_STATE, "Voting has not yet ended.", 409)

    yes_w = to_decimal(p.get("yes_weight", 0))
    total_w = to_decimal(p.get("eligible_weight_total", 0))
    threshold = to_decimal(p.get("pass_threshold_pct", 0))

    if total_w == 0:
        passes = False
    else:
        passes = (yes_w / total_w) >= threshold

    before = snapshot(p)
    p["status"] = "TALLIED_PASSED" if passes else "TALLIED_FAILED"
    bump(p)
    write_audit(
        subject_kind="PROPOSAL",
        subject_id=pid,
        action="PROPOSAL_TALLIED_PASSED" if passes else "PROPOSAL_TALLIED_FAILED",
        before=before,
        after=snapshot(p),
    )
    return success(p)


@bp.post("/proposals/<pid>/publish")
@require_roles("CommitteeChair")
def publish(pid):
    p = _get_or_404(pid)
    if p["status"] not in ("TALLIED_PASSED", "TALLIED_FAILED"):
        raise APIError(ERR_INVALID_STATE, "Proposal must be tallied before publish.", 409)
    p["published_at"] = iso_format(db.now())
    p["status"] = "PUBLISHED"
    bump(p)
    write_audit(
        subject_kind="PROPOSAL",
        subject_id=pid,
        action="PROPOSAL_PUBLISHED",
        before={},
        after=snapshot(p),
    )
    return success(p)


@bp.post("/proposals/<pid>/cancel")
@require_roles("CommitteeChair")
def cancel(pid):
    p = _get_or_404(pid)
    status = p["status"]
    if status == "DRAFT":
        # unconditional
        p["status"] = "CANCELLED"
        bump(p)
        return success(p)
    if status == "OPEN":
        ends = parse_iso(p["voting_ends_at"], field="voting_ends_at")
        if db.now() >= ends:
            raise APIError(ERR_INVALID_STATE, "Cannot cancel after voting_ends_at.", 409)
        p["status"] = "CANCELLED"
        bump(p)
        write_audit(
            subject_kind="PROPOSAL",
            subject_id=pid,
            action="PROPOSAL_CANCELLED",
            before={},
            after=snapshot(p),
        )
        return success(p)
    raise APIError(ERR_INVALID_STATE, "Proposal cannot be cancelled in this state.", 409)


@bp.get("/proposals/<pid>")
@require_roles("PropertyManager", "CommitteeChair", "Owner")
def get_proposal(pid):
    p = _get_or_404(pid)
    return success(p)
