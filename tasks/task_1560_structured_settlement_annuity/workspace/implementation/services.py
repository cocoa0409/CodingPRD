"""Business logic: calculations, ledger recomputation, cascades, clock sweep."""

from decimal import Decimal, ROUND_HALF_UP, getcontext

from db import DB, CLOCK, parse_date, add_years

getcontext().prec = 50

OUTSTANDING_STATUSES = {"SCHEDULED", "PAYABLE", "ISSUED", "RETURNED", "STALE_DATED", "ESCHEATABLE"}


# ---------------------------------------------------------------------------
# Serialization (strip internal fields)
# ---------------------------------------------------------------------------

def pub(entity):
    if entity is None:
        return None
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def sort_key(e):
    return (e["created_at"], e["_seq"])


def list_view(items, limit, offset):
    items = sorted(items, key=sort_key)
    total = len(items)
    page = items[offset:offset + limit]
    return [pub(i) for i in page], total


# ---------------------------------------------------------------------------
# Profile / payee helpers
# ---------------------------------------------------------------------------

def find_profile_by_state(state_code):
    for p in DB.state_statute_profiles.values():
        if p["state_code"] == state_code:
            return p
    return None


def payee_age_years(payee, on_date):
    dob = parse_date(payee["date_of_birth"])
    age = on_date.year - dob.year
    if (on_date.month, on_date.day) < (dob.month, dob.day):
        age -= 1
    return age


def compute_is_minor(payee):
    profile = find_profile_by_state(payee["address_state_code"])
    if profile is None:
        return False
    return payee_age_years(payee, CLOCK.today()) < profile["age_of_majority"]


def majority_birthday(payee):
    profile = find_profile_by_state(payee["address_state_code"])
    if profile is None:
        return None
    return add_years(parse_date(payee["date_of_birth"]), profile["age_of_majority"])


def active_guardianship(payee_id):
    for g in DB.guardianship_cases.values():
        if g["payee_id"] == payee_id and g["status"] == "ACTIVE":
            return g
    return None


# ---------------------------------------------------------------------------
# Agreement ledger
# ---------------------------------------------------------------------------

def active_schedule_for(agreement_id):
    for s in DB.payment_schedules.values():
        if s["settlement_agreement_id"] == agreement_id and s["status"] == "ACTIVE":
            return s
    return None


def recompute_agreement_totals(agreement, bump=True):
    """Recompute total_scheduled_cents / outstanding_liability_cents from the
    ACTIVE schedule's payment set. paid/escheated/transferred/commuted totals
    are maintained incrementally by callers."""
    sched = active_schedule_for(agreement["id"])
    total_sched = 0
    outstanding = 0
    if sched is not None:
        for p in DB.scheduled_payments.values():
            if p["payment_schedule_id"] == sched["id"]:
                total_sched += p["amount_cents"]
                if p["status"] in OUTSTANDING_STATUSES:
                    outstanding += p["amount_cents"]
    agreement["total_scheduled_cents"] = total_sched
    agreement["outstanding_liability_cents"] = outstanding
    if bump:
        from db import touch
        touch(agreement)


def policy_for_agreement(agreement_id):
    for pol in DB.annuity_policies.values():
        if pol["settlement_agreement_id"] == agreement_id:
            return pol
    return None


def non_terminal_payment_count(agreement_id):
    """Count payments on the agreement's ACTIVE schedule in non-terminal statuses."""
    sched = active_schedule_for(agreement_id)
    if sched is None:
        return 0
    n = 0
    for p in DB.scheduled_payments.values():
        if p["payment_schedule_id"] == sched["id"] and p["status"] in OUTSTANDING_STATUSES:
            n += 1
    return n


def exhaustion_check(agreement):
    """If no non-terminal payments remain on the ACTIVE schedule, the policy
    becomes EXHAUSTED (unless already terminal / FULLY_COMMUTED) and the
    agreement follows to CLOSED. The canonical arrow is ACTIVE -> CLOSED;
    FUNDED is included so a stream drained before its first maturation still
    closes (PRD §3.6: 'a transfer covering every remaining payment leaves the
    policy EXHAUSTED and the agreement CLOSED')."""
    from db import touch
    if non_terminal_payment_count(agreement["id"]) != 0:
        return
    policy = policy_for_agreement(agreement["id"])
    if policy is not None and policy["status"] in ("IN_FORCE", "PARTIALLY_COMMUTED"):
        policy["status"] = "EXHAUSTED"
        touch(policy)
        if agreement["status"] in ("FUNDED", "ACTIVE"):
            agreement["status"] = "CLOSED"
            touch(agreement)


# ---------------------------------------------------------------------------
# Escalation calculation (pinned rounding)
# ---------------------------------------------------------------------------

def escalation_exponent(anchor_date_str, due_date_str):
    """n = count of anniversaries of anchor that are <= due_date."""
    anchor = parse_date(anchor_date_str)
    due = parse_date(due_date_str)
    n = 0
    while True:
        ann = add_years(anchor, n + 1)
        if ann <= due:
            n += 1
        else:
            break
    return n


def escalated_amounts(base_amount_cents, escalation_rate_bps, n):
    """Returns (amount_cents carry_rounded, disclosure_amount_cents end_rounded)."""
    if n <= 0 or escalation_rate_bps == 0:
        return base_amount_cents, base_amount_cents
    factor = Decimal(1) + (Decimal(escalation_rate_bps) / Decimal(10000))
    # carry-rounded
    a = Decimal(base_amount_cents)
    for _ in range(n):
        a = (a * factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    carry = int(a)
    # end-rounded
    end = (Decimal(base_amount_cents) * (factor ** n)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return carry, int(end)


# ---------------------------------------------------------------------------
# Discounting helpers (ACT/365)
# ---------------------------------------------------------------------------

def t_years(from_date, to_date):
    return Decimal((to_date - from_date).days) / Decimal(365)


def pv_per_payment_then_sum(payments, rate_bps, valuation_date):
    """payments: list of (amount_cents, due_date). Each pv rounded half up to
    cents first, then summed."""
    rate = Decimal(rate_bps) / Decimal(10000)
    total = 0
    for amount, due in payments:
        t = t_years(valuation_date, due)
        pv = (Decimal(amount) / ((Decimal(1) + rate) ** t)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        total += int(pv)
    return total


def disclosed_discount_rate_bps(nominal, purchase_price_cents, wavg_years):
    """round_half_up(10000 * (nominal - price) / nominal / wavg_years)."""
    if nominal == 0 or wavg_years == 0:
        return 0
    val = (Decimal(10000)
           * (Decimal(nominal) - Decimal(purchase_price_cents))
           / Decimal(nominal)
           / Decimal(str(wavg_years)))
    return int(val.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def solve_irr_bps(payments, price, valuation_date):
    """Find r > 0 (as far as it exists) solving price = sum(amount/(1+r)^t).
    Returns round_half_up(10000*r). Bisection on r in (-0.9999, 10]."""
    # f(r) = sum(amount_i / (1+r)^t_i); decreasing in r. Want f(r) = price.
    def f(r):
        total = Decimal(0)
        base = Decimal(1) + r
        for amount, due in payments:
            t = t_years(valuation_date, due)
            total += Decimal(amount) / (base ** t)
        return total

    lo = Decimal("-0.999999")
    hi = Decimal("10")
    # If even at lo the PV is below price, rate is extremely negative;
    # price > nominal cannot happen here (guarded), so f(lo) huge.
    flo = f(lo)
    fhi = f(hi)
    target = Decimal(price)
    if fhi > target:
        r = hi
    elif flo < target:
        r = lo
    else:
        for _ in range(200):
            mid = (lo + hi) / 2
            fm = f(mid)
            if fm > target:
                lo = mid
            else:
                hi = mid
        r = (lo + hi) / 2
    return int((Decimal(10000) * r).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
