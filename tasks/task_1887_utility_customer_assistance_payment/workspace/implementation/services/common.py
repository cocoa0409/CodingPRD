"""Shared domain helpers: rounding, account lookups, delinquency, DPA queries."""

from fractions import Fraction

import db
from db import CLOCK


def round_half_up(fr):
    """Round a Fraction/int to the nearest integer, halves away from zero
    (values here are always non-negative)."""
    if isinstance(fr, int):
        return fr
    fr = Fraction(fr)
    floor = fr.numerator // fr.denominator
    return floor + 1 if (fr - floor) >= Fraction(1, 2) else floor


# --- account lookup helpers -------------------------------------------------

def open_order(account_id):
    """The account's open (SCHEDULED|BLOCKED) shutoff order, if any."""
    for o in db.shutoff_orders.values():
        if o["account_id"] == account_id and o["status"] in ("SCHEDULED", "BLOCKED"):
            return o
    return None


def active_enrollment(account_id):
    for e in db.enrollments.values():
        if e["account_id"] == account_id and e["status"] == "ACTIVE":
            return e
    return None


def non_terminal_dpa(account_id):
    for d in db.dpas.values():
        if d["account_id"] == account_id and d["status"] in ("DRAFT", "ACTIVE", "DEFAULTED"):
            return d
    return None


def covering_certificate(account_id, on_date=None):
    """ACTIVE certificate whose half-open window covers the (clock) date."""
    d = on_date or CLOCK.date()
    for c in db.certificates.values():
        if (c["account_id"] == account_id and c["status"] == "ACTIVE"
                and c["effective_from"] <= d < c["effective_to"]):
            return c
    return None


def active_life_threatening_cert(account_id):
    for c in db.certificates.values():
        if (c["account_id"] == account_id and c["status"] == "ACTIVE"
                and c["condition_class"] == "LIFE_THREATENING"):
            return c
    return None


# --- delinquency (calc: delinquency_tier_computation) ------------------------

DELINQUENT_MIN_CENTS = 5000
DELINQUENT_MIN_AGE_DAYS = 30
SEVERE_MIN_CENTS = 20000
SEVERE_MIN_AGE_DAYS = 60


def delinquency_tier(account):
    balance = account["arrearage_balance_cents"]
    since = account["arrearage_since"]
    age = (CLOCK.date() - since).days if since is not None else 0
    if balance >= SEVERE_MIN_CENTS and age >= SEVERE_MIN_AGE_DAYS:
        return "SEVERELY_DELINQUENT"
    if balance >= DELINQUENT_MIN_CENTS and age >= DELINQUENT_MIN_AGE_DAYS:
        return "DELINQUENT"
    return "CURRENT"


# --- DPA schedule helpers -----------------------------------------------------

GRACE_DAYS = 5
CURE_WINDOW_DAYS = 15


def installment_due_date(dpa, k):
    """1-based installment k due date."""
    return db.add_days(dpa["first_installment_due_on"], (k - 1) * 30)


def installment_schedule_amount(dpa, k):
    if k == dpa["installment_count"]:
        return dpa["final_installment_amount_cents"]
    return dpa["installment_amount_cents"]


def due_installment_count(dpa):
    """Count of installments whose due date has been reached by the clock."""
    if dpa["first_installment_due_on"] is None:
        return 0
    today = CLOCK.date()
    n = dpa["installment_count"]
    cnt = 0
    for k in range(1, n + 1):
        if installment_due_date(dpa, k) <= today:
            cnt += 1
        else:
            break
    return cnt


def kept_current_active_dpa(account_id):
    """An ACTIVE DPA with every due installment settled (PRD §3.7)."""
    d = non_terminal_dpa(account_id)
    if d is None or d["status"] != "ACTIVE":
        return None
    return d if d["installments_settled_count"] >= due_installment_count(d) else None


# --- account mutation ----------------------------------------------------------

SHUTOFF_MIN_ARREARAGE_CENTS = 10000


def adjust_arrearage(account, delta):
    """Mutate arrearage with arrearage_since bookkeeping (PRD §3.1)."""
    before = account["arrearage_balance_cents"]
    after = before + delta
    if after < 0:
        after = 0
    account["arrearage_balance_cents"] = after
    if before == 0 and after > 0:
        account["arrearage_since"] = CLOCK.date()
    elif after == 0:
        account["arrearage_since"] = None


def touch_account(account):
    """One account-touching write: version +1, updated_at, last_activity_at."""
    account["version"] += 1
    account["updated_at"] = CLOCK.now()
    account["last_activity_at"] = CLOCK.now()


def auto_cancel_open_order(account, tally=None):
    """Open-order auto-cancel check (PRD §3.5/§3.7): cancel when arrearage
    < 10000 or a kept-current ACTIVE DPA stands; flip service_status when no
    open order remains."""
    order = open_order(account["id"])
    if order is None:
        return False
    if not (account["arrearage_balance_cents"] < SHUTOFF_MIN_ARREARAGE_CENTS
            or kept_current_active_dpa(account["id"]) is not None):
        return False
    order["status"] = "CANCELLED"
    order["blocked_reason"] = None
    db.touch(order)
    if tally is not None:
        tally["orders_cancelled"] += 1
    if open_order(account["id"]) is None and account["service_status"] == "DISCONNECT_PENDING":
        account["service_status"] = "CONNECTED"
    return True
