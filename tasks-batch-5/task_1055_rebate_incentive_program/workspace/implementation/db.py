"""In-memory store, logical clock and shared helpers.

The store starts EMPTY on every boot. Nothing is seeded.
"""
import itertools
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import err

# --------------------------------------------------------------------------
# Constants (SCAFFOLD `constants` block)
# --------------------------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-07-01T00:00:00Z"

CLAIM_WINDOW_DAYS = 90
OFFER_GRACE_DAYS = 15
DEDUPE_WINDOW_DAYS = 365
MAX_CLAIMS_PER_CLAIMANT_PER_OFFER = 3
RECEIPT_MAX_LINES = 20
APPEAL_WINDOW_DAYS = 30
MAX_APPEALS_PER_CLAIM = 2

DEALER_TIER_1_MAX_UNITS = 9
DEALER_TIER_2_MAX_UNITS = 49
DEALER_TIER_1_PCT = Decimal("0.05")
DEALER_TIER_2_PCT = Decimal("0.08")
DEALER_TIER_3_PCT = Decimal("0.12")
CONSUMER_REBATE_PCT = Decimal("0.10")
CONSUMER_FLAT_BONUS_CENTS = 500

RESERVE_FACTOR = Decimal("0.15")
BUDGET_WARN_PCT = Decimal("0.8000")
BUDGET_HARD_PCT = Decimal("1.0000")

CHECK_FEE_CENTS = 150
CARD_FEE_CENTS = 50
CARD_METHOD_MIN_CENTS = 2500
PAYOUT_MIN_CENTS = 100

ESCHEAT_DORMANCY_DAYS = 180
CARD_DORMANCY_DAYS = 90
VIRTUAL_CARD_VALID_DAYS = 365

FRAUD_SCORE_MIN = 0
FRAUD_SCORE_MAX = 100
FRAUD_SCORE_THRESHOLD = 70
W_DENIED = 15
W_DUPLICATE = 25
W_VELOCITY = 10
W_HIGH_VALUE = 20
VELOCITY_FREE_CLAIMS = 2
VELOCITY_WINDOW_DAYS = 30
HIGH_VALUE_CLAIM_CENTS = 50000
SUBSTANTIATION_MULTIPLIER = Decimal("1.5")
CLEARANCE_CREDIT = 30

ROLES = {
    "ProgramAdmin",
    "ClaimsProcessor",
    "FinanceOfficer",
    "FraudAnalyst",
    "Dealer",
    "Consumer",
}
CLAIMANT_ROLES = {"Dealer", "Consumer"}

CLAIM_TERMINAL_ADJ = {"APPROVED", "REVOKED", "WITHDRAWN", "VOIDED"}
CLAIM_OPEN_ADJ = {"SUBMITTED", "UNDER_REVIEW", "HELD"}
CLAIM_ACTIVE_ADJ = {"SUBMITTED", "UNDER_REVIEW", "HELD", "APPROVED"}

# --------------------------------------------------------------------------
# Stores
# --------------------------------------------------------------------------
programs = {}
offers = {}
claimants = {}
claims = {}
receipts = {}
payouts = {}
virtual_cards = {}
escheat_records = {}
budget_entries = {}
fraud_cases = {}

_seq = itertools.count(1)

_clock = {"now": None}


def parse_iso(value):
    """Parse an ISO-8601 instant. Returns an aware UTC datetime or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        if not isinstance(value, str) or not value.strip():
            return None
        text = value.strip()
        if text.endswith("Z") or text.endswith("z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now():
    """The logical clock."""
    if _clock["now"] is None:
        _clock["now"] = parse_iso(DEFAULT_CLOCK_UTC)
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt
    return _clock["now"]


def reset():
    for store in (
        programs, offers, claimants, claims, receipts, payouts,
        virtual_cards, escheat_records, budget_entries, fraud_cases,
    ):
        store.clear()
    _clock["now"] = parse_iso(DEFAULT_CLOCK_UTC)


def whole_days(later, earlier):
    """Number of complete 24h days elapsed from `earlier` to `later` (floored)."""
    delta = later - earlier
    return int(delta.total_seconds() // 86400)


def new_id():
    return str(uuid.uuid4())


def base_record(versioned=True):
    ts = now()
    rec = {"id": new_id(), "created_at": ts, "_seq": next(_seq)}
    if versioned:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Record a mutation: bump version and refresh updated_at."""
    if "version" in rec:
        rec["version"] += 1
        rec["updated_at"] = now()
    return rec


def by_created(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round4(value):
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def add_days(dt, days):
    return dt + timedelta(days=days)


# --------------------------------------------------------------------------
# Lookup helpers (raise the scaffold-declared not-found errors)
# --------------------------------------------------------------------------
def _get(store, rid, error_id):
    rec = store.get(rid)
    if rec is None:
        raise err(error_id)
    return rec


def get_program(rid):
    return _get(programs, rid, "ERR_PROGRAM_NOT_FOUND")


def get_offer(rid):
    return _get(offers, rid, "ERR_OFFER_NOT_FOUND")


def get_claimant(rid):
    return _get(claimants, rid, "ERR_CLAIMANT_NOT_FOUND")


def get_claim(rid):
    return _get(claims, rid, "ERR_CLAIM_NOT_FOUND")


def get_receipt(rid):
    return _get(receipts, rid, "ERR_RECEIPT_NOT_FOUND")


def get_payout(rid):
    return _get(payouts, rid, "ERR_PAYOUT_NOT_FOUND")


def get_card(rid):
    return _get(virtual_cards, rid, "ERR_CARD_NOT_FOUND")


def get_fraud_case(rid):
    return _get(fraud_cases, rid, "ERR_FRAUD_CASE_NOT_FOUND")


def get_escheat_record(rid):
    rec = escheat_records.get(rid)
    if rec is None:
        raise err("ERR_PROGRAM_NOT_FOUND", "Escheat record not found.")
    return rec


def get_budget_entry(rid):
    rec = budget_entries.get(rid)
    if rec is None:
        raise err("ERR_PROGRAM_NOT_FOUND", "Budget entry not found.")
    return rec


# --------------------------------------------------------------------------
# Relationship helpers
# --------------------------------------------------------------------------
def offers_of_program(program_id):
    return by_created([o for o in offers.values() if o["program_id"] == program_id])


def claims_of_program(program_id):
    out = []
    for c in claims.values():
        offer = offers.get(c["offer_id"])
        if offer is not None and offer["program_id"] == program_id:
            out.append(c)
    return by_created(out)


def claims_of_offer(offer_id):
    return by_created([c for c in claims.values() if c["offer_id"] == offer_id])


def claims_of_claimant(claimant_id):
    return by_created([c for c in claims.values() if c["claimant_id"] == claimant_id])


def receipts_of_claim(claim_id):
    return by_created([r for r in receipts.values() if r["claim_id"] == claim_id])


def payouts_of_claim(claim_id):
    return by_created([p for p in payouts.values() if p["claim_id"] == claim_id])


def cards_of_payout(payout_id):
    return by_created([c for c in virtual_cards.values() if c["payout_id"] == payout_id])


def entries_of_program(program_id):
    return by_created([e for e in budget_entries.values() if e["program_id"] == program_id])


def cases_of_claimant(claimant_id):
    return by_created([f for f in fraud_cases.values() if f["claimant_id"] == claimant_id])


def program_of_claim(claim):
    offer = offers.get(claim["offer_id"])
    if offer is None:
        return None
    return programs.get(offer["program_id"])


def program_of_payout(payout):
    claim = claims.get(payout["claim_id"])
    if claim is None:
        return None
    return program_of_claim(claim)
