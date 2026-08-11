"""Volunteer service hours and period-report aggregation (PRD §3.4, §3.8)."""

from core import numbers as N
from core import timeutil as T
from core.store import db

from . import derive

SCHEDULED_STATUSES = ("CREW_PENDING", "CONFIRMED", "COMPLETED")


def volunteer_service_hours(volunteer_id, period_start, period_end, variant):
    """Per-session round FIRST, then sum, then round again (§2.6)."""
    statuses = SCHEDULED_STATUSES if variant == "scheduled" else ("COMPLETED",)
    total = N.dec(0)
    count = 0
    for assignment in db["crew_assignments"].values():
        if assignment["volunteer_id"] != volunteer_id:
            continue
        if assignment["status"] != "ASSIGNED":
            continue
        session = db["sessions"].get(assignment["session_id"])
        if session is None or session["schedule_status"] not in statuses:
            continue
        session_date = T.day_of(session["scheduled_start"].dt)
        if not (period_start <= session_date <= period_end):
            continue
        minutes = (session["duration_minutes"] if variant == "scheduled"
                   else (session.get("mounted_minutes") or 0))
        total += N.dec(N.minutes_to_hours(minutes))
        count += 1
    return N.round2(total), count


def in_period_sessions(period_start, period_end):
    rows = []
    for session in db["sessions"].values():
        session_date = T.day_of(session["scheduled_start"].dt)
        if period_start <= session_date <= period_end:
            rows.append(session)
    return rows


def aggregate(period_start, period_end):
    """The draft_live_recompute variant; finalize freezes exactly this result."""
    sessions = in_period_sessions(period_start, period_end)
    completed = [s for s in sessions if s["schedule_status"] == "COMPLETED"]

    hours = N.dec(0)
    for session in completed:
        hours += N.dec(derive.session_service_hours(session))
    total_service_hours = N.round2(hours)

    rider_ids = {s["rider_id"] for s in completed}
    veteran = 0
    for rider_id in rider_ids:
        rider = db["riders"].get(rider_id)
        if rider is not None and rider["demographic_group"] == "VETERAN":
            veteran += 1

    volunteer_total = N.dec(0)
    for volunteer_id in db["volunteers"]:
        value, _ = volunteer_service_hours(volunteer_id, period_start, period_end,
                                           "delivered")
        volunteer_total += N.dec(value)

    session_ids = {s["id"] for s in sessions}
    charges = [c for c in db["charges"].values() if c["session_id"] in session_ids]
    charge_ids = {c["id"] for c in charges}

    grant_cents = 0
    scholarship_cents = 0
    private_cents = 0
    for allocation in db["funding_allocations"].values():
        if allocation["charge_id"] not in charge_ids:
            continue
        if allocation["status"] != "ALLOCATED":
            continue
        if allocation["source_type"] == "GRANT":
            grant_cents += allocation["amount_cents"]
        elif allocation["source_type"] == "SCHOLARSHIP":
            scholarship_cents += allocation["amount_cents"]
        elif allocation["source_type"] == "PRIVATE_PAY":
            private_cents += allocation["amount_cents"]

    total_charged = sum(c["amount_cents"] for c in charges
                        if derive.charge_status(c) != "REVERSED")

    return {
        "total_service_hours": total_service_hours,
        "rider_count": len(rider_ids),
        "veteran_rider_count": veteran,
        "volunteer_hours": N.round2(volunteer_total),
        "grant_utilization_cents": grant_cents,
        "scholarship_spend_cents": scholarship_cents,
        "private_pay_cents": private_cents,
        "total_charged_cents": total_charged,
    }


AGGREGATE_KEYS = (
    "total_service_hours", "rider_count", "veteran_rider_count", "volunteer_hours",
    "grant_utilization_cents", "scholarship_spend_cents", "private_pay_cents",
    "total_charged_cents",
)


def period_report(row):
    """DRAFT recomputes live on every read; FINALIZED returns the frozen snapshot."""
    out = {
        "id": row["id"],
        "created_at": row["created_at"].raw,
        "updated_at": row["updated_at"].raw,
        "version": row["version"],
        "period_start": row["period_start"],
        "period_end": row["period_end"],
        "status": row["status"],
        "finalized_at": T.raw_or_none(row.get("finalized_at")),
        "amendment_count": row["amendment_count"],
        "amendment_net_cents": row["amendment_net_cents"],
    }
    if row["status"] == "FINALIZED":
        for key in AGGREGATE_KEYS:
            out[key] = row[key]
    else:
        live = aggregate(T.parse_date(row["period_start"]),
                         T.parse_date(row["period_end"]))
        for key in AGGREGATE_KEYS:
            out[key] = live[key]
    return out
