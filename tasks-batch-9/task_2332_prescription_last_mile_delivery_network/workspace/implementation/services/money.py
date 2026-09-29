"""Pricing: the six-line bill, the per-line member share and the payer-mix waterfall."""

from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from constants import (
    ABSORB_TIER1_CENTS,
    ABSORB_TIER2_CENTS,
    ABSORB_TIER2_FLOOR_CENTS,
    ABSORB_TIER3_CENTS,
    ABSORB_TIER3_FLOOR_CENTS,
    COLD_CLASSES,
    CONTROLLED_CLASSES,
    REATTEMPT_SURCHARGE_CENTS,
    REATTEMPT_SURCHARGE_MAX_UNITS,
)
from db import db, new_row, sort_rows
from errors import api_error
from services import derive


def round_half_up_cents(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_miles(distance):
    return int(Decimal(distance).quantize(Decimal("1"), rounding=ROUND_CEILING))


def billable_attempts(variant, delivery):
    if variant == "PROVISIONAL":
        return 1
    return max(derive.attempt_count(delivery), 1)


def build_lines(zone, window, handling_class, attempts):
    """The ordered six-line vector; zeros are retained in position."""
    base = zone["base_fee_cents"]
    mileage = zone["per_mile_cents"] * ceil_miles(zone["distance_band_miles"])
    cold = zone["cold_pack_fee_cents"] * attempts if handling_class in COLD_CLASSES else 0
    controlled = zone["controlled_handling_fee_cents"] if handling_class in CONTROLLED_CLASSES else 0
    after_hours = zone["after_hours_fee_cents"] if window["is_after_hours"] else 0
    units = min(max(attempts - 1, 0), REATTEMPT_SURCHARGE_MAX_UNITS)
    reattempt = REATTEMPT_SURCHARGE_CENTS * units
    return [base, mileage, cold, controlled, after_hours, reattempt]


def patient_gross_share(lines, cost_share_pct):
    """Rounded half up once per line item, then summed — never sum-then-round."""
    total = 0
    for line in lines:
        total += round_half_up_cents(Decimal(line) * cost_share_pct)
    return total


def absorption_tier(pre_absorption_cents):
    if pre_absorption_cents >= ABSORB_TIER3_FLOOR_CENTS:
        return ABSORB_TIER3_CENTS
    if pre_absorption_cents >= ABSORB_TIER2_FLOOR_CENTS:
        return ABSORB_TIER2_CENTS
    if pre_absorption_cents >= 1:
        return ABSORB_TIER1_CENTS
    return 0


def effective_remaining(grant, released=None):
    remaining = derive.grant_remaining_cents(grant)
    if released:
        remaining += released.get(grant["id"], 0)
    return remaining


def select_grant(order, window, released=None):
    """Rung 19. Deterministic: lowest created_at among the plan's ACTIVE pools."""
    plan_id = order.get("health_plan_id")
    if not plan_id:
        return None
    year = window["window_start"].year
    candidates = [g for g in db.plan_grants.values()
                  if g["health_plan_id"] == plan_id
                  and g["benefit_year"] == year
                  and effective_remaining(g, released) > 0]
    if not candidates:
        raise api_error("ERR_GRANT_NOT_APPLICABLE",
                        "The order's health plan has no ACTIVE grant pool for the "
                        "window's benefit year.")
    return sort_rows(candidates)[0]


def plan_allocation(order, window, zone, handling_class, variant, delivery,
                    grant, released=None):
    """Compute every allocation figure without mutating anything (rung 40 may reject)."""
    attempts = billable_attempts(variant, delivery) if delivery is not None else 1
    lines = build_lines(zone, window, handling_class, attempts)
    subtotal = sum(lines)

    plan = db.health_plans.get(order.get("health_plan_id")) if order.get("health_plan_id") else None
    cost_share_pct = plan["member_cost_share_pct"] if plan else Decimal("1.00")
    gross = patient_gross_share(lines, cost_share_pct)

    if grant is None:
        plan_grant_cents = 0
        grant_id = None
    else:
        eligible = min(gross, grant["per_delivery_cap_cents"],
                       effective_remaining(grant, released))
        if plan is not None and plan["payer_type"] == "MEDICAID" and eligible < gross:
            raise api_error("ERR_GRANT_COVERAGE_INSUFFICIENT",
                            "A MEDICAID member may not be billed any residue; the "
                            "grant cannot fully absorb the member share.")
        plan_grant_cents = eligible
        grant_id = grant["id"]

    pre_absorption = gross - plan_grant_cents
    tier = absorption_tier(pre_absorption)
    absorbed = min(tier, pre_absorption)
    patient_payable = pre_absorption - absorbed
    pharmacy_payable = subtotal - plan_grant_cents - patient_payable

    return {
        "plan_grant_id": grant_id,
        "variant": variant,
        "status": "ACTIVE",
        "base_line_cents": lines[0],
        "mileage_line_cents": lines[1],
        "cold_pack_line_cents": lines[2],
        "controlled_line_cents": lines[3],
        "after_hours_line_cents": lines[4],
        "reattempt_line_cents": lines[5],
        "fee_subtotal_cents": subtotal,
        "cost_share_pct_applied": cost_share_pct,
        "patient_gross_share_cents": gross,
        "plan_grant_cents": plan_grant_cents,
        "absorption_tier_cents": tier,
        "pharmacy_absorption_cents": absorbed,
        "patient_payable_cents": patient_payable,
        "pharmacy_payable_cents": pharmacy_payable,
    }


def write_allocation(delivery, values):
    allocation = new_row()
    allocation["delivery_id"] = delivery["id"]
    allocation.update(values)
    db.fee_allocations[allocation["id"]] = allocation
    return allocation
