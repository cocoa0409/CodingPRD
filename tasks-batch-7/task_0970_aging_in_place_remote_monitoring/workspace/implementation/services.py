"""Business logic: records, derived fields, alerts/escalation, telemetry side
effects, dose materialization, clock sweeps, proration, wellness scoring."""
import uuid
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal

import db
from util import iso, round1d, rhu_cents

OPEN_ALERT_STATUSES = {"RAISED", "NOTIFYING", "ESCALATED", "ACKNOWLEDGED"}
SEV_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}

OFFLINE_MINUTES = 90
DOSE_HORIZON_HOURS = 48
INACTIVITY_HOURS = 12
PUNCTUAL_GRACE_MINUTES = 15
MISSED_STREAK_CRITICAL = 2
MISSED_STREAK_ROUTINE = 3
LOW_BATTERY_THRESHOLD = 20
CRITICAL_BATTERY_THRESHOLD = 10
ACTIVE_DAY_MOTION_THRESHOLD = 3
AUTO_NOTE = "AUTO_RESOLVED_POSTURE_DEGRADED"


# ---------------------------------------------------------------- records ---

def create_record(store, fields, light=False):
    rec = dict(fields)
    rec["id"] = uuid.uuid4().hex
    rec["created_at"] = db.clock
    if not light:
        rec["updated_at"] = db.clock
        rec["version"] = 1
    rec["_seq"] = db.next_seq()
    store[rec["id"]] = rec
    return rec


def touch(rec):
    rec["updated_at"] = db.clock
    rec["version"] += 1


def ser(rec):
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = iso(v)
        elif isinstance(v, date):
            out[k] = v.isoformat()
        elif isinstance(v, Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out


def ser_senior(s):
    out = ser(s)
    out["monitoring_posture"] = posture(s["id"])
    out["open_alert_count"] = open_alert_count(s["id"])
    out["risk_tier"] = risk_tier(s["id"])
    return out


# ----------------------------------------------------- senior derivations ---

def current_subscription(senior_id):
    subs = [s for s in db.subscriptions.values() if s["senior_id"] == senior_id]
    if not subs:
        return None
    return max(subs, key=lambda s: s["_seq"])


def posture(senior_id):
    sub = current_subscription(senior_id)
    if sub is None:
        return "INACTIVE"
    ss = sub["service_status"]
    if ss == "ACTIVE":
        return "ACTIVE"
    if ss == "SUSPENDED":
        return "DEGRADED"
    return "INACTIVE"


def open_alert_count(senior_id):
    return sum(1 for a in db.alerts.values()
               if a["senior_id"] == senior_id and a["status"] in OPEN_ALERT_STATUSES)


def risk_tier(senior_id):
    for a in db.alerts.values():
        if (a["senior_id"] == senior_id and a["severity"] == "CRITICAL"
                and a["status"] in OPEN_ALERT_STATUSES):
            return "ELEVATED"
    for s in db.medication_schedules.values():
        if (s["senior_id"] == senior_id and s["status"] == "ACTIVE"
                and s["criticality"] == "CRITICAL" and s["missed_streak"] >= 3):
            return "ELEVATED"
    return "STANDARD"


# ------------------------------------------------------- alerts & tree -----

def has_open_alert(senior_id=None, alert_type=None, device_id=None):
    for a in db.alerts.values():
        if a["status"] not in OPEN_ALERT_STATUSES:
            continue
        if senior_id is not None and a["senior_id"] != senior_id:
            continue
        if alert_type is not None and a["alert_type"] != alert_type:
            continue
        if device_id is not None and a.get("device_id") != device_id:
            continue
        return True
    return False


def eligible_contacts(senior_id, severity):
    rank = SEV_RANK[severity]
    entries = [e for e in db.contacts.values()
               if e["senior_id"] == senior_id and e["status"] == "ACTIVE"
               and SEV_RANK[e["min_severity"]] <= rank]
    entries.sort(key=lambda e: (e["priority_rank"], e["created_at"], e["_seq"]))
    return entries


def create_notification(alert, entry, level):
    return create_record(db.notifications, {
        "alert_id": alert["id"],
        "contact_entry_id": entry["id"],
        "caregiver_id": entry["caregiver_id"],
        "level": level,
        "status": "SENT",
        "sent_at": db.clock,
    }, light=True)


def start_notification_round(alert):
    entries = eligible_contacts(alert["senior_id"], alert["severity"])
    if entries:
        create_notification(alert, entries[0], 1)
        alert["status"] = "NOTIFYING"
        alert["escalation_level"] = 1
    # else: stays RAISED in the monitoring-center queue


def create_alert(senior_id, alert_type, severity, device_id=None, manual=False):
    """Posture gate: non-CRITICAL alerts are suppressed unless posture is ACTIVE.
    CRITICAL alerts (and manually raised alerts) bypass the gate."""
    if not manual and severity != "CRITICAL" and posture(senior_id) != "ACTIVE":
        return None
    alert = create_record(db.alerts, {
        "senior_id": senior_id,
        "device_id": device_id,
        "alert_type": alert_type,
        "severity": severity,
        "status": "RAISED",
        "escalation_level": 0,
        "escalation_exhausted": False,
        "reopen_count": 0,
        "acknowledged_by_caregiver_id": None,
        "resolution_note": None,
    })
    start_notification_round(alert)
    return alert


def supersede_sent_notifications(alert_id, except_notif_id=None, acked_notif_id=None):
    for n in db.notifications.values():
        if n["alert_id"] != alert_id or n["status"] != "SENT":
            continue
        if acked_notif_id is not None and n["id"] == acked_notif_id:
            n["status"] = "ACKED"
        elif except_notif_id is not None and n["id"] == except_notif_id:
            continue
        else:
            n["status"] = "SUPERSEDED"


def auto_resolve_alert(alert, note=AUTO_NOTE):
    alert["status"] = "RESOLVED"
    alert["resolution_note"] = note
    supersede_sent_notifications(alert["id"])
    touch(alert)


# ---------------------------------------------------------- telemetry -----

def handle_battery(device, reading):
    device["battery_percent"] = reading
    if reading > LOW_BATTERY_THRESHOLD:
        return
    open_medium = None
    open_any = False
    for a in db.alerts.values():
        if (a.get("device_id") == device["id"] and a["alert_type"] == "LOW_BATTERY"
                and a["status"] in OPEN_ALERT_STATUSES):
            open_any = True
            if a["severity"] == "MEDIUM":
                open_medium = a
    if reading <= CRITICAL_BATTERY_THRESHOLD and open_medium is not None:
        open_medium["severity"] = "HIGH"
        touch(open_medium)
    elif not open_any:
        sev = "HIGH" if reading <= CRITICAL_BATTERY_THRESHOLD else "MEDIUM"
        create_alert(device["senior_id"], "LOW_BATTERY", sev, device_id=device["id"])


def confirm_dose(dose, at):
    sched = db.medication_schedules[dose["schedule_id"]]
    dose["status"] = "TAKEN"
    dose["confirmed_at"] = at
    dose["punctual"] = at <= dose["scheduled_at"] + timedelta(minutes=PUNCTUAL_GRACE_MINUTES)
    if sched["missed_streak"] != 0:
        sched["missed_streak"] = 0
        touch(sched)


def match_dose(senior_id, observed_at):
    cands = []
    for d in db.doses.values():
        if d["senior_id"] != senior_id or d["status"] != "PENDING":
            continue
        sched = db.medication_schedules[d["schedule_id"]]
        if d["scheduled_at"] <= observed_at <= d["scheduled_at"] + timedelta(minutes=sched["window_minutes"]):
            cands.append(d)
    cands.sort(key=lambda d: (d["scheduled_at"], d["created_at"], d["_seq"]))
    if cands:
        confirm_dose(cands[0], observed_at)


def ingest_event(device, event_type, observed_at, battery, note):
    ev = create_record(db.events, {
        "device_id": device["id"],
        "senior_id": device["senior_id"],
        "event_type": event_type,
        "observed_at": observed_at,
        "battery_percent": battery,
        "note": note,
    }, light=True)
    if device["status"] != "DECOMMISSIONED":
        changed = False
        if device["status"] in ("INSTALLED", "OFFLINE"):
            device["status"] = "ONLINE"
            changed = True
        if device["last_seen_at"] != observed_at:
            device["last_seen_at"] = observed_at
            changed = True
        if battery is not None:
            handle_battery(device, battery)
            changed = True
        if changed:
            touch(device)
    if event_type == "FALL_DETECTED":
        create_alert(device["senior_id"], "FALL", "CRITICAL", device_id=device["id"])
    elif event_type == "PILL_DISPENSED":
        match_dose(device["senior_id"], observed_at)
    return ev


# --------------------------------------------------------- medication -----

def materialize_doses(sched):
    """Materialize PENDING DoseEvents for [now, now+48h) not yet materialized."""
    now = db.clock
    horizon = now + timedelta(hours=DOSE_HORIZON_HOURS)
    day = sched["start_date"]
    end_day = horizon.date()
    while day <= end_day:
        for tstr in sched["times_of_day"]:
            hh, mm = int(tstr[0:2]), int(tstr[3:5])
            sched_dt = datetime(day.year, day.month, day.day, hh, mm, tzinfo=timezone.utc)
            if now <= sched_dt < horizon:
                exists = any(d["schedule_id"] == sched["id"] and d["scheduled_at"] == sched_dt
                             for d in db.doses.values())
                if not exists:
                    create_record(db.doses, {
                        "schedule_id": sched["id"],
                        "senior_id": sched["senior_id"],
                        "scheduled_at": sched_dt,
                        "status": "PENDING",
                        "confirmed_at": None,
                        "punctual": None,
                    }, light=True)
        day += timedelta(days=1)


def end_schedule(sched):
    sched["status"] = "ENDED"
    touch(sched)
    for d in db.doses.values():
        if d["schedule_id"] == sched["id"] and d["status"] == "PENDING":
            d["status"] = "SKIPPED"


# ------------------------------------------------------------ sweeps ------

def run_sweeps():
    """Pinned sweep order (calculations.clock_sweep_order)."""
    now = db.clock

    # 1. Device offline detection
    for dev in list(db.devices.values()):
        if (dev["status"] == "ONLINE" and dev["last_seen_at"] is not None
                and now - dev["last_seen_at"] > timedelta(minutes=OFFLINE_MINUTES)):
            dev["status"] = "OFFLINE"
            touch(dev)
            if not has_open_alert(device_id=dev["id"], alert_type="DEVICE_OFFLINE"):
                create_alert(dev["senior_id"], "DEVICE_OFFLINE", "MEDIUM", device_id=dev["id"])

    # 2. Dose horizon extension
    for s in list(db.medication_schedules.values()):
        if s["status"] == "ACTIVE":
            materialize_doses(s)

    # 3. Dose window misses
    pending = [d for d in db.doses.values() if d["status"] == "PENDING"]
    pending.sort(key=lambda d: (d["scheduled_at"], d["_seq"]))
    for d in pending:
        sched = db.medication_schedules[d["schedule_id"]]
        if now > d["scheduled_at"] + timedelta(minutes=sched["window_minutes"]):
            d["status"] = "MISSED"
            sched["missed_streak"] += 1
            touch(sched)
            thr = MISSED_STREAK_CRITICAL if sched["criticality"] == "CRITICAL" else MISSED_STREAK_ROUTINE
            if (sched["missed_streak"] >= thr
                    and not has_open_alert(senior_id=d["senior_id"], alert_type="MISSED_MEDICATION")):
                sev = "HIGH" if sched["criticality"] == "CRITICAL" else "MEDIUM"
                create_alert(d["senior_id"], "MISSED_MEDICATION", sev)

    # 4. Alert notification timeouts / escalation / exhaustion
    for a in list(db.alerts.values()):
        if a["status"] not in ("NOTIFYING", "ESCALATED"):
            continue
        if a["severity"] != "CRITICAL" and posture(a["senior_id"]) != "ACTIVE":
            continue
        sent = [n for n in db.notifications.values()
                if n["alert_id"] == a["id"] and n["status"] == "SENT"]
        if not sent:
            continue
        latest = max(sent, key=lambda n: (n["sent_at"], n["_seq"]))
        entry = db.contacts.get(latest["contact_entry_id"])
        if entry is None:
            continue
        if now - latest["sent_at"] > timedelta(seconds=entry["response_timeout_seconds"]):
            latest["status"] = "TIMED_OUT"
            ranking = eligible_contacts(a["senior_id"], a["severity"])
            if a["escalation_level"] < len(ranking):
                nxt = ranking[a["escalation_level"]]
                a["escalation_level"] += 1
                create_notification(a, nxt, a["escalation_level"])
                a["status"] = "ESCALATED"
            else:
                a["escalation_exhausted"] = True
            touch(a)

    # 5. Inactivity detection
    for s in db.seniors.values():
        sid = s["id"]
        if posture(sid) != "ACTIVE":
            continue
        online_motion = any(d for d in db.devices.values()
                            if d["senior_id"] == sid and d["device_type"] == "MOTION"
                            and d["status"] == "ONLINE")
        if not online_motion:
            continue
        cutoff = now - timedelta(hours=INACTIVITY_HOURS)
        recent = any(e for e in db.events.values()
                     if e["senior_id"] == sid and e["event_type"] == "MOTION"
                     and e["observed_at"] >= cutoff)
        if recent:
            continue
        if has_open_alert(senior_id=sid, alert_type="INACTIVITY"):
            continue
        create_alert(sid, "INACTIVITY", "HIGH")

    # 6. Check-in compliance
    for s in db.seniors.values():
        sid = s["id"]
        sub = current_subscription(sid)
        if sub is None or sub["service_status"] != "ACTIVE":
            continue
        plan = db.plans.get(sub["plan_id"])
        if plan is None:
            continue
        last_ci = max((c["occurred_at"] for c in db.checkins.values()
                       if c["senior_id"] == sid), default=None)
        base = sub.get("_activated_at")
        candidates = [x for x in (last_ci, base) if x is not None]
        if not candidates:
            continue
        last = max(candidates)
        if (now - last > timedelta(hours=plan["checkin_interval_hours"])
                and not has_open_alert(senior_id=sid, alert_type="MISSED_CHECKIN")):
            create_alert(sid, "MISSED_CHECKIN", "LOW")

    # 7. Appointment no-show
    for appt in list(db.appointments.values()):
        if appt["status"] in ("SCHEDULED", "CONFIRMED") and now > appt["window_end"]:
            appt["status"] = "NO_SHOW"
            touch(appt)


# ---------------------------------------------------------- proration -----

def run_change_plan(sub, new_plan, mode):
    old_plan = db.plans[sub["plan_id"]]
    now = db.clock
    kits = [k for k in db.kits.values() if k["senior_id"] == sub["senior_id"]]
    kit_sensors = max(kits, key=lambda k: k["_seq"])["motion_sensor_count"] if kits else 0

    extra_old = max(0, kit_sensors - old_plan["included_motion_sensors"])
    extra_new = max(0, kit_sensors - new_plan["included_motion_sensors"])

    if mode == "FULL_CYCLE_SWAP":
        plan_credit = old_plan["monthly_fee_cents"]
        sensor_credit = old_plan["extra_sensor_fee_cents"] * extra_old
        plan_charge = new_plan["monthly_fee_cents"]
        sensor_charge = new_plan["extra_sensor_fee_cents"] * extra_new
        sub["current_period_end"] = now + timedelta(days=30)
    else:  # DAILY_PRORATE
        cpe = sub.get("current_period_end")
        if cpe is None:
            days_remaining = 0
        else:
            days_remaining = int((cpe - now).total_seconds() // 86400)
            days_remaining = max(0, min(30, days_remaining))
        plan_credit = rhu_cents(Decimal(old_plan["monthly_fee_cents"]) * days_remaining / 30)
        sensor_credit = rhu_cents(Decimal(old_plan["extra_sensor_fee_cents"] * extra_old)
                                  * days_remaining / 30)
        plan_charge = rhu_cents(Decimal(new_plan["monthly_fee_cents"]) * days_remaining / 30)
        sensor_charge = rhu_cents(Decimal(new_plan["extra_sensor_fee_cents"] * extra_new)
                                  * days_remaining / 30)

    total_credit = plan_credit + sensor_credit
    total_charge = plan_charge + sensor_charge
    net = total_charge - total_credit
    if net >= 0:
        sub["lifetime_charged_cents"] += net
    else:
        sub["lifetime_credited_cents"] += -net
        sub["billing_credit_cents"] += -net
    sub["last_change_plan_credit_cents"] = plan_credit
    sub["last_change_sensor_credit_cents"] = sensor_credit
    sub["last_change_total_credit_cents"] = total_credit
    sub["last_change_total_charge_cents"] = total_charge
    sub["last_change_net_cents"] = net
    sub["plan_id"] = new_plan["id"]
    touch(sub)


# ---------------------------------------------------- wellness scoring ----

def compute_report_metrics(senior_id, ps, pe, mode):
    now = db.clock

    # activity_score
    motion_days = {}
    for e in db.events.values():
        if (e["senior_id"] == senior_id and e["event_type"] == "MOTION"
                and ps <= e["observed_at"] < pe):
            motion_days[e["observed_at"].date()] = motion_days.get(e["observed_at"].date(), 0) + 1
    active_days = sum(1 for c in motion_days.values() if c >= ACTIVE_DAY_MOTION_THRESHOLD)
    if mode == "FINAL":
        divisor = Decimal((pe - ps).total_seconds()) / Decimal(86400)
    else:
        elapsed = int((now - ps).total_seconds() // 86400)
        divisor = Decimal(max(1, elapsed))
    if divisor <= 0:
        divisor = Decimal(1)
    activity = round1d(min(Decimal(100), Decimal(100) * Decimal(active_days) / divisor))

    # adherence_pct
    weights = []
    for d in db.doses.values():
        if d["senior_id"] != senior_id or not (ps <= d["scheduled_at"] < pe):
            continue
        if d["status"] == "TAKEN":
            weights.append(Decimal("1.0") if d["punctual"] else Decimal("0.5"))
        elif d["status"] == "MISSED":
            weights.append(Decimal("0.0"))
        elif d["status"] == "PENDING" and mode == "PROVISIONAL" and d["scheduled_at"] <= now:
            weights.append(Decimal("1.0"))
    if not weights:
        adherence = Decimal("100.0")
    else:
        adherence = round1d(Decimal(100) * sum(weights) / Decimal(len(weights)))

    # device_health_pct
    health = 100
    for dev in db.devices.values():
        if dev["senior_id"] != senior_id or dev["status"] == "DECOMMISSIONED":
            continue
        if dev["status"] == "OFFLINE":
            health -= 10
        if dev["battery_percent"] <= LOW_BATTERY_THRESHOLD:
            health -= 5
    health = max(0, health)
    health_dec = Decimal(health).quantize(Decimal("0.1"))

    # wellness_index: weighting first, penalty second, cap third, rounding last
    raw = Decimal("0.40") * activity + Decimal("0.35") * adherence + Decimal("0.25") * health_dec
    if adherence < 60:
        raw = raw * Decimal("0.8")
    fall_cap = False
    for a in db.alerts.values():
        if (a["senior_id"] == senior_id and a["alert_type"] == "FALL"
                and ps <= a["created_at"] < pe and a["status"] != "FALSE_ALARM"):
            raw = min(raw, Decimal(59))
            fall_cap = True
            break
    index = round1d(raw)

    alert_count = sum(1 for a in db.alerts.values()
                      if a["senior_id"] == senior_id and ps <= a["created_at"] < pe)

    return {
        "activity_score": float(activity),
        "adherence_pct": float(adherence),
        "device_health_pct": float(health_dec),
        "wellness_index": float(index),
        "fall_cap_applied": fall_cap,
        "alert_count": alert_count,
    }


def adherence_today(senior_id):
    now = db.clock
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    weights = []
    for d in db.doses.values():
        if d["senior_id"] != senior_id:
            continue
        if day_start <= d["scheduled_at"] <= now and d["status"] in ("TAKEN", "MISSED"):
            if d["status"] == "TAKEN":
                weights.append(Decimal("1.0") if d["punctual"] else Decimal("0.5"))
            else:
                weights.append(Decimal("0.0"))
    if not weights:
        return 100.0
    return float(round1d(Decimal(100) * sum(weights) / Decimal(len(weights))))
