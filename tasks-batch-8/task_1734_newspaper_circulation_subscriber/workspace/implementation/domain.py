"""Business logic: effective rate, subscriber ledger, payment waterfall, lapse
cycle, vacation-hold proration, save-offer choreography, carrier settlement,
audit totals, and the pinned seven-step nightly batch."""
from datetime import timedelta
from decimal import Decimal

import clock
from db import bump, by_created, create_rec, store
from errors import ApiError
from util import D, days, rhu

# --- Calculation constants (scaffold Table 3) ---
TERMS_DAYS = 14
GRACE_DAYS = 7
SUSPEND_DAYS = 21
LAPSE_DAYS = 45
DAYS_PER_WEEK = 7
MONTHLY_GOODWILL_CAP_CENTS = 5000
COMPLAINT_CREDIT_CAP_CENTS = 2000
ANNUAL_HOLD_BUDGET_DAYS = 30
VARIANCE_TOLERANCE = 2
BONUS_PCT = Decimal("0.05")
BONUS_MAX_COMPLAINTS = 2
PER_COMPLAINT_DEDUCTION_CENTS = 150
DEDUCTION_CAP_CENTS = 3000

# Billing-axis sets.
ACTIVE_SET = ("ACTIVE", "GRACE")  # holds / assignments / complaints / cancel
NON_TERMINAL = ("PENDING_START", "ACTIVE", "GRACE", "SUSPENDED", "CANCEL_PENDING")
CHARGE_OPEN_SET = ("OPEN", "PARTIALLY_PAID")
PRINT_CAPABLE = ("PRINT", "BUNDLE")


def today():
    return clock.now_dt().date()


# ---------------------------------------------------------------------------
# Fetch helpers (existence -> ERR_NOT_FOUND, validated left-to-right by caller)
# ---------------------------------------------------------------------------

def fetch(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
    return rec


def plan_of(sub):
    return store.plans.get(sub["plan_id"])


def subscriber_of(sub):
    return store.subscribers.get(sub["subscriber_id"])


def print_capable(plan):
    return plan is not None and plan["plan_type"] in PRINT_CAPABLE


def subscriptions_of(subscriber_id):
    return [s for s in by_created(store.subscriptions.values())
            if s["subscriber_id"] == subscriber_id]


# ---------------------------------------------------------------------------
# effective_weekly_rate (stepped tenure pricing + save discount floor)
# ---------------------------------------------------------------------------

def effective_weekly_rate(sub, plan, period_start):
    d = (period_start - sub["start_date"]).days
    tenure_weeks = (d // DAYS_PER_WEEK) if d >= 0 else 0
    stepped = plan["base_weekly_rate_cents"]
    for step in sorted(plan["step_up_schedule"], key=lambda s: s["after_weeks"]):
        if tenure_weeks >= step["after_weeks"]:  # inclusive boundary
            stepped = step["weekly_rate_cents"]
    rate = stepped
    until = sub["save_discount_until"]
    if until is not None and period_start < until:
        discounted = rhu(Decimal(stepped) * (Decimal(1) - D(sub["save_discount_pct"])))
        rate = max(discounted, plan["min_weekly_rate_cents"])
    return rate


# ---------------------------------------------------------------------------
# Subscriber ledger (PRD 2.6)
# ---------------------------------------------------------------------------

def charge_outstanding(ch):
    return ch["amount_cents"] - ch["paid_amount_cents"] - ch["credit_applied_cents"]


def charge_status_for(covered, amount):
    if covered <= 0:
        return "OPEN"
    if covered >= amount:
        return "PAID"
    return "PARTIALLY_PAID"


def settle_subscriber(subr, unapplied_delta=0):
    """Recompute balance_due_cents (and apply an unapplied-cash delta) with one
    version bump when anything actually changed."""
    old = (subr["balance_due_cents"], subr["unapplied_cash_cents"])
    if unapplied_delta:
        subr["unapplied_cash_cents"] += unapplied_delta
    total = 0
    for ch in store.charges.values():
        if ch["subscriber_id"] == subr["id"] and ch["status"] in (
                "OPEN", "PARTIALLY_PAID", "PAID"):
            total += charge_outstanding(ch)
    subr["balance_due_cents"] = total - subr["unapplied_cash_cents"]
    if (subr["balance_due_cents"], subr["unapplied_cash_cents"]) != old:
        bump(subr)


def waterfall(subscriber_id, funds_cents, kind):
    """Oldest-due-first allocation: due_date ASC, tie-break created_at ASC
    (never id). kind 'payment' credits paid_amount_cents; 'credit' credits
    credit_applied_cents. Returns (allocations [(charge, amt)], remaining)."""
    eligible = [ch for ch in store.charges.values()
                if ch["subscriber_id"] == subscriber_id
                and ch["status"] in CHARGE_OPEN_SET
                and charge_outstanding(ch) > 0]
    eligible.sort(key=lambda ch: (ch["due_date"], ch["created_dt"], ch["_ord"]))
    allocations = []
    remaining = funds_cents
    for ch in eligible:
        if remaining <= 0:
            break
        take = min(remaining, charge_outstanding(ch))
        if take <= 0:
            continue
        if kind == "payment":
            ch["paid_amount_cents"] += take
        else:
            ch["credit_applied_cents"] += take
        covered = ch["paid_amount_cents"] + ch["credit_applied_cents"]
        new_status = charge_status_for(covered, ch["amount_cents"])
        ch["status"] = new_status
        bump(ch)
        allocations.append((ch, take))
        remaining -= take
    return allocations, remaining


def auto_apply_credit(memo):
    """Credit memo auto-apply at issuance; leftover stays on the memo
    (ISSUED). Fully consumed -> APPLIED. Part of issuance: no memo bump."""
    _allocs, remaining = waterfall(memo["subscriber_id"], memo["amount_cents"], "credit")
    memo["applied_cents"] = memo["amount_cents"] - remaining
    if remaining == 0:
        memo["status"] = "APPLIED"
    subr = store.subscribers[memo["subscriber_id"]]
    settle_subscriber(subr)
    reevaluate_billing(subr["id"])


# ---------------------------------------------------------------------------
# Lapse cycle (threshold re-evaluation; strictly-greater boundaries)
# ---------------------------------------------------------------------------

def days_past_due(subscriber_id):
    t = today()
    worst = 0
    for ch in store.charges.values():
        if ch["subscriber_id"] == subscriber_id and ch["status"] in CHARGE_OPEN_SET:
            d = (t - ch["due_date"]).days
            if d > worst:
                worst = d
    return worst


def lapse_target(d):
    if d <= GRACE_DAYS:
        return "ACTIVE"      # exactly 7 days past due stays ACTIVE
    if d <= SUSPEND_DAYS:
        return "GRACE"
    if d <= LAPSE_DAYS:
        return "SUSPENDED"
    return "LAPSED"


def transition_billing(sub, target):
    """System re-evaluation move on the billing axis, with the side effects the
    state machine pins for each landing state."""
    cur = sub["billing_status"]
    if cur == target:
        return
    plan = plan_of(sub)
    sub["billing_status"] = target
    if target == "SUSPENDED":
        if sub["delivery_status"] in ("DELIVERING", "HELD"):
            sub["delivery_status"] = "NOT_DELIVERED"
        # charge generation stops while SUSPENDED (cycle step 4 filter)
    elif target == "ACTIVE":
        if cur == "SUSPENDED":
            sub["next_charge_date"] = today()  # reinstatement reset
        if sub["delivery_status"] == "NOT_DELIVERED" and print_capable(plan):
            sub["delivery_status"] = "DELIVERING"
    elif target == "LAPSED":
        for ch in store.charges.values():
            if ch["subscription_id"] == sub["id"] and ch["status"] in CHARGE_OPEN_SET:
                ch["status"] = "WRITTEN_OFF"
                bump(ch)
        sub["delivery_status"] = "NOT_DELIVERED"
        sub["ended_at"] = today()
    bump(sub)
    if target == "LAPSED":
        subr = subscriber_of(sub)
        settle_subscriber(subr)
        bubble_up(subr)


def reevaluate_billing(subscriber_id):
    """Compute the oldest-unpaid past-due age over the subscriber's charges and
    drive every non-terminal, non-pending subscription to its threshold state.
    Returns the number of billing-axis transitions made."""
    target = lapse_target(days_past_due(subscriber_id))
    changes = 0
    for sub in subscriptions_of(subscriber_id):
        if sub["billing_status"] in ("ACTIVE", "GRACE", "SUSPENDED"):
            if sub["billing_status"] != target:
                transition_billing(sub, target)
                changes += 1
    return changes


def bubble_up(subr):
    """Subscriber ACTIVE -> LAPSED when it has >= 1 subscription and every
    subscription is in a terminal billing state."""
    if subr["status"] != "ACTIVE":
        return
    subs = subscriptions_of(subr["id"])
    if subs and all(s["billing_status"] in ("CANCELLED", "LAPSED") for s in subs):
        subr["status"] = "LAPSED"
        bump(subr)


def cancel_terminal(sub):
    """Shared churn side effects for a subscription reaching CANCELLED."""
    sub["billing_status"] = "CANCELLED"
    sub["delivery_status"] = "NOT_DELIVERED"
    sub["ended_at"] = today()
    bump(sub)
    bubble_up(subscriber_of(sub))


# ---------------------------------------------------------------------------
# BillingCharge generation (weekly catch-up)
# ---------------------------------------------------------------------------

def _make_charge(sub):
    """Generate one weekly charge at next_charge_date and advance it by 7 days.
    Does not bump the subscription; the caller owns that mutation's version."""
    plan = plan_of(sub)
    ps = sub["next_charge_date"]
    ch = create_rec(store.charges, {
        "subscription_id": sub["id"],
        "subscriber_id": sub["subscriber_id"],
        "period_start": ps,
        "period_end": ps + days(DAYS_PER_WEEK),
        "due_date": ps + days(TERMS_DAYS),
        "amount_cents": effective_weekly_rate(sub, plan, ps),
        "paid_amount_cents": 0,
        "credit_applied_cents": 0,
        "status": "OPEN",
    })
    sub["next_charge_date"] = ps + days(DAYS_PER_WEEK)
    return ch


# ---------------------------------------------------------------------------
# Vacation holds
# ---------------------------------------------------------------------------

def hold_length(h):
    return (h["end_date"] - h["start_date"]).days


def activate_hold(hold):
    sub = store.subscriptions[hold["subscription_id"]]
    plan = plan_of(sub)
    hold["status"] = "ACTIVE"
    hold["weekly_rate_snapshot_cents"] = effective_weekly_rate(sub, plan, today())
    if sub["delivery_status"] == "DELIVERING":
        sub["delivery_status"] = "HELD"
        bump(sub)
    bump(hold)


def complete_hold(hold, actual_end):
    """Completion (natural end or early resume). Proration credit uses the
    snapshot rate over the actual held span [start_date, actual_end)."""
    sub = store.subscriptions[hold["subscription_id"]]
    plan = plan_of(sub)
    hold["status"] = "COMPLETED"
    hold["end_date"] = actual_end
    if sub["delivery_status"] == "HELD":
        sub["delivery_status"] = "DELIVERING"
        bump(sub)
    if hold["resolution"] == "CREDIT":
        held_days = (actual_end - hold["start_date"]).days
        base = hold["weekly_rate_snapshot_cents"]
        if base is None:
            base = effective_weekly_rate(sub, plan, hold["start_date"])
        if plan["proration_method"] == "PER_ISSUE":
            # Rounding order pinned: per-issue rate rounded FIRST, then multiplied.
            per_issue = rhu(Decimal(base) / Decimal(plan["issues_per_week"]))
            credit = per_issue * held_days
        else:  # PER_DAY: single rounding after the multiply
            credit = rhu(Decimal(base) * Decimal(held_days) / Decimal(DAYS_PER_WEEK))
        hold["credit_amount_cents"] = credit
        memo = create_rec(store.credit_memos, {
            "subscriber_id": sub["subscriber_id"],
            "source": "PRORATION",
            "complaint_id": None,
            "hold_id": hold["id"],
            "amount_cents": credit,
            "applied_cents": 0,
            "reason": "Vacation hold proration credit",
            "status": "ISSUED",
        })
        auto_apply_credit(memo)
    bump(hold)


def annual_hold_days_used(subscription_id, year):
    total = 0
    for h in store.holds.values():
        if h["subscription_id"] != subscription_id:
            continue
        if h["status"] not in ("SCHEDULED", "ACTIVE", "COMPLETED"):
            continue
        if h["start_date"].year == year:
            total += hold_length(h)
    return total


# ---------------------------------------------------------------------------
# Save offers
# ---------------------------------------------------------------------------

def expire_offer(offer, churn):
    """EXPIRED flip. Cycle expiry churns a CANCEL_PENDING subscription;
    supersede expiry leaves billing untouched (churn=False there)."""
    offer["status"] = "EXPIRED"
    bump(offer)
    if churn:
        sub = store.subscriptions[offer["subscription_id"]]
        if sub["billing_status"] == "CANCEL_PENDING":
            cancel_terminal(sub)


# ---------------------------------------------------------------------------
# Complaints
# ---------------------------------------------------------------------------

def resolve_route_id(sub, service_date):
    """Route assignment covering service_date (closed interval); ACTIVE
    preferred, ENDED as fallback, null when none."""
    fallback = None
    for a in by_created(store.assignments.values()):
        if a["subscription_id"] != sub["id"]:
            continue
        if a["start_date"] > service_date:
            continue
        if a["end_date"] is not None and service_date > a["end_date"]:
            continue
        if a["status"] == "ACTIVE":
            return a["route_id"]
        if fallback is None:
            fallback = a["route_id"]
    return fallback


def monthly_goodwill_used(subscriber_id):
    """Current-calendar-month total of non-VOIDED GOODWILL/COMPLAINT memos."""
    t = today()
    total = 0
    for m in store.credit_memos.values():
        if m["subscriber_id"] != subscriber_id:
            continue
        if m["source"] not in ("GOODWILL", "COMPLAINT"):
            continue
        if m["status"] == "VOIDED":
            continue
        cd = m["created_dt"].date()
        if cd.year == t.year and cd.month == t.month:
            total += m["amount_cents"]
    return total


# ---------------------------------------------------------------------------
# Carrier settlement (computed read over the week [week_start, week_start+7))
# ---------------------------------------------------------------------------

def _held_days_between(sub, lo, hi_excl):
    """Held days inside the half-open day range [lo, hi_excl) (holds are
    half-open too)."""
    total = 0
    for h in store.holds.values():
        if h["subscription_id"] != sub["id"] or h["status"] == "CANCELLED":
            continue
        s = max(h["start_date"], lo)
        e = min(h["end_date"], hi_excl)
        if s < e:
            total += (e - s).days
    return total


def carrier_settlement(carrier, week_start):
    week_end = week_start + days(DAYS_PER_WEEK)
    routes = [r for r in store.routes.values() if r["carrier_id"] == carrier["id"]]
    active_route_ids = {r["id"] for r in routes if r["status"] == "ACTIVE"}
    all_route_ids = {r["id"] for r in routes}
    delivered = 0
    for asg in store.assignments.values():
        if asg["route_id"] not in active_route_ids:
            continue
        # Intersection filter: closed assignment interval vs the half-open
        # week [week_start, week_end).
        if asg["start_date"] >= week_end:
            continue
        if asg["end_date"] is not None and asg["end_date"] < week_start:
            continue
        sub = store.subscriptions.get(asg["subscription_id"])
        if sub is None:
            continue
        if not print_capable(plan_of(sub)):
            continue
        if sub["billing_status"] not in ("ACTIVE", "GRACE", "CANCEL_PENDING"):
            continue
        # Delivery-day count: overlap measured as max(start) .. min(end, week
        # end) with the end bound exclusive (open-ended assignment -> week end).
        lo = max(asg["start_date"], week_start)
        hi_excl = week_end if asg["end_date"] is None else min(asg["end_date"], week_end)
        overlap_days = max(0, (hi_excl - lo).days)
        delivered += max(0, overlap_days - _held_days_between(sub, lo, hi_excl))
    complaint_count = sum(
        1 for c in store.complaints.values()
        if c["route_id"] in all_route_ids
        and week_start <= c["service_date"] < week_end)
    gross = delivered * carrier["per_copy_rate_cents"]
    bonus = rhu(Decimal(gross) * BONUS_PCT) if complaint_count <= BONUS_MAX_COMPLAINTS else 0
    deduction = (min(complaint_count * PER_COMPLAINT_DEDUCTION_CENTS, DEDUCTION_CAP_CENTS)
                 if carrier["compensation_model"] == "PER_COPY_NET_OF_COMPLAINTS" else 0)
    net = max(gross + bonus - deduction, 0)
    return {
        "week_start_date": week_start.isoformat(),
        "compensation_model": carrier["compensation_model"],
        "delivered_copies": delivered,
        "complaint_count": complaint_count,
        "gross_cents": gross,
        "bonus_cents": bonus,
        "deduction_cents": deduction,
        "net_cents": net,
    }


# ---------------------------------------------------------------------------
# Audit bureau totals
# ---------------------------------------------------------------------------

def audit_totals(period_start, period_end):
    paid_print = 0
    paid_digital = 0
    for sub in store.subscriptions.values():
        if sub["billing_status"] not in ("ACTIVE", "GRACE", "CANCEL_PENDING"):
            continue
        if sub["start_date"] > period_end:
            continue
        if sub["ended_at"] is not None and sub["ended_at"] < period_start:
            continue
        pt = plan_of(sub)["plan_type"]
        if pt in ("PRINT", "BUNDLE"):
            paid_print += 1
        if pt in ("DIGITAL", "BUNDLE"):
            paid_digital += 1
    single_copy = 0
    for r in store.rack_reports.values():
        if r["status"] == "RECONCILED" and period_start <= r["week_start_date"] <= period_end:
            single_copy += r["copies_delivered"] - r["copies_returned"]
    return paid_print, paid_digital, single_copy


# ---------------------------------------------------------------------------
# Nightly batch — seven steps in pinned order (PRD 2.5)
# ---------------------------------------------------------------------------

def run_daily_cycle():
    t = today()
    counts = {
        "activated_subscriptions": 0,
        "holds_activated": 0,
        "holds_completed": 0,
        "charges_generated": 0,
        "offers_expired": 0,
        "status_changes": 0,
        "plan_changes_applied": 0,
    }

    # (1) Activate PENDING_START subscriptions whose start_date has arrived;
    #     first weekly charge generates immediately.
    for sub in by_created(store.subscriptions.values()):
        if sub["billing_status"] == "PENDING_START" and sub["start_date"] <= t:
            plan = plan_of(sub)
            sub["billing_status"] = "ACTIVE"
            sub["next_charge_date"] = sub["start_date"]
            if sub["delivery_status"] == "NOT_DELIVERED" and print_capable(plan):
                sub["delivery_status"] = "DELIVERING"
            _make_charge(sub)
            bump(sub)
            settle_subscriber(subscriber_of(sub))
            counts["activated_subscriptions"] += 1
            counts["charges_generated"] += 1

    # (2) Activate SCHEDULED holds whose start has arrived.
    for hold in by_created(store.holds.values()):
        if hold["status"] == "SCHEDULED" and hold["start_date"] <= t:
            activate_hold(hold)
            counts["holds_activated"] += 1

    # (3) Complete ACTIVE holds whose end has arrived (proration credits).
    for hold in by_created(store.holds.values()):
        if hold["status"] == "ACTIVE" and hold["end_date"] <= t:
            complete_hold(hold, hold["end_date"])
            counts["holds_completed"] += 1

    # (4) Weekly charge catch-up for ACTIVE / GRACE / CANCEL_PENDING.
    for sub in by_created(store.subscriptions.values()):
        if sub["billing_status"] in ("ACTIVE", "GRACE", "CANCEL_PENDING") \
                and sub["next_charge_date"] is not None:
            n = 0
            while sub["next_charge_date"] <= t:
                _make_charge(sub)
                n += 1
            if n:
                bump(sub)
                settle_subscriber(subscriber_of(sub))
            counts["charges_generated"] += n

    # (5) Expire OFFERED save offers past expires_at; CANCEL_PENDING churns.
    for offer in by_created(store.save_offers.values()):
        if offer["status"] == "OFFERED" and offer["expires_at"] <= t:
            expire_offer(offer, churn=True)
            counts["offers_expired"] += 1

    # (6) Lapse-cycle evaluation across all non-terminal subscriptions.
    for subr in by_created(store.subscribers.values()):
        counts["status_changes"] += reevaluate_billing(subr["id"])

    # (7) Apply pending plan changes whose effective_date has arrived.
    for sub in by_created(store.subscriptions.values()):
        if sub["pending_plan_id"] is not None \
                and sub["pending_plan_effective_date"] is not None \
                and sub["pending_plan_effective_date"] <= t:
            sub["plan_id"] = sub["pending_plan_id"]
            sub["pending_plan_id"] = None
            sub["pending_plan_effective_date"] = None
            bump(sub)
            counts["plan_changes_applied"] += 1

    return counts
