"""Monetary calculations: proration, tax, late fee, bill totals, etc."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

from clock import parse_iso


def round_half_up(value) -> int:
    """Round a numeric value to the nearest integer using ROUND_HALF_UP.

    Accepts ints/floats/Decimals. Negative numbers: ROUND_HALF_UP rounds
    half away from zero; we apply it to the signed value so that
    -2.5 -> -3 and 2.5 -> 3, which matches "round half up to integer cents"
    when interpreted on the signed result.
    """
    if isinstance(value, int):
        return value
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def billing_cycle_period(billing_cycle: str):
    """Returns a function timedelta-ish for the given billing_cycle.

    The PRD states 'one calendar month for MONTHLY, three for QUARTERLY, twelve
    for ANNUAL'.  We approximate calendar months by adding the corresponding
    number of months while preserving day-of-month when possible. Since cycle
    boundaries are stored as datetimes, we compute via day-counts based on
    that interval, but the cycle length in days is just (cycle_end - cycle_start).days.
    """
    return billing_cycle


def add_billing_cycle(start_dt, billing_cycle: str):
    """Return start_dt + cycle period as datetime.

    Add 1 calendar month for MONTHLY, 3 for QUARTERLY, 12 for ANNUAL.
    Preserves day-of-month with clamping (e.g. Jan 31 + 1 month = Feb 28/29).
    """
    months_by_cycle = {"MONTHLY": 1, "QUARTERLY": 3, "ANNUAL": 12}
    months = months_by_cycle[billing_cycle]
    year = start_dt.year + (start_dt.month - 1 + months) // 12
    month = (start_dt.month - 1 + months) % 12 + 1
    # Clamp day to last day of month
    import calendar
    last_day = calendar.monthrange(year, month)[1]
    day = min(start_dt.day, last_day)
    return start_dt.replace(year=year, month=month, day=day)


def cycle_days(cycle_start_iso: str, cycle_end_iso: str) -> int:
    """Whole days between cycle_start and cycle_end."""
    cs = parse_iso(cycle_start_iso)
    ce = parse_iso(cycle_end_iso)
    delta = ce - cs
    return delta.days


def elapsed_days(cycle_start_iso: str, now_dt) -> int:
    """floor((now - cycle_start) in days)."""
    cs = parse_iso(cycle_start_iso)
    delta = now_dt - cs
    return delta.days  # timedelta.days floors toward negative infinity for negative durations; OK


def proration_amount(current_base_cents: int, target_base_cents: int,
                     cycle_start_iso: str, cycle_end_iso: str, now_dt) -> int:
    """Compute prorated_charge_cents per the proration_amount calculation.

    new_per_day - old_per_day, multiplied by remaining_days, rounded HALF_UP
    at the final step.
    For UPGRADE the result is positive; for DOWNGRADE_IMMEDIATE_REFUND it is
    naturally negative.
    """
    cd = cycle_days(cycle_start_iso, cycle_end_iso)
    if cd <= 0:
        return 0
    ed = elapsed_days(cycle_start_iso, now_dt)
    if ed < 0:
        ed = 0
    if ed > cd:
        ed = cd
    remaining_days = cd - ed
    old_per_day = Decimal(current_base_cents) / Decimal(cd)
    new_per_day = Decimal(target_base_cents) / Decimal(cd)
    unrounded = (new_per_day - old_per_day) * Decimal(remaining_days)
    return round_half_up(unrounded)


def compute_tiered_lines(quota_consumed: dict, package: dict):
    """Walk tiered brackets for TIERED|HYBRID packages.

    Returns (tiered_lines list, residuals dict per metric of leftover units
    not absorbed by brackets).

    Each tiered_line: { 'kind': 'TIERED', 'metric': m,
                        'quantity': units, 'unit_price_cents': p,
                        'line_total_cents': units*p,
                        'description': ... }
    """
    tiered_brackets = package.get("tiered_brackets") or []
    included = package.get("included_quotas") or {}
    # Group brackets by metric, preserving order.
    grouped = {}
    for b in tiered_brackets:
        grouped.setdefault(b["metric"], []).append(b)

    lines = []
    residuals = {}
    # Walk every metric that has any consumption
    for metric, consumed_qty in quota_consumed.items():
        inc = int(included.get(metric, 0))
        excess = int(consumed_qty) - inc
        if excess <= 0:
            residuals[metric] = 0
            continue
        if metric not in grouped:
            # No tier brackets for this metric — leftover stays for overage
            residuals[metric] = excess
            continue
        remaining = excess
        # Track absolute capacity consumed so far for this metric
        cumulative_capacity = 0
        for bracket in grouped[metric]:
            upper = bracket.get("upper_bound")
            unit_price = int(bracket["unit_price_cents"])
            if upper is None:
                bracket_capacity = remaining  # treat as infinite; take everything
            else:
                # Total absolute capacity (units above included) for this bracket
                bracket_top_units_above_included = int(upper) - inc - cumulative_capacity
                if bracket_top_units_above_included < 0:
                    bracket_top_units_above_included = 0
                bracket_capacity = bracket_top_units_above_included
            take = min(remaining, bracket_capacity) if bracket_capacity > 0 else 0
            if take > 0:
                lines.append({
                    "kind": "TIERED",
                    "metric": metric,
                    "description": f"Tiered usage {metric} bracket",
                    "quantity": take,
                    "unit_price_cents": unit_price,
                    "line_total_cents": take * unit_price,
                })
                remaining -= take
                cumulative_capacity += take
            if remaining <= 0:
                break
        residuals[metric] = max(remaining, 0)
    return lines, residuals


def compute_overage_lines(quota_consumed: dict, package: dict, tier_residuals: dict):
    """For metrics in package.overage_rates apply flat rate to uncovered units."""
    overage_rates = package.get("overage_rates") or {}
    included = package.get("included_quotas") or {}
    lines = []
    for metric, rate in overage_rates.items():
        rate_cents = int(rate)
        # Determine uncovered units for this metric
        if metric in tier_residuals:
            uncovered = tier_residuals[metric]
        else:
            consumed_qty = int(quota_consumed.get(metric, 0))
            inc = int(included.get(metric, 0))
            uncovered = max(consumed_qty - inc, 0)
        if uncovered <= 0:
            continue
        lines.append({
            "kind": "OVERAGE",
            "metric": metric,
            "description": f"Overage {metric}",
            "quantity": uncovered,
            "unit_price_cents": rate_cents,
            "line_total_cents": uncovered * rate_cents,
        })
    return lines


def compute_addon_lines(package: dict, selected_addons: list):
    """Add-on line items based on selected_addons code list."""
    catalog = {a["code"]: int(a.get("monthly_price_cents", 0))
               for a in (package.get("addons") or [])}
    lines = []
    for code in selected_addons or []:
        if code in catalog:
            price = catalog[code]
            lines.append({
                "kind": "ADDON",
                "addon_code": code,
                "description": f"Add-on {code}",
                "quantity": 1,
                "unit_price_cents": price,
                "line_total_cents": price,
            })
    return lines


def tax_calculation(lines: list, discount_cents: int, jurisdiction: dict) -> int:
    """tax_cents per Jurisdiction.rounding_mode."""
    rate_bps = int(jurisdiction["tax_rate_bps"])
    mode = jurisdiction["rounding_mode"]
    if mode == "PER_LINE":
        total_line_tax = 0
        for line in lines:
            line_tax = round_half_up(
                Decimal(int(line["line_total_cents"])) * Decimal(rate_bps) / Decimal(10000)
            )
            total_line_tax += line_tax
        disc_tax = round_half_up(
            Decimal(int(discount_cents)) * Decimal(rate_bps) / Decimal(10000)
        )
        return total_line_tax - disc_tax
    elif mode == "TOTAL":
        subtotal = sum(int(line["line_total_cents"]) for line in lines)
        taxable_base = subtotal - int(discount_cents)
        if taxable_base < 0:
            taxable_base = 0
        return round_half_up(Decimal(taxable_base) * Decimal(rate_bps) / Decimal(10000))
    else:
        return 0


def late_fee_accrual(amount_due_cents: int, due_at_iso: str, now_dt) -> int:
    """Compute late_fee_cents per the late_fee_accrual rule."""
    if amount_due_cents <= 0:
        return 0
    due_at = parse_iso(due_at_iso)
    delta = now_dt - due_at
    days_past = delta.days  # timedelta.days floors toward negative infinity
    if days_past <= 0:
        return 0
    if days_past <= 30:
        bps = 100
    elif days_past <= 60:
        bps = 250
    else:
        bps = 500
    return round_half_up(Decimal(amount_due_cents) * Decimal(bps) / Decimal(10000))
