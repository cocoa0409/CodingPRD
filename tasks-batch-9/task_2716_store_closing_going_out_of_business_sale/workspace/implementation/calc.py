"""Calculations, derivations and roll-ups (PRD 3.2 - 3.9)."""

from decimal import Decimal

import clock
import db
from money import ONE, ZERO, ceil_int, dec, floor_int, ratio4, round4, round_money

# --------------------------------------------------------------- constants

CATEGORY_SELL_THROUGH_RATE = {
    "APPAREL": Decimal("0.85"),
    "FOOTWEAR": Decimal("0.80"),
    "HOME": Decimal("0.70"),
    "ELECTRONICS": Decimal("0.95"),
    "JEWELRY": Decimal("0.60"),
    "SEASONAL": Decimal("0.90"),
}

CATEGORIES = tuple(sorted(CATEGORY_SELL_THROUGH_RATE))
SOURCES = ("ORIGINAL", "AUGMENTATION")

CLAIM_CODES = (
    "LOWEST_PRICES_EVER",
    "EVERYTHING_MUST_GO",
    "LOST_OUR_LEASE",
    "BELOW_COST",
    "FINAL_DAYS",
    "AUGMENTED_MERCHANDISE_DISCLOSURE",
)
PRICE_COMPARISON_CLAIMS = ("BELOW_COST", "LOWEST_PRICES_EVER")
DISCLOSURE_CLAIM = "AUGMENTED_MERCHANDISE_DISCLOSURE"

ESCALATION_BAND = Decimal("0.05")
ESCALATION_STEP_PCT = Decimal("0.05")
MAX_ESCALATION_PCT = Decimal("0.20")
MAX_DISCOUNT_PCT = Decimal("0.90")
MIN_ATTENDANCE_RATE = Decimal("0.90")
HOLDOVER_MULTIPLIER = Decimal("1.5")
MAX_NEGOTIATION_ROUNDS = 3
MAX_CONCURRENT_DELIVERIES = 2
RESTRICTED_AT = 1
FROZEN_AT = 3

FEE_TIER_TABLE = (
    (Decimal("0.60"), Decimal("0.0200")),
    (Decimal("0.80"), Decimal("0.0350")),
    (None, Decimal("0.0500")),
)

ENGAGEMENT_STATUSES = ("DRAFT", "PENDING_RETAILER_APPROVAL", "ACTIVE", "WIND_DOWN", "CLOSED")
STORE_STATUSES = ("PLANNED", "LICENSE_PENDING", "SELLING", "SUSPENDED", "CLOSED", "SURRENDERED")
SUSPENSION_REASONS = ("NONE", "LICENSE_REVOKED", "LICENSE_EXPIRED", "COMPLIANCE_HOLD")
LOT_STATUSES = ("ON_FLOOR", "SOLD_OUT", "RETURNED_TO_SUPPLIER")
CONSIGNMENT_STATUSES = ("PROPOSED", "DISCLOSURE_FILED", "RECEIVED", "RETURNED", "SOLD_OUT")
STAGE_STATUSES = ("ARMED", "ACTIVE", "CLOSED", "VOIDED")
LICENSE_STATUSES = ("APPLIED", "APPROVED", "DENIED", "EXPIRED", "REVOKED")
EMPLOYMENT_STATUSES = ("ACTIVE", "NOTICE_GIVEN", "TERMINATED_INVOLUNTARY", "TERMINATED_VOLUNTARY")
BONUS_STATUSES = ("PENDING", "EARNED", "PRORATED_EARNED", "FORFEITED", "PAID")
DAY_STATUSES = ("PENDING_REVIEW", "POSTED", "REJECTED")
EXPENSE_CATEGORIES = ("OCCUPANCY", "ADVERTISING", "PAYROLL", "SECURITY", "SUPPLIES", "PROFESSIONAL_FEES")
EXPENSE_STATUSES = ("SUBMITTED", "APPROVED", "VOIDED", "SETTLED")
DISPOSITION_STATUSES = ("DRAFT", "OFFER_SENT", "LANDLORD_COUNTERED", "AGREED", "REJECTED_FINAL", "SURRENDERED")
SETTLEMENT_BASES = ("PROVISIONAL", "FINAL")
SETTLEMENT_STATUSES = ("DRAFT", "PROPOSED", "DISPUTED", "ACCEPTED", "FINALIZED", "SUPERSEDED")
ECONOMICS_MODELS = ("GUARANTEED", "FEE_BASED", "HYBRID")
EXPENSE_RESPONSIBILITIES = ("LIQUIDATOR", "RETAILER", "SHARED")

PLANNED_STAGE_STATUSES = ("ARMED", "ACTIVE")
PROJECTING_LOT_STATUSES = ("ON_FLOOR", "SOLD_OUT")
CLOSED_STORE_STATUSES = ("CLOSED", "SURRENDERED")


def as_date(value):
    if value is None:
        return None
    return clock.parse_date(value)


def compliance_posture(strike_count):
    """PRD 2.8: OPEN at 0, RESTRICTED at 1-2, FROZEN at 3 or more."""
    if strike_count >= FROZEN_AT:
        return "FROZEN"
    if strike_count >= RESTRICTED_AT:
        return "RESTRICTED"
    return "OPEN"


# ------------------------------------------------------------- projections

def guaranty_amount(engagement):
    if engagement["economics_model"] == "FEE_BASED":
        return 0
    pct = engagement.get("guaranty_pct")
    if pct is None:
        return 0
    return round_money(dec(engagement["original_cost_value_cents"]) * dec(pct))


def planned_avg_discount(store_id):
    stages = [
        s
        for s in db.stages_of_store(store_id)
        if s["stage_status"] in PLANNED_STAGE_STATUSES
    ]
    if not stages:
        return Decimal("0.0000")
    total = sum((dec(s["discount_pct"]) for s in stages), ZERO)
    return round4(total / dec(len(stages)))


def recompute_store(store):
    """store_projected_recovery_estimate plus every other store-level derivation."""
    lots = db.lots_of_store(store["id"])
    for lot in lots:
        lot["units_on_hand"] = lot["units_initial"] - lot["units_sold"] - lot["units_returned"]
        net_units = lot["units_initial"] - lot["units_returned"]
        lot["cost_value_cents"] = net_units * lot["unit_cost_cents"]
        lot["retail_value_cents"] = net_units * lot["unit_retail_cents"]

    store["original_cost_value_cents"] = sum(
        lot["cost_value_cents"] for lot in lots if lot["source"] == "ORIGINAL"
    )
    store["augmentation_cost_value_cents"] = sum(
        lot["cost_value_cents"] for lot in lots if lot["source"] == "AUGMENTATION"
    )
    store["units_initial_total"] = sum(
        lot["units_initial"] - lot["units_returned"] for lot in lots
    )
    store["units_sold_total"] = sum(lot["units_sold"] for lot in lots)
    store["realized_sell_through_pct"] = ratio4(
        store["units_sold_total"], store["units_initial_total"]
    )
    store["augmentation_units_accounted"] = sum(
        lot["units_on_hand"] + lot["units_sold"] + lot["units_returned"]
        for lot in lots
        if lot["source"] == "AUGMENTATION"
    )

    planned = planned_avg_discount(store["id"])
    store["planned_avg_discount_pct"] = planned

    projected_total = 0
    for lot in lots:
        if lot["lot_status"] in PROJECTING_LOT_STATUSES:
            rate = CATEGORY_SELL_THROUGH_RATE[lot["category"]]
            net_units = lot["units_initial"] - lot["units_returned"]
            projected_units = floor_int(dec(net_units) * rate)
            amount = round_money(
                dec(projected_units) * dec(lot["unit_retail_cents"]) * (ONE - planned)
            )
            lot["projected_recovery_cents"] = amount
            projected_total += amount
        else:
            lot["projected_recovery_cents"] = 0
    store["projected_gross_recovery_cents"] = projected_total
    store["projected_recovery_ratio"] = ratio4(
        projected_total, store["original_cost_value_cents"]
    )

    posted = [
        d for d in db.sales_days_of_store(store["id"]) if d["day_status"] == "POSTED"
    ]
    store["realized_gross_recovery_cents"] = sum(d["net_sales_cents"] for d in posted)
    store["realized_recovery_ratio"] = ratio4(
        sum(d["original_net_sales_cents"] for d in posted),
        store["original_cost_value_cents"],
    )
    return store


def recompute_engagement(engagement):
    stores = db.stores_of_engagement(engagement["id"])
    engagement["original_cost_value_cents"] = sum(
        s["original_cost_value_cents"] for s in stores
    )
    engagement["guaranty_amount_cents"] = guaranty_amount(engagement)
    engagement["projected_gross_recovery_cents"] = sum(
        s["projected_gross_recovery_cents"] for s in stores
    )
    engagement["projected_shortfall_cents"] = max(
        0, engagement["guaranty_amount_cents"] - engagement["projected_gross_recovery_cents"]
    )

    posted = [
        d
        for d in db.sales_days_of_engagement(engagement["id"])
        if d["day_status"] == "POSTED"
    ]
    engagement["original_net_sales_cents"] = sum(
        d["original_net_sales_cents"] for d in posted
    )
    engagement["augmentation_net_sales_cents"] = sum(
        d["augmentation_net_sales_cents"] for d in posted
    )
    engagement["gross_recovery_cents"] = (
        engagement["original_net_sales_cents"] + engagement["augmentation_net_sales_cents"]
    )

    counted = [
        i
        for i in db.expense_items_of_engagement(engagement["id"])
        if i["expense_status"] in ("APPROVED", "SETTLED")
    ]
    engagement["expense_total_cents"] = sum(i["amount_cents"] for i in counted)
    engagement["expense_liquidator_share_cents"] = sum(
        i["liquidator_share_cents"] or 0 for i in counted
    )
    engagement["expense_retailer_share_cents"] = sum(
        i["retailer_share_cents"] or 0 for i in counted
    )

    engagement["retention_accrual_cents"] = sum(
        e["earned_bonus_cents"]
        for e in db.employees_of_engagement(engagement["id"])
        if e["bonus_status"] in ("EARNED", "PRORATED_EARNED", "PAID")
    )
    engagement["compliance_posture"] = compliance_posture(
        engagement["compliance_strike_count"]
    )
    return engagement


def recompute_chain(engagement):
    """Recompute the whole dependency spine of PRD 2.9 in dependency order."""
    for store in db.stores_of_engagement(engagement["id"]):
        recompute_store(store)
    recompute_engagement(engagement)
    return engagement


def engagement_of_store(store):
    return db.get("engagements", store["engagement_id"])


def jurisdiction_of_store(store):
    return db.get("jurisdictions", store["jurisdiction_id"])


# ---------------------------------------------------------- markdown stages

def escalation_for_shortfall(shortfall):
    """PRD 3.4: ceil(shortfall / band) steps, step size 0.05, capped at 0.20."""
    steps = ceil_int(dec(shortfall) / ESCALATION_BAND)
    raise_pct = dec(steps) * ESCALATION_STEP_PCT
    if raise_pct > MAX_ESCALATION_PCT:
        raise_pct = MAX_ESCALATION_PCT
    return round4(raise_pct)


def stages_overlapping(store_id, start, end, statuses=PLANNED_STAGE_STATUSES):
    """Half-open [start, end) overlap against existing stage windows."""
    out = []
    for stage in db.stages_of_store(store_id):
        if stage["stage_status"] not in statuses:
            continue
        existing_start = as_date(stage["window_start_date"])
        existing_end = as_date(stage["window_end_date"])
        if start < existing_end and existing_start < end:
            out.append(stage)
    return out


# ------------------------------------------------------------ licence rules

def license_covers_date(store, day):
    """An APPROVED licence of the store whose closed period covers `day`."""
    for lic in db.licenses_of_store(store["id"]):
        if lic["license_status"] != "APPROVED":
            continue
        if as_date(lic["period_start_date"]) <= day <= as_date(lic["period_end_date"]):
            return lic
    return None


def license_covers_window(store, window_start, window_end_exclusive):
    """PRD 3.4: period must cover window_start .. window_end - 1 day."""
    from datetime import timedelta

    last_selling_day = window_end_exclusive - timedelta(days=1)
    for lic in db.licenses_of_store(store["id"]):
        if lic["license_status"] != "APPROVED":
            continue
        if (
            as_date(lic["period_start_date"]) <= window_start
            and as_date(lic["period_end_date"]) >= last_selling_day
        ):
            return lic
    return None


def most_recent_non_denied_license(store_id):
    candidates = [
        lic
        for lic in db.licenses_of_store(store_id)
        if lic["license_status"] != "DENIED"
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda lic: (as_date(lic["period_end_date"]), db.order_key(lic)),
    )


# -------------------------------------------------------------- augmentation

def augmentation_cap_ratio(store, incoming_cost_cents):
    received_cost = 0
    returned_cost = 0
    for cons in db.consignments_of_store(store["id"]):
        if cons["consignment_status"] in ("RECEIVED", "SOLD_OUT"):
            received_cost += cons["cost_value_cents"]
        elif cons["consignment_status"] == "RETURNED":
            returned_cost += cons["units_returned"] * cons["unit_cost_cents"]
    post_receipt_cost = received_cost - returned_cost + incoming_cost_cents
    return ratio4(post_receipt_cost, store["original_cost_value_cents"])


def delivery_slot_available(store_id, start, end):
    """At most MAX_CONCURRENT_DELIVERIES closed windows may cover any one day."""
    from datetime import timedelta

    active = []
    for cons in db.consignments_of_store(store_id):
        if cons["consignment_status"] not in ("PROPOSED", "DISCLOSURE_FILED", "RECEIVED"):
            continue
        existing_start = as_date(cons["delivery_window_start_date"])
        existing_end = as_date(cons["delivery_window_end_date"])
        if existing_start <= end and start <= existing_end:
            active.append((existing_start, existing_end))
    if not active:
        return True
    probes = {start}
    for existing_start, _existing_end in active:
        if start <= existing_start <= end:
            probes.add(existing_start)
    for probe in probes:
        overlapping = sum(
            1 for s, e in active if s <= probe <= e
        )
        if overlapping >= MAX_CONCURRENT_DELIVERIES:
            return False
    return True


# ---------------------------------------------------------------- retention

def settle_retention_bonus(employee, settlement_day):
    """PRD 3.7 retention_bonus_settlement. Only PENDING rows should be passed in."""
    start = as_date(employee["retention_start_date"])
    target = as_date(employee["retention_target_date"])
    required_days = (target - start).days + 1
    served_days = (settlement_day - start).days + 1
    if served_days < 0:
        served_days = 0
    employee["served_days"] = served_days

    if employee["employment_status"] == "TERMINATED_VOLUNTARY":
        employee["bonus_status"] = "FORFEITED"
        employee["earned_bonus_cents"] = 0
        return employee
    if dec(employee["attendance_rate"]) < MIN_ATTENDANCE_RATE:
        employee["bonus_status"] = "FORFEITED"
        employee["earned_bonus_cents"] = 0
        return employee

    ratio = dec(served_days) / dec(required_days) if required_days > 0 else ZERO
    if ratio > ONE:
        ratio = ONE
    employee["earned_bonus_cents"] = round_money(dec(employee["retention_bonus_cents"]) * ratio)
    employee["bonus_status"] = "EARNED" if ratio == ONE else "PRORATED_EARNED"
    return employee


# ------------------------------------------------------------- sales days

def units_on_floor(store_id, source):
    return sum(
        lot["units_on_hand"]
        for lot in db.lots_of_store(store_id)
        if lot["source"] == source and lot["lot_status"] == "ON_FLOOR"
    )


def allocate_sales_day(store, day):
    """PRD 3.6 sales_day_unit_allocation: two waterfalls, ORIGINAL then AUGMENTATION."""
    notes = []
    plan = (
        ("ORIGINAL", day["original_units_sold"]),
        ("AUGMENTATION", day["augmentation_units_sold"]),
    )
    for source, units in plan:
        remaining = units
        if remaining <= 0:
            continue
        candidates = [
            lot
            for lot in db.lots_of_store(store["id"])
            if lot["source"] == source and lot["lot_status"] == "ON_FLOOR"
        ]
        candidates.sort(key=lambda lot: (lot["_created"], lot["category"], lot["_seq"]))
        for lot in candidates:
            if remaining <= 0:
                break
            take = min(remaining, lot["units_on_hand"])
            if take <= 0:
                continue
            lot["units_sold"] += take
            lot["units_on_hand"] = (
                lot["units_initial"] - lot["units_sold"] - lot["units_returned"]
            )
            net_units = lot["units_initial"] - lot["units_returned"]
            lot["cost_value_cents"] = net_units * lot["unit_cost_cents"]
            lot["retail_value_cents"] = net_units * lot["unit_retail_cents"]
            remaining -= take
            notes.append("%s:%d@%s" % (source, take, lot["id"]))
            if lot["units_on_hand"] == 0:
                lot["lot_status"] = "SOLD_OUT"
                consignment_id = lot.get("consignment_id")
                if consignment_id:
                    cons = db.get("consignments", consignment_id)
                    if cons is not None and cons["consignment_status"] == "RECEIVED":
                        cons["consignment_status"] = "SOLD_OUT"
                        db.touch(cons)
            db.touch(lot)
    return ";".join(notes)


# ---------------------------------------------------------------- expenses

def expense_responsibility_split(engagement, amount_cents):
    """PRD 3.7: liquidator side rounded once, retailer side is the remainder."""
    model = engagement["expense_responsibility"]
    if model == "LIQUIDATOR":
        liquidator = amount_cents
    elif model == "RETAILER":
        liquidator = 0
    else:
        pct = engagement.get("shared_expense_liquidator_pct") or ZERO
        liquidator = round_money(dec(amount_cents) * dec(pct))
    return liquidator, amount_cents - liquidator


# ------------------------------------------------------------------- lease

def lease_surrender_waterfall(lease, holdover_penalty_cents, fixture_sale_price_cents):
    """PRD 3.8: rent, then CAM, then restoration, then holdover."""
    available = fixture_sale_price_cents + lease["surrender_credit_cents"]
    claims = (
        ("allocated_rent_cents", lease["rent_arrears_cents"]),
        ("allocated_cam_cents", lease["cam_arrears_cents"]),
        ("allocated_restoration_cents", lease["restoration_cost_cents"]),
        ("allocated_holdover_cents", holdover_penalty_cents),
    )
    remaining = available
    allocations = {}
    allocated_total = 0
    claim_total = 0
    for field, claim in claims:
        claim_total += claim
        taken = min(remaining, claim)
        if taken < 0:
            taken = 0
        allocations[field] = taken
        allocated_total += taken
        remaining -= taken
    allocations["unpaid_landlord_balance_cents"] = claim_total - allocated_total
    allocations["residual_to_retailer_cents"] = max(0, available - claim_total)
    return allocations


def holdover_penalty(lease, holdover_days):
    return round_money(
        dec(lease["daily_holdover_rate_cents"]) * dec(holdover_days) * HOLDOVER_MULTIPLIER
    )


# -------------------------------------------------------------- settlement

def fee_rate_for_ratio(recovery_ratio):
    """PRD 3.9 step two: both tier boundaries belong to the higher band."""
    ratio = dec(recovery_ratio)
    for boundary, rate in FEE_TIER_TABLE:
        if boundary is None or ratio < boundary:
            return rate
    return FEE_TIER_TABLE[-1][1]


def settlement_inclusion_sets(engagement, basis):
    if basis == "FINAL":
        day_statuses = ("POSTED",)
        expense_statuses = ("APPROVED", "SETTLED")
    else:
        day_statuses = ("POSTED", "PENDING_REVIEW")
        expense_statuses = ("APPROVED", "SETTLED", "SUBMITTED")
    days = [
        d
        for d in db.sales_days_of_engagement(engagement["id"])
        if d["day_status"] in day_statuses
    ]
    items = [
        i
        for i in db.expense_items_of_engagement(engagement["id"])
        if i["expense_status"] in expense_statuses
    ]
    return days, items


def compute_settlement_split(settlement, engagement):
    """PRD 3.9: five pinned steps."""
    days, items = settlement_inclusion_sets(engagement, settlement["settlement_basis"])

    # step one -- inclusion sets
    original_net_sales = sum(d["original_net_sales_cents"] for d in days)
    gross_recovery = sum(d["net_sales_cents"] for d in days)

    # step two -- ratio, tier, fee
    recovery_ratio = ratio4(original_net_sales, engagement["original_cost_value_cents"])
    fee_rate = fee_rate_for_ratio(recovery_ratio)
    liquidator_fee = round_money(dec(gross_recovery) * fee_rate)

    # step three -- expenses, rounded once on the total for SHARED
    expense_total = sum(i["amount_cents"] for i in items)
    responsibility = engagement["expense_responsibility"]
    if responsibility == "LIQUIDATOR":
        liquidator_expense = expense_total
    elif responsibility == "RETAILER":
        liquidator_expense = 0
    else:
        pct = engagement.get("shared_expense_liquidator_pct") or ZERO
        liquidator_expense = round_money(dec(expense_total) * dec(pct))
    retailer_expense = expense_total - liquidator_expense

    # step four -- economics model
    guaranty = engagement["guaranty_amount_cents"]
    model = engagement["economics_model"]
    if model == "GUARANTEED":
        retailer_proceeds = guaranty - retailer_expense
    elif model == "FEE_BASED":
        retailer_proceeds = gross_recovery - liquidator_fee - retailer_expense
    else:
        excess = gross_recovery - liquidator_fee - guaranty
        if excess < 0:
            excess = 0
        share = round_money(
            dec(excess) * dec(engagement.get("hybrid_retailer_excess_pct") or ZERO)
        )
        retailer_proceeds = guaranty + share - retailer_expense

    # step five -- the residual identity
    liquidator_proceeds = gross_recovery - expense_total - retailer_proceeds

    settlement["gross_recovery_cents"] = gross_recovery
    settlement["original_net_sales_cents"] = original_net_sales
    settlement["recovery_ratio"] = recovery_ratio
    settlement["fee_rate"] = fee_rate
    settlement["liquidator_fee_cents"] = liquidator_fee
    settlement["guaranty_amount_cents"] = guaranty
    settlement["expense_total_cents"] = expense_total
    settlement["liquidator_expense_cents"] = liquidator_expense
    settlement["retailer_expense_cents"] = retailer_expense
    settlement["retailer_proceeds_cents"] = retailer_proceeds
    settlement["liquidator_proceeds_cents"] = liquidator_proceeds
    settlement["retention_accrual_cents"] = engagement["retention_accrual_cents"]
    return settlement


def economics_config_valid(model, guaranty_pct, hybrid_pct, responsibility, shared_pct):
    """PRD 3.1 coherence check."""
    if model in ("GUARANTEED", "HYBRID"):
        if guaranty_pct is None or dec(guaranty_pct) <= 0:
            return False
    else:
        if guaranty_pct is not None and dec(guaranty_pct) != 0:
            return False
    if model == "HYBRID":
        if hybrid_pct is None or dec(hybrid_pct) <= 0:
            return False
    else:
        if hybrid_pct is None or dec(hybrid_pct) != 0:
            return False
    if responsibility == "SHARED":
        if shared_pct is None or dec(shared_pct) <= 0:
            return False
    else:
        if shared_pct is None or dec(shared_pct) != 0:
            return False
    return True
