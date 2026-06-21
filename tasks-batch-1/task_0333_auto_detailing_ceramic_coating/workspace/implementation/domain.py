"""Domain calculations and cross-entity cascades (PRD §3.2, §3.5-§3.8, §1.3).

These functions operate directly on the in-memory records in db.py. All money
is integer cents; all datetimes are aware UTC.
"""
import clock
import db
from money import apply_bps
from timeutil import add_minutes

# ---- Pricing / ledger constants (PRD §1.3, §2.6) ----
MEMBER_DISCOUNT_BPS = 1500
DEPOSIT_BPS = 2000
SILVER_THRESHOLD_CENTS = 50000
GOLD_THRESHOLD_CENTS = 150000
CYCLE_DAYS = 30
CREDITS_PER_CYCLE = 1

# Work statuses that count an appointment as "in flight" for projected spend (§3.6).
IN_FLIGHT_WORK = {"BOOKED", "CHECKED_IN", "IN_PREP", "IN_SERVICE", "CURING", "READY"}
# Non-terminal work statuses for resource-overlap consideration (§3.3).
NON_TERMINAL_WORK = {"BOOKED", "CHECKED_IN", "IN_PREP", "IN_SERVICE", "CURING", "READY"}


# =====================================================================
# Pricing: calc appointment_total (§3.2, §3.7)
# =====================================================================
def package_pricing(tier, vehicle_size, is_member):
    """Return (pkg_raw, member_discount, pkg_net) for one tier/size/member flag.

    pkg_raw = round_half_up(base_price_cents * size_multiplier_bps / 10000)
    member_discount = round_half_up(pkg_raw * MEMBER_DISCOUNT_BPS / 10000) if member else 0
    pkg_net = pkg_raw - member_discount
    """
    pkg = _package_by_tier(tier)
    rate = _rate_by_size(vehicle_size)
    pkg_raw = apply_bps(pkg["base_price_cents"], rate["size_multiplier_bps"])
    member_discount = apply_bps(pkg_raw, MEMBER_DISCOUNT_BPS) if is_member else 0
    pkg_net = pkg_raw - member_discount
    return pkg_raw, member_discount, pkg_net


def addon_total(appt_id, statuses):
    """Sum of price_cents_snapshot over this appointment's add-on lines whose
    line_status is in `statuses`."""
    total = 0
    for line in db.appointment_addons.values():
        if line["appointment_id"] == appt_id and line["line_status"] in statuses:
            total += line["price_cents_snapshot"]
    return total


def addon_extra_minutes(appt_id, statuses):
    total = 0
    for line in db.appointment_addons.values():
        if line["appointment_id"] == appt_id and line["line_status"] in statuses:
            total += line["extra_minutes_snapshot"]
    return total


def compute_provisional(appt):
    """provisional_total_cents = pkg_net + addon_total(REQUESTED), using
    is_member_at_booking. Reported BEFORE credit."""
    _, _, pkg_net = package_pricing(
        appt["tier"], appt["vehicle_size"], appt["is_member_at_booking"]
    )
    addons = addon_total(appt["id"], {"REQUESTED"})
    return pkg_net + addons


def compute_final(appt):
    """final_total_cents = pkg_net + addon_total(PERFORMED), using CURRENT
    membership-active state. Reported BEFORE credit."""
    is_member = customer_is_member_now(appt["customer_id"])
    _, _, pkg_net = package_pricing(appt["tier"], appt["vehicle_size"], is_member)
    addons = addon_total(appt["id"], {"PERFORMED"})
    return pkg_net + addons


def deposit_amount(provisional_total_cents):
    return apply_bps(provisional_total_cents, DEPOSIT_BPS)


# =====================================================================
# Occupancy window: calc occupancy_window (§3.2)
# =====================================================================
def compute_occupancy(appt):
    """Recompute vehicle_release_utc and occupancy_end_utc from the tier timing,
    requested add-on extra minutes, and scheduled_start_utc. Returns
    (occupancy_end_utc, vehicle_release_utc)."""
    pkg = _package_by_tier(appt["tier"])
    extra = addon_extra_minutes(appt["id"], {"REQUESTED"})
    busy = pkg["prep_minutes"] + pkg["service_minutes"] + extra
    cure = pkg["cure_minutes"]
    start = appt["scheduled_start_utc"]
    vehicle_release = add_minutes(start, busy + cure)
    if appt["location_mode"] == "SHOP":
        occ_end = add_minutes(start, busy + cure)
    else:
        occ_end = add_minutes(start, busy)
    return occ_end, vehicle_release


# =====================================================================
# Payment ledger: calc payment_ledger (§3.7)
# =====================================================================
def compute_outstanding(appt):
    return (appt["final_total_cents"]
            - appt["credit_applied_cents"]
            - appt["amount_charged_cents"]
            + appt["amount_refunded_cents"])


def recompute_outstanding(appt):
    appt["outstanding_balance_cents"] = compute_outstanding(appt)


# =====================================================================
# Loyalty: calc customer_loyalty_tier (§3.6)
# =====================================================================
def customer_is_member_now(customer_id):
    """True if the customer's membership_id is set AND that membership is ACTIVE."""
    cust = db.customers.get(customer_id)
    if not cust or not cust.get("membership_id"):
        return False
    mem = db.memberships.get(cust["membership_id"])
    return bool(mem) and mem["status"] == "ACTIVE"


def _tier_for(chronological_cents):
    if chronological_cents >= GOLD_THRESHOLD_CENTS:
        return "GOLD"
    if chronological_cents >= SILVER_THRESHOLD_CENTS:
        return "SILVER"
    return "BRONZE"


def recompute_chronological(customer_id):
    """chronological_lifetime_spend_cents = sum(final_total_cents for PAID appts);
    recompute loyalty_tier from it. Mutates the customer record."""
    cust = db.customers.get(customer_id)
    if not cust:
        return
    total = 0
    for appt in db.appointments.values():
        if appt["customer_id"] == customer_id and appt["payment_status"] == "PAID":
            total += appt["final_total_cents"]
    cust["chronological_lifetime_spend_cents"] = total
    cust["loyalty_tier"] = _tier_for(total)
    touch(cust)
    # projected depends on chronological, so refresh it too.
    _recompute_projected_inner(cust)


def recompute_projected(customer_id):
    cust = db.customers.get(customer_id)
    if not cust:
        return
    _recompute_projected_inner(cust)
    touch(cust)


def _recompute_projected_inner(cust):
    cid = cust["id"]
    projected = cust["chronological_lifetime_spend_cents"]
    for appt in db.appointments.values():
        if (appt["customer_id"] == cid
                and appt["work_status"] in IN_FLIGHT_WORK
                and appt["payment_status"] != "PAID"):
            projected += appt["provisional_total_cents"]
    cust["projected_lifetime_spend_cents"] = projected


# =====================================================================
# Membership credit ledger: calc membership_credit_ledger (§3.5)
# =====================================================================
def recompute_credits_remaining(mem):
    mem["credits_remaining"] = (mem["credits_granted_total"]
                                - mem["credits_consumed_total"]
                                - mem["credits_expired_total"])


# =====================================================================
# Common-field bookkeeping (§2.4)
# =====================================================================
def touch(record):
    """Mark a versioned resource as mutated: refresh updated_at, bump version."""
    record["updated_at"] = clock.now()
    record["version"] += 1


# ---- catalog lookups by natural key ----
def _package_by_tier(tier):
    for p in db.packages.values():
        if p["tier"] == tier:
            return p
    return None


def _rate_by_size(size):
    for r in db.vehicle_size_rates.values():
        if r["vehicle_size"] == size:
            return r
    return None


def addon_by_code(code):
    for a in db.addons.values():
        if a["addon_code"] == code:
            return a
    return None


def package_by_tier(tier):
    return _package_by_tier(tier)


def rate_by_size(size):
    return _rate_by_size(size)
