"""Pure calculation functions: fee tiers, NAV, dividends."""
from datetime import datetime, timedelta, timezone
from clock import parse_iso_date, parse_iso
from services.util import round_half_up, round_half_down


CONFIRM_CYCLE_BY_TYPE = {
    "EQUITY": 2,
    "HYBRID": 2,
    "BOND": 1,
    "MONEY_MARKET": 0,
    "QDII": 3,
}


def confirmation_cycle_days_for_type(fund_type: str) -> int:
    return CONFIRM_CYCLE_BY_TYPE[fund_type]


def find_subscription_tier(tiers, gross_amount_cents):
    """Return the matching tier by amount band: min_amount_cents <= amt AND (max is null OR amt < max)."""
    for tier in tiers:
        lo = tier["min_amount_cents"]
        hi = tier.get("max_amount_cents")
        if lo <= gross_amount_cents and (hi is None or gross_amount_cents < hi):
            return tier
    return None


def find_redemption_tier(tiers, holding_days):
    for tier in tiers:
        lo = tier["min_holding_days"]
        hi = tier.get("max_holding_days")
        if lo <= holding_days and (hi is None or holding_days < hi):
            return tier
    return None


def validate_fee_tiers(subscription_tiers, redemption_tiers):
    """Return True if both arrays are non-empty, ordered ascending, and non-overlapping."""
    return _validate_amount_tiers(subscription_tiers) and _validate_holding_tiers(redemption_tiers)


def _validate_amount_tiers(tiers) -> bool:
    if not tiers or not isinstance(tiers, list):
        return False
    prev_max = None
    prev_min = None
    for t in tiers:
        if not isinstance(t, dict):
            return False
        if "min_amount_cents" not in t or "rate_bps" not in t:
            return False
        lo = t["min_amount_cents"]
        hi = t.get("max_amount_cents")
        if not isinstance(lo, int) or isinstance(lo, bool):
            return False
        if hi is not None and (not isinstance(hi, int) or isinstance(hi, bool)):
            return False
        if hi is not None and hi <= lo:
            return False
        if prev_max is None and prev_min is None:
            pass
        else:
            # Ordered ascending by min
            if prev_min is not None and lo < prev_min:
                return False
            # Non-overlapping: prev_max must be set and <= lo
            if prev_max is None:
                return False
            if prev_max > lo:
                return False
        prev_min = lo
        prev_max = hi
    return True


def _validate_holding_tiers(tiers) -> bool:
    if not tiers or not isinstance(tiers, list):
        return False
    prev_max = None
    prev_min = None
    for t in tiers:
        if not isinstance(t, dict):
            return False
        if "min_holding_days" not in t or "rate_bps" not in t:
            return False
        lo = t["min_holding_days"]
        hi = t.get("max_holding_days")
        if not isinstance(lo, int) or isinstance(lo, bool):
            return False
        if hi is not None and (not isinstance(hi, int) or isinstance(hi, bool)):
            return False
        if hi is not None and hi <= lo:
            return False
        if prev_max is None and prev_min is None:
            pass
        else:
            if prev_min is not None and lo < prev_min:
                return False
            if prev_max is None:
                return False
            if prev_max > lo:
                return False
        prev_min = lo
        prev_max = hi
    return True


# -----------------------------
# NAV per share
# -----------------------------
INITIAL_NAV_MICROS = 1_000_000


def compute_nav_components(portfolio_market_value_cents: int,
                           portfolio_accrued_income_cents: int,
                           mgmt_bps: int, cust_bps: int, sales_bps: int,
                           shares_outstanding: int):
    gross_assets = portfolio_market_value_cents + portfolio_accrued_income_cents
    mgmt_fee = round_half_up(gross_assets * mgmt_bps, 10000 * 365)
    cust_fee = round_half_up(gross_assets * cust_bps, 10000 * 365)
    sales_fee = round_half_up(gross_assets * sales_bps, 10000 * 365)
    net_assets = gross_assets - mgmt_fee - cust_fee - sales_fee
    if shares_outstanding == 0:
        nav_micros = INITIAL_NAV_MICROS
    else:
        nav_micros = round_half_up(net_assets * 100_000_000, shares_outstanding)
    return {
        "gross_assets_cents": gross_assets,
        "management_fee_accrued_cents": mgmt_fee,
        "custodian_fee_accrued_cents": cust_fee,
        "sales_service_fee_accrued_cents": sales_fee,
        "net_assets_cents": net_assets,
        "shares_outstanding_at_nav": shares_outstanding,
        "nav_per_share_micros": nav_micros,
    }


# -----------------------------
# Subscription fee
# -----------------------------
def compute_subscription_confirmation(gross_amount_cents: int, nav_micros: int,
                                       subscription_tiers, back_end_load_enabled: bool):
    """Returns dict with subscription_fee_cents, confirmed_shares, confirmed_amount_cents."""
    if back_end_load_enabled:
        subscription_fee = 0
        confirmed_shares = round_half_up(gross_amount_cents * 100_000_000, nav_micros)
    else:
        tier = find_subscription_tier(subscription_tiers, gross_amount_cents)
        rate = tier["rate_bps"] if tier else 0
        subscription_fee = round_half_up(gross_amount_cents * rate, 10000)
        net_amount = gross_amount_cents - subscription_fee
        confirmed_shares = round_half_up(net_amount * 100_000_000, nav_micros)
    return {
        "subscription_fee_cents": subscription_fee,
        "confirmed_shares": confirmed_shares,
        "confirmed_amount_cents": gross_amount_cents,
    }


# -----------------------------
# Redemption fee with FIFO holding-period
# -----------------------------
def compute_redemption_confirmation(requested_shares: int, nav_micros: int,
                                     trade_date,  # date
                                     redemption_tiers,
                                     subscription_tiers,
                                     back_end_load_enabled: bool,
                                     consumed_lots):
    """consumed_lots: list of dicts {lot, take, original_shares, original_cost} as produced by holdings.fifo_burn.

    Returns dict: gross_redeem_amount_cents, redemption_fee_cents, back_end_load_fee_cents, confirmed_amount_cents,
    per_lot_amounts (used to credit cost decreases), and net_amount.
    """
    gross_redeem_amount = round_half_up(requested_shares * nav_micros, 100_000_000)
    total_fee = 0
    total_back_end = 0
    for entry in consumed_lots:
        lot = entry["lot"]
        take = entry["take"]
        original_shares = entry["original_shares"]
        original_cost = entry["original_cost"]
        # holding_days: floor of (trade_date - acquired_date) calendar days
        acquired_date = parse_iso_date(lot["acquired_at"])
        if hasattr(trade_date, "date"):
            td = trade_date.date() if hasattr(trade_date, "date") else trade_date
        else:
            td = trade_date
        holding_days = max(0, (td - acquired_date).days)
        rtier = find_redemption_tier(redemption_tiers, holding_days)
        rate = rtier["rate_bps"] if rtier else 0
        lot_amount = round_half_up(take * nav_micros, 100_000_000)
        lot_fee = round_half_up(lot_amount * rate, 10000)
        total_fee += lot_fee
        if back_end_load_enabled:
            # proportional original cost
            if take == original_shares:
                lot_cost_proportional = original_cost
            else:
                lot_cost_proportional = round_half_up(original_cost * take, original_shares)
            stier = find_subscription_tier(subscription_tiers, lot_cost_proportional)
            srate = stier["rate_bps"] if stier else 0
            total_back_end += round_half_up(lot_cost_proportional * srate, 10000)
    back_end_fee = total_back_end if back_end_load_enabled else 0
    confirmed_amount = gross_redeem_amount - total_fee - back_end_fee
    return {
        "gross_redeem_amount_cents": gross_redeem_amount,
        "redemption_fee_cents": total_fee,
        "back_end_load_fee_cents": back_end_fee,
        "confirmed_amount_cents": confirmed_amount,
    }


# -----------------------------
# Conversion fee
# -----------------------------
def compute_conversion_fee(gross_redeem_amount_cents: int, conversion_fee_bps: int) -> int:
    return round_half_up(gross_redeem_amount_cents * conversion_fee_bps, 10000)


# -----------------------------
# Large redemption percentage
# -----------------------------
def compute_large_redemption_pct_bps(requested_shares: int, total_outstanding_shares: int) -> int:
    if total_outstanding_shares <= 0:
        return 0
    return round_half_up(requested_shares * 10000, total_outstanding_shares)


# -----------------------------
# Dividend amounts
# -----------------------------
def compute_dividend_amounts(eligible_shares: int, dividend_per_share_micros: int,
                              tax_resident_status: str,
                              tax_rate_bps_domestic: int, tax_rate_bps_foreign: int):
    gross = round_half_up(eligible_shares * dividend_per_share_micros, 100_000_000)
    if tax_resident_status == "EXEMPT":
        tax = 0
    elif tax_resident_status == "DOMESTIC":
        tax = round_half_up(gross * tax_rate_bps_domestic, 10000)
    else:  # FOREIGN
        tax = round_half_up(gross * tax_rate_bps_foreign, 10000)
    net = gross - tax
    return gross, tax, net


def compute_reinvested_shares(net_dividend_cents: int, nav_micros: int) -> int:
    if nav_micros <= 0:
        return 0
    return round_half_down(net_dividend_cents * 100_000_000, nav_micros)


# -----------------------------
# Trade date (acceptance window)
# -----------------------------
def assign_trade_date(submitted_at):
    """submitted_at: datetime UTC. Cutoff at 15:00 UTC inclusive shifts to next day."""
    if isinstance(submitted_at, str):
        submitted_at = parse_iso(submitted_at)
    cutoff = submitted_at.replace(hour=15, minute=0, second=0, microsecond=0)
    if submitted_at < cutoff:
        return submitted_at.date()
    return submitted_at.date() + timedelta(days=1)
