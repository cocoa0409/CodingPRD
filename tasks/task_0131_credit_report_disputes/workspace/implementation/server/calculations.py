"""Calculation rules per SCAFFOLD §1.3 and PRD §3.5–§3.8.

Implements:
  * fico_calculation        (PRD §3.5)
  * dispute_risk_score      (PRD §3.6)
  * free_report_grant       (PRD §3.6)
  * deadline_day            (PRD §3.8)
  * posture                 (PRD §3.7)
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from .clock import clock
from .store import store


# ----------------------------------------------------------------------
# FICO
# ----------------------------------------------------------------------

PAYMENT_SCORES = {
    "CURRENT": 100,
    "LATE_30": 70,
    "LATE_60": 40,
    "LATE_90": 20,
    "CHARGE_OFF": 0,
    "COLLECTION": 0,
}

PAYMENT_HISTORY_WEIGHT = 0.35
UTILIZATION_WEIGHT = 0.30
AGE_WEIGHT = 0.15
MIX_WEIGHT = 0.10
RECENT_INQUIRIES_WEIGHT = 0.10
PER_ITEM_NOMINAL_LIMIT_CENTS = 1_000_000  # $10,000 per-item limit


def _round_half_up(value: float) -> int:
    """Round half away from zero (round_half_up), then to int."""
    d = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(d)


def _tradelines_for_report(credit_report_id: str) -> list[dict[str, Any]]:
    return [
        ti
        for ti in store.tradeline_items.values()
        if ti["credit_report_id"] == credit_report_id
    ]


def _accepted_inquiry_count(credit_report_id: str) -> int:
    return sum(
        1
        for hi in store.hard_inquiries.values()
        if hi["credit_report_id"] == credit_report_id and hi["outcome"] == "ACCEPTED"
    )


def compute_fico(
    credit_report_id: str,
    *,
    overrides: dict[str, dict[str, Any]] | None = None,
    extra_deleted_ids: set[str] | None = None,
) -> int:
    """Compute the FICO score per PRD §3.5.

    overrides:           map of tradeline_item_id -> partial dict applied on top
                         of the stored row (used for the projected variant).
    extra_deleted_ids:   tradeline_item_ids to treat as if payment_status=DELETED.
    """
    overrides = overrides or {}
    extra_deleted_ids = extra_deleted_ids or set()

    all_items = _tradelines_for_report(credit_report_id)
    # Apply overrides + deletions to produce the working snapshot.
    snapshot: list[dict[str, Any]] = []
    for item in all_items:
        merged = dict(item)
        if item["id"] in overrides:
            merged.update(overrides[item["id"]])
        if item["id"] in extra_deleted_ids:
            merged["payment_status"] = "DELETED"
        snapshot.append(merged)

    # Working set T: non-DELETED items.
    T = [ti for ti in snapshot if ti["payment_status"] != "DELETED"]

    # Payment-history component (mean of per-item payment scores).
    if not T:
        payment_history = 100.0
    else:
        payment_history = sum(PAYMENT_SCORES[ti["payment_status"]] for ti in T) / len(T)

    # Utilization component.
    if not T:
        utilization_score = 100.0
    else:
        total_balance = sum(ti["balance_cents"] for ti in T)
        denom = max(1, len(T) * PER_ITEM_NOMINAL_LIMIT_CENTS)
        util_pct = min(100.0, total_balance / denom * 100.0)
        utilization_score = max(0.0, 100.0 - util_pct)

    # Age component (constant 100 per scaffold v1).
    age_score = 100.0

    # Mix component.
    mix_score = 50.0 if len(T) == 1 else 100.0

    # Recent-inquiries component (uses real hard inquiries, not snapshot).
    inquiries = _accepted_inquiry_count(credit_report_id)
    inquiries_score = max(0.0, 100.0 - 20.0 * inquiries)

    # Combine — all floats; single rounding at the very end (PRD §3.5).
    raw = (
        PAYMENT_HISTORY_WEIGHT * payment_history
        + UTILIZATION_WEIGHT * utilization_score
        + AGE_WEIGHT * age_score
        + MIX_WEIGHT * mix_score
        + RECENT_INQUIRIES_WEIGHT * inquiries_score
    )
    score = _round_half_up(300 + 5.5 * raw)
    return max(300, min(850, score))


def recompute_fico_on_report(credit_report_id: str) -> None:
    """Recompute & store the final FICO on a report."""
    from .store import stamp_update

    report = store.credit_reports.get(credit_report_id)
    if not report:
        return
    new_score = compute_fico(credit_report_id)
    if report.get("fico_score") != new_score:
        report["fico_score"] = new_score
        stamp_update(report)


def compute_projected_fico(credit_report_id: str) -> int:
    """Provisional FICO assuming every in-flight dispute resolves in the consumer's favor."""
    overrides: dict[str, dict[str, Any]] = {}
    extra_deleted: set[str] = set()
    NON_TERMINAL = {"RECEIVED", "UNDER_INVESTIGATION", "RESULTS_PENDING", "ESCALATED"}
    for dispute in store.disputes.values():
        if dispute["credit_report_id"] != credit_report_id:
            continue
        if dispute["status"] not in NON_TERMINAL:
            continue
        ti_id = dispute["tradeline_item_id"]
        action = dispute["requested_action"]
        payload = dispute.get("requested_payload") or {}
        if action == "DELETE_ITEM":
            extra_deleted.add(ti_id)
        elif action == "CORRECT_BALANCE":
            new_bal = payload.get("new_balance_cents")
            if isinstance(new_bal, int) and new_bal >= 0:
                overrides.setdefault(ti_id, {})["balance_cents"] = new_bal
        elif action == "CORRECT_STATUS":
            new_status = payload.get("new_payment_status")
            if new_status in PAYMENT_SCORES or new_status == "DELETED":
                overrides.setdefault(ti_id, {})["payment_status"] = new_status
        elif action == "CORRECT_DOFD":
            new_dofd = payload.get("new_dofd_day")
            if isinstance(new_dofd, int):
                overrides.setdefault(ti_id, {})["reported_dofd_day"] = new_dofd
    return compute_fico(
        credit_report_id, overrides=overrides, extra_deleted_ids=extra_deleted
    )


# ----------------------------------------------------------------------
# Dispute Risk Score
# ----------------------------------------------------------------------


def _consumer_disputes_in_365(consumer_id: str, *, exclude_id: str | None = None) -> list[dict[str, Any]]:
    today = clock.day
    cutoff = today - 365
    out: list[dict[str, Any]] = []
    for d in store.disputes.values():
        if d["consumer_id"] != consumer_id:
            continue
        if exclude_id is not None and d["id"] == exclude_id:
            continue
        if d.get("submitted_day", 0) >= cutoff:
            out.append(d)
    return out


def compute_dispute_risk_score(
    consumer_id: str,
    *,
    has_supporting_docs: bool,
    exclude_dispute_id: str | None = None,
) -> int:
    """PRD §3.6 — integer arithmetic, clamped 0..100."""
    relevant = _consumer_disputes_in_365(consumer_id, exclude_id=exclude_dispute_id)
    prior_disputes = len(relevant)
    prior_dismissed = sum(1 for d in relevant if d["status"] == "CLOSED_DISMISSED")
    # "Escalated at any point" — track via the auxiliary flag we maintain.
    prior_escalated = sum(
        1
        for d in relevant
        if store.dispute_escalation_history.get(d["id"], False) or d["status"] == "ESCALATED"
    )
    docs_term = 1 if has_supporting_docs else 0
    raw = 2 * prior_disputes + 5 * prior_dismissed + 3 * prior_escalated - 1 * docs_term
    score = 10 * raw
    return max(0, min(100, score))


# ----------------------------------------------------------------------
# Free Report Grant
# ----------------------------------------------------------------------

MAX_FREE_REPORTS_BALANCE = 12


def apply_free_report_grant(consumer_id: str, *, outcome: str, actual_field_changed: bool) -> None:
    """PRD §3.6 — non-linear interaction of (outcome, change, freeze)."""
    from .store import stamp_update

    consumer = store.consumers.get(consumer_id)
    if consumer is None:
        return
    grant = 1 if outcome in {"UPDATED", "DELETED"} and actual_field_changed else 0
    if grant == 0:
        return  # gate failed → no change
    has_active_freeze = any(
        f["consumer_id"] == consumer_id and f["status"] == "ACTIVE"
        for f in store.credit_freezes.values()
    )
    tier_grant = 2 if has_active_freeze else 1
    new_balance = min(MAX_FREE_REPORTS_BALANCE, consumer["free_reports_remaining"] + tier_grant)
    if new_balance != consumer["free_reports_remaining"]:
        consumer["free_reports_remaining"] = new_balance
        stamp_update(consumer)


# ----------------------------------------------------------------------
# Posture
# ----------------------------------------------------------------------

NON_TERMINAL_DISPUTE_STATUSES = {
    "RECEIVED",
    "UNDER_INVESTIGATION",
    "RESULTS_PENDING",
    "ESCALATED",
}


def compute_posture(credit_report_id: str) -> str:
    report = store.credit_reports.get(credit_report_id)
    if report is None:
        return "OPEN"
    consumer_id = report["consumer_id"]
    bureau = report["bureau"]
    active_freezes = sum(
        1
        for f in store.credit_freezes.values()
        if f["consumer_id"] == consumer_id
        and f["bureau"] == bureau
        and f["status"] == "ACTIVE"
    )
    active_disputes = sum(
        1
        for d in store.disputes.values()
        if d["credit_report_id"] == credit_report_id
        and d["status"] in NON_TERMINAL_DISPUTE_STATUSES
    )
    if active_freezes > 0:
        return "FROZEN"
    if active_disputes >= 1:
        return "RESTRICTED"
    return "OPEN"


def recompute_posture(credit_report_id: str) -> None:
    """Recompute and persist a report's posture (bumps version if changed)."""
    from .store import stamp_update

    report = store.credit_reports.get(credit_report_id)
    if report is None:
        return
    new_posture = compute_posture(credit_report_id)
    if report.get("posture") != new_posture:
        report["posture"] = new_posture
        stamp_update(report)


def recompute_posture_for_consumer_bureau(consumer_id: str, bureau: str) -> None:
    for report in store.credit_reports.values():
        if report["consumer_id"] == consumer_id and report["bureau"] == bureau:
            recompute_posture(report["id"])


# ----------------------------------------------------------------------
# Deadline
# ----------------------------------------------------------------------

BASE_DEADLINE_DAYS = 30
EXTENSION_DAYS = 15  # 30 + 15 = 45
REVERIFY_DAYS = 25


def base_deadline(submitted_day: int) -> int:
    return submitted_day + BASE_DEADLINE_DAYS


def extended_deadline(submitted_day: int) -> int:
    return submitted_day + BASE_DEADLINE_DAYS + EXTENSION_DAYS


def reverification_deadline(forwarded_day: int) -> int:
    return forwarded_day + REVERIFY_DAYS
