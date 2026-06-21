"""Premium-account ledger reconciliation + calculation engine.

Implements (PRD §2.6, §3.5–§3.7):
  - gross_monthly_premium (standard vs disability tier)
  - first_month_amount_due (full vs daily-prorated)
  - subsidy_applied (chronological first-match, no stacking)
  - deemed_full_payment (insignificant-shortfall allowance)
  - paid_through_date (longest unbroken satisfied run from month 1)
  - the four conserved account accumulators + credit_balance

All derived recomputes that change an account/invoice bump version+updated_at
via models.touch (PRD §2.4: derived-field changes count as mutations).
"""
from decimal import Decimal

from db import store
from models import touch
from money import mul_round, ratio_round, round_half_up
from timeutil import (
    parse_year_month, year_month_index, add_months, last_day_of_month,
    days_in_month,
)


# ---------------------------------------------------------------------------
# Premium / fee tier
# ---------------------------------------------------------------------------
def fee_pct_for_index(plan, enrollment, coverage_month_index):
    """Standard load, except months 19-29 of a disability-extended enrollment
    use the disability load (PRD §3.5)."""
    if enrollment.get("disability_extension") and 19 <= coverage_month_index <= 29:
        return plan["disability_admin_fee_pct"]
    return plan["standard_admin_fee_pct"]


def _premium_with_fee(applicable_premium_cents, fee_pct):
    return round_half_up(
        Decimal(applicable_premium_cents) * (Decimal(1) + Decimal(str(fee_pct)))
    )


def gross_premium_cents(plan, enrollment, coverage_month_index):
    fee = fee_pct_for_index(plan, enrollment, coverage_month_index)
    return _premium_with_fee(plan["applicable_premium_cents"], fee)


def monthly_premium_cents(plan):
    """Account-level gross premium for non-disability months = applicable *
    (1 + standard_admin_fee_pct), round-half-up (PRD §3.4)."""
    return _premium_with_fee(plan["applicable_premium_cents"], plan["standard_admin_fee_pct"])


def coverage_month_index(enrollment, year, month):
    """1-based index of (year, month) relative to coverage_start_date month."""
    start = enrollment["coverage_start_date"]
    return year_month_index(year, month) - year_month_index(start.year, start.month) + 1


# ---------------------------------------------------------------------------
# Subsidy: chronological first-match
# ---------------------------------------------------------------------------
def active_subsidy_for_month(enrollment_id, year, month):
    """Return the first ACTIVE grant (ordered by start_month asc, created_at
    asc) whose inclusive [start_month, end_month] contains (year, month), or
    None."""
    target = year_month_index(year, month)
    grants = []
    for g in store.subsidies.values():
        if g["enrollment_id"] != enrollment_id:
            continue
        if g["status"] != "ACTIVE":
            continue
        sy, sm = parse_year_month(g["start_month"])
        ey, em = parse_year_month(g["end_month"])
        if year_month_index(sy, sm) <= target <= year_month_index(ey, em):
            grants.append((year_month_index(sy, sm), g["created_at"], g["_seq"], g))
    if not grants:
        return None
    grants.sort(key=lambda t: (t[0], t[1], t[2]))
    return grants[0][3]


def compute_subsidy_for_invoice(enrollment, invoice):
    """subsidy_applied = round_half_up(amount_due * grant.subsidy_pct) for the
    first matching ACTIVE grant, else 0."""
    y, m = parse_year_month(invoice["coverage_month"])
    grant = active_subsidy_for_month(enrollment["id"], y, m)
    if grant is None:
        return 0
    return mul_round(invoice["amount_due_cents"], grant["subsidy_pct"])


def recompute_invoice_subsidy(enrollment, invoice):
    """Recompute subsidy_applied_cents + beneficiary_owed_cents on an invoice."""
    sub = compute_subsidy_for_invoice(enrollment, invoice)
    changed = (sub != invoice.get("subsidy_applied_cents")
               or (invoice["amount_due_cents"] - sub) != invoice.get("beneficiary_owed_cents"))
    invoice["subsidy_applied_cents"] = sub
    invoice["beneficiary_owed_cents"] = invoice["amount_due_cents"] - sub
    if changed:
        touch(invoice)
    return changed


# ---------------------------------------------------------------------------
# Amount due (full vs daily-prorated first month)
# ---------------------------------------------------------------------------
def amount_due_cents(gross, proration_mode, coverage_start_date):
    if proration_mode == "DAILY_PRORATED":
        dim = days_in_month(coverage_start_date)
        days_covered = dim - coverage_start_date.day + 1
        return ratio_round(gross, days_covered, dim)
    return gross


# ---------------------------------------------------------------------------
# Payment satisfaction / deemed-full / paid_through
# ---------------------------------------------------------------------------
def posted_paid_for_month(account_id, coverage_month):
    """Sum of amount_cents across POSTED payments targeting that month."""
    total = 0
    for p in store.payments.values():
        if p["account_id"] != account_id:
            continue
        if p["status"] != "POSTED":
            continue
        if p["target_coverage_month"] != coverage_month:
            continue
        total += p["amount_cents"]
    return total


def shortfall_allowance(plan, beneficiary_owed_cents):
    """max(floor, round_half_up(0.10 * beneficiary_owed_cents))."""
    pct_part = mul_round(beneficiary_owed_cents, 0.10)
    return max(plan["insignificant_shortfall_floor_cents"], pct_part)


def invoice_for_month(account_id, coverage_month):
    for inv in store.invoices.values():
        if inv["account_id"] == account_id and inv["coverage_month"] == coverage_month \
                and inv["status"] != "VOID":
            return inv
    return None


def latest_payment_deemed_full(account_id, coverage_month):
    """True when the most recently received POSTED payment for the month is
    deemed_full_payment."""
    candidates = [p for p in store.payments.values()
                  if p["account_id"] == account_id
                  and p["status"] == "POSTED"
                  and p["target_coverage_month"] == coverage_month]
    if not candidates:
        return False
    candidates.sort(key=lambda p: (p["received_date"], p["_seq"]))
    return bool(candidates[-1].get("deemed_full_payment"))


def month_satisfied(account_id, invoice):
    """A month is satisfied when POSTED payments + subsidy >= beneficiary_owed,
    or the latest payment for it is deemed_full_payment (PRD §3.6)."""
    cm = invoice["coverage_month"]
    paid = posted_paid_for_month(account_id, cm)
    if paid + invoice["subsidy_applied_cents"] >= invoice["beneficiary_owed_cents"]:
        return True
    if latest_payment_deemed_full(account_id, cm):
        return True
    return False


def compute_paid_through_date(account, enrollment):
    """Walk months ascending from index 1; advance through the longest unbroken
    run of satisfied months; paid_through = last calendar day of the last month
    in that run. Null if month 1 not satisfied (PRD §3.6)."""
    # Build a map of coverage_month_index -> non-void invoice for this account.
    invoices_by_index = {}
    for inv in store.invoices.values():
        if inv["account_id"] != account["id"]:
            continue
        if inv["status"] == "VOID":
            continue
        invoices_by_index[inv["coverage_month_index"]] = inv

    last_satisfied_index = 0
    idx = 1
    while idx in invoices_by_index:
        inv = invoices_by_index[idx]
        if month_satisfied(account["id"], inv):
            last_satisfied_index = idx
            idx += 1
        else:
            break
    if last_satisfied_index == 0:
        return None
    start = enrollment["coverage_start_date"]
    end_dt = add_months(start, last_satisfied_index - 1)
    ld = last_day_of_month(end_dt.year, end_dt.month)
    return end_dt.replace(day=ld, hour=0, minute=0, second=0, microsecond=0)


# ---------------------------------------------------------------------------
# Account accumulators / conservation
# ---------------------------------------------------------------------------
def recompute_account(account, enrollment, bump=True):
    """Recompute the four conserved accumulators, credit_balance, and
    paid_through_date from underlying records. credit_balance >= 0 invariant.

    Returns True if any persisted field changed."""
    invoiced = 0
    subsidized = 0
    for inv in store.invoices.values():
        if inv["account_id"] != account["id"]:
            continue
        if inv["status"] == "VOID":
            continue
        invoiced += inv["amount_due_cents"]
        subsidized += inv["subsidy_applied_cents"]

    paid = 0
    for p in store.payments.values():
        if p["account_id"] != account["id"]:
            continue
        if p["status"] != "POSTED":
            continue
        paid += p["amount_cents"]

    refunded = account.get("amount_refunded_cents", 0)
    credit = paid + subsidized - invoiced - refunded
    if credit < 0:
        credit = 0

    ptd = compute_paid_through_date(account, enrollment)

    before = (
        account.get("amount_invoiced_cents"),
        account.get("amount_subsidized_cents"),
        account.get("amount_paid_cents"),
        account.get("credit_balance_cents"),
        account.get("paid_through_date"),
    )
    account["amount_invoiced_cents"] = invoiced
    account["amount_subsidized_cents"] = subsidized
    account["amount_paid_cents"] = paid
    account["credit_balance_cents"] = credit
    account["paid_through_date"] = ptd
    after = (invoiced, subsidized, paid, credit, ptd)

    changed = before != after
    if changed and bump:
        touch(account)
    return changed
