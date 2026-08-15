"""Business services: serializers, class forecast, ledger, currency, medical,
bid ranking, and cascades. All rule constants come straight from the PRD."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from db import store
from errors import ApiError
from util import render_ts

# ---- Rule constants (PRD §3) ------------------------------------------------
ATP_MINIMUM_HOURS = 1500
RECORDS_RESPONSE_WINDOW_DAYS = 30
GROUND_SCHOOL_FEE_CENTS = 150000
IOE_RATE_CENTS_PER_HOUR = 9000
CHECKRIDE_FEE_CENTS = 120000
RETRAINING_SURCHARGE_RATE = Decimal("0.25")
MILESTONE_PASS_SCORE = 80
MAX_CHECKRIDE_ATTEMPTS = 2
RECENCY_WINDOW_DAYS = 90
WARNING_BAND_DAYS = 7
LAPSED_TO_EXPIRED_DAYS = 365
FIRST_CLASS_MONTHS_UNDER_40 = 12
FIRST_CLASS_MONTHS_40_PLUS = 6
THIRD_CLASS_MONTHS_UNDER_40 = 60
THIRD_CLASS_MONTHS_40_PLUS = 24
INSTRUCTOR_BUFFER = timedelta(minutes=30)

PHASE_SURVIVAL = {
    "GROUND_SCHOOL": Decimal("0.90"),
    "SIMULATOR": Decimal("0.95"),
    "CHECKRIDE": Decimal("0.97"),
    "IOE": Decimal("0.98"),
}
PHASE_ORDER = {"GROUND_SCHOOL": 0, "SIMULATOR": 1, "CHECKRIDE": 2, "IOE": 3, "DONE": 4}
PHASE_NEXT = {"GROUND_SCHOOL": "SIMULATOR", "SIMULATOR": "CHECKRIDE", "IOE": "DONE"}

ACTIVE_ENROLLMENT_STATES = {"TENTATIVE", "CONFIRMED", "IN_PROGRESS", "REMEDIATION"}
CONFIRMED_ENROLLMENT_STATES = {"CONFIRMED", "IN_PROGRESS", "REMEDIATION", "COMPLETED"}

TIER_BY_PHASE = {
    "GROUND_SCHOOL": {"GROUND", "CHECK_AIRMAN"},
    "SIMULATOR": {"SIMULATOR", "CHECK_AIRMAN"},
    "CHECKRIDE": {"CHECK_AIRMAN"},
    "IOE": {"CHECK_AIRMAN"},
}


# ---- Generic entity helpers --------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def stamp_new(entity):
    now = store.now()
    entity["id"] = new_id()
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    entity["_seq"] = store.next_seq()
    return entity


def touch(entity):
    entity["updated_at"] = store.now()


def bump(entity):
    entity["updated_at"] = store.now()
    entity["version"] += 1


# ---- Serializers (internal keys prefixed with _ are never emitted) -----------

def _base(e):
    return {
        "id": e["id"],
        "created_at": render_ts(e["created_at"]),
        "updated_at": render_ts(e["updated_at"]),
        "version": e["version"],
    }


def ser_applicant(a):
    d = _base(a)
    d.update({
        "full_name": a["full_name"],
        "email": a["email"],
        "license_number": a["license_number"],
        "total_flight_hours": a["total_flight_hours"],
        "status": a["status"],
        "seniority_number": a["seniority_number"],
        "current_equipment_id": a["current_equipment_id"],
        "cleared_at": render_ts(a["cleared_at"]),
        "ledger_balance_cents": a["ledger_balance_cents"],
    })
    return d


def ser_records_request(r):
    d = _base(r)
    d.update({
        "applicant_id": r["applicant_id"],
        "request_type": r["request_type"],
        "status": r["status"],
        "sent_at": render_ts(r["sent_at"]),
        "due_at": render_ts(r["due_at"]),
        "response_received_at": render_ts(r["response_received_at"]),
        "failure_reason": r["failure_reason"],
    })
    return d


def ser_equipment(e):
    d = _base(e)
    d.update({
        "code": e["code"],
        "name": e["name"],
        "simulator_cost_per_hour_cents": e["simulator_cost_per_hour_cents"],
        "ioe_hours_required": e["ioe_hours_required"],
        "landings_required_90d": e["landings_required_90d"],
    })
    return d


def ser_training_class(c):
    d = _base(c)
    d.update({
        "equipment_id": c["equipment_id"],
        "class_date": render_ts(c["class_date"]),
        "seat_capacity": c["seat_capacity"],
        "base_attrition_rate": c["base_attrition_rate"],
        "status": c["status"],
        "active_enrollment_count": c["active_enrollment_count"],
        "confirmed_count": c["confirmed_count"],
        "max_seats_sellable": c["max_seats_sellable"],
        "projected_completions_aggregate": c["projected_completions_aggregate"],
        "projected_completions_walk": c["projected_completions_walk"],
        "over_committed": c["over_committed"],
    })
    return d


def ser_enrollment(e):
    d = _base(e)
    d.update({
        "applicant_id": e["applicant_id"],
        "training_class_id": e["training_class_id"],
        "status": e["status"],
        "current_phase": e["current_phase"],
        "failed_attempts": e["failed_attempts"],
        "entered_remediation_at": render_ts(e["entered_remediation_at"]),
    })
    return d


def ser_training_event(e):
    d = _base(e)
    d.update({
        "enrollment_id": e["enrollment_id"],
        "instructor_id": e["instructor_id"],
        "simulator_slot_id": e["simulator_slot_id"],
        "phase": e["phase"],
        "event_type": e["event_type"],
        "scheduled_start": render_ts(e["scheduled_start"]),
        "scheduled_end": render_ts(e["scheduled_end"]),
        "status": e["status"],
        "score": e["score"],
        "billed_amount_cents": e["billed_amount_cents"],
    })
    return d


def ser_checkride(c):
    d = _base(c)
    d.update({
        "enrollment_id": c["enrollment_id"],
        "check_airman_id": c["check_airman_id"],
        "ride_type": c["ride_type"],
        "status": c["status"],
        "scheduled_at": render_ts(c["scheduled_at"]),
        "completed_at": render_ts(c["completed_at"]),
        "attempt_number": c["attempt_number"],
    })
    return d


def ser_qualification(q):
    d = _base(q)
    d.update({
        "applicant_id": q["applicant_id"],
        "equipment_id": q["equipment_id"],
        "currency_state": q["currency_state"],
        "operating_state": q["operating_state"],
        "qualified_at": render_ts(q["qualified_at"]),
        "landings_90d": q["landings_90d"],
        "landings_expiring_7d": q["landings_expiring_7d"],
        "lapsed_since": render_ts(q["lapsed_since"]),
        "last_evaluated_at": render_ts(q["last_evaluated_at"]),
    })
    return d


def ser_flight_activity(f):
    d = _base(f)
    d.update({
        "qualification_id": f["qualification_id"],
        "activity_date": render_ts(f["activity_date"]),
        "landings": f["landings"],
        "hours": f["hours"],
        "activity_type": f["activity_type"],
    })
    return d


def ser_medical(m):
    d = _base(m)
    d.update({
        "applicant_id": m["applicant_id"],
        "cert_class": m["cert_class"],
        "issued_at": render_ts(m["issued_at"]),
        "pilot_age_at_issue": m["pilot_age_at_issue"],
        "first_class_valid_through": render_ts(m["first_class_valid_through"]),
        "third_class_valid_through": render_ts(m["third_class_valid_through"]),
        "status": m["status"],
    })
    return d


def ser_bid_period(p):
    d = _base(p)
    d.update({
        "equipment_id": p["equipment_id"],
        "opens_at": render_ts(p["opens_at"]),
        "closes_at": render_ts(p["closes_at"]),
        "seats_available": p["seats_available"],
        "status": p["status"],
        "awarded_at": render_ts(p["awarded_at"]),
    })
    return d


def ser_bid(b):
    d = _base(b)
    d.update({
        "bid_period_id": b["bid_period_id"],
        "applicant_id": b["applicant_id"],
        "preference_rank": b["preference_rank"],
        "status": b["status"],
        "denial_reason": b["denial_reason"],
        "seniority_snapshot": b["seniority_snapshot"],
        "awarded_at": render_ts(b["awarded_at"]),
    })
    return d


def ser_instructor(i):
    d = _base(i)
    d.update({
        "full_name": i["full_name"],
        "instructor_type": i["instructor_type"],
        "daily_max_sessions": i["daily_max_sessions"],
    })
    return d


def ser_simulator_slot(s):
    d = _base(s)
    d.update({
        "equipment_id": s["equipment_id"],
        "start_at": render_ts(s["start_at"]),
        "end_at": render_ts(s["end_at"]),
        "status": s["status"],
    })
    return d


def ser_ledger_entry(e):
    # Append-only: id + created_at only; no updated_at / version.
    return {
        "id": e["id"],
        "created_at": render_ts(e["created_at"]),
        "applicant_id": e["applicant_id"],
        "enrollment_id": e["enrollment_id"],
        "entry_type": e["entry_type"],
        "amount_cents": e["amount_cents"],
        "provisional": e["provisional"],
        "memo": e["memo"],
    }


# ---- Lookups -----------------------------------------------------------------

def get_applicant(aid):
    a = store.applicants.get(aid)
    if a is None:
        raise ApiError("ERR_APPLICANT_NOT_FOUND", "Applicant %s not found" % aid)
    return a


def get_records_request(rid):
    r = store.records_requests.get(rid)
    if r is None:
        raise ApiError("ERR_RECORDS_REQUEST_NOT_FOUND", "RecordsRequest %s not found" % rid)
    return r


def get_equipment(eid):
    e = store.equipment.get(eid)
    if e is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "Equipment %s not found" % eid)
    return e


def get_class(cid):
    c = store.training_classes.get(cid)
    if c is None:
        raise ApiError("ERR_TRAINING_CLASS_NOT_FOUND", "TrainingClass %s not found" % cid)
    return c


def get_enrollment(eid):
    e = store.enrollments.get(eid)
    if e is None:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND", "Enrollment %s not found" % eid)
    return e


def get_event(eid):
    e = store.training_events.get(eid)
    if e is None:
        raise ApiError("ERR_TRAINING_EVENT_NOT_FOUND", "TrainingEvent %s not found" % eid)
    return e


def get_checkride(cid):
    c = store.checkrides.get(cid)
    if c is None:
        raise ApiError("ERR_CHECKRIDE_NOT_FOUND", "Checkride %s not found" % cid)
    return c


def get_qualification(qid):
    q = store.qualifications.get(qid)
    if q is None:
        raise ApiError("ERR_QUALIFICATION_NOT_FOUND", "Qualification %s not found" % qid)
    return q


def get_medical(mid):
    m = store.medical_certificates.get(mid)
    if m is None:
        raise ApiError("ERR_MEDICAL_CERTIFICATE_NOT_FOUND", "MedicalCertificate %s not found" % mid)
    return m


def get_bid_period(pid):
    p = store.bid_periods.get(pid)
    if p is None:
        raise ApiError("ERR_BID_PERIOD_NOT_FOUND", "BidPeriod %s not found" % pid)
    return p


def get_bid(bid):
    b = store.bids.get(bid)
    if b is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "Bid %s not found" % bid)
    return b


def get_instructor(iid):
    i = store.instructors.get(iid)
    if i is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "Instructor %s not found" % iid)
    return i


def get_slot(sid):
    s = store.simulator_slots.get(sid)
    if s is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "SimulatorSlot %s not found" % sid)
    return s


def get_flight_activity(fid):
    f = store.flight_activities.get(fid)
    if f is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "FlightActivity %s not found" % fid)
    return f


def get_ledger_entry(lid):
    e = store.cost_ledger.get(lid)
    if e is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "CostLedgerEntry %s not found" % lid)
    return e


def class_equipment(cls):
    return store.equipment.get(cls["equipment_id"])


def enrollment_class(enrollment):
    return store.training_classes.get(enrollment["training_class_id"])


def enrollment_equipment(enrollment):
    cls = enrollment_class(enrollment)
    return class_equipment(cls) if cls else None


# ---- Calculation: class_seat_forecast ----------------------------------------

def recompute_class(cls):
    """Pinned evaluation order: counts -> sellable ceiling -> both projection
    variants -> over_committed. Computed from pre-call state by callers."""
    enrollments = [e for e in store.enrollments.values() if e["training_class_id"] == cls["id"]]
    active = [e for e in enrollments if e["status"] in ACTIVE_ENROLLMENT_STATES]
    cls["active_enrollment_count"] = len(active)
    cls["confirmed_count"] = sum(1 for e in enrollments if e["status"] in CONFIRMED_ENROLLMENT_STATES)
    rate = Decimal(str(cls["base_attrition_rate"]))
    cap = Decimal(cls["seat_capacity"])
    cls["max_seats_sellable"] = int((cap * (Decimal(1) + rate)).to_integral_value(rounding=ROUND_FLOOR))
    cls["projected_completions_aggregate"] = int(
        (Decimal(len(active)) * (Decimal(1) - rate)).to_integral_value(rounding=ROUND_FLOOR)
    )

    def walk_key(e):
        applicant = store.applicants.get(e["applicant_id"])
        email = applicant["email"] if applicant else ""
        return (e["created_at"], email, e.get("_seq", 0))

    total = Decimal(0)
    for e in sorted(active, key=walk_key):
        if e["status"] in ("TENTATIVE", "CONFIRMED"):
            p = Decimal(1) - rate
        elif e["status"] == "REMEDIATION":
            p = Decimal("0.80")
        else:  # IN_PROGRESS -> per-phase survival lookup
            p = PHASE_SURVIVAL.get(e["current_phase"], Decimal(1))
        total += p
    cls["projected_completions_walk"] = int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    cls["over_committed"] = cls["active_enrollment_count"] > cls["max_seats_sellable"]


# ---- Calculation: ledger + training_footprint_cost ---------------------------

def insert_ledger(applicant_id, enrollment_id, entry_type, amount_cents, memo):
    entry = {
        "id": new_id(),
        "created_at": store.now(),
        "_seq": store.next_seq(),
        "applicant_id": applicant_id,
        "enrollment_id": enrollment_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "provisional": True,
        "memo": memo,
        "_reversed": False,
    }
    store.cost_ledger[entry["id"]] = entry
    recompute_applicant_balance(applicant_id)
    return entry


def recompute_applicant_balance(applicant_id):
    applicant = store.applicants.get(applicant_id)
    if applicant is None:
        return
    total = sum(e["amount_cents"] for e in store.cost_ledger.values() if e["applicant_id"] == applicant_id)
    applicant["ledger_balance_cents"] = total
    touch(applicant)


def event_duration_hours(event):
    delta = event["scheduled_end"] - event["scheduled_start"]
    micros = Decimal(delta.days * 86400 * 10**6 + delta.seconds * 10**6 + delta.microseconds)
    return micros / Decimal(3600 * 10**6)


def round_half_up_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def event_rate_card_cents(event):
    """Per-line billing for a TrainingEvent, rounded half-up to integer cents."""
    phase = event["phase"]
    if phase == "GROUND_SCHOOL":
        return GROUND_SCHOOL_FEE_CENTS
    if phase == "SIMULATOR":
        enrollment = store.enrollments.get(event["enrollment_id"])
        equipment = enrollment_equipment(enrollment) if enrollment else None
        rate = equipment["simulator_cost_per_hour_cents"] if equipment else 0
        return round_half_up_cents(event_duration_hours(event) * Decimal(rate))
    if phase == "IOE":
        return round_half_up_cents(event_duration_hours(event) * Decimal(IOE_RATE_CENTS_PER_HOUR))
    # CHECKRIDE-phase events bill the flat checkride fee.
    return CHECKRIDE_FEE_CENTS


def retraining_charge_cents():
    return round_half_up_cents(Decimal(CHECKRIDE_FEE_CENTS) * RETRAINING_SURCHARGE_RATE)


def reverse_enrollment_charges(enrollment, memo):
    """Insert a REVERSAL mirror for every not-yet-reversed charge of the enrollment."""
    for entry in sorted(
        (e for e in store.cost_ledger.values() if e["enrollment_id"] == enrollment["id"]),
        key=lambda e: e.get("_seq", 0),
    ):
        if entry["entry_type"] == "REVERSAL" or entry["_reversed"]:
            continue
        entry["_reversed"] = True
        insert_ledger(enrollment["applicant_id"], enrollment["id"], "REVERSAL", -entry["amount_cents"], memo)


def footprint(applicant_id):
    entries = [e for e in store.cost_ledger.values() if e["applicant_id"] == applicant_id]
    provisional_total = sum(e["amount_cents"] for e in entries)

    enrollment_ids = {e["id"] for e in store.enrollments.values() if e["applicant_id"] == applicant_id}
    events = [
        e for e in store.training_events.values()
        if e["enrollment_id"] in enrollment_ids and e["status"] in ("COMPLETED", "FAILED")
    ]
    events.sort(key=lambda e: (e["created_at"], e["scheduled_start"], e.get("_seq", 0)))
    rides = [
        c for c in store.checkrides.values()
        if c["enrollment_id"] in enrollment_ids and c["status"] in ("COMPLETED_PASS", "COMPLETED_FAIL")
    ]
    rides.sort(key=lambda c: (c["created_at"], c["scheduled_at"], c.get("_seq", 0)))

    lines = [event_rate_card_cents(e) for e in events]
    for c in rides:
        lines.append(CHECKRIDE_FEE_CENTS)
        if c["status"] == "COMPLETED_FAIL":
            lines.append(retraining_charge_cents())
    return {
        "applicant_id": applicant_id,
        "provisional_total_cents": provisional_total,
        "final_total_cents": sum(lines),
        "entry_count": len(entries),
    }


# ---- Calculation: currency_recency_check -------------------------------------

def recompute_landings(q, now=None):
    now = now or store.now()
    window_low = now - timedelta(days=RECENCY_WINDOW_DAYS)     # exclusive
    expire_cut = now - timedelta(days=RECENCY_WINDOW_DAYS - WARNING_BAND_DAYS)  # inclusive
    landings_90d = 0
    landings_expiring_7d = 0
    for fa in store.flight_activities.values():
        if fa["qualification_id"] != q["id"]:
            continue
        d = fa["activity_date"]
        if window_low < d <= now:
            landings_90d += fa["landings"]
            if d <= expire_cut:
                landings_expiring_7d += fa["landings"]
    q["landings_90d"] = landings_90d
    q["landings_expiring_7d"] = landings_expiring_7d
    return landings_90d, landings_expiring_7d


def evaluate_currency(q):
    """Run the recency check against the logical clock. Returns the evaluated
    next currency state. Applies the transition when one exists in the machine
    (refresh/scan legs: QUALIFIED<->CURRENCY_WARNING, {QUALIFIED,CURRENCY_WARNING}->LAPSED).
    LAPSED / REQUALIFYING / EXPIRED never move via this check."""
    now = store.now()
    landings_90d, landings_expiring_7d = recompute_landings(q, now)
    equipment = store.equipment.get(q["equipment_id"])
    required = equipment["landings_required_90d"] if equipment else 0
    if landings_90d >= required and (landings_90d - landings_expiring_7d) >= required:
        next_state = "QUALIFIED"
    elif landings_90d >= required:
        next_state = "CURRENCY_WARNING"
    else:
        next_state = "LAPSED"

    current = q["currency_state"]
    q["last_evaluated_at"] = now
    transitioned = False
    if current in ("QUALIFIED", "CURRENCY_WARNING") and next_state != current:
        q["currency_state"] = next_state
        if next_state == "LAPSED":
            q["lapsed_since"] = now
        transitioned = True
    touch(q)
    return transitioned


# ---- Calculation: medical_validity_window ------------------------------------

def _last_day_of_month(year, month):
    if month == 12:
        nxt = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        nxt = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return (nxt - timedelta(days=1)).day


def _add_months(year, month, n):
    total = (year * 12 + (month - 1)) + n
    return total // 12, total % 12 + 1


def medical_windows(issued_at, pilot_age_at_issue):
    if pilot_age_at_issue < 40:
        n1, n3 = FIRST_CLASS_MONTHS_UNDER_40, THIRD_CLASS_MONTHS_UNDER_40
    else:
        n1, n3 = FIRST_CLASS_MONTHS_40_PLUS, THIRD_CLASS_MONTHS_40_PLUS
    y1, m1 = _add_months(issued_at.year, issued_at.month, n1)
    y3, m3 = _add_months(issued_at.year, issued_at.month, n3)
    first_through = datetime(y1, m1, _last_day_of_month(y1, m1), tzinfo=timezone.utc)
    third_through = datetime(y3, m3, _last_day_of_month(y3, m3), tzinfo=timezone.utc)
    return first_through, third_through


def medical_status_at(cert, now):
    current_date = now.date()
    if current_date <= cert["first_class_valid_through"].date():
        return "VALID"
    if current_date <= cert["third_class_valid_through"].date():
        return "DOWNGRADED"
    return "EXPIRED"


def has_valid_first_medical(applicant_id):
    return any(
        m["applicant_id"] == applicant_id and m["cert_class"] == "FIRST" and m["status"] == "VALID"
        for m in store.medical_certificates.values()
    )


# ---- Cascades -----------------------------------------------------------------

def cancel_applicant_scheduled_events(applicant_id):
    """Every SCHEDULED TrainingEvent of any enrollment of the applicant -> CANCELLED.
    System cascade: updated_at refreshed, no version bump. Returns count."""
    enrollment_ids = {e["id"] for e in store.enrollments.values() if e["applicant_id"] == applicant_id}
    count = 0
    for ev in store.training_events.values():
        if ev["enrollment_id"] in enrollment_ids and ev["status"] == "SCHEDULED":
            ev["status"] = "CANCELLED"
            touch(ev)
            count += 1
    return count


def grounding_cascade(applicant_id):
    """Fires when the applicant loses first-class medical coverage (a certificate
    left VALID and no other VALID FIRST-class certificate remains): every
    qualification in operating_state ACTIVE -> GROUNDED, and every SCHEDULED
    TrainingEvent of the applicant's enrollments -> CANCELLED. System cascade:
    updated_at refreshed, no version bumps. Returns (grounded, events_cancelled)."""
    if has_valid_first_medical(applicant_id):
        return (0, 0)
    grounded = 0
    for q in store.qualifications.values():
        if q["applicant_id"] == applicant_id and q["operating_state"] == "ACTIVE":
            q["operating_state"] = "GROUNDED"
            touch(q)
            grounded += 1
    events_cancelled = cancel_applicant_scheduled_events(applicant_id)
    return (grounded, events_cancelled)


def restoration_sweep():
    """Grounded qualifications return to ACTIVE when a VALID FIRST-class medical
    exists again (scan-only, system transition: no version bump)."""
    for q in store.qualifications.values():
        if q["operating_state"] == "GROUNDED" and has_valid_first_medical(q["applicant_id"]):
            q["operating_state"] = "ACTIVE"
            touch(q)


def applicant_for_enrollment(enrollment):
    return store.applicants.get(enrollment["applicant_id"])


def find_qualification(applicant_id, equipment_id):
    for q in store.qualifications.values():
        if q["applicant_id"] == applicant_id and q["equipment_id"] == equipment_id:
            return q
    return None
