"""Business services: serializers, derived-field reconciliation, calculations,
state-machine side effects, and the audit trail.

Constants (PRD §3 / scaffold §1.4):
  REFERRAL_RESPONSE_DAYS = 15
  RCA_DEADLINE_DAYS = 30
  RETENTION_YEARS = 5
  RESTITUTION_AUTHORITY_CAP_CENTS = 2500000
  HIGH_VALUE_CLAIM_CENTS = 1000000
  EW_MIN_COUNT = 3, EW_RATE_BPS = 5000, EW_OPEN_COUNT = 10
  POSTURE_WATCH_SUBSTANTIATED = 3, POSTURE_FREEZE_SUBSTANTIATED = 5
"""
import uuid
from datetime import timedelta

from flask import g

from db import Rec, store
from errors import ApiError, ERR_NOT_FOUND
from timeutil import business_days_between, iso, trunc_days, floor_days

REFERRAL_RESPONSE_DAYS = 15
RCA_DEADLINE_DAYS = 30
RETENTION_YEARS = 5
RESTITUTION_AUTHORITY_CAP_CENTS = 2500000
HIGH_VALUE_CLAIM_CENTS = 1000000
EW_MIN_COUNT = 3
EW_RATE_BPS = 5000
EW_OPEN_COUNT = 10
POSTURE_WATCH_SUBSTANTIATED = 3
POSTURE_FREEZE_SUBSTANTIATED = 5

OPEN_STATUSES = {"INTAKE", "TRIAGED", "INVESTIGATING", "RESPONSE_DRAFTED", "RESPONSE_QA", "REOPENED"}
TERMINAL_STATUSES = {"RESOLVED", "WITHDRAWN"}


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Lookup helpers (existence checks -> ERR_NOT_FOUND, path ids left-to-right)
# ---------------------------------------------------------------------------

def _lookup(table, rid, label):
    rec = table.get(rid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, f"{label} '{rid}' does not exist.", 404)
    return rec


def get_product(pid):
    return _lookup(store.products, pid, "Product")


def get_channel(cid):
    return _lookup(store.channels, cid, "Channel")


def get_category(cid):
    return _lookup(store.categories, cid, "TaxonomyCategory")


def get_template(tid):
    return _lookup(store.templates, tid, "ResponseTemplate")


def get_complaint(cid):
    return _lookup(store.complaints, cid, "Complaint")


def get_referral(rid):
    return _lookup(store.referrals, rid, "RegulatoryReferral")


def get_rca(rid):
    return _lookup(store.rcas, rid, "RootCauseAnalysis")


def get_decision(did):
    return _lookup(store.decisions, did, "RemediationDecision")


def get_review(rid):
    return _lookup(store.reviews, rid, "QualityReview")


def get_escalation(eid):
    return _lookup(store.escalations, eid, "EscalationCase")


def product_by_code(code):
    rec = store.product_by_code.get(code)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, f"Product code '{code}' does not resolve.", 404)
    return rec


def channel_by_code(code):
    rec = store.channel_by_code.get(code)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, f"Channel code '{code}' does not resolve.", 404)
    return rec


def category_by_code(code):
    rec = store.category_by_code.get(code)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, f"Taxonomy category code '{code}' does not resolve.", 404)
    return rec


def template_by_key(key):
    rec = store.template_by_key.get(key)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, f"Response template key '{key}' does not resolve.", 404)
    return rec


# ---------------------------------------------------------------------------
# Record construction / mutation bookkeeping
# ---------------------------------------------------------------------------

def fresh_rec(**fields):
    """Create a record with the full common set: id, created_at, updated_at, version=1."""
    now = store.now()
    rec = Rec(_seq=store.next_seq(), id=new_id(), created_at=now, updated_at=now, version=1, **fields)
    return rec


def fresh_audit_rec(**fields):
    """Create an append-only/point-in-time record: id + created_at only (no updated_at/version)."""
    now = store.now()
    rec = Rec(_seq=store.next_seq(), id=new_id(), created_at=now, **fields)
    return rec


def touch(rec):
    """§2.4: every mutation refreshes updated_at to the logical clock and bumps version."""
    rec.updated_at = store.now()
    rec.version += 1
    rec._touch_seq = store.next_seq()


def append_event(complaint_id, event_type, payload):
    """Append an IntakeEvent to the complaint's tamper-evident audit trail."""
    ev = fresh_audit_rec(
        complaint_id=complaint_id,
        event_type=event_type,
        actor_user_id=g.user_id,
        actor_role=g.role,
        payload=payload,
        event_at=store.now(),
    )
    store.events[ev.id] = ev
    return ev


# ---------------------------------------------------------------------------
# Derived-field reconciliation and calculations
# ---------------------------------------------------------------------------

def latest_rca(complaint_id):
    """The latest RCA of a complaint (greatest creation sequence). A superseded
    RCA always has a newer sibling, so the latest is never SUPERSEDED."""
    cands = [r for r in store.rcas.values() if r.complaint_id == complaint_id]
    if not cands:
        return None
    return max(cands, key=lambda r: r._seq)


def recompute_posture(product):
    """product_posture calculation: refresh aggregates first, then thresholds.

    open_complaint_count = complaints in non-terminal pipeline statuses.
    substantiated_count_90d = complaints whose latest RCA is a COMPLETED
    SUBSTANTIATED analysis and whose received_at is within the trailing
    90 calendar days of the logical clock.
    """
    now = store.now()
    comps = [c for c in store.complaints.values() if c.product_code == product.product_code]
    product.open_complaint_count = sum(1 for c in comps if c.status in OPEN_STATUSES)
    cutoff = now - timedelta(days=90)
    sub = 0
    for c in comps:
        if c.received_at >= cutoff:
            r = latest_rca(c.id)
            if r is not None and r.status == "COMPLETED" and r.verdict == "SUBSTANTIATED":
                sub += 1
    product.substantiated_count_90d = sub
    if sub >= POSTURE_FREEZE_SUBSTANTIATED:
        product.posture = "FROZEN"
    elif product.early_warning_active or sub >= POSTURE_WATCH_SUBSTANTIATED:
        product.posture = "WATCH"
    else:
        product.posture = "OPEN"


def recompute_restitution(complaint):
    """approved = sum over decisions in APPROVED or PAID; paid = sum over PAID."""
    decs = [d for d in store.decisions.values() if d.complaint_id == complaint.id]
    complaint.approved_restitution_cents = sum(
        d.restitution_amount_cents for d in decs if d.status in ("APPROVED", "PAID")
    )
    complaint.paid_restitution_cents = sum(
        d.restitution_amount_cents for d in decs if d.status == "PAID"
    )


def compute_restitution_amount(line_items):
    """Pinned rounding order: floor per line item, THEN sum (PRD §3.6)."""
    total = 0
    for li in line_items:
        rate = li.get("rounding_rate_bps", 10000)
        total += (li["amount_cents"] * rate) // 10000
    return total


def latest_completed_review(complaint_id):
    cands = [
        r for r in store.reviews.values()
        if r.complaint_id == complaint_id and r.status == "COMPLETED"
    ]
    if not cands:
        return None
    return max(cands, key=lambda r: getattr(r, "_touch_seq", r._seq))


def recompute_timeliness_score(complaint):
    """response_timeliness_score (PRD §3.8): null until first referral submission.

    days_to_respond = floor((submitted_at - received_at) / 86400)
    base = max(0, 100 - 5 * days_to_respond)
    multiplier = 0.5 if LATE else 1.0; floor(base * multiplier) BEFORE bonuses
    qa_bonus = +10 / -15 / 0 from latest COMPLETED QualityReview
    high_value_bonus = +5 when claimed_loss_cents >= 1000000
    score = clamp(min(100, floored + bonuses), 0)
    """
    refs = [
        r for r in store.referrals.values()
        if r.complaint_id == complaint.id and r.submitted_at is not None
    ]
    if not refs:
        complaint.timeliness_score = None
        return
    ref = max(refs, key=lambda r: getattr(r, "_touch_seq", r._seq))
    days_to_respond = floor_days(ref.submitted_at - complaint.received_at)
    base = max(0, 100 - 5 * days_to_respond)
    if ref.timeliness == "LATE":
        base = base // 2  # floor(base * 0.5), base is a non-negative integer
    review = latest_completed_review(complaint.id)
    if review is None:
        qa_bonus = 0
    elif review.outcome == "PASS":
        qa_bonus = 10
    else:
        qa_bonus = -15
    high_value_bonus = 5 if complaint.claimed_loss_cents >= HIGH_VALUE_CLAIM_CENTS else 0
    score = min(100, base + qa_bonus + high_value_bonus)
    complaint.timeliness_score = max(0, score)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def ser_product(p):
    return {
        "id": p.id,
        "product_code": p.product_code,
        "display_name": p.display_name,
        "posture": p.posture,
        "open_complaint_count": p.open_complaint_count,
        "substantiated_count_90d": p.substantiated_count_90d,
        "early_warning_active": p.early_warning_active,
        "created_at": iso(p.created_at),
        "updated_at": iso(p.updated_at),
        "version": p.version,
    }


def ser_channel(c):
    return {
        "id": c.id,
        "channel_code": c.channel_code,
        "display_name": c.display_name,
        "is_regulator_portal": c.is_regulator_portal,
        "created_at": iso(c.created_at),
        "updated_at": iso(c.updated_at),
        "version": c.version,
    }


def ser_category(c):
    return {
        "id": c.id,
        "category_code": c.category_code,
        "parent_category_code": c.parent_category_code,
        "retired": c.retired,
        "created_at": iso(c.created_at),
        "updated_at": iso(c.updated_at),
        "version": c.version,
    }


def ser_template(t):
    return {
        "id": t.id,
        "template_key": t.template_key,
        "channel_code": t.channel_code,
        "category_code": t.category_code,
        "body": t.body,
        "status": t.status,
        "created_at": iso(t.created_at),
        "updated_at": iso(t.updated_at),
        "version": t.version,
    }


def ser_complaint(c):
    """Computed ages are evaluated at read time (PRD §3.5)."""
    end_at = c.resolved_at if c.status in TERMINAL_STATUSES else store.now()
    return {
        "id": c.id,
        "complainant_ref": c.complainant_ref,
        "channel_code": c.channel_code,
        "product_code": c.product_code,
        "category_code": c.category_code,
        "received_at": iso(c.received_at),
        "narrative": c.narrative,
        "claimed_loss_cents": c.claimed_loss_cents,
        "status": c.status,
        "response_text": c.response_text,
        "response_template_key": c.response_template_key,
        "resolved_at": iso(c.resolved_at) if c.resolved_at is not None else None,
        "approved_restitution_cents": c.approved_restitution_cents,
        "paid_restitution_cents": c.paid_restitution_cents,
        "days_open_business": business_days_between(c.received_at, end_at),
        "days_open_calendar": trunc_days(end_at - c.received_at),
        "timeliness_score": c.timeliness_score,
        "owner_user_id": c.owner_user_id,
        "retention_purge_at": iso(c.retention_purge_at) if c.retention_purge_at is not None else None,
        "created_at": iso(c.created_at),
        "updated_at": iso(c.updated_at),
        "version": c.version,
    }


def ser_event(e):
    return {
        "id": e.id,
        "complaint_id": e.complaint_id,
        "event_type": e.event_type,
        "actor_user_id": e.actor_user_id,
        "actor_role": e.actor_role,
        "payload": e.payload,
        "event_at": iso(e.event_at),
        "created_at": iso(e.created_at),
    }


def ser_referral(r):
    return {
        "id": r.id,
        "complaint_id": r.complaint_id,
        "portal_ref": r.portal_ref,
        "received_via_portal_at": iso(r.received_via_portal_at),
        "response_due_at": iso(r.response_due_at),
        "submitted_at": iso(r.submitted_at) if r.submitted_at is not None else None,
        "timeliness": r.timeliness,
        "status": r.status,
        "response_text": r.response_text,
        "created_at": iso(r.created_at),
        "updated_at": iso(r.updated_at),
        "version": r.version,
    }


def ser_rca(r):
    return {
        "id": r.id,
        "complaint_id": r.complaint_id,
        "verdict": r.verdict,
        "linked_product_code": r.linked_product_code,
        "process_step": r.process_step,
        "completed_at": iso(r.completed_at) if r.completed_at is not None else None,
        "status": r.status,
        "created_at": iso(r.created_at),
        "updated_at": iso(r.updated_at),
        "version": r.version,
    }


def ser_decision(d):
    return {
        "id": d.id,
        "complaint_id": d.complaint_id,
        "decision_type": d.decision_type,
        "line_items": d.line_items,
        "restitution_amount_cents": d.restitution_amount_cents,
        "drafted_by_user_id": d.drafted_by_user_id,
        "approved_by_user_id": d.approved_by_user_id,
        "status": d.status,
        "created_at": iso(d.created_at),
        "updated_at": iso(d.updated_at),
        "version": d.version,
    }


def ser_review(r):
    return {
        "id": r.id,
        "complaint_id": r.complaint_id,
        "reviewer_user_id": r.reviewer_user_id,
        "window_start_at": iso(r.window_start_at),
        "window_end_at": iso(r.window_end_at),
        "outcome": r.outcome,
        "status": r.status,
        "created_at": iso(r.created_at),
        "updated_at": iso(r.updated_at),
        "version": r.version,
    }


def ser_escalation(e):
    return {
        "id": e.id,
        "complaint_id": e.complaint_id,
        "escalation_tier": e.escalation_tier,
        "reason": e.reason,
        "raised_by_user_id": e.raised_by_user_id,
        "status": e.status,
        "created_at": iso(e.created_at),
        "updated_at": iso(e.updated_at),
        "version": e.version,
    }


def ser_snapshot(s):
    return {
        "id": s.id,
        "product_code": s.product_code,
        "period_start_at": iso(s.period_start_at),
        "period_end_at": iso(s.period_end_at),
        "complaint_count": s.complaint_count,
        "substantiated_count": s.substantiated_count,
        "substantiation_rate_bps": s.substantiation_rate_bps,
        "early_warning": s.early_warning,
        "evaluated_at": iso(s.evaluated_at),
        "created_at": iso(s.created_at),
    }


def paged(records, serializer, limit, offset):
    """Sort by created_at ascending (creation sequence tiebreak), then paginate."""
    ordered = sorted(records, key=lambda r: (r.created_at, r._seq))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [serializer(r) for r in page], total
