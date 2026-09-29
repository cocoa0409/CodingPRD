"""Pure integer arithmetic for money and basis points (PRD section 2.6).

Every monetary reduction uses round-half-up on exact integers; floats are never
used for money.
"""

import config


def rhu_div(numerator, denominator):
    """Round-half-up integer division; ``denominator`` must be positive."""
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    if numerator >= 0:
        return (2 * numerator + denominator) // (2 * denominator)
    return -((2 * (-numerator) + denominator) // (2 * denominator))


def ceil_div(numerator, denominator):
    return -(-numerator // denominator)


def pct_bps(amount, bps):
    """round_half_up(amount * bps / 10000)."""
    return rhu_div(amount * bps, 10000)


def ceil_to_par(amount):
    par = config.STOCK_PAR_VALUE_CENTS
    return ceil_div(amount, par) * par


# ------------------------------------------------------------- member stock --


def membership_stock_requirement(total_assets_cents):
    raw = pct_bps(total_assets_cents, config.MEMBERSHIP_STOCK_BPS)
    return min(config.MEMBERSHIP_STOCK_MAX_CENTS,
               max(config.MEMBERSHIP_STOCK_MIN_CENTS, raw))


# ------------------------------------------------------------- advance sizing --


def gross_up(requested_net_proceeds_cents, activity_stock_pct_bps, fund_stock_from_advance):
    """Return (gross_principal_cents, activity_stock_cents, net_proceeds_cents).

    The three-step evaluation order is normative: step two reads the step-one
    provisional gross and never the final gross principal.
    """
    n = requested_net_proceeds_cents
    p = activity_stock_pct_bps
    if not fund_stock_from_advance:
        gross = n
        activity = ceil_to_par(pct_bps(n, p))
        return gross, activity, n
    g0 = ceil_div(n * 10000, 10000 - p)
    activity = ceil_to_par(pct_bps(g0, p))
    gross = n + activity
    return gross, activity, n


def advance_rate_bps(product_rate_bps, subsidy_rate_bps):
    return max(config.RATE_FLOOR_BPS, product_rate_bps - subsidy_rate_bps)


# ------------------------------------------------------------ set-aside pool --


def bucket_capacities(total_pool_cents):
    first = pct_bps(total_pool_cents, config.BUCKET_SHARE_FIRST_TIME_BPS)
    rehab = pct_bps(total_pool_cents, config.BUCKET_SHARE_REHABILITATION_BPS)
    general_raw = pct_bps(total_pool_cents, config.BUCKET_SHARE_GENERAL_BPS)
    residual = total_pool_cents - (first + rehab + general_raw)
    return first, rehab, general_raw + residual


# ------------------------------------------------------ verification scoring --


def exception_scoring(critical, major, minor, sample_size):
    """Return (weighted_exception_score, exception_rate_pct, haircut_bps, outcome).

    ``weighted_exception_score`` is 3.0/1.0/0.25 weighted; it is carried as a
    quarter-integer internally so the percentage rounding stays exact.
    """
    quarters = (config.SEVERITY_WEIGHT_Q["CRITICAL"] * critical
                + config.SEVERITY_WEIGHT_Q["MAJOR"] * major
                + config.SEVERITY_WEIGHT_Q["MINOR"] * minor)
    # exception_rate_pct rounded to two decimals, held scaled by 100
    scaled = rhu_div(100 * 100 * quarters, 4 * sample_size)
    if scaled < config.HAIRCUT_BAND_1_PCT_SCALED:
        haircut, outcome = 0, "PASS"
    elif scaled < config.HAIRCUT_BAND_2_PCT_SCALED:
        haircut, outcome = 300, "QUALIFIED"
    elif scaled < config.HAIRCUT_BAND_3_PCT_SCALED:
        haircut, outcome = 700, "QUALIFIED"
    else:
        haircut, outcome = 1500, "FAIL"
    score = quarters / 4
    rate = scaled / 100
    return score, rate, haircut, outcome


# ---------------------------------------------------------------- prepayment --


def base_fee(principal_cents, spread_bps, days):
    """One single rounding applied to the whole product."""
    numerator = principal_cents * spread_bps * days
    denominator = 10000 * 360
    return rhu_div(numerator, denominator)


def raw_prepayment_fee(product, principal_cents, advance_rate, market_rate_bps, days):
    """The signed raw fee before any administrative fee is added."""
    method = product["prepayment_fee_method"]
    if method == "NONE":
        return 0
    if method == "FLAT_PCT":
        return pct_bps(principal_cents, product["flat_prepayment_fee_bps"])
    spread = advance_rate - market_rate_bps
    if method == "YIELD_MAINTENANCE":
        return base_fee(principal_cents, max(0, spread), days)
    # SYMMETRIC_MARKET_VALUE
    raw = base_fee(principal_cents, spread, days)
    if raw < 0:
        if product["symmetric_credit_enabled"]:
            cap = pct_bps(principal_cents, config.SYMMETRIC_CREDIT_CAP_BPS)
            raw = -min(-raw, cap)
        else:
            raw = 0
    return raw
