"""Calculations and derived-field reconciliation (SCAFFOLD §1.3, PRD §3)."""
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

import clock
import db as store
from db import (LOT_LIVE_STATUSES, LOT_ROLLUP_STATUSES, RESERVING_STATUSES,
                active_quota, db, order_asc, order_desc, set_field)

D = Decimal
ZERO = Decimal(0)


def rh(value, places=0):
    """round half up to `places` decimals."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quant = Decimal(1).scaleb(-places)
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def rh_int(value):
    return int(rh(value, 0))


def floor_int(value):
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def ceil_int(value):
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.to_integral_value(rounding=ROUND_CEILING))


# ==========================================================================
# lot helpers
# ==========================================================================

def lot_age_days(lot, at=None):
    at = at or clock.now()
    delta = (at - lot["first_received_at"]).total_seconds()
    if delta <= 0:
        return 0
    return int(delta // 86400)


def bucket_for(age_days):
    if age_days >= 365:
        return "OVER_365"
    if age_days >= 271:
        return "D271_365"
    if age_days >= 181:
        return "D181_270"
    return "UNDER_181"


def billable_units(lot):
    return lot["fulfillable_units"] + lot["unfulfillable_units"] + lot["units_reserved_for_removal"]


def settle_lot_status(lot):
    """InventoryLot lot_status dimension (PRD §3.6)."""
    live = billable_units(lot)
    if lot["units_received_total"] >= 1 and live == 0:
        set_field(lot, "lot_status", "DEPLETED")
    elif lot["lot_status"] == "ACTIVE" and lot["units_removed"] >= 1 and live >= 1:
        set_field(lot, "lot_status", "PARTIALLY_REMOVED")


# ==========================================================================
# derived-field reconciliation
# ==========================================================================

def recompute_lot_fees(lot):
    rows = order_asc([a for a in db.assessments.values()
                      if a["inventory_lot_id"] == lot["id"]])
    set_field(lot, "storage_fee_accrued_cents", sum(a["total_fee_cents"] for a in rows))
    set_field(lot, "ltsf_exposed", bool(rows) and rows[-1]["ltsf_surcharge_cents"] > 0)


def recompute_listing(listing):
    """calculation listing_health_recompute (PRD §3.2)."""
    lots = store.listing_lots(listing["id"])
    live = [l for l in lots if l["lot_status"] in LOT_LIVE_STATUSES]
    rollup = [l for l in lots if l["lot_status"] in LOT_ROLLUP_STATUSES]

    fulfillable = sum(l["fulfillable_units"] for l in live)
    unfulfillable = sum(l["unfulfillable_units"] for l in live)
    missing = sum(l["missing_units"] for l in rollup)
    aged = sum(l["fulfillable_units"] + l["unfulfillable_units"]
               for l in live if l["aged_bucket"] == "OVER_365")

    set_field(listing, "fulfillable_units", fulfillable)
    set_field(listing, "unfulfillable_units", unfulfillable)
    set_field(listing, "missing_units", missing)
    set_field(listing, "aged_over_365_units", aged)
    if lots:
        set_field(listing, "lot_ever_created", True)

    if fulfillable == 0 and unfulfillable >= 1:
        health = "STRANDED"
    elif fulfillable == 0:
        health = "OUT_OF_STOCK"
    elif aged >= 1:
        health = "EXCESS_AGED"
    else:
        health = "HEALTHY"
    set_field(listing, "inventory_health", health)

    if fulfillable == 0 and listing["lot_ever_created"]:
        set_field(listing, "listing_status", "SUPPRESSED")
        if missing >= 1:
            reason = "MISSING_INVENTORY"
        elif unfulfillable >= 1:
            reason = "STRANDED_INVENTORY"
        else:
            reason = "ZERO_FULFILLABLE"
        set_field(listing, "suppression_reason", reason)
    # otherwise listing_status / suppression_reason are left untouched:
    # suppression clears only through the reinstate endpoint.


def recompute_seller(seller):
    seller_id = seller["id"]
    listings = store.seller_listings(seller_id)
    listing_ids = {l["id"] for l in listings}
    plans = store.seller_plans(seller_id)
    lots = [l for l in db.lots.values() if l["sku_listing_id"] in listing_ids]
    lot_ids = {l["id"] for l in lots}

    set_field(seller, "restock_reserved_units",
              sum(p["allocated_units"] for p in plans if p["status"] in RESERVING_STATUSES))
    set_field(seller, "open_discrepancy_units",
              sum(l["missing_units"] for l in lots
                  if l["reconciliation_status"] in ("DISCREPANCY_OPEN", "DISCREPANCY_CLAIMED")))
    set_field(seller, "suppressed_listing_count",
              sum(1 for l in listings if l["listing_status"] == "SUPPRESSED"))
    set_field(seller, "storage_fee_accrued_cents",
              sum(a["total_fee_cents"] for a in db.assessments.values()
                  if a["inventory_lot_id"] in lot_ids))
    set_field(seller, "reimbursement_credit_cents",
              sum(c["reimbursement_amount_cents"] for c in db.claims.values()
                  if c["inventory_lot_id"] in lot_ids and c["status"] == "APPROVED"))
    set_field(seller, "mcf_fee_accrued_cents",
              sum(o["mcf_fee_cents"] for o in db.mcf_orders.values()
                  if o["sku_listing_id"] in listing_ids and o["order_status"] == "MCF_SHIPPED"))

    # calculation storage_utilization_ratio
    total = ZERO
    for lot in lots:
        if lot["lot_status"] not in LOT_LIVE_STATUSES:
            continue
        listing = db.listings.get(lot["sku_listing_id"])
        if listing is None:
            continue
        total += rh(D(billable_units(lot)) * listing["unit_cubic_feet"], 4)
    entitlement = seller["storage_cubic_feet_entitlement"]
    if entitlement and entitlement != ZERO:
        ratio = rh(total / entitlement, 4)
    else:
        ratio = rh(ZERO, 4)
    set_field(seller, "storage_utilization_ratio", ratio)


def recompute_fc(fc):
    set_field(fc, "committed_receiving_units",
              sum(p["declared_units"] for p in db.plans.values()
                  if p["destination_fc_id"] == fc["id"] and p["status"] in RESERVING_STATUSES))


def recompute_all():
    """Derived fields are never caches that lag: reconcile everything in-request."""
    for lot in db.lots.values():
        recompute_lot_fees(lot)
    for listing in db.listings.values():
        recompute_listing(listing)
    for seller in db.sellers.values():
        recompute_seller(seller)
    # The performance score is a pure function of the quota's inputs, its
    # downgrade steps and the seller's open_discrepancy_units, so re-deriving it
    # here is idempotent: it only moves when that discrepancy figure moved,
    # which is exactly when PRD §3.1 requires a re-score.
    for seller in db.sellers.values():
        rescore_active_quota(seller)
    for fc in db.fcs.values():
        recompute_fc(fc)


# ==========================================================================
# calculation iprs_and_restock_limit
# ==========================================================================

TIER_ORDER = ("TIER_ELEVATED", "TIER_STANDARD", "TIER_RESTRICTED")
TIER_MULTIPLIER = {
    "TIER_ELEVATED": D("3.0"),
    "TIER_STANDARD": D("1.5"),
    "TIER_RESTRICTED": D("0.5"),
}


def run_iprs(quota):
    seller = db.sellers.get(quota["seller_account_id"])
    if seller is None:
        return

    sell_through = quota["sell_through_rate"]
    excess = quota["excess_units_ratio"]
    stranded = quota["stranded_ratio"]
    in_stock = quota["in_stock_rate"]

    comp = (D("0.40") * min(D(1), sell_through / D("2.5"))
            + D("0.25") * (D(1) - min(D(1), excess / D("0.30")))
            + D("0.20") * (D(1) - min(D(1), stranded / D("0.10")))
            + D("0.15") * in_stock)
    score = rh_int(D(1000) * comp)

    penalty = 0
    if stranded > D("0.05"):
        penalty += 75
    if seller["open_discrepancy_units"] > 500:
        penalty += 50
    iprs = max(0, score - penalty)

    if iprs >= 800:
        base_tier = "TIER_ELEVATED"
    elif iprs >= 500:
        base_tier = "TIER_STANDARD"
    else:
        base_tier = "TIER_RESTRICTED"

    steps = quota["capacity_tier_downgrade_steps"]
    index = min(len(TIER_ORDER) - 1, TIER_ORDER.index(base_tier) + max(0, steps))
    effective = TIER_ORDER[index]
    limit = floor_int(D(quota["base_capacity_units"]) * TIER_MULTIPLIER[effective])

    set_field(quota, "iprs_score", iprs)
    set_field(quota, "base_capacity_tier", base_tier)
    set_field(quota, "capacity_tier", effective)
    set_field(quota, "restock_limit_units", limit)
    set_field(seller, "seller_status", "SUSPENDED" if iprs < 200 else "ACTIVE")


def rescore_active_quota(seller):
    quota = active_quota(seller["id"])
    if quota is not None:
        run_iprs(quota)


# ==========================================================================
# calculation restock_allocation
# ==========================================================================

def _committed_charge(plan):
    return sum(p["allocated_units"] for p in store.seller_plans(plan["seller_account_id"])
               if p["id"] != plan["id"] and p["status"] in RESERVING_STATUSES)


def _sibling_draft_charge(plan):
    return sum(p["provisional_allocated_units"] for p in store.seller_plans(plan["seller_account_id"])
               if p["id"] != plan["id"] and p["status"] == "DRAFT")


def _waterfall(plan, pool):
    remaining = pool
    grants = []
    for line in store.plan_lines(plan["id"]):
        grant = min(line["units"], remaining)
        grants.append((line, grant))
        remaining -= grant
    return grants


def _limit_units(plan):
    quota = active_quota(plan["seller_account_id"])
    return quota["restock_limit_units"] if quota is not None else 0


def run_provisional(plan):
    pool = max(0, _limit_units(plan) - _committed_charge(plan) - _sibling_draft_charge(plan))
    grants = _waterfall(plan, pool)
    total = 0
    for line, grant in grants:
        set_field(line, "provisional_allocated_units", grant)
        total += grant
    set_field(plan, "provisional_allocated_units", total)
    set_field(plan, "allocation_status",
              "WITHIN_LIMIT" if total == plan["declared_units"] else "OVER_LIMIT")


def compute_final(plan):
    pool = max(0, _limit_units(plan) - _committed_charge(plan))
    grants = _waterfall(plan, pool)
    return grants, sum(g for _, g in grants)


def refresh_sibling_drafts(plan):
    for other in order_asc(store.seller_plans(plan["seller_account_id"])):
        if other["id"] == plan["id"] or other["status"] != "DRAFT":
            continue
        run_provisional(other)


# ==========================================================================
# calculation velocity_forecast
# ==========================================================================

def run_velocity_forecast(listing, payload):
    variant = payload["forecast_variant"]
    trailing = D(payload["trailing_30_units_sold"])
    prior = D(payload["prior_year_same_period_units_sold"])
    index = payload["seasonal_index"]

    if variant == "TRAILING_30":
        daily = rh(trailing / D(30), 4)
    else:
        numerator = D("0.60") * trailing + D("0.40") * prior * index
        daily = rh(numerator / D(30), 4)

    horizon = payload["coverage_target_days"] + payload["lead_time_days"]
    target_units = ceil_int(daily * D(horizon))

    in_flight = 0
    for line in db.line_items.values():
        if line["sku_listing_id"] != listing["id"]:
            continue
        plan = db.plans.get(line["shipment_plan_id"])
        if plan is not None and plan["status"] in RESERVING_STATUSES:
            in_flight += line["units"]

    quota = active_quota(listing["seller_account_id"])
    if quota is None:
        headroom = 0
    else:
        headroom = max(0, quota["restock_limit_units"] - quota["utilized_units"])

    raw_need = max(0, target_units - listing["fulfillable_units"] - in_flight)
    recommended = min(raw_need, headroom)
    stranded_risk = (listing["unfulfillable_units"] > 0
                     or (daily == rh(ZERO, 4) and listing["fulfillable_units"] > 0))

    return {
        "daily_velocity": daily,
        "target_units": target_units,
        "in_flight_units": in_flight,
        "quota_headroom_units": headroom,
        "recommended_replenishment_units": recommended,
        "stranded_risk_flag": stranded_risk,
    }


# ==========================================================================
# calculation mcf_fee_quote
# ==========================================================================

ZONE_BASE_CENTS = {"ZONE_1": 380, "ZONE_2": 458, "ZONE_3": 540}
WEIGHT_CENTS_PER_LB = D(42)


def run_mcf_quote(units, billable_weight_lb, destination_zone, self_fulfilled_cost_cents, at=None):
    at = at or clock.now()
    base = ZONE_BASE_CENTS[destination_zone]
    overweight = billable_weight_lb - D(1)
    if overweight < ZERO:
        overweight = ZERO
    per_unit = base + rh_int(overweight * WEIGHT_CENTS_PER_LB)
    gross = per_unit * units
    is_peak = at.month in (10, 11, 12)
    peak_surcharge = rh_int(D(gross) * D("0.08")) if is_peak else 0
    pre_discount = gross + peak_surcharge

    if pre_discount >= 100000:
        pct = D("0.10")
    elif pre_discount >= 50000:
        pct = D("0.06")
    elif pre_discount >= 20000:
        pct = D("0.03")
    else:
        pct = D("0.00")
    discount = rh_int(D(pre_discount) * pct)
    fee = pre_discount - discount
    advantage = self_fulfilled_cost_cents - fee
    return {
        "is_peak_period": is_peak,
        "mcf_fee_cents": fee,
        "fee_advantage_cents": advantage,
        "recommended_channel": "MCF" if advantage >= 0 else "SELF_FULFILLED",
    }


# ==========================================================================
# calculation lot_selection
# ==========================================================================

def _rank(rows):
    return sorted(rows, key=lambda l: (l["first_received_at"], l["created_at"], l["_seq"]))


def select_receive_lot(sku_listing_id, fc_id):
    candidates = [l for l in db.lots.values()
                  if l["sku_listing_id"] == sku_listing_id
                  and l["fulfillment_center_id"] == fc_id
                  and l["lot_status"] in LOT_LIVE_STATUSES]
    if candidates:
        return _rank(candidates)[0]
    return None


def mcf_draw_plan(sku_listing_id, units):
    candidates = []
    for lot in db.lots.values():
        if lot["sku_listing_id"] != sku_listing_id:
            continue
        if lot["lot_status"] not in LOT_LIVE_STATUSES:
            continue
        if lot["fulfillable_units"] < 1:
            continue
        fc = db.fcs.get(lot["fulfillment_center_id"])
        if fc is not None and fc["receiving_status"] == "SUSPENDED":
            continue
        candidates.append(lot)

    remaining = units
    plan = []
    for lot in _rank(candidates):
        if remaining == 0:
            break
        draw = min(lot["fulfillable_units"], remaining)
        plan.append((lot, draw))
        remaining -= draw
    if remaining > 0:
        return None
    return plan


# ==========================================================================
# calculation removal_settlement
# ==========================================================================

REMOVAL_FEES = {
    "DISPOSAL": (100, 15),
    "RETURN_TO_SELLER": (200, 50),
    "LIQUIDATION": (0, 25),
}
LIQUIDATION_RECOVERY_CAP_CENTS_PER_UNIT = 120


def run_removal_settlement(removal, listing):
    units = removal["requested_units"]
    base, per_unit = REMOVAL_FEES[removal["removal_method"]]
    fee = base + units * per_unit
    if removal["removal_method"] == "LIQUIDATION":
        recovery = min(rh_int(D(units) * D(listing["unit_cost_cents"]) * D("0.05")),
                       units * LIQUIDATION_RECOVERY_CAP_CENTS_PER_UNIT)
    else:
        recovery = 0
    return fee, recovery, recovery - fee


# ==========================================================================
# calculation reimbursement_settlement
# ==========================================================================

CLAIM_POOL_FIELD = {
    "LOST_INBOUND": "missing_units",
    "DAMAGED_WAREHOUSE": "unfulfillable_units",
    "LOST_REMOVAL": "units_removed",
}
CLAIM_TYPE_FACTOR = {
    "LOST_INBOUND": D("1.00"),
    "DAMAGED_WAREHOUSE": D("0.90"),
    "LOST_REMOVAL": D("0.80"),
}
CLAIM_ANCHOR_FIELD = {
    "LOST_INBOUND": "discrepancy_opened_at",
    "DAMAGED_WAREHOUSE": "unfulfillable_recorded_at",
    "LOST_REMOVAL": "last_removal_completed_at",
}
CLAIM_EVIDENCE_MIN = {
    "LOST_INBOUND": 2,
    "DAMAGED_WAREHOUSE": 3,
    "LOST_REMOVAL": 2,
}
FILING_WINDOW_DAYS = 60


def claim_pool_units(lot, claim_type):
    return lot[CLAIM_POOL_FIELD[claim_type]]


def run_reimbursement_settlement(claim, lot, listing, seller):
    pool = claim_pool_units(lot, claim["claim_type"])
    eligible = min(claim["claimed_units"], pool)
    per_unit_value = min(listing["unit_cost_cents"], seller["unit_cost_cap_cents"])
    factor = CLAIM_TYPE_FACTOR[claim["claim_type"]]
    amount = rh_int(D(eligible) * D(per_unit_value) * factor)
    return eligible, amount


# ==========================================================================
# calculation storage_fee_assessment
# ==========================================================================

def assess_lot(lot, listing, fc, at, sequence):
    age_days = lot_age_days(lot, at)
    bucket = bucket_for(age_days)
    units = billable_units(lot)
    cubic_feet = rh(D(units) * listing["unit_cubic_feet"], 4)
    monthly = rh_int(cubic_feet * D(fc["monthly_storage_rate_cents_per_cubic_foot"]))
    if bucket == "OVER_365":
        steps = 2
    elif bucket == "D271_365":
        steps = 1
    else:
        steps = 0
    surcharge = rh_int(cubic_feet * D(fc["ltsf_rate_cents_per_cubic_foot"]) * D(steps))
    row = store.new_row(with_common=False)
    row.update({
        "inventory_lot_id": lot["id"],
        "billing_run_sequence": sequence,
        "assessed_at": at,
        "age_days_at_assessment": age_days,
        "aged_bucket": bucket,
        "billable_cubic_feet": cubic_feet,
        "monthly_storage_fee_cents": monthly,
        "ltsf_surcharge_cents": surcharge,
        "total_fee_cents": monthly + surcharge,
    })
    set_field(lot, "aged_bucket", bucket)
    return row
