"""Core billing engine: MRR reconciliation, invoice finalization, overage,
proration, payments, dunning, revenue recognition. Every routine traces to a
PRD §3 sentence (cited inline).
"""
from db import db, stamp_new, touch
from util import (
    round_half_up, add_days, full_days_elapsed,
    CYCLE_DAYS, RECOGNITION_DAYS, DUNNING_MAX_ATTEMPTS,
    DUNNING_RETRY_OFFSETS_DAYS, TAX_BPS_DENOMINATOR,
)


# =============================================================================
# MRR reconciliation (PRD §3.8 account_mrr, §2.9 cascading derived fields)
# =============================================================================
def _active_addon_fee_sum(subscription_id):
    total = 0
    for sa in db.subscription_addons.values():
        if sa["subscription_id"] == subscription_id and sa["status"] == "ACTIVE":
            addon = db.addons.get(sa["addon_id"])
            if addon:
                total += addon["monthly_fee_cents"]
    return total


def compute_mrr_contribution(sub):
    """Per-subscription normalized MRR (PRD §3.8).

    Contributes only while lifecycle_status == ACTIVE; TRIALING/CANCELED -> 0.
    base = plan.monthly_fee_cents + sum(ACTIVE add-on fees)
    RECURRING coupon -> subtract recurring discount (PERCENT or FIXED).
    """
    if sub["lifecycle_status"] != "ACTIVE":
        return 0
    plan = db.plans.get(sub["plan_id"])
    base = (plan["monthly_fee_cents"] if plan else 0) + _active_addon_fee_sum(sub["id"])

    recurring_discount = 0
    coupon_id = sub.get("coupon_id")
    if coupon_id:
        coupon = db.coupons.get(coupon_id)
        if coupon and coupon["duration"] == "RECURRING":
            if coupon["discount_type"] == "PERCENT":
                recurring_discount = round_half_up(base * coupon["percent_off"], 100)
            else:  # FIXED
                recurring_discount = min(coupon["amount_off_cents"], base)
    return base - recurring_discount


def recompute_subscription_mrr(sub):
    sub["mrr_contribution_cents"] = compute_mrr_contribution(sub)


def recompute_account_mrr(account):
    """Account.mrr_cents = sum of ACTIVE subscriptions' contributions (PRD §3.8)."""
    total = 0
    for sub in db.subscriptions.values():
        if sub["account_id"] == account["id"] and sub["lifecycle_status"] == "ACTIVE":
            total += sub["mrr_contribution_cents"]
    if account["mrr_cents"] != total:
        account["mrr_cents"] = total
        touch(account)
    return total


def reconcile_subscription_and_account(sub):
    """Recompute the subscription contribution and bubble up to the account
    (PRD §2.9). The account derived figure + updated_at/version refresh together.
    """
    recompute_subscription_mrr(sub)
    account = db.accounts.get(sub["account_id"])
    if account:
        recompute_account_mrr(account)


def record_churn(sub, lost_mrr_cents):
    """Stamp churn metadata for the MRR/churn report (PRD §3.8). Internal-only
    keys (not serialized). Captures the recurring revenue lost to this churn and
    the clock at which it churned."""
    sub["_churned_at"] = db.now()
    sub["_churned_mrr_cents"] = lost_mrr_cents


# =============================================================================
# Usage overage sweep (PRD §3.6 usage_overage_charge — marginal tiered bands)
# =============================================================================
def sweep_overage(sub, plan, period_start, period_end):
    """Sum unbilled usage in [period_start, period_end), apply marginal bands.

    Returns (overage_cost_cents, swept_records). Caller marks records billed
    and creates the OVERAGE line. Integer rate * integer units -> exact cents.
    """
    swept = []
    total_units = 0
    for ur in db.usage_records.values():
        if ur["subscription_id"] != sub["id"]:
            continue
        if ur["billed"]:
            continue
        rec_at = ur["recorded_at"]
        if period_start <= rec_at < period_end:
            total_units += ur["units"]
            swept.append(ur)

    overage_units = max(0, total_units - plan["included_usage_units"])

    remaining = overage_units
    cost = 0
    prev_cap = 0
    for band in plan["overage_tiers"]:
        if remaining == 0:
            break
        up_to = band.get("up_to_units")
        if up_to is None:
            band_width = remaining
        else:
            band_width = up_to - prev_cap
        take = min(remaining, band_width)
        cost += take * band["rate_cents_per_unit"]
        remaining -= take
        prev_cap = up_to if up_to is not None else prev_cap
    return cost, swept, overage_units


# =============================================================================
# Invoice line creation
# =============================================================================
def add_line(invoice, kind, description, amount_cents):
    line = {
        "invoice_id": invoice["id"],
        "kind": kind,
        "description": description,
        "amount_cents": amount_cents,
    }
    stamp_new(line, versioned=True)
    db.invoice_lines[line["id"]] = line
    return line


def _lines_for_invoice(invoice_id):
    return [l for l in db.invoice_lines.values() if l["invoice_id"] == invoice_id]


# =============================================================================
# Invoice finalize total (PRD §3.6 invoice_finalize_total — pinned order)
# =============================================================================
def is_first_finalized_invoice(sub, this_invoice):
    """True when `this_invoice` is the subscription's first finalized (non-DRAFT)
    invoice. Used to gate ONCE coupons (PRD §3.6 first_invoice variant)."""
    for inv in db.invoices.values():
        if inv["subscription_id"] != sub["id"]:
            continue
        if inv["id"] == this_invoice["id"]:
            continue
        if inv["status"] != "DRAFT":
            # Any already-finalized invoice means this is not the first.
            return False
    return True


def finalize_invoice(invoice, sub, account):
    """DRAFT -> OPEN finalization (PRD §3.6):
      1. subtotal = signed sum of lines
      2. discount (coupon: none / ONCE-not-first -> 0; PERCENT; FIXED)
      3. taxable_base = subtotal - discount
      4. tax = round_half_up(taxable_base * rate_bps / 10000)
      5. total = taxable_base + tax
    Then snapshot tax_jurisdiction_id, transition OPEN, attempt first payment.
    """
    lines = _lines_for_invoice(invoice["id"])
    subtotal = sum(l["amount_cents"] for l in lines)

    discount = 0
    coupon = db.coupons.get(invoice.get("coupon_id")) if invoice.get("coupon_id") else None
    if coupon is not None:
        first = is_first_finalized_invoice(sub, invoice)
        if coupon["duration"] == "ONCE" and not first:
            discount = 0
        elif coupon["discount_type"] == "PERCENT":
            discount = round_half_up(subtotal * coupon["percent_off"], 100)
        elif coupon["discount_type"] == "FIXED":
            discount = min(coupon["amount_off_cents"], subtotal)

    taxable_base = subtotal - discount

    jurisdiction = db.tax_jurisdictions.get(account["tax_jurisdiction_id"])
    rate_bps = jurisdiction["tax_rate_bps"] if jurisdiction else 0
    tax = round_half_up(taxable_base * rate_bps, TAX_BPS_DENOMINATOR)

    total = taxable_base + tax

    invoice["subtotal_cents"] = subtotal
    invoice["discount_cents"] = discount
    invoice["tax_cents"] = tax
    invoice["total_cents"] = total
    # Snapshot jurisdiction at finalization (PRD §3.6).
    invoice["tax_jurisdiction_id"] = account["tax_jurisdiction_id"]
    invoice["status"] = "OPEN"
    touch(invoice)

    # Immediately attempt the first payment as attempt number 1 (PRD §3.6/§3.7).
    attempt_payment(invoice, sub, account, attempt_number=1)
    return invoice


# =============================================================================
# Payments (PRD §3.7)
# =============================================================================
def _create_payment(invoice, attempt_number, status):
    p = {
        "invoice_id": invoice["id"],
        "amount_cents": invoice["total_cents"],
        "attempt_number": attempt_number,
        "status": status,
    }
    stamp_new(p, versioned=True)
    db.payments[p["id"]] = p
    return p


def attempt_payment(invoice, sub, account, attempt_number):
    """Attempt a payment. CLEARS iff account.payment_method_ok else FAILS
    (PRD §3.7). On CLEAR: invoice OPEN->PAID, amount_paid, revenue entry.
    On FAIL: begin/advance dunning.
    """
    ok = bool(account.get("payment_method_ok", True))
    if ok:
        payment = _create_payment(invoice, attempt_number, "CLEARED")
        _mark_invoice_paid(invoice, sub)
        return payment
    else:
        payment = _create_payment(invoice, attempt_number, "FAILED")
        _begin_dunning_on_first_failure(invoice, sub)
        return payment


def _mark_invoice_paid(invoice, sub):
    """OPEN -> PAID (PRD §3.7): amount_paid_cents = total; create revenue entry.
    Also reset dunning + revert billing_status to CURRENT when recovering."""
    invoice["status"] = "PAID"
    invoice["amount_paid_cents"] = invoice["total_cents"]
    touch(invoice)
    # Recovery from PAST_DUE (PRD §3.7): reset dunning, revert billing_status.
    if sub["billing_status"] == "PAST_DUE":
        sub["billing_status"] = "CURRENT"
        sub["dunning_attempt"] = 0
        sub["next_retry_at"] = None
        sub.pop("_first_failure_at", None)
        touch(sub)
    create_revenue_entry(invoice, sub)


def _begin_dunning_on_first_failure(invoice, sub):
    """First failure of an OPEN invoice (PRD §3.7):
      invoice OPEN -> PAST_DUE; billing_status CURRENT -> PAST_DUE;
      dunning_attempt += 1; next_retry_at = first_failure + OFFSETS[dunning_attempt].
    """
    now = db.now()
    sub["_first_failure_at"] = now  # internal anchor (not serialized)
    sub["dunning_attempt"] = sub["dunning_attempt"] + 1
    sub["billing_status"] = "PAST_DUE"
    sub["next_retry_at"] = add_days(now, DUNNING_RETRY_OFFSETS_DAYS[sub["dunning_attempt"]])
    touch(sub)
    invoice["status"] = "PAST_DUE"
    touch(invoice)


# =============================================================================
# Revenue recognition (PRD §3.8 recognized_revenue_to_date)
# =============================================================================
def create_revenue_entry(invoice, sub):
    """Create the RevenueScheduleEntry for a now-paid invoice (PRD §3.8).

    total_recognizable_cents = sum of SUBSCRIPTION + ADDON line amounts only;
    OVERAGE / PRORATION_* excluded.
    """
    recognizable = 0
    for l in _lines_for_invoice(invoice["id"]):
        if l["kind"] in ("SUBSCRIPTION", "ADDON"):
            recognizable += l["amount_cents"]
    entry = {
        "invoice_id": invoice["id"],
        "subscription_id": invoice["subscription_id"],
        "service_period_start": invoice["period_start"],
        "service_period_end": invoice["period_end"],
        "total_recognizable_cents": recognizable,
    }
    stamp_new(entry, versioned=True)
    db.revenue_entries[entry["id"]] = entry
    return entry


def recognized_to_date(entry):
    """recognized_to_date_cents as of the current clock (PRD §3.8).

    elapsed_days = clamp(floor((now - service_period_start)/1d), 0, 30)
    value = clamp(round_half_up(total * elapsed/30), 0, total)
    """
    now = db.now()
    elapsed = full_days_elapsed(now, entry["service_period_start"])
    if elapsed < 0:
        elapsed = 0
    if elapsed > RECOGNITION_DAYS:
        elapsed = RECOGNITION_DAYS
    total = entry["total_recognizable_cents"]
    value = round_half_up(total * elapsed, RECOGNITION_DAYS)
    if value < 0:
        value = 0
    if value > total:
        value = total
    return value


# =============================================================================
# Cycle invoice generation (subscription + add-on + overage lines)
# =============================================================================
def build_cycle_invoice(sub, account, plan, period_start, period_end,
                        include_overage, overage_window=None):
    """Create a DRAFT invoice with SUBSCRIPTION, ADDON, and (optionally) OVERAGE
    lines, then finalize it. Used for first-cycle (convert/auto) and renewals.
    coupon snapshot = the subscription's coupon (PRD §3.6).

    overage_window, when supplied, is the (start, end) of the *closing* cycle
    whose unbilled usage is swept — distinct from the invoice's own service
    period at renewal (PRD §3.3/§3.6). When None, the invoice's own period is
    swept (first-cycle invoices).
    """
    invoice = {
        "account_id": account["id"],
        "subscription_id": sub["id"],
        "coupon_id": sub.get("coupon_id"),
        "tax_jurisdiction_id": account["tax_jurisdiction_id"],
        "subtotal_cents": 0,
        "discount_cents": 0,
        "tax_cents": 0,
        "total_cents": 0,
        "amount_paid_cents": 0,
        "period_start": period_start,
        "period_end": period_end,
        "status": "DRAFT",
    }
    stamp_new(invoice, versioned=True)
    db.invoices[invoice["id"]] = invoice

    # SUBSCRIPTION line: plan monthly fee.
    add_line(invoice, "SUBSCRIPTION", f"Plan {plan.get('tier')} monthly fee",
             plan["monthly_fee_cents"])

    # ADDON lines: one per ACTIVE add-on on the subscription.
    for sa in _active_subscription_addons(sub["id"]):
        addon = db.addons.get(sa["addon_id"])
        if addon:
            add_line(invoice, "ADDON", f"Add-on {addon['code']} monthly fee",
                     addon["monthly_fee_cents"])

    # OVERAGE line: sweep unbilled usage in the closing cycle.
    if include_overage:
        ow_start, ow_end = overage_window if overage_window is not None else (period_start, period_end)
        cost, swept, overage_units = sweep_overage(sub, plan, ow_start, ow_end)
        if cost > 0 or overage_units > 0:
            if cost > 0:
                add_line(invoice, "OVERAGE",
                         f"Metered overage ({overage_units} units)", cost)
            for ur in swept:
                ur["billed"] = True  # idempotent metering (PRD §3.4/§3.6)

    finalize_invoice(invoice, sub, account)
    return invoice


def _active_subscription_addons(subscription_id):
    return [sa for sa in db.subscription_addons.values()
            if sa["subscription_id"] == subscription_id and sa["status"] == "ACTIVE"]


# =============================================================================
# Plan-change proration (PRD §3.5 proration_on_plan_change — dual variant)
# =============================================================================
def build_proration_invoice(sub, account, old_plan, new_plan):
    """Emit PRORATION_CREDIT (negative) + PRORATION_CHARGE (positive) lines on a
    new DRAFT invoice and finalize it (PRD §3.5). Day-granular over 30 days.
    """
    now = db.now()
    elapsed_days = full_days_elapsed(now, sub["period_start"])
    if elapsed_days < 0:
        elapsed_days = 0
    if elapsed_days > CYCLE_DAYS:
        elapsed_days = CYCLE_DAYS
    remaining_days = CYCLE_DAYS - elapsed_days

    credit = round_half_up(old_plan["monthly_fee_cents"] * remaining_days, CYCLE_DAYS)
    charge = round_half_up(new_plan["monthly_fee_cents"] * remaining_days, CYCLE_DAYS)

    invoice = {
        "account_id": account["id"],
        "subscription_id": sub["id"],
        "coupon_id": sub.get("coupon_id"),
        "tax_jurisdiction_id": account["tax_jurisdiction_id"],
        "subtotal_cents": 0,
        "discount_cents": 0,
        "tax_cents": 0,
        "total_cents": 0,
        "amount_paid_cents": 0,
        "period_start": sub["period_start"],
        "period_end": sub["period_end"],
        "status": "DRAFT",
    }
    stamp_new(invoice, versioned=True)
    db.invoices[invoice["id"]] = invoice

    add_line(invoice, "PRORATION_CREDIT",
             f"Unused remainder of plan {old_plan.get('tier')}", -credit)
    add_line(invoice, "PRORATION_CHARGE",
             f"New plan {new_plan.get('tier')} for remaining {remaining_days} days",
             charge)

    finalize_invoice(invoice, sub, account)
    return invoice
