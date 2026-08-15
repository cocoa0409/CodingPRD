"""Ops snapshot sweep: hazard expiry, AMI comms evaluation, no-read escalation,
aggregates with aging buckets; plus SLA finalization."""
from datetime import timedelta

from db import db, stamp_new, touch
from util import parse_dt, parse_date, fmt_date, fmt_dt, rate_2dp, days_between
from services.cascades import hazard_resolution_cascade

AMI_MISS_THRESHOLD = 3
ENDPOINT_FAILURE_DAYS = 14
BACKLOG_AGED_DAYS = 7
HAZARD_TTL_DAYS = 30

ESC_BASE = 10
ESC_STREAK_W = 25
ESC_WINDOW_W = 5
ESC_URGENCY_DAYS = 7
ESC_HAZARD_BONUS = 15
ESC_DISPATCH_THRESHOLD = 40
ESC_SCORE_CAP = 100

SLA_TARGET_NUM = 197
SLA_TARGET_DEN = 200

COVERED_STATES = ("VALIDATED", "ESTIMATED", "SUPERSEDED")
BACKLOG_STATES = ("PENDING", "NO_READ_PENDING")


def _previous_snapshot_at(this_snapshot_at):
    """Greatest existing snapshot_at strictly before this one; None when first."""
    prevs = [
        parse_dt(s["snapshot_at"]) for s in db.snapshots.values()
        if parse_dt(s["snapshot_at"]) < this_snapshot_at
    ]
    return max(prevs) if prevs else None


def _step1_hazard_expiry(snapshot_at):
    flags = sorted(
        (h for h in db.hazards.values() if h["flag_status"] == "ACTIVE"),
        key=lambda h: (parse_dt(h["expires_at"]), h["_seq"]),
    )
    for h in flags:
        if parse_dt(h["expires_at"]) < snapshot_at:  # strict; equality stays ACTIVE
            h["flag_status"] = "EXPIRED"
            touch(h)
            hazard_resolution_cascade(h["service_account_id"], h["id"])


def _step2_ami_comms(snapshot_at):
    prev = _previous_snapshot_at(snapshot_at)
    meters = sorted(
        (m for m in db.meters.values()
         if m["meter_type"] == "AMI" and m["meter_status"] == "IN_SERVICE"),
        key=lambda m: (m["created_at"], m["_seq"]),
    )
    for m in meters:
        window_start = prev if prev is not None else parse_dt(m["created_at"])
        hit = any(
            r["meter_id"] == m["id"]
            and r["read_source"] == "AMI_REMOTE"
            and r["read_status"] != "REJECTED"
            and window_start < parse_dt(r["read_at"]) <= snapshot_at
            for r in db.reads.values()
        )
        if hit:
            if m["endpoint_comms_status"] != "COMMUNICATING" \
                    or m["consecutive_missed_days"] != 0 \
                    or m["non_communicating_since"] is not None:
                m["endpoint_comms_status"] = "COMMUNICATING"
                m["consecutive_missed_days"] = 0
                m["non_communicating_since"] = None
                touch(m)
            continue
        m["consecutive_missed_days"] += 1
        status = m["endpoint_comms_status"]
        if m["consecutive_missed_days"] >= AMI_MISS_THRESHOLD and status in (
            "COMMUNICATING", "DEGRADED",
        ):
            m["endpoint_comms_status"] = "NON_COMMUNICATING"
            m["non_communicating_since"] = fmt_dt(snapshot_at)
        elif status == "NON_COMMUNICATING" and m["non_communicating_since"] is not None:
            since = parse_dt(m["non_communicating_since"])
            if snapshot_at - since >= timedelta(days=ENDPOINT_FAILURE_DAYS):
                m["endpoint_comms_status"] = "FAILED"
        elif status in ("COMMUNICATING", "DEGRADED"):
            # misses 1..2 leave the meter in DEGRADED
            m["endpoint_comms_status"] = "DEGRADED"
        touch(m)


def _step3_escalation(snapshot_at, snapshot_date):
    candidates = []
    for stop in db.stops.values():
        if stop["stop_status"] != "NO_READ_PENDING":
            continue
        period = db.periods.get(stop["billing_cycle_period_id"])
        if not period or period["period_status"] not in ("WINDOW_OPEN", "WINDOW_CLOSED"):
            continue
        account = db.accounts.get(stop["service_account_id"])
        streak = account["estimated_read_streak"] if account else 0
        days_until_close = days_between(
            parse_date(period["read_window_close_date"]), snapshot_date
        )
        has_hazard = any(
            h["service_account_id"] == stop["service_account_id"]
            and h["flag_status"] == "ACTIVE"
            for h in db.hazards.values()
        )
        score = ESC_BASE \
            + ESC_STREAK_W * streak \
            + ESC_WINDOW_W * max(0, ESC_URGENCY_DAYS - days_until_close) \
            + (ESC_HAZARD_BONUS if has_hazard else 0)
        score = min(ESC_SCORE_CAP, score)
        candidates.append((score, days_until_close, stop))
    # pinned evaluation order: score DESC, days_until_window_close ASC, created ASC
    candidates.sort(key=lambda t: (-t[0], t[1], t[2]["created_at"], t[2]["_seq"]))
    for score, _days, stop in candidates:
        if score < ESC_DISPATCH_THRESHOLD:
            continue
        existing = any(
            w["route_stop_id"] == stop["id"]
            and w["work_order_type"] == "RE_READ"
            and w["work_order_status"] in ("OPEN", "DISPATCHED", "IN_PROGRESS", "REWORK")
            for w in db.work_orders.values()
        )
        if existing:
            continue
        wo = {
            "work_order_type": "RE_READ",
            "service_account_id": stop["service_account_id"],
            "meter_id": None,
            "route_stop_id": stop["id"],
            "investigation_id": None,
            "campaign_enrollment_id": None,
            "scheduled_date": fmt_date(snapshot_date),
            "work_shift": "FULL",
            "notes": None,
            "technician_id": None,
            "work_order_status": "OPEN",
            "new_meter_id": None,
            "old_final_read_value": None,
            "new_initial_read_value": None,
            "reread_value": None,
            "reread_at": None,
            "evidence_note": None,
            "completed_at": None,
        }
        stamp_new(wo)
        db.work_orders[wo["id"]] = wo


def _step4_aggregates(snap, snapshot_at, snapshot_date):
    eligible = [
        s for s in db.stops.values()
        if s["stop_status"] != "CANCELLED"
        and (lambda r: r is not None and r["route_status"] != "CANCELLED"
             and r["scheduled_date"] <= fmt_date(snapshot_date))(
            db.routes.get(s["route_id"]))
    ]
    covered = [s for s in eligible if s["stop_status"] in COVERED_STATES]
    backlog = [
        s for s in db.stops.values()
        if s["stop_status"] in BACKLOG_STATES
        and (lambda r: r is not None and r["route_status"] != "CANCELLED")(
            db.routes.get(s["route_id"]))
    ]
    aged_cutoff = snapshot_at - timedelta(days=BACKLOG_AGED_DAYS)
    aged = [s for s in backlog if parse_dt(s["created_at"]) <= aged_cutoff]
    snap["eligible_stop_count"] = len(eligible)
    snap["covered_stop_count"] = len(covered)
    snap["backlog_count"] = len(backlog)
    snap["backlog_aged_7plus_count"] = len(aged)
    snap["estimated_read_count"] = sum(
        1 for r in db.reads.values() if r["read_status"] == "ESTIMATED"
    )
    snap["validated_read_count"] = sum(
        1 for r in db.reads.values() if r["read_status"] == "VALIDATED"
    )
    snap["read_rate_percent"] = rate_2dp(len(covered), len(eligible))
    skipped = sum(1 for s in eligible if s["stop_status"] == "SKIPPED_HAZARD")
    snap["net_read_rate_percent"] = rate_2dp(len(covered), len(eligible) - skipped)
    snap["sla_breach"] = None


def run_sweep(snap):
    snapshot_at = parse_dt(snap["snapshot_at"])
    snapshot_date = snapshot_at.date()
    _step1_hazard_expiry(snapshot_at)
    _step2_ami_comms(snapshot_at)
    _step3_escalation(snapshot_at, snapshot_date)
    _step4_aggregates(snap, snapshot_at, snapshot_date)


def finalize_sla(snap):
    """Exact integer cross-multiplication; equality is NOT a breach."""
    snap["sla_breach"] = (
        snap["covered_stop_count"] * SLA_TARGET_DEN
        < snap["eligible_stop_count"] * SLA_TARGET_NUM
    )
