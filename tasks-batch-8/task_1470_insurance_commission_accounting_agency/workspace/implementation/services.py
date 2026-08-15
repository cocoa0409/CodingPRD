"""Business logic: calculations (scaffold 1.3), state-machine side effects,
cascades, the delinquency sweep, and serializers with derived fields."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import DB, new_id, next_seq, now_iso, today
from errors import ApiError
from util import parse_date, parse_dt

# ---- Calculation constants (scaffold 1.3) ----------------------------------
SUSPEND_THRESHOLD_CENTS = 500000      # strictly greater than $5,000.00 suspends
VARIANCE_TOLERANCE_CENTS = 100        # |reported - expected| <= 100 matches
MAX_OVERRIDE_SHARE_BPS = 2500         # override capped at 25% of booked BASE
FORM_1099_THRESHOLD_CENTS = 60000     # >= triggers a DRAFT form
GRACE_DAYS = 30
INVOICE_DUE_DAYS = 30                 # due_date = effective_date + 30 days

TIERS = ("STANDARD", "GOLD", "PLATINUM")
LINES_OF_BUSINESS = ("LIFE", "ANNUITY", "HEALTH", "PROPERTY_CASUALTY")
BILLING_TYPES = ("AGENCY_BILL", "DIRECT_BILL")


# ---- Low-level helpers ------------------------------------------------------

def rhu(value):
    """Round a Decimal to whole cents, half-up (PRD 2.6)."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rate_amount(base_cents, bps):
    """round_half_up(base_cents * bps / 10000)."""
    return rhu(Decimal(base_cents) * Decimal(bps) / Decimal(10000))


def new_resource(fields):
    t = now_iso()
    r = {"id": new_id(), "created_at": t, "updated_at": t, "version": 1, "_seq": next_seq()}
    r.update(fields)
    return r


def touch(r):
    """Every mutation refreshes updated_at and increments version (PRD 2.5)."""
    r["updated_at"] = now_iso()
    r["version"] += 1


def pub(r):
    return {k: v for k, v in r.items() if not k.startswith("_")}


def by_seq(items):
    return sorted(items, key=lambda r: r["_seq"])


def not_found(message="Referenced resource does not exist"):
    raise ApiError("ERR_NOT_FOUND", 404, message)


# ---- Derived producer aggregates (calculations.producer_balance_recompute) --

def producer_balance_cents(producer_id):
    earned = sum(
        e["amount_cents"]
        for e in DB["entries"].values()
        if e["producer_id"] == producer_id and e["status"] in ("EXPECTED", "MATCHED")
    )
    paid = sum(
        p["amount_cents"]
        for p in DB["payouts"].values()
        if p["producer_id"] == producer_id and p["status"] == "PAID"
    )
    return earned - paid


def producer_pending_chargebacks_cents(producer_id):
    return sum(
        c["amount_cents"] - c["recovered_cents"]
        for c in DB["chargebacks"].values()
        if c["producer_id"] == producer_id and c["status"] == "PENDING"
    )


def has_pending_chargebacks(producer_id):
    return any(
        c["producer_id"] == producer_id and c["status"] == "PENDING"
        for c in DB["chargebacks"].values()
    )


def suspension_check(producer_id):
    """Immediately after any Chargeback creation: pending total strictly above
    the threshold on an ACTIVE producer -> SUSPENDED (version + updated_at)."""
    p = DB["producers"].get(producer_id)
    if (
        p is not None
        and p["status"] == "ACTIVE"
        and producer_pending_chargebacks_cents(producer_id) > SUSPEND_THRESHOLD_CENTS
    ):
        p["status"] = "SUSPENDED"
        touch(p)


# ---- Schedules ---------------------------------------------------------------

def window_covers(schedule, date_str):
    """Half-open window: effective_from inclusive, effective_to exclusive."""
    if schedule["effective_from"] > date_str:
        return False
    return schedule["effective_to"] is None or date_str < schedule["effective_to"]


def find_covering_schedule(product_id, tier, effective_date):
    for s in by_seq(DB["schedules"].values()):
        if (
            s["product_id"] == product_id
            and s["tier"] == tier
            and s["status"] == "ACTIVE"
            and window_covers(s, effective_date)
        ):
            return s
    return None


def windows_overlap_half_open(f1, t1, f2, t2):
    """Half-open [from, to) intersection; None 'to' is open-ended."""
    if t2 is not None and f1 >= t2:
        return False
    if t1 is not None and f2 >= t1:
        return False
    return True


def periods_overlap_closed(s1, e1, s2, e2):
    """Closed-interval [start, end] intersection; shared boundary overlaps."""
    return s1 <= e2 and s2 <= e1


# ---- Commission entries -------------------------------------------------------

def create_entry(policy_id, producer_id, schedule_id, entry_type, amount_cents,
                 annualized_full, variant, status, matched_statement_id=None,
                 matched_at=None, source_entry_id=None):
    e = new_resource({
        "policy_id": policy_id,
        "producer_id": producer_id,
        "schedule_id": schedule_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "annualized_full_amount_cents": annualized_full,
        "variant": variant,
        "status": status,
        "matched_statement_id": matched_statement_id,
        "matched_at": matched_at,
        "source_entry_id": source_entry_id,
    })
    DB["entries"][e["id"]] = e
    return e


def policy_of(entry):
    return DB["policies"].get(entry["policy_id"])


def carrier_id_of_policy(policy):
    product = DB["products"].get(policy["product_id"])
    return product["carrier_id"] if product else None


# ---- Bind (calculations.expected_commission + override_commission) -----------

def nearest_active_ancestor(producer):
    """Walk upline_producer_id; skip non-ACTIVE ancestors; None when none."""
    seen = set()
    cur = producer.get("upline_producer_id")
    while cur:
        if cur in seen:
            return None
        seen.add(cur)
        p = DB["producers"].get(cur)
        if p is None:
            return None
        if p["status"] == "ACTIVE":
            return p
        cur = p.get("upline_producer_id")
    return None


def bind_policy(policy, producer, schedule):
    """QUOTED -> ACTIVE side effects: BASE entry, OVERRIDE entry, and the
    AGENCY_BILL premium invoice."""
    premium = policy["premium_annual_cents"]
    annual_full = rate_amount(premium, schedule["commission_rate_bps"])
    variant = (
        "ANNUALIZED_FULL" if schedule["advance_months"] == 12 else "ADVANCE_LIMITED"
    )
    if variant == "ANNUALIZED_FULL":
        amount = annual_full
    else:
        amount = rhu(Decimal(annual_full) * Decimal(schedule["advance_months"]) / Decimal(12))
    base = create_entry(
        policy["id"], producer["id"], schedule["id"], "BASE",
        amount, annual_full, variant, "EXPECTED",
    )
    # Override: nearest ACTIVE ancestor; skipped when rate is 0 or none exists.
    if schedule["override_rate_bps"] != 0:
        ancestor = nearest_active_ancestor(producer)
        if ancestor is not None:
            raw = rate_amount(premium, schedule["override_rate_bps"])
            cap = rate_amount(base["amount_cents"], MAX_OVERRIDE_SHARE_BPS)
            override = min(raw, cap)
            create_entry(
                policy["id"], ancestor["id"], schedule["id"], "OVERRIDE",
                override, override, variant, "EXPECTED",
            )
    policy["status"] = "ACTIVE"
    touch(policy)
    if policy["billing_type"] == "AGENCY_BILL":
        due = (parse_date(policy["effective_date"]) + timedelta(days=INVOICE_DUE_DAYS)).isoformat()
        inv = new_resource({
            "policy_id": policy["id"],
            "amount_cents": policy["premium_annual_cents"],
            "paid_total_cents": 0,
            "due_date": due,
            "status": "OPEN",
        })
        DB["invoices"][inv["id"]] = inv


# ---- Cancellation cascade (calculations.chargeback_unearned_commission) ------

def whole_months_between(date_str_a, date_str_b):
    """Whole calendar months from a to b: (dy)*12 + dm, minus one when the
    cancellation day-of-month is earlier than the effective day; clamp [0,12]."""
    a = parse_date(date_str_a)
    b = parse_date(date_str_b)
    m = (b.year - a.year) * 12 + (b.month - a.month)
    if b.day < a.day:
        m -= 1
    return max(0, min(12, m))


def cancellation_cascade(policy, cancel_effective_date, reason, new_status):
    """Shared cascade for CANCELLED_VOLUNTARY and CANCELLED_NONPAY."""
    policy["status"] = new_status
    policy["cancel_effective_date"] = cancel_effective_date
    policy["cancelled_at"] = now_iso()
    touch(policy)
    months_earned = whole_months_between(policy["effective_date"], cancel_effective_date)
    targets = [
        e for e in by_seq(DB["entries"].values())
        if e["policy_id"] == policy["id"] and e["status"] in ("EXPECTED", "MATCHED")
    ]
    affected_producers = []
    for e in targets:
        annual_full = e["annualized_full_amount_cents"]
        earned = min(
            rhu(Decimal(annual_full) * Decimal(months_earned) / Decimal(12)),
            e["amount_cents"],
        )
        unearned = e["amount_cents"] - earned
        e["status"] = "CHARGED_BACK"
        touch(e)
        # EARNED_ADJUSTMENT is always created, even when earned == 0.
        create_entry(
            e["policy_id"], e["producer_id"], e["schedule_id"], "EARNED_ADJUSTMENT",
            earned, earned, e["variant"], "MATCHED",
            matched_at=now_iso(), source_entry_id=e["id"],
        )
        if unearned > 0:
            cb = new_resource({
                "policy_id": e["policy_id"],
                "producer_id": e["producer_id"],
                "commission_entry_id": e["id"],
                "reason": reason,
                "amount_cents": unearned,
                "recovered_cents": 0,
                "status": "PENDING",
            })
            DB["chargebacks"][cb["id"]] = cb
            if e["producer_id"] not in affected_producers:
                affected_producers.append(e["producer_id"])
    for pid in affected_producers:
        suspension_check(pid)


# ---- Delinquency sweep (calculations.delinquency_evaluation) -----------------

def run_delinquency_sweep():
    """Fired after every logical-clock move. Calendar-day comparisons; the due
    date itself is still payable (current date must be strictly later)."""
    current = today()
    # Step 1: OPEN invoices past due and underpaid -> DELINQUENT.
    for inv in by_seq(DB["invoices"].values()):
        if (
            inv["status"] == "OPEN"
            and parse_date(inv["due_date"]) < current
            and inv["paid_total_cents"] < inv["amount_cents"]
        ):
            inv["status"] = "DELINQUENT"
            touch(inv)
    # Step 2: ACTIVE AGENCY_BILL policies with a delinquent invoice -> GRACE.
    for pol in by_seq(DB["policies"].values()):
        if pol["billing_type"] != "AGENCY_BILL" or pol["status"] != "ACTIVE":
            continue
        if any(
            inv["policy_id"] == pol["id"] and inv["status"] == "DELINQUENT"
            for inv in DB["invoices"].values()
        ):
            pol["status"] = "GRACE"
            touch(pol)
    # Step 3: GRACE policies whose oldest delinquent invoice is more than
    # GRACE_DAYS past due cancel for nonpayment (full cascade).
    for pol in by_seq(DB["policies"].values()):
        if pol["billing_type"] != "AGENCY_BILL" or pol["status"] != "GRACE":
            continue
        delinquent = [
            inv for inv in DB["invoices"].values()
            if inv["policy_id"] == pol["id"] and inv["status"] == "DELINQUENT"
        ]
        if not delinquent:
            continue
        oldest_due = min(parse_date(inv["due_date"]) for inv in delinquent)
        lapse_date = oldest_due + timedelta(days=GRACE_DAYS)
        if current > lapse_date:
            cancellation_cascade(pol, lapse_date.isoformat(), "NONPAY_LAPSE", "CANCELLED_NONPAY")


# ---- Statement reconciliation (calculations.statement_reconciliation) --------

def run_statement_matching(stmt):
    """Match each line, in array order, against the earliest-created EXPECTED
    BASE entry whose policy number and carrier match."""
    stmt["status"] = "RECONCILING"
    for line in stmt["lines"]:
        candidates = []
        for e in by_seq(DB["entries"].values()):
            if e["entry_type"] != "BASE" or e["status"] != "EXPECTED":
                continue
            pol = policy_of(e)
            if pol is None or pol["policy_number"] != line["line_ref"]:
                continue
            if carrier_id_of_policy(pol) != stmt["carrier_id"]:
                continue
            candidates.append(e)
        if not candidates:
            line["match_status"] = "ORPHAN"
            line["matched_entry_id"] = None
            continue
        entry = candidates[0]
        line["matched_entry_id"] = entry["id"]
        if abs(line["reported_amount_cents"] - entry["amount_cents"]) <= VARIANCE_TOLERANCE_CENTS:
            entry["status"] = "MATCHED"
            entry["matched_statement_id"] = stmt["id"]
            entry["matched_at"] = now_iso()
            touch(entry)
            line["match_status"] = "MATCHED"
        else:
            entry["status"] = "VARIANCE"
            entry["matched_statement_id"] = stmt["id"]
            touch(entry)
            line["match_status"] = "VARIANCE_FLAGGED"
    touch(stmt)


def resolve_variance(entry, accept_amount_cents):
    """VARIANCE -> MATCHED; flagging line -> MATCHED; VARIANCE_ADJUSTMENT entry;
    negative adjustment creates an OVERPAYMENT_VARIANCE chargeback."""
    stmt = DB["statements"].get(entry["matched_statement_id"])
    entry["status"] = "MATCHED"
    entry["matched_at"] = now_iso()
    touch(entry)
    if stmt is not None:
        for line in stmt["lines"]:
            if line.get("matched_entry_id") == entry["id"] and line["match_status"] == "VARIANCE_FLAGGED":
                line["match_status"] = "MATCHED"
                break
        touch(stmt)
    adjustment = accept_amount_cents - entry["amount_cents"]
    create_entry(
        entry["policy_id"], entry["producer_id"], entry["schedule_id"],
        "VARIANCE_ADJUSTMENT", adjustment, adjustment, entry["variant"], "MATCHED",
        matched_at=now_iso(), source_entry_id=entry["id"],
    )
    if adjustment < 0:
        cb = new_resource({
            "policy_id": entry["policy_id"],
            "producer_id": entry["producer_id"],
            "commission_entry_id": entry["id"],
            "reason": "OVERPAYMENT_VARIANCE",
            "amount_cents": -adjustment,
            "recovered_cents": 0,
            "status": "PENDING",
        })
        DB["chargebacks"][cb["id"]] = cb
        suspension_check(entry["producer_id"])


# ---- Trust remittance (calculations.trust_remittance) -------------------------

def retained_commission_cents(carrier_id):
    total = 0
    for e in DB["entries"].values():
        if e["status"] not in ("EXPECTED", "MATCHED"):
            continue
        pol = policy_of(e)
        if pol is None or pol["billing_type"] != "AGENCY_BILL":
            continue
        if carrier_id_of_policy(pol) != carrier_id:
            continue
        total += e["amount_cents"]
    return total


def remittable_cents(carrier):
    return carrier["trust_balance_cents"] - retained_commission_cents(carrier["id"])


# ---- 1099 (calculations.producer_compensation_1099) ---------------------------

def tax_year_window(tax_year):
    start = datetime(tax_year, 1, 1, tzinfo=timezone.utc)
    end = datetime(tax_year + 1, 1, 1, tzinfo=timezone.utc)
    return start, end


def cash_basis_total_cents(producer_id, tax_year):
    start, end = tax_year_window(tax_year)
    total = 0
    for p in DB["payouts"].values():
        if p["producer_id"] != producer_id or p["status"] != "PAID" or not p["paid_at"]:
            continue
        paid_at = parse_dt(p["paid_at"])
        if start <= paid_at < end:
            total += p["amount_cents"]
    return total


def accrual_basis_total_cents(producer_id, tax_year):
    start, end = tax_year_window(tax_year)
    total = 0
    for e in DB["entries"].values():
        if e["producer_id"] != producer_id or e["status"] != "MATCHED" or not e["matched_at"]:
            continue
        matched_at = parse_dt(e["matched_at"])
        if start <= matched_at < end:
            total += e["amount_cents"]
    return total


# ---- Serializers (derived fields computed at read time) -----------------------

def ser_producer(p):
    d = pub(p)
    d["commission_balance_cents"] = producer_balance_cents(p["id"])
    d["pending_chargebacks_cents"] = producer_pending_chargebacks_cents(p["id"])
    return d


def ser_carrier(c):
    return pub(c)


def ser_product(p):
    return pub(p)


def ser_schedule(s):
    return pub(s)


def ser_policy(p):
    return pub(p)


def ser_invoice(i):
    return pub(i)


def ser_statement(s):
    d = pub(s)
    d["lines"] = [dict(line) for line in s["lines"]]
    d["total_reported_cents"] = sum(l["reported_amount_cents"] for l in s["lines"])
    matched_lines = [l for l in s["lines"] if l["match_status"] == "MATCHED"]
    matched_total = sum(l["reported_amount_cents"] for l in matched_lines)
    expected_total = 0
    for l in matched_lines:
        entry = DB["entries"].get(l.get("matched_entry_id") or "")
        if entry is not None:
            expected_total += entry["amount_cents"]
    d["matched_total_cents"] = matched_total
    d["expected_matched_total_cents"] = expected_total
    d["variance_total_cents"] = matched_total - expected_total
    return d


def ser_entry(e):
    return pub(e)


def ser_chargeback(c):
    d = pub(c)
    d["outstanding_cents"] = c["amount_cents"] - c["recovered_cents"]
    return d


def ser_disclosure(d0):
    return pub(d0)


def ser_payout(p):
    return pub(p)


def ser_taxform(f):
    d = pub(f)
    if f["status"] == "FINALIZED":
        # Totals were recomputed and locked at finalization time.
        d["cash_basis_total_cents"] = f["cash_basis_total_cents"]
        d["accrual_basis_total_cents"] = f["accrual_basis_total_cents"]
    else:
        d["cash_basis_total_cents"] = cash_basis_total_cents(f["producer_id"], f["tax_year"])
        d["accrual_basis_total_cents"] = accrual_basis_total_cents(f["producer_id"], f["tax_year"])
    return d
