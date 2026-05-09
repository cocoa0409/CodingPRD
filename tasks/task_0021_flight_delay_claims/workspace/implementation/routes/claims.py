"""Claim routes (creation, review, approve, reject, settle, mark_exception, reverse)."""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from db import db, gen_id, now_iso_z
from errors import (
    ERR_CLAIM_NOT_ELIGIBLE,
    ERR_FLIGHT_NOT_FINALIZED,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_POLICY_INACTIVE,
    ERR_QUOTA_EXHAUSTED,
    ERR_SOD_VIOLATION,
    ERR_TICKET_NOT_BOUND,
    ERR_WAITING_PERIOD_NOT_MET,
    raise_api_error,
)
from middleware import require_roles
from response import list_response, success_response
from services.calculations import combined_payout, prorate_segments, reinsurance_waterfall
from services.common import (
    append_audit,
    check_version,
    emit_outbox,
    get_claim_or_404,
    get_insurer_or_404,
    get_json_body,
    get_policy_or_404,
    optional_field,
    paginate,
    parse_pagination,
    require_field,
    sort_by_created_at,
)
from services.eligibility import recompute_claim_segments
from services.reserve import append_reserve_adjustment

bp = Blueprint("claims", __name__)


VALID_REJECTION_REASONS = {
    "EXCLUDED_CAUSE", "WAITING_PERIOD", "DELAY_BELOW_THRESHOLD", "MANUAL_DENY",
}


def _serialize_claim(c: dict) -> dict:
    out = dict(c)
    segs = []
    for sid in c.get("segment_ids", []):
        seg = db.claim_segments.get(sid)
        if seg:
            segs.append(dict(seg))
    out["segments"] = segs
    return out


def _create_segment(claim: dict, ticket: dict, claimed_actual_loss_cents: int = 0) -> dict:
    seg = {
        "id": gen_id(),
        "claim_id": claim["id"],
        "insurer_id": claim["insurer_id"],
        "ticket_id": ticket["id"],
        "flight_id": ticket["flight_id"],
        "claimed_actual_loss_cents": claimed_actual_loss_cents,
        "delay_minutes_used": None,
        "tier_selected": None,
        "gross_segment_payout_cents": 0,
        "final_segment_payout_cents": 0,
        "eligibility": None,
    }
    db.stamp_create(seg)
    db.claim_segments[seg["id"]] = seg
    return seg


# ---------- Create claim ----------

@bp.post("/insurers/<insurer_id>/policies/<policy_id>/claims")
@require_roles("ClaimsReviewer", "PolicyAdmin")
def create_claim(insurer_id: str, policy_id: str):
    get_insurer_or_404(insurer_id)
    policy = get_policy_or_404(insurer_id, policy_id)
    body = get_json_body()

    ticket_ids = require_field(body, "ticket_ids", type_=list)
    if not ticket_ids:
        raise_api_error(ERR_INVALID_REQUEST, "ticket_ids must be non-empty.")
    # Optional per-segment input. Two accepted shapes (PRD §3.6 names the
    # field but does not pin the request format):
    #   (a) top-level parallel array `claimed_actual_loss_cents: [int, ...]`
    #   (b) `segments: [{"ticket_id": "...", "claimed_actual_loss_cents": int}, ...]`
    claimed_losses = optional_field(body, "claimed_actual_loss_cents", default=None, type_=list)
    segments_input = optional_field(body, "segments", default=None, type_=list)
    # Build a lookup from ticket_id -> claimed_actual_loss_cents from segments_input.
    losses_by_ticket: dict = {}
    if isinstance(segments_input, list):
        for s in segments_input:
            if not isinstance(s, dict):
                continue
            tid = s.get("ticket_id")
            v = s.get("claimed_actual_loss_cents")
            if isinstance(tid, str) and isinstance(v, int) and not isinstance(v, bool) and v >= 0:
                losses_by_ticket[tid] = v

    tickets = []
    for tid in ticket_ids:
        if not isinstance(tid, str):
            raise_api_error(ERR_INVALID_REQUEST, "ticket_ids must be strings.")
        t = db.tickets.get(tid)
        if not t or t.get("insurer_id") != insurer_id:
            raise_api_error(ERR_NOT_FOUND, f"Ticket {tid} not found.")
        tickets.append(t)

    # All tickets must be ATTACHED/CHANGED and bound to this policy for auto-match
    bound_to_policy = all(t.get("policy_id") == policy_id and t.get("status") in ("ATTACHED", "CHANGED")
                          for t in tickets)

    claim = {
        "id": gen_id(),
        "policy_id": policy_id,
        "insurer_id": insurer_id,
        "ticket_ids": list(ticket_ids),
        "review_status": "MATCHED" if bound_to_policy else "PENDING_MATCH",
        "payout_status": "NOT_PAYABLE",
        "estimated_payout_cents": 0,
        "final_payout_cents": 0,
        "rejection_reason": None,
        "payout_batch_id": None,
        "assigned_reviewer_id": None,
        "assigned_approver_id": None,
        "payout_operator_id": None,
        "segment_ids": [],
    }
    db.stamp_create(claim)
    db.claims[claim["id"]] = claim

    # Create one segment per ticket
    for idx, t in enumerate(tickets):
        loss = 0
        # Prefer segments-array (by ticket_id) when provided.
        if t["id"] in losses_by_ticket:
            loss = losses_by_ticket[t["id"]]
        elif isinstance(claimed_losses, list) and idx < len(claimed_losses):
            v = claimed_losses[idx]
            if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
                loss = v
        seg = _create_segment(claim, t, claimed_actual_loss_cents=loss)
        claim["segment_ids"].append(seg["id"])

    # Auto-rejection cascade if a referenced ticket is REFUNDED → review_status = REJECTED, MATCHING_FAILED
    if any(t.get("status") == "REFUNDED" for t in tickets):
        claim["review_status"] = "REJECTED"
        claim["rejection_reason"] = "MATCHING_FAILED"

    db.stamp_update(claim)
    append_audit(insurer_id, "CLAIM", claim["id"], "STATUS_CHANGE",
                 {"to": claim["review_status"], "trigger": "create_claim"})

    return jsonify(success_response(_serialize_claim(claim))), 201


# ---------- Get / list ----------

@bp.get("/insurers/<insurer_id>/claims/<claim_id>")
@require_roles("Any")
def get_claim(insurer_id: str, claim_id: str):
    get_insurer_or_404(insurer_id)
    c = get_claim_or_404(insurer_id, claim_id)
    return jsonify(success_response(_serialize_claim(c))), 200


@bp.get("/insurers/<insurer_id>/claims")
@require_roles("Any")
def list_claims(insurer_id: str):
    get_insurer_or_404(insurer_id)
    limit, offset = parse_pagination()
    policy_id = request.args.get("policy_id")
    flight_id = request.args.get("flight_id")
    review_status = request.args.get("review_status")
    payout_status = request.args.get("payout_status")

    items = [c for c in db.claims.values() if c.get("insurer_id") == insurer_id]
    if policy_id is not None:
        items = [c for c in items if c.get("policy_id") == policy_id]
    if review_status is not None:
        items = [c for c in items if c.get("review_status") == review_status]
    if payout_status is not None:
        items = [c for c in items if c.get("payout_status") == payout_status]
    if flight_id is not None:
        filtered = []
        for c in items:
            for sid in c.get("segment_ids", []):
                seg = db.claim_segments.get(sid)
                if seg and seg.get("flight_id") == flight_id:
                    filtered.append(c)
                    break
        items = filtered

    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return jsonify(list_response([_serialize_claim(c) for c in page], limit, offset, total)), 200


# ---------- Submit review ----------

@bp.post("/insurers/<insurer_id>/claims/<claim_id>/submit_review")
@require_roles("ClaimsReviewer")
def submit_review(insurer_id: str, claim_id: str):
    get_insurer_or_404(insurer_id)
    c = get_claim_or_404(insurer_id, claim_id)
    body = get_json_body()
    check_version(body, c)
    assigned_reviewer_id = require_field(body, "assigned_reviewer_id", type_=str)

    # State check
    if c["review_status"] != "MATCHED":
        raise_api_error(ERR_INVALID_STATE,
                        f"Claim is in review_status {c['review_status']}; cannot submit.")

    policy = db.policies[c["policy_id"]]

    # Priority order: ticket binding (12) > flight finalization (7) > waiting period (8)
    # But spec orders: flight finalization before waiting before ticket-not-bound? Let's follow scaffold:
    # priority 7 = flight finalization, 8 = waiting period, 12 = ticket binding.

    # Flight finalisation (priority 7)
    for sid in c["segment_ids"]:
        seg = db.claim_segments[sid]
        flight = db.flights[seg["flight_id"]]
        if flight["status"] not in ("LANDED", "CANCELLED", "DIVERTED", "RETURNED"):
            raise_api_error(ERR_FLIGHT_NOT_FINALIZED,
                            f"Flight {flight['id']} is not finalised (status {flight['status']}).")

    # Waiting period (priority 8) — checked per segment
    for sid in c["segment_ids"]:
        seg = db.claim_segments[sid]
        ticket = db.tickets[seg["ticket_id"]]
        if ticket["scheduled_departure_epoch_ms"] < (
            policy["effective_from_epoch_ms"] + (policy.get("waiting_period_ms", 0) or 0)
        ):
            raise_api_error(ERR_WAITING_PERIOD_NOT_MET,
                            "Waiting period not met for at least one segment.")

    # Ticket binding (priority 12)
    for sid in c["segment_ids"]:
        seg = db.claim_segments[sid]
        ticket = db.tickets[seg["ticket_id"]]
        if ticket["status"] not in ("ATTACHED", "CHANGED"):
            raise_api_error(ERR_TICKET_NOT_BOUND,
                            f"Ticket {ticket['id']} is in status {ticket['status']}.")

    # Compute eligibility/gross/tier/delay per segment
    recompute_claim_segments(c)
    c["assigned_reviewer_id"] = assigned_reviewer_id
    c["review_status"] = "UNDER_REVIEW"
    db.stamp_update(c)
    append_audit(insurer_id, "CLAIM", c["id"], "STATUS_CHANGE",
                 {"from": "MATCHED", "to": "UNDER_REVIEW"})
    return jsonify(success_response(_serialize_claim(c))), 200


# ---------- Return to match ----------

@bp.post("/insurers/<insurer_id>/claims/<claim_id>/return_to_match")
@require_roles("ClaimsReviewer")
def return_to_match(insurer_id: str, claim_id: str):
    get_insurer_or_404(insurer_id)
    c = get_claim_or_404(insurer_id, claim_id)
    body = get_json_body()
    check_version(body, c)

    if c["review_status"] != "UNDER_REVIEW":
        raise_api_error(ERR_INVALID_STATE, f"Claim is not UNDER_REVIEW.")

    if c.get("assigned_reviewer_id") != g.user_id:
        raise_api_error(ERR_FORBIDDEN_FOR_ROLE,
                        "Only the assigned reviewer can return the claim to MATCHED.")

    c["review_status"] = "MATCHED"
    c["assigned_reviewer_id"] = None
    db.stamp_update(c)
    append_audit(insurer_id, "CLAIM", c["id"], "STATUS_CHANGE",
                 {"from": "UNDER_REVIEW", "to": "MATCHED"})
    return jsonify(success_response(_serialize_claim(c))), 200


# ---------- Approve ----------

@bp.post("/insurers/<insurer_id>/claims/<claim_id>/approve")
@require_roles("ClaimsApprover")
def approve_claim(insurer_id: str, claim_id: str):
    get_insurer_or_404(insurer_id)
    c = get_claim_or_404(insurer_id, claim_id)
    body = get_json_body()
    check_version(body, c)
    assigned_approver_id = require_field(body, "assigned_approver_id", type_=str)

    # SoD: approver != reviewer (priority 5 — comes before state check per scaffold validation order)
    if c.get("assigned_reviewer_id") and assigned_approver_id == c["assigned_reviewer_id"]:
        raise_api_error(ERR_SOD_VIOLATION, "Approver cannot equal reviewer.")
    # The body's assigned_approver_id should equal the caller's X-User-ID
    if assigned_approver_id != g.user_id:
        raise_api_error(ERR_INVALID_REQUEST, "assigned_approver_id must equal X-User-ID.")
    if g.user_id == c.get("assigned_reviewer_id"):
        raise_api_error(ERR_SOD_VIOLATION, "Caller cannot approve a claim they reviewed.")

    if c["review_status"] != "UNDER_REVIEW":
        raise_api_error(ERR_INVALID_STATE,
                        f"Claim is in review_status {c['review_status']}; cannot approve.")

    policy = db.policies[c["policy_id"]]
    if policy["status"] != "ACTIVE":
        raise_api_error(ERR_POLICY_INACTIVE, "Parent policy is not ACTIVE.")

    # Eligibility — every segment must be ELIGIBLE
    eligible = []
    for sid in c["segment_ids"]:
        seg = db.claim_segments[sid]
        if seg["eligibility"] != "ELIGIBLE":
            raise_api_error(ERR_CLAIM_NOT_ELIGIBLE,
                            f"Segment {sid} eligibility is {seg['eligibility']}.")
        eligible.append(seg)

    # Compute estimated payout
    eligible_gross = [s["gross_segment_payout_cents"] for s in eligible]
    sum_gross, capped = combined_payout(
        eligible_gross,
        policy.get("deductible_cents", 0) or 0,
        policy.get("policy_limit_cents", 0) or 0,
    )
    estimated = capped

    # Quota check
    if (policy.get("claim_quota_used_cents", 0) or 0) + estimated > (policy.get("claim_quota_total_cents", 0) or 0):
        raise_api_error(ERR_QUOTA_EXHAUSTED, "Approval would exceed claim quota.")

    c["estimated_payout_cents"] = estimated
    c["assigned_approver_id"] = assigned_approver_id
    c["review_status"] = "APPROVED"
    c["payout_status"] = "PAYABLE"
    db.stamp_update(c)

    # Reserve debit
    append_reserve_adjustment(policy, c["id"], +estimated, "APPROVE_DEBIT")
    db.stamp_update(policy)
    append_audit(insurer_id, "CLAIM", c["id"], "STATUS_CHANGE",
                 {"from": "UNDER_REVIEW", "to": "APPROVED",
                  "estimated_payout_cents": estimated})
    append_audit(insurer_id, "POLICY", policy["id"], "RESERVE_ADJUSTED",
                 {"reason": "APPROVE_DEBIT", "delta_cents": estimated,
                  "balance_after": policy["reserve_balance_cents"]})
    return jsonify(success_response(_serialize_claim(c))), 200


# ---------- Reject ----------

@bp.post("/insurers/<insurer_id>/claims/<claim_id>/reject")
@require_roles("ClaimsReviewer", "ClaimsApprover")
def reject_claim(insurer_id: str, claim_id: str):
    get_insurer_or_404(insurer_id)
    c = get_claim_or_404(insurer_id, claim_id)
    body = get_json_body()
    check_version(body, c)
    rejection_reason = require_field(body, "rejection_reason", type_=str)
    if rejection_reason not in VALID_REJECTION_REASONS:
        raise_api_error(ERR_INVALID_REQUEST, "Invalid rejection_reason.")

    if c["review_status"] != "UNDER_REVIEW":
        raise_api_error(ERR_INVALID_STATE, "Claim is not UNDER_REVIEW.")

    c["review_status"] = "REJECTED"
    c["rejection_reason"] = rejection_reason
    db.stamp_update(c)
    append_audit(insurer_id, "CLAIM", c["id"], "STATUS_CHANGE",
                 {"to": "REJECTED", "rejection_reason": rejection_reason})
    return jsonify(success_response(_serialize_claim(c))), 200


# ---------- Settle ----------

@bp.post("/insurers/<insurer_id>/claims/<claim_id>/settle")
@require_roles("PayoutOperator", "system")
def settle_claim(insurer_id: str, claim_id: str):
    get_insurer_or_404(insurer_id)
    c = get_claim_or_404(insurer_id, claim_id)
    body = get_json_body()
    check_version(body, c)

    # SoD: settler != per-claim approver
    if c.get("assigned_approver_id") and g.user_id == c["assigned_approver_id"]:
        raise_api_error(ERR_SOD_VIOLATION, "Settler cannot equal approver.")

    if c["payout_status"] != "EXECUTING":
        raise_api_error(ERR_INVALID_STATE,
                        f"Claim payout_status is {c['payout_status']}; cannot settle.")

    policy = db.policies[c["policy_id"]]
    estimated = c.get("estimated_payout_cents", 0) or 0
    final_total = estimated  # Pinned: final == estimated in absence of corrections.
    c["final_payout_cents"] = final_total

    # Per-segment pro-ration
    eligible = [db.claim_segments[s] for s in c.get("segment_ids", [])
                if db.claim_segments[s].get("eligibility") == "ELIGIBLE"]
    sum_gross = sum(s.get("gross_segment_payout_cents", 0) or 0 for s in eligible)
    finals = prorate_segments(eligible, final_total, sum_gross)
    for sid, amt in finals.items():
        db.claim_segments[sid]["final_segment_payout_cents"] = amt
        db.stamp_update(db.claim_segments[sid])

    # Reserve release
    append_reserve_adjustment(policy, c["id"], -estimated, "SETTLE_RELEASE")
    policy["claim_quota_used_cents"] = (policy.get("claim_quota_used_cents", 0) or 0) + final_total
    db.stamp_update(policy)

    # Reinsurance allocation
    primary_share, reinsurer_share = reinsurance_waterfall(final_total)
    alloc = {
        "id": gen_id(),
        "claim_id": c["id"],
        "insurer_id": insurer_id,
        "primary_share_cents": primary_share,
        "reinsurer_share_cents": reinsurer_share,
        "pinned_total_cents": final_total,
        "created_at": now_iso_z(),
    }
    db.reinsurance_allocations[alloc["id"]] = alloc

    c["payout_status"] = "PAID"
    db.stamp_update(c)

    # Outbox events: PAYMENT, POLICY_ADMIN, AIRLINE
    for tgt in ("PAYMENT", "POLICY_ADMIN", "AIRLINE"):
        emit_outbox(insurer_id, tgt, "CLAIM_PAID", "CLAIM", c["id"],
                    {"claim_id": c["id"], "amount_cents": final_total})

    append_audit(insurer_id, "CLAIM", c["id"], "PAYOUT_RECORDED",
                 {"final_payout_cents": final_total,
                  "primary_share_cents": primary_share,
                  "reinsurer_share_cents": reinsurer_share})
    append_audit(insurer_id, "POLICY", policy["id"], "RESERVE_ADJUSTED",
                 {"reason": "SETTLE_RELEASE", "delta_cents": -estimated,
                  "balance_after": policy["reserve_balance_cents"]})

    # Update parent batch totals & possible auto SETTLED transition
    if c.get("payout_batch_id"):
        batch = db.payout_batches.get(c["payout_batch_id"])
        if batch:
            batch["total_settled_payout_cents"] = (batch.get("total_settled_payout_cents", 0) or 0) + final_total
            db.stamp_update(batch)
            _maybe_auto_settle_batch(batch)

    return jsonify(success_response(_serialize_claim(c))), 200


def _maybe_auto_settle_batch(batch: dict):
    if batch.get("execution_phase") != "EXECUTING":
        return
    if batch.get("exception_claim_ids"):
        return
    for cid in batch.get("claim_ids", []):
        cc = db.claims.get(cid)
        if not cc or cc.get("payout_status") not in ("PAID", "REVERSED"):
            return
    prev = batch["execution_phase"]
    batch["execution_phase"] = "SETTLED"
    db.stamp_update(batch)
    append_audit(batch["insurer_id"], "PAYOUT_BATCH", batch["id"], "STATUS_CHANGE",
                 {"from": prev, "to": "SETTLED"})


# ---------- Mark exception ----------

@bp.post("/insurers/<insurer_id>/claims/<claim_id>/mark_exception")
@require_roles("PayoutOperator", "system")
def mark_exception(insurer_id: str, claim_id: str):
    get_insurer_or_404(insurer_id)
    c = get_claim_or_404(insurer_id, claim_id)
    body = get_json_body()
    check_version(body, c)

    if c["payout_status"] != "EXECUTING":
        raise_api_error(ERR_INVALID_STATE, f"Claim payout_status is {c['payout_status']}.")

    c["payout_status"] = "PAYABLE"
    db.stamp_update(c)

    if c.get("payout_batch_id"):
        batch = db.payout_batches.get(c["payout_batch_id"])
        if batch:
            ex = list(batch.get("exception_claim_ids") or [])
            if c["id"] not in ex:
                ex.append(c["id"])
            batch["exception_claim_ids"] = ex
            if batch.get("execution_phase") == "EXECUTING":
                batch["execution_phase"] = "EXCEPTIONS"
            db.stamp_update(batch)

    append_audit(insurer_id, "CLAIM", c["id"], "STATUS_CHANGE",
                 {"to": "PAYABLE", "trigger": "mark_exception",
                  "reason": body.get("reason")})
    return jsonify(success_response(_serialize_claim(c))), 200


# ---------- Reverse ----------

@bp.post("/insurers/<insurer_id>/claims/<claim_id>/reverse")
@require_roles("ClaimsAdmin")
def reverse_claim(insurer_id: str, claim_id: str):
    get_insurer_or_404(insurer_id)
    c = get_claim_or_404(insurer_id, claim_id)
    body = get_json_body()
    check_version(body, c)

    if c["payout_status"] != "PAID":
        raise_api_error(ERR_INVALID_STATE, "Only PAID claims can be reversed.")

    policy = db.policies[c["policy_id"]]
    final_payout = c.get("final_payout_cents", 0) or 0
    append_reserve_adjustment(policy, c["id"], +final_payout, "REVERSE_REBUILD")
    policy["claim_quota_used_cents"] = max(0, (policy.get("claim_quota_used_cents", 0) or 0) - final_payout)
    db.stamp_update(policy)

    c["payout_status"] = "REVERSED"
    db.stamp_update(c)

    emit_outbox(insurer_id, "BANKING", "CLAIM_REVERSED", "CLAIM", c["id"],
                {"claim_id": c["id"], "amount_cents": final_payout})

    append_audit(insurer_id, "CLAIM", c["id"], "STATUS_CHANGE",
                 {"to": "REVERSED", "amount_cents": final_payout})
    append_audit(insurer_id, "POLICY", policy["id"], "RESERVE_ADJUSTED",
                 {"reason": "REVERSE_REBUILD", "delta_cents": final_payout,
                  "balance_after": policy["reserve_balance_cents"]})
    return jsonify(success_response(_serialize_claim(c))), 200
