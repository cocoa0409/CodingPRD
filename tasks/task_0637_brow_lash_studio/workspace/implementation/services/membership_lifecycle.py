"""Membership state machine + cycle reconciliation (PRD §3.4, §2.7, §2.9)."""
import math

import errors
from clock import clock
from common import touch
from db import store
from services import credits, derive


def _advance_one_month(dt):
    """Advance a datetime by one calendar month (PRD §3.4: cycle_anchor_utc +1
    month). Clamp day-of-month to the target month's length."""
    year = dt.year + (1 if dt.month == 12 else 0)
    month = 1 if dt.month == 12 else dt.month + 1
    # days in target month
    if month == 12:
        next_month_year, next_month = year + 1, 1
    else:
        next_month_year, next_month = year, month + 1
    import calendar
    last_day = calendar.monthrange(year, month)[1]
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)


def close_cycle(membership, expected_version):
    """Close a billing cycle (PRD §3.4 / calculations.cycle_rollover).

    Permitted only while ACTIVE; OCC-guarded (PRD §2.9)."""
    # Priority order within this op: state (5) then OCC (12) per PRD §2.10 family.
    if membership["status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_INVALID_MEMBERSHIP_STATE, 409,
                              "Membership must be ACTIVE to close a cycle.")
    if expected_version != membership["version"]:
        raise errors.ApiError(errors.ERR_STALE_MEMBERSHIP_VERSION, 412,
                              "Stale membership version.")
    plan = store.membership_plans[membership["plan_id"]]
    pre_balance = credits.credit_balance(membership["id"])
    cap = math.floor(plan["monthly_credit_allotment"] * plan["rollover_cap_multiplier"])
    carried = min(pre_balance, cap)
    forfeited = pre_balance - carried  # >= 0
    if forfeited > 0:
        credits.append_ledger_entry(membership["id"], -forfeited,
                                    "ROLLOVER_FORFEIT", membership["id"])
    # GRANT of the monthly allotment (net: balance = carried + allotment).
    credits.append_ledger_entry(membership["id"], plan["monthly_credit_allotment"],
                                "GRANT", membership["id"])
    membership["cycles_closed"] += 1
    membership["cycle_anchor_utc"] = _advance_one_month(membership["cycle_anchor_utc"])
    touch(membership)
    return membership


def flag_past_due(membership):
    if membership["status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_INVALID_MEMBERSHIP_STATE, 409,
                              "Membership must be ACTIVE to flag past due.")
    membership["status"] = "PAST_DUE"
    touch(membership)
    return membership


def settle_dues(membership):
    if membership["status"] != "PAST_DUE":
        raise errors.ApiError(errors.ERR_INVALID_MEMBERSHIP_STATE, 409,
                              "Membership must be PAST_DUE to settle dues.")
    membership["status"] = "ACTIVE"
    touch(membership)
    return membership


def reactivate(membership):
    if membership["status"] != "SUSPENDED":
        raise errors.ApiError(errors.ERR_INVALID_MEMBERSHIP_STATE, 409,
                              "Membership must be SUSPENDED to reactivate.")
    member = store.members[membership["member_id"]]
    studio = store.studios[member["studio_id"]]
    count = derive.noshow_strike_count(member)
    if count >= studio["noshow_strike_threshold"]:
        raise errors.ApiError(errors.ERR_STRIKES_STILL_ACTIVE, 409,
                              "No-show strikes have not aged out yet.")
    membership["status"] = "ACTIVE"
    touch(membership)
    return membership


def cancel_membership(membership):
    """ACTIVE/PAST_DUE/SUSPENDED -> CANCELLED (PRD §3.4). No precondition on
    from-state besides being non-terminal-distinct; cascades ACTIVE recurring
    schedules of the member to ENDED (PRD §2.7)."""
    membership["status"] = "CANCELLED"
    touch(membership)
    member_id = membership["member_id"]
    for sched in store.recurring_schedules.values():
        if sched["member_id"] == member_id and sched["status"] == "ACTIVE":
            sched["status"] = "ENDED"
            touch(sched)
    return membership


def suspend_for_strikes(member):
    """System cascade when a member's noshow_strike_count reaches the threshold
    (PRD §2.7, §3.8). Suspends the member's ACTIVE/PAST_DUE memberships and
    auto-cancels their future BOOKED appointments."""
    # Suspend memberships in ACTIVE or PAST_DUE.
    for ms in store.memberships.values():
        if ms["member_id"] != member["id"]:
            continue
        if ms["status"] in ("ACTIVE", "PAST_DUE"):
            ms["status"] = "SUSPENDED"
            touch(ms)
    # Auto-cancel future BOOKED appointments of the member.
    now = clock.now()
    for appt in store.appointments.values():
        if appt["member_id"] != member["id"]:
            continue
        if appt["status"] != "BOOKED":
            continue
        if appt["start_utc"] <= now:
            continue  # only future appointments
        appt["status"] = "CANCELLED"
        # Credit-paid: credits returned; cash: forfeits nothing.
        appt["deposit_forfeited_cents"] = 0
        if appt["pay_with_credits"] and appt["membership_id"] and appt["credits_charged"] > 0:
            credits.append_ledger_entry(appt["membership_id"], appt["credits_charged"],
                                        "REFUND", appt["id"])
            ms = store.memberships.get(appt["membership_id"])
            if ms:
                touch(ms)
        touch(appt)
