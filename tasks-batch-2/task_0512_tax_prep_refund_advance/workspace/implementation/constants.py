"""Calculation constants (SCAFFOLD Table 3 / PRD §3.4, §3.7, §3.8). All money in
integer cents."""

# ---- prep_fee_total (PRD §3.4) ---------------------------------------------
BASE_1040_CENTS = 15000
SCHEDULE_FEE = {"A": 4000, "B": 2500, "C": 9000, "D": 6000, "E": 7500, "EIC": 5000}
STATE_RETURN_CENTS = 6000
# Band multiplier: SIMPLE 1.00, STANDARD 1.20, COMPLEX 1.50
BAND_MULT = {"SIMPLE": "1.00", "STANDARD": "1.20", "COMPLEX": "1.50"}
DISCOUNT_PCT = "0.10"
DISCOUNT_CAP_CENTS = 2500

# ---- advance_max_eligible (PRD §3.8) ---------------------------------------
# Tier caps keyed by refund-size break (lower edge inclusive):
#   < 100000          -> 0
#   100000 .. <300000 -> 50000
#   300000 .. <600000 -> 150000
#   >= 600000         -> 350000
RISK_FRACTION = {"LOW": "0.75", "MEDIUM": "0.50", "HIGH": "0.00"}

# ---- bank-product defaults -------------------------------------------------
BANK_PRODUCT_FEE_CENTS = 3995
AUDIT_PROTECTION_FEE_CENTS = 5900

# ---- disbursement_surcharge (PRD §3.7) -------------------------------------
SURCHARGE_PCT = "0.029"

# ---- enum domains ----------------------------------------------------------
SCHEDULE_SET = {"A", "B", "C", "D", "E", "EIC"}
COMPLEXITY_BANDS = {"SIMPLE", "STANDARD", "COMPLEX"}
RETURN_KINDS = {"ORIGINAL", "PRIOR_YEAR", "AMENDED_1040X"}
RISK_BANDS = {"LOW", "MEDIUM", "HIGH"}
DOC_TYPES = {"W2", "1099", "ID", "PRIOR_RETURN", "OTHER"}

# Return statuses that count toward open_return_count / assigned_open_returns:
# everything NOT IN {EFILED_ACCEPTED, CANCELLED}.
RETURN_CLOSED_STATES = {"EFILED_ACCEPTED", "CANCELLED"}


def advance_tier_cap(expected_refund_cents):
    """Refund-size tier cap (PRD §3.8). Lower edge inclusive."""
    r = expected_refund_cents
    if r < 100000:
        return 0
    if r < 300000:
        return 50000
    if r < 600000:
        return 150000
    return 350000
