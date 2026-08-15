"""Motion + Vote routes."""
from datetime import timedelta

from flask import Blueprint, request

import db
from db import clock, _format_iso, _parse_iso
from middleware import get_auth, require_roles
from response import success_object, success_list
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_MOTION_NOT_OPEN, ERR_MOTION_TERMINAL, ERR_QUORUM_NOT_MET,
    ERR_COMMITTEE_IMPAIRED, ERR_VOTER_INELIGIBLE, ERR_VOTER_RECUSED,
    ERR_COI_REVIEW_PENDING, ERR_SEGREGATION_OF_DUTIES, ERR_VOTING_CLOSED,
    ERR_DUPLICATE_VOTE, ERR_PHYSICIAN_EXITING, ERR_NO_ELIGIBLE_RECIPIENTS,
    ERR_DISTRIBUTION_CAP_EXCEEDED,
)
from services.core import (
    get_body, check_unknown_fields, req_enum, opt_str, dec,
    new_entity, touch, get_or_404, pagination_params, paginate,
    serialize_motion, serialize_vote, motion_threshold_type,
    recompute_motion_counts, motion_tallies, committee_status,
    serialize_committee, compute_distributable_cap,
    compute_distribution_allocations, eligible_distribution_recipients,
    serialize_distribution, serialize_call, serialize_physician,
)

bp = Blueprint("motions", __name__)
ALL_ROLES = ("BoardAdmin", "Physician", "ComplianceOfficer")

MOTION_TYPES = ("CHARTER_AMENDMENT", "COMP_POLICY", "CAPITAL_CALL",
                "DISTRIBUTION", "BUYOUT_APPROVAL", "MERGER")
MOTION_TERMINAL = ("ADOPTED", "REJECTED", "WITHDRAWN", "EXPIRED", "SUPERSEDED")


def _validate_payload(motion_type, payload):
    """Priority-2 shape validation of the type-specific payload."""
    if payload is None or not isinstance(payload, dict):
        raise_err(ERR_INVALID_REQUEST, "payload is required")
    if motion_type == "CAPITAL_CALL":
        for f in ("amount_cents", "due_date", "purpose"):
            if f not in payload:
                raise_err(ERR_INVALID_REQUEST, f"payload.{f} is required")
        amt = payload["amount_cents"]
        if isinstance(amt, bool) or not isinstance(amt, int) or amt <= 0:
            raise_err(ERR_INVALID_REQUEST, "payload.amount_cents must be positive")
        if not isinstance(payload["purpose"], str):
            raise_err(ERR_INVALID_REQUEST, "payload.purpose must be a string")
        try:
            due = _parse_iso(payload["due_date"])
        except Exception:
            raise_err(ERR_INVALID_REQUEST, "payload.due_date invalid")
        if due <= clock.now():
            raise_err(ERR_INVALID_REQUEST,
                      "payload.due_date must be strictly after the clock")
    elif motion_type == "DISTRIBUTION":
        for f in ("amount_cents", "method", "fiscal_net_income_before_bonus_cents"):
            if f not in payload:
                raise_err(ERR_INVALID_REQUEST, f"payload.{f} is required")
        amt = payload["amount_cents"]
        if isinstance(amt, bool) or not isinstance(amt, int) or amt <= 0:
            raise_err(ERR_INVALID_REQUEST, "payload.amount_cents must be positive")
        if payload["method"] not in ("PRO_RATA", "SENIORITY_TIERED"):
            raise_err(ERR_INVALID_REQUEST, "payload.method invalid")
        nibb = payload["fiscal_net_income_before_bonus_cents"]
        if isinstance(nibb, bool) or not isinstance(nibb, int):
            raise_err(ERR_INVALID_REQUEST,
                      "payload.fiscal_net_income_before_bonus_cents must be integer")
    elif motion_type == "CHARTER_AMENDMENT":
        nq = payload.get("new_quorum_count")
        nt = payload.get("new_approval_threshold")
        if nq is None and nt is None:
            raise_err(ERR_INVALID_REQUEST,
                      "CHARTER_AMENDMENT payload requires new_quorum_count or new_approval_threshold")
        if nq is not None and (isinstance(nq, bool) or not isinstance(nq, int) or nq < 1):
            raise_err(ERR_INVALID_REQUEST, "payload.new_quorum_count invalid")
        if nt is not None and nt not in ("SIMPLE_MAJORITY", "SUPERMAJORITY"):
            raise_err(ERR_INVALID_REQUEST, "payload.new_approval_threshold invalid")
    elif motion_type == "COMP_POLICY":
        if "new_bonus_pool_pct" not in payload:
            raise_err(ERR_INVALID_REQUEST, "payload.new_bonus_pool_pct is required")
        v = payload["new_bonus_pool_pct"]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise_err(ERR_INVALID_REQUEST, "payload.new_bonus_pool_pct invalid")
    elif motion_type == "BUYOUT_APPROVAL":
        if "exit_valuation_id" not in payload:
            raise_err(ERR_INVALID_REQUEST, "payload.exit_valuation_id is required")
        if not isinstance(payload["exit_valuation_id"], str):
            raise_err(ERR_INVALID_REQUEST, "payload.exit_valuation_id invalid")
    elif motion_type == "MERGER":
        if "merger_proposal_id" not in payload:
            raise_err(ERR_INVALID_REQUEST, "payload.merger_proposal_id is required")
        if not isinstance(payload["merger_proposal_id"], str):
            raise_err(ERR_INVALID_REQUEST, "payload.merger_proposal_id invalid")


def _validate_payload_fks(motion_type, payload):
    """Priority-5 existence validation of body FK references."""
    if motion_type == "BUYOUT_APPROVAL":
        if payload["exit_valuation_id"] not in db.exit_valuations:
            raise_err(ERR_NOT_FOUND, "ExitValuation not found")
    if motion_type == "MERGER":
        if payload["merger_proposal_id"] not in db.merger_proposals:
            raise_err(ERR_NOT_FOUND, "MergerProposal not found")


@bp.post("/governance/motions")
def create_motion():
    role, user_id = get_auth()
    body = get_body()
    # threshold_type client-supplied -> unknown field
    if "threshold_type" in body:
        raise_err(ERR_INVALID_REQUEST, "threshold_type is computed, not accepted")
    check_unknown_fields(body, ["motion_type", "sponsor_physician_id",
                                "committee_id", "supersedes_motion_id", "payload"])

    motion_type = req_enum(body, "motion_type", MOTION_TYPES)
    sponsor_id = body.get("sponsor_physician_id")
    if not isinstance(sponsor_id, str) or not sponsor_id:
        raise_err(ERR_INVALID_REQUEST, "sponsor_physician_id is required")
    committee_id = opt_str(body, "committee_id")
    supersedes_id = opt_str(body, "supersedes_motion_id")
    payload = body.get("payload")

    if motion_type == "CHARTER_AMENDMENT" and not committee_id:
        raise_err(ERR_INVALID_REQUEST,
                  "committee_id is required for CHARTER_AMENDMENT")
    _validate_payload(motion_type, payload)

    require_roles(role, ("Physician", "BoardAdmin"))
    # ownership: Physician sponsors only for self
    if role == "Physician" and user_id != sponsor_id:
        from errors import ERR_RESOURCE_OWNERSHIP
        raise_err(ERR_RESOURCE_OWNERSHIP,
                  "Physician may only sponsor own motions")

    # existence of body FKs
    sponsor = db.physicians.get(sponsor_id)
    if sponsor is None:
        raise_err(ERR_NOT_FOUND, "Sponsor physician not found")
    if committee_id is not None and committee_id not in db.committees:
        raise_err(ERR_NOT_FOUND, "Committee not found")
    if supersedes_id is not None and supersedes_id not in db.motions:
        raise_err(ERR_NOT_FOUND, "supersedes_motion_id not found")
    _validate_payload_fks(motion_type, payload)

    # state: sponsor must be SHAREHOLDER + GOOD_STANDING; EXITING blocked
    if sponsor["partnership_status"] == "EXITING":
        raise_err(ERR_PHYSICIAN_EXITING,
                  "EXITING physician may not sponsor motions")
    if sponsor["partnership_status"] != "SHAREHOLDER" or sponsor["standing"] != "GOOD_STANDING":
        raise_err(ERR_INVALID_STATE,
                  "Sponsor must be SHAREHOLDER in GOOD_STANDING")

    # segregation of duties: COMPENSATION committee CHAIR may not sponsor COMP_POLICY
    if motion_type == "COMP_POLICY":
        for c in db.committees.values():
            if c["committee_type"] == "COMPENSATION":
                for mem in c["members"]:
                    if (mem["physician_id"] == sponsor_id
                            and mem["committee_role"] == "CHAIR"):
                        raise_err(ERR_SEGREGATION_OF_DUTIES,
                                  "COMPENSATION committee CHAIR may not sponsor COMP_POLICY")

    # supersede target state
    if supersedes_id is not None:
        target = db.motions[supersedes_id]
        if target["status"] not in ("DRAFT", "PROPOSED"):
            raise_err(ERR_MOTION_TERMINAL,
                      "Only DRAFT or PROPOSED motions may be superseded")

    # DISTRIBUTION checks: eligible recipients + cap (checked at creation)
    if motion_type == "DISTRIBUTION":
        if not eligible_distribution_recipients():
            raise_err(ERR_NO_ELIGIBLE_RECIPIENTS,
                      "No eligible shareholders for distribution")
        if db.policy is not None:
            _, cap = compute_distributable_cap(
                payload["fiscal_net_income_before_bonus_cents"])
            if payload["amount_cents"] > cap:
                raise_err(ERR_DISTRIBUTION_CAP_EXCEEDED,
                          "Distribution amount exceeds distributable cap")

    m = new_entity(db.motions, {
        "motion_type": motion_type,
        "sponsor_physician_id": sponsor_id,
        "committee_id": committee_id,
        "supersedes_motion_id": supersedes_id,
        "payload": payload,
        "threshold_type": motion_threshold_type(motion_type),
        "status": "DRAFT",
        "eligible_voter_ids": [],
        "recused_physician_ids": [],
        "eligible_voter_count": 0,
        "required_votes": 0,
        "votes_for": 0,
        "votes_against": 0,
        "votes_abstain": 0,
        "opened_at": None,
        "closes_at": None,
    })

    if supersedes_id is not None:
        target = db.motions[supersedes_id]
        target["status"] = "SUPERSEDED"
        touch(target)

    return success_object(serialize_motion(m), 201)


@bp.get("/governance/motions")
def list_motions():
    role, _ = get_auth()
    require_roles(role, ALL_ROLES)
    items = list(db.motions.values())
    f_sponsor = request.args.get("sponsor_physician_id")
    f_committee = request.args.get("committee_id")
    f_supersedes = request.args.get("supersedes_motion_id")
    f_status = request.args.get("status")
    if f_sponsor is not None:
        items = [m for m in items if m["sponsor_physician_id"] == f_sponsor]
    if f_committee is not None:
        items = [m for m in items if m.get("committee_id") == f_committee]
    if f_supersedes is not None:
        items = [m for m in items if m.get("supersedes_motion_id") == f_supersedes]
    if f_status is not None:
        items = [m for m in items if m["status"] == f_status]
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_motion(m) for m in page], limit, offset, total)


@bp.get("/governance/motions/<mid>")
def get_motion(mid):
    role, _ = get_auth()
    require_roles(role, ALL_ROLES)
    m = get_or_404(db.motions, mid, "Motion")
    return success_object(serialize_motion(m))


def _sponsor_eligible(m):
    sponsor = db.physicians.get(m["sponsor_physician_id"])
    if sponsor is None:
        return False
    return (sponsor["partnership_status"] == "SHAREHOLDER"
            and sponsor["standing"] == "GOOD_STANDING")


def _motion_actor_check(role, user_id, m):
    """Physician callers may act on own motions; BoardAdmin always allowed."""
    if role == "Physician" and user_id != m["sponsor_physician_id"]:
        from errors import ERR_RESOURCE_OWNERSHIP
        raise_err(ERR_RESOURCE_OWNERSHIP, "Physician may only act on own motions")


@bp.post("/governance/motions/<mid>/propose")
def propose_motion(mid):
    role, user_id = get_auth()
    require_roles(role, ("Physician", "BoardAdmin"))
    m = get_or_404(db.motions, mid, "Motion")
    _motion_actor_check(role, user_id, m)
    if m["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Motion is not DRAFT")
    if not _sponsor_eligible(m):
        raise_err(ERR_INVALID_STATE,
                  "Sponsor must be SHAREHOLDER in GOOD_STANDING")
    m["status"] = "PROPOSED"
    touch(m)
    return success_object(serialize_motion(m))


@bp.post("/governance/motions/<mid>/open")
def open_motion(mid):
    role, user_id = get_auth()
    require_roles(role, ("Physician", "BoardAdmin"))
    m = get_or_404(db.motions, mid, "Motion")
    _motion_actor_check(role, user_id, m)
    if m["status"] != "PROPOSED":
        raise_err(ERR_INVALID_STATE, "Motion is not PROPOSED")
    if not _sponsor_eligible(m):
        raise_err(ERR_INVALID_STATE,
                  "Sponsor must be SHAREHOLDER in GOOD_STANDING")
    if m["motion_type"] == "CHARTER_AMENDMENT":
        c = db.committees.get(m["committee_id"])
        if c is None or c["status"] != "ACTIVE":
            raise_err(ERR_COMMITTEE_IMPAIRED,
                      "Committee must be ACTIVE to open a CHARTER_AMENDMENT")
    # snapshot electorate
    now = clock.now()
    m["eligible_voter_ids"] = [p["id"] for p in db.physicians.values()
                               if p["partnership_status"] == "SHAREHOLDER"
                               and p["standing"] == "GOOD_STANDING"]
    m["opened_at"] = _format_iso(now)
    closes = now + timedelta(days=db.policy["voting_window_days"])
    m["closes_at"] = _format_iso(closes)
    m["status"] = "OPEN"
    recompute_motion_counts(m)
    touch(m)
    return success_object(serialize_motion(m))


@bp.post("/governance/motions/<mid>/table")
def table_motion(mid):
    role, user_id = get_auth()
    require_roles(role, ("Physician", "BoardAdmin"))
    m = get_or_404(db.motions, mid, "Motion")
    _motion_actor_check(role, user_id, m)
    if m["status"] != "OPEN":
        raise_err(ERR_MOTION_NOT_OPEN, "Motion is not OPEN")
    m["status"] = "TABLED"
    touch(m)
    return success_object(serialize_motion(m))


@bp.post("/governance/motions/<mid>/resume")
def resume_motion(mid):
    role, user_id = get_auth()
    require_roles(role, ("Physician", "BoardAdmin"))
    m = get_or_404(db.motions, mid, "Motion")
    _motion_actor_check(role, user_id, m)
    if m["status"] != "TABLED":
        raise_err(ERR_INVALID_STATE, "Motion is not TABLED")
    now = clock.now()
    m["opened_at"] = _format_iso(now)
    m["closes_at"] = _format_iso(now + timedelta(days=db.policy["voting_window_days"]))
    m["status"] = "OPEN"
    touch(m)
    return success_object(serialize_motion(m))


@bp.post("/governance/motions/<mid>/withdraw")
def withdraw_motion(mid):
    role, user_id = get_auth()
    require_roles(role, ("Physician", "BoardAdmin"))
    m = get_or_404(db.motions, mid, "Motion")
    _motion_actor_check(role, user_id, m)
    if m["status"] not in ("DRAFT", "PROPOSED", "TABLED"):
        raise_err(ERR_INVALID_STATE, "Motion cannot be withdrawn from this state")
    m["status"] = "WITHDRAWN"
    touch(m)
    return success_object(serialize_motion(m))


def _adopt_side_effects(m):
    """Type-specific adoption effects (§3.4)."""
    payload = m["payload"]
    if m["motion_type"] == "CAPITAL_CALL":
        new_entity(db.capital_calls, {
            "motion_id": m["id"],
            "purpose": payload["purpose"],
            "total_amount_cents": payload["amount_cents"],
            "due_date": payload["due_date"],
            "assessed_total_cents": 0,
            "collected_cents": 0,
            "status": "APPROVED",
        })
    elif m["motion_type"] == "DISTRIBUTION":
        # re-check eligibility at adoption
        if not eligible_distribution_recipients():
            raise_err(ERR_NO_ELIGIBLE_RECIPIENTS,
                      "No eligible shareholders for distribution")
        nibb = payload["fiscal_net_income_before_bonus_cents"]
        bonus, cap = compute_distributable_cap(nibb)
        if payload["amount_cents"] > cap:
            raise_err(ERR_DISTRIBUTION_CAP_EXCEEDED,
                      "Distribution amount exceeds distributable cap")
        alloc_map = compute_distribution_allocations(
            payload["amount_cents"], payload["method"])
        allocations = [{
            "physician_id": pid,
            "allocated_cents": cents,
            "status": "PENDING",
        } for pid, cents in alloc_map.items()]
        new_entity(db.distributions, {
            "motion_id": m["id"],
            "total_amount_cents": payload["amount_cents"],
            "method": payload["method"],
            "fiscal_net_income_before_bonus_cents": nibb,
            "bonus_accrual_cents": bonus,
            "distributable_cap_cents": cap,
            "allocations": allocations,
            "status": "APPROVED",
        })
    elif m["motion_type"] == "CHARTER_AMENDMENT":
        c = db.committees.get(m["committee_id"])
        if c is not None:
            if payload.get("new_quorum_count") is not None:
                c["quorum_count"] = payload["new_quorum_count"]
            if payload.get("new_approval_threshold") is not None:
                c["approval_threshold"] = payload["new_approval_threshold"]
            c["charter_version"] += 1
            c["status"] = committee_status(len(c["members"]), c["quorum_count"],
                                           c["status"])
            touch(c)
    elif m["motion_type"] == "COMP_POLICY":
        if db.policy is not None:
            db.policy["bonus_pool_pct"] = payload["new_bonus_pool_pct"]
            db.policy["comp_policy_version"] += 1
            touch(db.policy)
    # BUYOUT_APPROVAL / MERGER: no direct effect at adoption


@bp.post("/governance/motions/<mid>/close")
def close_motion(mid):
    role, _ = get_auth()
    require_roles(role, ("BoardAdmin",))
    m = get_or_404(db.motions, mid, "Motion")
    if m["status"] != "OPEN":
        raise_err(ERR_MOTION_NOT_OPEN, "Motion is not OPEN")
    motion_tallies(m)
    cast = m["votes_for"] + m["votes_against"] + m["votes_abstain"]
    quorum = db.policy["board_quorum_count"] if db.policy else 5
    if cast < quorum:
        raise_err(ERR_QUORUM_NOT_MET, "Quorum not met")

    if m["threshold_type"] == "SUPERMAJORITY":
        recompute_motion_counts(m)
        adopted = m["votes_for"] >= m["required_votes"]
    else:
        adopted = m["votes_for"] > m["votes_against"]

    if adopted:
        _adopt_side_effects(m)
        m["status"] = "ADOPTED"
    else:
        m["status"] = "REJECTED"
    touch(m)
    return success_object(serialize_motion(m))


# ---------------- Votes ----------------

@bp.post("/governance/motions/<mid>/votes")
def cast_vote(mid):
    role, user_id = get_auth()
    body = get_body()
    check_unknown_fields(body, ["vote_choice"])
    choice = req_enum(body, "vote_choice", ("FOR", "AGAINST", "ABSTAIN"))
    require_roles(role, ("Physician",))
    m = get_or_404(db.motions, mid, "Motion")
    # voter is self; existence of physician
    phys = db.physicians.get(user_id)
    if phys is None:
        raise_err(ERR_NOT_FOUND, "Physician not found")

    # state
    if m["status"] != "OPEN":
        raise_err(ERR_MOTION_NOT_OPEN, "Motion is not OPEN")
    # eligibility: in snapshot and still GOOD_STANDING
    if user_id not in m["eligible_voter_ids"] or phys["standing"] != "GOOD_STANDING":
        raise_err(ERR_VOTER_INELIGIBLE, "Voter is not eligible")

    # compliance gates
    if user_id in m["recused_physician_ids"]:
        raise_err(ERR_VOTER_RECUSED, "Voter is recused from this motion")
    for c in db.coi_disclosures.values():
        if (c["physician_id"] == user_id and c.get("related_motion_id") == mid
                and c["status"] == "FILED"):
            raise_err(ERR_COI_REVIEW_PENDING,
                      "Unreviewed COI disclosure on this motion")
    if (m["motion_type"] == "COMP_POLICY"
            and m["sponsor_physician_id"] == user_id):
        raise_err(ERR_SEGREGATION_OF_DUTIES,
                  "Sponsor may not vote on own COMP_POLICY motion")

    # temporal
    if m.get("closes_at") and clock.now() >= _parse_iso(m["closes_at"]):
        raise_err(ERR_VOTING_CLOSED, "Voting window has closed")

    # uniqueness
    for v in db.votes.values():
        if (v["motion_id"] == mid and v["physician_id"] == user_id
                and v["status"] != "VOIDED"):
            raise_err(ERR_DUPLICATE_VOTE, "Duplicate vote")

    v = new_entity(db.votes, {
        "motion_id": mid,
        "physician_id": user_id,
        "vote_choice": choice,
        "status": "CAST",
        "void_reason": None,
    })
    motion_tallies(m)
    touch(m)
    return success_object(serialize_vote(v), 201)


@bp.get("/governance/motions/<mid>/votes")
def list_motion_votes(mid):
    role, _ = get_auth()
    require_roles(role, ALL_ROLES)
    get_or_404(db.motions, mid, "Motion")
    items = [v for v in db.votes.values() if v["motion_id"] == mid]
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_vote(v) for v in page], limit, offset, total)


@bp.get("/governance/physicians/<pid>/votes")
def list_physician_votes(pid):
    role, _ = get_auth()
    require_roles(role, ALL_ROLES)
    get_or_404(db.physicians, pid, "Physician")
    items = [v for v in db.votes.values() if v["physician_id"] == pid]
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_vote(v) for v in page], limit, offset, total)
