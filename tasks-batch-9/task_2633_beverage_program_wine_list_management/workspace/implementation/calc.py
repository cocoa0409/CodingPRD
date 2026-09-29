"""The fourteen calculations of PRD section 3, in their pinned rounding orders."""
from decimal import Decimal
from fractions import Fraction

from core import (
    BTG_SPOILAGE_ALLOWANCE_POURS,
    EVENT_POUR_SIZE_ML,
    LARGE_PARTY_CORKAGE_DISCOUNT_PCT,
    LARGE_PARTY_THRESHOLD,
    MAX_PRESERVATION_HOURS,
    PAR_URGENT_FRACTION,
    PRESERVATION_BASE_HOURS,
    PRESERVATION_METHOD_FACTOR,
    VARIANCE_FROZEN_PCT,
    VARIANCE_RESTRICTED_PCT,
    D,
    ceil_dec,
    ceil_to_multiple,
    fail,
    floor_div_dec,
    rhu,
    rhu_int,
    store,
    timedelta,
)

LIVE_VERSION_STATES = ("PUBLISHED", "REPRINT_PENDING")


# ---------------------------------------------------------------------------
# list_entry_bottle_price
# ---------------------------------------------------------------------------
def markup_multiplier(cost_cents):
    """Every break belongs to the band below it (<= on the upper bound)."""
    cost = int(cost_cents)
    if cost <= 2000:
        return D("3.50")
    if cost <= 6000:
        return D("3.00")
    if cost <= 15000:
        return D("2.60")
    return D("2.20")


def category_target_pct(venue, category):
    return D(venue["cogs_target_pct_by_category"][category])


def bottle_price_cents(wine, venue):
    cost = D(wine["reference_cost_cents"])
    markup_price = rhu_int(cost * markup_multiplier(cost))
    target_price = rhu_int(cost * 100 / category_target_pct(venue, wine["category"]))
    winner = max(markup_price, target_price)
    premium = D("1.15") if wine["is_allocated"] else D("1.00")
    raw = rhu_int(D(winner) * premium)
    return ceil_to_multiple(raw, 100)


def price_band(bottle_price):
    price = int(bottle_price)
    if price <= 6000:
        return "VALUE"
    if price <= 12000:
        return "CORE"
    if price <= 25000:
        return "PREMIUM"
    return "RESERVE"


TOP_TWO_BANDS = ("PREMIUM", "RESERVE")


# ---------------------------------------------------------------------------
# list_entry_glass_price
# ---------------------------------------------------------------------------
def effective_pours_for(bottle_size_ml, pour_size_ml):
    gross = floor_div_dec(D(bottle_size_ml) / D(pour_size_ml))
    return gross - BTG_SPOILAGE_ALLOWANCE_POURS


def glass_price_cents(wine, venue, effective_pours):
    raw = (
        D(wine["reference_cost_cents"])
        * 100
        / category_target_pct(venue, wine["category"])
        / D(effective_pours)
    )
    return ceil_to_multiple(rhu_int(raw), 25)


# ---------------------------------------------------------------------------
# btg_preservation_expiry
# ---------------------------------------------------------------------------
def preservation_expires_at(opened_at, wine_category, preservation_method):
    base = D(PRESERVATION_BASE_HOURS[wine_category])
    factor = PRESERVATION_METHOD_FACTOR[preservation_method]
    hours = min(MAX_PRESERVATION_HOURS, floor_div_dec(base * factor))
    return opened_at + timedelta(hours=hours)


# ---------------------------------------------------------------------------
# lot_depletion_cogs
# ---------------------------------------------------------------------------
def lot_available(lot):
    return int(lot["bottles_on_hand"]) - int(lot["bottles_committed"])


def candidate_lots(venue_id, wine_id, availability=None):
    """ON_HAND lots of the pair with something left to give, received_at ASC then created_at ASC."""
    rows = [
        lot
        for lot in store.inventory_lots.values()
        if lot["venue_id"] == venue_id
        and lot["wine_id"] == wine_id
        and lot["state"] == "ON_HAND"
        and (lot_available(lot) if availability is None else availability.get(lot["id"], 0)) > 0
    ]
    return sorted(rows, key=lambda r: (r["received_at"], r["created_at"], r["_seq"]))


def weighted_average_unit_cents(candidates, availability=None):
    total_available = 0
    total_value = 0
    for lot in candidates:
        avail = lot_available(lot) if availability is None else availability.get(lot["id"], 0)
        total_available += avail
        total_value += avail * int(lot["unit_cost_cents"])
    if total_available <= 0:
        return 0
    return rhu_int(D(total_value) / D(total_available))


def draw_from_lots(venue, venue_wine_lots, bottles, availability=None):
    """Walk the candidate order taking min(available, remaining) from each lot.

    Returns (total_cogs_cents, [(lot, bottles_taken, cogs_for_those_bottles), ...]).
    The physical draw follows received_at ASC under both costing variants; only the
    money differs.
    """
    remaining = int(bottles)
    draws = []
    method = venue["costing_method"]
    wac_unit = (
        weighted_average_unit_cents(venue_wine_lots, availability)
        if method == "WEIGHTED_AVERAGE"
        else None
    )
    for lot in venue_wine_lots:
        if remaining <= 0:
            break
        avail = lot_available(lot) if availability is None else availability.get(lot["id"], 0)
        if avail <= 0:
            continue
        take = min(avail, remaining)
        unit = wac_unit if wac_unit is not None else int(lot["unit_cost_cents"])
        draws.append((lot, take, take * int(unit)))
        remaining -= take
    total = sum(item[2] for item in draws)
    return total, draws


def cost_pinned_lot(venue, lot, bottles):
    """A write-off and a slot close are pinned to one explicit lot."""
    if venue["costing_method"] == "WEIGHTED_AVERAGE":
        unit = weighted_average_unit_cents([lot], {lot["id"]: max(1, lot_available(lot))})
    else:
        unit = int(lot["unit_cost_cents"])
    return int(bottles) * int(unit)


# ---------------------------------------------------------------------------
# btg_close_cost_split
# ---------------------------------------------------------------------------
def btg_close_split(bottle_cogs_cents, effective_pours, pours_sold, education_pours):
    cost_per_pour = rhu_int(D(bottle_cogs_cents) / D(effective_pours))
    sale_cogs = cost_per_pour * int(pours_sold)
    edu_cogs = cost_per_pour * int(education_pours)
    spoil_cogs = int(bottle_cogs_cents) - sale_cogs - edu_cogs
    return sale_cogs, edu_cogs, spoil_cogs


# ---------------------------------------------------------------------------
# list_entry_contest_points
# ---------------------------------------------------------------------------
def contest_points(entry, venue, wine):
    ledger = [
        e for e in store.depletion_entries.values() if e.get("list_entry_id") == entry["id"]
    ]
    pours_sold = sum(int(e["pours"]) for e in ledger if e["reason"] == "SALE_BTG")
    bottles_sold = sum(int(e["bottles"]) for e in ledger if e["reason"] == "SALE_BOTTLE")
    cogs = sum(int(e["cogs_cents"]) for e in ledger)
    revenue = sum(int(e["revenue_cents"]) for e in ledger)
    if revenue > 0:
        target_pct = category_target_pct(venue, wine["category"])
        realized_pct = rhu(D(cogs) * 100 / D(revenue), 2)
        factor = (target_pct - realized_pct) / target_pct
        if factor < 0:
            factor = D("0.0")
        if factor > 1:
            factor = D("1.0")
        margin_factor = rhu(factor, 4)
    else:
        margin_factor = D("0.0")
    total = (
        D(1) * pours_sold
        + D(3) * bottles_sold
        + D(5) * (1 if entry["education_verified"] else 0)
        + D(10) * margin_factor
    )
    return rhu(total, 2)


# ---------------------------------------------------------------------------
# allocation_waterfall_grant
# ---------------------------------------------------------------------------
def waterfall(pool, claims):
    """claims: list of claim records in creation order. Returns
    {claim_id: (granted, raw_share_decimal, remainder_awarded)}."""
    pool = int(pool)
    total_requested = sum(int(c["requested_bottles"]) for c in claims)
    result = {}
    if total_requested <= pool:
        for claim in claims:
            share = Fraction(pool * int(claim["requested_bottles"]), total_requested) if total_requested else Fraction(0)
            result[claim["id"]] = [int(claim["requested_bottles"]), _frac_4dp(share), False]
        return result, pool - total_requested

    fracs = {}
    granted = {}
    for claim in claims:
        share = Fraction(pool * int(claim["requested_bottles"]), total_requested)
        base = share.numerator // share.denominator
        granted[claim["id"]] = base
        fracs[claim["id"]] = share - base
        result[claim["id"]] = [base, _frac_4dp(share), False]

    order = sorted(
        claims,
        key=lambda c: (
            -fracs[c["id"]],
            _priority_rank(c),
            c["created_at"],
            c["_seq"],
        ),
    )
    remainder = pool - sum(granted.values())
    for claim in order:
        if remainder <= 0:
            break
        granted[claim["id"]] += 1
        result[claim["id"]][2] = True
        remainder -= 1

    # No claim may end with more than it asked for; bottles freed by the cap are
    # handed out again by repeating the same ordered pass.
    while True:
        freed = 0
        for claim in claims:
            requested = int(claim["requested_bottles"])
            if granted[claim["id"]] > requested:
                freed += granted[claim["id"]] - requested
                granted[claim["id"]] = requested
        if freed <= 0:
            break
        awarded_any = False
        for claim in order:
            if freed <= 0:
                break
            if granted[claim["id"]] < int(claim["requested_bottles"]):
                granted[claim["id"]] += 1
                result[claim["id"]][2] = True
                freed -= 1
                awarded_any = True
        if not awarded_any:
            break

    for claim in claims:
        result[claim["id"]][0] = granted[claim["id"]]
    return result, pool - sum(granted.values())


def _frac_4dp(share):
    return rhu(D(share.numerator) / D(share.denominator), 4)


def _priority_rank(claim):
    venue = store.venues.get(claim["venue_id"])
    return int(venue["priority_rank"]) if venue else 0


def claim_state_for(granted, requested):
    if granted == requested:
        return "GRANTED"
    if granted > 0:
        return "PARTIALLY_GRANTED"
    return "REJECTED"


# ---------------------------------------------------------------------------
# wine_dinner_ticket_price
# ---------------------------------------------------------------------------
def event_pour_yield(wine):
    pours = floor_div_dec(D(wine["bottle_size_ml"]) / D(EVENT_POUR_SIZE_ML)) - 1
    if pours <= 0:
        fail(
            "ERR_VALUE_OUT_OF_RANGE",
            "This bottle size yields no saleable event pour at the standard 100 ml pour.",
        )
    return pours


def event_pricing(event, venue, lines):
    """lines: [(pour_plan_line, list_entry, wine), ...] in pour_plan array order."""
    beverage_cost_per_seat = 0
    for line, entry, wine in lines:
        pours = event_pour_yield(wine)
        cost_per_pour = rhu_int(D(wine["reference_cost_cents"]) / D(pours))
        line_cost = rhu_int(D(cost_per_pour) * D(line["pours_per_seat"]))
        beverage_cost_per_seat += line_cost

    seat_count = int(event["seat_count"])
    provisional_gross = ceil_to_multiple(
        rhu_int(D(beverage_cost_per_seat) * 100 / D(venue["event_cogs_target_pct"])), 500
    )
    provisional_revenue = provisional_gross * seat_count
    if provisional_revenue < 250000:
        tier = D("0.0")
    elif provisional_revenue < 500000:
        tier = D("4.0")
    else:
        tier = D("7.0")
    final_ticket = ceil_to_multiple(
        rhu_int(D(provisional_gross) * (D(100) - tier) / D(100)), 100
    )
    total_beverage_cost = beverage_cost_per_seat * seat_count
    denominator = final_ticket * seat_count
    projected = (
        rhu(D(total_beverage_cost) * 100 / D(denominator), 2) if denominator else D("0.00")
    )
    return {
        "beverage_cost_per_seat_cents": beverage_cost_per_seat,
        "provisional_gross_cents": provisional_gross,
        "tier_discount_pct": tier,
        "final_ticket_price_cents": final_ticket,
        "projected_pour_cost_pct": projected,
    }


def event_bottles_needed(seat_count, pours_per_seat, pour_yield):
    return ceil_dec(D(int(seat_count) * int(pours_per_seat)) / D(pour_yield))


# ---------------------------------------------------------------------------
# corkage_charge
# ---------------------------------------------------------------------------
def corkage_quote(venue, byo_bottle_count, bottles_purchased, party_size):
    earned = int(bottles_purchased) // int(venue["corkage_waiver_purchase_ratio"])
    waived = min(int(byo_bottle_count), earned)
    chargeable = int(byo_bottle_count) - waived
    total = chargeable * int(venue["corkage_fee_cents"])
    discount_applied = int(party_size) >= LARGE_PARTY_THRESHOLD
    if discount_applied:
        total = rhu_int(D(total) * (D(100) - LARGE_PARTY_CORKAGE_DISCOUNT_PCT) / D(100))
    return {
        "waived_bottles": waived,
        "chargeable_bottles": chargeable,
        "corkage_total_cents": int(total),
        "large_party_discount_applied": discount_applied,
    }


# ---------------------------------------------------------------------------
# venue_pour_cost_variance
# ---------------------------------------------------------------------------
THEORETICAL_REASONS = ("SALE_BTG", "SALE_BOTTLE", "EVENT")


def pour_cost_figures(venue_id, period_start, period_end):
    """Half-open window [period_start, period_end) on occurred_at."""
    all_entries = [
        e
        for e in store.depletion_entries.values()
        if e["venue_id"] == venue_id
        and e["occurred_at"] >= period_start
        and e["occurred_at"] < period_end
    ]
    sale_entries = [e for e in all_entries if e["reason"] in THEORETICAL_REASONS]

    actual_cogs = sum(int(e["cogs_cents"]) for e in all_entries)
    actual_revenue = sum(int(e["revenue_cents"]) for e in all_entries)
    theoretical_cogs = sum(int(e["cogs_cents"]) for e in sale_entries)
    theoretical_revenue = sum(int(e["revenue_cents"]) for e in sale_entries)

    if actual_revenue == 0:
        fail("ERR_NO_REVENUE_IN_PERIOD", "The period carries no recognised revenue.")
    if theoretical_revenue == 0:
        fail("ERR_NO_REVENUE_IN_PERIOD", "The period carries no recognised sales revenue.")

    actual_pct = rhu(D(actual_cogs) * 100 / D(actual_revenue), 2)
    theoretical_pct = rhu(D(theoretical_cogs) * 100 / D(theoretical_revenue), 2)
    variance_pct = rhu(actual_pct - theoretical_pct, 2)
    return {
        "actual_pour_cost_pct": actual_pct,
        "theoretical_pour_cost_pct": theoretical_pct,
        "variance_pct": variance_pct,
        "actual_cogs_cents": actual_cogs,
        "actual_revenue_cents": actual_revenue,
        "theoretical_cogs_cents": theoretical_cogs,
        "theoretical_revenue_cents": theoretical_revenue,
        "entry_count": len(all_entries),
    }


def has_escalated_investigation(venue_id):
    return any(
        inv["venue_id"] == venue_id and inv["state"] == "ESCALATED"
        for inv in store.variance_investigations.values()
    )


def posture_for(variance_pct, escalated):
    """Boundaries belong to the lower band: exactly 3.00 stays OPEN, exactly 6.00 RESTRICTED."""
    variance = D(variance_pct)
    if variance > VARIANCE_FROZEN_PCT or escalated:
        return "FROZEN"
    if variance > VARIANCE_RESTRICTED_PCT:
        return "RESTRICTED"
    return "OPEN"


# ---------------------------------------------------------------------------
# par_reorder_quantity
# ---------------------------------------------------------------------------
def par_lines(venue_id, entries):
    """entries: ListEntry rows of the venue's single live ListVersion."""
    lines = []
    for entry in entries:
        wine = store.wines.get(entry["wine_id"])
        on_hand = sum(
            int(lot["bottles_on_hand"])
            for lot in store.inventory_lots.values()
            if lot["venue_id"] == venue_id
            and lot["wine_id"] == entry["wine_id"]
            and lot["state"] == "ON_HAND"
        )
        on_order = 0
        for claim in store.allocation_claims.values():
            if claim["venue_id"] != venue_id:
                continue
            if claim["state"] not in ("GRANTED", "PARTIALLY_GRANTED"):
                continue
            offer = store.allocation_offers.get(claim["offer_id"])
            if offer is None or offer["wine_id"] != entry["wine_id"]:
                continue
            on_order += int(claim["granted_bottles"])
        par = int(entry["par_bottles"])
        deficit = par - on_hand - on_order
        if deficit <= 0:
            reorder = 0
        else:
            case_pack = int(wine["case_pack"]) if wine else 1
            reorder = ceil_dec(D(deficit) / D(case_pack)) * case_pack
        urgent = on_hand < ceil_dec(D(par) * PAR_URGENT_FRACTION)
        lines.append(
            {
                "list_entry_id": entry["id"],
                "wine_id": entry["wine_id"],
                "par_bottles": par,
                "bottles_on_hand": on_hand,
                "bottles_on_order": on_order,
                "deficit_bottles": deficit,
                "reorder_bottles": reorder,
                "is_urgent": urgent,
                "_sort_rank": int(entry["sort_rank"]),
            }
        )
    lines.sort(key=lambda l: (not l["is_urgent"], -l["reorder_bottles"], l["_sort_rank"]))
    for line in lines:
        line.pop("_sort_rank", None)
    return lines
