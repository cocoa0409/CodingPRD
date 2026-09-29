"""Calculation rules (SCAFFOLD 1.3 / PRD 3.6-3.9)."""
import math
from decimal import Decimal

import derive
from errors import fail
from store import db
from util import (MICRO_DOLLARS_PER_CENT, add_months, ceil_hours, micro_to_cents,
                  round_half_up, round_half_up_2)

WASTE_PENALTY_CENTS_PER_EVENT = 4500
PARTS_GRACE_HOURS = 8
SLA_CREDIT_CAP_CENTS = 25000
CREDIT_STEP_HOURS = 4
CREDIT_PCT_PER_STEP = Decimal("0.05")
MAX_FACTOR = Decimal("0.50")
RESIDUAL_CREDIT_PER_DEVICE_CENTS = 12000
SANITIZATION_FEE_PER_DEVICE_CENTS = 7500
SANITIZATION_DISCOUNT_THRESHOLD_CENTS = 500000
SANITIZATION_DISCOUNT_PCT = Decimal("0.10")
MIN_CARTRIDGE_PAGES = 3000
TONER_REORDER_PCT = 15
AUTO_TONER_UNIT_PRICE_CENTS = 8900
MAX_OPEN_ORDERS_PER_DEVICE = 1
SPIKE_MULTIPLIER = 3
UTIL_CONSOLIDATE_MAX_PCT = 15
UTIL_DOWNGRADE_MAX_PCT = 40
UTIL_UPGRADE_MIN_PCT = 90
SECONDS_PER_DAY = 86400


# ---------------------------------------------------- meter_read_validation ---
def validate_read(read, device):
    """Returns (status, exception_reason, mono_delta, color_delta)."""
    mono = read["mono_meter"] - device["last_accepted_mono_meter"]
    color = read["color_meter"] - device["last_accepted_color_meter"]
    if mono < 0 or color < 0:
        return "EXCEPTION", "ROLLBACK", 0, 0
    if mono + color > SPIKE_MULTIPLIER * device["rated_monthly_duty_cycle"]:
        return "EXCEPTION", "IMPLAUSIBLE_SPIKE", 0, 0
    return "ACCEPTED", "NONE", mono, color


# ------------------------------------------------------- sla_response_credit ---
def sla_response_credit(ticket, contract):
    hours_late = ticket["hours_late"]
    excused = min(hours_late, max(0, ticket["parts_hold_hours"] - PARTS_GRACE_HOURS))
    billable = hours_late - excused
    if billable <= 0:
        return 0
    step = -((-billable) // CREDIT_STEP_HOURS)
    factor = CREDIT_PCT_PER_STEP * Decimal(step)
    if ticket["severity"] == "CRITICAL":
        factor = factor * Decimal(2)
    if factor > MAX_FACTOR:
        factor = MAX_FACTOR
    credit = round_half_up(Decimal(contract["monthly_service_fee_cents"]) * factor)
    return min(SLA_CREDIT_CAP_CENTS, credit)


def service_labor_charge(ticket, contract):
    if contract["included_service_scope"] == "FULL":
        return 0
    hours = ticket["labor_hours"]
    whole = int(math.ceil(float(hours)))
    if whole < 0:
        whole = 0
    return whole * contract["labor_rate_cents_per_hour"]


# ------------------------------------------------- billing_statement_charge ---
def _select_tier(contract_id, page_class, volume):
    """Returns (tier_index, rate).  Raises ERR_TIER_COVERAGE_GAP on a gap."""
    rows = derive.tier_rows(contract_id, page_class)
    if not rows:
        return 0, 0
    if volume == 0:
        for row in rows:
            if row["tier_index"] == 1:
                return row["tier_index"], row["rate_micro_dollars_per_page"]
        return 0, 0
    for row in rows:
        upper = row["to_page"]
        if row["from_page"] <= volume and (upper is None or volume <= upper):
            return row["tier_index"], row["rate_micro_dollars_per_page"]
    fail("ERR_TIER_COVERAGE_GAP",
         "No %s rate-card band contains a contract volume of %d pages." % (page_class, volume))


def _period_days(period):
    seconds = (period["period_end"] - period["period_start"]).total_seconds()
    return int(math.ceil(seconds / float(SECONDS_PER_DAY)))


def _elapsed_days(period, clock):
    upper = clock if clock < period["period_end"] else period["period_end"]
    seconds = (upper - period["period_start"]).total_seconds()
    days = int(math.floor(seconds / float(SECONDS_PER_DAY)))
    return max(1, days)


def price_statement(period, contract, variant, clock):
    """The six-step pricing algorithm; returns (figures, line_specs)."""
    reads = [r for r in derive.period_reads(period["id"]) if r["status"] == "ACCEPTED"]
    per_device = {}
    for read in reads:
        bucket = per_device.setdefault(read["device_id"], [0, 0])
        bucket[0] += read["mono_delta"]
        bucket[1] += read["color_delta"]

    devices = []
    for device_id in per_device:
        device = db.devices.get(device_id)
        if device is not None:
            devices.append(device)
    devices.sort(key=lambda d: (d["created_at"], d["_seq"]))

    if variant == "PROVISIONAL":
        period_days = _period_days(period)
        elapsed_days = _elapsed_days(period, clock)

    billable = {}
    for device in devices:
        actual_mono, actual_color = per_device[device["id"]]
        if variant == "FINAL":
            billable[device["id"]] = (actual_mono, actual_color)
        else:
            scale_num = Decimal(period_days)
            scale_den = Decimal(elapsed_days)
            billable[device["id"]] = (
                round_half_up(Decimal(actual_mono) * scale_num / scale_den),
                round_half_up(Decimal(actual_color) * scale_num / scale_den),
            )

    volume_mono = sum(billable[d["id"]][0] for d in devices)
    volume_color = sum(billable[d["id"]][1] for d in devices)

    mono_tier_index, mono_rate = _select_tier(contract["id"], "MONO", volume_mono)
    color_tier_index, color_rate = _select_tier(contract["id"], "COLOR", volume_color)

    line_specs = []
    usage_subtotal = 0
    for device in devices:
        pages_mono, pages_color = billable[device["id"]]
        for page_class, pages, rate in (("MONO", pages_mono, mono_rate),
                                        ("COLOR", pages_color, color_rate)):
            if pages <= 0:
                continue
            amount = micro_to_cents(pages, rate)
            line_specs.append({
                "device_id": device["id"],
                "page_class": page_class,
                "pages": pages,
                "rate_micro_dollars_per_page": rate,
                "amount_cents": amount,
            })
            usage_subtotal += amount

    shortfall_mono = max(0, contract["minimum_mono_pages_per_period"] - volume_mono)
    shortfall_color = max(0, contract["minimum_color_pages_per_period"] - volume_color)
    shortfall_cents = (micro_to_cents(shortfall_mono, derive.tier1_rate(contract["id"], "MONO"))
                       + micro_to_cents(shortfall_color, derive.tier1_rate(contract["id"], "COLOR")))

    tickets = []
    for ticket in db.sorted_rows("tickets"):
        if ticket["status"] != "RESOLVED" or ticket["responded_at"] is None:
            continue
        device = db.devices.get(ticket["device_id"])
        if device is None or device["contract_id"] != contract["id"]:
            continue
        if period["period_start"] <= ticket["responded_at"] < period["period_end"]:
            tickets.append(ticket)

    if contract["included_service_scope"] == "FULL":
        service_labor_cents = 0
    else:
        service_labor_cents = sum(t["labor_cents"] for t in tickets)
    sla_credit_cents = sum(t["sla_credit_cents"] for t in tickets)

    waste_penalty_cents = 0
    if variant == "FINAL":
        count = 0
        for order in db.orders.values():
            if not order["waste_flagged"] or order["status"] == "CANCELLED":
                continue
            device = db.devices.get(order["device_id"])
            if device is None or device["contract_id"] != contract["id"]:
                continue
            if period["period_start"] <= order["created_at"] < period["period_end"]:
                count += 1
        waste_penalty_cents = WASTE_PENALTY_CENTS_PER_EVENT * count

    total = (usage_subtotal + shortfall_cents + service_labor_cents
             + waste_penalty_cents - sla_credit_cents)

    figures = {
        "mono_pages_billed": volume_mono,
        "color_pages_billed": volume_color,
        "mono_tier_index": mono_tier_index,
        "color_tier_index": color_tier_index,
        "mono_rate_micro_dollars_per_page": mono_rate,
        "color_rate_micro_dollars_per_page": color_rate,
        "usage_subtotal_cents": usage_subtotal,
        "shortfall_pages": shortfall_mono + shortfall_color,
        "shortfall_cents": shortfall_cents,
        "service_labor_cents": service_labor_cents,
        "sla_credit_cents": sla_credit_cents,
        "waste_penalty_cents": waste_penalty_cents,
        "total_cents": total,
    }
    return figures, line_specs


# --------------------------------------------------------- settlement_amount ---
def settlement_amount(removal, contract, clock):
    unbilled_mono = 0
    unbilled_color = 0
    for read in db.meter_reads.values():
        if read["status"] != "ACCEPTED":
            continue
        device = db.devices.get(read["device_id"])
        if device is None or device["contract_id"] != contract["id"]:
            continue
        period = db.periods.get(read["billing_period_id"])
        if period is None or period["status"] not in ("OPEN", "SWEPT", "PROVISIONAL"):
            continue
        unbilled_mono += read["mono_delta"]
        unbilled_color += read["color_delta"]

    unbilled_charge = (micro_to_cents(unbilled_mono, derive.tier1_rate(contract["id"], "MONO"))
                       + micro_to_cents(unbilled_color, derive.tier1_rate(contract["id"], "COLOR")))

    term_end = add_months(contract["created_at"], contract["term_months"])
    if clock < term_end:
        early_fee = contract["early_termination_fee_cents"]
    else:
        early_fee = 0

    device_count = derive.removal_device_count(removal["id"])
    if removal["sanitization_method"] == "PHYSICAL_DESTRUCTION":
        residual = 0
    else:
        residual = RESIDUAL_CREDIT_PER_DEVICE_CENTS * device_count

    gross = unbilled_charge + early_fee - residual

    base = SANITIZATION_FEE_PER_DEVICE_CENTS * device_count
    if gross >= SANITIZATION_DISCOUNT_THRESHOLD_CENTS:
        discount = SANITIZATION_DISCOUNT_PCT
    else:
        discount = Decimal("0.00")
    fee = round_half_up(Decimal(base) * (Decimal(1) - discount))

    return {
        "unbilled_pages_charge_cents": unbilled_charge,
        "early_termination_fee_applied_cents": early_fee,
        "device_residual_credit_cents": residual,
        "gross_settlement_cents": gross,
        "sanitization_fee_cents": fee,
        "net_settlement_cents": gross + fee,
    }


# ---------------------------------------------------- review computations -----
def review_fleet(contract_id):
    """PLACED / NETWORKED / ACTIVE / SERVICE_HOLD devices, created_at ASC."""
    rows = [d for d in derive.contract_devices(contract_id)
            if d["lifecycle_state"] in derive.FLEET_STATES]
    rows.sort(key=lambda d: (d["created_at"], d["_seq"]))
    return rows


def _realized_lines(period):
    """device_id -> [pages, amount_cents] from the period's FINAL statement."""
    result = {}
    if period is None:
        return result
    statement = derive.period_statement(period["id"], "FINAL")
    if statement is None:
        return result
    for line in derive.statement_lines(statement["id"]):
        bucket = result.setdefault(line["device_id"], [0, 0])
        bucket[0] += line["pages"]
        bucket[1] += line["amount_cents"]
    return result


def tco_savings(contract, fleet):
    mono_rate = derive.tier1_rate(contract["id"], "MONO")
    color_rate = derive.tier1_rate(contract["id"], "COLOR")

    baseline_savings = 0
    for device in fleet:
        pages = device["assessed_monthly_mono_pages"] + device["assessed_monthly_color_pages"]
        baseline_cost = (micro_to_cents(pages, device["baseline_cost_micro_dollars_per_page"])
                         + device["baseline_overhead_cents_per_month"])
        micro = (device["assessed_monthly_mono_pages"] * mono_rate
                 + device["assessed_monthly_color_pages"] * color_rate)
        mps_cost = round_half_up(Decimal(micro) / Decimal(MICRO_DOLLARS_PER_CENT))
        baseline_savings += baseline_cost - mps_cost

    period = derive.latest_closed_period(contract["id"])
    if period is None:
        return baseline_savings, 0

    realized = _realized_lines(period)
    realized_savings = 0
    for device in fleet:
        pages, billed = realized.get(device["id"], (0, 0))
        realized_baseline = (micro_to_cents(pages, device["baseline_cost_micro_dollars_per_page"])
                             + device["baseline_overhead_cents_per_month"])
        realized_savings += realized_baseline - billed
    return baseline_savings, realized_savings


def right_sizing(contract, fleet):
    """Returns device_id -> action plus the four tallies."""
    period = derive.latest_closed_period(contract["id"])
    actions = {}
    if period is None:
        for device in fleet:
            actions[device["id"]] = "RETAIN"
    else:
        realized = _realized_lines(period)
        for device in fleet:
            pages = realized.get(device["id"], (0, 0))[0]
            duty = device["rated_monthly_duty_cycle"]
            if pages * 100 <= duty * UTIL_CONSOLIDATE_MAX_PCT:
                actions[device["id"]] = "CONSOLIDATE"
            elif pages * 100 <= duty * UTIL_DOWNGRADE_MAX_PCT:
                actions[device["id"]] = "DOWNGRADE"
            elif pages * 100 >= duty * UTIL_UPGRADE_MIN_PCT:
                actions[device["id"]] = "UPGRADE"
            else:
                actions[device["id"]] = "RETAIN"
    tallies = {"RETAIN": 0, "DOWNGRADE": 0, "UPGRADE": 0, "CONSOLIDATE": 0}
    for action in actions.values():
        tallies[action] += 1
    return actions, tallies


def volume_trend(contract_id):
    periods = derive.closed_periods_desc(contract_id)
    if len(periods) < 2:
        return 0.0

    def volume(period):
        statement = derive.period_statement(period["id"], "FINAL")
        if statement is None:
            return 0
        return statement["mono_pages_billed"] + statement["color_pages_billed"]

    current = volume(periods[0])
    prior = volume(periods[1])
    if prior == 0:
        return 0.0
    pct = round_half_up_2(Decimal(current - prior) * Decimal(100) / Decimal(prior))
    return float(pct)
