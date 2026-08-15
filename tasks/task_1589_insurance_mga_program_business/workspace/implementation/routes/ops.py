"""Test-driving / ops endpoints: the logical clock and the daily operations
checkpoint (PRD section 2.5).

One run-daily invocation: completes due cancellations (with earned premium,
refund and capacity-release consequences of section 3.4), expires policies in
BOUND/ISSUED whose effective_to has passed, withdraws lapsed QUOTED quotes,
expires ACTIVE appointments whose effective_to has passed, and flags overdue
DRAFT bordereaux.
"""
from flask import Blueprint

from db import STORE, touch, now_dt, format_dt
from middleware import require_roles
from response import success_object
from services import capacity, trust
from services.pricing import cancellation_earned_cents, is_flat_cancel, CANCELLATION_FEE_CENTS
from validation import get_body, req_datetime

bp = Blueprint("ops", __name__)


@bp.post("/mga/_clock/set_current_utc")
def set_current_utc():
    require_roles("PlatformAdmin")
    body = get_body()
    new_now = req_datetime(body, "to_iso8601")
    STORE.clock = new_now
    return success_object({"current_utc": format_dt(STORE.clock)})


def _complete_cancellation(p, clock):
    """PENDING_CANCELLATION -> CANCELLED with earned premium, refund posting and
    capacity release."""
    program = STORE.programs[p["program_id"]]
    flat = is_flat_cancel(p)
    earned = cancellation_earned_cents(p)
    p["earned_premium_cents"] = earned
    fee = 0 if flat else CANCELLATION_FEE_CENTS
    refund = max(0, p["collected_cents"] - earned - fee)
    released = p["gross_premium_cents"] - earned
    p["capacity_released_cents"] = released
    p["status"] = "CANCELLED"
    p["cancelled_at"] = clock
    if refund > 0:
        trust.post_entry(program, "REFUND", -refund, policy=p)
    tranche = capacity.current_tranche(p["program_id"])
    if tranche is not None:
        capacity.release(tranche, released)
    program["consumed_aggregate_cents"] = max(0, program["consumed_aggregate_cents"] - released)
    touch(p)


@bp.post("/mga/_ops/run-daily")
def run_daily():
    require_roles("PlatformAdmin")
    clock = now_dt()
    cancelled_policy_ids = []
    expired_policy_ids = []
    withdrawn_quote_ids = []
    expired_appointment_ids = []
    flagged_bordereau_ids = []

    # 1. Due cancellations (inclusive: cancellation_date <= clock).
    for p in sorted(STORE.policies.values(), key=lambda x: x["_seq"]):
        if p["status"] == "PENDING_CANCELLATION" and p["cancellation_date"] <= clock:
            _complete_cancellation(p, clock)
            cancelled_policy_ids.append(p["id"])

    # 2. Policy expiries: BOUND/ISSUED whose effective_to has passed. The whole
    # term is earned; no capacity is released (the aggregate is lifetime
    # written premium).
    for p in sorted(STORE.policies.values(), key=lambda x: x["_seq"]):
        if p["status"] in ("BOUND", "ISSUED") and p["effective_to"] < clock:
            p["status"] = "EXPIRED"
            p["earned_premium_cents"] = p["gross_premium_cents"]
            touch(p)
            expired_policy_ids.append(p["id"])

    # 3. Quote lapses: QUOTED whose quote_valid_until has lapsed.
    for p in sorted(STORE.policies.values(), key=lambda x: x["_seq"]):
        if p["status"] == "QUOTED" and p["quote_valid_until"] < clock:
            p["status"] = "WITHDRAWN"
            touch(p)
            withdrawn_quote_ids.append(p["id"])

    # 4. Appointment expiries: ACTIVE whose effective_to has passed.
    for a in sorted(STORE.tpa_appointments.values(), key=lambda x: x["_seq"]):
        if a["status"] == "ACTIVE" and a["effective_to"] < clock:
            a["status"] = "EXPIRED"
            touch(a)
            expired_appointment_ids.append(a["id"])

    # 5. Bordereau overdue flags: still-DRAFT bordereaux whose due_date passed.
    for b in sorted(STORE.bordereaux.values(), key=lambda x: x["_seq"]):
        if b["status"] == "DRAFT" and b["due_date"] < clock and not b["overdue"]:
            b["overdue"] = True
            touch(b)
            flagged_bordereau_ids.append(b["id"])

    return success_object({
        "cancelled_policy_ids": cancelled_policy_ids,
        "expired_policy_ids": expired_policy_ids,
        "withdrawn_quote_ids": withdrawn_quote_ids,
        "expired_appointment_ids": expired_appointment_ids,
        "flagged_bordereau_ids": flagged_bordereau_ids,
    })
