"""Calculation rules (SCAFFOLD Table 1.3 / PRD §3.5-§3.10).

All money is integer cents. Percentage terms are rounded half-up to whole cents
FIRST, then summed (PRD §2.7).
"""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value):
    """Round a numeric (int/float/Decimal) to a whole number of cents, half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pct_term(amount_cents, rate):
    """round_half_up(amount_cents * rate) using Decimal arithmetic."""
    result = (Decimal(int(amount_cents)) * Decimal(str(rate))).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(result)


# ---- bid_increment ---------------------------------------------------------
BAND1_MAX_CENTS = 500000
BAND2_MAX_CENTS = 1000000
INCR_BAND1 = 10000
INCR_BAND2 = 25000
INCR_BAND3 = 50000


def bid_increment(reference_price_cents):
    p = int(reference_price_cents)
    if p < BAND1_MAX_CENTS:
        return INCR_BAND1
    elif p < BAND2_MAX_CENTS:
        return INCR_BAND2
    else:
        return INCR_BAND3


# ---- clearing_price --------------------------------------------------------
def clearing_price(lot, consignment, lot_bids):
    """Return (high_bidder_id, high_bid_cents).

    lot_bids: list of bid dicts for this lot (append-only events).
    Each bid has buyer_id, ceiling_cents, created_at, _seq.
    """
    starting = int(lot.get("starting_bid_cents", 0))
    floor = int(consignment.get("floor_price_cents", 0))
    house_floor = max(starting, floor)

    if not lot_bids:
        return None, house_floor

    # Group by buyer: each buyer's effective ceiling = max ceiling_cents among
    # their bids; remember the qualifying bid's ordering key for tie-breaks.
    # The qualifying bid is the buyer's max-ceiling bid; if a buyer placed the
    # same max ceiling more than once, the earliest qualifying bid wins.
    per_buyer = {}  # buyer_id -> {"ceiling": int, "order": (seq,)}
    for b in lot_bids:
        bid_id = b["buyer_id"]
        ceiling = int(b["ceiling_cents"])
        order_key = b["_seq"]
        cur = per_buyer.get(bid_id)
        if cur is None or ceiling > cur["ceiling"] or (
            ceiling == cur["ceiling"] and order_key < cur["order"]
        ):
            per_buyer[bid_id] = {"ceiling": ceiling, "order": order_key}

    # Rank buyers by ceiling DESC, tie-break by earliest qualifying bid order ASC.
    ranked = sorted(
        per_buyer.items(),
        key=lambda kv: (-kv[1]["ceiling"], kv[1]["order"]),
    )

    b1_id, b1 = ranked[0]
    c1 = b1["ceiling"]

    if len(ranked) == 1:
        # single bidder: beat the house floor but never above own ceiling
        standing = min(c1, max(house_floor, starting))
        return b1_id, standing

    c2 = ranked[1][1]["ceiling"]
    second_ref = max(c2, house_floor)
    standing = min(c1, second_ref + bid_increment(second_ref))
    return b1_id, standing


# ---- sale_outcome ----------------------------------------------------------
def sale_outcome(high_bidder_id, high_bid_cents, reserve_price_cents):
    if high_bidder_id is None:
        return "PASSED"
    if int(high_bid_cents) >= int(reserve_price_cents):
        return "SOLD"
    return "IF"


# ---- buyer_fee -------------------------------------------------------------
STANDARD_FLOOR_FEE = 12500
STANDARD_MID_PCT = 0.06
STANDARD_HIGH_PCT = 0.04
STANDARD_HIGH_ADDON = 20000
PREMIUM_FLOOR_FEE = 17500
PREMIUM_MID_PCT = 0.08
PREMIUM_HIGH_PCT = 0.05
PREMIUM_HIGH_ADDON = 25000
ONLINE_SURCHARGE_PCT = 0.10
MID_BAND_FLOOR_CENTS = 200000
HIGH_BAND_FLOOR_CENTS = 1000000


def buyer_fee(sale_price_cents, schedule_code, channel):
    s = int(sale_price_cents)
    if schedule_code == "PREMIUM":
        if s < MID_BAND_FLOOR_CENTS:
            base = PREMIUM_FLOOR_FEE
        elif s < HIGH_BAND_FLOOR_CENTS:
            base = pct_term(s, PREMIUM_MID_PCT)
        else:
            base = pct_term(s, PREMIUM_HIGH_PCT) + PREMIUM_HIGH_ADDON
    else:  # STANDARD (default)
        if s < MID_BAND_FLOOR_CENTS:
            base = STANDARD_FLOOR_FEE
        elif s < HIGH_BAND_FLOOR_CENTS:
            base = pct_term(s, STANDARD_MID_PCT)
        else:
            base = pct_term(s, STANDARD_HIGH_PCT) + STANDARD_HIGH_ADDON

    if channel == "ONLINE":
        online = pct_term(base, ONLINE_SURCHARGE_PCT)
    else:
        online = 0
    return base + online


# ---- buyer_total_due -------------------------------------------------------
def buyer_total_due(sale_price_cents, buyer_fee_cents):
    return int(sale_price_cents) + int(buyer_fee_cents)


# ---- seller_net_proceeds ---------------------------------------------------
SELLER_FEE_CAP_CENTS = 150000
ASSURANCE_FEE_CENTS = 5000


def seller_net_proceeds(sale_price_cents, seller_fee_pct, as_is):
    s = int(sale_price_cents)
    commission = pct_term(s, seller_fee_pct)
    commission = min(commission, SELLER_FEE_CAP_CENTS)
    assurance = 0 if as_is else ASSURANCE_FEE_CENTS
    net = s - commission - assurance
    return max(net, 0)


# ---- arbitration_credit ----------------------------------------------------
MAX_CREDIT_PCT = 0.30


def arbitration_credit(claimed_cents, sale_price_cents, reason_code, as_is, grade):
    """Return (approved_cents, resolution)."""
    if as_is:
        return 0, "DENIED"
    q = int(claimed_cents)
    s = int(sale_price_cents)
    cap = pct_term(s, MAX_CREDIT_PCT)
    if q >= s:
        return s, "APPROVED_FULL"
    elif q <= cap:
        return q, "APPROVED_PARTIAL"
    else:
        return cap, "APPROVED_PARTIAL"
