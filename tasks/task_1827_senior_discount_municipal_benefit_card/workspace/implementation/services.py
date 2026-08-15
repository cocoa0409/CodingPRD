"""Business logic: derived fields, cascades, clock transitions, calculations."""
import random
import string
from datetime import timedelta
from decimal import Decimal

import clock
import store
from util import bump, fmt_value, new_record, round_half_up_cents

# ---- program constants (scaffold calculations table) ----
MIN_AGE_YEARS = 65
INCOME_LIMIT_CENTS = 2400000
CARDHOLDER_MONTHLY_DISCOUNT_CAP_CENTS = 5000
FRAUD_SUSPEND_THRESHOLD = 3
CALENDAR_DAY_FLAG_THRESHOLD = 5
TRAILING_24H_REJECT_THRESHOLD = 10

CARD_LIVE_STATUSES = ("ACTIVE", "SUSPENDED")


# ---------------------------------------------------------------------------
# date helpers
# ---------------------------------------------------------------------------
def age_years(dob, on_date):
    """Whole years between dob and on_date, incrementing on the birthday."""
    return on_date.year - dob.year - ((on_date.month, on_date.day) < (dob.month, dob.day))


def add_calendar_years(dt, years):
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:  # Feb 29 -> Feb 28
        return dt.replace(year=dt.year + years, day=28)


# ---------------------------------------------------------------------------
# lookups / derived fields
# ---------------------------------------------------------------------------
def cardholder_transactions(ch_id):
    return [t for t in store.transactions.values() if t["cardholder_id"] == ch_id]


def cardholder_cards(ch_id):
    return [c for c in store.cards.values() if c["cardholder_id"] == ch_id]


def fraud_flag_count(ch_id):
    return sum(1 for t in cardholder_transactions(ch_id) if t["status"] == "FLAGGED")


def ytd_totals(ch_id):
    yr = clock.today().year
    incl = [t for t in cardholder_transactions(ch_id)
            if t["status"] in ("POSTED", "FLAGGED") and t["created_at"].year == yr]
    return sum(t["discount_cents"] for t in incl), len(incl)


def month_used_discount_cents(ch_id):
    today = clock.today()
    return sum(t["discount_cents"] for t in cardholder_transactions(ch_id)
               if t["status"] in ("POSTED", "FLAGGED")
               and t["created_at"].year == today.year
               and t["created_at"].month == today.month)


def current_month_reimbursed_cents(merchant_id):
    today = clock.today()
    return sum(c["final_amount_cents"] or 0 for c in store.claims.values()
               if c["merchant_id"] == merchant_id and c["status"] == "APPROVED"
               and c["updated_at"].year == today.year
               and c["updated_at"].month == today.month)


# ---------------------------------------------------------------------------
# calculations (scaffold section 1.3)
# ---------------------------------------------------------------------------
def select_offer(merchant_id, category):
    """ACTIVE offers of merchant+category whose half-open window holds today."""
    today = clock.today()
    cands = [o for o in store.offers.values()
             if o["merchant_id"] == merchant_id
             and o["category"] == category
             and o["status"] == "ACTIVE"
             and o["valid_from"] <= today < o["valid_until"]]
    if not cands:
        return None
    cands.sort(key=lambda o: (o["valid_from"], o["created_at"], o["_seq"]))
    return cands[0]


def compute_discount_cents(offer, purchase_amount_cents, ch_id):
    """Exact-rational raw -> per-txn cap -> monthly headroom -> round once."""
    raw = (Decimal(purchase_amount_cents)
           * Decimal(str(offer["discount_pct"])) / Decimal(100))
    capped = min(raw, Decimal(offer["max_discount_cents"]))
    remaining = max(CARDHOLDER_MONTHLY_DISCOUNT_CAP_CENTS
                    - month_used_discount_cents(ch_id), 0)
    granted = min(capped, Decimal(remaining))
    return round_half_up_cents(granted)


def claim_amount_cents(merchant, period_month, statuses):
    """Line-item rounding FIRST (round each line half-up), then sum."""
    year = int(period_month[:4])
    month = int(period_month[5:7])
    rate = Decimal(str(merchant["reimbursement_rate_pct"]))
    total = 0
    for t in store.transactions.values():
        if t["merchant_id"] != merchant["id"] or t["status"] not in statuses:
            continue
        if t["created_at"].year == year and t["created_at"].month == month:
            total += round_half_up_cents(
                Decimal(t["discount_cents"]) * rate / Decimal(100))
    return total


def velocity_counts(ch_id):
    """(trailing_24h_count, calendar_day_count), each including the candidate."""
    now = clock.now()
    window_start = now - timedelta(hours=24)
    trailing = 1
    cal_day = 1
    for t in cardholder_transactions(ch_id):
        if t["status"] == "VOIDED":
            continue
        if window_start < t["created_at"] <= now:
            trailing += 1
        if t["created_at"].date() == now.date():
            cal_day += 1
    return trailing, cal_day


# ---------------------------------------------------------------------------
# fraud cascades (scaffold state machines: UsageTransaction / Cardholder)
# ---------------------------------------------------------------------------
def after_transaction_flagged(ch):
    if (fraud_flag_count(ch["id"]) >= FRAUD_SUSPEND_THRESHOLD
            and ch["status"] in ("ACTIVE", "RECERTIFICATION_DUE")):
        ch["pre_suspension_status"] = ch["status"]
        ch["status"] = "SUSPENDED"
        bump(ch)
        for card in cardholder_cards(ch["id"]):
            if card["status"] == "ACTIVE":
                card["status"] = "SUSPENDED"
                bump(card)


def after_transaction_unflagged(ch):
    if fraud_flag_count(ch["id"]) < FRAUD_SUSPEND_THRESHOLD and ch["status"] == "SUSPENDED":
        ch["status"] = ch["pre_suspension_status"]
        ch["pre_suspension_status"] = None
        bump(ch)
        for card in cardholder_cards(ch["id"]):
            if card["status"] == "SUSPENDED":
                card["status"] = "ACTIVE"
                bump(card)


# ---------------------------------------------------------------------------
# cards
# ---------------------------------------------------------------------------
def mint_card_number():
    existing = {c["card_number"] for c in store.cards.values()}
    while True:
        n = "".join(random.choices(string.digits, k=16))
        if n not in existing:
            return n


def issue_card(ch, reason, replaces_card_id):
    rec = new_record()
    now = clock.now()
    rec.update({
        "cardholder_id": ch["id"],
        "card_number": mint_card_number(),
        "issue_reason": reason,
        "status": "ACTIVE",
        "issued_at": now,
        "expires_at": add_calendar_years(now, 2),
        "replaces_card_id": replaces_card_id,
    })
    store.cards[rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# logical-clock-driven transitions (PRD 2.4 dependency order)
# ---------------------------------------------------------------------------
def apply_time_transitions():
    now = clock.now()
    today = now.date()
    # 1. recertification window opening: ACTIVE -> RECERTIFICATION_DUE
    for ch in store.cardholders.values():
        if ch["status"] == "ACTIVE" and ch["recertification_due_date"] is not None:
            if today >= ch["recertification_due_date"] - timedelta(days=60):
                ch["status"] = "RECERTIFICATION_DUE"
                bump(ch)
    # 2. lapse: RECERTIFICATION_DUE -> LAPSED; cards ACTIVE|SUSPENDED -> EXPIRED
    for ch in store.cardholders.values():
        if ch["status"] == "RECERTIFICATION_DUE" and ch["recertification_due_date"] is not None:
            if today >= ch["recertification_due_date"] + timedelta(days=1):
                ch["status"] = "LAPSED"
                bump(ch)
                for card in cardholder_cards(ch["id"]):
                    if card["status"] in CARD_LIVE_STATUSES:
                        card["status"] = "EXPIRED"
                        bump(card)
    # 3. card expiry: clock >= expires_at
    for card in store.cards.values():
        if card["status"] in CARD_LIVE_STATUSES and now >= card["expires_at"]:
            card["status"] = "EXPIRED"
            bump(card)
    # 4. offer retirement: clock date >= valid_until
    for off in store.offers.values():
        if off["status"] == "ACTIVE" and today >= off["valid_until"]:
            off["status"] = "RETIRED"
            bump(off)


# ---------------------------------------------------------------------------
# serializers
# ---------------------------------------------------------------------------
def application_out(r):
    return {
        "id": r["id"],
        "kind": r["kind"],
        "applicant_full_name": r["applicant_full_name"],
        "date_of_birth": fmt_value(r["date_of_birth"]),
        "annual_income_cents": r["annual_income_cents"],
        "residency_address": r["residency_address"],
        "cardholder_id": r["cardholder_id"],
        "status": r["status"],
        "reviewed_by_user_id": r["reviewed_by_user_id"],
        "info_request_reason": r["info_request_reason"],
        "denial_reason": r["denial_reason"],
        "decided_by_user_id": r["decided_by_user_id"],
        "created_at": fmt_value(r["created_at"]),
        "updated_at": fmt_value(r["updated_at"]),
        "version": r["version"],
    }


def document_out(r):
    return {
        "id": r["id"],
        "application_id": r["application_id"],
        "document_type": r["document_type"],
        "document_reference": r["document_reference"],
        "status": r["status"],
        "reviewed_by_user_id": r["reviewed_by_user_id"],
        "rejection_reason": r["rejection_reason"],
        "created_at": fmt_value(r["created_at"]),
        "updated_at": fmt_value(r["updated_at"]),
        "version": r["version"],
    }


def cardholder_out(r):
    ytd_discount, ytd_count = ytd_totals(r["id"])
    return {
        "id": r["id"],
        "full_name": r["full_name"],
        "date_of_birth": fmt_value(r["date_of_birth"]),
        "annual_income_cents": r["annual_income_cents"],
        "residency_address": r["residency_address"],
        "status": r["status"],
        "pre_suspension_status": r["pre_suspension_status"],
        "recertification_due_date": fmt_value(r["recertification_due_date"]),
        "fraud_flag_count": fraud_flag_count(r["id"]),
        "ytd_discount_cents": ytd_discount,
        "ytd_transaction_count": ytd_count,
        "age_years": age_years(r["date_of_birth"], clock.today()),
        "created_at": fmt_value(r["created_at"]),
        "updated_at": fmt_value(r["updated_at"]),
        "version": r["version"],
    }


def card_out(r):
    return {
        "id": r["id"],
        "cardholder_id": r["cardholder_id"],
        "card_number": r["card_number"],
        "issue_reason": r["issue_reason"],
        "status": r["status"],
        "issued_at": fmt_value(r["issued_at"]),
        "expires_at": fmt_value(r["expires_at"]),
        "replaces_card_id": r["replaces_card_id"],
        "created_at": fmt_value(r["created_at"]),
        "updated_at": fmt_value(r["updated_at"]),
        "version": r["version"],
    }


def merchant_out(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "reimbursement_rate_pct": r["reimbursement_rate_pct"],
        "monthly_reimbursement_cap_cents": r["monthly_reimbursement_cap_cents"],
        "status": r["status"],
        "current_month_reimbursed_cents": current_month_reimbursed_cents(r["id"]),
        "created_at": fmt_value(r["created_at"]),
        "updated_at": fmt_value(r["updated_at"]),
        "version": r["version"],
    }


def offer_out(r):
    return {
        "id": r["id"],
        "merchant_id": r["merchant_id"],
        "category": r["category"],
        "discount_pct": r["discount_pct"],
        "max_discount_cents": r["max_discount_cents"],
        "valid_from": fmt_value(r["valid_from"]),
        "valid_until": fmt_value(r["valid_until"]),
        "status": r["status"],
        "created_at": fmt_value(r["created_at"]),
        "updated_at": fmt_value(r["updated_at"]),
        "version": r["version"],
    }


def waiver_out(r):
    return {
        "id": r["id"],
        "cardholder_id": r["cardholder_id"],
        "waiver_type": r["waiver_type"],
        "start_date": fmt_value(r["start_date"]),
        "end_date": fmt_value(r["end_date"]),
        "created_at": fmt_value(r["created_at"]),
        "updated_at": fmt_value(r["updated_at"]),
        "version": r["version"],
    }


def transaction_out(r):
    return {
        "id": r["id"],
        "card_id": r["card_id"],
        "merchant_id": r["merchant_id"],
        "cardholder_id": r["cardholder_id"],
        "offer_id": r["offer_id"],
        "category": r["category"],
        "purchase_amount_cents": r["purchase_amount_cents"],
        "discount_cents": r["discount_cents"],
        "status": r["status"],
        "flagged_by_user_id": r["flagged_by_user_id"],
        "flag_reason": r["flag_reason"],
        "voided_by_user_id": r["voided_by_user_id"],
        "created_at": fmt_value(r["created_at"]),
        "updated_at": fmt_value(r["updated_at"]),
        "version": r["version"],
    }


def claim_out(r):
    return {
        "id": r["id"],
        "merchant_id": r["merchant_id"],
        "period_month": r["period_month"],
        "program_fund_id": r["program_fund_id"],
        "provisional_amount_cents": r["provisional_amount_cents"],
        "final_amount_cents": r["final_amount_cents"],
        "status": r["status"],
        "denial_reason": r["denial_reason"],
        "created_at": fmt_value(r["created_at"]),
        "updated_at": fmt_value(r["updated_at"]),
        "version": r["version"],
    }


def fund_out(r):
    return {
        "id": r["id"],
        "fiscal_year": r["fiscal_year"],
        "allocated_cents": r["allocated_cents"],
        "paid_cents": r["paid_cents"],
        "available_cents": r["allocated_cents"] - r["paid_cents"],
        "created_at": fmt_value(r["created_at"]),
        "updated_at": fmt_value(r["updated_at"]),
        "version": r["version"],
    }
