"""Business logic: allocations, amortization, penalties, accrual, waterfall, cascades."""
from datetime import timedelta, timezone, datetime
from decimal import Decimal, ROUND_HALF_UP, localcontext

import errors
from serializers import eligible_parcels, parcel_frontage
from store import STORE, new_id, now, touch

CENT = Decimal("1")
RATE_Q = Decimal("0.0001")
PCT_Q = Decimal("0.01")


def rhu(value, quantum=CENT):
    """Round half up to the given Decimal quantum; returns Decimal."""
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, CENT))


# ---------------------------------------------------------------------------
# preliminary_assessment_allocation / final_levy_allocation (§3.3, §3.7)
# ---------------------------------------------------------------------------

def allocate_amounts(total_cents, parcels, methodology):
    """Pinned allocation: FRONT_FOOT 4dp rate or PER_PARCEL share, then the
    penny-remainder walk in (frontage DESC, created_at ASC) order.
    Returns {parcel_id: amount_cents} summing exactly to total_cents."""
    if not parcels:
        return {}
    amounts = {}
    if methodology == "FRONT_FOOT":
        sum_frontage = sum((parcel_frontage(p) for p in parcels), Decimal("0"))
        with localcontext() as ctx:
            ctx.prec = 50
            rate = rhu(Decimal(total_cents) / sum_frontage, RATE_Q)
            for p in parcels:
                raw = parcel_frontage(p) * rate
                amounts[p["id"]] = rhu_int(raw)
    else:  # PER_PARCEL
        with localcontext() as ctx:
            ctx.prec = 50
            share = rhu_int(Decimal(total_cents) / Decimal(len(parcels)))
        for p in parcels:
            amounts[p["id"]] = share
    diff = total_cents - sum(amounts.values())
    if diff:
        order = sorted(parcels,
                       key=lambda p: (-parcel_frontage(p), p["created_at"],
                                      p.get("_seq", 0)))
        step = 1 if diff > 0 else -1
        i = 0
        remaining = abs(diff)
        while remaining > 0:
            p = order[i % len(order)]
            amounts[p["id"]] += step
            remaining -= 1
            i += 1
    return amounts


def run_preliminary_allocation(district):
    """Create one PRELIMINARY assessment per ACTIVE non-exempt parcel against
    the locked estimate's total_estimated_cost_cents."""
    est = STORE.estimates[district["approved_estimate_id"]]
    parcels = eligible_parcels(district["id"])
    amounts = allocate_amounts(est["total_estimated_cost_cents"], parcels,
                               district["methodology"])
    ts = now()
    for p in parcels:
        a = {
            "id": new_id(),
            "district_id": district["id"],
            "parcel_id": p["id"],
            "preliminary_amount_cents": amounts[p["id"]],
            "final_levy_cents": None,
            "payment_option": "NONE",
            "term_years": None,
            "principal_balance_cents": 0,
            "total_paid_cents": 0,
            "credit_balance_cents": 0,
            "total_refunded_cents": 0,
            "status": "PRELIMINARY",
            "option_selected_at": None,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        STORE.put("assessments", a)
        STORE.principal_history[a["id"]] = []


def rerun_preliminary_allocation(district):
    """Objection-sustain reallocation: rewrite every surviving PRELIMINARY
    assessment's preliminary_amount_cents over the remaining roll."""
    est = STORE.estimates[district["approved_estimate_id"]]
    parcels = eligible_parcels(district["id"])
    amounts = allocate_amounts(est["total_estimated_cost_cents"], parcels,
                               district["methodology"])
    for p in parcels:
        for a in STORE.assessments.values():
            if (a["parcel_id"] == p["id"] and a["district_id"] == district["id"]
                    and a["status"] == "PRELIMINARY"):
                if a["preliminary_amount_cents"] != amounts[p["id"]]:
                    a["preliminary_amount_cents"] = amounts[p["id"]]
                    touch(a)


# ---------------------------------------------------------------------------
# protest weight (§3.4)
# ---------------------------------------------------------------------------

def compute_protest_pct(district, hearing):
    eps = eligible_parcels(district["id"])
    denom = sum((parcel_frontage(p) for p in eps), Decimal("0"))
    if denom == 0:
        return None
    hearing_id = hearing["id"] if hearing else None
    overruled_parcel_ids = {
        o["parcel_id"] for o in STORE.objections.values()
        if o["hearing_id"] == hearing_id and o["status"] == "OVERRULED"
    }
    numer = sum((parcel_frontage(p) for p in eps if p["id"] in overruled_parcel_ids),
                Decimal("0"))
    pct = rhu(numer / denom * Decimal("100"), PCT_Q)
    return float(pct)


# ---------------------------------------------------------------------------
# installment amortization schedule (§3.7)
# ---------------------------------------------------------------------------

def build_amortization_schedule(district, assessment, trueup_at):
    P = assessment["final_levy_cents"]
    n = assessment["term_years"]
    r = Decimal(district["annual_interest_rate_bp"]) / Decimal("10000")
    with localcontext() as ctx:
        ctx.prec = 50
        if r == 0:
            level = rhu_int(Decimal(P) / Decimal(n))
        else:
            level = rhu_int(Decimal(P) * r / (Decimal(1) - (Decimal(1) + r) ** (-n)))
        balance = P
        for y in range(1, n + 1):
            interest_y = rhu_int(Decimal(balance) * r) if r != 0 else 0
            if y < n:
                principal_y = level - interest_y
            else:
                principal_y = balance
            due = trueup_at + timedelta(days=365 * y)
            issue = due - timedelta(days=30)
            inv = {
                "id": new_id(),
                "district_id": district["id"],
                "parcel_assessment_id": assessment["id"],
                "kind": "ANNUAL",
                "year_index": y,
                "issue_date": issue,
                "due_date": due,
                "principal_cents": principal_y,
                "interest_cents": interest_y,
                "penalty_cents": 0,
                "paid_cents": 0,
                # waterfall split tracking (internal)
                "_penalty_paid": 0,
                "_interest_paid": 0,
                "_principal_paid": 0,
                "status": "SCHEDULED",
                "created_at": trueup_at,
                "updated_at": trueup_at,
                "version": 1,
            }
            STORE.put("invoices", inv)
            balance -= principal_y


# ---------------------------------------------------------------------------
# accrued interest ACT/365 (§3.8)
# ---------------------------------------------------------------------------

def accrued_total_interest(district, assessment, at):
    """Sum of per-segment interest from principal-change events since true-up.
    PREPAID/SETTLEMENT_DUE (no schedule) accrue nothing."""
    if assessment["status"] in ("PREPAID", "SETTLEMENT_DUE"):
        return 0
    history = STORE.principal_history.get(assessment["id"], [])
    if not history:
        return 0
    rate = Decimal(district["annual_interest_rate_bp"]) / Decimal("10000")
    total = 0
    events = sorted(history, key=lambda e: (e[0], e[2]))
    for i, (t0, bal, _seq) in enumerate(events):
        t1 = events[i + 1][0] if i + 1 < len(events) else at
        days = Decimal(str((t1 - t0).total_seconds())) / Decimal("86400")
        if days <= 0:
            continue
        with localcontext() as ctx:
            ctx.prec = 50
            total += rhu_int(Decimal(bal) * rate * days / Decimal("365"))
    return total


def interest_paid_total(assessment):
    return sum(p["applied_interest_cents"] for p in STORE.payments.values()
               if p["parcel_assessment_id"] == assessment["id"])


def accrued_unpaid_interest(district, assessment, at):
    return max(0, accrued_total_interest(district, assessment, at)
             - interest_paid_total(assessment))


def penalty_unpaid_total(assessment):
    total = 0
    for inv in STORE.invoices.values():
        if (inv["parcel_assessment_id"] == assessment["id"]
                and inv["status"] == "DELINQUENT"):
            total += max(0, inv["penalty_cents"] - inv["_penalty_paid"])
    return total


def billed_unpaid_total(assessment):
    total = 0
    for inv in STORE.invoices.values():
        if (inv["parcel_assessment_id"] == assessment["id"]
                and inv["status"] in ("ISSUED", "PARTIALLY_PAID", "DELINQUENT")):
            inv_total = inv["principal_cents"] + inv["interest_cents"] + inv["penalty_cents"]
            total += max(0, inv_total - inv["paid_cents"])
    return total


def payoff_quote(district, assessment, at):
    accrued = accrued_unpaid_interest(district, assessment, at)
    penalty = penalty_unpaid_total(assessment)
    payoff = assessment["principal_balance_cents"] + accrued + penalty
    return {
        "payoff_cents": payoff,
        "principal_balance_cents": assessment["principal_balance_cents"],
        "billed_unpaid_cents": billed_unpaid_total(assessment),
        "accrued_interest_cents": accrued,
        "penalty_unpaid_cents": penalty,
    }


# ---------------------------------------------------------------------------
# payment waterfall (§3.8)
# ---------------------------------------------------------------------------

def record_principal_event(assessment):
    STORE.principal_history.setdefault(assessment["id"], []).append(
        (now(), assessment["principal_balance_cents"], STORE.next_seq()))


def apply_waterfall(district, assessment, amount):
    """Applies `amount` per the pinned waterfall. Returns the split
    (applied_penalty, applied_interest, applied_principal)."""
    applied_penalty = 0
    applied_interest = 0
    applied_principal = 0
    remaining = amount

    # Step 1: billed invoices, due_date ASC, tie-break created_at ASC;
    # within an invoice: penalty -> interest -> principal.
    billed = [inv for inv in STORE.invoices.values()
              if inv["parcel_assessment_id"] == assessment["id"]
              and inv["status"] in ("ISSUED", "PARTIALLY_PAID", "DELINQUENT")]
    billed.sort(key=lambda i: (i["due_date"], i["created_at"], i.get("_seq", 0)))
    for inv in billed:
        if remaining <= 0:
            break
        was_delinquent = inv["status"] == "DELINQUENT"
        # penalty
        due_pen = inv["penalty_cents"] - inv["_penalty_paid"]
        pay = min(remaining, max(0, due_pen))
        if pay:
            inv["_penalty_paid"] += pay
            inv["paid_cents"] += pay
            applied_penalty += pay
            remaining -= pay
        # interest
        due_int = inv["interest_cents"] - inv["_interest_paid"]
        pay = min(remaining, max(0, due_int))
        if pay:
            inv["_interest_paid"] += pay
            inv["paid_cents"] += pay
            applied_interest += pay
            remaining -= pay
        # principal
        due_pri = inv["principal_cents"] - inv["_principal_paid"]
        pay = min(remaining, max(0, due_pri))
        if pay:
            inv["_principal_paid"] += pay
            inv["paid_cents"] += pay
            applied_principal += pay
            assessment["principal_balance_cents"] -= pay
            remaining -= pay
        inv_total = inv["principal_cents"] + inv["interest_cents"] + inv["penalty_cents"]
        if inv["paid_cents"] >= inv_total:
            inv["status"] = "PAID"
        elif inv["paid_cents"] > 0:
            inv["status"] = "PARTIALLY_PAID"
        touch(inv)
        if was_delinquent and inv["status"] == "PAID":
            # cure check: no DELINQUENT sibling remains -> assessment cured
            if not any(o["parcel_assessment_id"] == assessment["id"]
                       and o["status"] == "DELINQUENT"
                       for o in STORE.invoices.values()):
                if assessment["status"] == "DELINQUENT":
                    assessment["status"] = "IN_REPAYMENT"

    # Step 2: remainder -> accrued-unbilled interest. The interest applied in
    # step 1 of THIS payment is not yet in the payment store, so subtract it
    # explicitly alongside all previously stored interest payments.
    if remaining > 0:
        accrued_now = accrued_total_interest(district, assessment, now())
        accrued_open = max(0, accrued_now
                           - interest_paid_total(assessment) - applied_interest)
        pay = min(remaining, accrued_open)
        if pay:
            applied_interest += pay
            remaining -= pay

    # Step 3: remainder -> principal balance (prepayment).
    if remaining > 0:
        applied_principal += remaining
        assessment["principal_balance_cents"] -= remaining
        remaining = 0

    record_principal_event(assessment)

    # Step 4: paid-off check (accrued-unpaid accounting for this payment).
    accrued_now = accrued_total_interest(district, assessment, now())
    accrued_open = max(0, accrued_now
                       - interest_paid_total(assessment) - applied_interest)
    if (assessment["principal_balance_cents"] == 0
            and billed_unpaid_total(assessment) == 0
            and accrued_open == 0):
        assessment["status"] = "PAID_OFF"
        for inv in STORE.invoices.values():
            if (inv["parcel_assessment_id"] == assessment["id"]
                    and inv["status"] == "SCHEDULED"):
                inv["status"] = "VOIDED"
                touch(inv)

    return applied_penalty, applied_interest, applied_principal


# ---------------------------------------------------------------------------
# delinquency penalty (§3.8) + billing run
# ---------------------------------------------------------------------------

def compute_penalty(district, inv, at):
    grace_end = inv["due_date"] + timedelta(days=30)
    delta = (at - grace_end).total_seconds()
    months = int(delta // (30 * 86400))
    if months <= 0:
        return 0
    base = inv["principal_cents"] + inv["interest_cents"] - inv["paid_cents"]
    if base <= 0:
        return 0
    if district["interest_method"] == "SIMPLE":
        return months * rhu_int(Decimal(base) * Decimal("0.01"))
    # COMPOUND: penalty capitalizes monthly
    balance = base
    total = 0
    for _ in range(months):
        step = rhu_int(Decimal(balance) * Decimal("0.01"))
        balance += step
        total += step
    return total


def billing_run(district):
    at = now()
    issued_count = 0
    newly_delinquent = 0
    cured = 0
    invoices = [inv for inv in STORE.invoices.values()
                if inv["district_id"] == district["id"]]
    # issue pass
    for inv in invoices:
        if inv["status"] == "SCHEDULED" and at >= inv["issue_date"]:
            inv["status"] = "ISSUED"
            touch(inv)
            issued_count += 1
    # delinquency pass
    for inv in invoices:
        if inv["status"] in ("ISSUED", "PARTIALLY_PAID"):
            inv_total = inv["principal_cents"] + inv["interest_cents"] + inv["penalty_cents"]
            if inv["paid_cents"] < inv_total:
                grace_end = inv["due_date"] + timedelta(days=30)
                if at > grace_end:
                    inv["status"] = "DELINQUENT"
                    touch(inv)
                    newly_delinquent += 1
                    a = STORE.assessments.get(inv["parcel_assessment_id"])
                    if a and a["status"] == "IN_REPAYMENT":
                        a["status"] = "DELINQUENT"
                        touch(a)
    # idempotent penalty recompute over delinquent invoices
    for inv in invoices:
        if inv["status"] == "DELINQUENT":
            inv_total = inv["principal_cents"] + inv["interest_cents"] + inv["penalty_cents"]
            if inv["paid_cents"] < inv_total:
                new_pen = compute_penalty(district, inv, at)
                if new_pen != inv["penalty_cents"]:
                    inv["penalty_cents"] = new_pen
                    touch(inv)
    # cure pass (consistency): DELINQUENT assessment with no DELINQUENT invoice
    for a in STORE.assessments.values():
        if a["district_id"] == district["id"] and a["status"] == "DELINQUENT":
            if not any(inv["parcel_assessment_id"] == a["id"]
                       and inv["status"] == "DELINQUENT"
                       for inv in STORE.invoices.values()):
                a["status"] = "IN_REPAYMENT"
                touch(a)
                cured += 1
    return {"issued_count": issued_count,
            "newly_delinquent_count": newly_delinquent,
            "cured_count": cured}


# ---------------------------------------------------------------------------
# construction schedule validation (§3.6)
# ---------------------------------------------------------------------------

def _mmdd_of(d):
    return (d.month, d.day)


def _mmdd_le(a, b):
    return a <= b


def check_season(district, start_d, end_d):
    s = district["season_start_mmdd"]
    e = district["season_end_mmdd"]
    s_t = (int(s[:2]), int(s[3:]))
    e_t = (int(e[:2]), int(e[3:]))
    if s_t == (1, 1) and e_t == (12, 31):
        return True
    span = (end_d - start_d).days
    if span >= 365:
        return False
    d = start_d
    one = timedelta(days=1)
    while d <= end_d:
        md = _mmdd_of(d)
        if not (_mmdd_le(s_t, md) and _mmdd_le(md, e_t)):
            return False
        d += one
    return True


def check_crew_buffer(district, crew_name, start_d, end_d):
    for p in STORE.phases.values():
        if (p["district_id"] != district["id"]
                or p["status"] not in ("PLANNED", "IN_PROGRESS")
                or p["crew_name"] != crew_name):
            continue
        x_start = datetime.strptime(p["start_date"], "%Y-%m-%d").date()
        x_end = datetime.strptime(p["end_date"], "%Y-%m-%d").date()
        ok = (start_d >= x_end + timedelta(days=5)) or \
             (x_start >= end_d + timedelta(days=5))
        if not ok:
            return False
    return True


def check_capacity(district, start_d, end_d):
    existing = []
    for p in STORE.phases.values():
        if (p["district_id"] == district["id"]
                and p["status"] in ("PLANNED", "IN_PROGRESS")):
            xs = datetime.strptime(p["start_date"], "%Y-%m-%d").date()
            xe = datetime.strptime(p["end_date"], "%Y-%m-%d").date()
            existing.append((xs, xe))
    d = start_d
    one = timedelta(days=1)
    while d <= end_d:
        count = sum(1 for (xs, xe) in existing if xs <= d <= xe)
        if count >= 2:
            return False
        d += one
    return True


# ---------------------------------------------------------------------------
# cascades (§2.9, §3.5, §3.9)
# ---------------------------------------------------------------------------

def supersede_preliminary_assessments(district):
    for a in STORE.assessments.values():
        if a["district_id"] == district["id"] and a["status"] == "PRELIMINARY":
            a["status"] = "SUPERSEDED"
            touch(a)


def abandon_district(district):
    """Cascade per the district's current status, then -> ABANDONED."""
    st = district["status"]
    if st == "PETITIONING":
        for pet in STORE.petitions.values():
            if pet["district_id"] == district["id"] and pet["status"] == "CIRCULATING":
                pet["status"] = "VOIDED"
                pet["closed_at"] = now()
                touch(pet)
                for s in STORE.signatures.values():
                    if s["petition_id"] == pet["id"] and s["status"] in ("SUBMITTED", "VERIFIED"):
                        s["status"] = "VOIDED"
                        touch(s)
    elif st == "SCOPING":
        for e in STORE.estimates.values():
            if e["district_id"] == district["id"] and e["status"] in ("SUBMITTED", "APPROVED"):
                e["status"] = "SUPERSEDED"
                touch(e)
    elif st == "HEARING_SCHEDULED":
        for h in STORE.hearings.values():
            if h["district_id"] == district["id"] and h["status"] == "SCHEDULED":
                h["status"] = "VOIDED"
                touch(h)
        supersede_preliminary_assessments(district)
    elif st == "OBJECTION_WINDOW":
        for h in STORE.hearings.values():
            if h["district_id"] == district["id"] and h["status"] == "HELD":
                h["status"] = "VOIDED"
                touch(h)
        supersede_preliminary_assessments(district)
        for o in STORE.objections.values():
            if o["district_id"] == district["id"] and o["status"] in ("FILED", "UNDER_REVIEW"):
                o["status"] = "WITHDRAWN"
                touch(o)
    district["status"] = "ABANDONED"
    touch(district)


def finalize_true_up(district):
    """TRUE_UP -> BILLING: final levies, prepaid delta settlement, schedules."""
    est = STORE.estimates[district["approved_estimate_id"]]
    approved_change_total = sum(
        co["amount_cents"] for co in STORE.change_orders.values()
        if co["district_id"] == district["id"] and co["status"] == "APPROVED")
    district["final_total_cost_cents"] = est["contract_price_cents"] + approved_change_total
    trueup_at = now()

    parcels = eligible_parcels(district["id"])
    amounts = allocate_amounts(district["final_total_cost_cents"], parcels,
                               district["methodology"])
    for p in parcels:
        for a in STORE.assessments.values():
            if (a["parcel_id"] == p["id"] and a["district_id"] == district["id"]
                    and a["status"] in ("LEVIED", "PREPAID")):
                a["final_levy_cents"] = amounts[p["id"]]

    levy_bearing = [a for a in STORE.assessments.values()
                    if a["district_id"] == district["id"]
                    and a["status"] in ("LEVIED", "PREPAID")]
    levy_bearing.sort(key=lambda a: (a["created_at"], a["id"]))
    for a in levy_bearing:
        if a["status"] == "LEVIED":
            if a["payment_option"] == "NONE":
                a["payment_option"] = "INSTALLMENTS"
                a["term_years"] = 10
            if a["payment_option"] == "PREPAY_FULL":
                # elected but never paid: settle against nothing paid
                delta = a["final_levy_cents"] - a["total_paid_cents"]
                _settle_prepaid(district, a, delta, trueup_at)
            else:
                a["principal_balance_cents"] = a["final_levy_cents"]
                record_principal_event(a)
                build_amortization_schedule(district, a, trueup_at)
                a["status"] = "IN_REPAYMENT"
            touch(a)
        else:  # PREPAID
            delta = a["final_levy_cents"] - a["preliminary_amount_cents"]
            _settle_prepaid(district, a, delta, trueup_at)
            touch(a)

    district["status"] = "BILLING"
    touch(district)


def _settle_prepaid(district, a, delta, trueup_at):
    if delta > 0:
        a["status"] = "SETTLEMENT_DUE"
        a["principal_balance_cents"] = delta
        inv = {
            "id": new_id(),
            "district_id": district["id"],
            "parcel_assessment_id": a["id"],
            "kind": "SUPPLEMENTAL",
            "year_index": 0,
            "issue_date": trueup_at,
            "due_date": trueup_at + timedelta(days=30),
            "principal_cents": delta,
            "interest_cents": 0,
            "penalty_cents": 0,
            "paid_cents": 0,
            "_penalty_paid": 0,
            "_interest_paid": 0,
            "_principal_paid": 0,
            "status": "ISSUED",
            "created_at": trueup_at,
            "updated_at": trueup_at,
            "version": 1,
        }
        STORE.put("invoices", inv)
    else:
        a["status"] = "PAID_OFF"
        a["principal_balance_cents"] = 0
        if delta < 0:
            a["credit_balance_cents"] = -delta
