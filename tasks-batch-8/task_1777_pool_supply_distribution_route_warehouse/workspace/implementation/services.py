"""Business logic: calculations, FEFO allocation, backorder waterfall, posture, tiers."""
from decimal import Decimal

from db import db, next_seq
from util import new_id, now_ts, round_half_up

# ---------------------------------------------------------------------------
# Constants (scaffold §1.3)
# ---------------------------------------------------------------------------
TIER_DISCOUNT = {"PRO": Decimal("0.00"), "ELITE": Decimal("0.05"), "PREMIER": Decimal("0.10")}
TIER_RANK = {"PRO": 0, "ELITE": 1, "PREMIER": 2}
TIER_ELITE_CENTS = 2000000
TIER_PREMIER_CENTS = 5000000

FREIGHT_FREE_MIN_CENTS = 50000
FREIGHT_BASE_CENTS = 2500
FREIGHT_HAZMAT_SURCHARGE_CENTS = 1800
FREIGHT_SHORTFALL_CAP_CENTS = 7500

FLAT_LABOR_HOURS = 2
LABOR_CAP_HOURS = 6
RESTOCK_PCT = Decimal("0.15")

BACKORDER_PRIORITY = {"PREMIER": 1, "ELITE": 2, "PRO": 3}


# ---------------------------------------------------------------------------
# Record lifecycle (PRD 2.4): version starts at 1, +1 on every mutation.
# ---------------------------------------------------------------------------

def new_record(collection, fields):
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = now_ts()
    rec["updated_at"] = rec["created_at"]
    rec["version"] = 1
    rec["_seq"] = next_seq()
    db[collection][rec["id"]] = rec
    return rec


def new_child_record(collection, fields):
    """OrderLine: id + created_at only (no updated_at / version)."""
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = now_ts()
    rec["_seq"] = next_seq()
    db[collection][rec["id"]] = rec
    return rec


def touch(rec):
    rec["updated_at"] = now_ts()
    rec["version"] = rec.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Stock lots
# ---------------------------------------------------------------------------

def lot_available(lot) -> int:
    return lot["qty_on_hand"] - lot["qty_reserved_willcall"] - lot["qty_reserved_route"]


def reserve_bucket_for_channel(channel) -> str:
    return "qty_reserved_willcall" if channel == "WILL_CALL" else "qty_reserved_route"


def fefo_allocate(branch_id, product_id, qty):
    """FEFO lot pick for a confirm-time line allocation (PRD 3.4).

    All-or-nothing: only a lot able to cover the FULL line quantity is picked
    (earliest expiry ASC, expiring lots before non-expiring, created_at ASC
    tie-break) -> full grant. A line no single lot can cover goes short:
    (None, 0) so the caller leaves allocated_qty zero and backorders the full
    qty. Returns (lot_or_None, grant).
    """
    lots = [
        l for l in db["stock_lots"].values()
        if l["branch_id"] == branch_id and l["product_id"] == product_id
    ]

    def key(l):
        return (l["expiry_date"] is None, l["expiry_date"] or "", l["_seq"])

    full = sorted((l for l in lots if lot_available(l) >= qty), key=key)
    if full:
        return full[0], qty
    return None, 0


# ---------------------------------------------------------------------------
# Branch posture & seasonal pool (computed on read — PRD 2.7, entities.Branch)
# ---------------------------------------------------------------------------

def compute_posture(branch_id) -> str:
    for p in db["products"].values():
        open_units = sum(
            b["qty_open"]
            for b in db["backorder_requests"].values()
            if b["branch_id"] == branch_id
            and b["product_id"] == p["id"]
            and b["status"] == "OPEN"
        )
        if open_units >= p["shortage_freeze_threshold"]:
            return "FROZEN"
    for p in db["products"].values():
        floor = p["low_stock_floor"]
        if floor > 0:
            avail = sum(
                lot_available(l)
                for l in db["stock_lots"].values()
                if l["branch_id"] == branch_id and l["product_id"] == p["id"]
            )
            if avail <= floor:
                return "CONSTRAINED"
    return "NORMAL"


def compute_pool_units(branch_id) -> int:
    program_ids = {
        p["id"] for p in db["seasonal_programs"].values() if p["branch_id"] == branch_id
    }
    return sum(
        c["committed_units"]
        for c in db["seasonal_commitments"].values()
        if c["program_id"] in program_ids and c["status"] == "COMMITTED"
    )


# ---------------------------------------------------------------------------
# Pricing (order_pricing), freight (freight_charge), tiers (account_tier_recompute)
# ---------------------------------------------------------------------------

def price_line(product, tier, seasonal_pct, qty):
    """Per-line pinned pricing order: base -> tier factor -> seasonal factor ->
    round extended half up PER LINE -> unit derived FROM the rounded line."""
    base = Decimal(product["base_price_cents"])
    t = TIER_DISCOUNT[tier]
    s = (Decimal(str(seasonal_pct)) / Decimal("100")) if seasonal_pct else Decimal("0")
    unit_unrounded = base * (1 - t) * (1 - s)
    extended = round_half_up(unit_unrounded * qty)
    unit = round_half_up(Decimal(extended) / Decimal(qty))
    return unit, extended


def freight_charge(order, lines) -> int:
    """Order-level threshold freight. WILL_CALL -> 0. Hazmat counts toward the minimum."""
    if order["channel"] == "WILL_CALL":
        return 0
    subtotal = order["order_subtotal_cents"]
    if subtotal >= FREIGHT_FREE_MIN_CENTS:
        return 0
    hazmat_any = any(
        db["products"][l["product_id"]]["hazmat_class"] != "NONE" for l in lines
    )
    shortfall = FREIGHT_FREE_MIN_CENTS - subtotal
    shortfall_fee = min(shortfall, FREIGHT_SHORTFALL_CAP_CENTS)
    return FREIGHT_BASE_CENTS + (FREIGHT_HAZMAT_SURCHARGE_CENTS if hazmat_any else 0) + shortfall_fee


def tier_for_volume(ytd_volume_cents) -> str:
    if ytd_volume_cents >= TIER_PREMIER_CENTS:
        return "PREMIER"
    if ytd_volume_cents >= TIER_ELITE_CENTS:
        return "ELITE"
    return "PRO"


def ratchet_tier(account):
    """Tier never decreases."""
    new_tier = tier_for_volume(account["ytd_volume_cents"])
    if TIER_RANK[new_tier] > TIER_RANK[account["tier"]]:
        account["tier"] = new_tier


# ---------------------------------------------------------------------------
# Backorder waterfall (backorder_waterfall_allocation)
# ---------------------------------------------------------------------------

def create_backorder(branch_id, line, order, qty):
    return new_record("backorder_requests", {
        "branch_id": branch_id,
        "order_line_id": line["id"],
        "product_id": line["product_id"],
        "account_id": order["account_id"],
        "qty_open": qty,
        "qty_original": qty,
        "priority_rank": BACKORDER_PRIORITY[order["tier_at_confirm"]],
        "superseded_by_id": None,
        "status": "OPEN",
    })


def order_line_order(line):
    return db["orders"][line["order_id"]]


def _grant_on_lot(lot, backorder, grant):
    line = db["order_lines"][backorder["order_line_id"]]
    order = order_line_order(line)
    lot[reserve_bucket_for_channel(order["channel"])] += grant
    backorder["qty_open"] -= grant
    # Track where the reservation sits so an order-cancel rollback can release it.
    backorder["_reservation_lot_id"] = lot["id"]
    backorder["_granted_units"] = backorder.get("_granted_units", 0) + grant
    backorder["status"] = "CLOSED" if backorder["qty_open"] == 0 else "ALLOCATED"
    touch(backorder)


def sweep_backorders_for_lot(lot):
    """Automatic waterfall over OPEN backorders matching (product, branch).

    Ranking: priority_rank ASC (snapshot), then created_at ASC (_seq). UUID id
    is never a ranking key. ALLOCATED-with-residual requests do NOT re-enter.
    """
    candidates = sorted(
        (
            b for b in db["backorder_requests"].values()
            if b["product_id"] == lot["product_id"]
            and b["branch_id"] == lot["branch_id"]
            and b["status"] == "OPEN"
        ),
        key=lambda b: (b["priority_rank"], b["_seq"]),
    )
    available = lot_available(lot)
    for b in candidates:
        if available <= 0:
            break
        grant = min(b["qty_open"], available)
        _grant_on_lot(lot, b, grant)
        available -= grant


# ---------------------------------------------------------------------------
# Seasonal program settle (close / branch close-season cascade)
# ---------------------------------------------------------------------------

def settle_program_commitments(program):
    for c in db["seasonal_commitments"].values():
        if c["program_id"] == program["id"] and c["status"] == "COMMITTED":
            c["status"] = (
                "FULFILLED" if c["consumed_units"] == c["committed_units"] else "DEFAULTED"
            )
            touch(c)


# ---------------------------------------------------------------------------
# Warranty credit (warranty_labor_credit)
# ---------------------------------------------------------------------------

def provisional_credit(center) -> int:
    return FLAT_LABOR_HOURS * center["labor_rate_cents"]


def final_credit(actual_labor_hours, center) -> int:
    base = round_half_up(Decimal(str(actual_labor_hours)) * Decimal(center["labor_rate_cents"]))
    cap = LABOR_CAP_HOURS * center["labor_rate_cents"]
    return min(base, cap)


# ---------------------------------------------------------------------------
# RMA credit (rma_credit): fee decided BEFORE credit; credit uses the FROZEN
# historical unit_price_cents of the earliest-created matching line.
# ---------------------------------------------------------------------------

def rma_fee_pct(reason) -> Decimal:
    if reason == "OVERSTOCK":
        return RESTOCK_PCT
    return Decimal("0")


def rma_credit(order_id, product_id, qty, reason):
    lines = sorted(
        (
            l for l in db["order_lines"].values()
            if l["order_id"] == order_id and l["product_id"] == product_id
        ),
        key=lambda l: l["_seq"],
    )
    if not lines:
        from errors import raise_error, ERR_INVALID_REQUEST
        raise_error(ERR_INVALID_REQUEST, "no order line matches the RMA (order, product)")
    base_credit = lines[0]["unit_price_cents"] * qty
    fee = rma_fee_pct(reason)
    return round_half_up(Decimal(base_credit) * (1 - fee)), fee
