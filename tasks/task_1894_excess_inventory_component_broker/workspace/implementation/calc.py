"""Business calculations: pricing, volatility, carrying value, posture, exposure."""

from datetime import timedelta
from fractions import Fraction

from core import DB, now_dt, next_seq, touch, new_id

URGENCY_PREMIUM = {
    "STANDARD": Fraction(0),
    "PRIORITY": Fraction(1, 10),
    "CRITICAL": Fraction(1, 4),
}

VOLATILITY_DAMPENER_THRESHOLD = Fraction(1, 5)  # 0.20, strict >
VOLATILITY_DAMPENER_RATE = Fraction(3, 100)  # 0.03
WINDOW_SECONDS = 2592000  # 30 days
DEPRECIATION_HORIZON_DAYS = 365
BROKER_MARKET_HAIRCUT = Fraction(85, 100)  # 0.85
RECOMMENDED_MARGIN = Fraction(11, 10)  # 1.10

OPEN_EXPOSURE_STATUSES = (
    "PENDING_ESCROW",
    "ESCROW_FUNDED",
    "FULFILLING",
    "SHIPPED",
    "DELIVERED",
    "REFUND_PENDING",
)


def rhu(fr):
    """Round a non-negative Fraction half-up to an integer."""
    return (fr.numerator * 2 + fr.denominator) // (2 * fr.denominator)


# ------------------------- market price intelligence ------------------------
def latest_snapshot(mpn):
    cands = [s for s in DB.snapshots.values() if s["mpn"] == mpn]
    if not cands:
        return None
    return max(cands, key=lambda s: (s["observed_at"], s["created_at"], s["_seq"]))


def recommended_price_for_mpn(mpn):
    snap = latest_snapshot(mpn)
    if snap is None:
        return None
    return rhu(Fraction(snap["spot_price_cents"]) * RECOMMENDED_MARGIN)


def market_volatility_index(mpn, at):
    start = at - timedelta(seconds=WINDOW_SECONDS)
    window = [
        s["spot_price_cents"]
        for s in DB.snapshots.values()
        if s["mpn"] == mpn and start < s["observed_at"] <= at
    ]
    if len(window) < 2:
        return Fraction(0)
    lo, hi = min(window), max(window)
    return Fraction(hi - lo, lo)


# ------------------------------ lot posture ---------------------------------
def active_listings_for(lot_id):
    return [
        lst
        for lst in DB.listings.values()
        if lst["lot_id"] == lot_id and lst["status"] == "ACTIVE"
    ]


def lot_base_posture(lot):
    if (
        lot["qty_available"] == 0
        and lot["qty_reserved"] == 0
        and (lot["qty_sold"] + lot["qty_returned"]) > 0
    ):
        return "DEPLETED"
    if lot["qty_available"] == 0:
        return "FULLY_RESERVED"
    if active_listings_for(lot["id"]):
        return "LISTED"
    return "IN_STOCK"


def recompute_lot_posture(lot):
    """Recompute derived status; every recompute is a lot mutation."""
    if lot.get("_quarantined"):
        new_status = "QUARANTINED"
    else:
        new_status = lot_base_posture(lot)
    lot["status"] = new_status
    touch(lot)
    if new_status == "DEPLETED":
        for lst in active_listings_for(lot["id"]):
            lst["status"] = "SOLD_OUT"
            touch(lst)


# ---------------------------- carrying value --------------------------------
def lot_age_days(lot, at=None):
    at = at or now_dt()
    return (at - lot["received_at"]).days  # timedelta.days floors


def carrying_value_straight_line(lot):
    on_hand = lot["qty_available"] + lot["qty_reserved"]
    cost_total = lot["cost_basis_per_unit_cents"] * on_hand
    age = lot_age_days(lot)
    remaining = max(0, DEPRECIATION_HORIZON_DAYS - age)
    return rhu(Fraction(cost_total * remaining, DEPRECIATION_HORIZON_DAYS))


def carrying_value_market(lot):
    snap = latest_snapshot(lot["mpn"])
    if snap is None:
        return None
    on_hand = lot["qty_available"] + lot["qty_reserved"]
    return rhu(Fraction(snap["spot_price_cents"] * on_hand) * BROKER_MARKET_HAIRCUT)


# ------------------------------ bin occupancy -------------------------------
def bin_occupied_units(bin_id):
    total = 0
    for lot in DB.lots.values():
        if lot["storage_bin_id"] == bin_id and lot["status"] != "DEPLETED":
            total += lot["qty_available"] + lot["qty_reserved"]
    return total


# --------------------------- customer exposure ------------------------------
def customer_exposure(customer_id):
    return sum(
        o["required_escrow_cents"]
        for o in DB.orders.values()
        if o["customer_id"] == customer_id and o["status"] in OPEN_EXPOSURE_STATUSES
    )


# ----------------------------- seller balances ------------------------------
def lot_of_order(order):
    listing = DB.listings.get(order["listing_id"])
    if not listing:
        return None
    return DB.lots.get(listing["lot_id"])


def seller_payout_total(seller_id):
    total = 0
    for e in DB.escrow.values():
        if e["entry_type"] != "SELLER_PAYOUT":
            continue
        order = DB.orders.get(e["sales_order_id"])
        if not order:
            continue
        lot = lot_of_order(order)
        if not lot:
            continue
        offer = DB.offers.get(lot["buy_offer_id"])
        if offer and offer["seller_id"] == seller_id:
            total += -e["amount_cents"]
    return total


# -------------------------- consignment helpers -----------------------------
def current_agreement(lot_id, at=None):
    at = at or now_dt()
    for a in DB.agreements.values():
        if (
            a["lot_id"] == lot_id
            and a["status"] == "ACTIVE"
            and a["effective_from"] <= at < a["effective_to"]
        ):
            return a
    return None


# ------------------------------ escrow ledger -------------------------------
def escrow_entry(order_id, entry_type, amount_cents, note):
    e = {
        "id": new_id(),
        "created_at": now_dt(),
        "_seq": next_seq(),
        "sales_order_id": order_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "note": note,
    }
    DB.escrow[e["id"]] = e
    return e


# --------------------------- pricing calculations ---------------------------
def provisional_pricing(listing, customer, quantity):
    premium = URGENCY_PREMIUM[customer["urgency_tier"]]
    unit = rhu(Fraction(listing["asking_price_per_unit_cents"]) * (1 + premium))
    total = unit * quantity
    return unit, total, total  # unit, provisional_total, required_escrow


def age_discount(age_days):
    if age_days >= 180:
        return Fraction(12, 100)
    if age_days >= 90:
        return Fraction(5, 100)
    return Fraction(0)


def final_settlement_pricing(order, lot, at):
    age = (at - lot["received_at"]).days
    ad = age_discount(age)
    vol = market_volatility_index(lot["mpn"], at)
    vd = VOLATILITY_DAMPENER_RATE if vol > VOLATILITY_DAMPENER_THRESHOLD else Fraction(0)
    final_unit = rhu(Fraction(order["provisional_unit_price_cents"]) * (1 - ad) * (1 - vd))
    final_total = final_unit * order["quantity"]
    refund = order["provisional_total_cents"] - final_total
    return final_unit, final_total, refund


def escrow_split(final_total_cents, fee_bps):
    """Pinned rounding order: fee rounded half-up first, payout is the remainder."""
    fee = rhu(Fraction(final_total_cents * fee_bps, 10000))
    payout = final_total_cents - fee
    return fee, payout


def asking_price_floor(cost_basis_per_unit_cents):
    """floor(cost_basis x 0.80) in integer cents."""
    return (cost_basis_per_unit_cents * 4) // 5
