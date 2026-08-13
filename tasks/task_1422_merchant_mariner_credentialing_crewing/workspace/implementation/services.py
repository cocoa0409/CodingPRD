"""Business logic: postures, cascades, sweeps, overlap checks, calculations.

Implements SCAFFOLD 1.3 calculation rules and the cascading consistency of
PRD 2.9. Every recompute bumps version/updated_at only when a persisted
field actually changed (PRD 2.4).
"""

import calendar
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from db import store

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD 1.3)
# ---------------------------------------------------------------------------

DRUG_CURRENCY_DAYS = 365
RESTRICTED_WINDOW_DAYS = 30
CREDENTIAL_RENEWAL_GRACE_DAYS = 180
PER_COURSE_CAP_CENTS = 200000
CANCEL_FEE_PCT_TICKETED = Decimal("0.15")
CHANNEL_PCT = {"DIRECT": Decimal("0.80"), "UNION_HALL": Decimal("1.00")}

REGION_DAY_FACTOR = {
    "OCEAN": Fraction(1, 1),
    "NEAR_COASTAL": Fraction(1, 1),
    "GREAT_LAKES": Fraction(1, 1),
    "INLAND": Fraction(1, 2),
}
WATCH_MULTIPLIER = {"EIGHT_HOUR": Fraction(1, 1), "TWELVE_HOUR": Fraction(3, 2)}

QUALIFYING_DRUG_TYPES = {"PRE_EMPLOYMENT", "PERIODIC", "RANDOM", "RETURN_TO_DUTY"}

UPGRADE_REQUIREMENTS = {
    "CHIEF_MATE": {"days_required": 360, "lookback_months": 36, "track": "DECK", "min_serving_grade": 4},
    "MASTER": {"days_required": 360, "lookback_months": 36, "track": "DECK", "min_serving_grade": 6},
    "SECOND_ENGINEER": {"days_required": 270, "lookback_months": 36, "track": "ENGINE", "min_serving_grade": 4},
}

ASSIGNMENT_OPEN_STATES = {"PROPOSED", "CONFIRMED", "ONBOARD", "SUSPENDED"}


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def mariner_of(mid):
    return store.mariners.get(mid)


def vessel_of(vid):
    return store.vessels.get(vid)


def slot_of(sid):
    return store.manning_slots.get(sid)


def credential_is_valid(cred, now):
    """A credential is valid while status VALID and expiry on or after now."""
    return cred["status"] == "VALID" and cred["expiry_date"] >= now


def medical_is_valid(cert, now):
    return cert["status"] == "VALID" and cert["expiry_date"] >= now


def compute_drug_test_current_until(mariner_id):
    """Latest qualifying NEGATIVE collected_date + 365 days, or None."""
    best = None
    for t in store.drug_tests.values():
        if t["mariner_id"] != mariner_id:
            continue
        if t["status"] != "COMPLETED" or t["result"] != "NEGATIVE":
            continue
        if t["test_type"] not in QUALIFYING_DRUG_TYPES:
            continue
        if best is None or t["collected_date"] > best:
            best = t["collected_date"]
    if best is None:
        return None
    return best + timedelta(days=DRUG_CURRENCY_DAYS)


# ---------------------------------------------------------------------------
# Mariner readiness posture (calculations.mariner_readiness_posture)
# ---------------------------------------------------------------------------

def compute_posture(m):
    """Return (posture, reasons, earliest_expiry) from current committed rows."""
    now = store.clock
    # Gate 1: lifecycle — skip remaining gates.
    if m["status"] != "ACTIVE":
        return "BLOCKED", ["STATUS_NOT_ACTIVE"], None

    reasons = []
    # Gate 2: medical.
    valid_meds = [
        c
        for c in store.medical_certificates.values()
        if c["mariner_id"] == m["id"] and medical_is_valid(c, now)
    ]
    med_expiry = max((c["expiry_date"] for c in valid_meds), default=None)
    if med_expiry is None:
        reasons.append("NO_VALID_MEDICAL")

    # Gate 3: drug currency.
    drug_until = compute_drug_test_current_until(m["id"])
    if drug_until is None or drug_until < now:
        reasons.append("DRUG_CURRENCY_LAPSED")

    # Gate 4: latest completed result (by collected_date, tie-break created_at/_seq).
    completed = [
        t
        for t in store.drug_tests.values()
        if t["mariner_id"] == m["id"] and t["status"] == "COMPLETED"
    ]
    if completed:
        latest = max(
            completed,
            key=lambda t: (t["collected_date"] or t["created_at"], t["created_at"], t["_seq"]),
        )
        if latest["result"] in ("POSITIVE", "REFUSAL"):
            reasons.append("DRUG_RESULT_POSITIVE")

    # Gate 5: primary credential.
    valid_primary = [
        c
        for c in store.credentials.values()
        if c["mariner_id"] == m["id"]
        and c["endorsement_code"] == m["primary_endorsement_code"]
        and credential_is_valid(c, now)
    ]
    cred_expiry = max((c["expiry_date"] for c in valid_primary), default=None)
    if cred_expiry is None:
        reasons.append("NO_VALID_PRIMARY_CREDENTIAL")

    if reasons:
        return "BLOCKED", reasons, None

    # Restricted window: one reason per source expiring within 30 days.
    earliest = min(med_expiry, drug_until, cred_expiry)
    horizon = now + timedelta(days=RESTRICTED_WINDOW_DAYS)
    soon = []
    if med_expiry <= horizon:
        soon.append("MEDICAL_EXPIRING_SOON")
    if drug_until <= horizon:
        soon.append("DRUG_CURRENCY_EXPIRING_SOON")
    if cred_expiry <= horizon:
        soon.append("CREDENTIAL_EXPIRING_SOON")
    if soon:
        return "RESTRICTED", soon, earliest
    return "CLEAR", [], None


def recompute_mariner(m):
    """Recompute posture fields; bump on change. Returns (became_blocked, old)."""
    old_posture = m["readiness_posture"]
    posture, reasons, earliest = compute_posture(m)
    drug_until = compute_drug_test_current_until(m["id"])
    changed = (
        m["readiness_posture"] != posture
        or list(m["readiness_reasons"]) != list(reasons)
        or m["drug_test_current_until"] != drug_until
    )
    m["readiness_posture"] = posture
    m["readiness_reasons"] = list(reasons)
    m["drug_test_current_until"] = drug_until
    m["_earliest_expiry"] = earliest
    if changed:
        store.bump(m)
    return old_posture != "BLOCKED" and posture == "BLOCKED", old_posture


def recompute_mariner_with_cascade(m):
    """Recompute posture; if the mariner became BLOCKED, suspend open crewing."""
    became_blocked, _ = recompute_mariner(m)
    if became_blocked:
        cascade_assignments_suspended(m)


def cascade_assignments_suspended(m):
    """Posture flipped to BLOCKED: CONFIRMED and ONBOARD assignments -> SUSPENDED."""
    vessel_ids = set()
    for a in store.assignments.values():
        if a["mariner_id"] != m["id"]:
            continue
        if a["assignment_status"] in ("CONFIRMED", "ONBOARD"):
            a["assignment_status"] = "SUSPENDED"
            store.bump(a)
            vessel_ids.add(a["vessel_id"])
    for vid in vessel_ids:
        v = vessel_of(vid)
        if v is not None:
            recompute_vessel(v)


# ---------------------------------------------------------------------------
# Vessel manning compliance (calculations.manning_compliance_posture)
# ---------------------------------------------------------------------------

def recompute_vessel(v):
    """Recompute slot coverage and vessel compliance posture; bump on change."""
    slots = [
        s
        for s in store.manning_slots.values()
        if s["vessel_id"] == v["id"] and s["status"] == "ACTIVE"
    ]
    covered = 0
    for s in slots:
        cov = (
            "COVERED"
            if any(
                a["manning_slot_id"] == s["id"] and a["assignment_status"] == "ONBOARD"
                for a in store.assignments.values()
            )
            else "UNCOVERED"
        )
        if s["current_coverage"] != cov:
            s["current_coverage"] = cov
            store.bump(s)
        if cov == "COVERED":
            covered += 1
    if any(
        s["is_critical_position"] and s["current_coverage"] == "UNCOVERED"
        for s in slots
    ):
        posture = "CRITICAL_SHORTAGE"
    elif any(s["current_coverage"] == "UNCOVERED" for s in slots):
        posture = "DEFICIENT"
    else:
        posture = "COMPLIANT"
    if (
        v["slots_total"] != len(slots)
        or v["slots_covered"] != covered
        or v["compliance_posture"] != posture
    ):
        v["slots_total"] = len(slots)
        v["slots_covered"] = covered
        v["compliance_posture"] = posture
        store.bump(v)


def active_rotation_plan(vessel_id):
    plans = [
        p
        for p in store.rotation_plans.values()
        if p["vessel_id"] == vessel_id and p["status"] == "ACTIVE"
    ]
    if not plans:
        return None
    return max(plans, key=lambda p: p["_seq"])


# ---------------------------------------------------------------------------
# Credential expiry sweep (calculations.credential_expiry_sweep) — pinned order
# ---------------------------------------------------------------------------

def run_expiry_sweep():
    now = store.clock
    # 1. Expire credentials in VALID / RENEWAL_PENDING / SUSPENDED_PREREQ.
    newly_inactive = []
    for c in store.credentials.values():
        if c["status"] in ("VALID", "RENEWAL_PENDING", "SUSPENDED_PREREQ") and c[
            "expiry_date"
        ] < now:
            c["status"] = "EXPIRED"
            store.bump(c)
            newly_inactive.append(c)
    # 2. Lapse credentials EXPIRED for more than 180 days.
    for c in store.credentials.values():
        if (
            c["status"] == "EXPIRED"
            and c["expiry_date"] + timedelta(days=CREDENTIAL_RENEWAL_GRACE_DAYS) < now
        ):
            c["status"] = "LAPSED"
            store.bump(c)
            newly_inactive.append(c)
    # 3. Prerequisite cascade: dependents of newly expired/lapsed -> SUSPENDED_PREREQ.
    for c in newly_inactive:
        for dep in store.credentials.values():
            if (
                dep["prerequisite_credential_id"] == c["id"]
                and dep["status"] in ("VALID", "RENEWAL_PENDING")
            ):
                dep["status"] = "SUSPENDED_PREREQ"
                store.bump(dep)
    # 4. Expire medical certificates in VALID / SUSPENDED.
    for cert in store.medical_certificates.values():
        if cert["status"] in ("VALID", "SUSPENDED") and cert["expiry_date"] < now:
            cert["status"] = "EXPIRED"
            store.bump(cert)
    # 5. Recompute every mariner's posture (clock drift alone can flip postures).
    newly_blocked = []
    for m in store.mariners.values():
        became_blocked, _ = recompute_mariner(m)
        if became_blocked:
            newly_blocked.append(m)
    # 6. Posture cascade: suspend open assignments of newly blocked mariners.
    vessel_ids = set()
    for m in newly_blocked:
        for a in store.assignments.values():
            if a["mariner_id"] != m["id"]:
                continue
            if a["assignment_status"] in ("CONFIRMED", "ONBOARD"):
                a["assignment_status"] = "SUSPENDED"
                store.bump(a)
                vessel_ids.add(a["vessel_id"])
    # 7. Slot coverage / vessel posture recompute.
    for vid in vessel_ids:
        v = vessel_of(vid)
        if v is not None:
            recompute_vessel(v)


# ---------------------------------------------------------------------------
# Sea service day credit (calculations.sea_service_day_credit)
# ---------------------------------------------------------------------------

def calendar_days(start, end):
    """Inclusive whole-day count: (end - start) in whole days + 1."""
    return (end - start).days + 1


def compute_verified_days(rec):
    days = calendar_days(rec["start_date"], rec["end_date"])
    product = (
        Fraction(days)
        * REGION_DAY_FACTOR[rec["service_region"]]
        * WATCH_MULTIPLIER[rec["watch_schedule"]]
    )
    # floor_to_half(x) = floor(x * 2) / 2
    return math.floor(product * 2) / 2.0


# ---------------------------------------------------------------------------
# Upgrade eligibility (calculations.upgrade_eligibility)
# ---------------------------------------------------------------------------

def subtract_months(dt, months):
    total = dt.year * 12 + (dt.month - 1) - months
    y, m0 = divmod(total, 12)
    month = m0 + 1
    day = min(dt.day, calendar.monthrange(y, month)[1])
    return dt.replace(year=y, month=month, day=day)


def upgrade_eligibility(m, target):
    req = UPGRADE_REQUIREMENTS[target]
    now = store.clock
    window_start = subtract_months(now, req["lookback_months"])
    verified_sum = 0.0
    for r in store.sea_service_records.values():
        if r["mariner_id"] != m["id"] or r["record_status"] != "VERIFIED":
            continue
        if r["rank_track"] != req["track"] or r["rank_grade"] < req["min_serving_grade"]:
            continue
        if r["start_date"] < window_start:
            continue
        verified_sum += r["verified_days"] or 0.0
    days_met = verified_sum >= req["days_required"]
    course_met = False
    for e in store.training_enrollments.values():
        if e["mariner_id"] != m["id"] or e["status"] not in ("COMPLETED", "REIMBURSED"):
            continue
        course = store.training_courses.get(e["course_id"])
        if course is not None and course["grants_endorsement_code"] == target:
            course_met = True
            break
    return {
        "eligible": days_met and course_met,
        "target_endorsement_code": target,
        "verified_days_in_window": verified_sum,
        "required_days": req["days_required"],
        "course_requirement_met": course_met,
        "shortfall_days": max(0.0, req["days_required"] - verified_sum),
        "window_start": window_start,
    }


# ---------------------------------------------------------------------------
# Training reimbursement (calculations.training_reimbursement)
# ---------------------------------------------------------------------------

def round_half_up_cents(value):
    """Round a Decimal to whole cents (integer), half up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_provisional_amount(course_cost_cents, channel_snapshot):
    capped = min(course_cost_cents, PER_COURSE_CAP_CENTS)
    pct = CHANNEL_PCT[channel_snapshot]
    return round_half_up_cents(Decimal(capped) * pct)


def budget_for(mariner_id, fiscal_year):
    for b in store.training_budgets.values():
        if b["mariner_id"] == mariner_id and b["fiscal_year"] == fiscal_year:
            return b
    return None


# ---------------------------------------------------------------------------
# Travel fares (calculations.travel_fare_total)
# ---------------------------------------------------------------------------

def compute_total_fare(legs):
    """Per-leg round-half-up, then sum (pinned order)."""
    total = 0
    for leg in legs:
        fare = Decimal(leg["base_fare_cents"]) * (
            Decimal(1) + Decimal(leg["markup_bps"]) / Decimal(10000)
        )
        total += round_half_up_cents(fare)
    return total


def compute_cancellation_fee(total_fare_cents):
    return round_half_up_cents(Decimal(total_fare_cents) * CANCEL_FEE_PCT_TICKETED)


# ---------------------------------------------------------------------------
# Assignment overlap checks (calculations.assignment_overlap_checks)
# ---------------------------------------------------------------------------

def find_mariner_overlap(mariner_id, sign_on, relief, exclude_id=None):
    """Strict half-open double-booking check over {CONFIRMED, ONBOARD, SUSPENDED}."""
    for a in store.assignments.values():
        if a["mariner_id"] != mariner_id or a["id"] == exclude_id:
            continue
        if a["assignment_status"] not in ("CONFIRMED", "ONBOARD", "SUSPENDED"):
            continue
        if sign_on < a["planned_relief_date"] and a["sign_on_date"] < relief:
            return a
    return None


def handover_overlap_days(a_sign_on, a_relief, b_sign_on, b_relief):
    """Whole-day overlap (floor; negative treated as 0)."""
    delta = min(a_relief, b_relief) - max(a_sign_on, b_sign_on)
    seconds = delta.total_seconds()
    days = int(seconds // 86400)
    return max(0, days)


def find_handover_violation(slot_id, sign_on, relief, max_overlap_days, exclude_id=None):
    """Bounded-buffer slot handover check over {CONFIRMED, ONBOARD}."""
    for a in store.assignments.values():
        if a["manning_slot_id"] != slot_id or a["id"] == exclude_id:
            continue
        if a["assignment_status"] not in ("CONFIRMED", "ONBOARD"):
            continue
        overlap = handover_overlap_days(
            sign_on, relief, a["sign_on_date"], a["planned_relief_date"]
        )
        if overlap > max_overlap_days:
            return a
    return None


# ---------------------------------------------------------------------------
# Travel cascade shared by assignment cancel / mariner terminate / vessel lay-up
# ---------------------------------------------------------------------------

def cancel_travel_bookings(assignment):
    """Cancel every non-terminal booking of the assignment (fees for TICKETED)."""
    for b in store.travel_bookings.values():
        if b["assignment_id"] != assignment["id"]:
            continue
        if b["status"] in ("QUOTED", "BOOKED", "TICKETED"):
            if b["status"] == "TICKETED":
                b["cancellation_fee_cents"] = compute_cancellation_fee(
                    b["total_fare_cents"] or 0
                )
            else:
                b["cancellation_fee_cents"] = 0
            b["status"] = "CANCELLED"
            store.bump(b)


def cancel_assignment_cascade(assignment):
    """PROPOSED/CONFIRMED/SUSPENDED -> CANCELLED with the travel cascade."""
    assignment["assignment_status"] = "CANCELLED"
    store.bump(assignment)
    cancel_travel_bookings(assignment)
