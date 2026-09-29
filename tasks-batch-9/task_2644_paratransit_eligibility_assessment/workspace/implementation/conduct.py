"""PRD 3.9 / 2.8 — the conduct block: dual point bases, the pooled miss ratio,
the escalating suspension ladder and the conserved day ledger."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from store import db, date_of, today

CONDUCT_WINDOW_DAYS = 90
POINTS = {
    "NO_SHOW": 2,
    "LATE_CANCEL": 1,
    "COMPLETED": 0,
    "CANCEL_IN_ADVANCE": 0,
    "AGENCY_FAULT_NO_SHOW": 0,
}
CHARGEABLE_TYPES = ("NO_SHOW", "LATE_CANCEL")

SUSPENSION_POINT_THRESHOLD = 6
SUSPENSION_MIN_MISS_COUNT = 3
SUSPENSION_RATIO_THRESHOLD_PCT = Decimal("10.0")
SUSPENSION_LADDER_DAYS = (7, 14, 21, 30)

PRIOR_COUNTING_STATUSES = ("UPHELD_PENDING", "ACTIVE", "SERVED", "VOID")
LIVE_PROCEEDING_STATUSES = (
    "PROPOSED",
    "NOTICE_SENT",
    "RIDER_RESPONDED",
    "RESPONSE_LAPSED",
    "UPHELD_PENDING",
    "ACTIVE",
)


def conduct_window():
    """PRD 2.8: 90 calendar days ending on today's date, both ends inclusive."""
    end = today()
    return end - timedelta(days=CONDUCT_WINDOW_DAYS - 1), end


def _events(applicant_id):
    return [e for e in db.trip_events.values() if e["applicant_id"] == applicant_id]


def _chronological(events):
    """PRD 3.9: accumulated in trip_date ASC then created_at ASC order."""
    return sorted(events, key=lambda e: (e["trip_date"], e["created_at"], e["_seq"]))


def round_half_up_1(numerator, denominator):
    value = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )
    return value


def compute_conduct(applicant_id):
    """Recomputed on every ingestion, every excusal and every read of the rider."""
    start, end = conduct_window()
    events = _chronological(_events(applicant_id))

    event_basis = 0
    report_basis = 0
    scheduled = 0
    chargeable = 0

    for e in events:
        trip_date = e["trip_date"]
        recorded_date = date_of(e["recorded_at"])
        in_event_window = trip_date is not None and start <= trip_date <= end
        in_report_window = recorded_date is not None and start <= recorded_date <= end
        if not e["excused"]:
            if in_event_window:
                event_basis += e["points_assessed"]
            if in_report_window:
                report_basis += e["points_assessed"]
        if in_event_window:
            scheduled += 1
            if not e["excused"] and e["event_type"] in CHARGEABLE_TYPES:
                chargeable += 1

    if scheduled == 0:
        ratio = Decimal("0.0")
    else:
        ratio = round_half_up_1(chargeable * 100, scheduled)

    return {
        "no_show_points_event_basis": event_basis,
        "no_show_points_report_basis": report_basis,
        "chargeable_miss_count_90d": chargeable,
        "scheduled_trip_count_90d": scheduled,
        "no_show_ratio_pct": ratio,
    }


def thresholds_met(conduct):
    """PRD 3.9: all three must hold simultaneously."""
    return (
        conduct["no_show_points_event_basis"] >= SUSPENSION_POINT_THRESHOLD
        and conduct["chargeable_miss_count_90d"] >= SUSPENSION_MIN_MISS_COUNT
        and conduct["no_show_ratio_pct"] > SUSPENSION_RATIO_THRESHOLD_PCT
    )


def proceedings_of(applicant_id):
    return [p for p in db.proceedings.values() if p["applicant_id"] == applicant_id]


def has_live_proceeding(applicant_id):
    return any(p["status"] in LIVE_PROCEEDING_STATUSES for p in proceedings_of(applicant_id))


def prior_upheld_count(applicant_id):
    """PRD 3.9: only proceedings whose decision is UPHELD and whose status is
    UPHELD_PENDING, ACTIVE, SERVED or VOID.  A RESCINDED one, and one voided
    while still merely PROPOSED, never count."""
    return len(
        [
            p
            for p in proceedings_of(applicant_id)
            if p.get("decision") == "UPHELD" and p["status"] in PRIOR_COUNTING_STATUSES
        ]
    )


def ladder_duration(prior_count):
    return SUSPENSION_LADDER_DAYS[min(prior_count, len(SUSPENSION_LADDER_DAYS) - 1)]


def days_served_now(proceeding):
    """PRD 3.9 ledger, resolved by status at read time."""
    status = proceeding["status"]
    duration = proceeding["duration_days"]
    if status == "ACTIVE":
        start = proceeding["suspension_start_date"]
        if start is None:
            return 0
        inclusive = (today() - start).days + 1
        if inclusive < 0:
            inclusive = 0
        return min(duration, inclusive)
    if status == "UPHELD_PENDING":
        return 0
    return proceeding["days_served"]


def ledger_total(applicant_id):
    """Sum of every proceeding's duration_days (== served + forgiven)."""
    return sum(p["duration_days"] for p in proceedings_of(applicant_id))


def service_status(applicant_id):
    """PRD 2.10: SUSPENDED for as long as any proceeding sits in ACTIVE."""
    for p in proceedings_of(applicant_id):
        if p["status"] == "ACTIVE":
            return "SUSPENDED"
    return "ACTIVE"
