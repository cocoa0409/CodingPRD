"""Audit log, clock-advance, settlement-sweep, event-emit endpoints."""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict

from flask import Blueprint, jsonify, request

from auth import get_caller, require_roles
from clock import clock, format_iso, parse_iso
from errors import ERR_VALIDATION, raise_err
from request_body import get_json_body, paginate, parse_pagination, require_field
from response import empty_success, success_array
from services.cascade import (
    cascade_company_expired,
    take_posting_off_shelf,
)
from store import append_audit, bump, store


bp = Blueprint("audit_test_drivers", __name__)


@bp.get("/recruitment/audit-events")
def list_audit_events():
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin"])
    limit, offset = parse_pagination()
    subject_entity = request.args.get("subject_entity")
    subject_id = request.args.get("subject_id")
    event_kind = request.args.get("event_kind")
    rows = list(store.audit_events)
    if subject_entity is not None:
        rows = [r for r in rows if r.get("subject_entity") == subject_entity]
    if subject_id is not None:
        rows = [r for r in rows if r.get("subject_id") == subject_id]
    if event_kind is not None:
        rows = [r for r in rows if r.get("event_kind") == event_kind]
    rows.sort(key=lambda r: r.get("created_at", ""))
    page, total = paginate(rows, limit, offset)
    body_out, status = success_array(page, limit=limit, offset=offset, total_count=total)
    return jsonify(body_out), status


def _run_auto_transitions():
    """Run every auto-transition whose precondition is now satisfied.

    - Company VERIFIED whose reverification_due_at has been reached → EXPIRED
    - JobPosting LIVE whose listed_at + 30 days has been reached → EXPIRED
    - InterviewRound SCHEDULED whose scheduled_end_at has been reached → FEEDBACK_PENDING
    - Offer ISSUED whose acceptance_deadline_at has been reached → EXPIRED
    """
    now = clock.now()
    # Companies
    for c in list(store.companies.values()):
        if c.get("verification_status") == "VERIFIED" and c.get("reverification_due_at"):
            try:
                due = parse_iso(c["reverification_due_at"])
            except Exception:
                continue
            if now >= due:
                from_state = c["verification_status"]
                c["verification_status"] = "EXPIRED"
                c["posting_quota_limit"] = 0
                bump(c)
                append_audit(
                    subject_entity="Company",
                    subject_id=c["id"],
                    event_kind="STATE_TRANSITION",
                    from_state=from_state,
                    to_state="EXPIRED",
                    actor_role="system",
                    actor_user_id="system",
                )
                cascade_company_expired(c)
    # JobPostings
    for p in list(store.job_postings.values()):
        if p.get("posting_status") == "LIVE" and p.get("listed_at"):
            try:
                listed = parse_iso(p["listed_at"])
            except Exception:
                continue
            if now >= listed + timedelta(days=30):
                # Take off-shelf with terminal state EXPIRED
                take_posting_off_shelf(p, to_state="EXPIRED")
    # InterviewRounds
    for r in list(store.interview_rounds.values()):
        if r.get("round_status") == "SCHEDULED" and r.get("scheduled_end_at"):
            try:
                end = parse_iso(r["scheduled_end_at"])
            except Exception:
                continue
            if now >= end:
                r["round_status"] = "FEEDBACK_PENDING"
                bump(r)
                append_audit(
                    subject_entity="InterviewRound",
                    subject_id=r["id"],
                    event_kind="STATE_TRANSITION",
                    from_state="SCHEDULED",
                    to_state="FEEDBACK_PENDING",
                    actor_role="system",
                    actor_user_id="system",
                )
    # Offers — strictly past deadline auto-expires; equality is left for
    # the accept-path priority-12 check (PRD §2.7 priority 12 says equality
    # at accept yields ERR_OFFER_EXPIRED, which requires the offer still be
    # ISSUED at exact equality).
    for o in list(store.offers.values()):
        if o.get("offer_status") == "ISSUED" and o.get("acceptance_deadline_at"):
            try:
                dline = parse_iso(o["acceptance_deadline_at"])
            except Exception:
                continue
            if now > dline:
                o["offer_status"] = "EXPIRED"
                o["expired_at"] = format_iso(now)
                bump(o)
                append_audit(
                    subject_entity="Offer",
                    subject_id=o["id"],
                    event_kind="STATE_TRANSITION",
                    from_state="ISSUED",
                    to_state="EXPIRED",
                    actor_role="system",
                    actor_user_id="system",
                )


@bp.post("/recruitment/_clock/advance")
def advance_clock():
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin"])
    body = get_json_body()
    to_iso = require_field(body, "to_iso8601")
    try:
        target = parse_iso(to_iso)
    except Exception:
        raise_err(ERR_VALIDATION, "to_iso8601 must be a valid ISO8601 string.")
    clock.set(target)
    _run_auto_transitions()
    body_out, status = empty_success()
    return jsonify(body_out), status


@bp.post("/recruitment/_settlement-sweep/run")
def run_settlement_sweep():
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin"])
    now = clock.now()
    # Process in chronological order (created_at ASC).
    records = sorted(
        store.commission_records.values(), key=lambda r: r.get("created_at", "")
    )
    for rec in records:
        if rec.get("settlement_status") != "ACCRUED":
            continue
        try:
            created = parse_iso(rec["created_at"])
        except Exception:
            continue
        age_days = (now - created).total_seconds() / 86400.0
        if age_days >= 30:
            rec["settlement_status"] = "SETTLED"
            rec["settled_at"] = format_iso(now)
            rec["net_settlement_cents"] = int(rec["gross_commission_cents"]) - int(
                rec["tax_withheld_cents"]
            )
            append_audit(
                subject_entity="CommissionRecord",
                subject_id=rec["id"],
                event_kind="COMMISSION_SETTLED",
                from_state=None,
                to_state=None,
                actor_role="system",
                actor_user_id="system",
            )
    body_out, status = empty_success()
    return jsonify(body_out), status


@bp.post("/recruitment/_events/emit")
def emit_event():
    caller = get_caller()
    require_roles(caller, ["PlatformAdmin"])
    body = get_json_body()
    system = require_field(body, "system")
    kind = require_field(body, "kind")
    subject_id = require_field(body, "subject_id")
    if not isinstance(system, str) or not system:
        raise_err(ERR_VALIDATION, "system must be a non-empty string.")
    if not isinstance(kind, str) or not kind:
        raise_err(ERR_VALIDATION, "kind must be a non-empty string.")
    if not isinstance(subject_id, str) or not subject_id:
        raise_err(ERR_VALIDATION, "subject_id must be a non-empty string.")
    key = (system, kind, subject_id)
    if key in store.processed_external_events:
        # Idempotent — no state regression on duplicate.
        body_out, status = empty_success()
        return jsonify(body_out), status
    store.processed_external_events.add(key)
    # We do not regress any subject state on an external event; just log it
    # as a state-transition audit row with null states (the audit list filter
    # may pick it up via subject_id).
    append_audit(
        subject_entity="Application",  # placeholder; subject_entity not strictly defined here
        subject_id=subject_id,
        event_kind="STATE_TRANSITION",
        from_state=None,
        to_state=None,
        actor_role=caller.role,
        actor_user_id=caller.user_id,
    )
    body_out, status = empty_success()
    return jsonify(body_out), status
