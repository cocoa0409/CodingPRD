"""Calculation rules (PRD §2.6, §3.2, §3.5, §3.8, §3.9 / SCAFFOLD §1.3).

All money is integer cents. Each percentage component is floor-divided by 10000
independently BEFORE the legs are summed (the binding per-leg precision rule),
then the flat base is added, then the result is min-capped. No floats."""

# ---- check_cash_fee constants ----
HOLD_THRESHOLD_CENTS = 300000      # face >= -> AMOUNT_THRESHOLD hold
VELOCITY_HOLD_COUNT = 8            # daily_transaction_count >= at posting -> VELOCITY hold

# ---- service_fee constants ----
MO_FLAT_CENTS = 99
MO_BPS = 50
MO_MAX_CENTS = 500
WIRE_FLAT_CENTS = 1500
WIRE_BPS = 100
BILLPAY_FLAT_CENTS = 195
PREPAID_FLAT_CENTS = 395
PREPAID_BPS = 30

# ---- customer_risk_score constants ----
HIGH_MAKER_PTS = 120
AMOUNT_HOLD_PTS = 60
VELOCITY_HOLD_PTS = 90
RETURN_RISK_DELTA = 250
WRITE_OFF_RISK_DELTA = 200
RISK_SCORE_MIN = 0
RISK_SCORE_MAX = 1000

# ---- returned_item_recovery constants ----
RETURN_FEE_CENTS = 2500

# ---- velocity_window constants ----
DAILY_TXN_LIMIT = 12
DAILY_CASH_LIMIT_CENTS = 1000000
STANDARD_CEILING_CENTS = 500000
ELEVATED_CEILING_CENTS = 200000
HIGH_CEILING_CENTS = 50000

EMBARGOED_COUNTRIES = {"CU", "IR", "KP", "SY"}


def _bps_floor(amount_cents, bps):
    """floor(amount * bps / 10000) — integer floor division, fractional part
    discarded (PRD §2.6)."""
    return (amount_cents * bps) // 10000


def check_cash_fee(face_cents, schedule):
    """Tiered check-cash fee (PRD §3.2). Per-leg flooring is the contract:
    each percent leg floored independently, then summed, then base added, then
    capped at max_fee_cents."""
    base = schedule["base_fee_cents"]
    bp = schedule["tier_breakpoint_cents"]
    if face_cents <= bp:
        pct = _bps_floor(face_cents, schedule["percent_rate_bps"])
    else:
        low = _bps_floor(bp, schedule["percent_rate_bps"])
        high = _bps_floor(face_cents - bp, schedule["high_percent_rate_bps"])
        pct = low + high
    raw_fee = base + pct
    return min(raw_fee, schedule["max_fee_cents"])


def service_fee(txn_type, face_cents):
    """Fixed-constant fee for non-CHECK_CASH products (PRD §3.2)."""
    if txn_type == "MONEY_ORDER":
        return min(MO_FLAT_CENTS + _bps_floor(face_cents, MO_BPS), MO_MAX_CENTS)
    if txn_type == "WIRE":
        return WIRE_FLAT_CENTS + _bps_floor(face_cents, WIRE_BPS)  # uncapped
    if txn_type == "BILL_PAY":
        return BILLPAY_FLAT_CENTS  # flat, face-independent
    if txn_type == "PREPAID_LOAD":
        return max(PREPAID_FLAT_CENTS, _bps_floor(face_cents, PREPAID_BPS))  # greater-of
    raise ValueError("service_fee called for unsupported type %s" % txn_type)


def net_disbursed(txn_type, face_cents, fee_cents):
    """Sign convention (PRD §3.5): CHECK_CASH cash leaves the drawer (+face-fee);
    all others cash enters from the customer (-(face+fee))."""
    if txn_type == "CHECK_CASH":
        return face_cents - fee_cents
    return -(face_cents + fee_cents)


def risk_tier_for_score(score):
    """HIGH if >=700, ELEVATED if >=350, else STANDARD (PRD §3.8)."""
    if score >= 700:
        return "HIGH"
    if score >= 350:
        return "ELEVATED"
    return "STANDARD"


def ceiling_for_tier(tier):
    if tier == "STANDARD":
        return STANDARD_CEILING_CENTS
    if tier == "ELEVATED":
        return ELEVATED_CEILING_CENTS
    if tier == "HIGH":
        return HIGH_CEILING_CENTS
    raise ValueError("unknown tier %s" % tier)


def clamp_score(score):
    return max(RISK_SCORE_MIN, min(RISK_SCORE_MAX, score))


def hold_derived_delta(maker_account_risk, hold_reason):
    """Confirmed risk delta when a held check is resolved (PRD §3.8):
    +120 if maker HIGH, +60 if AMOUNT_THRESHOLD, +90 if VELOCITY."""
    delta = 0
    if maker_account_risk == "HIGH":
        delta += HIGH_MAKER_PTS
    if hold_reason == "AMOUNT_THRESHOLD":
        delta += AMOUNT_HOLD_PTS
    if hold_reason == "VELOCITY":
        delta += VELOCITY_HOLD_PTS
    return delta
