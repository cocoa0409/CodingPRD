"""Business logic: calculations, state cascades, shared resolvers.

Every formula here follows the PRD/scaffold exactly: pinned evaluation order,
exact decimal arithmetic, round-half-up at each pinned step.
"""

from datetime import timedelta
from decimal import Decimal

from db import store, get_clock, touch
from errors import ApiError, ERR_NO_MARKET_INDEX, ERR_NO_FREIGHT_LANE
from util import D, round0, round2

# ---------------------------------------------------------------------------
# Calculation constants (scaffold 1.3)
# ---------------------------------------------------------------------------
WET_DAY_THRESHOLD_MM = D("2.0")
DRYING_INDEX_MIN = 60

MOISTURE_TIER_CAP_PCT = D("16.0")

DROUGHT_REGIME_PCT = D("0.15")
VOLATILE_REGIME_PCT = D("0.08")
REGIME_LOOKBACK_DAYS = 30

TIER_MULTIPLIER = {
    "SUPREME": D("1.30"),
    "PREMIUM": D("1.15"),
    "GOOD": D("1.00"),
    "FAIR": D("0.85"),
}
DROUGHT_SURCHARGE_PCT = D("0.05")

SHRINK_MONTHLY_PCT = D("0.015")
SHRINK_CONTROLLED_MONTHLY_PCT = D("0.0075")
SHRINK_CAP_PCT = D("0.12")

COMMISSION_TIER1_MAX_TONS = D("500")
COMMISSION_TIER2_MAX_TONS = D("1500")
COMMISSION_TIER1_PCT = D("0.08")
COMMISSION_TIER2_PCT = D("0.06")
COMMISSION_TIER3_PCT = D("0.04")
PROTEIN_BONUS_THRESHOLD = D("20.0")
PROTEIN_BONUS_PCT = D("0.02")

BALE_RATE_TIER1_CENTS = 1200
BALE_RATE_TIER2_CENTS = 1050
BALE_RATE_TIER3_CENTS = 900
BALE_TIER1_MAX = 500
BALE_TIER2_MAX = 1000
MIN_BALING_CHARGE_CENTS = 600000
WET_BALING_MOISTURE_PCT = D("18.0")
WET_BALING_SURCHARGE_PCT = D("0.15")

QUOTE_TIERS = {"SUPREME", "PREMIUM", "GOOD", "FAIR", "UNGRADED"}
SELLABLE_TIERS = {"SUPREME", "PREMIUM", "GOOD", "FAIR"}
FORAGE_TYPES = {"ALFALFA", "GRASS", "MIXED"}
BALE_TYPES = {"SMALL_SQUARE", "LARGE_SQUARE", "ROUND"}
SPOILAGE_REASONS = {"MOLD", "MOISTURE", "PEST", "FIRE", "OTHER"}

# ---------------------------------------------------------------------------
# Reference resolvers
# ---------------------------------------------------------------------------

def grower_region_of_cutting(cutting):
    field = store["fields"].get(cutting["field_id"])
    if field is None:
        return None
    grower = store["growers"].get(field["grower_id"])
    return grower["region_code"] if grower else None


def grower_of_lot(lot):
    cutting = store["cuttings"].get(lot["cutting_id"])
    if cutting is None:
        return None
    field = store["fields"].get(cutting["field_id"])
    if field is None:
        return None
    return store["growers"].get(field["grower_id"])


def grower_of_cutting(cutting):
    field = store["fields"].get(cutting["field_id"])
    if field is None:
        return None
    return store["growers"].get(field["grower_id"])

# ---------------------------------------------------------------------------
# weather_window_evaluation
# ---------------------------------------------------------------------------

def _weather_report_for(region_code, day):
    for rep in store["weather_reports"].values():
        if rep["region_code"] == region_code and rep["report_date"] == day:
            return rep
    return None


def day_is_dry(region_code, day):
    """A day is DRY iff precipitation <= 2.0 (exactly 2.0 is dry) AND
    drying-capable iff drying_index >= 60 (exactly 60 qualifies).
    A day with no report counts as NOT dry."""
    rep = _weather_report_for(region_code, day)
    if rep is None:
        return False
    return D(rep["precipitation_mm"]) <= WET_DAY_THRESHOLD_MM and rep["drying_index"] >= DRYING_INDEX_MIN


def window_open_on(region_code, day):
    """Trailing 3 calendar days ending on `day` (inclusive) must each be dry."""
    return all(day_is_dry(region_code, day - timedelta(days=i)) for i in (0, 1, 2))


def reevaluate_cuttings_for_report(region_code, report_date):
    """POST /api/weather-reports side effect: flip SCHEDULED <-> WINDOW_OPEN
    for cuttings in the region whose planned window contains report_date or
    which are currently WINDOW_OPEN."""
    for cutting in list(store["cuttings"].values()):
        if cutting["status"] not in ("SCHEDULED", "WINDOW_OPEN"):
            continue
        if grower_region_of_cutting(cutting) != region_code:
            continue
        in_window = cutting["planned_window_start"] <= report_date <= cutting["planned_window_end"]
        if not in_window and cutting["status"] != "WINDOW_OPEN":
            continue
        if window_open_on(region_code, report_date):
            if cutting["status"] == "SCHEDULED":
                cutting["status"] = "WINDOW_OPEN"
                touch(cutting)
        else:
            if cutting["status"] == "WINDOW_OPEN":
                cutting["status"] = "SCHEDULED"  # weather-slip revert
                touch(cutting)

# ---------------------------------------------------------------------------
# quality_tier_assignment
# ---------------------------------------------------------------------------

def quality_tier_assignment(rfv, protein_pct, moisture_pct):
    r = D(rfv)
    if r >= D("185"):
        base = "SUPREME"
    elif r >= D("170"):
        base = "PREMIUM"  # rfv exactly 170.0 -> PREMIUM
    elif r >= D("150"):
        base = "GOOD"
    elif r >= D("125"):
        base = "FAIR"
    else:
        base = "UNGRADED"
    # moisture cap: exactly 16.0 does NOT cap
    if D(moisture_pct) > MOISTURE_TIER_CAP_PCT and base in ("SUPREME", "PREMIUM", "GOOD"):
        base = "FAIR"
    return base

# ---------------------------------------------------------------------------
# market_regime_classification
# ---------------------------------------------------------------------------

def classify_drought_regime(region_code, forage_type, effective_date, price_cents):
    priors = [
        idx for idx in store["market_indices"].values()
        if idx["region_code"] == region_code
        and idx["forage_type"] == forage_type
        and idx["effective_date"] < effective_date
        and idx["effective_date"] >= effective_date - timedelta(days=REGIME_LOOKBACK_DAYS)
    ]
    if not priors:
        return "STABLE"
    priors.sort(key=lambda i: (i["effective_date"], i["_seq"]))
    prior = priors[-1]
    pct = (D(price_cents) - D(prior["price_per_ton_cents"])) / D(prior["price_per_ton_cents"])
    if pct >= DROUGHT_REGIME_PCT:  # exactly +15% -> DROUGHT
        return "DROUGHT"
    if abs(pct) >= VOLATILE_REGIME_PCT:  # exactly +/-8% -> VOLATILE
        return "VOLATILE"
    return "STABLE"

# ---------------------------------------------------------------------------
# freight_charge (standalone; reused inside quote_pricing)
# ---------------------------------------------------------------------------

def find_freight_lane(origin_region_code, dest_region_code):
    for lane in store["freight_lanes"].values():
        if lane["origin_region_code"] == origin_region_code and lane["dest_region_code"] == dest_region_code:
            return lane
    return None


def freight_charge_cents(lane):
    base = max(D(lane["min_charge_cents"]),
               D(round0(D(lane["distance_miles"]) * D(lane["rate_per_mile_cents"]))))
    miles = lane["distance_miles"]
    if miles < 100:
        fuel_pct = D("0")
    elif miles < 300:  # 100..299 -> 6%
        fuel_pct = D("0.06")
    else:  # >= 300 -> 11%
        fuel_pct = D("0.11")
    surcharge = round0(base * fuel_pct)
    return int(base) + surcharge  # sum AFTER both parts rounded

# ---------------------------------------------------------------------------
# quote_pricing (SPOT / LOCKED variants)
# ---------------------------------------------------------------------------

def select_spot_index(origin_region_code, forage_type):
    """Latest MarketIndex (origin, forage) with effective_date <= current clock date."""
    today = get_clock().date()
    candidates = [
        idx for idx in store["market_indices"].values()
        if idx["region_code"] == origin_region_code
        and idx["forage_type"] == forage_type
        and idx["effective_date"] <= today
    ]
    if not candidates:
        raise ApiError(ERR_NO_MARKET_INDEX, 422,
                       "no market index effective on/before the current clock for this origin region and forage type")
    candidates.sort(key=lambda i: (i["effective_date"], i["_seq"]))
    return candidates[-1]


def compute_quote_pricing(quote_fields, variant):
    """variant: "SPOT" (latest index at current clock) or "LOCKED" (pinned index).
    Per-unit rounding BEFORE tonnage multiplication; freight summed after parts rounded."""
    if variant == "LOCKED":
        idx = store["market_indices"].get(quote_fields["pinned_market_index_id"])
        if idx is None:
            raise ApiError(ERR_NO_MARKET_INDEX, 422, "pinned market index is missing")
    else:
        idx = select_spot_index(quote_fields["origin_region_code"], quote_fields["forage_type"])
    lane = find_freight_lane(quote_fields["origin_region_code"], quote_fields["dest_region_code"])
    if lane is None:
        raise ApiError(ERR_NO_FREIGHT_LANE, 422,
                       "no freight lane exists for the origin/destination region pair")
    mult = TIER_MULTIPLIER[quote_fields["quality_tier"]]
    drought_factor = D("1") + DROUGHT_SURCHARGE_PCT if idx["drought_regime"] == "DROUGHT" else D("1")
    unit_price = round0(D(idx["price_per_ton_cents"]) * mult * drought_factor)
    commodity = round0(D(unit_price) * D(quote_fields["tons"]))  # integer math AFTER unit rounding
    freight = freight_charge_cents(lane)
    total = commodity + freight
    return {
        "index": idx,
        "unit_price_cents": unit_price,
        "commodity_cents": commodity,
        "freight_cents": freight,
        "total_cents": total,
    }

# ---------------------------------------------------------------------------
# shrink_tonnage (ACCOUNTING / PHYSICAL variants)
# ---------------------------------------------------------------------------

def full_months_between(harvested_date, clock_date):
    months = (clock_date.year - harvested_date.year) * 12 + (clock_date.month - harvested_date.month)
    if clock_date.day < harvested_date.day:
        months -= 1
    return max(0, months)


def shrink_tonnages(lot):
    """Returns (allocatable_tonnage, physical_tonnage), each rounded to 2dp
    half-up AFTER the full expression. ACCOUNTING = simple shrink; PHYSICAL =
    compound shrink floored at the 12% cap."""
    site = store["storage_sites"].get(lot["storage_site_id"])
    controlled = bool(site["moisture_controlled"]) if site else False
    rate = SHRINK_CONTROLLED_MONTHLY_PCT if controlled else SHRINK_MONTHLY_PCT
    months = full_months_between(lot["harvested_date"], get_clock().date())
    h = D(lot["harvested_tonnage"])
    simple_shrunk = h * (D("1") - min(SHRINK_CAP_PCT, D(months) * rate))
    compound_shrunk = h * (D("1") - rate) ** months
    compound_floor = h * (D("1") - SHRINK_CAP_PCT)
    if compound_shrunk < compound_floor:
        compound_shrunk = compound_floor
    allocatable = simple_shrunk - D(lot["spoilage_tonnage"]) - D(lot["shipped_tonnage"]) - D(lot["open_allocated_tonnage"])
    physical = compound_shrunk - D(lot["spoilage_tonnage"]) - D(lot["shipped_tonnage"])
    if allocatable < 0:
        allocatable = D("0")
    if physical < 0:
        physical = D("0")
    return round2(allocatable), round2(physical)


def allocatable_tonnage(lot):
    return shrink_tonnages(lot)[0]


def physical_tonnage(lot):
    return shrink_tonnages(lot)[1]

# ---------------------------------------------------------------------------
# storage_occupancy
# ---------------------------------------------------------------------------

def site_occupancy(site_id):
    """Sum of physical_tonnage over lots at the site in {ACTIVE, DEPLETED};
    CONDEMNED lots are pulled from storage."""
    lots = [
        lot for lot in store["bale_lots"].values()
        if lot["storage_site_id"] == site_id and lot["status"] in ("ACTIVE", "DEPLETED")
    ]
    occupied = sum((physical_tonnage(lot) for lot in lots), D("0"))
    return round2(occupied), len(lots)

# ---------------------------------------------------------------------------
# baling_service_billing
# ---------------------------------------------------------------------------

def baling_invoice_cents(actual_bale_count, baled_moisture_pct):
    c = actual_bale_count
    tier1 = min(c, BALE_TIER1_MAX)
    tier2 = min(max(c - BALE_TIER1_MAX, 0), BALE_TIER2_MAX - BALE_TIER1_MAX)
    tier3 = max(c - BALE_TIER2_MAX, 0)
    subtotal = tier1 * BALE_RATE_TIER1_CENTS + tier2 * BALE_RATE_TIER2_CENTS + tier3 * BALE_RATE_TIER3_CENTS
    # exactly 18.0 -> no surcharge
    wet = round0(D(subtotal) * WET_BALING_SURCHARGE_PCT) if D(baled_moisture_pct) > WET_BALING_MOISTURE_PCT else 0
    return max(MIN_BALING_CHARGE_CENTS, subtotal + wet)  # minimum applied LAST

# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def apply_release(allocation):
    """OPEN -> RELEASED: reserved tonnage returns to lot/contract/load; a
    LOADING load with zero OPEN allocations reverts to PLANNED."""
    if allocation["status"] != "OPEN":
        return
    tons = D(allocation["tons"])
    allocation["status"] = "RELEASED"
    touch(allocation)

    lot = store["bale_lots"].get(allocation["bale_lot_id"])
    if lot is not None:
        lot["open_allocated_tonnage"] = D(lot["open_allocated_tonnage"]) - tons
        touch(lot)
    contract = store["contracts"].get(allocation["contract_id"])
    if contract is not None:
        contract["open_allocated_tons"] = D(contract["open_allocated_tons"]) - tons
        touch(contract)
    load = store["delivery_loads"].get(allocation["delivery_load_id"])
    if load is not None:
        load["loaded_tons"] = D(load["loaded_tons"]) - tons
        remaining_open = any(
            a["status"] == "OPEN"
            for a in store["load_allocations"].values()
            if a["delivery_load_id"] == load["id"]
        )
        if load["logistics_status"] == "LOADING" and not remaining_open:
            load["logistics_status"] = "PLANNED"
        touch(load)


def cancel_open_allocations_for_contract(contract):
    for a in list(store["load_allocations"].values()):
        if a["contract_id"] == contract["id"] and a["status"] == "OPEN":
            apply_release(a)


def release_open_allocations_for_lot(lot):
    for a in list(store["load_allocations"].values()):
        if a["bale_lot_id"] == lot["id"] and a["status"] == "OPEN":
            apply_release(a)


def contract_close_side_effects(contract):
    """Shared by cancel and declare-default: release OPEN allocations, then
    release the buyer's credit reserve."""
    cancel_open_allocations_for_contract(contract)
    buyer = store["buyers"].get(contract["buyer_id"])
    if buyer is not None:
        buyer["credit_used_cents"] = buyer["credit_used_cents"] - contract["total_reserved_cents"]
        touch(buyer)

# ---------------------------------------------------------------------------
# Quote expiry sweep (lazy + bulk on clock advance)
# ---------------------------------------------------------------------------

def sweep_quote_if_expired(quote):
    """ISSUED quote whose expires_at the current clock has passed -> EXPIRED.
    Returns True if the quote transitioned."""
    if quote["status"] == "ISSUED" and quote["expires_at"] is not None and get_clock() > quote["expires_at"]:
        quote["status"] = "EXPIRED"
        touch(quote)
        return True
    return False


def sweep_all_quotes():
    for q in list(store["quotes"].values()):
        sweep_quote_if_expired(q)

# ---------------------------------------------------------------------------
# Delivery cascade (deliver) and grower settlement (settle)
# ---------------------------------------------------------------------------

def deliver_load(load):
    """IN_TRANSIT -> DELIVERED with the 3-hop cascade."""
    open_allocs = [
        a for a in store["load_allocations"].values()
        if a["delivery_load_id"] == load["id"] and a["status"] == "OPEN"
    ]
    open_allocs.sort(key=lambda a: (a["created_at"], a["_seq"]))
    touched_lots = {}
    touched_contracts = {}
    # Hop 1: allocations -> DELIVERED; shipped/delivered/open rebalanced.
    for a in open_allocs:
        tons = D(a["tons"])
        a["status"] = "DELIVERED"
        touch(a)
        lot = store["bale_lots"].get(a["bale_lot_id"])
        if lot is not None:
            lot["shipped_tonnage"] = D(lot["shipped_tonnage"]) + tons
            lot["open_allocated_tonnage"] = D(lot["open_allocated_tonnage"]) - tons
            touch(lot)
            touched_lots[lot["id"]] = lot
        contract = store["contracts"].get(a["contract_id"])
        if contract is not None:
            contract["delivered_tons"] = D(contract["delivered_tons"]) + tons
            contract["open_allocated_tons"] = D(contract["open_allocated_tons"]) - tons
            touch(contract)
            touched_contracts[contract["id"]] = contract
        load["loaded_tons"] = D(load["loaded_tons"]) - tons
    # Hop 2: contract fulfillment; lot depletion.
    fulfilled = []
    for contract in touched_contracts.values():
        if contract["status"] == "ACTIVE" and D(contract["delivered_tons"]) >= D(contract["committed_tons"]):
            contract["status"] = "FULFILLED"  # exact equality fulfills
            touch(contract)
            fulfilled.append(contract)
    for lot in touched_lots.values():
        if lot["status"] == "ACTIVE" and allocatable_tonnage(lot) == D("0.00") and D(lot["shipped_tonnage"]) > 0:
            lot["status"] = "DEPLETED"
            touch(lot)
    # Hop 3: credit reserve release on fulfillment.
    for contract in fulfilled:
        buyer = store["buyers"].get(contract["buyer_id"])
        if buyer is not None:
            buyer["credit_used_cents"] = buyer["credit_used_cents"] - contract["total_reserved_cents"]
            touch(buyer)
    load["logistics_status"] = "DELIVERED"
    touch(load)


def settle_load(load):
    """settlement_status OPEN -> SETTLED; grower_settlement per DELIVERED
    allocation in created_at ASC order (never by id)."""
    allocs = [
        a for a in store["load_allocations"].values()
        if a["delivery_load_id"] == load["id"] and a["status"] == "DELIVERED"
    ]
    allocs.sort(key=lambda a: (a["created_at"], a["_seq"]))
    for a in allocs:
        lot = store["bale_lots"].get(a["bale_lot_id"])
        contract = store["contracts"].get(a["contract_id"])
        grower = grower_of_lot(lot) if lot else None
        ytd = D(grower["settled_tons_ytd"]) if grower else D("0")  # BEFORE adding A
        if ytd < COMMISSION_TIER1_MAX_TONS:
            rate = COMMISSION_TIER1_PCT
        elif ytd < COMMISSION_TIER2_MAX_TONS:  # ytd exactly 500 -> 6%
            rate = COMMISSION_TIER2_PCT
        else:
            rate = COMMISSION_TIER3_PCT
        bonus = D("0")
        if lot is not None and lot["certified_protein_pct"] is not None \
                and D(lot["certified_protein_pct"]) >= PROTEIN_BONUS_THRESHOLD:
            bonus = PROTEIN_BONUS_PCT
        gross = round0(D(a["tons"]) * D(contract["unit_price_cents"]) * (D("1") + bonus))
        commission = round0(D(gross) * rate)  # commission on GROSS, never on net
        net = gross - commission
        a["settled_gross_cents"] = gross
        a["settled_commission_cents"] = commission
        a["settled_net_cents"] = net
        a["status"] = "SETTLED"
        touch(a)
        if grower is not None:
            grower["settled_tons_ytd"] = D(grower["settled_tons_ytd"]) + D(a["tons"])
            touch(grower)
    load["settlement_status"] = "SETTLED"
    touch(load)

# ---------------------------------------------------------------------------
# auto_allocation_waterfall
# ---------------------------------------------------------------------------

def auto_allocate(load):
    """Waterfall partial-load allocation. Returns the created allocations.
    Raises ERR_NO_ELIGIBLE_CONTRACT / ERR_NO_ELIGIBLE_LOT."""
    from errors import ERR_NO_ELIGIBLE_CONTRACT, ERR_NO_ELIGIBLE_LOT

    def remaining(c):
        return round2(D(c["committed_tons"]) - D(c["delivered_tons"]) - D(c["open_allocated_tons"]))

    eligible_contracts = [
        c for c in store["contracts"].values()
        if c["status"] == "ACTIVE" and remaining(c) > 0
    ]
    eligible_contracts.sort(key=lambda c: (c["delivery_deadline"], c["created_at"], c["_seq"]))
    if not eligible_contracts:
        raise ApiError(ERR_NO_ELIGIBLE_CONTRACT, 422,
                       "no ACTIVE contract with remaining tonnage exists")

    remaining_capacity = round2(D(load["capacity_tons"]) - D(load["loaded_tons"]))
    created = []
    for contract in eligible_contracts:
        if remaining_capacity <= 0:
            break
        take = min(remaining(contract), remaining_capacity)
        if take <= 0:
            continue
        lots = [
            lot for lot in store["bale_lots"].values()
            if lot["status"] == "ACTIVE"
            and lot["quality_tier"] == contract["quality_tier"]
            and allocatable_tonnage(lot) > 0
        ]
        lots.sort(key=lambda l: (l["harvested_date"], l["created_at"], l["_seq"]))
        for lot in lots:
            if take <= 0:
                break
            lot_take = min(allocatable_tonnage(lot), take)
            if lot_take <= 0:
                continue
            alloc = create_allocation(load, contract, lot, lot_take, bump_load_version=False)
            created.append(alloc)
            take -= lot_take
            remaining_capacity -= lot_take
    if not created:
        raise ApiError(ERR_NO_ELIGIBLE_LOT, 422,
                       "no ACTIVE graded lot matched any eligible contract's tier")
    touch(load)  # the operation increments the load's version by 1
    return created


def create_allocation(load, contract, lot, tons, bump_load_version=True):
    """Create an OPEN allocation and apply the three-place reservation."""
    from db import new_id, stamp_new

    alloc = stamp_new({
        "id": new_id(),
        "delivery_load_id": load["id"],
        "contract_id": contract["id"],
        "bale_lot_id": lot["id"],
        "tons": D(tons),
        "settled_gross_cents": None,
        "settled_commission_cents": None,
        "settled_net_cents": None,
        "status": "OPEN",
    })
    store["load_allocations"][alloc["id"]] = alloc
    lot["open_allocated_tonnage"] = D(lot["open_allocated_tonnage"]) + D(tons)
    touch(lot)
    contract["open_allocated_tons"] = D(contract["open_allocated_tons"]) + D(tons)
    touch(contract)
    load["loaded_tons"] = D(load["loaded_tons"]) + D(tons)
    if bump_load_version:
        touch(load)
    return alloc


def contract_remaining(contract):
    return round2(D(contract["committed_tons"]) - D(contract["delivered_tons"]) - D(contract["open_allocated_tons"]))
