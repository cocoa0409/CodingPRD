"""Every arithmetic rule of PRD §2.7 and SCAFFOLD §1.3.

Rounding is round-half-up throughout and the number of decimal places is fixed
per quantity, never chosen by the implementation.
"""

from decimal import Decimal, ROUND_HALF_UP

# ---- constants (SCAFFOLD §1.3) ---------------------------------------------
TRAINING_VALID_DAYS = 365
AGREEMENT_TERMINATION_GRACE_DAYS = 90
POVERTY_WEIGHT = Decimal("0.60")
PRIOR_WEIGHT = Decimal("0.40")
HOLD_HARMLESS_FLOOR_PCT = Decimal("0.90")
MIN_ALLOCATION_CASES = 5
SLOW_INDEX_THRESHOLD = Decimal("0.60")
TURNOVER_WEIGHT = Decimal("0.70")
AGE_WEIGHT = Decimal("0.30")
AGE_SATURATION_DAYS = Decimal("90")
SHELF_WEIGHT = Decimal("0.50")
DOCK_TURNAROUND_MINUTES = 30
RECORDKEEPING_WITHHOLD_PCT = Decimal("0.10")
RECORDKEEPING_COMPLIANCE_MIN = Decimal("0.9500")
HOUSEHOLD_BASE_LIMIT_CENTS = 195000
HOUSEHOLD_PER_PERSON_CENTS = 68000

ZERO_2 = Decimal("0.00")
ZERO_4 = Decimal("0.0000")
ZERO_6 = Decimal("0.000000")


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places):
    """Round half up to a fixed number of decimal places."""
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def floor_int(value):
    """Discard the fractional part (values in this domain are never negative)."""
    return int(dec(value).to_integral_value(rounding="ROUND_FLOOR"))


def ceil_int(value):
    return int(-((-dec(value)).to_integral_value(rounding="ROUND_FLOOR")))


# ---------------------------------------------------------------------------
# Largest-remainder reconciliation (PRD §2.7)
# ---------------------------------------------------------------------------
def largest_remainder(rows, total, weight_key, extra_sort):
    """Floor each proportional share, then hand out the leftover units.

    `rows` is a list of dicts; `weight_key` names the weight; `extra_sort`
    returns the documented tie-break tuple after the fractional part. Every
    tie-break ends in created_at ascending, and no ranking reads a row's id.
    Returns a dict of row index -> integer share.
    """
    total_weight = sum(dec(r[weight_key]) for r in rows)
    shares = {}
    fracs = []
    for index, row in enumerate(rows):
        if total_weight == 0:
            exact = Decimal(0)
        else:
            exact = dec(total) * dec(row[weight_key]) / total_weight
        base = floor_int(exact)
        shares[index] = base
        fracs.append((index, exact - base))
    residual = int(total) - sum(shares.values())
    if residual > 0:
        ranked = sorted(
            fracs,
            key=lambda item: (-item[1],) + extra_sort(rows[item[0]], item[0]),
        )
        position = 0
        while residual > 0 and ranked:
            index = ranked[position % len(ranked)][0]
            shares[index] += 1
            residual -= 1
            position += 1
    elif residual < 0:
        ranked = sorted(
            fracs,
            key=lambda item: (item[1],) + extra_sort(rows[item[0]], item[0]),
        )
        position = 0
        while residual < 0 and ranked:
            index = ranked[position % len(ranked)][0]
            shares[index] -= 1
            residual += 1
            position += 1
    return shares


# ---------------------------------------------------------------------------
# calculations.agency_case_allocation
# ---------------------------------------------------------------------------
def compute_allocation(plans, allocatable_cases, formula_variant):
    """Run the eight-step split over `plans`, in included-set order.

    Each plan is a dict carrying poverty_population, area_eligible_count,
    prior_pounds and prior_cases. The plan dicts are filled in place with
    poverty_factor, poverty_share, prior_share, raw_score, floor_cases and
    allocated_cases. Raises the caller-supplied `infeasible` signal by
    returning None-free values; the caller checks the returned error id.
    """
    # step 1 — the poverty factor
    for plan in plans:
        divisor = plan["area_eligible_count"]
        if divisor and divisor > 0:
            plan["poverty_factor"] = rhu(
                dec(plan["poverty_population"]) / dec(divisor), 4
            )
        else:
            plan["poverty_factor"] = ZERO_4

    # step 2 — the poverty share
    sum_poverty = sum(plan["poverty_factor"] for plan in plans)
    for plan in plans:
        if sum_poverty == 0:
            plan["poverty_share"] = ZERO_6
        else:
            plan["poverty_share"] = rhu(plan["poverty_factor"] / sum_poverty, 6)

    # step 3 — the prior share and the blended score
    sum_prior = sum(dec(plan["prior_pounds"]) for plan in plans)
    for plan in plans:
        if sum_prior == 0:
            plan["prior_share"] = ZERO_6
            plan["raw_score"] = rhu(plan["poverty_share"], 6)
        else:
            plan["prior_share"] = rhu(dec(plan["prior_pounds"]) / sum_prior, 6)
            plan["raw_score"] = rhu(
                POVERTY_WEIGHT * plan["poverty_share"]
                + PRIOR_WEIGHT * plan["prior_share"],
                6,
            )

    # step 4 — the exact and floored case counts
    for plan in plans:
        plan["_exact"] = dec(allocatable_cases) * plan["raw_score"]
        plan["_base"] = floor_int(plan["_exact"])

    # step 5 — largest-remainder rounding
    remainder = int(allocatable_cases) - sum(plan["_base"] for plan in plans)
    provisional = {index: plan["_base"] for index, plan in enumerate(plans)}
    fracs = [
        (index, plan["_exact"] - plan["_base"], plan["poverty_factor"])
        for index, plan in enumerate(plans)
    ]
    if remainder > 0:
        ranked = sorted(fracs, key=lambda item: (-item[1], -item[2], item[0]))
        position = 0
        while remainder > 0 and ranked:
            index = ranked[position % len(ranked)][0]
            provisional[index] += 1
            remainder -= 1
            position += 1
    elif remainder < 0:
        ranked = sorted(fracs, key=lambda item: (item[1], item[2], item[0]))
        position = 0
        while remainder < 0 and ranked:
            index = ranked[position % len(ranked)][0]
            if provisional[index] > 0:
                provisional[index] -= 1
                remainder += 1
            position += 1
            if position > len(ranked) * (abs(remainder) + 2):
                break
    for index, plan in enumerate(plans):
        plan["_provisional"] = provisional[index]

    # step 6 — the variant switch
    if formula_variant == "HOLD_HARMLESS":
        for plan in plans:
            plan["floor_cases"] = floor_int(
                HOLD_HARMLESS_FLOOR_PCT * dec(plan["prior_cases"])
            )
        shortfall_total = sum(
            max(0, plan["floor_cases"] - plan["_provisional"]) for plan in plans
        )
        donors = [
            (index, plan)
            for index, plan in enumerate(plans)
            if plan["_provisional"] > plan["floor_cases"]
        ]
        donors.sort(
            key=lambda item: (
                -(item[1]["_provisional"] - item[1]["floor_cases"]),
                -int(item[1]["prior_cases"]),
                item[0],
            )
        )
        excess_total = sum(
            plan["_provisional"] - plan["floor_cases"] for _, plan in donors
        )
        if shortfall_total > excess_total:
            return "ERR_ALLOCATION_INFEASIBLE"
        reductions = {}
        applied = 0
        for position, (index, plan) in enumerate(donors):
            excess = plan["_provisional"] - plan["floor_cases"]
            if position < len(donors) - 1:
                reduction = (
                    floor_int(dec(shortfall_total) * dec(excess) / dec(excess_total))
                    if excess_total
                    else 0
                )
                reductions[index] = reduction
                applied += reduction
            else:
                reductions[index] = shortfall_total - applied
        for index, plan in enumerate(plans):
            plan["allocated_cases"] = (
                max(plan["_provisional"], plan["floor_cases"]) - reductions.get(index, 0)
            )
    else:
        for plan in plans:
            plan["floor_cases"] = 0
            plan["allocated_cases"] = plan["_provisional"]

    # step 7 — the minimum lift (single pass, never re-run against its output)
    deficits = [
        (index, MIN_ALLOCATION_CASES - plan["allocated_cases"])
        for index, plan in enumerate(plans)
        if plan["allocated_cases"] < MIN_ALLOCATION_CASES
    ]
    needed = sum(need for _, need in deficits)
    for _ in range(needed):
        candidates = [
            (index, plan)
            for index, plan in enumerate(plans)
            if plan["allocated_cases"]
            > max(MIN_ALLOCATION_CASES, plan["floor_cases"])
        ]
        if not candidates:
            return "ERR_ALLOCATION_INFEASIBLE"
        candidates.sort(key=lambda item: (-item[1]["allocated_cases"], item[0]))
        candidates[0][1]["allocated_cases"] -= 1
    for index, _ in deficits:
        plans[index]["allocated_cases"] = MIN_ALLOCATION_CASES

    # step 8 — the invariant
    if sum(plan["allocated_cases"] for plan in plans) != int(allocatable_cases):
        return "ERR_ALLOCATION_INFEASIBLE"
    return None


# ---------------------------------------------------------------------------
# calculations.admin_funds_allocation
# ---------------------------------------------------------------------------
def compute_admin_funds(rows, pool_cents, total_allocated_cases):
    """Fill each row dict with base/withheld/redistribution/final cents.

    `rows` are dicts in AgencyAllocation created_at order carrying
    distributed_pounds, allocated_cases and record_compliance_pct.
    """
    # step 1 — the weighting basis
    pounds_total = sum(dec(row["distributed_pounds"]) for row in rows)
    if pounds_total == 0:
        for row in rows:
            row["_weight"] = dec(row["allocated_cases"])
        total_weight = dec(total_allocated_cases)
        if total_weight == 0:
            total_weight = sum(row["_weight"] for row in rows)
    else:
        for row in rows:
            row["_weight"] = dec(row["distributed_pounds"])
        total_weight = pounds_total

    # step 2 — the base award
    bases = {}
    fracs = []
    for index, row in enumerate(rows):
        if total_weight == 0:
            exact = Decimal(0)
        else:
            exact = dec(pool_cents) * row["_weight"] / total_weight
        base = floor_int(exact)
        bases[index] = base
        fracs.append((index, exact - base, row["_weight"]))
    residual = int(pool_cents) - sum(bases.values())
    if residual > 0:
        ranked = sorted(fracs, key=lambda item: (-item[1], -item[2], item[0]))
        position = 0
        while residual > 0 and ranked:
            bases[ranked[position % len(ranked)][0]] += 1
            residual -= 1
            position += 1
    for index, row in enumerate(rows):
        row["admin_funds_base_cents"] = bases[index]

    # step 3 — the recordkeeping withholding (reads step-two figures only)
    for row in rows:
        if dec(row["record_compliance_pct"]) < RECORDKEEPING_COMPLIANCE_MIN:
            row["admin_funds_withheld_cents"] = floor_int(
                dec(row["admin_funds_base_cents"]) * RECORDKEEPING_WITHHOLD_PCT
            )
        else:
            row["admin_funds_withheld_cents"] = 0

    # step 4 — redistributing the withheld pool
    withheld_pool = sum(row["admin_funds_withheld_cents"] for row in rows)
    recipients = [
        (index, row)
        for index, row in enumerate(rows)
        if row["admin_funds_withheld_cents"] == 0
    ]
    if not recipients:
        recipients = list(enumerate(rows))
    recipient_base_total = sum(row["admin_funds_base_cents"] for _, row in recipients)
    redist = {index: 0 for index in range(len(rows))}
    rfracs = []
    for index, row in recipients:
        if recipient_base_total == 0:
            exact = Decimal(0)
        else:
            exact = (
                dec(withheld_pool)
                * dec(row["admin_funds_base_cents"])
                / dec(recipient_base_total)
            )
        share = floor_int(exact)
        redist[index] = share
        rfracs.append((index, exact - share, row["admin_funds_base_cents"]))
    residual_r = withheld_pool - sum(redist.values())
    if residual_r > 0 and rfracs:
        ranked = sorted(rfracs, key=lambda item: (-item[1], -item[2], item[0]))
        position = 0
        while residual_r > 0:
            redist[ranked[position % len(ranked)][0]] += 1
            residual_r -= 1
            position += 1

    # step 5 — the final award
    for index, row in enumerate(rows):
        row["_redistributed_cents"] = redist[index]
        row["admin_funds_cents"] = (
            row["admin_funds_base_cents"]
            - row["admin_funds_withheld_cents"]
            + redist[index]
        )
    return rows


# ---------------------------------------------------------------------------
# calculations.lot_monitor_flag
# ---------------------------------------------------------------------------
def monitor_score(days_on_hand, cases_received, cases_shipped, shelf_span_days,
                  days_to_best_by, policy):
    if not cases_received:
        turnover = ZERO_4
    else:
        turnover = rhu(dec(cases_shipped) / dec(cases_received), 4)
    if shelf_span_days and shelf_span_days > 0:
        shelf_remaining = rhu(
            dec(max(0, days_to_best_by)) / dec(shelf_span_days), 4
        )
    else:
        shelf_remaining = ZERO_4
    if policy == "SHELF_LIFE_BASED":
        index = rhu(
            SHELF_WEIGHT * (Decimal(1) - shelf_remaining)
            + SHELF_WEIGHT * (Decimal(1) - turnover),
            4,
        )
    else:
        saturation = dec(days_on_hand) / AGE_SATURATION_DAYS
        if saturation > Decimal(1):
            saturation = Decimal(1)
        index = rhu(
            TURNOVER_WEIGHT * (Decimal(1) - turnover) + AGE_WEIGHT * saturation, 4
        )
    return index


def monitor_flag(cases_on_hand, excess_case_ceiling, index):
    if cases_on_hand > excess_case_ceiling:
        return "EXCESS"
    if index >= SLOW_INDEX_THRESHOLD:
        return "SLOW_MOVING"
    return "NONE"


# ---------------------------------------------------------------------------
# household income test
# ---------------------------------------------------------------------------
def income_limit_cents(household_size):
    return HOUSEHOLD_BASE_LIMIT_CENTS + (household_size - 1) * HOUSEHOLD_PER_PERSON_CENTS
