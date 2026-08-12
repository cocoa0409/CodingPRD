"""Daily-report pricing (SCAFFOLD 1.3 shift_labor_cost, daily_report_total,
overhead_allocation; PRD 3.8).

Pinned rounding order: round each line half-up to integer cents exactly once,
BEFORE the cap; labor_cost_cents sums the rounded per-line costs; the
overhead tier is keyed on the turnaround's reported cost EXCLUDING the
candidate report.
"""
from decimal import ROUND_HALF_UP, Decimal

BASE_RATE_CENTS = 8500
OT1_MULT = Decimal("1.5")
OT2_MULT = Decimal("2.0")
NIGHT_MULT = Decimal("1.20")
HAZARD_MULT = Decimal("1.15")
DAILY_CAP_CENTS = 250000

OVERHEAD_TIER_THRESHOLD_CENTS = 200000
OVERHEAD_PCT = {"LOW": Decimal("0.10"), "HIGH": Decimal("0.15")}


def _d(value):
    return Decimal(str(value))


def line_cost_cents(hours, shift_type, hazard_flag):
    """shift_labor_cost: tiered overtime, NIGHT then HAZARD multipliers,
    round half-up to cents once, then cap."""
    h = _d(hours)
    regular_hours = min(h, Decimal(8))
    ot1_hours = min(max(h - Decimal(8), Decimal(0)), Decimal(4))
    ot2_hours = max(h - Decimal(12), Decimal(0))
    base = (regular_hours * BASE_RATE_CENTS
            + ot1_hours * BASE_RATE_CENTS * OT1_MULT
            + ot2_hours * BASE_RATE_CENTS * OT2_MULT)
    if shift_type == "NIGHT":
        base = base * NIGHT_MULT
    if hazard_flag:
        base = base * HAZARD_MULT
    line_cost = int(base.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return min(line_cost, DAILY_CAP_CENTS)


def price_report(report, shift_type_for):
    """Compute line_costs_cents / labor_cost_cents / overhead_cents /
    total_cost_cents for a report being submitted.

    shift_type_for: callable resolving a line's shift_id -> shift_type.
    tier_base: turnaround reported_cost_cents EXCLUDING this report (sum of
    total_cost_cents over the turnaround's OTHER APPROVED reports).
    """
    line_costs = []
    for line in report["lines"]:
        line_costs.append(line_cost_cents(
            line["hours"], shift_type_for(line["shift_id"]), line["hazard_flag"]))
    labor = sum(line_costs)
    return line_costs, labor


def overhead_cents(labor_cost_cents, tier_base):
    tier = "LOW" if tier_base < OVERHEAD_TIER_THRESHOLD_CENTS else "HIGH"
    return int((_d(labor_cost_cents) * OVERHEAD_PCT[tier]).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))
