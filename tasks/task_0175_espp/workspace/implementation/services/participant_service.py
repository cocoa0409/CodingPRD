"""Per-participant aggregates: accrual summary, dilution preview."""
from __future__ import annotations

from typing import Dict

from core.errors import APIError
from core.store import store
from core.utils import parse_iso, round_half_up_int
from services.calculations import compute_dilution_score


BP_DENOM = 10000


def accrual_summary(
    *,
    participant_id: str,
    calendar_year: int,
    include_projection: bool,
) -> dict:
    """Compute per-participant accrual summary for a calendar year."""
    committed_cents = 0
    projected_cents = 0
    cap_cents = None
    plan_id_for_cap = None

    # Group enrollments by plan.
    enrollments_for_participant = [
        e for e in store.enrollments.values() if e["participant_id"] == participant_id
    ]

    # Filter to enrollments whose owning offering period's start_date.year matches.
    in_year_enrollments = []
    for e in enrollments_for_participant:
        op = store.offering_periods.get(e["offering_period_id"])
        if op is None:
            continue
        try:
            yr = parse_iso(op["start_date"]).year
        except Exception:
            continue
        if yr != calendar_year:
            continue
        if e["status"] not in ("ACTIVE", "COMPLETED", "WITHDRAWN"):
            continue
        in_year_enrollments.append((e, op))

    for e, op in in_year_enrollments:
        committed_cents += e["ytd_accrual_cents"]
        if cap_cents is None:
            plan = store.plans.get(op["plan_id"])
            if plan is not None:
                cap_cents = plan["annual_accrual_cap_cents"]
                plan_id_for_cap = plan["id"]

    if include_projection:
        for e, op in in_year_enrollments:
            if e["status"] != "ACTIVE":
                continue
            plan = store.plans.get(op["plan_id"])
            if plan is None:
                continue
            posted_total = sum(
                c["amount_cents"]
                for c in store.contributions.values()
                if c["enrollment_id"] == e["id"] and c["status"] == "POSTED"
            )
            grant_fmv = op["grant_date_fmv_cents"]
            if grant_fmv is None:
                # Cannot project without grant FMV; skip.
                continue
            purchase_fmv = op["purchase_date_fmv_cents"] if op["purchase_date_fmv_cents"] is not None else grant_fmv
            chosen_fmv = min(grant_fmv, purchase_fmv)
            per_share_price = round_half_up_int(
                chosen_fmv * (BP_DENOM - plan["discount_bp"]), BP_DENOM
            )
            if per_share_price == 0:
                continue
            projected_shares = posted_total // per_share_price
            projected_cents += projected_shares * grant_fmv

    # If we never found a plan (e.g. no in-year enrollments), fall back to 0
    # cap so remaining is reported as 0 minus committed (which is also 0).
    if cap_cents is None:
        cap_cents = 0

    remaining = cap_cents - committed_cents - projected_cents

    return {
        "participant_id": participant_id,
        "calendar_year": calendar_year,
        "committed_cents": committed_cents,
        "projected_cents": projected_cents if include_projection else 0,
        "remaining_cents": remaining,
        "include_projection": include_projection,
        "annual_accrual_cap_cents": cap_cents,
    }


def dilution_preview(
    *, plan_id: str, eligible_employee_count: int
) -> dict:
    from services.plan_service import get_plan_or_404

    plan = get_plan_or_404(plan_id)

    # Find the plan's currently-OPEN offering period (there should be at most one).
    open_op = None
    for op in store.offering_periods.values():
        if op["plan_id"] == plan_id and op["status"] == "OPEN":
            open_op = op
            break

    active_enrollment_count = 0
    if open_op is not None:
        for e in store.enrollments.values():
            if e["offering_period_id"] == open_op["id"] and e["status"] == "ACTIVE":
                active_enrollment_count += 1

    score = compute_dilution_score(
        max_contribution_rate_bp=plan["max_contribution_rate_bp"],
        annual_accrual_cap_cents=plan["annual_accrual_cap_cents"],
        active_enrollment_count=active_enrollment_count,
        eligible_employee_count=eligible_employee_count,
    )
    return {
        "plan_id": plan_id,
        "eligible_employee_count": eligible_employee_count,
        "active_enrollment_count": active_enrollment_count,
        "dilution_score": score,
    }
