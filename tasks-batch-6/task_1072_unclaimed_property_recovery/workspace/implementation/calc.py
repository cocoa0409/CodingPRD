"""Business calculations: dormancy, escheat remittance, recovery fee, payout waterfall."""
from decimal import Decimal
from store import parse_iso, add_years, full_calendar_years
from common import round_half_up, D

ANNUAL_INTEREST_RATE = Decimal("0.02")
MAX_INTEREST_MULTIPLE = Decimal("0.5")
STATE_MAX_FEE_PCT = Decimal("0.10")
ADMIN_FLAT_FEE_CENTS = 500
ADMIN_TIER_THRESHOLD_CENTS = 100000
ADMIN_PCT = Decimal("0.005")


def compute_dormancy_date(ptype, last_activity_dt, issue_dt):
    """Returns the dormancy datetime, or raises ValueError if the required anchor is missing."""
    basis = ptype["dormancy_basis"]
    if basis == "LAST_ACTIVITY":
        anchor = last_activity_dt
    else:  # ISSUANCE
        anchor = issue_dt
    if anchor is None:
        raise ValueError("missing anchor date for dormancy basis")
    return add_years(anchor, ptype["dormancy_period_years"])


def escheat_remittance_amount(prop, ptype, now):
    amount = prop["amount_cents"]
    dormancy_dt = parse_iso(prop["dormancy_date"])
    years_dormant = full_calendar_years(dormancy_dt, now)
    if not ptype["interest_bearing"]:
        interest = D(0)
    else:
        raw_interest = D(amount) * ANNUAL_INTEREST_RATE * D(years_dormant)
        cap = D(amount) * MAX_INTEREST_MULTIPLE
        interest = min(raw_interest, cap)
    return round_half_up(D(amount) + interest)


def effective_fee_pct(contract_fee_pct):
    return min(D(contract_fee_pct), STATE_MAX_FEE_PCT)


def provisional_fee(contract_fee_pct, amount_cents):
    return round_half_up(effective_fee_pct(contract_fee_pct) * D(amount_cents))


def payout_waterfall(contract_fee_pct, claim_amount_cents):
    """Returns (fee_cents, admin_deduction_cents, net_payout_cents)."""
    eff = effective_fee_pct(contract_fee_pct)
    fee_cents = round_half_up(eff * D(claim_amount_cents))
    post_fee = claim_amount_cents - fee_cents
    if post_fee <= ADMIN_TIER_THRESHOLD_CENTS:
        admin = ADMIN_FLAT_FEE_CENTS
    else:
        admin = round_half_up(ADMIN_PCT * D(post_fee))
    net = claim_amount_cents - fee_cents - admin
    return fee_cents, admin, net
