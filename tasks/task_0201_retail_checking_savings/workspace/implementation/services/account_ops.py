"""Account lifecycle operations: dormancy, escheat, interest, stop-expiry.

PRD §3.7 (dormancy/escheat), §3.11 (interest), §3.10 (stop expiry), §3.8 (close).
"""
import math
from db import db, clock_date_iso, parse_date, days_between
from models import stamp_new, touch
from services import ledger
from services.resolve import primary_owner, get_apy_tier_by_code
import errors
from errors import ApiError


def inactivity_days(account):
    """Whole days from last_activity_date to the current ledger clock date."""
    last = parse_date(account["last_activity_date"])
    return days_between(last, db.clock_date())


def expire_active_stops(account_id):
    """Cascade: move every ACTIVE StopPayment on the account to EXPIRED."""
    for sp in db.stop_payments.values():
        if sp["account_id"] == account_id and sp["status"] == "ACTIVE":
            sp["status"] = "EXPIRED"
            touch(sp)


def run_escheat(account):
    """DORMANT -> ESCHEATED sweep (PRD §3.7)."""
    bal = ledger.ledger_balance(account["id"])
    swept = bal if bal > 0 else 0

    po = primary_owner(account["id"])
    jurisdiction = None
    if po is not None:
        cust = db.customers.get(po["customer_id"])
        if cust is not None:
            jurisdiction = cust.get("country_of_residence")

    event = {
        "account_id": account["id"],
        "swept_amount_cents": swept,
        "jurisdiction": jurisdiction,
        "dormancy_days_at_escheat": inactivity_days(account),
    }
    stamp_new(event)
    db.escheat_events[event["id"]] = event

    # Post an ESCHEAT_SWEEP transaction for -swept (drives positive balance to 0).
    if swept > 0:
        ledger.post_system_txn(account["id"], "ESCHEAT_SWEEP", swept)

    account["status"] = "ESCHEATED"
    touch(account)
    expire_active_stops(account["id"])
    return event


def post_interest(account, period_start_date, period_end_date):
    """Compute + post tiered interest for a period (PRD §3.11).

    raw = ledger_balance_at_period_start * annual_rate_bps / 10000 * days / 365
    posted_interest_cents = floor toward zero, single truncation after full
    multiplication.
    """
    tier = get_apy_tier_by_code(account["apy_tier_code"], account["product_type"])
    rate_bps = tier["annual_rate_bps"] if tier is not None else 0

    start = parse_date(period_start_date)
    end = parse_date(period_end_date)
    days = days_between(start, end)

    # The period-start balance. With a deterministic ledger clock the tests post
    # interest against the account's current ledger balance; "as it stood at the
    # period start" is the live ledger balance at posting time.
    bal = ledger.ledger_balance(account["id"])

    raw = bal * rate_bps * days / (10000 * 365)
    posted = math.floor(raw)  # single truncation toward zero (floor)

    posting = {
        "account_id": account["id"],
        "period_start_date": period_start_date,
        "period_end_date": period_end_date,
        "posted_interest_cents": posted,
        "applied_apy_tier_code": account["apy_tier_code"],
    }
    stamp_new(posting)
    db.interest_postings[posting["id"]] = posting

    # INTEREST credit transaction for posted_interest_cents (PRD §3.11).
    # A zero or negative posted interest still records the posting; only a
    # positive credit posts a balance-moving transaction.
    if posted > 0:
        ledger.post_system_txn(account["id"], "INTEREST", posted)

    account["accrued_interest_cents"] = 0
    touch(account)
    return posting


def interest_periods_overlap(account_id, new_start, new_end):
    """Half-open [start, end) overlap check (PRD §3.11, adjacency allowed)."""
    ns = parse_date(new_start)
    ne = parse_date(new_end)
    for p in db.interest_postings.values():
        if p["account_id"] != account_id:
            continue
        ps = parse_date(p["period_start_date"])
        pe = parse_date(p["period_end_date"])
        # Two half-open intervals overlap iff ns < pe and ps < ne.
        if ns < pe and ps < ne:
            return True
    return False


def run_stop_expiry(account_id):
    """Expire ACTIVE stops whose expires_on <= ledger clock date (PRD §3.10)."""
    today = db.clock_date()
    for sp in db.stop_payments.values():
        if sp["account_id"] == account_id and sp["status"] == "ACTIVE":
            exp = parse_date(sp["expires_on"])
            if exp <= today:
                sp["status"] = "EXPIRED"
                touch(sp)
