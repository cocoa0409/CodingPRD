"""Appointment terminal transitions: complete / cancel / no-show (PRD §3.8)."""
from datetime import timedelta

import errors
from clock import clock
from common import round_half_up, touch
from db import store
from services import credits, derive, membership_lifecycle


def complete(appt):
    """BOOKED -> COMPLETED (PRD §3.8). LashTech or StudioManager.

    Caller has verified role + ownership. State + clock preconditions here."""
    if appt["status"] != "BOOKED":
        raise errors.ApiError(errors.ERR_APPOINTMENT_NOT_BOOKED, 409, "Appointment is not BOOKED.")
    if clock.now() < appt["start_utc"]:
        raise errors.ApiError(errors.ERR_APPOINTMENT_NOT_STARTED, 409, "Appointment has not started.")
    appt["status"] = "COMPLETED"
    touch(appt)
    # If the service category is PREMIUM, the member's last_premium_completed_utc
    # is recomputed (derived at read time); recomputation is a mutation of the
    # member parent, so refresh its updated_at/version (PRD §2.5).
    st = store.service_types.get(appt["service_type_id"])
    if st and st["category"] == "PREMIUM":
        member = store.members.get(appt["member_id"])
        if member:
            touch(member)
    return appt


def mark_no_show(appt):
    """BOOKED -> NO_SHOW (PRD §3.8). FrontDesk or StudioManager."""
    if appt["status"] != "BOOKED":
        raise errors.ApiError(errors.ERR_APPOINTMENT_NOT_BOOKED, 409, "Appointment is not BOOKED.")
    if clock.now() < appt["start_utc"]:
        raise errors.ApiError(errors.ERR_APPOINTMENT_NOT_STARTED, 409, "Appointment has not started.")
    appt["status"] = "NO_SHOW"
    # Full deposit forfeited; cash deposit kept. Credit-paid: no refund.
    appt["deposit_forfeited_cents"] = appt["deposit_cents"]
    touch(appt)

    member = store.members.get(appt["member_id"])
    if member:
        # noshow_strike_count recomputed (mutation of member parent).
        touch(member)
        count = derive.noshow_strike_count(member)
        studio = store.studios.get(member["studio_id"])
        threshold = studio["noshow_strike_threshold"] if studio else 3
        if count >= threshold:
            # Cascade: membership ACTIVE/PAST_DUE -> SUSPENDED.
            membership_lifecycle.suspend_for_strikes(member)
    return appt


def cancel(appt):
    """BOOKED -> CANCELLED (timely) or LATE_CANCELLED (late) (PRD §3.8).

    Timely: time remaining until start >= cutoff hours.
    Late:   time remaining < cutoff hours AND clock still before start."""
    if appt["status"] != "BOOKED":
        raise errors.ApiError(errors.ERR_APPOINTMENT_NOT_BOOKED, 409, "Appointment is not BOOKED.")
    studio = store.studios[appt["studio_id"]]
    cutoff_hours = studio["late_cancel_cutoff_hours"]
    now = clock.now()
    remaining = appt["start_utc"] - now  # timedelta
    cutoff = timedelta(hours=cutoff_hours)

    if remaining >= cutoff:
        # Timely cancellation.
        appt["status"] = "CANCELLED"
        appt["deposit_forfeited_cents"] = 0
        _refund_credits_if_any(appt)
        touch(appt)
        _reclaim_recurring_slot(appt)
    else:
        # Late cancellation (clock within cutoff window; clock < start).
        appt["status"] = "LATE_CANCELLED"
        appt["deposit_forfeited_cents"] = round_half_up(appt["deposit_cents"] * 0.50)
        _refund_credits_if_any(appt)
        touch(appt)
    return appt


def _refund_credits_if_any(appt):
    """On CANCELLED/LATE_CANCELLED of a credit-paid appointment, append a REFUND
    ledger entry of +credits_charged and bump membership version."""
    if appt["pay_with_credits"] and appt["membership_id"] and appt["credits_charged"] > 0:
        credits.append_ledger_entry(appt["membership_id"], appt["credits_charged"],
                                    "REFUND", appt["id"])
        ms = store.memberships.get(appt["membership_id"])
        if ms:
            touch(ms)


def _reclaim_recurring_slot(appt):
    """Timely cancel of a recurring-spawned fill rewinds the schedule
    (PRD §3.8): next_due_utc -= cadence_days; spawned_count -= 1."""
    sched_id = appt.get("recurring_schedule_id")
    if not sched_id:
        return
    sched = store.recurring_schedules.get(sched_id)
    if not sched:
        return
    sched["next_due_utc"] = sched["next_due_utc"] - timedelta(days=sched["cadence_days"])
    sched["spawned_count"] = sched["spawned_count"] - 1
    touch(sched)
