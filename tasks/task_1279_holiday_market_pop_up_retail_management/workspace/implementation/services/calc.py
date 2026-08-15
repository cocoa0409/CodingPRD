"""Calculation rules (scaffold 1.3). Monetary math uses integer cents or
Decimal; rounding is round-half-up applied once at the end, except the POS
fee which uses integer floor semantics.
"""
from decimal import ROUND_HALF_UP, Decimal

import db

# Two-dimensional base rent lookup: RENT_TABLE[booth_type][zone] in cents.
RENT_TABLE = {
    "STANDARD": {"NORTH": 200000, "SOUTH": 180000, "EAST": 190000, "WEST": 170000},
    "CHALET": {"NORTH": 500000, "SOUTH": 480000, "EAST": 490000, "WEST": 470000},
}
EARLY_BIRD_DAYS = 45
LATE_COMMIT_DAYS = 7
EARLY_BIRD_MULT = Decimal("0.85")
LATE_COMMIT_MULT = Decimal("1.20")
HEATING_FLAT_CENTS = 45000  # $450.00 flat
SALES_DIVISOR = 200000  # $2,000 in cents per renewal-score point


def compute_base_rent_cents(booth, market, created_at):
    base = RENT_TABLE[booth["booth_type"]][booth["zone"]]
    days_to_open = (market["opens_at"] - created_at).days  # floor semantics
    if days_to_open >= EARLY_BIRD_DAYS:
        mult = EARLY_BIRD_MULT
    elif days_to_open <= LATE_COMMIT_DAYS:
        mult = LATE_COMMIT_MULT
    else:
        mult = Decimal("1.00")
    return int((Decimal(base) * mult).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_heating_surcharge_cents(application, booth):
    if application.get("heating_requested") and booth["booth_type"] == "CHALET":
        return HEATING_FLAT_CENTS
    return 0


def has_active_pos_device(assignment_id):
    return any(
        d["assignment_id"] == assignment_id and d["status"] == "ACTIVE"
        for d in db.STORES["pos_devices"].values()
    )


def compute_pos_fee_cents(market, assignment_id, gross_card_cents):
    """Provisional per-row floor variant (authoritative for DRAFT/SUBMITTED)."""
    if market["shared_pos_enabled"] and has_active_pos_device(assignment_id):
        return (gross_card_cents * market["shared_pos_fee_bps"]) // 10000
    return 0


def compute_net_payable_cents(gross_card_cents, gross_cash_cents, refund_cents, pos_fee_cents):
    return gross_card_cents + gross_cash_cents - refund_cents - pos_fee_cents


def most_recent_jury_average(vendor_id):
    best = None
    for app in db.STORES["applications"].values():
        if app["vendor_id"] != vendor_id:
            continue
        if app.get("jury_average") is None:
            continue
        key = (app["created_at"], app["_seq"])
        if best is None or key > best[0]:
            best = (key, app["jury_average"])
    return best[1] if best is not None else None


def recompute_renewal_score(vendor):
    sales = Decimal(vendor["lifetime_gross_sales_cents"]) / Decimal(SALES_DIVISOR)
    if sales > 50:
        sales = Decimal(50)
    reliability = max(0, 30 - 10 * vendor["no_show_strikes"])
    avg = most_recent_jury_average(vendor["id"])
    jury = (Decimal(str(avg)) / Decimal(100) * Decimal(20)) if avg is not None else Decimal(0)
    score = (sales + Decimal(reliability) + jury).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    vendor["renewal_score"] = float(score)


def compute_discount_pct(renewal_score):
    s = Decimal(str(renewal_score))
    if s >= 80:
        return 20
    if s >= 60:
        return 15
    if s >= 40:
        return 10
    if s >= 20:
        return 5
    return 0
