"""Bill charge-stack computation and budget-plan true-up (PRD §3.4, §3.7).

Consumption inputs are summed from the account's ACTIVE meters whose reads fall
within the half-open cycle window [period_start, period_end). The charge stack
(fixed, water volumetric, sewer volumetric, leak credit) is then assembled.
"""
import db
from services import calc, ledger
from services.common import parse_datetime


def _meter_consumption_in_window(meter_id, period_start, period_end):
    """Sum consumption_gallons of reads for a meter whose read_date is in
    [period_start, period_end)."""
    total = 0
    for read in db.meter_reads.values():
        if read["meter_id"] != meter_id:
            continue
        rd = parse_datetime(read["read_date"])
        if rd is None:
            continue
        if period_start <= rd < period_end:
            total += read["consumption_gallons"]
    return total


def consumption_for_account(account_id, cycle):
    """Return (potable_gallons, irrigation_gallons, has_any_read_in_window).

    Reads are summed across the account's ACTIVE meters within the cycle window
    (PRD §3.4). has_any_read_in_window is used to enforce ERR_NO_CONSUMPTION_DATA.
    """
    period_start = parse_datetime(cycle["period_start"])
    period_end = parse_datetime(cycle["period_end"])

    potable = 0
    irrigation = 0
    has_read = False
    for meter in db.meters.values():
        if meter["account_id"] != account_id:
            continue
        if meter["status"] != "ACTIVE":
            continue
        # Does this meter have any read in window at all?
        for read in db.meter_reads.values():
            if read["meter_id"] != meter["id"]:
                continue
            rd = parse_datetime(read["read_date"])
            if rd is not None and period_start <= rd < period_end:
                has_read = True
                break
        consumed = _meter_consumption_in_window(meter["id"], period_start, period_end)
        if meter["meter_type"] == "POTABLE":
            potable += consumed
        elif meter["meter_type"] == "IRRIGATION":
            irrigation += consumed
    return potable, irrigation, has_read


def compute_charge_stack(bill, account, schedule):
    """(Re)compute all derived charge fields on a bill in place (PRD §3.4).

    Uses the account's current assistance-enrollment state for the fixed-charge
    discount, the pinned rate schedule for pricing, and the account's active
    budget plan (if any) for total_cents / budget_billing_amount_cents.
    Preserves any existing leak_credit_cents.
    """
    total_gallons = bill["potable_consumption_gallons"] + bill["irrigation_consumption_gallons"]

    water_vol = calc.tiered_water_volumetric(total_gallons, schedule["water_tiers"])

    billable_sewer = calc.billable_sewer_gallons(
        bill["potable_consumption_gallons"],
        schedule["sewer_ratio_pct"],
        schedule.get("sewer_cap_gallons"),
    )
    sewer_vol = calc.sewer_volumetric_cents(billable_sewer, schedule["sewer_rate_cents_per_kgal"])

    fixed = calc.fixed_charge_cents(
        schedule["fixed_water_charge_cents"],
        schedule["fixed_sewer_charge_cents"],
        account["assistance_enrolled"],
        schedule["assistance_discount_pct"],
    )

    leak_credit = bill.get("leak_credit_cents", 0)

    bill["water_volumetric_cents"] = water_vol
    bill["billable_sewer_gallons"] = billable_sewer
    bill["sewer_volumetric_cents"] = sewer_vol
    bill["fixed_charge_cents"] = fixed
    bill["amount_billed_cents"] = calc.amount_billed_cents(fixed, water_vol, sewer_vol, leak_credit)

    plan = ledger.active_budget_plan(account["id"])
    if plan is not None:
        bill["budget_billing_amount_cents"] = plan["monthly_amount_cents"]
        bill["total_cents"] = plan["monthly_amount_cents"]
    else:
        bill["budget_billing_amount_cents"] = 0
        bill["total_cents"] = bill["amount_billed_cents"]


def recompute_plan_trueup(plan):
    """Recompute trued_up_delta_cents for a plan (PRD §3.7, chronological).

    actual_to_date = sum(amount_billed_cents of POSTED/PAID bills since
    enrollment, chronological by created_at ASC). installments_to_date =
    cycles_elapsed * monthly_amount_cents. delta = actual - installments.
    """
    aid = plan["account_id"]
    enroll_seq = plan["_enroll_seq"]
    bills = [
        b for b in db.bills.values()
        if b["account_id"] == aid
        and b["status"] in ("POSTED", "PAID")
        and b["_seq"] > enroll_seq
    ]
    bills.sort(key=lambda b: (b["created_at"], b["_seq"]))
    actual_to_date = sum(b["amount_billed_cents"] for b in bills)
    installments_to_date = plan["cycles_elapsed"] * plan["monthly_amount_cents"]
    plan["trued_up_delta_cents"] = actual_to_date - installments_to_date
