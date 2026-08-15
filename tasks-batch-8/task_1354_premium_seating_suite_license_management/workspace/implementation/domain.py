"""Domain logic: derived fields, calculations (SCAFFOLD table 1.3), serializers, cascades."""
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR

import db
import errors
from util import fmt_ts, rhu, dec, days_between

# ------------------------------------------------------------------ constants
TIER_MULTIPLIER = {"FOUNDERS": Decimal("1.60"), "PLATINUM": Decimal("1.30"),
                   "GOLD": Decimal("1.00"), "SILVER": Decimal("0.80")}
PER_GUEST_OVERAGE_CENTS = 1500
DEPOSIT_RATE = Decimal("0.30")
PLAYOFF_MULT = Decimal("1.25")
SERVICE_FEE_RATE = Decimal("0.18")
TRANSFER_FLAT_MIN_CENTS = 50000
LATE_PERIOD_RATE = Decimal("0.015")
LATE_CAP_RATE = Decimal("0.15")
LATE_MIN_FEE_CENTS = 2500
LATE_PERIOD_DAYS = 30
COVERED_EVENT_TYPES = {"REGULAR", "RIVALRY"}


# ------------------------------------------------------------------ time helpers
def now():
    return db.clock()


# ------------------------------------------------------------------ invoices: derived
def late_fee_cents(inv):
    """late_fee_accrual: recomputed on read for ISSUED / PARTIALLY_PAID invoices."""
    if inv["status"] not in ("ISSUED", "PARTIALLY_PAID"):
        return 0
    due = inv.get("due_on")
    if due is None:
        return 0
    days = days_between(due, now())
    if days < 0:
        days = 0
    periods = days // LATE_PERIOD_DAYS
    if periods == 0:
        return 0
    subtotal = inv["subtotal_cents"]
    raw = rhu(Decimal(subtotal) * LATE_PERIOD_RATE * periods)
    cap = rhu(Decimal(subtotal) * LATE_CAP_RATE)
    return max(LATE_MIN_FEE_CENTS, min(raw, cap))


def amount_due_cents(inv):
    return max(0, inv["subtotal_cents"] + late_fee_cents(inv) - inv["amount_paid_cents"])


def invoice_past_due(inv):
    """Open invoice whose due_on is strictly before the logical clock."""
    return inv["status"] in ("ISSUED", "PARTIALLY_PAID") and inv.get("due_on") is not None \
        and inv["due_on"] < now()


def invoice_days_past_due(inv):
    if inv["status"] not in ("ISSUED", "PARTIALLY_PAID") or inv.get("due_on") is None:
        return 0
    d = days_between(inv["due_on"], now())
    return d if d > 0 else 0


# ------------------------------------------------------------------ accounts: derived
def account_credit_standing(acc_id):
    """HOLD when any open invoice >= 30 days past due; WATCH when 1..29; else GOOD."""
    worst = 0
    for inv in db.all_of("invoices"):
        if inv["account_id"] != acc_id:
            continue
        d = invoice_days_past_due(inv)
        if d > worst:
            worst = d
    if worst >= 30:
        return "HOLD"
    if worst >= 1:
        return "WATCH"
    return "GOOD"


def account_balance_due(acc_id):
    return sum(amount_due_cents(i) for i in db.all_of("invoices")
               if i["account_id"] == acc_id and i["status"] in ("ISSUED", "PARTIALLY_PAID"))


def account_lifetime_spend(acc_id):
    """Sum of amount_cents over payments that ever reached CLEARED (refunds do not decrement)."""
    return sum(p["amount_cents"] for p in db.all_of("payments")
               if p["account_id"] == acc_id and p["status"] in ("CLEARED", "REFUNDED"))


# ------------------------------------------------------------------ agreements: coverage & derived
def covered_seasons(agr):
    """The term_seasons non-DRAFT seasons of the suite's venue starting at the start season,
    ordered by starts_on ASC. The start season itself always anchors the list."""
    start = db.get("seasons", agr["start_season_id"])
    suite = db.get("suites", agr["suite_id"])
    if start is None or suite is None:
        return []
    venue_seasons = [s for s in db.all_of("seasons") if s["venue_id"] == suite["venue_id"]]
    later = [s for s in venue_seasons
             if s["id"] != start["id"] and s["status"] != "DRAFT" and s["starts_on"] > start["starts_on"]]
    later.sort(key=lambda s: (s["starts_on"], s["_seq"]))
    covered = [start] + later
    return covered[:agr["term_seasons"]]


def covered_season_ids(agr):
    return [s["id"] for s in covered_seasons(agr)]


def current_season_index(agr):
    """1-based index of the covered season containing the clock; 1 before season 1 starts,
    term_seasons after the last covered season ends."""
    covered = covered_seasons(agr)
    if not covered:
        return 1
    clock = now()
    count = sum(1 for s in covered if s["starts_on"] <= clock)
    if count < 1:
        count = 1
    return min(count, agr["term_seasons"])


def agreement_f_b_accrued(agr):
    """Net F&B accrual toward the current covered season's minimum (f_b_minimum_accrual)."""
    covered = covered_seasons(agr)
    if not covered:
        return 0
    idx = current_season_index(agr) - 1
    if idx >= len(covered):
        idx = len(covered) - 1
    season_id = covered[idx]["id"]
    event_ids = {e["id"] for e in db.all_of("events") if e["season_id"] == season_id}
    total = 0
    for o in db.all_of("catering_orders"):
        if o.get("agreement_id") != agr["id"] or o["event_id"] not in event_ids:
            continue
        if o["status"] in ("CONFIRMED", "FULFILLED"):
            total += o["subtotal_cents"]
        elif o["status"] == "CANCELLED_LATE":
            total += o["cancel_fee_cents"]
    return total


def fee_schedule(base_fee, escalator_bp, term):
    """license_fee_schedule (rounded_step): each season compounds on the previous rounded fee."""
    fees = [int(base_fee)]
    factor = Decimal(10000 + int(escalator_bp)) / Decimal(10000)
    for _ in range(2, term + 1):
        fees.append(rhu(Decimal(fees[-1]) * factor))
    return fees


def covered_events_of_season(season_id, exclude_cancelled=True):
    out = []
    for e in db.all_of("events"):
        if e["season_id"] != season_id or e["event_type"] not in COVERED_EVENT_TYPES:
            continue
        if exclude_cancelled and e["status"] == "CANCELLED":
            continue
        out.append(e)
    return out


def proration_ratio(season_id, executed_on):
    """first_season_proration: remaining covered events at/after execution over total covered.
    At execute time SCHEDULED events count; at settle CANCELLED drop out of both counts
    (both call sites evaluate against live event statuses)."""
    covered = covered_events_of_season(season_id, exclude_cancelled=True)
    total = len(covered)
    if total == 0:
        return None  # caller falls back to full amount
    remaining = sum(1 for e in covered if e["starts_at"] >= executed_on)
    return Decimal(remaining) / Decimal(total)


# ------------------------------------------------------------------ waitlist: derived
def waitlist_priority_score(entry):
    acc = db.get("accounts", entry["account_id"])
    clock = now()
    waiting_periods = days_between(entry["created_at"], clock)
    if waiting_periods < 0:
        waiting_periods = 0
    waiting_periods = min(waiting_periods // 30, 10)
    lifetime = account_lifetime_spend(entry["account_id"]) if acc else 0
    spend_points = min(lifetime // 100000, 50)
    corporate = 1 if acc and acc.get("account_type") == "CORPORATE" else 0
    score = (Decimal("0.5") * waiting_periods
             + Decimal("0.3") * spend_points
             + Decimal("2.0") * corporate)
    return float(score.quantize(Decimal("0.0001"), rounding="ROUND_HALF_UP"))


# ------------------------------------------------------------------ serializers
def _pub(ent):
    return {k: v for k, v in ent.items() if not k.startswith("_")}


def _serialize(ent, dt_fields=()):
    out = {}
    for k, v in _pub(ent).items():
        if k in ("created_at", "updated_at") or k in dt_fields:
            out[k] = fmt_ts(v) if v is not None else None
        else:
            out[k] = v
    return out


def pub_venue(v):
    return _serialize(v)


def pub_suite(s):
    return _serialize(s)


def pub_season(s):
    return _serialize(s, ("starts_on", "ends_on", "renewal_window_opens_on", "renewal_window_closes_on"))


def pub_event(e):
    return _serialize(e, ("starts_at",))


def pub_account(a):
    out = _serialize(a)
    out["credit_standing"] = account_credit_standing(a["id"])
    out["balance_due_cents"] = account_balance_due(a["id"])
    out["lifetime_spend_cents"] = account_lifetime_spend(a["id"])
    return out


def pub_agreement(a):
    out = _serialize(a, ("executed_on",))
    out["current_season_index"] = current_season_index(a)
    out["f_b_accrued_cents_current_season"] = agreement_f_b_accrued(a)
    return out


def pub_invoice(i):
    out = _serialize(i, ("due_on", "issued_at"))
    lf = late_fee_cents(i)
    out["late_fee_cents"] = lf
    out["amount_due_cents"] = max(0, i["subtotal_cents"] + lf - i["amount_paid_cents"])
    return out


def pub_payment(p):
    return _serialize(p)


def pub_catering(o):
    return _serialize(o)


def pub_credential(c):
    return _serialize(c)


def pub_rental(r):
    return _serialize(r, ("hold_expires_at",))


def pub_transfer(t):
    return _serialize(t)


def pub_renewal(r):
    return _serialize(r, ("response_due_on",))


def pub_waitlist(w):
    out = _serialize(w)
    out["priority_score"] = waitlist_priority_score(w)
    return out


def pub_assessment(a):
    return _serialize(a, ("levied_at",))


# ------------------------------------------------------------------ shared predicates
def catering_effective_cutoff_hours(event):
    if event.get("catering_cutoff_hours") is not None:
        return event["catering_cutoff_hours"]
    season = db.get("seasons", event["season_id"])
    venue = db.get("venues", season["venue_id"]) if season else None
    return venue.get("default_catering_cutoff_hours", 72) if venue else 72


def catering_cutoff_instant(event):
    return event["starts_at"] - timedelta(hours=catering_effective_cutoff_hours(event))


def agreement_covers_season(agr, season_id):
    return season_id in covered_season_ids(agr)


def event_license_covered(event, agr):
    """Agreement-context catering/credentials require a license-covered event:
    REGULAR/RIVALRY type and the event's season among the agreement's covered seasons."""
    if event["event_type"] not in COVERED_EVENT_TYPES:
        return False
    return agreement_covers_season(agr, event["season_id"])


def rental_availability_ok(suite, event, exclude_rental_id=None):
    """Rule set-membership check: no HELD/CONFIRMED rental on same (suite, event);
    REGULAR/RIVALRY additionally blocked by an agreement in ACTIVE/SUSPENDED/EXPIRING
    covering the event's season; suite must not be OUT_OF_SERVICE."""
    if suite["status"] == "OUT_OF_SERVICE":
        return False
    for r in db.all_of("rentals"):
        if r["id"] == exclude_rental_id:
            continue
        if r["suite_id"] == suite["id"] and r["event_id"] == event["id"] \
                and r["status"] in ("HELD", "CONFIRMED"):
            return False
    if event["event_type"] in COVERED_EVENT_TYPES:
        for a in db.all_of("agreements"):
            if a["suite_id"] == suite["id"] and a["status"] in ("ACTIVE", "SUSPENDED", "EXPIRING") \
                    and agreement_covers_season(a, event["season_id"]):
                return False
    return True


# ------------------------------------------------------------------ invoice factory
def create_auto_invoice(account_id, invoice_type, amount_cents, description, due_on,
                        agreement_id=None, rental_id=None, assessment_id=None, season_id=None):
    """Auto-created invoices enter ISSUED directly at creation."""
    inv = db.new_entity({
        "account_id": account_id,
        "agreement_id": agreement_id,
        "rental_id": rental_id,
        "assessment_id": assessment_id,
        "season_id": season_id,
        "invoice_type": invoice_type,
        "lines": [{"description": description, "quantity": 1, "unit_price_cents": int(amount_cents)}],
        "subtotal_cents": int(amount_cents),
        "amount_paid_cents": 0,
        "due_on": due_on,
        "issued_at": now(),
        "status": "ISSUED",
    })
    db.insert("invoices", inv)
    acc = db.get("accounts", account_id)
    if acc is not None:
        db.touch(acc)  # balance recompute bumps account version (PRD 2.9)
    return inv


# ------------------------------------------------------------------ account cascades
def suspend_account(acc, reason):
    """Account -> SUSPENDED; cascades ACTIVE/EXPIRING agreements to SUSPENDED."""
    acc["status"] = "SUSPENDED"
    db.touch(acc)
    suspended_agreements = []
    for agr in db.all_of("agreements"):
        if agr["account_id"] == acc["id"] and agr["status"] in ("ACTIVE", "EXPIRING"):
            agr["status"] = "SUSPENDED"
            agr["suspension_reason"] = reason
            agr["suspension_count"] = int(agr.get("suspension_count", 0)) + 1
            db.touch(agr)
            suspended_agreements.append(agr["id"])
    return suspended_agreements


def reinstate_account(acc):
    """Account -> ACTIVE; auto-cures ACCOUNT_DEFAULT-suspended agreements only."""
    acc["status"] = "ACTIVE"
    db.touch(acc)
    for agr in db.all_of("agreements"):
        if agr["account_id"] == acc["id"] and agr["status"] == "SUSPENDED" \
                and agr.get("suspension_reason") == "ACCOUNT_DEFAULT":
            agr["status"] = "ACTIVE"
            agr["suspension_reason"] = None
            db.touch(agr)


def release_suite(agr):
    """Agreement ended: suite -> AVAILABLE, current_agreement_id cleared."""
    suite = db.get("suites", agr["suite_id"])
    if suite is not None and suite.get("current_agreement_id") == agr["id"]:
        suite["status"] = "AVAILABLE"
        suite["current_agreement_id"] = None
        db.touch(suite)


# ------------------------------------------------------------------ assessment settlement
def maybe_settle_assessment(invoice):
    """LEVIED -> SETTLED once every spawned ASSESSMENT invoice is PAID or VOID."""
    aid = invoice.get("assessment_id")
    if not aid:
        return
    assessment = db.get("assessments", aid)
    if assessment is None or assessment["status"] != "LEVIED":
        return
    spawned = [i for i in db.all_of("invoices")
               if i.get("assessment_id") == aid and i["invoice_type"] == "ASSESSMENT"]
    if spawned and all(i["status"] in ("PAID", "VOID") for i in spawned):
        assessment["status"] = "SETTLED"
        db.touch(assessment)


# ------------------------------------------------------------------ payment cascades
def payment_clear(payment):
    clock = now()
    for alloc in payment["allocations"]:
        inv = db.get("invoices", alloc["invoice_id"])
        if inv is None:
            continue
        inv["amount_paid_cents"] += alloc["amount_cents"]
        total_now = inv["subtotal_cents"] + late_fee_cents(inv)
        inv["status"] = "PAID" if inv["amount_paid_cents"] >= total_now else "PARTIALLY_PAID"
        db.touch(inv)
        maybe_settle_assessment(inv)
    acc = db.get("accounts", payment["account_id"])
    if acc is not None:
        db.touch(acc)  # balance down + lifetime up
        # link 3: auto-reinstate when balance is zero and nothing is past due
        if acc["status"] == "SUSPENDED" and account_balance_due(acc["id"]) == 0:
            past_due = any(invoice_past_due(i) for i in db.all_of("invoices")
                           if i["account_id"] == acc["id"])
            if not past_due:
                reinstate_account(acc)  # link 4: auto-cure ACCOUNT_DEFAULT agreements


def payment_refund(payment):
    for alloc in payment["allocations"]:
        inv = db.get("invoices", alloc["invoice_id"])
        if inv is None:
            continue
        inv["amount_paid_cents"] -= alloc["amount_cents"]
        if inv["amount_paid_cents"] < 0:
            inv["amount_paid_cents"] = 0
        if inv["status"] in ("PAID", "PARTIALLY_PAID"):
            if inv["amount_paid_cents"] == 0:
                inv["status"] = "ISSUED"
            else:
                total_now = inv["subtotal_cents"] + late_fee_cents(inv)
                inv["status"] = "PAID" if inv["amount_paid_cents"] >= total_now else "PARTIALLY_PAID"
        db.touch(inv)
    acc = db.get("accounts", payment["account_id"])
    if acc is not None:
        db.touch(acc)  # balance recomputes upward by exactly amount_cents
