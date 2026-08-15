"""Core recomputation engine: habitability scores, unit status resolution,
site compliance posture, certification validity, pest exclusion, ledger buckets,
delinquency, and occupancy.

All mutations route through these helpers so every side effect in the PRD
lands consistently. Recomputations are idempotent and always derived from
the current store state.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
import db


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEVERITY_WEIGHT = {"CRITICAL": 25, "MAJOR": 10, "MINOR": 3}
HOLD_THRESHOLD = 40

OPEN_WORK_ORDER_STATUSES = {"REPORTED", "TRIAGED", "ASSIGNED", "IN_PROGRESS", "COMPLETED", "REOPENED"}
NONTERMINAL_WO = OPEN_WORK_ORDER_STATUSES  # terminal = CLOSED, CANCELLED

LIVE_TENANCY_STATUSES = {"PENDING_MOVE_IN", "ACTIVE", "NOTICE"}
ACTIVE_OCCUPANCY_STATUSES = {"ACTIVE", "NOTICE"}

GRACE_DAYS = 10

ALLOWANCE = {"ELECTRIC": 200, "GAS": 100, "WATER": 150}
TIER1_SPAN = 100
TIER1_RATE_TENTH_CENTS = Decimal("125")     # 12.5 cents per unit
TIER2_RATE_TENTH_CENTS = Decimal("187.5")   # 18.75 cents per unit

FEDERAL_MAX_PCT = Decimal("0.30")
MIN_NET_WAGE_FLOOR_CENTS = 40000

CERT_VALID_DAYS = 180
MAINTENANCE_GAP_DAYS = 14
SLA_HOURS = 72


def round_half_up_cents(value):
    """Round a Decimal to integer cents, half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def units_of_site(site_id):
    return [u for u in db.units.values() if u["site_id"] == site_id]


def work_orders_of_unit(unit_id):
    return [w for w in db.work_orders.values() if w["unit_id"] == unit_id]


def work_orders_of_site(site_id):
    unit_ids = {u["id"] for u in units_of_site(site_id)}
    return [w for w in db.work_orders.values() if w["unit_id"] in unit_ids]


def tenancies_of_unit(unit_id):
    return [t for t in db.tenancies.values() if t["unit_id"] == unit_id]


def tenancies_of_site(site_id):
    unit_ids = {u["id"] for u in units_of_site(site_id)}
    return [t for t in db.tenancies.values() if t["unit_id"] in unit_ids]


def certifications_of_unit(unit_id):
    return [c for c in db.certifications.values() if c["unit_id"] == unit_id]


def pest_treatments_of_unit(unit_id):
    return [p for p in db.pest_treatments.values() if p["unit_id"] == unit_id]


def complaints_of_site(site_id):
    unit_ids = {u["id"] for u in units_of_site(site_id)}
    tenancy_ids = {t["id"] for t in db.tenancies.values() if t["unit_id"] in unit_ids}
    return [c for c in db.complaints.values() if c["tenancy_id"] in tenancy_ids]


def inspections_of_site(site_id):
    return [i for i in db.regulatory_inspections.values() if i["site_id"] == site_id]


def members_of_household(household_id):
    return [m for m in db.household_members.values() if m["household_id"] == household_id]


def ledger_entries_of_tenancy(tenancy_id):
    return [e for e in db.ledger_entries.values() if e["tenancy_id"] == tenancy_id]


# ---------------------------------------------------------------------------
# Certification validity
# ---------------------------------------------------------------------------

def _sweep_expired_cert(cert):
    """Lazily flip a PASSED cert whose expiry has passed to EXPIRED. Returns True if flipped."""
    if cert["status"] == "PASSED" and cert.get("expiry_date"):
        if clock.parse_date(cert["expiry_date"]) < clock.current_date():
            cert["status"] = "EXPIRED"
            cert["updated_at"] = db.now_ts()
            return True
    return False


def unit_has_valid_certification(unit_id):
    """True if the unit holds a PASSED cert with expiry_date >= clock date.
    Performs lazy expiry flips as a side effect (per PRD 3.2)."""
    valid = False
    for cert in certifications_of_unit(unit_id):
        if cert["status"] == "PASSED":
            if clock.parse_date(cert["expiry_date"]) >= clock.current_date():
                valid = True
            else:
                _sweep_expired_cert(cert)
    return valid


def sweep_all_certs():
    """Flip every expired PASSED cert; return set of unit_ids that lost validity."""
    affected = set()
    for cert in db.certifications.values():
        if _sweep_expired_cert(cert):
            affected.add(cert["unit_id"])
    return affected


# ---------------------------------------------------------------------------
# Habitability scoring
# ---------------------------------------------------------------------------

def compute_habitability_scores(unit_id):
    open_set = [w for w in work_orders_of_unit(unit_id) if w["status"] in OPEN_WORK_ORDER_STATUSES]
    weights = [SEVERITY_WEIGHT[w["severity"]] for w in open_set]
    cumulative = sum(weights)
    if not weights:
        worst_case = 0.0
    else:
        worst_case = max(weights) + 0.25 * (sum(weights) - max(weights))
    return cumulative, round(worst_case, 2)


def any_open_critical(unit_id):
    return any(
        w["severity"] == "CRITICAL" and w["status"] in OPEN_WORK_ORDER_STATUSES
        for w in work_orders_of_unit(unit_id)
    )


def resolve_unit_status_after_hold_check(unit):
    """After a recompute, decide whether a unit should enter or leave
    HABITABILITY_HOLD. Returns the (possibly new) status. Does not touch
    CONDEMNED or DECOMMISSIONED units for hold *entry*; hold *exit* is only
    meaningful when currently in HABITABILITY_HOLD."""
    cumulative, _ = compute_habitability_scores(unit["id"])
    unit["habitability_score_cumulative"] = cumulative
    _, worst = compute_habitability_scores(unit["id"])
    unit["habitability_score_worst_case"] = worst
    critical_open = any_open_critical(unit["id"])
    status = unit["status"]

    if status in ("REGISTERED", "CERTIFIED", "OCCUPIED"):
        if cumulative >= HOLD_THRESHOLD or critical_open:
            unit["status"] = "HABITABILITY_HOLD"
            unit["updated_at"] = db.now_ts()
    elif status == "HABITABILITY_HOLD":
        if cumulative < HOLD_THRESHOLD and not critical_open:
            if unit_has_valid_certification(unit["id"]):
                if unit.get("current_occupancy", 0) > 0:
                    unit["status"] = "OCCUPIED"
                else:
                    unit["status"] = "CERTIFIED"
            else:
                unit["status"] = "REGISTERED"
            unit["updated_at"] = db.now_ts()
    return unit["status"]


def recompute_unit_scores_and_hold(unit_id):
    """Recompute scores, resolve hold entry/exit, recompute posture."""
    unit = db.units.get(unit_id)
    if unit is None:
        return
    cumulative, worst = compute_habitability_scores(unit_id)
    unit["habitability_score_cumulative"] = cumulative
    unit["habitability_score_worst_case"] = worst
    resolve_unit_status_after_hold_check(unit)
    recompute_site_posture(unit["site_id"])


# ---------------------------------------------------------------------------
# Site compliance posture
# ---------------------------------------------------------------------------

def compute_site_posture(site_id):
    site_units = units_of_site(site_id)
    condemned = [u for u in site_units if u["status"] == "CONDEMNED"]
    on_hold = [u for u in site_units if u["status"] == "HABITABILITY_HOLD"]

    if condemned or len(on_hold) >= 2:
        return "RESTRICTED"

    for insp in inspections_of_site(site_id):
        if insp["status"] == "FINDINGS_ISSUED" and insp.get("open_critical_count", 0) > 0:
            return "RESTRICTED"

    # WATCH
    if len(on_hold) == 1:
        return "WATCH"

    for wo in work_orders_of_site(site_id):
        if wo["severity"] == "CRITICAL" and wo["status"] in OPEN_WORK_ORDER_STATUSES:
            return "WATCH"

    for comp in complaints_of_site(site_id):
        if comp.get("sla_breached") and comp["status"] in ("FILED", "ACKNOWLEDGED", "INVESTIGATING", "ESCALATED_TO_AGENCY"):
            return "WATCH"

    return "NORMAL"


def recompute_site_posture(site_id):
    site = db.sites.get(site_id)
    if site is None:
        return
    site["compliance_posture"] = compute_site_posture(site_id)
    site["updated_at"] = db.now_ts()


# ---------------------------------------------------------------------------
# Pest exclusion
# ---------------------------------------------------------------------------

def recompute_pest_exclusion(unit_id):
    unit = db.units.get(unit_id)
    if unit is None:
        return
    applied = [p for p in pest_treatments_of_unit(unit_id) if p["status"] == "APPLIED"]
    if not applied:
        unit["under_pest_exclusion"] = False
        unit["pest_exclusion_end_date"] = None
        return
    end_dates = [clock.parse_date(p["exclusion_end_date"]) for p in applied]
    latest = max(end_dates)
    unit["pest_exclusion_end_date"] = latest.isoformat()
    unit["under_pest_exclusion"] = clock.current_date() <= latest


def unit_pest_exclusion_blocks_move_in(unit_id, move_in_date):
    """True if move_in_date <= any APPLIED treatment's exclusion_end_date."""
    for p in pest_treatments_of_unit(unit_id):
        if p["status"] == "APPLIED" and p.get("exclusion_end_date"):
            if move_in_date <= clock.parse_date(p["exclusion_end_date"]):
                return True
    return False


# ---------------------------------------------------------------------------
# Occupancy
# ---------------------------------------------------------------------------

def recompute_unit_occupancy(unit_id):
    """current_occupancy = sum of household member_count over ACTIVE/NOTICE tenancies."""
    total = 0
    for t in tenancies_of_unit(unit_id):
        if t["status"] in ACTIVE_OCCUPANCY_STATUSES:
            hh = db.households.get(t["household_id"])
            if hh:
                total += hh.get("member_count", 0)
    unit = db.units.get(unit_id)
    if unit is not None:
        unit["current_occupancy"] = total
    return total


# ---------------------------------------------------------------------------
# Household member recompute
# ---------------------------------------------------------------------------

def recompute_household_counts(household_id):
    hh = db.households.get(household_id)
    if hh is None:
        return
    members = members_of_household(household_id)
    hh["member_count"] = len(members)
    today = clock.current_date()
    minors = 0
    for m in members:
        dob = clock.parse_date(m["date_of_birth"])
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        is_minor = age < 18
        m["is_minor"] = is_minor
        if is_minor:
            minors += 1
    hh["minor_count"] = minors


# ---------------------------------------------------------------------------
# Ledger buckets, waterfall allocation, delinquency
# ---------------------------------------------------------------------------

DEBIT_TYPES = {"RENT", "UTILITY_OVERAGE", "DAMAGE"}
CREDIT_TYPES = {"SUBSIDY_CREDIT", "PAYMENT"}


def _bucket_of_debit(entry_type):
    if entry_type == "RENT":
        return "RENT"
    if entry_type == "UTILITY_OVERAGE":
        return "UTILITY"
    if entry_type == "DAMAGE":
        return "DAMAGE"
    return None


def _allocation_sort_key(entry):
    return (entry.get("created_at", ""), entry.get("entry_type", ""))


def compute_ledger(tenancy_id):
    """Recompute the three bucket balances, balance_cents, oldest_unpaid_charge_date,
    and is_delinquent for a tenancy. Implements chronological credit allocation
    per PRD 3.5.

    Returns dict of computed fields.
    """
    entries = [e for e in ledger_entries_of_tenancy(tenancy_id) if e["status"] == "POSTED"]
    entries.sort(key=_allocation_sort_key)

    # Track residual per debit entry, keyed by bucket.
    debit_residual = {}  # entry_id -> remaining cents
    debit_bucket = {}    # entry_id -> bucket
    debit_order = []     # entry ids in allocation order
    for e in entries:
        if e["entry_type"] in DEBIT_TYPES:
            debit_residual[e["id"]] = e["amount_cents"]
            debit_bucket[e["id"]] = _bucket_of_debit(e["entry_type"])
            debit_order.append(e["id"])

    # Apply credits chronologically.
    for e in entries:
        if e["entry_type"] not in CREDIT_TYPES:
            continue
        amount = e["amount_cents"]
        if e["entry_type"] == "SUBSIDY_CREDIT":
            # Credits the rent bucket only.
            buckets = ["RENT"]
        else:  # PAYMENT
            purpose = e.get("payment_purpose")
            if purpose == "RENT_AND_UTILITIES":
                buckets = ["RENT", "UTILITY"]
            else:
                buckets = ["RENT"]
        for bucket in buckets:
            if amount <= 0:
                break
            # Consume oldest residuals in this bucket first.
            for d_id in debit_order:
                if amount <= 0:
                    break
                if debit_bucket[d_id] == bucket and debit_residual[d_id] > 0:
                    take = min(amount, debit_residual[d_id])
                    debit_residual[d_id] -= take
                    amount -= take

    # Bucket balances.
    rent_balance = sum(r for d_id, r in debit_residual.items() if debit_bucket[d_id] == "RENT" and r > 0)
    utility_balance = sum(r for d_id, r in debit_residual.items() if debit_bucket[d_id] == "UTILITY" and r > 0)
    damage_balance = sum(r for d_id, r in debit_residual.items() if debit_bucket[d_id] == "DAMAGE" and r > 0)
    balance = rent_balance + utility_balance + damage_balance

    # Oldest unpaid debit charge_date across all buckets.
    oldest = None
    for d_id in debit_order:
        if debit_residual[d_id] > 0:
            entry = db.ledger_entries[d_id]
            cd = entry.get("charge_date")
            if cd is not None and (oldest is None or cd < oldest):
                oldest = cd

    is_delinquent = False
    if balance > 0 and oldest is not None:
        age_days = (clock.current_date() - clock.parse_date(oldest)).days
        is_delinquent = age_days > GRACE_DAYS

    return {
        "balance_cents": balance,
        "rent_bucket_balance_cents": rent_balance,
        "utility_bucket_balance_cents": utility_balance,
        "damage_bucket_balance_cents": damage_balance,
        "oldest_unpaid_charge_date": oldest,
        "is_delinquent": is_delinquent,
    }


def recompute_tenancy_ledger(tenancy_id):
    t = db.tenancies.get(tenancy_id)
    if t is None:
        return
    computed = compute_ledger(tenancy_id)
    t.update(computed)
    t["updated_at"] = db.now_ts()


# ---------------------------------------------------------------------------
# Compliance summary (computed read)
# ---------------------------------------------------------------------------

def compute_compliance_summary(site_id):
    site = db.sites.get(site_id)
    site_units = units_of_site(site_id)
    on_hold = [u for u in site_units if u["status"] == "HABITABILITY_HOLD"]
    condemned = [u for u in site_units if u["status"] == "CONDEMNED"]
    open_critical_wos = [
        w for w in work_orders_of_site(site_id)
        if w["severity"] == "CRITICAL" and w["status"] in OPEN_WORK_ORDER_STATUSES
    ]
    breached_open = [
        c for c in complaints_of_site(site_id)
        if c.get("sla_breached") and c["status"] in ("FILED", "ACKNOWLEDGED", "INVESTIGATING", "ESCALATED_TO_AGENCY")
    ]

    # units missing in-season pest treatment
    active_window = None
    for w in db.season_windows.values():
        if w["site_id"] == site_id and w["status"] == "ACTIVE":
            active_window = w
            break
    missing_pest = 0
    if active_window is not None:
        win_open = clock.parse_date(active_window["planned_open_date"])
        win_close = clock.parse_date(active_window["planned_close_date"])
        for u in site_units:
            if u["status"] in ("CERTIFIED", "OCCUPIED", "HABITABILITY_HOLD"):
                has = False
                for p in pest_treatments_of_unit(u["id"]):
                    if p["status"] in ("APPLIED", "CLEARED") and p.get("applied_date"):
                        ad = clock.parse_date(p["applied_date"])
                        if win_open <= ad <= win_close:
                            has = True
                            break
                if not has:
                    missing_pest += 1

    return {
        "compliance_posture": site["compliance_posture"] if site else "NORMAL",
        "units_on_hold_count": len(on_hold),
        "condemned_units_count": len(condemned),
        "open_critical_work_orders": len(open_critical_wos),
        "breached_open_complaints": len(breached_open),
        "units_missing_season_pest_treatment": missing_pest,
    }
