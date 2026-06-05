from decimal import Decimal, ROUND_HALF_UP

# ----------------------------------------------------------------------------
# Domain constants (PRD §3)
# ----------------------------------------------------------------------------
# risk_scoring weights (PRD §3.2 / SCAFFOLD risk_scoring.constants)
HORIZON_W = Decimal("0.35")
TOLERANCE_W = Decimal("0.35")
INCOME_W = Decimal("0.20")
LIQUIDITY_W = Decimal("0.10")

# wash-sale window day count (PRD §3.5)
WASH_SALE_DAYS = 30

# maximum permitted abs(correlation) for a harvest replacement (PRD §3.4)
MAX_REPLACEMENT_CORRELATION = Decimal("0.95")


def round_half_up(value):
    """Round a numeric value half-up to the nearest integer (PRD §2.6)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ----------------------------------------------------------------------------
# risk_scoring (PRD §3.2)
# ----------------------------------------------------------------------------
def risk_score(horizon_years, loss_tolerance, liquidity_need, income_band):
    """Weighted blend; compute raw as one expression (all four terms), round once,
    then clamp to [0, 100]. Rounding each term first would drift the result."""
    h = Decimal(min(horizon_years, 30))
    raw = (
        HORIZON_W * (h / Decimal(30)) * Decimal(100)
        + TOLERANCE_W * (Decimal(loss_tolerance) / Decimal(10)) * Decimal(100)
        + INCOME_W * (Decimal(income_band) / Decimal(10)) * Decimal(100)
        - LIQUIDITY_W * (Decimal(liquidity_need) / Decimal(10)) * Decimal(100)
    )
    score = round_half_up(raw)
    if score < 0:
        score = 0
    if score > 100:
        score = 100
    return score


def market_value_cents(quantity, price_cents):
    """round_half_up(quantity * price_cents) (PRD §2.7, §3.3)."""
    return round_half_up(Decimal(str(quantity)) * Decimal(price_cents))


# ----------------------------------------------------------------------------
# drift_computation (PRD §2.7, §3.3)
# ----------------------------------------------------------------------------
def compute_drift(open_lots, securities, model):
    """Return (invested_value_cents, max_drift_pct).

    open_lots: iterable of OPEN TaxLot dicts for the account.
    securities: dict security_id -> Security.
    model: the account's ModelPortfolio dict (may be None -> no targets).
    """
    invested = 0
    class_mv = {}  # asset_class -> summed market_value_cents
    for lot in open_lots:
        sec = securities.get(lot["security_id"])
        if sec is None:
            continue
        mv = market_value_cents(lot["quantity"], sec["price_cents"])
        invested += mv
        ac = sec["asset_class"]
        class_mv[ac] = class_mv.get(ac, 0) + mv

    # PRD §2.7: max_drift_pct is zero when the account holds no OPEN lots.
    if model is None or invested == 0:
        return invested, 0

    max_drift = 0
    for entry in model["targets"]:
        ac = entry["asset_class"]
        target_pct = entry["target_pct"]
        actual_pct = round_half_up(
            Decimal(100) * Decimal(class_mv.get(ac, 0)) / Decimal(invested)
        )
        drift = abs(actual_pct - target_pct)
        if drift > max_drift:
            max_drift = drift
    return invested, max_drift


# ----------------------------------------------------------------------------
# wash_sale_disallowance (PRD §3.5)
# ----------------------------------------------------------------------------
def wash_sale_disallowed(realized_loss_cents, closing_shares, replacement_shares):
    """disallowed = min(|loss|, round_half_up((repl_shares/closing_shares)*|loss|)).

    realized_loss_cents is the positive magnitude of the loss. replacement_shares
    is the total shares purchased in-window in the same security, already capped
    at closing_shares by the caller. Returns a non-negative integer."""
    if replacement_shares <= 0 or closing_shares <= 0:
        return 0
    abs_loss = abs(realized_loss_cents)
    prorated = round_half_up(
        (Decimal(str(replacement_shares)) / Decimal(str(closing_shares)))
        * Decimal(abs_loss)
    )
    return min(abs_loss, prorated)
