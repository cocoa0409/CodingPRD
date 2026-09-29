"""Money engine: pricing, schedules, rebates, allocation, late fees,
unearned-premium estimates and deficiency settlement.

Every amount is an exact integer number of cents.  Rounding order follows
PRD 2.6 / section 3 literally.
"""

from core import add_months, clock, new_record, round_half_up, touch
from model import (installments_of_agreement, late_fees_of_agreement,
                   policies_of_agreement)

TIER_SMALL_LIMIT = 500000
TIER_MID_LIMIT = 2000000
TIER_SMALL_BPS = 1800
TIER_MID_BPS = 1500
TIER_LARGE_BPS = 1200

OVERPAYMENT_TOLERANCE_CENTS = 50000

CANCELLATION_FEE_TIER_LIMIT = 25000
CANCELLATION_FEE_SMALL = 2500
CANCELLATION_FEE_LARGE = 5000


# ---------------------------------------------------------------------------
# Pricing engine
# ---------------------------------------------------------------------------

def premium_basis(agreement, variant):
    total = 0
    for policy in policies_of_agreement(agreement["id"]):
        if policy["carried_over"]:
            continue
        if variant == "PROVISIONAL":
            if policy["status"] == "PENDING_VERIFICATION":
                total += policy["gross_premium_cents"]
        else:
            if policy["status"] == "VERIFIED":
                total += policy["financed_premium_cents"]
    return total


def tier_rate_bps(amount_financed_cents):
    if amount_financed_cents <= TIER_SMALL_LIMIT:
        return TIER_SMALL_BPS
    if amount_financed_cents <= TIER_MID_LIMIT:
        return TIER_MID_BPS
    return TIER_LARGE_BPS


def period_interest(outstanding_cents, rate_bps):
    return round_half_up(outstanding_cents * rate_bps, 10000 * 12)


def finance_charge_for(method, amount_financed, rate_bps, count):
    if method == "ADD_ON":
        return round_half_up(amount_financed * rate_bps * count, 10000 * 12)
    base_slice = amount_financed // count
    outstanding = amount_financed
    total = 0
    for position in range(1, count + 1):
        total += period_interest(outstanding, rate_bps)
        principal = outstanding if position == count else base_slice
        outstanding -= principal
    return total


def price_agreement(agreement, rule, variant):
    """Run the five-step pricing engine and write the money fields."""
    basis = premium_basis(agreement, variant)
    amount_financed = (basis
                       - agreement["down_payment_cents"]
                       + agreement["service_fee_cents"]
                       + agreement["carried_over_balance_cents"])
    tier = tier_rate_bps(amount_financed)
    ceiling = rule["max_annual_rate_bps"]
    approved = agreement["approved_annual_rate_bps"]
    if agreement["rate_exception_approved"] and approved is not None:
        rate = min(approved, ceiling)
    else:
        rate = min(tier, ceiling)
    count = agreement["installment_count"]
    finance_charge = finance_charge_for(
        rule["finance_charge_method"], amount_financed, rate, count)
    agreement["total_premium_cents"] = basis
    agreement["amount_financed_cents"] = amount_financed
    agreement["effective_annual_rate_bps"] = rate
    agreement["finance_charge_cents"] = finance_charge
    agreement["total_of_payments_cents"] = amount_financed + finance_charge
    agreement["quote_basis"] = variant
    return agreement


# ---------------------------------------------------------------------------
# Installment schedule
# ---------------------------------------------------------------------------

def due_dates(first_due_date, count):
    return [add_months(first_due_date, k) for k in range(count)]


def schedule_rows(agreement, rule):
    """Return [(amount, principal_component, finance_charge_component)]."""
    count = agreement["installment_count"]
    rows = []
    if rule["finance_charge_method"] == "ADD_ON":
        top = agreement["total_of_payments_cents"]
        charge = agreement["finance_charge_cents"]
        base_amount = top // count
        base_charge = round_half_up(charge, count)
        for position in range(1, count + 1):
            if position == count:
                amount = top - base_amount * (count - 1)
                fee = charge - base_charge * (count - 1)
            else:
                amount = base_amount
                fee = base_charge
            rows.append((amount, amount - fee, fee))
        return rows
    base_slice = agreement["amount_financed_cents"] // count
    outstanding = agreement["amount_financed_cents"]
    rate = agreement["effective_annual_rate_bps"]
    for position in range(1, count + 1):
        fee = period_interest(outstanding, rate)
        principal = outstanding if position == count else base_slice
        rows.append((principal + fee, principal, fee))
        outstanding -= principal
    return rows


def cut_schedule(agreement, rule, first_due_date):
    rows = schedule_rows(agreement, rule)
    dates = due_dates(first_due_date, agreement["installment_count"])
    created = []
    for index, (amount, principal, fee) in enumerate(rows):
        created.append(new_record(
            "installments",
            agreement_id=agreement["id"],
            installment_number=index + 1,
            due_date=dates[index].isoformat(),
            amount_cents=amount,
            principal_component_cents=principal,
            finance_charge_component_cents=fee,
            paid_cents=0,
            status="SCHEDULED",
        ))
    return created


def redistribute_tail(agreement):
    """Rebuild the unpaid tail after a repricing (endorsement financing)."""
    rows = installments_of_agreement(agreement["id"])
    tail = [r for r in rows if r["status"] in ("SCHEDULED", "PAST_DUE")]
    if not tail:
        return
    paid_total = sum(r["paid_cents"] for r in rows)
    frozen_charge = sum(r["finance_charge_component_cents"] for r in rows
                        if r["status"] in ("PAID", "VOIDED"))
    tail_total = agreement["total_of_payments_cents"] - paid_total
    tail_charge = agreement["finance_charge_cents"] - frozen_charge
    count = len(tail)
    base_amount = tail_total // count if count else 0
    base_charge = round_half_up(tail_charge, count) if count else 0
    for index, row in enumerate(tail):
        if index == count - 1:
            amount = tail_total - base_amount * (count - 1)
            fee = tail_charge - base_charge * (count - 1)
        else:
            amount = base_amount
            fee = base_charge
        row["amount_cents"] = amount
        row["finance_charge_component_cents"] = fee
        row["principal_component_cents"] = amount - fee
        touch(row)


# ---------------------------------------------------------------------------
# Unearned finance charge rebate and payoff
# ---------------------------------------------------------------------------

def unearned_finance_charge_rebate(agreement, rule):
    rows = installments_of_agreement(agreement["id"])
    count = agreement["installment_count"]
    paid_count = sum(1 for r in rows if r["status"] == "PAID")
    remaining = count - paid_count
    if remaining <= 0:
        return 0
    if rule["rebate_method"] == "RULE_OF_78":
        rebate = round_half_up(
            agreement["finance_charge_cents"] * remaining * (remaining + 1),
            count * (count + 1))
    else:
        rebate = sum(r["finance_charge_component_cents"] for r in rows
                     if r["status"] in ("SCHEDULED", "PAST_DUE"))
    if rebate > agreement["unpaid_finance_charge_cents"]:
        rebate = agreement["unpaid_finance_charge_cents"]
    if rebate < 0:
        rebate = 0
    return rebate


def payoff_figures(agreement, rule):
    rebate = unearned_finance_charge_rebate(agreement, rule)
    gross = agreement["principal_balance_cents"] + agreement["unpaid_finance_charge_cents"]
    net = (gross - rebate
           + agreement["late_fee_balance_cents"]
           - agreement["unapplied_credit_cents"])
    return {
        "gross_balance_cents": gross,
        "unearned_finance_charge_rebate_cents": rebate,
        "outstanding_late_fee_cents": agreement["late_fee_balance_cents"],
        "unapplied_credit_cents": agreement["unapplied_credit_cents"],
        "net_payoff_cents": net,
        "rebate_method": rule["rebate_method"],
    }


# ---------------------------------------------------------------------------
# Payment allocation
# ---------------------------------------------------------------------------

def _split_paid(row):
    """How much of a row's paid_cents sits against charge vs principal."""
    charge_paid = min(row["paid_cents"], row["finance_charge_component_cents"])
    return charge_paid, row["paid_cents"] - charge_paid


def outstanding_fees_ordered(agreement_id):
    rows = [r for r in late_fees_of_agreement(agreement_id)
            if r["status"] == "OUTSTANDING"]
    return sorted(rows, key=lambda r: (r["assessed_date"],
                                       r["installment_number"],
                                       r["created_at"], r["_seq"]))


def allocate_payment(agreement, rule, payment):
    """Apply a payment to the note.  Mutates the agreement, installments and
    late fees, and records enough detail on the payment for exact reversal."""
    quote = payoff_figures(agreement, rule)
    tendered = payment["amount_cents"]
    variant = "PAYOFF" if tendered >= quote["net_payoff_cents"] else "STANDARD"
    payment["allocation_variant"] = variant
    contributions = {}
    settled_fees = []
    rows = installments_of_agreement(agreement["id"])

    if variant == "PAYOFF":
        rebate = quote["unearned_finance_charge_rebate_cents"]
        payment["rebate_applied_cents"] = rebate
        agreement["unpaid_finance_charge_cents"] -= rebate
        applied_fee = agreement["late_fee_balance_cents"]
        for fee in outstanding_fees_ordered(agreement["id"]):
            fee["status"] = "PAID"
            touch(fee)
            settled_fees.append(fee["id"])
        applied_charge = agreement["unpaid_finance_charge_cents"]
        applied_principal = agreement["principal_balance_cents"]
        applied_unapplied = tendered - applied_fee - applied_charge - applied_principal
        agreement["late_fee_balance_cents"] = 0
        agreement["unpaid_finance_charge_cents"] = 0
        agreement["principal_balance_cents"] = 0
        agreement["unapplied_credit_cents"] += applied_unapplied
        for row in rows:
            if row["status"] in ("SCHEDULED", "PAST_DUE"):
                delta = row["amount_cents"] - row["paid_cents"]
                if delta:
                    contributions[row["id"]] = delta
                row["paid_cents"] = row["amount_cents"]
                row["status"] = "PAID"
                touch(row)
        payment["applied_late_fee_cents"] = applied_fee
        payment["applied_finance_charge_cents"] = applied_charge
        payment["applied_principal_cents"] = applied_principal
        payment["applied_unapplied_cents"] = applied_unapplied
    else:
        payment["rebate_applied_cents"] = 0
        remainder = tendered
        applied_fee = 0
        applied_charge = 0
        applied_principal = 0
        for fee in outstanding_fees_ordered(agreement["id"]):
            if remainder >= fee["amount_cents"]:
                remainder -= fee["amount_cents"]
                applied_fee += fee["amount_cents"]
                agreement["late_fee_balance_cents"] -= fee["amount_cents"]
                fee["status"] = "PAID"
                touch(fee)
                settled_fees.append(fee["id"])
        past_due = sorted([r for r in rows if r["status"] == "PAST_DUE"],
                          key=lambda r: (r["due_date"], r["installment_number"]))
        scheduled = sorted([r for r in rows if r["status"] == "SCHEDULED"],
                           key=lambda r: r["installment_number"])
        for row in past_due + scheduled:
            if remainder <= 0:
                break
            charge_paid, principal_paid = _split_paid(row)
            charge_due = row["finance_charge_component_cents"] - charge_paid
            principal_due = row["principal_component_cents"] - principal_paid
            take_charge = min(remainder, max(charge_due, 0))
            remainder -= take_charge
            take_principal = min(remainder, max(principal_due, 0))
            remainder -= take_principal
            taken = take_charge + take_principal
            if taken <= 0:
                continue
            applied_charge += take_charge
            applied_principal += take_principal
            agreement["unpaid_finance_charge_cents"] -= take_charge
            agreement["principal_balance_cents"] -= take_principal
            row["paid_cents"] += taken
            contributions[row["id"]] = contributions.get(row["id"], 0) + taken
            if row["paid_cents"] >= row["amount_cents"]:
                row["status"] = "PAID"
            touch(row)
        agreement["unapplied_credit_cents"] += remainder
        payment["applied_late_fee_cents"] = applied_fee
        payment["applied_finance_charge_cents"] = applied_charge
        payment["applied_principal_cents"] = applied_principal
        payment["applied_unapplied_cents"] = remainder

    payment["_installment_contribs"] = contributions
    payment["_settled_fee_ids"] = settled_fees
    return payment


def reverse_payment(agreement, payment):
    """Unwind an allocation exactly (PRD 3.6)."""
    from model import get_late_fee
    agreement["principal_balance_cents"] += payment["applied_principal_cents"]
    agreement["unpaid_finance_charge_cents"] += (
        payment["applied_finance_charge_cents"] + payment["rebate_applied_cents"])
    agreement["unapplied_credit_cents"] -= payment["applied_unapplied_cents"]
    for fee_id in payment.get("_settled_fee_ids", []):
        fee = get_late_fee(fee_id)
        if fee["status"] == "PAID":
            fee["status"] = "OUTSTANDING"
            agreement["late_fee_balance_cents"] += fee["amount_cents"]
            touch(fee)
    today = clock.date().isoformat()
    rows = {r["id"]: r for r in installments_of_agreement(agreement["id"])}
    for row_id, amount in payment.get("_installment_contribs", {}).items():
        row = rows.get(row_id)
        if row is None:
            continue
        row["paid_cents"] = row["paid_cents"] - amount
        if row["paid_cents"] < 0:
            row["paid_cents"] = 0
        if row["status"] != "VOIDED":
            if row["paid_cents"] >= row["amount_cents"]:
                row["status"] = "PAID"
            elif row["due_date"] < today:
                row["status"] = "PAST_DUE"
            else:
                row["status"] = "SCHEDULED"
        touch(row)
    agreement["refund_due_cents"] = 0


# ---------------------------------------------------------------------------
# Late fees
# ---------------------------------------------------------------------------

def late_fee_amount(installment, rule):
    raw = round_half_up(installment["amount_cents"] * rule["late_fee_bps"], 10000)
    if raw < rule["late_fee_min_cents"]:
        raw = rule["late_fee_min_cents"]
    if raw > rule["late_fee_max_cents"]:
        raw = rule["late_fee_max_cents"]
    return raw


# ---------------------------------------------------------------------------
# Unearned premium estimate
# ---------------------------------------------------------------------------

def unearned_premium_estimate(policy, rule, cancellation_date):
    """Return (earned_days, estimate_cents)."""
    from core import parse_date
    start = parse_date(policy["verified_effective_date"], "verified_effective_date")
    end = parse_date(policy["expiration_date"], "expiration_date")
    term_days = (end - start).days
    elapsed = (cancellation_date - start).days
    earned = max(policy["min_earned_days"], elapsed)
    if earned > term_days:
        earned = term_days
    if policy["fully_earned"]:
        return earned, 0
    unearned_days = term_days - earned
    if term_days <= 0:
        return earned, 0
    pro_rata = round_half_up(policy["financed_premium_cents"] * unearned_days, term_days)
    if rule["unearned_premium_method"] == "SHORT_RATE":
        return earned, round_half_up(
            pro_rata * (10000 - rule["short_rate_penalty_bps"]), 10000)
    return earned, pro_rata


# ---------------------------------------------------------------------------
# Deficiency settlement and agency chargeback
# ---------------------------------------------------------------------------

def cancellation_fee_for(residual):
    if residual <= 0:
        return 0
    if residual <= CANCELLATION_FEE_TIER_LIMIT:
        return CANCELLATION_FEE_SMALL
    return CANCELLATION_FEE_LARGE


def settle_note(agreement, rule, agent):
    """Close a cancelled note once every carrier request has been answered."""
    from model import outstanding_chargeback_cents
    residual = (agreement["principal_balance_cents"]
                + agreement["unpaid_finance_charge_cents"]
                + agreement["late_fee_balance_cents"]
                - agreement["unapplied_credit_cents"])
    fee = cancellation_fee_for(residual)
    chargeback = None
    if residual <= 0:
        agreement["status"] = "CLOSED_ZERO"
        agreement["deficiency_balance_cents"] = 0
        agreement["agent_chargeback_cents"] = 0
        agreement["refund_due_cents"] = -residual
    else:
        agreement["status"] = "CANCELLED_DEFICIENT"
        deficiency = residual + fee
        agreement["deficiency_balance_cents"] = deficiency
        if agent["chargeback_basis"] == "COMMISSION_CAPPED":
            commission = round_half_up(
                agreement["total_premium_cents"] * agent["agent_commission_bps"], 10000)
            charge = min(deficiency, commission)
        else:
            headroom = (agent["chargeback_liability_cap_cents"]
                        - outstanding_chargeback_cents(agent["id"]))
            if headroom < 0:
                headroom = 0
            charge = min(deficiency, headroom)
        agreement["agent_chargeback_cents"] = charge
        chargeback = new_record(
            "chargebacks",
            producer_agent_id=agent["id"],
            agreement_id=agreement["id"],
            amount_cents=charge,
            basis=agent["chargeback_basis"],
            offset_applied_cents=0,
            status="PENDING",
            reason="CANCELLATION_DEFICIENCY",
        )
        exposure = outstanding_chargeback_cents(agent["id"])
        if (exposure >= agent["chargeback_liability_cap_cents"]
                and agent["status"] == "ACTIVE"):
            agent["status"] = "SUSPENDED_FOR_CHARGEBACKS"
            touch(agent)
    agreement["delinquency_stage"] = "CANCELLED"
    touch(agreement)
    return residual, fee, chargeback
