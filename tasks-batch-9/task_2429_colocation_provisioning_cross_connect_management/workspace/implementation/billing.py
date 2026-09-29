"""Money: the invoice-line ledger, period close and remote-hands labour.

Implements contract_power_billing, cross_connect_period_billing and
remote_hands_labor_charge exactly as pinned in PRD §3.6 and §3.9.
"""

from decimal import Decimal

from rollups import cabinets_of_contract, circuits_of_contract, orders_of_contract
from store import (
    AFTER_HOURS_EVENING_HOUR,
    AFTER_HOURS_MULTIPLIER,
    AFTER_HOURS_START_EXCLUSIVE_HOUR,
    BILLING_INCREMENT_MINUTES,
    CC_DECOMMISSION_CREDIT_PCT,
    CC_VOLUME_DISCOUNT_TIER_1_PCT,
    CC_VOLUME_DISCOUNT_TIER_2_PCT,
    CC_VOLUME_TIER_1_MIN_USD,
    CC_VOLUME_TIER_2_MIN_USD,
    COMMIT_HOURS_PER_MONTH,
    DEEMED_LOAD_FACTOR,
    INFRA_SURCHARGE_PCT,
    OVERAGE_TIER_1_LIMIT_KWH,
    OVERAGE_TIER_1_RATE,
    OVERAGE_TIER_2_LIMIT_KWH,
    OVERAGE_TIER_2_RATE,
    OVERAGE_TIER_3_RATE,
    POWER_COMMIT_RATE_USD_PER_KW_MONTH,
    REMOTE_HANDS_RATE_USD_PER_INCREMENT,
    SLA_BREACH_CREDIT_PCT,
    base_row,
    store,
)
from util import ceil_div, dec, floor_div, q2, q3, q4

ZERO = Decimal("0")


def append_line(
    contract,
    line_type,
    amount_usd,
    quantity=0,
    unit_rate_usd=0,
    period_start=None,
    period_end=None,
    source_ref_id=None,
    included_minutes_consumed=0,
):
    """An InvoiceLine is an immutable ledger entry: id and created_at only."""
    line = base_row(common_fields=False)
    line.update(
        {
            "contract_id": contract["id"],
            "line_type": line_type,
            "amount_usd": q2(amount_usd),
            "quantity": quantity,
            "unit_rate_usd": q4(unit_rate_usd),
            "period_start": period_start,
            "period_end": period_end,
            "source_ref_id": source_ref_id,
            "included_minutes_consumed": included_minutes_consumed,
            "reversed": False,
        }
    )
    store.invoice_lines[line["id"]] = line
    return line


# --------------------------------------------------------------------------
# contract_power_billing
# --------------------------------------------------------------------------

def contract_power_billing(contract, period_start, period_end):
    commit = dec(contract["power_commit_kw"])
    committed_charge = q2(commit * dec(POWER_COMMIT_RATE_USD_PER_KW_MONTH))
    included_kwh = q3(commit * dec(COMMIT_HOURS_PER_MONTH))

    if contract["billing_mode"] == "METERED_PLUS_COMMIT":
        total = ZERO
        for circuit in circuits_of_contract(contract["id"]):
            for interval in circuit.get("meter_intervals", []):
                if period_start <= interval["interval_start"] < period_end:
                    total += dec(interval["kwh"])
        billable_kwh = q3(total)
    else:  # COMMITTED_ONLY — meter intervals ignored, load is deemed
        allocated = ZERO
        for circuit in circuits_of_contract(contract["id"]):
            if circuit["status"] == "ENERGIZED" and circuit["redundancy_role"] == "PRIMARY":
                allocated += dec(circuit["allocated_kw"])
        billable_kwh = q3(allocated * dec(COMMIT_HOURS_PER_MONTH) * dec(DEEMED_LOAD_FACTOR))

    raw_overage = q3(dec(billable_kwh) - dec(included_kwh))
    overage_kwh = raw_overage if dec(raw_overage) > 0 else 0.0

    over = dec(overage_kwh)
    limit1 = dec(OVERAGE_TIER_1_LIMIT_KWH)
    limit2 = dec(OVERAGE_TIER_2_LIMIT_KWH)
    t1 = over if over < limit1 else limit1
    t2 = over - limit1
    if t2 < 0:
        t2 = ZERO
    if t2 > limit2 - limit1:
        t2 = limit2 - limit1
    t3 = over - limit2
    if t3 < 0:
        t3 = ZERO
    overage_charge = q2(
        t1 * dec(OVERAGE_TIER_1_RATE)
        + t2 * dec(OVERAGE_TIER_2_RATE)
        + t3 * dec(OVERAGE_TIER_3_RATE)
    )

    append_line(
        contract,
        "POWER_COMMIT",
        committed_charge,
        quantity=contract["power_commit_kw"],
        unit_rate_usd=POWER_COMMIT_RATE_USD_PER_KW_MONTH,
        period_start=period_start,
        period_end=period_end,
    )
    if dec(overage_kwh) > 0:
        rate = q4(dec(overage_charge) / dec(overage_kwh))
        append_line(
            contract,
            "POWER_OVERAGE",
            overage_charge,
            quantity=overage_kwh,
            unit_rate_usd=rate,
            period_start=period_start,
            period_end=period_end,
        )
    return {
        "committed_charge": committed_charge,
        "included_kwh": included_kwh,
        "billable_kwh": billable_kwh,
        "overage_kwh": overage_kwh,
        "overage_charge": overage_charge,
    }


# --------------------------------------------------------------------------
# cross_connect_period_billing
# --------------------------------------------------------------------------

def cross_connect_period_billing(contract, period_start, period_end):
    candidates = [o for o in orders_of_contract(contract["id"]) if o["status"] == "ACTIVE"]
    candidates.sort(key=lambda o: (dec(o["mrc_usd"]), o["created_at"], o.get("_seq", 0)))

    allowance = contract["cross_connect_allowance"] or 0
    billed = candidates[allowance:] if allowance < len(candidates) else []

    subtotal = q2(sum((dec(o["mrc_usd"]) for o in billed), ZERO))
    sub = dec(subtotal)
    if sub >= dec(CC_VOLUME_TIER_2_MIN_USD):
        discount = dec(CC_VOLUME_DISCOUNT_TIER_2_PCT)
    elif sub >= dec(CC_VOLUME_TIER_1_MIN_USD):
        discount = dec(CC_VOLUME_DISCOUNT_TIER_1_PCT)
    else:
        discount = ZERO
    discounted = q2(sub * (Decimal("1") - discount))
    surcharge = q2(dec(discounted) * dec(INFRA_SURCHARGE_PCT))
    total = q2(dec(discounted) + dec(surcharge))

    count = len(billed)
    if dec(discounted) > 0:
        rate = q4(dec(discounted) / dec(count)) if count else 0
        append_line(
            contract,
            "CROSS_CONNECT_MRC",
            discounted,
            quantity=count,
            unit_rate_usd=rate,
            period_start=period_start,
            period_end=period_end,
        )
        append_line(
            contract,
            "CROSS_CONNECT_SURCHARGE",
            surcharge,
            quantity=count,
            unit_rate_usd=INFRA_SURCHARGE_PCT,
            period_start=period_start,
            period_end=period_end,
        )
    return {
        "subtotal": subtotal,
        "discounted_subtotal": discounted,
        "surcharge": surcharge,
        "total": total,
        "billed_count": count,
    }


def cross_connect_decommission_credit(contract, order):
    credit = q2(-(dec(order["mrc_usd"]) * dec(CC_DECOMMISSION_CREDIT_PCT)))
    return append_line(
        contract,
        "CROSS_CONNECT_CREDIT",
        credit,
        quantity=1,
        unit_rate_usd=CC_DECOMMISSION_CREDIT_PCT,
        source_ref_id=order["id"],
    )


# --------------------------------------------------------------------------
# remote_hands_labor_charge
# --------------------------------------------------------------------------

def _after_hours(started_at):
    hour = started_at.hour
    return hour < AFTER_HOURS_START_EXCLUSIVE_HOUR or hour >= AFTER_HOURS_EVENING_HOUR


def remote_hands_labor_charge(ticket, contract, segments):
    """segments: list of {started_at, ended_at} with parsed datetimes, in the
    order they were submitted. Rounding order is pinned: ceil per segment,
    then sum; charge rounded per segment, then summed."""
    ordered = sorted(
        list(enumerate(segments)), key=lambda pair: (pair[1]["started_at"], pair[0])
    )

    computed = []
    for index, segment in ordered:
        delta = segment["ended_at"] - segment["started_at"]
        raw_minutes = int(delta.total_seconds() // 60)
        if raw_minutes <= 0:
            increments = 0
        else:
            increments = ceil_div(raw_minutes, BILLING_INCREMENT_MINUTES)
        computed.append(
            {
                "index": index,
                "increments": increments,
                "after_hours": _after_hours(segment["started_at"]),
            }
        )

    billable_increments = sum(c["increments"] for c in computed)
    billed_minutes = billable_increments * BILLING_INCREMENT_MINUTES

    budget = floor_div(contract["remote_hands_remaining_minutes"], BILLING_INCREMENT_MINUTES)
    included_applied = min(budget, billable_increments)

    remaining_budget = included_applied
    labor = ZERO
    for entry in computed:
        absorbed = min(entry["increments"], remaining_budget)
        remaining_budget -= absorbed
        chargeable = entry["increments"] - absorbed
        multiplier = dec(AFTER_HOURS_MULTIPLIER) if entry["after_hours"] else Decimal("1.0")
        charge = q2(dec(chargeable) * dec(REMOTE_HANDS_RATE_USD_PER_INCREMENT) * multiplier)
        entry["charge"] = charge
        labor += dec(charge)
    labor_charge = q2(labor)

    ticket["billable_increments"] = billable_increments
    ticket["billed_minutes"] = billed_minutes
    ticket["included_increments_applied"] = included_applied
    ticket["labor_charge_usd"] = labor_charge

    contract["remote_hands_remaining_minutes"] = (
        contract["remote_hands_remaining_minutes"] - included_applied * BILLING_INCREMENT_MINUTES
    )
    if contract["remote_hands_remaining_minutes"] < 0:
        contract["remote_hands_remaining_minutes"] = 0

    if dec(labor_charge) > 0:
        append_line(
            contract,
            "REMOTE_HANDS",
            labor_charge,
            quantity=billable_increments - included_applied,
            unit_rate_usd=REMOTE_HANDS_RATE_USD_PER_INCREMENT,
            source_ref_id=ticket["id"],
            included_minutes_consumed=included_applied * BILLING_INCREMENT_MINUTES,
        )
        if ticket["sla_breached"]:
            credit = q2(-(dec(labor_charge) * dec(SLA_BREACH_CREDIT_PCT)))
            append_line(
                contract,
                "SLA_CREDIT",
                credit,
                quantity=1,
                unit_rate_usd=SLA_BREACH_CREDIT_PCT,
                source_ref_id=ticket["id"],
            )
    return labor_charge


def reversal_line(contract, original, reason=None):
    amount = q2(-dec(original["amount_usd"]))
    return append_line(
        contract,
        "REVERSAL",
        amount,
        quantity=original.get("quantity", 0),
        unit_rate_usd=0,
        source_ref_id=original["id"],
    )
