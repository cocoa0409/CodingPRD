"""Shared domain logic: posture derivation, queue ranking, rate-schedule
selection, rent-charge creation, escalation, late fees, and coverage checks."""
import calendar
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from timeutil import iso_z, parse_iso, whole_days

# --- System constants (scaffold calculations table) ---
BASE_POINTS = 100
WAIT_POINTS_PER_DAY = 1
TRANSFER_PRIORITY_BONUS = 30
LATE_FEE_DAILY_PCT = Decimal("0.005")
LATE_FEE_FLOOR_CENTS = 500
LATE_FEE_CAP_PCT = Decimal("0.25")
MIN_LIABILITY_COVERAGE_CENTS = 100000000
DELINQUENCY_EVICTION_THRESHOLD_DAYS = 30
ABANDONED_AIRCRAFT_DAILY_CENTS = 2500
ANNIVERSARY_DAYS = 365

# Lease states that occupy a hangar / participate in billing & escalation.
OCCUPYING_LEASE_STATES = ("ACTIVE", "DELINQUENT", "CURE_PERIOD", "EVICTION_PENDING")

SIZE_CLASSES = ("T_HANGAR", "BOX", "EXECUTIVE", "CORPORATE")
DOOR_TYPES = ("SLIDING", "BIFOLD", "HYDRAULIC")
ESCALATION_POLICIES = ("ANNIVERSARY_COMPOUND", "ANNIVERSARY_SIMPLE")
CONDITION_RATINGS = ("GOOD", "FAIR", "POOR", "OUT_OF_SERVICE")
MAINTENANCE_RESPONSIBILITIES = ("TENANT", "AIRPORT", "SHARED")
RECORD_TYPES = ("FUEL_STORAGE_PERMIT", "STORMWATER_PLAN", "HAZMAT_DISCLOSURE")
FINDING_TYPES = ("NON_AERONAUTICAL_USE", "UNAUTHORIZED_SUBLEASE", "INSURANCE_LAPSE", "ENVIRONMENTAL_LAPSE")
EVICTION_REASONS = ("UNCURED_AUDIT", "DELINQUENCY", "NON_AERONAUTICAL_USE")


def touch(ent):
    """Every mutation refreshes updated_at and increments version."""
    ent["updated_at"] = iso_z(db.clock_now())
    ent["version"] += 1


# ---------------------------------------------------------------- hangars ---
def occupying_lease(hangar_id):
    for lease in db.leases.values():
        if lease["hangar_id"] == hangar_id and lease["status"] in OCCUPYING_LEASE_STATES:
            return lease
    return None


def hangar_posture(hangar):
    """Compound availability derivation (PRD 2.8), computed fresh on every read."""
    leased = occupying_lease(hangar["id"]) is not None
    oos = hangar["condition_rating"] == "OUT_OF_SERVICE"
    if leased and oos:
        return "OFFLINE"
    if leased:
        return "LEASED"
    if oos:
        return "MAINTENANCE_HOLD"
    return "AVAILABLE"


def serialize_hangar(hangar):
    out = db.public(hangar)
    out["posture"] = hangar_posture(hangar)
    return out


def open_offer_on_hangar(hangar_id):
    for offer in db.offers.values():
        if offer["hangar_id"] == hangar_id and offer["status"] == "OPEN":
            return offer
    return None


def hangar_available_for_offer(hangar):
    """An OPEN offer reserves its hangar against further offers for its lifetime."""
    return (
        hangar["status"] == "OPERATIONAL"
        and hangar_posture(hangar) == "AVAILABLE"
        and open_offer_on_hangar(hangar["id"]) is None
    )


# ------------------------------------------------------------- rate schedules
def select_rate_schedule(airport_id, size_class, now):
    """Half-open [effective_from, effective_to) coverage; latest effective_from
    wins among overlapping candidates, created_at ASC breaks ties."""
    cands = []
    for rs in db.rate_schedules.values():
        if rs["airport_id"] != airport_id or rs["size_class"] != size_class:
            continue
        if rs["status"] != "ACTIVE":
            continue
        if parse_iso(rs["effective_from"]) > now:
            continue
        effective_to = rs["effective_to"]
        if effective_to != "OPEN" and now >= parse_iso(effective_to):
            continue
        cands.append(rs)
    if not cands:
        return None
    cands.sort(key=lambda r: r["_seq"])  # created_at ASC tie-break (stable)
    cands.sort(key=lambda r: parse_iso(r["effective_from"]), reverse=True)
    return cands[0]


# ------------------------------------------------------------------ waitlist
def rank_queue(airport_id, size_class, now):
    """QUEUED applications at the airport for the size class, ranked by the
    lazily recomputed priority score DESC, created_at ASC tie-break."""
    cands = [
        a for a in db.applications.values()
        if a["airport_id"] == airport_id
        and a["status"] == "QUEUED"
        and a["size_class_requested"] == size_class
    ]
    for a in cands:
        days = whole_days(parse_iso(a["created_at"]), now)
        a["priority_score"] = (
            BASE_POINTS
            + WAIT_POINTS_PER_DAY * days
            + (TRANSFER_PRIORITY_BONUS if a["is_based_tenant_transfer"] else 0)
        )
    cands.sort(key=lambda a: a["_seq"])
    cands.sort(key=lambda a: -a["priority_score"])
    return cands


# -------------------------------------------------------------- rent charges
def create_rent_charge(lease_id, period_start, period_end, base_amount_cents, kind="RENT"):
    charge = db.new_entity({
        "lease_id": lease_id,
        "period_start": iso_z(period_start),
        "period_end": iso_z(period_end),
        "due_date": iso_z(period_start),  # due_date = period_start
        "base_amount_cents": int(base_amount_cents),
        "late_fee_cents": 0,
        "paid_cents": 0,
        "balance_cents": int(base_amount_cents),
        "status": "OPEN",
    })
    charge["_kind"] = kind
    db.rent_charges[charge["id"]] = charge
    return charge


def next_month_boundary(dt):
    """First instant of the calendar month following dt's month (UTC)."""
    if dt.month == 12:
        return dt.replace(year=dt.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return dt.replace(month=dt.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)


def create_first_charge(lease):
    """Pro-rated first charge: floor(rate * days_remaining / days_in_month).
    Pro-rate FIRST (integer floor at the daily level); late fees come later."""
    start = parse_iso(lease["lease_start_date"])
    end = next_month_boundary(start)
    days_in_month = calendar.monthrange(start.year, start.month)[1]
    days_remaining = days_in_month - start.day + 1  # inclusive of the start day
    base = (lease["current_monthly_rate_cents"] * days_remaining) // days_in_month
    charge = create_rent_charge(lease["id"], start, end, base, kind="RENT")
    lease["outstanding_balance_cents"] = base
    return charge


def charge_grace_end(airport, charge):
    return parse_iso(charge["due_date"]) + timedelta(days=airport["late_fee_grace_days"])


def charge_days_overdue(airport, charge, now):
    """Whole days past the end of the grace window; 0 while inside grace."""
    return whole_days(charge_grace_end(airport, charge), now)


def apply_late_fee(airport, charge, now):
    """late_fee_accrual: daily = max(500, rhu(0.005 * base)); accrued = daily*days;
    fee = min(accrued, rhu(0.25 * base)). Cap is per charge."""
    days = charge_days_overdue(airport, charge, now)
    if days <= 0:
        return False
    base = charge["base_amount_cents"]
    daily = max(
        LATE_FEE_FLOOR_CENTS,
        int((Decimal(base) * LATE_FEE_DAILY_PCT).quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
    )
    accrued = daily * days
    cap = int((Decimal(base) * LATE_FEE_CAP_PCT).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    fee = min(accrued, cap)
    if fee != charge["late_fee_cents"]:
        charge["late_fee_cents"] = fee
        charge["balance_cents"] = charge["base_amount_cents"] + fee - charge["paid_cents"]
        touch(charge)
        return True
    return False


def recompute_lease_derived(lease, now, flip_delinquent):
    """Ledger sync: outstanding_balance_cents = sum of OPEN/PARTIALLY_PAID
    balances; days_delinquent = max days_overdue over those charges. The sweep
    additionally flips ACTIVE -> DELINQUENT once a positive-balance charge has
    passed its due_date + grace window."""
    if lease["status"] == "TERMINATED":
        return
    airport = db.airports[lease["airport_id"]]
    charges = [
        c for c in db.rent_charges.values()
        if c["lease_id"] == lease["id"] and c["status"] in ("OPEN", "PARTIALLY_PAID")
    ]
    outstanding = sum(c["balance_cents"] for c in charges)
    days = 0
    for c in charges:
        days = max(days, charge_days_overdue(airport, c, now))
    changed = False
    if lease["outstanding_balance_cents"] != outstanding:
        lease["outstanding_balance_cents"] = outstanding
        changed = True
    if lease["days_delinquent"] != days:
        lease["days_delinquent"] = days
        changed = True
    if flip_delinquent and lease["status"] == "ACTIVE":
        for c in charges:
            if c["balance_cents"] > 0 and now > charge_grace_end(airport, c):
                lease["status"] = "DELINQUENT"
                changed = True
                break
    if changed:
        touch(lease)


# ---------------------------------------------------------------- escalation
def apply_escalation(lease, airport, now):
    """annual_rent_escalation: anniversaries are 365-day steps from lease start,
    inclusive boundary. COMPOUND multiplies the running rate; SIMPLE multiplies
    the original base by (1 + pct*k). Round half up once per anniversary step."""
    start = parse_iso(lease["lease_start_date"])
    n = 0
    while start + timedelta(days=ANNIVERSARY_DAYS * (n + 1)) <= now:
        n += 1
    applied = lease["last_escalation_anniversary"]
    if n <= applied:
        return False
    pct = Decimal(str(airport["escalation_pct"]))
    current = lease["current_monthly_rate_cents"]
    for k in range(applied + 1, n + 1):
        if airport["escalation_policy"] == "ANNIVERSARY_COMPOUND":
            current = int((Decimal(current) * (Decimal(1) + pct)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        else:  # ANNIVERSARY_SIMPLE
            current = int(
                (Decimal(lease["base_monthly_rate_cents"]) * (Decimal(1) + pct * k)).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
    lease["current_monthly_rate_cents"] = current
    lease["last_escalation_anniversary"] = n
    touch(lease)
    return True


# ------------------------------------------------------------------ coverage
def covering_certificate(lease_id, now):
    """insurance_compliance_check: VALID status, half-open window contains now,
    coverage >= MIN_LIABILITY_COVERAGE_CENTS."""
    for cert in db.certificates.values():
        if cert["lease_id"] != lease_id or cert["status"] != "VALID":
            continue
        if cert["liability_coverage_cents"] < MIN_LIABILITY_COVERAGE_CENTS:
            continue
        if parse_iso(cert["effective_from"]) <= now < parse_iso(cert["effective_to"]):
            return cert
    return None


def covering_env_record(lease_id, now):
    for rec in db.env_records.values():
        if rec["lease_id"] != lease_id or rec["status"] != "APPROVED":
            continue
        if parse_iso(rec["expires_at"]) > now:
            return rec
    return None


def open_finding_of_type(lease_id, finding_type):
    for f in db.findings.values():
        if f["lease_id"] == lease_id and f["finding_type"] == finding_type and f["status"] == "OPEN":
            return f
    return None


def file_finding(lease, finding_type, now):
    """Create an OPEN UseAuditFinding with cure_deadline = now + cure_window_days.
    Filing against an ACTIVE lease moves it to CURE_PERIOD; a DELINQUENT lease
    stays DELINQUENT with the finding OPEN alongside."""
    airport = db.airports[lease["airport_id"]]
    finding = db.new_entity({
        "lease_id": lease["id"],
        "finding_type": finding_type,
        "observed_at": iso_z(now),
        "cure_deadline": iso_z(now + timedelta(days=airport["cure_window_days"])),
        "cured_at": None,
        "status": "OPEN",
    })
    db.findings[finding["id"]] = finding
    if lease["status"] == "ACTIVE":
        lease["status"] = "CURE_PERIOD"
        touch(lease)
    return finding
