"""Business logic: calculations, derived fields, the bed selector, and the
audit-trail helper. Each calculation mirrors SCAFFOLD.yaml §1.3 and PRD §3.

All money is integer cents; per-line rounding uses round-half-up BEFORE
summation. All temporal comparisons run at millisecond resolution against the
server's test-driving clock.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db

# ---------------------------------------------------------------------------
# NICU clinical criteria (PRD §3.3)
# Meets criteria when ANY holds: gestational_age_weeks < 35 OR apgar_5min <= 6
# OR weight_grams < 1800. Clear only when ALL three thresholds are satisfied.
# ---------------------------------------------------------------------------
def meets_nicu_criteria(newborn: dict) -> bool:
    return (
        newborn["gestational_age_weeks"] < 35
        or newborn["apgar_5min"] <= 6
        or newborn["weight_grams"] < 1800
    )


# ---------------------------------------------------------------------------
# Open-stay predicate: a newborn has an open NICU stay when any of its stays
# is in PENDING_BED or ACTIVE (PRD §3.4 / §3.8).
# ---------------------------------------------------------------------------
def open_nicu_stays(newborn_id: str) -> list:
    return [
        s for s in db.nicu_stays.values()
        if s["newborn_id"] == newborn_id and s["status"] in ("PENDING_BED", "ACTIVE")
    ]


def active_nicu_stay(newborn_id: str):
    for s in db.nicu_stays.values():
        if s["newborn_id"] == newborn_id and s["status"] == "ACTIVE":
            return s
    return None


# ---------------------------------------------------------------------------
# compute_discharge_readiness (SCAFFOLD §1.3 / PRD §3.8)
# Four independent terms, summed, capped at 100.
# ---------------------------------------------------------------------------
def compute_discharge_readiness(newborn: dict) -> int:
    grams = newborn["weight_grams"]
    if grams >= 2500:
        weight_pts = 40
    elif grams >= 2000:
        weight_pts = 25
    elif grams >= 1800:
        weight_pts = 10
    else:
        weight_pts = 0

    feeding_pts = 0
    for c in db.lactation_consults.values():
        if (c["newborn_id"] == newborn["id"]
                and c["status"] == "COMPLETED"
                and c["feeding_adequate"] is True):
            feeding_pts = 30
            break

    nicu_pts = 20 if not open_nicu_stays(newborn["id"]) else 0

    filing_pts = 0
    for f in db.government_filings.values():
        if (f["newborn_id"] == newborn["id"]
                and f["filing_type"] == "BIRTH_CERTIFICATE"
                and f["status"] in ("SUBMITTED", "ACCEPTED")):
            filing_pts = 10
            break

    return min(100, weight_pts + feeding_pts + nicu_pts + filing_pts)


def refresh_readiness(newborn: dict) -> None:
    newborn["discharge_readiness_score"] = compute_discharge_readiness(newborn)


# ---------------------------------------------------------------------------
# compute_bag_value (SCAFFOLD §1.3 / PRD §3.6)
# Per-line round-half-up to integer cents BEFORE summation. EDUCATION free,
# MEDICATION +5% handling surcharge.
# ---------------------------------------------------------------------------
CATEGORY_MULTIPLIER = {
    "FORMULA": Decimal("1.00"),
    "DIAPERS": Decimal("1.00"),
    "EDUCATION": Decimal("0.00"),
    "CARSEAT_VOUCHER": Decimal("1.00"),
    "MEDICATION": Decimal("1.05"),
}


def compute_bag_value(line_items: list) -> int:
    total = 0
    for item in line_items:
        qty = Decimal(int(item["qty"]))
        unit = Decimal(int(item["unit_value_cents"]))
        mult = CATEGORY_MULTIPLIER[item["category"]]
        raw = qty * unit * mult
        line_value = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        total += line_value
    return total


def requires_pharmacy_signoff(line_items: list) -> bool:
    return any(item["category"] == "MEDICATION" for item in line_items)


# ---------------------------------------------------------------------------
# compute_sep_deadline (SCAFFOLD §1.3 / PRD §3.10)
# base = birth_datetime; raw = base + 30 calendar days (time preserved).
# MARKETPLACE => CALENDAR (no roll). EMPLOYER_GROUP / MEDICAID => BUSINESS_ROLL
# (if raw lands on Sat/Sun, roll forward to next Monday 23:59:59.999Z).
# ---------------------------------------------------------------------------
SEP_WINDOW_DAYS = 30


def compute_sep_deadline(birth_datetime_iso: str, plan_type: str) -> str:
    base = db.parse_iso(birth_datetime_iso)
    raw = base + timedelta(days=SEP_WINDOW_DAYS)
    if plan_type == "MARKETPLACE":
        deadline = raw
    else:  # EMPLOYER_GROUP, MEDICAID
        wd = raw.weekday()  # Mon=0 ... Sat=5, Sun=6
        if wd == 5:        # Saturday -> +2 days to Monday
            monday = raw + timedelta(days=2)
            deadline = monday.replace(hour=23, minute=59, second=59, microsecond=999000)
        elif wd == 6:      # Sunday -> +1 day to Monday
            monday = raw + timedelta(days=1)
            deadline = monday.replace(hour=23, minute=59, second=59, microsecond=999000)
        else:
            deadline = raw
    return db.fmt_iso(deadline)


# ---------------------------------------------------------------------------
# compute_filing_deadline (SCAFFOLD §1.3 / PRD §3.7)
# BIRTH_CERTIFICATE => +5 calendar days; SSN_APPLICATION => +365 calendar days.
# ---------------------------------------------------------------------------
def compute_filing_deadline(birth_datetime_iso: str, filing_type: str) -> str:
    base = db.parse_iso(birth_datetime_iso)
    days = 5 if filing_type == "BIRTH_CERTIFICATE" else 365
    return db.fmt_iso(base + timedelta(days=days))


# ---------------------------------------------------------------------------
# compute_followup_due (SCAFFOLD §1.3 / PRD §3.9)
# due_at = discharged_at + per-type SLA hours.
# ---------------------------------------------------------------------------
FOLLOWUP_SLA_HOURS = {
    "WEIGHT_CHECK": 48,
    "JAUNDICE_CHECK": 72,
    "FEEDING_CHECK": 120,
    "SAFETY_CALL": 168,
}


def compute_followup_due(discharged_at_iso: str, task_type: str) -> str:
    base = db.parse_iso(discharged_at_iso)
    return db.fmt_iso(base + timedelta(hours=FOLLOWUP_SLA_HOURS[task_type]))


# ---------------------------------------------------------------------------
# Policy dependents_added_count: number of ENROLLED enrollments on a policy.
# ---------------------------------------------------------------------------
def recompute_dependents_added_count(policy_id: str) -> int:
    count = sum(
        1 for e in db.dependent_enrollments.values()
        if e["policy_id"] == policy_id and e["status"] == "ENROLLED"
    )
    policy = db.insurance_policies.get(policy_id)
    if policy is not None:
        policy["dependents_added_count"] = count
    return count


# ---------------------------------------------------------------------------
# PreRegistration newborn_count
# ---------------------------------------------------------------------------
def recompute_newborn_count(pre_registration_id: str) -> int:
    count = sum(
        1 for n in db.newborns.values()
        if n["pre_registration_id"] == pre_registration_id
    )
    reg = db.pre_registrations.get(pre_registration_id)
    if reg is not None:
        reg["newborn_count"] = count
    return count


# ---------------------------------------------------------------------------
# Bed selector (PRD §3.4): among VACANT beds with acuity_level >= required,
# claim one. Returns the chosen bed dict or None. Ordering among eligible beds
# is by creation order (deterministic); the id is never used to choose.
# ---------------------------------------------------------------------------
ACUITY_ORDER = {"LEVEL_2": 2, "LEVEL_3": 3, "LEVEL_4": 4}


def select_bed_for_stay(required_level: str):
    req = ACUITY_ORDER[required_level]
    candidates = [
        b for b in db.nicu_beds.values()
        if b["occupancy_status"] == "VACANT" and ACUITY_ORDER[b["acuity_level"]] >= req
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda b: (b.get("created_at", ""), b.get("_seq", 0)))
    return candidates[0]


def occupy_bed(bed: dict, stay: dict) -> None:
    """Assign a stay onto a bed: stay->ACTIVE, bed->OCCUPIED. Each touched row
    independently bumps its updated_at/version (cascade consistency, §2.5)."""
    stay["nicu_bed_id"] = bed["id"]
    stay["status"] = "ACTIVE"
    db.stamp_update(stay)
    bed["occupancy_status"] = "OCCUPIED"
    bed["current_stay_id"] = stay["id"]
    db.stamp_update(bed)


# ---------------------------------------------------------------------------
# Audit trail (PRD §2.10). AuditEvent has only id + created_at (no version /
# updated_at). actor_role is the X-User-Role of the caller.
# ---------------------------------------------------------------------------
def append_audit(event_type: str, actor_role: str, newborn_id, detail: dict) -> dict:
    row = {
        "id": db.new_id(),
        "newborn_id": newborn_id,
        "actor_role": actor_role,
        "event_type": event_type,
        "detail": detail or {},
        "created_at": db.current_utc_iso(),
        "_seq": db.next_seq(),
    }
    db.audit_events[row["id"]] = row
    return row
