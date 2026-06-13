"""Pricing engine: TOU period derivation, demand, and the price_bill
calculation (PRD §3.3, scaffold §1.3 price_bill).

All monetary values are integer cents. Real-valued (kWh/kW) components are
converted to whole cents with round-half-up, applied exactly where the PRD
prescribes:
  - energy_charge_cents: rounded ONCE after the TOU-weighted sum.
  - demand_charge_cents: rounded independently.
  - export_credit_cents: rounded independently.
Ledger aggregation (waterfall, true-up) is exact integer arithmetic.
"""
from decimal import Decimal, ROUND_HALF_UP

from db import db

TOU_PERIODS = ("ON_PEAK", "MID_PEAK", "OFF_PEAK")


def round_half_up(value):
    """Round a real value to a whole integer using round-half-up (PRD §2.6)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def tou_period_for_hour(hour):
    """Map UTC hour-of-day to TOU period under the fixed schedule (PRD §3.2).

    ON_PEAK  : hours 16-20 (16:00 up to 21:00)
    MID_PEAK : hours 7-15 and 21-22 (07:00-16:00, 21:00-23:00)
    OFF_PEAK : hours 23, 0-6 (23:00 up to 07:00 next morning)
    """
    if 16 <= hour <= 20:
        return "ON_PEAK"
    if (7 <= hour <= 15) or (21 <= hour <= 22):
        return "MID_PEAK"
    # hours 23, 0, 1, 2, 3, 4, 5, 6
    return "OFF_PEAK"


def tier_price_cents(total_import_kwh, breakpoints, rates):
    """Inclining-block tier pricing over total_import_kwh (PRD §3.3 step 2).

    breakpoints: ascending kWh breakpoints b[0..n-1].
    rates: ascending per-kWh rates (cents) r[0..n] (length == breakpoints+1).

    Returns the tiered energy subtotal in cents (a Decimal, unrounded).
    """
    remaining = Decimal(str(total_import_kwh))
    lower = Decimal(0)
    tier_cost = Decimal(0)
    n = len(breakpoints)
    for i in range(n + 1):
        if i < n:
            upper = Decimal(str(breakpoints[i]))
        else:
            upper = None  # +inf
        if upper is None:
            block_kwh = remaining if remaining > 0 else Decimal(0)
        else:
            width = upper - lower
            block_kwh = min(remaining, width)
            if block_kwh < 0:
                block_kwh = Decimal(0)
        tier_cost += block_kwh * Decimal(str(rates[i]))
        remaining -= block_kwh
        if upper is not None:
            lower = upper
        if remaining <= 0:
            break
    return tier_cost


def billed_reads_for(account_id, period_start_dt, period_end_dt):
    """Return MeterRead records for the account's meters whose interval_start
    falls in the half-open window [period_start, period_end) (PRD §3.3).
    """
    from services.common import parse_dt

    meter_ids = {
        m["id"] for m in db.meters.values() if m["account_id"] == account_id
    }
    reads = []
    for r in db.meter_reads.values():
        if r["meter_id"] not in meter_ids:
            continue
        start = parse_dt(r["interval_start"])
        if start is None:
            continue
        if period_start_dt <= start < period_end_dt:
            reads.append(r)
    return reads


def active_grant_for(account_id):
    """Return the account's consumable AssistanceGrant (PLEDGED or APPLIED) with
    remaining_cents > 0, oldest-created first; None if there is none.
    """
    candidates = [
        g for g in db.assistance_grants.values()
        if g["account_id"] == account_id
        and g["status"] in ("PLEDGED", "APPLIED")
        and g["remaining_cents"] > 0
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda g: (g["created_at"], g["_seq"]))
    return candidates[0]


def price_bill(bill, account, tariff, plan):
    """Run the full pricing calculation for an issuing bill (PRD §3.3).

    Mutates `bill` with computed fields. Returns a dict describing the ledger
    deltas the caller must commit:
      {
        credit_debit_cents,        # debit account.net_metering_credit_balance
        new_credit_balance_cents,  # resulting credit bank value (carryover)
        assistance_applied_cents,
        grant,                     # grant record consumed (or None)
      }
    Does NOT mutate the account balance, version, or grant — the caller commits
    those so the operation stays atomic and ordered.
    """
    from services.common import parse_dt

    period_start_dt = parse_dt(bill["period_start"])
    period_end_dt = parse_dt(bill["period_end"])
    reads = billed_reads_for(bill["account_id"], period_start_dt, period_end_dt)

    # Step 1 — aggregate. Seed sums with Decimal(0) so an empty `reads` window
    # still yields a Decimal (a bare sum() over an empty iterable returns int 0,
    # which lacks Decimal methods used downstream by _num()).
    total_import = sum(
        (Decimal(str(r["import_kwh"])) for r in reads), Decimal(0)
    )
    total_export = sum(
        (Decimal(str(r["export_kwh"])) for r in reads), Decimal(0)
    )
    on_peak_demands = [
        Decimal(str(r["avg_demand_kw"]))
        for r in reads
        if r["tou_period"] == "ON_PEAK"
    ]
    billed_peak_demand = max(on_peak_demands) if on_peak_demands else Decimal(0)

    # Step 2 — inclining-block tier pricing over total imported energy.
    tier_cost = tier_price_cents(
        total_import,
        tariff["tier_breakpoints_kwh"],
        tariff["tier_rates_cents_per_kwh"],
    )

    # Step 3 — TOU weighting (round once after the weighted sum).
    multipliers = tariff["tou_multipliers"]
    weighted = Decimal(0)
    for p in TOU_PERIODS:
        period_import = sum(
            (Decimal(str(r["import_kwh"])) for r in reads if r["tou_period"] == p),
            Decimal(0),
        )
        if total_import > 0:
            share = period_import / total_import
        else:
            share = Decimal(0)
        weighted += tier_cost * share * Decimal(str(multipliers[p]))
    energy_charge_cents = round_half_up(weighted)

    # Step 4 — demand charge (rounded independently).
    demand_charge_cents = round_half_up(
        billed_peak_demand * Decimal(str(tariff["demand_charge_cents_per_kw"]))
    )

    # Step 5 — gross before credits.
    gross_cents = (
        tariff["fixed_charge_cents"] + energy_charge_cents + demand_charge_cents
    )

    # Step 6 — net-metering credit (export credit rounded independently).
    export_credit_cents = round_half_up(
        total_export * Decimal(str(tariff["net_metering_credit_cents_per_kwh"]))
    )
    credit_pool_cents = account["net_metering_credit_balance_cents"] + export_credit_cents
    floor_cents = tariff["fixed_charge_cents"] + demand_charge_cents
    max_creditable_cents = max(0, gross_cents - floor_cents)
    net_metering_credit_applied_cents = min(credit_pool_cents, max_creditable_cents)
    # PRD §3.3 step 6: "whatever remains of the pool after applying credit
    # becomes the carryover that rolls forward" — pool = carried balance + the
    # export credit earned this period, so the new banked balance is
    # (carried + export_credit) - applied.
    carryover_cents = credit_pool_cents - net_metering_credit_applied_cents

    # Step 7 — assistance applied AFTER net-metering credit.
    pre_assist_cents = gross_cents - net_metering_credit_applied_cents
    grant = active_grant_for(bill["account_id"])
    if grant is not None:
        assistance_applied_cents = min(grant["remaining_cents"], pre_assist_cents)
        if assistance_applied_cents < 0:
            assistance_applied_cents = 0
    else:
        assistance_applied_cents = 0

    # Step 8 — finalize.
    actual_cost_cents = max(0, pre_assist_cents - assistance_applied_cents)
    is_budget_billed = plan is not None and plan["status"] == "ACTIVE"
    if is_budget_billed:
        total_due_cents = plan["levelized_amount_cents"]
    else:
        total_due_cents = actual_cost_cents

    # Write computed fields onto the bill. kWh/kW values stay numeric (may be
    # float/int); cents are integers.
    bill["total_import_kwh"] = _num(total_import)
    bill["total_export_kwh"] = _num(total_export)
    bill["billed_peak_demand_kw"] = _num(billed_peak_demand)
    bill["energy_charge_cents"] = energy_charge_cents
    bill["demand_charge_cents"] = demand_charge_cents
    bill["net_metering_credit_applied_cents"] = net_metering_credit_applied_cents
    bill["assistance_applied_cents"] = assistance_applied_cents
    bill["actual_cost_cents"] = actual_cost_cents
    bill["total_due_cents"] = total_due_cents
    bill["is_budget_billed"] = is_budget_billed

    return {
        "credit_debit_cents": net_metering_credit_applied_cents,
        "new_credit_balance_cents": carryover_cents,
        "assistance_applied_cents": assistance_applied_cents,
        "grant": grant,
    }


def _num(dec):
    """Render a Decimal kWh/kW quantity as a JSON-friendly number: int when it is
    a whole number, otherwise float."""
    if dec == dec.to_integral_value():
        return int(dec)
    return float(dec)
