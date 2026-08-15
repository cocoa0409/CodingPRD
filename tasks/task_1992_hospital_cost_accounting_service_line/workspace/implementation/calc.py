"""Business calculations (PRD §3.4-§3.6, SCAFFOLD §1.3).

All money is Decimal; every computed monetary figure is round-half-up to
exactly two decimal places. The case-costing pipeline's evaluation order is
pinned and must not be rearranged: per-line round BEFORE summation, then a
single-step proportional overhead distribution (floor shares + remainder).
"""

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from db import store, touch

TWO = Decimal("0.01")
ZERO = Decimal("0")

# Flex-budget volume tiers (PRD §3.5)
TIER_1_MAX = Decimal("6000")
TIER_1_RATE = Decimal("0.20")
TIER_2_MAX = Decimal("20000")
TIER_2_RATE = Decimal("0.30")
TIER_3_RATE = Decimal("0.35")

# Refresh governance gates (PRD §3.6)
VARIANCE_THRESHOLD_PCT = Decimal("3.00")
MIN_DATA_QUALITY = Decimal("80.00")


def r2(d):
    """Round-half-up to exactly two decimal places."""
    return Decimal(d).quantize(TWO, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def case_activity_lines(case_id):
    return sorted(
        (l for l in store.activity_lines.values() if l["case_id"] == case_id),
        key=lambda l: l["_seq"],
    )


def case_implants(case_id):
    return sorted(
        (i for i in store.implants.values() if i["case_id"] == case_id),
        key=lambda i: i["_seq"],
    )


def case_supply_lines(case_id):
    return sorted(
        (s for s in store.supply_lines.values() if s["case_id"] == case_id),
        key=lambda s: s["_seq"],
    )


# ---------------------------------------------------------------------------
# §3.4 The pinned costing pipeline
# ---------------------------------------------------------------------------

def price_case(case, model):
    """(Re)compute the case's line allocations and totals in place.

    Steps 1-7 are evaluated in exactly the PRD's pinned order.
    """
    lines = case_activity_lines(case["id"])
    non_overhead = [l for l in lines if not l["is_overhead_line"]]

    rate_factor = model["rate_factor"]

    # Reset all lines (matters on refresh re-pricing).
    for line in lines:
        line["allocated_amount"] = ZERO
        line["_overhead_amount"] = ZERO

    # Step 1 — price each non-overhead line; per-line round BEFORE summation.
    for line in non_overhead:
        center = store.cost_centers[line["cost_center_id"]]
        if center["capacity_measure"] == "MINUTES":
            capacity_rate = center["allocated_cost"] / Decimal(
                center["practical_capacity_minutes"])
        elif center["capacity_measure"] == "RVU":
            capacity_rate = center["allocated_cost"] / center["total_rvu"]
        else:
            capacity_rate = ZERO
        raw = line["quantity"] * capacity_rate * rate_factor
        line["allocated_amount"] = r2(raw)

    # Step 2 — total activity is the sum of ALREADY-rounded line amounts.
    total_activity = sum((l["allocated_amount"] for l in non_overhead), ZERO)

    # Step 3 — overhead pool, single-step proportional distribution.
    pool_center = store.cost_centers[model["overhead_cost_center_id"]]
    pool = pool_center["allocated_cost"]
    if non_overhead and total_activity > ZERO:
        shares = []
        for line in non_overhead:  # created_at ASC (creation order)
            raw_share = pool * line["allocated_amount"] / total_activity
            floor_share = raw_share.quantize(TWO, rounding=ROUND_DOWN)
            shares.append((line, raw_share, floor_share))
            line["_overhead_amount"] = floor_share
        remainder = r2(pool) - sum((s[2] for s in shares), ZERO)
        # Remainder to the largest raw share; tie-break larger allocated_amount,
        # then earliest created_at.
        chosen = max(
            shares,
            key=lambda s: (s[1], s[0]["allocated_amount"], -s[0]["_seq"]),
        )
        chosen[0]["_overhead_amount"] = chosen[2] + remainder

    # Step 4 — total indirect = activity total + full overhead pool.
    total_indirect = r2(total_activity + pool)

    # Step 5 — direct = line base + implants + supplies.
    service_line = store.service_lines[case["service_line_id"]]
    implant_total = sum(
        (i["unit_cost"] * Decimal(i["quantity"]) for i in case_implants(case["id"])),
        ZERO,
    )
    supply_total = sum(
        (s["unit_cost"] * Decimal(s["quantity"]) for s in case_supply_lines(case["id"])),
        ZERO,
    )
    total_direct = r2(service_line["base_direct_cost"] + implant_total + supply_total)

    # Steps 6-7 — totals and margin.
    total_cost = r2(total_direct + total_indirect)
    margin = r2(case["expected_reimbursement"] - total_cost)

    case["_activity_total"] = r2(total_activity)
    case["_overhead_pool_amount"] = r2(pool)
    case["total_direct_cost"] = total_direct
    case["total_indirect_allocated"] = total_indirect
    case["total_cost"] = total_cost
    case["margin"] = margin


# ---------------------------------------------------------------------------
# §2.8 Ledger synchronization — service-line rollups
# ---------------------------------------------------------------------------

def recompute_service_line_rollup(sl):
    """Eager ledger sync: rollups over the line's POSTED/LOCKED cases.

    PRD §2.8: total_direct_cost is the line's base_direct_cost plus the sum of
    total_indirect_allocated across the line's posted cases (VOIDED cases are
    excluded, so with no live cases the rollup returns to its zero baseline);
    revenue is the sum of expected reimbursements.
    """
    cases = [
        c for c in store.cases.values()
        if c["service_line_id"] == sl["id"] and c["status"] in ("POSTED", "LOCKED")
    ]
    total_direct = sum(
        (sl["base_direct_cost"] + c["total_indirect_allocated"] for c in cases), ZERO)
    total_revenue = sum((c["expected_reimbursement"] for c in cases), ZERO)
    contribution = total_revenue - total_direct
    new_vals = (r2(total_direct), r2(total_revenue), r2(contribution))
    old_vals = (sl["total_direct_cost"], sl["total_revenue"], sl["contribution_margin"])
    if new_vals != old_vals:
        sl["total_direct_cost"], sl["total_revenue"], sl["contribution_margin"] = new_vals
        touch(sl)


# ---------------------------------------------------------------------------
# §3.5 Volume-flexed budget periods
# ---------------------------------------------------------------------------

def budget_period_actual_volume(bp):
    """Sum of pre-overhead activity totals of POSTED/LOCKED cases in this
    period priced by any model drawing on this overhead pool."""
    total = ZERO
    for c in store.cases.values():
        if c["status"] not in ("POSTED", "LOCKED"):
            continue
        if c["period"] != bp["period"]:
            continue
        model = store.cost_models.get(c["cost_model_id"])
        if model is None or model["overhead_cost_center_id"] != bp["cost_center_id"]:
            continue
        total += c["_activity_total"]
    return r2(total)


def flex_tier_rate(volume):
    if volume <= TIER_1_MAX:
        return TIER_1_RATE
    if volume <= TIER_2_MAX:
        return TIER_2_RATE
    return TIER_3_RATE


def recompute_budget_period(bp):
    """Live recompute while OPEN; LOCKED periods are frozen."""
    if bp["status"] == "LOCKED":
        return
    volume = budget_period_actual_volume(bp)
    flexed = r2(flex_tier_rate(volume) * volume)
    variance = r2(flexed - bp["static_budget_amount"])
    if variance < ZERO:
        direction = "FAVORABLE"
    elif variance == ZERO:
        direction = "ON_BUDGET"
    else:
        direction = "UNFAVORABLE"
    new_vals = (volume, flexed, variance, direction)
    old_vals = (
        bp["actual_indirect_volume"],
        bp["flexed_overhead"],
        bp["variance_amount"],
        bp["variance_direction"],
    )
    if new_vals != old_vals:
        bp["actual_indirect_volume"] = volume
        bp["flexed_overhead"] = flexed
        bp["variance_amount"] = variance
        bp["variance_direction"] = direction
        touch(bp)


def sync_ledgers_for_case(case):
    """Hop-1 + hop-2 cascade for case post/void."""
    sl = store.service_lines.get(case["service_line_id"])
    if sl is not None:
        recompute_service_line_rollup(sl)
    for bp in store.budget_periods.values():
        recompute_budget_period(bp)


# ---------------------------------------------------------------------------
# §3.6 Refresh variance report (computed at proposal time)
# ---------------------------------------------------------------------------

def _center_rate(allocated_cost, measure, pcm, total_rvu):
    if measure == "MINUTES":
        return allocated_cost / Decimal(pcm)
    if measure == "RVU":
        return allocated_cost / total_rvu
    # NONE-measured (overhead) centers have no denominator: rate == pool cost.
    return allocated_cost


def build_variance_report(proposed_rates):
    report = []
    for entry in proposed_rates:
        center = store.cost_centers[entry["cost_center_id"]]
        measure = center["capacity_measure"]
        current_rate = _center_rate(
            center["allocated_cost"], measure,
            center.get("practical_capacity_minutes"), center.get("total_rvu"))
        proposed_rate = _center_rate(
            entry["allocated_cost"], measure,
            entry.get("practical_capacity_minutes"), entry.get("total_rvu"))
        if current_rate == ZERO:
            delta_pct = ZERO if proposed_rate == ZERO else Decimal("100")
        else:
            delta_pct = r2((proposed_rate - current_rate) / current_rate * Decimal("100"))
        report.append({
            "cost_center_id": center["id"],
            "current_rate": float(r2(current_rate)),
            "proposed_rate": float(r2(proposed_rate)),
            "delta_pct": float(delta_pct),
        })
    return report


# ---------------------------------------------------------------------------
# §3.6 Refresh application — depth-3 cascade
# ---------------------------------------------------------------------------

def apply_refresh(refresh):
    model = store.cost_models[refresh["model_id"]]

    # Hop 1 — update each referenced center's rates to the proposed values.
    for entry in refresh["_proposed_rates"]:
        center = store.cost_centers[entry["cost_center_id"]]
        changed = False
        if center["allocated_cost"] != entry["allocated_cost"]:
            center["allocated_cost"] = entry["allocated_cost"]
            changed = True
        if center["capacity_measure"] == "MINUTES":
            if center.get("practical_capacity_minutes") != entry.get("practical_capacity_minutes"):
                center["practical_capacity_minutes"] = entry.get("practical_capacity_minutes")
                changed = True
        elif center["capacity_measure"] == "RVU":
            if center.get("total_rvu") != entry.get("total_rvu"):
                center["total_rvu"] = entry.get("total_rvu")
                changed = True
        if changed:
            touch(center)

    # Model version advances; recomputed cases are restamped with it.
    touch(model)
    new_version = model["version"]

    # Hop 2 — recompute every POSTED case priced by this model whose period is
    # on or after the refresh period.
    affected_lines = set()
    for case in store.cases.values():
        if case["cost_model_id"] != model["id"]:
            continue
        if case["status"] != "POSTED":
            continue
        if case["period"] < refresh["period"]:
            continue
        price_case(case, model)
        case["version_at_post"] = new_version
        touch(case)
        affected_lines.add(case["service_line_id"])

    # Hop 2 ledger sync — refresh each recomputed case's service-line rollups.
    for sl_id in affected_lines:
        sl = store.service_lines.get(sl_id)
        if sl is not None:
            recompute_service_line_rollup(sl)

    # Hop 3 — recompute every affected (open) budget period.
    for bp in store.budget_periods.values():
        recompute_budget_period(bp)
