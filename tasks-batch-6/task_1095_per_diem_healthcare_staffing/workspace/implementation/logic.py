"""Business calculations, eligibility gates, reliability recompute, fill posture."""
from datetime import timedelta
from decimal import Decimal

import store
from store import (db, now, new_id, parse_iso, render_dt, rhu, rhu_cents,
                   hours_2dp)
from envelope import AppError

OCCUPIED = {"PENDING_CONFIRMATION", "CONFIRMED", "WORKED"}


# ---------------------------------------------------------------------------
# Common-field lifecycle
# ---------------------------------------------------------------------------
def stamp_new(d):
    ts = now()
    d["id"] = new_id()
    d["created_at"] = ts
    d["updated_at"] = ts
    d["version"] = 1
    d["_seq"] = db.next_seq()
    return d


def bump(entity):
    entity["version"] += 1
    entity["updated_at"] = now()


# ---------------------------------------------------------------------------
# Accessors
# ---------------------------------------------------------------------------
def order_of_shift(shift):
    return db.orders[shift["order_id"]]


def facility_of_order(order):
    return db.facilities[order["facility_id"]]


def facility_of_shift(shift):
    return facility_of_order(order_of_shift(shift))


def shift_of_assignment(a):
    return db.shifts[a["shift_id"]]


def order_of_assignment(a):
    return order_of_shift(shift_of_assignment(a))


def facility_of_assignment(a):
    return facility_of_shift(shift_of_assignment(a))


def assignment_of_timesheet(t):
    return db.assignments[t["assignment_id"]]


def facility_id_of_assignment(a):
    return order_of_assignment(a)["facility_id"]


# ---------------------------------------------------------------------------
# Time / hour calculations
# ---------------------------------------------------------------------------
def whole_minutes(start_dt, end_dt):
    return int((end_dt - start_dt).total_seconds() // 60)


def scheduled_hours(start_dt, end_dt):
    secs = Decimal(str((end_dt - start_dt).total_seconds()))
    return hours_2dp(secs / Decimal(3600))


def deemed_unpaid_break(raw_minutes, break_minutes):
    if raw_minutes >= store.UNPAID_BREAK_THRESHOLD_MINUTES and break_minutes < store.UNPAID_BREAK_MINUTES:
        return store.UNPAID_BREAK_MINUTES
    return break_minutes


def worked_hours_from(raw_minutes, unpaid_break_minutes):
    return hours_2dp(Decimal(raw_minutes - unpaid_break_minutes) / Decimal(60))


def differential_hours(start_dt, end_dt):
    """Night & weekend hours over the half-open [start, end) interval, per-minute."""
    total = whole_minutes(start_dt, end_dt)
    night = 0
    weekend = 0
    for k in range(total):
        t = start_dt + timedelta(minutes=k)
        h = t.hour
        if h >= store.NIGHT_WINDOW_START_HOUR or h < store.NIGHT_WINDOW_END_HOUR:
            night += 1
        if t.weekday() >= 5:  # Sat=5, Sun=6
            weekend += 1
    return hours_2dp(Decimal(night) / Decimal(60)), hours_2dp(Decimal(weekend) / Decimal(60))


def pay_amount(effective_rate, regular_hours, overtime_hours, night_hours, weekend_hours):
    er = Decimal(effective_rate)
    regular_component = rhu_cents(regular_hours * er)
    overtime_component = rhu_cents(overtime_hours * er * store.OVERTIME_MULTIPLIER)
    differential_component = (rhu_cents(night_hours * store.NIGHT_DIFF_CENTS_PER_HOUR)
                              + rhu_cents(weekend_hours * store.WEEKEND_DIFF_CENTS_PER_HOUR))
    return regular_component + overtime_component + differential_component


# ---------------------------------------------------------------------------
# Rate card selection
# ---------------------------------------------------------------------------
def select_rate_card(facility_id, specialty, shift_start_dt):
    candidates = []
    for rc in db.rate_cards.values():
        if rc["facility_id"] != facility_id or rc["specialty"] != specialty:
            continue
        eff_from = parse_iso(rc["effective_from"])
        if eff_from > shift_start_dt:
            continue
        if rc["effective_to"] is not None:
            eff_to = parse_iso(rc["effective_to"])
            if not (shift_start_dt < eff_to):
                continue
        candidates.append(rc)
    if not candidates:
        return None
    candidates.sort(key=lambda rc: (parse_iso(rc["effective_from"]), rc["created_at"], rc["_seq"]))
    return candidates[-1]


# ---------------------------------------------------------------------------
# ESTIMATED pay at shift creation
# ---------------------------------------------------------------------------
def compute_estimated(shift):
    start = parse_iso(shift["scheduled_start"])
    end = parse_iso(shift["scheduled_end"])
    raw = whole_minutes(start, end)
    unpaid = deemed_unpaid_break(raw, 0)
    worked = worked_hours_from(raw, unpaid)
    night, weekend = differential_hours(start, end)
    est_pay = pay_amount(shift["effective_rate_cents_per_hour"], worked, Decimal("0.00"), night, weekend)
    shift["estimated_hours"] = float(worked)
    shift["estimated_pay_cents"] = est_pay


# ---------------------------------------------------------------------------
# Credential lifecycle
# ---------------------------------------------------------------------------
def materialize_expiry(cred):
    if cred["status"] == "VERIFIED" and cred["expires_on"] is not None:
        if now() >= parse_iso(cred["expires_on"]):
            cred["status"] = "EXPIRED"
            bump(cred)


def clinician_credentials(clinician_id):
    return [c for c in db.credentials.values() if c["clinician_id"] == clinician_id]


# ---------------------------------------------------------------------------
# Eligibility gates. Each returns None on pass, or an error_id string on fail.
# ---------------------------------------------------------------------------
def credential_gate(clinician_id, shift):
    facility = facility_of_shift(shift)
    creds = clinician_credentials(clinician_id)
    for c in creds:
        materialize_expiry(c)
    end = parse_iso(shift["scheduled_end"])
    buffer_cutoff = end + timedelta(days=store.CREDENTIAL_BUFFER_DAYS)
    for req_type in facility["required_credential_types"]:
        held = [c for c in creds if c["credential_type"] == req_type
                and c["status"] in ("VERIFIED", "EXPIRED")]
        if not held:
            return "ERR_CREDENTIAL_MISSING"
        verified = [c for c in held if c["status"] == "VERIFIED"]
        if not verified:
            # was verified then lapsed -> EXPIRED
            return "ERR_CREDENTIAL_EXPIRED"
        # pick the verified credential with the latest expiry
        best = max(verified, key=lambda c: parse_iso(c["expires_on"]))
        if parse_iso(best["expires_on"]) < buffer_cutoff:
            return "ERR_CREDENTIAL_EXPIRED"
    return None


def occupied_shifts(clinician_id, exclude_shift_id=None):
    result = []
    for a in db.assignments.values():
        if a["clinician_id"] != clinician_id or a["work_status"] not in OCCUPIED:
            continue
        if a["shift_id"] == exclude_shift_id:
            continue
        result.append(db.shifts[a["shift_id"]])
    return result


def overlap_gate(clinician_id, shift):
    s = parse_iso(shift["scheduled_start"])
    e = parse_iso(shift["scheduled_end"])
    for o in occupied_shifts(clinician_id, shift["id"]):
        os = parse_iso(o["scheduled_start"])
        oe = parse_iso(o["scheduled_end"])
        if s < oe and os < e:
            return "ERR_SHIFT_OVERLAP"
    return None


def rest_gate(clinician_id, shift):
    s = parse_iso(shift["scheduled_start"])
    e = parse_iso(shift["scheduled_end"])
    min_secs = store.MIN_REST_HOURS_BETWEEN_SHIFTS * 3600
    for o in occupied_shifts(clinician_id, shift["id"]):
        os = parse_iso(o["scheduled_start"])
        oe = parse_iso(o["scheduled_end"])
        if oe <= s:
            gap = (s - oe).total_seconds()
        elif e <= os:
            gap = (os - e).total_seconds()
        else:
            continue  # overlapping -> handled by overlap gate
        if gap < min_secs:
            return "ERR_REST_PERIOD_VIOLATION"
    return None


def week_bounds(dt):
    monday = (dt - timedelta(days=dt.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return monday, monday + timedelta(days=7)


def weekly_hours_gate(clinician_id, shift):
    s = parse_iso(shift["scheduled_start"])
    wk_start, wk_end = week_bounds(s)
    total = Decimal(str(shift["scheduled_hours"]))
    for o in occupied_shifts(clinician_id, shift["id"]):
        os = parse_iso(o["scheduled_start"])
        if wk_start <= os < wk_end:
            total += Decimal(str(o["scheduled_hours"]))
    if total > Decimal(str(store.MAX_WEEKLY_SCHEDULED_HOURS)):
        return "ERR_WEEKLY_HOURS_EXCEEDED"
    return None


def eligibility_gates(clinician_id, shift):
    """Full award/claim eligibility stack (credential, overlap, rest, weekly).
    Returns error_id or None."""
    for gate in (credential_gate, overlap_gate, rest_gate, weekly_hours_gate):
        err = gate(clinician_id, shift)
        if err:
            return err
    return None


# ---------------------------------------------------------------------------
# Shift claim_count recompute
# ---------------------------------------------------------------------------
def recompute_claim_count(shift):
    cnt = sum(1 for c in db.claims.values()
              if c["shift_id"] == shift["id"] and c["status"] == "PENDING")
    shift["claim_count"] = cnt
    bump(shift)


# ---------------------------------------------------------------------------
# Reliability
# ---------------------------------------------------------------------------
def _weight(event):
    age_days = int((now() - parse_iso_event(event["occurred_at"])).total_seconds() // 86400)
    if age_days <= store.RELIABILITY_WEIGHT_TIER1_MAX_AGE_DAYS:
        return store.RELIABILITY_WEIGHT_TIER1
    if age_days <= store.RELIABILITY_WEIGHT_TIER2_MAX_AGE_DAYS:
        return store.RELIABILITY_WEIGHT_TIER2
    if age_days <= store.RELIABILITY_WEIGHT_TIER3_MAX_AGE_DAYS:
        return store.RELIABILITY_WEIGHT_TIER3
    return Decimal(0)


def parse_iso_event(dt_value):
    # occurred_at is stored as a datetime object
    return dt_value


def _clinician_events(clinician_id):
    return [e for e in db.reliability_events.values() if e["clinician_id"] == clinician_id]


def _score(clinician_id, included_statuses):
    window_start = now() - timedelta(days=store.RELIABILITY_WINDOW_DAYS)
    raw = Decimal(store.RELIABILITY_BASE_SCORE)
    for e in _clinician_events(clinician_id):
        if e["adjudication_status"] not in included_statuses:
            continue
        occ = e["occurred_at"]
        if occ < window_start or occ > now():
            continue
        w = _weight(e)
        raw = raw - Decimal(e["penalty_points"]) * w + Decimal(e["credit_points"]) * w
    score = int(rhu(raw, 0))
    if score < store.RELIABILITY_MIN_SCORE:
        score = store.RELIABILITY_MIN_SCORE
    if score > store.RELIABILITY_MAX_SCORE:
        score = store.RELIABILITY_MAX_SCORE
    return score


def reliability_recompute(clinician):
    cid = clinician["id"]
    window_start = now() - timedelta(days=store.RELIABILITY_WINDOW_DAYS)
    clinician["reliability_score"] = _score(cid, {"CONFIRMED"})
    clinician["provisional_reliability_score"] = _score(cid, {"PENDING", "CONFIRMED"})
    ns = 0
    for e in _clinician_events(cid):
        occ = e["occurred_at"]
        if occ < window_start or occ > now():
            continue
        if e["event_type"] == "NO_SHOW" and e["adjudication_status"] == "CONFIRMED":
            ns += 1
    clinician["no_show_count"] = ns

    prov = clinician["provisional_reliability_score"]
    if clinician["status"] == "ACTIVE" and prov < store.RELIABILITY_SUSPENSION_THRESHOLD:
        clinician["status"] = "SUSPENDED"
        bump(clinician)
        _decline_pending_claims(cid)
    elif clinician["status"] == "SUSPENDED" and prov >= store.RELIABILITY_SUSPENSION_THRESHOLD:
        clinician["status"] = "ACTIVE"
        bump(clinician)


def _decline_pending_claims(clinician_id):
    affected_shifts = set()
    for c in db.claims.values():
        if c["clinician_id"] == clinician_id and c["status"] == "PENDING":
            c["status"] = "DECLINED"
            bump(c)
            affected_shifts.add(c["shift_id"])
    for sid in affected_shifts:
        recompute_claim_count(db.shifts[sid])


def append_reliability_event(clinician, assignment_id, event_type, penalty, credit,
                             adjudication_status, reason):
    e = stamp_new({
        "clinician_id": clinician["id"],
        "assignment_id": assignment_id,
        "event_type": event_type,
        "penalty_points": penalty,
        "credit_points": credit,
        "occurred_at": now(),
        "adjudication_status": adjudication_status,
        "adjudicated_at": None,
        "reason": reason,
    })
    db.reliability_events[e["id"]] = e
    return e


# ---------------------------------------------------------------------------
# Order fill posture
# ---------------------------------------------------------------------------
def order_shifts(order_id):
    return [s for s in db.shifts.values() if s["order_id"] == order_id]


def order_fill_posture(order):
    if order["status"] == "CANCELLED":
        return
    shifts = order_shifts(order["id"])
    shift_count = len(shifts)
    open_count = sum(1 for s in shifts if s["status"] == "OPEN")
    filled_count = sum(1 for s in shifts if s["status"] in ("ASSIGNED", "COMPLETED"))
    completed_count = sum(1 for s in shifts if s["status"] == "COMPLETED")
    cancelled_count = sum(1 for s in shifts if s["status"] == "CANCELLED")

    if (shift_count >= 1 and open_count == 0 and filled_count == completed_count
            and completed_count + cancelled_count == shift_count):
        status = "CLOSED"
    elif filled_count == order["headcount"]:
        status = "FILLED"
    elif filled_count > 0:
        status = "PARTIALLY_FILLED"
    else:
        status = "OPEN"

    changed = (order["shift_count"] != shift_count or order["open_count"] != open_count
               or order["filled_count"] != filled_count
               or order["completed_count"] != completed_count
               or order["cancelled_count"] != cancelled_count
               or order["status"] != status)
    if changed:
        order["shift_count"] = shift_count
        order["open_count"] = open_count
        order["filled_count"] = filled_count
        order["completed_count"] = completed_count
        order["cancelled_count"] = cancelled_count
        order["status"] = status
        bump(order)
