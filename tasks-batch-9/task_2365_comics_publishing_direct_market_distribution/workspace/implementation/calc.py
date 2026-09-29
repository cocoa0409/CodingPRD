"""The twelve pinned calculations of the PRD.

Rounding vocabularies (PRD 2.8) are kept strictly apart:
  * round half up : invoice lines, reprint demand projection
  * floor         : slip days, incentive earning, returns reserve, channel pools,
                    royalty shares
  * ceiling       : print overprint, carton rounding
"""

from decimal import Decimal, ROUND_HALF_UP

from core import (
    CARTON_MULTIPLE,
    CHANNEL_MULTIPLIER_BPS,
    EXCLUSIVE_ELIGIBILITY_UNITS,
    EXCLUSIVE_MIN_RATIO,
    FREE_HANDLING_THRESHOLD_CENTS,
    HANDLING_FEE_CENTS,
    MIN_FIRST_PRINTING,
    MIN_REPRINT,
    OVERPRINT_PCT_DEN,
    OVERPRINT_PCT_NUM,
    POOL_DENOMINATOR,
    RESERVE_COPIES,
    RETURNS_RESERVE_PCT,
    SLIP_AT_RISK_DAYS,
    SLIP_BREACH_DAYS,
    TIER_BASIC_UNITS,
    TIER_CORE_UNITS,
    TIER_PREMIER_UNITS,
    date_of,
)

# ---------------------------------------------------------------------------
# Rounding primitives
# ---------------------------------------------------------------------------

BILLED_PCT = {"ENTRY": 60, "BASIC": 55, "CORE": 50, "PREMIER": 45}
REORDER_DEMAND_NUM = 35
REORDER_DEMAND_DEN = 100


def round_half_up(numerator, denominator):
    """Exact round-half-up of numerator/denominator (ties away from zero)."""
    quotient = Decimal(numerator) / Decimal(denominator)
    return int(quotient.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_div(numerator, denominator):
    if denominator == 0:
        return 0
    return numerator // denominator


def ceil_div(numerator, denominator):
    if denominator == 0:
        return 0
    return -((-numerator) // denominator)


# ---------------------------------------------------------------------------
# stage_slip_days / schedule_health_posture
# ---------------------------------------------------------------------------


def stage_slip_days(delivered_at, planned_due_date):
    days = (date_of(delivered_at) - date_of(planned_due_date)).days
    return days if days > 0 else 0


def schedule_health_posture(total_slip_days):
    if total_slip_days <= SLIP_AT_RISK_DAYS:
        return "ON_TRACK"
    if total_slip_days <= SLIP_BREACH_DAYS:
        return "AT_RISK"
    return "SLIPPED"


# ---------------------------------------------------------------------------
# retailer_discount_tier
# ---------------------------------------------------------------------------


def retailer_discount_tier(cumulative_units_ytd):
    if cumulative_units_ytd >= TIER_PREMIER_UNITS:
        return "PREMIER"
    if cumulative_units_ytd >= TIER_CORE_UNITS:
        return "CORE"
    if cumulative_units_ytd >= TIER_BASIC_UNITS:
        return "BASIC"
    return "ENTRY"


# ---------------------------------------------------------------------------
# variant_incentive_allocation
# ---------------------------------------------------------------------------

_KIND_RANK = {"RATIO_INCENTIVE": 0, "RETAILER_EXCLUSIVE": 1, "STANDARD": 2}


def cover_walk_order(covers):
    """kind (fixed sequence), then incentive_ratio ASC with nulls last, then code ASC.
    Identifiers are never consulted."""
    def key(cover):
        ratio = cover.get("incentive_ratio")
        return (
            _KIND_RANK.get(cover["kind"], 99),
            1 if ratio is None else 0,
            ratio if ratio is not None else 0,
            cover["code"],
        )

    return sorted(covers, key=key)


def variant_incentive_allocation(order, covers, retailer_units_before):
    """Returns (allocations, total_units) for a single order at FOC lock."""
    if order.get("is_reorder"):
        return [], order["standard_qty"]

    standard_qty = order["standard_qty"]
    allocations = []
    for cover in cover_walk_order(covers):
        kind = cover["kind"]
        if kind == "RATIO_INCENTIVE":
            earned = floor_div(standard_qty, cover["incentive_ratio"])
            if cover.get("allocation_cap") is not None:
                earned = min(earned, cover["allocation_cap"])
        elif kind == "RETAILER_EXCLUSIVE":
            if retailer_units_before >= EXCLUSIVE_ELIGIBILITY_UNITS:
                earned = min(
                    order.get("exclusive_variant_qty") or 0,
                    floor_div(standard_qty, EXCLUSIVE_MIN_RATIO),
                )
                if cover.get("allocation_cap") is not None:
                    earned = min(earned, cover["allocation_cap"])
            else:
                earned = 0
        else:
            earned = 0
        if earned > 0:
            allocations.append({"variant_cover_id": cover["id"], "qty": earned})

    total_units = standard_qty + sum(a["qty"] for a in allocations)
    return allocations, total_units


# ---------------------------------------------------------------------------
# retailer_invoice_total
# ---------------------------------------------------------------------------


def retailer_invoice_total(tier, lines):
    """`lines` is a list of (qty, unit_price_cents) in the pinned order.
    Each line is rounded to the cent BEFORE the sum is taken."""
    billed_pct = BILLED_PCT[tier]
    merchandise_net = 0
    gross_total = 0
    for qty, unit in lines:
        gross = qty * unit
        gross_total += gross
        merchandise_net += round_half_up(gross * billed_pct, 100)
    handling = 0 if merchandise_net >= FREE_HANDLING_THRESHOLD_CENTS else HANDLING_FEE_CENTS
    return {
        "gross_cents": gross_total,
        "merchandise_net_cents": merchandise_net,
        "handling_fee_cents": handling,
        "invoice_total_cents": merchandise_net + handling,
    }


# ---------------------------------------------------------------------------
# print_run_quantity
# ---------------------------------------------------------------------------


def order_driven_quantity(order_base_units):
    overprint = ceil_div(order_base_units * OVERPRINT_PCT_NUM, OVERPRINT_PCT_DEN)
    raw = order_base_units + overprint + RESERVE_COPIES
    quantity = max(ceil_div(raw, CARTON_MULTIPLE) * CARTON_MULTIPLE, MIN_FIRST_PRINTING)
    return overprint, quantity


def demand_forecast_quantity(prior_printed, reorder_units):
    base = round_half_up(prior_printed * REORDER_DEMAND_NUM, REORDER_DEMAND_DEN) + reorder_units
    quantity = max(ceil_div(base, CARTON_MULTIPLE) * CARTON_MULTIPLE, MIN_REPRINT)
    return base, 0, quantity


# ---------------------------------------------------------------------------
# royalty_pool_split
# ---------------------------------------------------------------------------


def royalty_pool_split(pool_cents, cover_participation_bps, participants):
    """Split one channel pool across the title's participating assignments.

    `participants` must already be ordered by created_at ASC. Returns a dict of
    assignment id -> share in cents. Evaluation order is pinned: the cover
    portion is struck from the whole pool first, the pro-rata remainder is then
    normalised over the non-COVER participants' own basis-point total.
    """
    shares = {p["id"]: 0 for p in participants}
    if pool_cents <= 0:
        return shares

    cover_participants = [p for p in participants if p["craft"] == "COVER"]
    non_cover = [p for p in participants if p["craft"] != "COVER"]

    # Step 1 - cover portion off the pre-deduction pool.
    cover_pool = floor_div(pool_cents * cover_participation_bps, 10000)

    # Step 2 - pro-rata across COVER participants, floor then 1-cent leftovers.
    sum_cover = sum(p["royalty_share_bps"] for p in cover_participants)
    if cover_participants and sum_cover > 0:
        for p in cover_participants:
            shares[p["id"]] = floor_div(cover_pool * p["royalty_share_bps"], sum_cover)
        leftover = cover_pool - sum(shares[p["id"]] for p in cover_participants)
        for p in cover_participants:
            if leftover <= 0:
                break
            shares[p["id"]] += 1
            leftover -= 1

    # Step 3/4/5 - the remainder normalised over the non-cover bps total.
    remainder = pool_cents - cover_pool
    sum_nc = sum(p["royalty_share_bps"] for p in non_cover)
    if sum_nc > 0:
        for p in non_cover:
            shares[p["id"]] = floor_div(remainder * p["royalty_share_bps"], sum_nc)
        leftover = remainder - sum(shares[p["id"]] for p in non_cover)
        for p in non_cover:
            if leftover <= 0:
                break
            shares[p["id"]] += 1
            leftover -= 1

    return shares


# ---------------------------------------------------------------------------
# royalty_accrual
# ---------------------------------------------------------------------------

CHANNEL_ORDER = ["PRINT_DM", "DIGITAL", "COLLECTED", "SUBSIDIARY"]


def royalty_accrual(basis, events, title, participants, assignment_id):
    """Compute the statement's lines and money figures.

    `events` are the contributing revenue events (already filtered by title,
    period and basis_status); `participants` are the title's ACCEPTED / ACTIVE /
    COMPLETED assignments in created_at ASC order.
    """
    lines = []
    for channel in CHANNEL_ORDER:
        raw_net = sum(e["net_receipts_cents"] for e in events if e["channel"] == channel)
        if raw_net == 0:
            continue
        if basis == "ESTIMATED" and channel == "PRINT_DM":
            included_net = floor_div(raw_net * (100 - RETURNS_RESERVE_PCT), 100)
        else:
            included_net = raw_net
        channel_pool = floor_div(
            included_net * title["royalty_pool_bps"] * CHANNEL_MULTIPLIER_BPS[channel],
            POOL_DENOMINATOR,
        )
        shares = royalty_pool_split(channel_pool, title["cover_participation_bps"], participants)
        lines.append({
            "channel": channel,
            "included_net_cents": included_net,
            "channel_pool_cents": channel_pool,
            "creator_share_cents": shares.get(assignment_id, 0),
        })
    gross = sum(line["creator_share_cents"] for line in lines)
    return lines, gross
