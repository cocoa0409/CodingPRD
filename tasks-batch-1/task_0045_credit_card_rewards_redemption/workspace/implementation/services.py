"""Business logic: points-earning calculation, tier derivation, signup bonus,
points-lot lifecycle, redemption FIFO consumption / reversal, and the
period-close epoch.

All point quantities are exact integers (PRD §2.6 — points never round). The
earning calc multiplies all bps factors first and floors once at the very end
(PRD §2.9 / §3.5).
"""
from clock import clock
from db import db, new_common, now_iso
from util import parse_iso, add_months, add_days
from serialize import points_lot_out

STATEMENT_CREDIT_CENTS_PER_POINT = 1


# ---------------------------------------------------------------------------
# Window / tier-year membership
# ---------------------------------------------------------------------------

def in_signup_window(account, product, transacted_at):
    """transacted_at within [opened_at, opened_at + window_days) (PRD §3.7)."""
    opened = parse_iso(account["opened_at"])
    upper = add_days(opened, product["signup_bonus_window_days"])
    return opened <= transacted_at < upper


def signup_window_upper(account, product):
    return add_days(parse_iso(account["opened_at"]), product["signup_bonus_window_days"])


def in_tier_year(account, transacted_at):
    """transacted_at within [opened_at, opened_at + 365 days) (PRD §3.6)."""
    opened = parse_iso(account["opened_at"])
    upper = add_days(opened, 365)
    return opened <= transacted_at < upper


def derive_tier_index(product, annual_spend_cents):
    """Highest tier index whose min_annual_spend_cents <= annual_spend_cents;
    0 below the first breakpoint (PRD §3.6)."""
    idx = 0
    for i, tier in enumerate(product["tier_thresholds"]):
        if annual_spend_cents >= tier["min_annual_spend_cents"]:
            idx = i + 1  # tiers in the list are indices 1..N; implicit tier 0 below first
        else:
            break
    return idx


def tier_multiplier_bps(product, tier_index):
    """tier_multiplier_bps at the given index; 100 for the implicit tier 0."""
    if tier_index == 0:
        return 100
    # tier_index 1 maps to tier_thresholds[0]
    return product["tier_thresholds"][tier_index - 1]["tier_multiplier_bps"]


# ---------------------------------------------------------------------------
# Points-earning calculation (PRD §3.5)
# ---------------------------------------------------------------------------

def compute_earned_points(account, product, amount_cents, category_code, transacted_at):
    """Returns (earned_points, quarterly_bonus_applied_cents).

    Uses account["current_tier_index"] as the snapshot BEFORE this txn's spend
    is added (caller guarantees the snapshot).
    """
    # Stage 1 — per-cent base multiplier (category replaces base).
    cat_mult_bps = product["base_earn_rate_bps"]
    for cb in db.cashback_categories.values():
        if (cb["card_product_id"] == product["id"]
                and cb["code"] == category_code
                and cb["status"] == "ACTIVE"):
            cat_mult_bps = cb["earn_multiplier_bps"]
            break

    # Stage 2 — quarterly bonus eligibility & cap allocation.
    bonus_cents = 0
    q_mult_bps = 0
    q = _find_quarterly(product, category_code, transacted_at)
    if q is not None and _has_activation(account, q, transacted_at):
        used = _quarterly_used_cents(account, q)
        cap_remaining = max(0, q["bonus_cap_cents"] - used)
        bonus_cents = min(amount_cents, cap_remaining)
        q_mult_bps = q["earn_multiplier_bps"]

    # Stage 3 — tier multiplier on the whole transaction.
    tier_mult_bps = tier_multiplier_bps(product, account["current_tier_index"])

    # Stage 4 — combine and floor once (divide by 100*100*100).
    base_part = (amount_cents - bonus_cents) * cat_mult_bps
    quarterly_part = bonus_cents * q_mult_bps
    raw = (base_part + quarterly_part) * tier_mult_bps
    earned_points = raw // (100 * 100 * 100)
    return earned_points, bonus_cents


def _find_quarterly(product, category_code, transacted_at):
    """QuarterlyCategory with matching code/product whose window contains T:
    window_start <= T < window_end (PRD §3.5 stage two)."""
    for q in db.quarterly_categories.values():
        if q["card_product_id"] != product["id"] or q["code"] != category_code:
            continue
        ws = parse_iso(q["window_start"])
        we = parse_iso(q["window_end"])
        if ws <= transacted_at < we:
            return q
    return None


def _has_activation(account, quarterly_category, transacted_at):
    """ACTIVE CategoryActivation for (account, q) with activated_at <= T."""
    for a in db.category_activations.values():
        if (a["card_account_id"] == account["id"]
                and a["quarterly_category_id"] == quarterly_category["id"]
                and a["status"] == "ACTIVE"):
            if parse_iso(a["activated_at"]) <= transacted_at:
                return True
    return False


def _quarterly_used_cents(account, quarterly_category):
    """Sum of quarterly_bonus_applied_cents over the account's already-POSTED
    txns in this same quarterly window with positive quarterly bonus,
    processed transacted_at ASC then created_at ASC (PRD §3.5 stage two).

    Membership in 'this quarterly category' = same code AND transacted_at falls
    inside this category's window.
    """
    ws = parse_iso(quarterly_category["window_start"])
    we = parse_iso(quarterly_category["window_end"])
    matching = []
    for t in db.transactions.values():
        if t["card_account_id"] != account["id"]:
            continue
        if t["status"] != "POSTED":
            continue
        if t["category_code"] != quarterly_category["code"]:
            continue
        if t.get("quarterly_bonus_applied_cents", 0) <= 0:
            continue
        tat = parse_iso(t["transacted_at"])
        if not (ws <= tat < we):
            continue
        matching.append(t)
    matching.sort(key=lambda t: (t["transacted_at"], t["created_at"], t["_seq"]))
    return sum(t["quarterly_bonus_applied_cents"] for t in matching)


# ---------------------------------------------------------------------------
# Points-lot lifecycle & balance recomputation (PRD §2.6, §3.4)
# ---------------------------------------------------------------------------

def recompute_balance(account):
    """points_balance = sum(remaining_points) over the account's ACTIVE lots."""
    total = 0
    for lot in db.points_lots.values():
        if lot["card_account_id"] == account["id"] and lot["status"] == "ACTIVE":
            total += lot["remaining_points"]
    account["points_balance"] = total


def mint_lot(account, product, points, lot_type, source_transaction_id):
    """Mint a PointsLot. created_at == now; expires_at == created_at + expiry months."""
    rec = new_common(with_version=False)
    created = parse_iso(rec["created_at"])
    expires = add_months(created, product["points_expiry_months"])
    rec.update({
        "card_account_id": account["id"],
        "source_transaction_id": source_transaction_id,
        "lot_type": lot_type,
        "original_points": points,
        "remaining_points": points,
        "expires_at": _iso(expires),
        "status": "ACTIVE",
    })
    db.points_lots[rec["id"]] = rec
    return rec


def _iso(dt):
    from response import iso_ms
    return iso_ms(dt)


def active_lots_fifo(account):
    """Account's ACTIVE lots in FIFO order: expires_at ASC, then created_at ASC
    (PRD §3.8). _seq breaks any remaining ties deterministically."""
    lots = [l for l in db.points_lots.values()
            if l["card_account_id"] == account["id"] and l["status"] == "ACTIVE"]
    lots.sort(key=lambda l: (l["expires_at"], l["created_at"], l["_seq"]))
    return lots


# ---------------------------------------------------------------------------
# Signup bonus (PRD §3.7)
# ---------------------------------------------------------------------------

def maybe_grant_signup_bonus(account, product):
    """Grant the signup bonus if eligible on a POST that updated qualifying_spend.

    Conditions: status NOT_QUALIFIED, qualifying_spend >= threshold, and now is
    still before the window's exclusive upper bound. Grants at most once.
    """
    if account["signup_bonus_status"] != "NOT_QUALIFIED":
        return
    if account["qualifying_spend_cents"] < product["signup_bonus_spend_threshold_cents"]:
        return
    now = clock.now()
    if now >= signup_window_upper(account, product):
        return
    account["signup_bonus_status"] = "EARNED"
    if product["signup_bonus_points"] > 0:
        mint_lot(account, product, product["signup_bonus_points"], "SIGNUP_BONUS", None)
    recompute_balance(account)


# ---------------------------------------------------------------------------
# Redemption value (PRD §3.8)
# ---------------------------------------------------------------------------

def compute_redeemed_value(redemption, partner):
    p = redemption["points_requested"]
    if redemption["redemption_type"] == "STATEMENT_CREDIT":
        return p * STATEMENT_CREDIT_CENTS_PER_POINT
    # POINTS_TRANSFER: floor of fractional partner units
    return (p * partner["transfer_ratio_num"]) // partner["transfer_ratio_den"]


# ---------------------------------------------------------------------------
# Period-close epoch (PRD §3.10)
# ---------------------------------------------------------------------------

def run_close_period():
    from db import touch
    now = clock.now()
    expired_lot_count = 0
    expired_points = 0
    signup_windows_expired = 0
    touched_accounts = {}

    # Sweep 1 — expire lots whose expires_at <= now.
    for lot in db.points_lots.values():
        if lot["status"] == "ACTIVE" and parse_iso(lot["expires_at"]) <= now:
            forfeited = lot["remaining_points"]
            lot["status"] = "EXPIRED"
            lot["remaining_points"] = 0
            expired_lot_count += 1
            expired_points += forfeited
            touched_accounts[lot["card_account_id"]] = True

    # Sweep 2 — mark unmet signup windows EXPIRED_UNQUALIFIED.
    for acc in db.accounts.values():
        product = db.products.get(acc["card_product_id"])
        if product is None:
            continue
        if acc["signup_bonus_status"] != "NOT_QUALIFIED":
            continue
        if now >= signup_window_upper(acc, product) and \
                acc["qualifying_spend_cents"] < product["signup_bonus_spend_threshold_cents"]:
            acc["signup_bonus_status"] = "EXPIRED_UNQUALIFIED"
            signup_windows_expired += 1
            touched_accounts[acc["id"]] = True

    # Recompute balance and bump version on each account actually touched.
    for acc_id in touched_accounts:
        acc = db.accounts.get(acc_id)
        if acc is None:
            continue
        recompute_balance(acc)
        touch(acc)

    return {
        "expired_lot_count": expired_lot_count,
        "expired_points": expired_points,
        "signup_windows_expired": signup_windows_expired,
    }
