"""Domain calculations: tuition assessment, refunds, sponsor invoicing,
installment splitting, late fees, collections fee, 1098-T amounts,
and the billing cycle. Money math uses Decimal with ROUND_HALF_UP."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store, base_fields, touch, clock_date
from dates import parse_date
from errors import err, ERR_NO_APPLICABLE_TUITION_RATE, ERR_NO_BILLABLE_CHARGES
from services.core import (post_entry, account_entries, open_amount,
                           find_account, recompute_account)

D0 = Decimal("0")


def round_half_up_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------- assessment

def find_applicable_rate(term_id, residency, level, effective):
    """Single TuitionRate for (term, residency, level) whose CLOSED effective
    window contains the enrollment effective_date."""
    for r in sorted(store.rates.values(), key=lambda x: x["_seq"]):
        if (r["term_id"] == term_id and r["residency"] == residency
                and r["level"] == level
                and parse_date(r["effective_from"]) <= effective
                and effective <= parse_date(r["effective_to"])):
            return r
    return None


def assess_tuition(enrollment, student, term):
    """tuition_assessment: tiered pricing; posts CHARGE(TUITION)+CHARGE(FEE)."""
    effective = parse_date(enrollment["effective_date"])
    rate = find_applicable_rate(term["id"], student["residency_status"],
                                student["level"], effective)
    if rate is None:
        raise err(ERR_NO_APPLICABLE_TUITION_RATE,
                  "No tuition rate matches this term, residency, level, and effective date")
    ch = enrollment["credit_hours"]
    if ch >= rate["full_time_threshold_credits"]:
        tuition = rate["flat_rate_cents"] + \
            max(0, ch - rate["max_flat_credits"]) * rate["overload_rate_cents"]
    else:
        tuition = ch * rate["per_credit_rate_cents"]
    fee = term["flat_fee_cents"]
    post_entry(enrollment["account_id"], "CHARGE", tuition,
               due_date=term["census_date"], charge_kind="TUITION",
               enrollment_id=enrollment["id"], source_ref="",
               memo="Tuition assessment")
    post_entry(enrollment["account_id"], "CHARGE", fee,
               due_date=term["census_date"], charge_kind="FEE",
               enrollment_id=enrollment["id"], source_ref="",
               memo="Mandatory enrollment fee")
    enrollment["assessed_total_cents"] = tuition + fee


# ------------------------------------------------------------------- refunds

def refund_basis(enrollment_id):
    basis = 0
    for e in account_entries_for_enrollment(enrollment_id):
        if e["entry_type"] == "CHARGE":
            basis += e["amount_cents"]
        elif e["entry_type"] == "CHARGE_REVERSAL":
            basis -= e["amount_cents"]
    return basis


def account_entries_for_enrollment(enrollment_id):
    rows = [e for e in store.ledger_entries.values()
            if e["enrollment_id"] == enrollment_id]
    rows.sort(key=lambda e: e["_seq"])
    return rows


def refund_pct(term, effective):
    """refund_calculation variants. Returns a Decimal fraction."""
    if term["refund_policy"] == "SCHEDULE_TIERED":
        # Inclusive boundaries: effective on the milestone earns the higher tier.
        if effective <= parse_date(term["full_refund_end_date"]):
            return Decimal("1")
        if effective <= parse_date(term["mid_refund_end_date"]):
            return Decimal("0.5")
        if effective <= parse_date(term["withdrawal_deadline"]):
            return Decimal("0.25")
        return D0
    # PRO_RATA
    start = parse_date(term["start_date"])
    end = parse_date(term["end_date"])
    days_total = (end - start).days
    days_elapsed = max(0, (effective - start).days)
    ratio = Decimal(days_elapsed) / Decimal(days_total)
    if ratio > Decimal("0.60"):
        return D0
    return (Decimal("1") - ratio).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def create_refund(enrollment, term, trigger, effective):
    basis = refund_basis(enrollment["id"])
    pct = refund_pct(term, effective)
    amount = int((Decimal(basis) * pct).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    r = base_fields()
    r.update({
        "account_id": enrollment["account_id"],
        "enrollment_id": enrollment["id"],
        "trigger": trigger,
        "effective_date": effective.isoformat(),
        "policy_variant": term["refund_policy"],
        "basis_cents": basis,
        "pct_applied": float(pct),
        "amount_cents": amount,
        "status": "CALCULATED",
    })
    store.refunds[r["id"]] = r
    return r


# -------------------------------------------------------------- sponsor side

def waiver_allocated(entry_id, account_id):
    """Sum of waiver allocations referencing the entry from POSTED
    (non-revoked) waivers on the same account."""
    total = 0
    for w in store.waivers.values():
        if w["account_id"] == account_id and w["status"] == "POSTED":
            for a in w["allocations"]:
                if a["ledger_entry_id"] == entry_id:
                    total += a["amount_cents"]
    return total


def build_invoice_lines(agreement, account):
    """sponsor_invoice_amount: eligible unbilled CHARGE entries, created_at ASC,
    hard stop at the first line that would exceed the remaining cap."""
    billed_elsewhere = set()
    for inv in store.invoices.values():
        if inv["agreement_id"] == agreement["id"] and inv["status"] != "VOID":
            for line in inv["lines"]:
                billed_elsewhere.add(line["ledger_entry_id"])
    eligible = []
    for e in account_entries(account["id"]):
        if e["entry_type"] != "CHARGE":
            continue
        if e["charge_kind"] == "TUITION" and not agreement["covers_tuition"]:
            continue
        if e["charge_kind"] == "FEE" and not agreement["covers_fees"]:
            continue
        if e["id"] in billed_elsewhere:
            continue
        eligible.append(e)
    eligible.sort(key=lambda e: e["_seq"])

    cap_remaining = agreement["cap_cents"] - agreement["billed_cents"]
    lines = []
    running = 0
    for e in eligible:
        if agreement["billing_basis"] == "GROSS":
            line_amount = e["amount_cents"]
        else:  # NET_OF_WAIVER
            line_amount = max(0, e["amount_cents"] - waiver_allocated(e["id"], account["id"]))
        if running + line_amount > cap_remaining:
            break  # hard stop; no skipping ahead
        if line_amount == 0:
            continue
        lines.append({"ledger_entry_id": e["id"], "memo": e["memo"],
                      "amount_cents": line_amount})
        running += line_amount
    if not lines:
        raise err(ERR_NO_BILLABLE_CHARGES,
                  "Sponsor invoice generation produced zero billable lines")
    return lines, running


def agreement_account(agreement):
    return find_account(agreement["student_id"], agreement["term_id"])


# --------------------------------------------------------------------- plans

def split_installments(total, n):
    """installment_split: round each share FIRST (half up), final installment
    absorbs the remainder."""
    base = int((Decimal(total) / Decimal(n)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    amounts = [base] * (n - 1)
    amounts.append(total - base * (n - 1))
    return amounts


def plan_installments(plan_id):
    rows = [i for i in store.installments.values() if i["plan_id"] == plan_id]
    rows.sort(key=lambda i: i["sequence"])
    return rows


def cancel_plan(plan):
    """Non-PAID installments -> CANCELLED; plan -> CANCELLED."""
    for i in plan_installments(plan["id"]):
        if i["status"] != "PAID":
            i["status"] = "CANCELLED"
            touch(i)
    plan["status"] = "CANCELLED"
    touch(plan)


# ------------------------------------------------------------- billing cycle

def run_billing_cycle(term):
    today = clock_date()
    grace = timedelta(days=term["grace_days"])
    # Aging pass: SCHEDULED installments past grace on plans of this term's
    # accounts, processed by plan created_at ASC then sequence ASC.
    plan_ids = set()
    acct_by_id = {}
    for a in store.accounts.values():
        if a["term_id"] == term["id"]:
            acct_by_id[a["id"]] = a
    plans = [p for p in store.plans.values() if p["account_id"] in acct_by_id]
    plans.sort(key=lambda p: p["_seq"])
    for p in plans:
        plan_ids.add(p["id"])
    candidates = [i for i in store.installments.values()
                  if i["plan_id"] in plan_ids and i["status"] == "SCHEDULED"
                  and i["paid_cents"] < i["amount_cents"]
                  and today > parse_date(i["due_date"]) + grace]
    plan_seq = {p["id"]: p["_seq"] for p in plans}
    candidates.sort(key=lambda i: (plan_seq[i["plan_id"]], i["sequence"]))

    marked = defaulted = fees = 0
    for i in candidates:
        i["status"] = "PAST_DUE"
        touch(i)
        # late_fee_assessment: one LATE_FEE entry per installment, rounded
        # half up individually before any summation.
        fee = round_half_up_cents(Decimal(i["amount_cents"]) * Decimal(str(term["late_fee_pct"])))
        plan = store.plans[i["plan_id"]]
        account = acct_by_id[plan["account_id"]]
        post_entry(account["id"], "LATE_FEE", fee, due_date=i["due_date"],
                   source_ref=i["id"], memo="Late fee")
        i["late_fee_posted"] = True
        marked += 1
        fees += 1
        if plan["status"] == "ACTIVE":
            plan["status"] = "DEFAULTED"
            plan["defaulted_count"] += 1
            touch(plan)
            defaulted += 1

    # Recompute pass across the term's accounts: past-due, status flips, holds.
    holds_placed = holds_released = 0
    for a in sorted(acct_by_id.values(), key=lambda x: x["_seq"]):
        if a["status"] in ("WRITTEN_OFF", "CLOSED"):
            continue
        placed, released = recompute_account(a)
        holds_placed += placed
        holds_released += released

    return {
        "installments_marked_past_due": marked,
        "plans_defaulted": defaulted,
        "late_fees_posted": fees,
        "holds_placed": holds_placed,
        "holds_released": holds_released,
    }


# ------------------------------------------------------------------ 1098-T

def compute_tax_boxes(student_id, tax_year):
    """form1098t_amounts: accounts whose term start_date falls inside the
    calendar tax year (Jan 1 .. Dec 31 inclusive)."""
    lo = f"{tax_year}-01-01"
    hi = f"{tax_year}-12-31"
    payments_received = 0
    qtre_charges = 0
    waiver_sum = 0
    for a in store.accounts.values():
        if a["student_id"] != student_id:
            continue
        term = store.terms.get(a["term_id"])
        if term is None or not (lo <= term["start_date"] <= hi):
            continue
        for e in account_entries(a["id"]):
            t = e["entry_type"]
            if t == "PAYMENT":
                payments_received += e["amount_cents"]
            elif t == "PAYMENT_REVERSAL":
                payments_received -= e["amount_cents"]
            elif t == "CHARGE" and e["charge_kind"] == "TUITION":
                qtre_charges += e["amount_cents"]
            elif t == "CHARGE_REVERSAL" and e["charge_kind"] == "TUITION":
                qtre_charges -= e["amount_cents"]
            elif t == "WAIVER":
                waiver_sum += e["amount_cents"]
            elif t == "WAIVER_REVERSAL":
                waiver_sum -= e["amount_cents"]
    box1 = max(0, min(payments_received, qtre_charges))
    box5 = max(0, waiver_sum)
    return box1, 0, box5
