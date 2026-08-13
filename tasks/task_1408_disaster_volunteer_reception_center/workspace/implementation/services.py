"""Business logic: calculations, derived fields, state transitions, cascades.

Derived counters (filled_count, rostered_count, booked_seats, committed_hours,
verified_hours_total, risk scores, incident cost-share rollups) are computed
from source records at read time; posture and recognition_tier are stored.
Every mutation of a resource bumps its version by exactly 1 per API operation
and refreshes updated_at from the logical clock (PRD section 2.5/2.6).
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import g

import db

# --- Calculation constants ---------------------------------------------------

RATE_STANDARD_CENTS = 2800
RATE_ADVANCED_CENTS = 4600
OT_DAILY_THRESHOLD = Decimal("8.0")
OT_MULTIPLIER = Decimal("1.5")

FEDERAL_SHARE = Decimal("0.75")
STATE_SHARE = Decimal("0.125")

COMMITTED_HOUR_CAP = Decimal("40.00")

SEVERITY_POINTS = {"LOW": 5, "MEDIUM": 15, "HIGH": 30, "CRITICAL": 60}
NO_SHOW_PENALTY = 10
SUSPEND_THRESHOLD = 50
BLACKLIST_THRESHOLD = 100
DECAY_STEP1_HOURS = 168
DECAY_STEP2_HOURS = 720

CRITICAL_UNFILLED_THRESHOLD = 3
FROZEN_WINDOW_HOURS = 24
TURNAROUND_MINUTES = 45

GOLD_HOURS = Decimal("60.00")
SILVER_HOURS = Decimal("24.00")
BRONZE_HOURS = Decimal("8.00")
GOLD_RISK_CAP = 20

CLASS_RANK = {"STANDARD": 1, "ADVANCED": 2}

FILLED_STATES = ("CONFIRMED", "CHECKED_IN", "COMPLETED")      # filled_count / rostered_count
COMMITTED_STATES = ("CONFIRMED", "CHECKED_IN")                # committed_hours
PIPELINE_STATES = ("PROPOSED", "ACCEPTED")                    # keep a request out of OPEN
BOOKED_STATES = ("BOOKED", "BOARDED")                         # booked_seats


# --- Record primitives ---------------------------------------------------------

def create_record(store, fields):
    rec = {
        "id": db.new_id(),
        "version": 1,
        "created_at_dt": db.now(),
        "updated_at_dt": db.now(),
        "_seq": db.next_seq(),
    }
    rec.update(fields)  # a pre-set "id" in fields wins (volunteer self-registration)
    store[rec["id"]] = rec
    g.touched.add(id(rec))  # creation is version 1; no same-request bump
    return rec


def touch(rec):
    """Bump version once per API operation and refresh updated_at."""
    key = id(rec)
    if key in g.touched:
        return
    g.touched.add(key)
    rec["version"] += 1
    rec["updated_at_dt"] = db.now()


def hours2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def shift_duration_hours(start_at, end_at):
    seconds = Decimal(str((end_at - start_at).total_seconds()))
    return (seconds / Decimal(3600)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# --- Derived counters ------------------------------------------------------------

def assignments_of_volunteer(volunteer_id):
    return [a for a in db.assignments.values() if a["volunteer_id"] == volunteer_id]


def assignments_of_request(request_id):
    return [a for a in db.assignments.values() if a["support_request_id"] == request_id]


def assignments_of_shift(shift_id):
    return [a for a in db.assignments.values() if a["site_shift_id"] == shift_id]


def hour_entries_of_assignment(assignment_id):
    return [e for e in db.hour_entries.values() if e["assignment_id"] == assignment_id]


def filled_count(req):
    return sum(1 for a in assignments_of_request(req["id"]) if a["status"] in FILLED_STATES)


def rostered_count(shift):
    return sum(1 for a in assignments_of_shift(shift["id"]) if a["status"] in FILLED_STATES)


def booked_seats(trip):
    return sum(1 for b in db.seat_bookings.values() if b["trip_id"] == trip["id"] and b["status"] in BOOKED_STATES)


def committed_hours(volunteer_id):
    total = Decimal("0")
    for a in assignments_of_volunteer(volunteer_id):
        if a["status"] in COMMITTED_STATES:
            total += Decimal(str(db.shifts[a["site_shift_id"]]["duration_hours"]))
    return hours2(total)


def verified_hours_total(volunteer_id):
    total = Decimal("0")
    for a in assignments_of_volunteer(volunteer_id):
        for e in hour_entries_of_assignment(a["id"]):
            if e["status"] == "VERIFIED":
                total += e["hours"]
    return hours2(total)


# --- Risk scores -----------------------------------------------------------------

def _risk_sources(volunteer_id):
    """(points, t_event) pairs: substantiated reports and no-show assignments."""
    sources = []
    for r in db.risk_reports.values():
        if r["subject_volunteer_id"] == volunteer_id and r["status"] == "SUBSTANTIATED":
            sources.append((r["points_awarded"], r["adjudicated_at"]))
    for a in assignments_of_volunteer(volunteer_id):
        if a["status"] == "NO_SHOW":
            shift = db.shifts[a["site_shift_id"]]
            sources.append((NO_SHOW_PENALTY, shift["end_at"]))
    return sources


def _decayed(points, t_event):
    age_hours = (db.now() - t_event).total_seconds() / 3600.0
    if age_hours < DECAY_STEP1_HOURS:
        return points
    if age_hours < DECAY_STEP2_HOURS:
        return points // 2
    return 0


def risk_scores(volunteer_id):
    current = 0
    lifetime = 0
    for points, t_event in _risk_sources(volunteer_id):
        current += _decayed(points, t_event)
        lifetime += points
    return max(current, 0), lifetime


# --- Cost-share calculations -------------------------------------------------------

def qualifying_credential(volunteer_id, skill_code):
    """The volunteer's VERIFIED credential matching skill_code (highest class,
    then earliest created). Falls back to any matching credential record."""
    verified = [
        c for c in db.credentials.values()
        if c["volunteer_id"] == volunteer_id and c["skill_code"] == skill_code and c["status"] == "VERIFIED"
    ]
    pool = verified or [
        c for c in db.credentials.values()
        if c["volunteer_id"] == volunteer_id and c["skill_code"] == skill_code
    ]
    if not pool:
        return None
    pool.sort(key=lambda c: (-CLASS_RANK[c["credential_class"]], c["created_at_dt"], c["_seq"]))
    return pool[0]


def entry_value_cents(entry, assignment):
    """round_half_up(normal*rate + overtime*rate*1.5), once per entry."""
    req = db.support_requests[assignment["support_request_id"]]
    cred = qualifying_credential(assignment["volunteer_id"], req["required_skill"])
    rate = RATE_ADVANCED_CENTS if (cred and cred["credential_class"] == "ADVANCED") else RATE_STANDARD_CENTS
    hours = entry["hours"]
    normal = min(hours, OT_DAILY_THRESHOLD)
    overtime = hours - normal
    value = Decimal(normal) * rate + Decimal(overtime) * rate * OT_MULTIPLIER
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def incident_cost_share(incident_id):
    """Rollup over the incident's assignments' hour entries. Per-entry values are
    integers already; shares are computed federal, state, then local by subtraction."""
    provisional = 0
    verified = 0
    for a in db.assignments.values():
        if a["incident_id"] != incident_id:
            continue
        for e in hour_entries_of_assignment(a["id"]):
            if e["status"] in ("SUBMITTED", "DISPUTED", "VERIFIED"):
                provisional += e["entry_value_cents"]
            if e["status"] == "VERIFIED":
                verified += e["entry_value_cents"]
    federal = int((Decimal(verified) * FEDERAL_SHARE).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    state = int((Decimal(verified) * STATE_SHARE).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    local = verified - federal - state
    return {
        "provisional_cost_share_cents": provisional,
        "verified_cost_share_cents": verified,
        "federal_share_cents": federal,
        "state_share_cents": state,
        "local_share_cents": local,
    }


# --- Posture ------------------------------------------------------------------------

def derive_posture(incident_id):
    unfilled_critical = sum(
        1 for r in db.support_requests.values()
        if r["incident_id"] == incident_id
        and r["criticality"] == "CRITICAL"
        and r["status"] in ("OPEN", "MATCHING")
    )
    window_start = db.now() - timedelta(hours=FROZEN_WINDOW_HOURS)
    recent_critical_substantiation = False
    for r in db.risk_reports.values():
        if r["status"] != "SUBSTANTIATED" or r["severity"] != "CRITICAL":
            continue
        if r["adjudicated_at"] is None or r["adjudicated_at"] <= window_start:
            continue
        subject = db.volunteers.get(r["subject_volunteer_id"])
        if subject and subject["incident_id"] == incident_id:
            recent_critical_substantiation = True
            break
    red_shift_open = any(
        s["incident_id"] == incident_id
        and s["hazard_level"] == "RED"
        and s["status"] in ("OPEN_FOR_ROSTER", "LOCKED")
        for s in db.shifts.values()
    )
    if recent_critical_substantiation:
        return "FROZEN"
    if unfilled_critical >= CRITICAL_UNFILLED_THRESHOLD or red_shift_open:
        return "RESTRICTED"
    return "OPEN"


def recompute_posture(incident):
    """Posture is only ever evaluated while the lifecycle is ACTIVE."""
    if incident["lifecycle_status"] != "ACTIVE":
        return
    new_value = derive_posture(incident["id"])
    if new_value != incident["operational_posture"]:
        incident["operational_posture"] = new_value
        touch(incident)


# --- Automatic state reconciliation (PRD section 2.6) ---------------------------------

def recompute_request_status(req):
    """filled_count recompute + OPEN/MATCHING/FILLED reconciliation."""
    if req["status"] in ("OPEN", "MATCHING", "FILLED"):
        filled = filled_count(req)
        has_pipeline = any(a["status"] in PIPELINE_STATES for a in assignments_of_request(req["id"]))
        if filled >= req["headcount_needed"]:
            target = "FILLED"
        elif filled == 0 and not has_pipeline:
            target = "OPEN"
        else:
            target = "MATCHING"
        if target != req["status"]:
            req["status"] = target
    touch(req)  # every recompute is a mutation of the request


def recompute_shift_status(shift):
    """rostered_count recompute + OPEN_FOR_ROSTER/LOCKED reconciliation."""
    if shift["status"] in ("OPEN_FOR_ROSTER", "LOCKED"):
        target = "LOCKED" if rostered_count(shift) >= shift["capacity"] else "OPEN_FOR_ROSTER"
        if target != shift["status"]:
            shift["status"] = target
    touch(shift)


def maybe_undeploy(volunteer):
    """DEPLOYED -> READY when the volunteer's last CHECKED_IN assignment closes."""
    if volunteer["status"] != "DEPLOYED":
        return
    if not any(a["status"] == "CHECKED_IN" for a in assignments_of_volunteer(volunteer["id"])):
        volunteer["status"] = "READY"
        touch(volunteer)


def has_fresh_cleared_bg(volunteer_id):
    return any(
        b["volunteer_id"] == volunteer_id and b["status"] == "CLEARED" and b["expires_at"] > db.now()
        for b in db.background_checks.values()
    )


def has_verified_credential(volunteer_id):
    return any(
        c["volunteer_id"] == volunteer_id and c["status"] == "VERIFIED"
        for c in db.credentials.values()
    )


def has_current_briefing(volunteer_id):
    return any(
        c["volunteer_id"] == volunteer_id
        and c["clearance_type"] == "SAFETY_BRIEFING"
        and c["status"] == "ACTIVE"
        and c["valid_until"] is not None
        and c["valid_until"] > db.now()
        for c in db.clearances.values()
    )


def has_active_waiver(volunteer_id):
    return any(
        c["volunteer_id"] == volunteer_id
        and c["clearance_type"] == "LIABILITY_WAIVER"
        and c["status"] == "ACTIVE"
        for c in db.clearances.values()
    )


def has_issued_ppe(volunteer_id):
    return any(
        p["volunteer_id"] == volunteer_id and p["status"] == "ISSUED"
        for p in db.ppe_issuances.values()
    )


def reeval_volunteer_clearance(volunteer):
    """Automatic VETTING <-> CLEARED reconciliation."""
    if volunteer["status"] == "VETTING":
        if has_fresh_cleared_bg(volunteer["id"]) and has_verified_credential(volunteer["id"]):
            volunteer["status"] = "CLEARED"
            touch(volunteer)
    elif volunteer["status"] == "CLEARED":
        if not has_fresh_cleared_bg(volunteer["id"]) or not has_verified_credential(volunteer["id"]):
            volunteer["status"] = "VETTING"
            touch(volunteer)


# --- Cascades ---------------------------------------------------------------------------

def release_assignment_effects(assignment, counted):
    """Committed-hours / rostered_count / filled_count release with regressions."""
    req = db.support_requests[assignment["support_request_id"]]
    shift = db.shifts[assignment["site_shift_id"]]
    volunteer = db.volunteers[assignment["volunteer_id"]]
    if counted:
        touch(volunteer)  # committed_hours released
        recompute_shift_status(shift)
    recompute_request_status(req)


def cancel_bookings_of_assignment(assignment):
    for b in db.seat_bookings.values():
        if b["assignment_id"] == assignment["id"] and b["status"] in BOOKED_STATES:
            b["status"] = "CANCELLED"
            touch(b)
            touch(db.trips[b["trip_id"]])  # booked_seats recomputed


def cancel_assignment(assignment, counted):
    """Shared cancel/recall mechanics for one assignment (no state check)."""
    release_assignment_effects(assignment, counted)
    cancel_bookings_of_assignment(assignment)


def suspension_cascade(volunteer):
    """SUSPENSION CASCADE, applied in the spec's exact order."""
    # 1. Assignments: PROPOSED/ACCEPTED/CONFIRMED -> CANCELLED; CHECKED_IN -> RECALLED
    mine = sorted(assignments_of_volunteer(volunteer["id"]), key=lambda a: a["_seq"])
    for a in mine:
        if a["status"] in ("PROPOSED", "ACCEPTED", "CONFIRMED"):
            counted = a["status"] == "CONFIRMED"
            a["status"] = "CANCELLED"
            touch(a)
            # 2. per-assignment release and recomputes
            release_assignment_effects(a, counted)
        elif a["status"] == "CHECKED_IN":
            a["status"] = "RECALLED"
            touch(a)
            release_assignment_effects(a, True)
    # 3. Seat bookings of this volunteer in BOOKED/BOARDED -> CANCELLED
    for b in sorted(db.seat_bookings.values(), key=lambda x: x["_seq"]):
        if b["volunteer_id"] == volunteer["id"] and b["status"] in BOOKED_STATES:
            b["status"] = "CANCELLED"
            touch(b)
            touch(db.trips[b["trip_id"]])
    # 4. Incident posture recompute
    recompute_posture(db.incidents[volunteer["incident_id"]])


def withdraw_cascade(volunteer):
    """Release cascade: suspension items 1-2 and 4 (no RECALLED conversion) plus seats."""
    mine = sorted(assignments_of_volunteer(volunteer["id"]), key=lambda a: a["_seq"])
    for a in mine:
        if a["status"] in ("PROPOSED", "ACCEPTED", "CONFIRMED"):
            counted = a["status"] == "CONFIRMED"
            a["status"] = "CANCELLED"
            touch(a)
            release_assignment_effects(a, counted)
    for b in sorted(db.seat_bookings.values(), key=lambda x: x["_seq"]):
        if b["volunteer_id"] == volunteer["id"] and b["status"] in BOOKED_STATES:
            b["status"] = "CANCELLED"
            touch(b)
            touch(db.trips[b["trip_id"]])
    recompute_posture(db.incidents[volunteer["incident_id"]])


def request_cancel_cascade(req):
    mine = sorted(assignments_of_request(req["id"]), key=lambda a: a["_seq"])
    for a in mine:
        if a["status"] in ("PROPOSED", "ACCEPTED", "CONFIRMED"):
            counted = a["status"] == "CONFIRMED"
            a["status"] = "CANCELLED"
            touch(a)
            release_assignment_effects(a, counted)
            cancel_bookings_of_assignment(a)
        elif a["status"] == "CHECKED_IN":
            a["status"] = "RECALLED"
            touch(a)
            release_assignment_effects(a, True)
            cancel_bookings_of_assignment(a)
            maybe_undeploy(db.volunteers[a["volunteer_id"]])


def shift_cancel_cascade(shift):
    """SHIFT CANCELLATION CASCADE, in the spec's exact order."""
    # 1. Assignments on this shift
    mine = sorted(assignments_of_shift(shift["id"]), key=lambda a: a["_seq"])
    for a in mine:
        if a["status"] in ("PROPOSED", "ACCEPTED", "CONFIRMED"):
            counted = a["status"] == "CONFIRMED"
            a["status"] = "CANCELLED"
            touch(a)
            release_assignment_effects(a, counted)
            cancel_bookings_of_assignment(a)
        elif a["status"] == "CHECKED_IN":
            a["status"] = "RECALLED"
            touch(a)
            release_assignment_effects(a, True)
            cancel_bookings_of_assignment(a)
            maybe_undeploy(db.volunteers[a["volunteer_id"]])
    # 2. SCHEDULED trips ferrying to this shift -> CANCELLED (DEPARTED unaffected)
    cancelled_trips = []
    for t in sorted(db.trips.values(), key=lambda x: x["_seq"]):
        if t["site_shift_id"] == shift["id"] and t["status"] == "SCHEDULED":
            t["status"] = "CANCELLED"
            touch(t)
            cancelled_trips.append(t)
    # 3. Seat bookings on those trips in BOOKED/BOARDED -> CANCELLED
    for t in cancelled_trips:
        for b in sorted(db.seat_bookings.values(), key=lambda x: x["_seq"]):
            if b["trip_id"] == t["id"] and b["status"] in BOOKED_STATES:
                b["status"] = "CANCELLED"
                touch(b)
                touch(t)
    # 4. Incident posture recompute
    recompute_posture(db.incidents[shift["incident_id"]])


def cancel_trip_cascade(trip):
    for b in sorted(db.seat_bookings.values(), key=lambda x: x["_seq"]):
        if b["trip_id"] == trip["id"] and b["status"] in BOOKED_STATES:
            b["status"] = "CANCELLED"
            touch(b)
    touch(trip)  # booked_seats recomputed (to 0)


# --- Overlap rules ----------------------------------------------------------------------

def shift_conflict(volunteer_id, candidate_shift, exclude_assignment_id=None):
    """Half-open [start_at, end_at) overlap against CONFIRMED/CHECKED_IN shifts."""
    cs, ce = candidate_shift["start_at"], candidate_shift["end_at"]
    for a in assignments_of_volunteer(volunteer_id):
        if a["status"] not in COMMITTED_STATES:
            continue
        if exclude_assignment_id and a["id"] == exclude_assignment_id:
            continue
        other = db.shifts[a["site_shift_id"]]
        if cs < other["end_at"] and other["start_at"] < ce:
            return True
    return False


def vehicle_turnaround_conflict(incident_id, vehicle_id, depart_at, arrive_estimate_at):
    buffer = timedelta(minutes=TURNAROUND_MINUTES)
    for t in db.trips.values():
        if t["incident_id"] != incident_id or t["vehicle_id"] != vehicle_id:
            continue
        if t["status"] not in ("SCHEDULED", "DEPARTED"):
            continue
        if depart_at < t["arrive_estimate_at"] + buffer and t["depart_at"] < arrive_estimate_at + buffer:
            return True
    return False


def trip_overlap_conflict(volunteer_id, candidate_trip):
    """Volunteer holds a non-CANCELLED booking on an overlapping trip window."""
    cd, ca = candidate_trip["depart_at"], candidate_trip["arrive_estimate_at"]
    for b in db.seat_bookings.values():
        if b["volunteer_id"] != volunteer_id or b["status"] == "CANCELLED":
            continue
        if b["trip_id"] == candidate_trip["id"]:
            continue  # same trip is governed by the duplicate-booking rule
        other = db.trips[b["trip_id"]]
        if cd < other["arrive_estimate_at"] and other["depart_at"] < ca:
            return True
    return False


# --- Recognition tier ---------------------------------------------------------------------

def recognition_tier_for(volunteer):
    vht = verified_hours_total(volunteer["id"])
    _, lifetime = risk_scores(volunteer["id"])
    if vht >= GOLD_HOURS:
        base = "GOLD"
    elif vht >= SILVER_HOURS:
        base = "SILVER"
    elif vht >= BRONZE_HOURS:
        base = "BRONZE"
    else:
        base = "NONE"
    if base == "GOLD" and lifetime >= GOLD_RISK_CAP:
        return "SILVER"
    return base


# --- Clock sweep ----------------------------------------------------------------------------

def run_clock_sweep():
    now = db.now()
    affected_volunteers = set()
    for c in sorted(db.credentials.values(), key=lambda x: x["_seq"]):
        if c["status"] == "VERIFIED" and c["expires_at"] <= now:
            c["status"] = "EXPIRED"
            touch(c)
            affected_volunteers.add(c["volunteer_id"])
    for b in sorted(db.background_checks.values(), key=lambda x: x["_seq"]):
        if b["status"] == "CLEARED" and b["expires_at"] <= now:
            b["status"] = "EXPIRED"
            touch(b)
            affected_volunteers.add(b["volunteer_id"])
    for cl in sorted(db.clearances.values(), key=lambda x: x["_seq"]):
        if (
            cl["status"] == "ACTIVE"
            and cl["clearance_type"] == "SAFETY_BRIEFING"
            and cl["valid_until"] is not None
            and cl["valid_until"] <= now
        ):
            cl["status"] = "EXPIRED"
            touch(cl)
    for vid in affected_volunteers:
        reeval_volunteer_clearance(db.volunteers[vid])
    for inc in db.incidents.values():
        recompute_posture(inc)


# --- Serializers ------------------------------------------------------------------------------

def _base(rec):
    return {
        "id": rec["id"],
        "created_at": db.fmt_ts(rec["created_at_dt"]),
        "updated_at": db.fmt_ts(rec["updated_at_dt"]),
        "version": rec["version"],
    }


def incident_view(rec):
    out = _base(rec)
    out.update({
        "name": rec["name"],
        "lifecycle_status": rec["lifecycle_status"],
        "operational_posture": rec["operational_posture"],
        "ppe_stock": dict(rec["ppe_stock"]),
    })
    out.update(incident_cost_share(rec["id"]))
    out.update({
        "activated_at": db.fmt_ts(rec["activated_at"]),
        "demobilized_at": db.fmt_ts(rec["demobilized_at"]),
        "closed_at": db.fmt_ts(rec["closed_at"]),
    })
    return out


def volunteer_view(rec):
    out = _base(rec)
    current, lifetime = risk_scores(rec["id"])
    out.update({
        "incident_id": rec["incident_id"],
        "full_name": rec["full_name"],
        "phone": rec["phone"],
        "email": rec["email"],
        "home_locality": rec["home_locality"],
        "status": rec["status"],
        "registered_by_user_id": rec["registered_by_user_id"],
        "committed_hours": float(committed_hours(rec["id"])),
        "verified_hours_total": float(verified_hours_total(rec["id"])),
        "current_risk_score": current,
        "lifetime_risk_score": lifetime,
        "recognition_tier": rec["recognition_tier"],
        "demobilized_at": db.fmt_ts(rec["demobilized_at"]),
    })
    return out


def credential_view(rec):
    out = _base(rec)
    out.update({
        "volunteer_id": rec["volunteer_id"],
        "skill_code": rec["skill_code"],
        "credential_class": rec["credential_class"],
        "evidence_notes": rec["evidence_notes"],
        "expires_at": db.fmt_ts(rec["expires_at"]),
        "status": rec["status"],
        "verified_by_user_id": rec["verified_by_user_id"],
        "verified_at": db.fmt_ts(rec["verified_at"]),
    })
    return out


def background_check_view(rec):
    out = _base(rec)
    out.update({
        "volunteer_id": rec["volunteer_id"],
        "status": rec["status"],
        "adjudicated_by_user_id": rec["adjudicated_by_user_id"],
        "adjudicated_at": db.fmt_ts(rec["adjudicated_at"]),
        "expires_at": db.fmt_ts(rec["expires_at"]),
    })
    return out


def clearance_view(rec):
    out = _base(rec)
    out.update({
        "volunteer_id": rec["volunteer_id"],
        "clearance_type": rec["clearance_type"],
        "status": rec["status"],
        "completed_at": db.fmt_ts(rec["completed_at"]),
        "valid_until": db.fmt_ts(rec["valid_until"]),
        "revoked_reason": rec["revoked_reason"],
    })
    return out


def support_request_view(rec):
    out = _base(rec)
    out.update({
        "incident_id": rec["incident_id"],
        "requesting_agency": rec["requesting_agency"],
        "site_name": rec["site_name"],
        "required_skill": rec["required_skill"],
        "min_credential_class": rec["min_credential_class"],
        "headcount_needed": rec["headcount_needed"],
        "criticality": rec["criticality"],
        "window_start": db.fmt_ts(rec["window_start"]),
        "window_end": db.fmt_ts(rec["window_end"]),
        "status": rec["status"],
        "filled_count": filled_count(rec),
    })
    return out


def shift_view(rec):
    out = _base(rec)
    out.update({
        "incident_id": rec["incident_id"],
        "site_name": rec["site_name"],
        "hazard_level": rec["hazard_level"],
        "start_at": db.fmt_ts(rec["start_at"]),
        "end_at": db.fmt_ts(rec["end_at"]),
        "capacity": rec["capacity"],
        "duration_hours": float(Decimal(str(rec["duration_hours"]))),
        "rostered_count": rostered_count(rec),
        "status": rec["status"],
    })
    return out


def assignment_view(rec):
    out = _base(rec)
    out.update({
        "incident_id": rec["incident_id"],
        "volunteer_id": rec["volunteer_id"],
        "support_request_id": rec["support_request_id"],
        "site_shift_id": rec["site_shift_id"],
        "status": rec["status"],
        "origin": rec["origin"],
        "checked_in_at": db.fmt_ts(rec["checked_in_at"]),
        "completed_at": db.fmt_ts(rec["completed_at"]),
    })
    return out


def trip_view(rec):
    out = _base(rec)
    out.update({
        "incident_id": rec["incident_id"],
        "site_shift_id": rec["site_shift_id"],
        "vehicle_id": rec["vehicle_id"],
        "seat_capacity": rec["seat_capacity"],
        "depart_at": db.fmt_ts(rec["depart_at"]),
        "arrive_estimate_at": db.fmt_ts(rec["arrive_estimate_at"]),
        "booked_seats": booked_seats(rec),
        "status": rec["status"],
    })
    return out


def seat_booking_view(rec):
    out = _base(rec)
    out.update({
        "trip_id": rec["trip_id"],
        "assignment_id": rec["assignment_id"],
        "volunteer_id": rec["volunteer_id"],
        "status": rec["status"],
    })
    return out


def ppe_issuance_view(rec):
    out = _base(rec)
    out.update({
        "volunteer_id": rec["volunteer_id"],
        "item_type": rec["item_type"],
        "quantity": rec["quantity"],
        "status": rec["status"],
        "closed_at": db.fmt_ts(rec["closed_at"]),
    })
    return out


def hour_entry_view(rec):
    out = _base(rec)
    out.update({
        "assignment_id": rec["assignment_id"],
        "work_date": rec["work_date"],
        "hours": float(rec["hours"]),
        "status": rec["status"],
        "submitted_by_user_id": rec["submitted_by_user_id"],
        "verified_by_user_id": rec["verified_by_user_id"],
        "dispute_count": rec["dispute_count"],
        "resubmit_count": rec["resubmit_count"],
        "dispute_reason": rec["dispute_reason"],
        "entry_value_cents": rec["entry_value_cents"],
    })
    return out


def risk_report_view(rec):
    out = _base(rec)
    out.update({
        "subject_volunteer_id": rec["subject_volunteer_id"],
        "reporter_user_id": rec["reporter_user_id"],
        "severity": rec["severity"],
        "category": rec["category"],
        "description": rec["description"],
        "occurred_at": db.fmt_ts(rec["occurred_at"]),
        "status": rec["status"],
        "adjudicated_by_user_id": rec["adjudicated_by_user_id"],
        "adjudicated_at": db.fmt_ts(rec["adjudicated_at"]),
        "points_awarded": rec["points_awarded"],
    })
    return out
