"""Repayment schedule endpoints (PRD §3.7)."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..calculations import variant_b_total_due
from ..clock import clock
from ..constants import MAX_PARTIAL_PREPAYMENTS
from ..errors import api_error
from ..response import success_envelope
from ..services.cascades import cascade_settle_schedule
from ..store import fmt_ts, store
from ..utils import (
    get_json_body,
    optional_bool,
    parse_iso_or_none,
    require_int,
)

bp = Blueprint("repayment_schedules", __name__, url_prefix="/scf/repayment-schedules")


READ_ROLES = ("Funder", "SupplierUser", "CoreEnterpriseUser", "CollectionManager", "PlatformAdmin")
WRITE_ROLES = ("CoreEnterpriseUser", "SupplierUser", "PlatformAdmin")


# ---- GET /scf/repayment-schedules/{id} ----
@bp.get("/<sid>")
@require_auth(READ_ROLES)
def get_schedule(sid):
    schedule = store.repayment_schedules.get(sid)
    if schedule is None:
        raise api_error("ERR_NOT_FOUND", "Repayment schedule not found")
    return success_envelope(schedule)


# ---- POST /scf/repayment-schedules/{id}/repay ----
@bp.post("/<sid>/repay")
@require_auth(WRITE_ROLES)
def repay_schedule(sid):
    schedule = store.repayment_schedules.get(sid)
    if schedule is None:
        raise api_error("ERR_NOT_FOUND", "Repayment schedule not found")
    if schedule.get("status") in ("SETTLED", "WRITTEN_OFF"):
        raise api_error("ERR_INVALID_STATE", "Schedule is terminal")
    body = get_json_body()
    repay_amount = require_int(body, "repay_amount_cents")
    if repay_amount <= 0:
        raise api_error("ERR_AMOUNT_NON_POSITIVE", "repay_amount_cents must be > 0")
    partial = optional_bool(body, "partial", False)
    early_settle = optional_bool(body, "early_settle", False)

    outstanding = int(schedule["total_due_cents"]) - int(schedule.get("paid_cents", 0))
    if outstanding <= 0:
        raise api_error("ERR_INVALID_STATE", "No outstanding balance")

    now = clock.now()
    scheduled_dt = parse_iso_or_none(schedule.get("scheduled_repayment_date"))

    if partial:
        # Partial prepayment
        if repay_amount >= outstanding:
            raise api_error("ERR_OVERPAYMENT", "partial repayment must be strictly less than outstanding")
        if int(schedule.get("prepayment_count", 0)) >= MAX_PARTIAL_PREPAYMENTS:
            raise api_error("ERR_PREPAYMENT_LIMIT_REACHED", "Partial-prepayment cap reached")
        with store.lock:
            schedule["paid_cents"] = int(schedule.get("paid_cents", 0)) + repay_amount
            schedule["prepayment_count"] = int(schedule.get("prepayment_count", 0)) + 1
            prepayments = schedule.setdefault("prepayments", [])
            prepayments.append({"at": fmt_ts(now), "amount_cents": repay_amount})
            if schedule.get("status") == "SCHEDULED":
                schedule["status"] = "PARTIALLY_PAID"
            store.stamp_update(schedule)
        return success_envelope(schedule)

    # Full balance (or early-settle with rebate)
    if early_settle and scheduled_dt is not None and now < scheduled_dt:
        # Compute chronological total due via Variant B, then rebate
        app = store.financing_applications.get(schedule["application_id"])
        principal = int(schedule.get("principal_cents") or (app or {}).get("approved_amount_cents") or 0)
        apr_bps = int((app or {}).get("approved_apr_bps") or 0)
        fees_cents = int(schedule.get("fees_cents", 0))

        # Disbursement reference time
        disbursement = None
        for d in store.disbursements.values():
            if d.get("application_id") == schedule["application_id"]:
                disbursement = d
                break
        released_at = parse_iso_or_none((disbursement or {}).get("released_at"))
        if released_at is None:
            released_at = parse_iso_or_none(schedule.get("created_at"))

        # Build prepayments list
        prepayments_list = []
        for entry in schedule.get("prepayments", []):
            pwhen = parse_iso_or_none(entry.get("at"))
            if pwhen is not None:
                prepayments_list.append((pwhen, int(entry.get("amount_cents", 0))))

        chrono_total = variant_b_total_due(
            principal_cents=principal,
            approved_apr_bps=apr_bps,
            released_at=released_at,
            settle_date=now,
            fees_cents=fees_cents,
            prepayments=prepayments_list,
        )
        forward_total = int(schedule["total_due_cents"])
        rebate = max(0, forward_total - chrono_total)
        net_payment_required = forward_total - int(schedule.get("paid_cents", 0)) - rebate
        # PRD §3.7: "The net payment required is the forward total
        # minus prior paid_cents minus this rebate, and the schedule
        # advances to SETTLED." A caller may pass the netted amount
        # exactly, or may pass the un-netted outstanding (which the
        # server then rebates internally). Anything strictly greater
        # than outstanding overpays; anything strictly less than the
        # net payment required underpays.
        outstanding_now = forward_total - int(schedule.get("paid_cents", 0))
        if repay_amount > outstanding_now:
            raise api_error("ERR_OVERPAYMENT", "repay_amount_cents > outstanding")
        if repay_amount < net_payment_required:
            raise api_error(
                "ERR_OVERPAYMENT",
                f"repay_amount_cents below net-payment-required ({net_payment_required})",
            )

        with store.lock:
            schedule["paid_cents"] = forward_total - rebate
            schedule["rebate_cents"] = rebate
            schedule["status"] = "SETTLED"
            schedule["total_due_cents_chronological"] = chrono_total
            store.stamp_update(schedule)
            cascade_settle_schedule(schedule, g.user_role, g.user_id)
            store.append_audit(
                actor_role=g.user_role,
                actor_id=g.user_id,
                entity_type="RepaymentSchedule",
                entity_id=schedule["id"],
                action="REPAY",
                amount_cents=repay_amount,
            )
        return success_envelope(schedule)

    # Plain full-balance settlement (with no rebate or after due date)
    if repay_amount > outstanding:
        raise api_error("ERR_OVERPAYMENT", "repay_amount_cents > outstanding")
    if repay_amount < outstanding:
        raise api_error("ERR_VALIDATION", "Non-partial repay must equal outstanding")

    with store.lock:
        schedule["paid_cents"] = int(schedule["total_due_cents"])
        schedule["status"] = "SETTLED"
        store.stamp_update(schedule)
        cascade_settle_schedule(schedule, g.user_role, g.user_id)
        store.append_audit(
            actor_role=g.user_role,
            actor_id=g.user_id,
            entity_type="RepaymentSchedule",
            entity_id=schedule["id"],
            action="REPAY",
            amount_cents=repay_amount,
        )
    return success_envelope(schedule)
