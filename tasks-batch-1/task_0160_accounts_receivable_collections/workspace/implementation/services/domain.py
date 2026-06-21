"""Core domain logic: aging, derived-field recomputation, posture cascade,
calculations, and serialization.

All money is integer cents. The system clock (db.now_ms) is the override-able
clock from PRD §3.10; aging and promise coverage comparisons use it.
"""
from services.common import touch, round_half_up_int, round_half_up_2
import db

DAY_MS = 86400000

# Aging bucket ordering, worst-last for "worst" comparisons.
AGING_ORDER = ["CURRENT", "B1_30", "B31_60", "B61_90", "B91_PLUS"]

COLLECT_PROB = {
    "CURRENT": 1.0,
    "B1_30": 0.90,
    "B31_60": 0.70,
    "B61_90": 0.40,
    "B91_PLUS": 0.10,
}

AGE_WEIGHT = {"CURRENT": 0.0, "B1_30": 1.0, "B31_60": 2.0, "B61_90": 3.0, "B91_PLUS": 4.0}
STAGE_WEIGHT = {"CURRENT": 0.0, "DUNNING": 1.0, "COLLECTIONS": 2.0, "WRITEOFF": 0.0}

CREDIT_WATCH_PCT = 0.80
MONTHLY_RATE = 0.015

W_BAL = 1.0
W_AGE = 2.0
W_STAGE = 1.5
W_PTP = 3.0


# ---------------------------------------------------------------------------
# Aging (PRD §3.2, calculations.aging_bucket_assignment).
# ---------------------------------------------------------------------------
def days_overdue(reference_ms, now=None):
    now_ = db.now_ms() if now is None else now
    return (now_ - reference_ms) // DAY_MS  # floor of whole UTC days


def aging_bucket(invoice, basis="due"):
    """basis: 'due' (due_date) for dunning/credit; 'invoice' (invoice_date) for
    the statement aging report. Paid/written-off -> CURRENT."""
    if invoice["status"] in ("PAID", "WRITTEN_OFF"):
        return "CURRENT"
    ref = invoice["due_date_ms"] if basis == "due" else invoice["invoice_date_ms"]
    d = days_overdue(ref)
    if d < 1:
        return "CURRENT"
    elif d <= 30:
        return "B1_30"
    elif d <= 60:
        return "B31_60"
    elif d <= 90:
        return "B61_90"
    else:
        return "B91_PLUS"


def dunnable(invoice):
    return invoice["balance_cents"] - invoice["disputed_amount_cents"]


def customer_invoices(customer_id):
    return [iv for iv in db.invoices.values() if iv["customer_id"] == customer_id]


# ---------------------------------------------------------------------------
# Derived balances & credit posture (PRD §2.6, §2.7).
# ---------------------------------------------------------------------------
def compute_exposure(customer_id):
    total = 0
    for iv in customer_invoices(customer_id):
        if iv["status"] in ("OPEN", "PARTIAL"):
            total += dunnable(iv)
    return total


def compute_total_open_balance(customer_id):
    total = 0
    for iv in customer_invoices(customer_id):
        if iv["status"] in ("OPEN", "PARTIAL", "DISPUTED"):
            total += iv["balance_cents"]
    return total


def eval_credit_status(customer):
    """PRD §2.7. Fixed order: manual_hold -> >=limit HOLD -> >=80% WATCH -> GOOD.
    Boundary inclusive (>=). Watch threshold = round_half_up(0.80 * limit).

    A promise break (PRD §3.5) pushes credit_status to WATCH directly; we record
    that as an internal sticky 'watch_floor' so a later exposure-driven recompute
    (which §2.7/§3.1 perform from exposure alone) does not silently drop the
    posture back to GOOD. The floor only raises GOOD->WATCH; HOLD still wins."""
    exposure = customer["exposure_cents"]
    limit = customer["credit_limit_cents"]
    if customer["manual_hold"]:
        return "HOLD"
    if exposure >= limit:
        return "HOLD"
    watch_threshold = round_half_up_int(CREDIT_WATCH_PCT * limit)
    if exposure >= watch_threshold:
        return "WATCH"
    if customer.get("watch_floor"):
        return "WATCH"
    return "GOOD"


def eval_collection_stage(customer):
    """PRD §3.5 / calculations.collection_stage_eval."""
    cid = customer["id"]
    invs = customer_invoices(cid)
    # worst aging over OPEN/PARTIAL/DISPUTED on due-date basis
    worst_idx = 0
    for iv in invs:
        if iv["status"] in ("OPEN", "PARTIAL", "DISPUTED"):
            b = aging_bucket(iv, "due")
            worst_idx = max(worst_idx, AGING_ORDER.index(b))
    worst = AGING_ORDER[worst_idx]

    has_writeoff = any(iv["status"] == "WRITTEN_OFF" for iv in invs)
    has_broken_promise = _has_unredeemed_broken_promise(cid)

    if has_writeoff:
        return "WRITEOFF"
    if worst == "CURRENT" and not has_broken_promise:
        return "CURRENT"
    if has_broken_promise or worst in ("B61_90", "B91_PLUS"):
        return "COLLECTIONS"
    return "DUNNING"


def compute_promise_applied(promise):
    """applied_payment_cents (PRD §3.5): payments received within the promise's
    half-open coverage window [coverage_start, coverage_end), credited toward
    the commitment. Computed from the customer's payments by received_at."""
    total = 0
    for p in db.payments.values():
        if p["customer_id"] != promise["customer_id"]:
            continue
        rec_ms = p.get("received_at_ms")
        if rec_ms is None:
            continue
        if promise["coverage_start_ms"] <= rec_ms < promise["coverage_end_ms"]:
            total += p["amount_cents"]
    return total


def recompute_stage_only(customer):
    """Recompute only collection_stage (parallel dimension), leaving
    credit_status untouched. Used by the promise-break cascade where
    credit_status is set directly to WATCH rather than from exposure."""
    before = customer["collection_stage"]
    customer["collection_stage"] = eval_collection_stage(customer)
    if before != customer["collection_stage"]:
        touch(customer)
    return customer


def _has_unredeemed_broken_promise(customer_id):
    """A BROKEN promise with no later KEPT promise (by created_at)."""
    broken = []
    kept = []
    for p in db.promises.values():
        if p["customer_id"] != customer_id:
            continue
        if p["status"] == "BROKEN":
            broken.append(p)
        elif p["status"] == "KEPT":
            kept.append(p)
    if not broken:
        return False
    latest_broken = max(b["created_at"] for b in broken)
    latest_kept = max((k["created_at"] for k in kept), default=None)
    if latest_kept is not None and latest_kept > latest_broken:
        return False
    return True


def recompute_customer(customer, recompute_stage=False, already_touched=False):
    """Recompute derived fields. Bumps the customer's version/updated_at only if
    something actually changed (PRD §2.6: 'Each such recomputation that alters
    the customer is a mutation of the customer').

    When ``already_touched`` is set, the caller has already counted this single
    logical operation as one customer mutation (one version increment), so the
    recompute refreshes derived fields without adding a second increment — a
    hold/release is one mutation, not two (PRD §2.4)."""
    before = (
        customer["exposure_cents"],
        customer["total_open_balance_cents"],
        customer["credit_status"],
        customer["collection_stage"],
    )
    cid = customer["id"]
    customer["exposure_cents"] = compute_exposure(cid)
    customer["total_open_balance_cents"] = compute_total_open_balance(cid)
    customer["credit_status"] = eval_credit_status(customer)
    if recompute_stage:
        customer["collection_stage"] = eval_collection_stage(customer)
    after = (
        customer["exposure_cents"],
        customer["total_open_balance_cents"],
        customer["credit_status"],
        customer["collection_stage"],
    )
    if before != after and not already_touched:
        touch(customer)
    return customer


# ---------------------------------------------------------------------------
# Calculations: collection_priority_score (PRD §3.7).
# ---------------------------------------------------------------------------
def collection_priority_score(invoice, customer, now=None):
    dun = dunnable(invoice)
    bal_term = W_BAL * min(dun / 100000.0, 10.0)
    age_term = W_AGE * AGE_WEIGHT[aging_bucket(invoice, "due")]
    stage_term = W_STAGE * STAGE_WEIGHT[customer["collection_stage"]]
    ptp = 1 if _has_active_promise_covering_today(customer["id"], now) else 0
    score = bal_term + age_term + stage_term - W_PTP * ptp
    return round_half_up_2(score)


def _has_active_promise_covering_today(customer_id, now=None):
    now_ = db.now_ms() if now is None else now
    for p in db.promises.values():
        if p["customer_id"] != customer_id:
            continue
        if p["status"] != "ACTIVE":
            continue
        if p["coverage_start_ms"] <= now_ < p["coverage_end_ms"]:
            return True
    return False


# ---------------------------------------------------------------------------
# Serialization to API shape.
# ---------------------------------------------------------------------------
_CUSTOMER_FIELDS = [
    "name", "currency", "credit_limit_cents", "credit_status",
    "collection_stage", "exposure_cents", "total_open_balance_cents",
    "bad_debt_total_cents", "manual_hold",
]
_INVOICE_FIELDS = [
    "customer_id", "invoice_date", "due_date", "face_amount_cents",
    "balance_cents", "disputed_amount_cents", "status", "aging_bucket",
    "dunning_stage_index",
]
_PAYMENT_FIELDS = [
    "customer_id", "amount_cents", "received_at", "applied_cents",
    "unapplied_cents", "status",
]
_APPLICATION_FIELDS = [
    "payment_id", "invoice_id", "applied_cents", "short_pay_cents", "reversed",
]
_DISPUTE_FIELDS = [
    "invoice_id", "amount_cents", "reason_code", "status",
    "resolution_credit_cents", "reopen_count",
]
_PROMISE_FIELDS = [
    "customer_id", "promised_amount_cents", "coverage_start", "coverage_end",
    "status", "applied_payment_cents",
]
_WRITEOFF_FIELDS = ["invoice_id", "amount_cents", "reason_code", "approved"]
_SEQUENCE_FIELDS = ["name", "active", "steps"]
_NOTICE_FIELDS = ["invoice_id", "sequence_id", "step_index", "severity", "priority_score"]
_PAUSE_FIELDS = ["customer_id", "pause_start", "pause_end", "status"]
_STATEMENT_FIELDS = [
    "customer_id", "period_end", "opening_balance_cents", "new_charges_cents",
    "finance_charge_cents", "closing_balance_cents",
]

_COMMON = ["id", "created_at", "updated_at", "version"]
_LIGHT_COMMON = ["id", "created_at"]


def _serialize(record, fields, common):
    out = {}
    for f in common:
        out[f] = record.get(f)
    for f in fields:
        out[f] = record.get(f)
    return out


def serialize_customer(c):
    return _serialize(c, _CUSTOMER_FIELDS, _COMMON)


def serialize_invoice(iv):
    # aging_bucket is recomputed on read (due-date basis) per PRD §3.1/§3.2.
    iv["aging_bucket"] = aging_bucket(iv, "due")
    return _serialize(iv, _INVOICE_FIELDS, _COMMON)


def serialize_payment(p):
    return _serialize(p, _PAYMENT_FIELDS, _COMMON)


def serialize_application(a):
    return _serialize(a, _APPLICATION_FIELDS, _COMMON)


def serialize_dispute(d):
    return _serialize(d, _DISPUTE_FIELDS, _COMMON)


def serialize_promise(p):
    # applied_payment_cents is recomputed from in-window payments on read.
    p["applied_payment_cents"] = compute_promise_applied(p)
    return _serialize(p, _PROMISE_FIELDS, _COMMON)


def serialize_writeoff(w):
    return _serialize(w, _WRITEOFF_FIELDS, _COMMON)


def serialize_sequence(s):
    return _serialize(s, _SEQUENCE_FIELDS, _COMMON)


def serialize_notice(n):
    return _serialize(n, _NOTICE_FIELDS, _LIGHT_COMMON)


def serialize_pause(p):
    # status derived from the clock on read (PRD §3.7).
    p["status"] = pause_status(p)
    return _serialize(p, _PAUSE_FIELDS, _COMMON)


def serialize_statement(s):
    return _serialize(s, _STATEMENT_FIELDS, _COMMON)


def pause_status(p, now=None):
    now_ = db.now_ms() if now is None else now
    if now_ < p["pause_start_ms"]:
        return "SCHEDULED"
    if p["pause_start_ms"] <= now_ <= p["pause_end_ms"]:
        return "ACTIVE"
    return "EXPIRED"
