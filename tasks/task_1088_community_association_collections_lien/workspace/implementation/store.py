"""In-memory data store, logical clock, helpers, computed fields and services.

Storage is process-local Python dicts only. Every boot starts empty; there is
NO seeding of any entity at startup.
"""
import math
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------
NOTICE_COOLDOWN_DAYS = 30
VALIDATION_PERIOD_DAYS = 30
PLAN_MISSED_BREACH_THRESHOLD = 2
LIEN_MINIMUM_BALANCE_CENTS = 180000
PAYOFF_GOOD_THROUGH_DAYS = 15
INTEREST_DAY_COUNT = 365
DELINQUENCY_GRACE_DAYS = 30

CLOCK_DEFAULT = "2026-05-01T00:00:00Z"

CHARGE_TYPES = ["REGULAR", "SPECIAL", "LATE_FEE", "INTEREST", "ATTORNEY_COST", "FINE"]
CHARGE_PRIORITY = {
    "ATTORNEY_COST": 0,
    "FINE": 1,
    "LATE_FEE": 2,
    "INTEREST": 3,
    "SPECIAL": 4,
    "REGULAR": 5,
}
NOTICE_TYPES = ["VALIDATION", "DEMAND", "INTENT_TO_LIEN", "INTENT_TO_FORECLOSE"]
CHAPTERS = ["CH7", "CH13"]
REVERSAL_REASONS = ["NSF", "ADJUSTMENT"]
REMITTANCE_BASIS = ["CASH", "NET"]

ROLES = {"CollectionsAgent", "ComplianceOfficer", "TrustAccountant", "AssociationManager"}

# --------------------------------------------------------------------------
# Data store (all in-memory, empty on boot)
# --------------------------------------------------------------------------
associations = {}
accounts = {}
assessments = {}
payments = {}
notices = {}
plans = {}
liens = {}
referrals = {}
bankruptcies = {}
remittances = {}

_seq = 0
_touched = set()


class _Clock:
    def __init__(self):
        self.now = parse_iso(CLOCK_DEFAULT)

    def set(self, iso):
        self.now = parse_iso(iso)


# --------------------------------------------------------------------------
# time / id helpers
# --------------------------------------------------------------------------
def parse_iso(s):
    """Parse an ISO8601 string (date or datetime, optional Z) to aware UTC dt."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        # date-only fallback
        dt = datetime.fromisoformat(t + "T00:00:00")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_date(dt):
    """Canonical plain-second UTC instant for generated domain date fields
    (sent_date, dispute_date, final_due_date, ...). Matches PRD's own instant
    notation ('...T00:00:00Z'); created_at/updated_at keep three fractional
    digits via fmt_iso."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


clock = _Clock()


def now_dt():
    return clock.now


def now_iso():
    return fmt_iso(clock.now)


def now_date():
    return fmt_date(clock.now)


def new_id():
    return str(uuid.uuid4())


def day_floor(later, earlier):
    return math.floor((later - earlier).total_seconds() / 86400.0)


def round_half_up_cents(dec_value):
    return int(Decimal(dec_value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# common-field / mutation helpers
# --------------------------------------------------------------------------
def reset_touched():
    global _touched
    _touched = set()


def stamp_new(ent):
    global _seq
    _seq += 1
    ent["id"] = new_id()
    ent["created_at"] = now_iso()
    ent["updated_at"] = now_iso()
    ent["version"] = 1
    ent["_cseq"] = _seq
    ent["_cdt"] = now_dt()
    return ent


def touch(ent):
    """Bump version + updated_at once per request for this resource."""
    key = id(ent)
    if key in _touched:
        return
    _touched.add(key)
    ent["updated_at"] = now_iso()
    ent["version"] += 1


# --------------------------------------------------------------------------
# reverse-lookup helpers
# --------------------------------------------------------------------------
def account_assessments(account_id):
    return [a for a in assessments.values() if a["account_id"] == account_id]


def account_payments(account_id):
    return [p for p in payments.values() if p["account_id"] == account_id]


def account_notices(account_id):
    return [n for n in notices.values() if n["account_id"] == account_id]


def account_plans(account_id):
    return [p for p in plans.values() if p["account_id"] == account_id]


def account_liens(account_id):
    return [l for l in liens.values() if l["account_id"] == account_id]


def account_referrals(account_id):
    return [r for r in referrals.values() if r["account_id"] == account_id]


def account_bankruptcies(account_id):
    return [b for b in bankruptcies.values() if b["account_id"] == account_id]


def association_accounts(association_id):
    return [a for a in accounts.values() if a["association_id"] == association_id]


def association_of_account(account_id):
    acc = accounts.get(account_id)
    return acc["association_id"] if acc else None


# --------------------------------------------------------------------------
# computed quantities
# --------------------------------------------------------------------------
def account_total_balance(account_id):
    return sum(a["balance_cents"] for a in account_assessments(account_id)
               if a["status"] in ("OPEN", "PARTIAL"))


def account_aging(account_id):
    buckets = {
        "bucket_current": 0,
        "bucket_1_30": 0,
        "bucket_31_60": 0,
        "bucket_61_90": 0,
        "bucket_91_plus": 0,
    }
    now = now_dt()
    for a in account_assessments(account_id):
        if a["status"] not in ("OPEN", "PARTIAL"):
            continue
        d = day_floor(now, parse_iso(a["due_date"]))
        bal = a["balance_cents"]
        if d <= 0:
            buckets["bucket_current"] += bal
        elif d <= 30:
            buckets["bucket_1_30"] += bal
        elif d <= 60:
            buckets["bucket_31_60"] += bal
        elif d <= 90:
            buckets["bucket_61_90"] += bal
        else:
            buckets["bucket_91_plus"] += bal
    return buckets


def association_trust_balance(association_id):
    acct_ids = {a["id"] for a in association_accounts(association_id)}
    posted = sum(p["amount_cents"] for p in payments.values()
                 if p["account_id"] in acct_ids and p["status"] == "POSTED")
    remitted = sum(r["gross_amount_cents"] for r in remittances.values()
                   if r["association_id"] == association_id and r["status"] == "REMITTED")
    return posted - remitted


def plan_amount_paid(plan):
    activated = plan.get("_activated_dt")
    if activated is None:
        return 0
    total = 0
    for p in account_payments(plan["account_id"]):
        if p["status"] != "POSTED":
            continue
        if p["_cdt"] >= activated:
            total += p["amount_cents"]
    return total


def plan_missed_count(plan):
    now = now_dt()
    first = parse_iso(plan["first_due_date"])
    num = plan["num_installments"]
    inst = plan["installment_cents"]
    installments_due = 0
    for k in range(1, num + 1):
        sched = first + timedelta(days=30 * (k - 1))
        if sched <= now:
            installments_due += 1
    expected = min(installments_due, num) * inst
    paid = plan_amount_paid(plan)
    if paid >= expected or inst <= 0:
        return 0
    shortfall = expected - paid
    return math.ceil(shortfall / inst)


# --------------------------------------------------------------------------
# serializers
# --------------------------------------------------------------------------
_COMMON_OUT = ("id", "created_at", "updated_at", "version")


def ser_association(a):
    return {
        "id": a["id"],
        "name": a["name"],
        "state_code": a["state_code"],
        "interest_rate_annual_pct": a["interest_rate_annual_pct"],
        "late_fee_cents": a["late_fee_cents"],
        "management_fee_pct": a["management_fee_pct"],
        "status": a["status"],
        "trust_balance_cents": association_trust_balance(a["id"]),
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_account(a):
    return {
        "id": a["id"],
        "association_id": a["association_id"],
        "unit_number": a["unit_number"],
        "owner_name": a["owner_name"],
        "status": a["status"],
        "total_balance_cents": account_total_balance(a["id"]),
        "aging": account_aging(a["id"]),
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_assessment(a):
    return {
        "id": a["id"],
        "account_id": a["account_id"],
        "charge_type": a["charge_type"],
        "amount_cents": a["amount_cents"],
        "due_date": a["due_date"],
        "balance_cents": a["balance_cents"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_payment(p):
    return {
        "id": p["id"],
        "account_id": p["account_id"],
        "amount_cents": p["amount_cents"],
        "received_date": p["received_date"],
        "allocations": p["allocations"],
        "unapplied_cents": p["unapplied_cents"],
        "status": p["status"],
        "reversal_reason": p["reversal_reason"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_notice(n):
    return {
        "id": n["id"],
        "account_id": n["account_id"],
        "notice_type": n["notice_type"],
        "status": n["status"],
        "sent_date": n["sent_date"],
        "dispute_date": n["dispute_date"],
        "created_at": n["created_at"],
        "updated_at": n["updated_at"],
        "version": n["version"],
    }


def ser_plan(p):
    return {
        "id": p["id"],
        "account_id": p["account_id"],
        "total_amount_cents": p["total_amount_cents"],
        "installment_cents": p["installment_cents"],
        "num_installments": p["num_installments"],
        "first_due_date": p["first_due_date"],
        "final_due_date": p["final_due_date"],
        "amount_paid_cents": plan_amount_paid(p),
        "missed_count": plan_missed_count(p),
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_lien(l):
    return {
        "id": l["id"],
        "account_id": l["account_id"],
        "recorded_amount_cents": l["recorded_amount_cents"],
        "recorded_date": l["recorded_date"],
        "recorded_by_user_id": l["recorded_by_user_id"],
        "status": l["status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def ser_referral(r):
    return {
        "id": r["id"],
        "account_id": r["account_id"],
        "lien_id": r["lien_id"],
        "attorney_name": r["attorney_name"],
        "referred_by_user_id": r["referred_by_user_id"],
        "referred_date": r["referred_date"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_bankruptcy(b):
    return {
        "id": b["id"],
        "account_id": b["account_id"],
        "chapter": b["chapter"],
        "case_number": b["case_number"],
        "filed_date": b["filed_date"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def ser_remittance(r):
    return {
        "id": r["id"],
        "association_id": r["association_id"],
        "period_start": r["period_start"],
        "period_end": r["period_end"],
        "basis": r["basis"],
        "gross_amount_cents": r["gross_amount_cents"],
        "management_fee_cents": r["management_fee_cents"],
        "net_amount_cents": r["net_amount_cents"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }
