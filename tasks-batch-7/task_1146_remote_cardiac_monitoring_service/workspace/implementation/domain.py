"""Domain logic: SLA deadlines, fatigue figures, billing math, strike cascade, sweep."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from clock import now
from db import base_record, touch
from response import serialize

# Fee schedule (integer cents per 30 days), per monitor type
TC_FEE = {"HOLTER": 18075, "EVENT": 54915, "IMPLANTABLE": 90000}
PC_FEE = {"HOLTER": 2425, "EVENT": 5205, "IMPLANTABLE": 12000}
MIN_BILLABLE_DAYS = 10
WINDOW_DAYS = 30
GAP_HOURS = 48
FINAL_SLA_HOURS = 72


def round_half_up_2(value_decimal):
    return value_decimal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round_half_up_0(value_decimal):
    return int(value_decimal.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------- technicians
def fatigue_index_dec(load, capacity):
    return round_half_up_2(Decimal(load) / Decimal(capacity))


def throughput_index_dec(ack_total, load, capacity, created_at, at):
    full_days = int((at - created_at).total_seconds() // 86400)
    days = max(1, full_days)
    return round_half_up_2(Decimal(ack_total + load) / Decimal(capacity * days))


def fatigue_status_of(fatigue_dec):
    if fatigue_dec >= Decimal("0.80"):
        return "FATIGUED"
    if fatigue_dec >= Decimal("0.60"):
        return "AT_RISK"
    return "NORMAL"


def serialize_technician(t):
    d = serialize(t)
    load = t["open_alert_load"]
    cap = t["shift_capacity"]
    fi = fatigue_index_dec(load, cap)
    ti = throughput_index_dec(t["alerts_acknowledged_total"], load, cap,
                              t["created_at"], now())
    d["fatigue_index"] = float(fi)
    d["throughput_index"] = float(ti)
    d["fatigue_status"] = fatigue_status_of(fi)
    return d


# ---------------------------------------------------------------- SLA
def _next_0800(t):
    if t.hour < 8:
        return t.replace(hour=8, minute=0, second=0, microsecond=0)
    return (t + timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)


def compute_sla_deadline(severity, detected_at):
    """BUSINESS_HOURS variant: business hours are 08:00 <= t < 20:00 UTC daily."""
    if severity == "CRITICAL":
        return detected_at + timedelta(minutes=15)
    in_hours = 8 <= detected_at.hour < 20
    if severity == "URGENT":
        if in_hours:
            return detected_at + timedelta(minutes=60)
        return _next_0800(detected_at) + timedelta(minutes=30)
    # ROUTINE
    if in_hours:
        return detected_at + timedelta(minutes=1440)
    return _next_0800(detected_at) + timedelta(minutes=120)


# ---------------------------------------------------------------- pricing
def price_lines(monitor_type, days):
    """Per-line round_half_up to whole cents, then sum (never round the sum)."""
    tc = round_half_up_0(Decimal(TC_FEE[monitor_type]) * Decimal(days) / Decimal(30))
    pc = round_half_up_0(Decimal(PC_FEE[monitor_type]) * Decimal(days) / Decimal(30))
    return tc, pc, tc + pc


def whole_days_overlap(start, end, intervals):
    """Whole 24h days of overlap between [start, end) and the union of intervals."""
    clipped = []
    for s, e in intervals:
        a, b = max(s, start), min(e, end)
        if a < b:
            clipped.append((a, b))
    clipped.sort()
    total_seconds = 0.0
    cur_s = cur_e = None
    for s, e in clipped:
        if cur_s is None:
            cur_s, cur_e = s, e
        elif s <= cur_e:
            if e > cur_e:
                cur_e = e
        else:
            total_seconds += (cur_e - cur_s).total_seconds()
            cur_s, cur_e = s, e
    if cur_s is not None:
        total_seconds += (cur_e - cur_s).total_seconds()
    return int(total_seconds // 86400)


# ------------------------------------------------------- notification attempt
def resolve_ordering_physician_id(alert):
    ep = db.episodes.get(alert["episode_id"])
    if not ep:
        return None
    en = db.enrollments.get(ep["enrollment_id"])
    if not en:
        return None
    od = db.orders.get(en["order_id"])
    return od["ordering_physician_id"] if od else None


def create_attempt(alert, channel):
    t = now()
    att = base_record()
    att.update({
        "alert_id": alert["id"],
        "physician_id": resolve_ordering_physician_id(alert),
        "channel": channel,
        "attempted_at": t,
        "status": "PENDING",
        "within_sla": None,
    })
    db.attempts[att["id"]] = att
    alert["notification_attempt_count"] += 1
    return att


# ------------------------------------------------------------- strike cascade
def map_strikes(n):
    if n <= 0:
        return "COMPLIANT"
    if n <= 2:
        return "WATCH"
    return "SUSPENDED"


def record_compliance_event(episode, event_type):
    """Create a ComplianceEvent and apply the strike cascade. Returns the event."""
    t = now()
    ev = base_record()
    ev.update({
        "episode_id": episode["id"],
        "event_type": event_type,
        "status": "OPEN",
        "resolution_action": None,
    })
    db.compliance_events[ev["id"]] = ev

    episode["strike_count"] += 1
    if episode["clinical_status"] == "MONITORING":
        new_status = map_strikes(episode["strike_count"])
        if new_status != episode["compliance_status"]:
            episode["compliance_status"] = new_status
            if new_status == "SUSPENDED":
                iv = base_record()
                iv.update({"episode_id": episode["id"], "started_at": t, "ended_at": None})
                db.suspension_intervals[iv["id"]] = iv
    touch(episode)

    patient = db.patients.get(episode["patient_id"])
    if patient is not None:
        patient["open_compliance_events"] += 1
        touch(patient)
    return ev


# ---------------------------------------------------------------- billing
def mature_period(period, at):
    """ACCRUING -> READY: compute billable_days and FINAL per-line amounts."""
    ep = db.episodes[period["episode_id"]]
    intervals = []
    for iv in db.suspension_intervals.values():
        if iv["episode_id"] == ep["id"]:
            intervals.append((iv["started_at"], iv["ended_at"] if iv["ended_at"] else at))
    overlap = whole_days_overlap(period["start_date"], period["end_date"], intervals)
    billable = period["window_days"] - overlap
    if billable < 0:
        billable = 0
    period["billable_days"] = billable
    tc, pc, total = price_lines(ep["monitor_type"], billable)
    period["tc_amount_cents"] = tc
    period["pc_amount_cents"] = pc
    period["total_amount_cents"] = total
    period["status"] = "READY"
    touch(period)


# ---------------------------------------------------------------- sweep
def run_sweep():
    t = now()
    # (1) refurbishment completion
    for d in db.devices.values():
        if (d["status"] == "REFURBISHING" and d["refurbishment_due_at"] is not None
                and d["refurbishment_due_at"] <= t):
            d["status"] = "IN_STOCK"
            touch(d)
    # (2) shipment staging: at most one transition per shipment per sweep
    for s in db.shipments.values():
        if s["status"] == "LABEL_CREATED" and t > s["due_at"]:
            s["status"] = "OVERDUE"
            touch(s)
            ep = db.episodes.get(s["episode_id"])
            if ep is not None:
                record_compliance_event(ep, "RETURN_OVERDUE")
        elif s["status"] == "OVERDUE" and t > s["due_at"] + timedelta(days=20):
            s["status"] = "LOST"
            touch(s)
            d = db.devices.get(s["device_id"])
            if d is not None and d["status"] == "RETURN_IN_TRANSIT":
                d["status"] = "LOST"
                touch(d)
    # (3) alert SLA escalation
    for a in db.alerts.values():
        if a["status"] in ("NEW", "ACKNOWLEDGED", "TRIAGED") and a["sla_deadline"] < t:
            a["status"] = "ESCALATED"
            create_attempt(a, "ESCALATION")
            touch(a)
    # (4) transmission gap detection + strike cascade
    for ep in db.episodes.values():
        if ep["clinical_status"] != "MONITORING":
            continue
        cands = [ep["started_at"]]
        rec = [tr["received_at"] for tr in db.transmissions.values()
               if tr["episode_id"] == ep["id"] and tr["status"] == "PROCESSED"]
        if rec:
            cands.append(max(rec))
        gaps = [ev["created_at"] for ev in db.compliance_events.values()
                if ev["episode_id"] == ep["id"] and ev["event_type"] == "TRANSMISSION_GAP"]
        if gaps:
            cands.append(max(gaps))
        base = max(cands)
        open_gap = any(ev for ev in db.compliance_events.values()
                       if ev["episode_id"] == ep["id"]
                       and ev["event_type"] == "TRANSMISSION_GAP"
                       and ev["status"] == "OPEN")
        if (t - base) >= timedelta(hours=GAP_HOURS) and not open_gap:
            record_compliance_event(ep, "TRANSMISSION_GAP")
    # (5) billing window readiness
    for p in db.billing_periods.values():
        if p["status"] == "ACCRUING" and p["end_date"] <= t:
            mature_period(p, t)
