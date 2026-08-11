"""The cycle, the snap-forward, the auto-schedule and the two reminders (PRD 3.8)."""

from core.constants import (
    REMINDER_OFFSET_DAYS_PRIMARY,
    REMINDER_OFFSET_DAYS_SECONDARY,
    REMINDER_SUPPRESSION_WINDOW_DAYS,
    SNAP_FORWARD_LOOKAHEAD_DAYS,
)
from core.store import db, order_key
from core.timeutil import (
    add_days,
    add_weeks,
    clock,
    parse_iso_date,
    render_date,
    weekday_token,
)


def derive_next_due(horse):
    """A live therapeutic prescription overrides the routine cycle UNCONDITIONALLY.

    Returns ``(next_due_on_iso_or_None, cycle_source_or_None)``.  With no
    ``last_completed_on`` there is no base date and ``next_due_on`` stays null.
    """
    base = parse_iso_date(horse.get("last_completed_on"))
    if base is None:
        return None, None
    prescription = db.get("vet_prescriptions", horse.get("active_prescription_id"))
    expires = parse_iso_date(prescription["expires_on"]) if prescription else None
    if (
        prescription is not None
        and prescription["status"] == "ACTIVE"
        and expires is not None
        and expires >= base
    ):
        cycle_weeks = prescription["prescribed_cycle_weeks"]
        source = "THERAPEUTIC"
    else:
        cycle_weeks = horse["routine_cycle_weeks"]
        source = "ROUTINE"
    return render_date(add_weeks(base, cycle_weeks)), source


def refresh_next_due(horse):
    """Re-run the derivation and write it; returns True when the row changed."""
    next_due, _source = derive_next_due(horse)
    changed = horse.get("next_due_on") != next_due
    horse["next_due_on"] = next_due
    return changed


def snap_forward(raw_due_iso, barn):
    """Offset 0 is tested FIRST, then 1, 2 and 3.

    The first candidate whose weekday the barn serves and which is not a
    blackout date is taken; if all four fail the raw due date stands.
    """
    raw = parse_iso_date(raw_due_iso)
    if raw is None or barn is None:
        return raw_due_iso
    blackouts = barn.get("blackout_dates") or []
    for offset in range(0, SNAP_FORWARD_LOOKAHEAD_DAYS + 1):
        candidate = add_days(raw, offset)
        candidate_iso = render_date(candidate)
        if weekday_token(candidate) in barn["served_weekdays"] and candidate_iso not in blackouts:
            return candidate_iso
    return render_date(raw)


def mint_reminders(appointment):
    """Two PENDING rows, at the primary and then the secondary offset.

    # Adjudication of friction 10: the pair is minted UNCONDITIONALLY, both
    # when a successor visit is auto-minted and again whenever any appointment
    # is attached to a stop, so an auto-minted visit that is later routed ends
    # up with four reminder rows.  Section 3.8 states the attachment minting
    # without any "unless it already has a pair" qualifier ("The same pair of
    # reminders is minted whenever an appointment is attached to a stop"), and
    # the unconditional reading strands no declared behaviour.
    """
    minted = []
    scheduled = parse_iso_date(appointment["scheduled_date"])
    for offset in (REMINDER_OFFSET_DAYS_PRIMARY, REMINDER_OFFSET_DAYS_SECONDARY):
        due_on = render_date(add_days(scheduled, -offset)) if scheduled else None
        minted.append(
            db.mint(
                "reminders",
                {
                    "appointment_id": appointment["id"],
                    "offset_days": offset,
                    "due_on": due_on,
                    "status": "PENDING",
                    "sent_on": None,
                },
            )
        )
    return minted


def reminders_of(appointment_id):
    rows = [r for r in db.reminders.values() if r["appointment_id"] == appointment_id]
    rows.sort(key=order_key)
    return rows


def reminder_is_suppressed(reminder):
    """A recently sent sibling suppresses delivery; the window is closed on both sides."""
    for sibling in reminders_of(reminder["appointment_id"]):
        if sibling["id"] == reminder["id"]:
            continue
        if sibling["status"] not in ("SENT", "ACKNOWLEDGED"):
            continue
        sent_on = parse_iso_date(sibling.get("sent_on"))
        if sent_on is None:
            continue
        if abs((clock.today - sent_on).days) <= REMINDER_SUPPRESSION_WINDOW_DAYS:
            return True
    return False
