"""Derived figures — SCAFFOLD section 1.3 / PRD sections 2.6, 3.2, 3.5, 3.6, 3.7.

Every figure here is computed server-side from stored inputs and never accepted
from a client.
"""

from decimal import Decimal, ROUND_HALF_UP

# ------------------------------------------------------------------ constants --

AG_REVIEW_STATES = ("CA", "NY", "MA", "IL", "WA")
AG_PETITION_THRESHOLD_CENTS = 500000000
NOTICE_WAITING_DAYS = 20
PETITION_WAITING_DAYS = 45
ASSET_ACQUISITION_SURCHARGE_DAYS = 15
JUDICIAL_BASIS_SURCHARGE_DAYS = 10

FEE_TIER_1_CEILING_CENTS = 100000000
FEE_TIER_2_CEILING_CENTS = 1000000000
FEE_TIER_1_CENTS = 25000
FEE_TIER_2_CENTS = 150000
FEE_TIER_3_CENTS = 500000

ENDOWMENT_SPENDING_RATE_BPS = 700

RESERVE_FLOOR_MONTHS = Decimal("3.00")
EXCLUSIVITY_COOLING_OFF_DAYS = 30

MISSION_IDENTICAL_POINTS = Decimal("40.00")
MISSION_FAMILY_POINTS = Decimal("28.00")
MISSION_UNRELATED_POINTS = Decimal("12.00")
RESTRICTED_FUNDS_ESCALATION_DEDUCTION = Decimal("10.00")
OVERLAP_MAX_POINTS = Decimal("30.00")

REQUIRED_RATIOS = {
    "MERGER": Decimal("0.6667"),
    "ASSET_ACQUISITION": Decimal("0.6667"),
    "PARENT_SUBSIDIARY": Decimal("0.6000"),
    "MANAGEMENT_SERVICES_AGREEMENT": Decimal("0.5000"),
}


# -------------------------------------------------------------------- rounding --

def rhu(value, places):
    """Round half up to a fixed number of decimal places, as a Decimal."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    exp = Decimal(1).scaleb(-places)
    return value.quantize(exp, rounding=ROUND_HALF_UP)


def rhu_int(value):
    """Round half up to a whole unit (integer cents)."""
    return int(rhu(value, 0))


def num(value, places):
    """Render a Decimal as the JSON number the API returns."""
    return float(rhu(value, places))


def monthly_expense_cents(annual_expense_cents):
    """Per-organization step, pinned to run BEFORE any summation."""
    return rhu_int(Decimal(annual_expense_cents) / Decimal(12))


def mission_family(code):
    if not isinstance(code, str):
        return None
    return code.split("-")[0]


# --------------------------------------------------- alignment assessment ------

def reserve_months_decimal(available_unrestricted_cents, combined_monthly_expense_cents):
    if combined_monthly_expense_cents == 0:
        return Decimal("0.00")
    return rhu(
        Decimal(available_unrestricted_cents) / Decimal(combined_monthly_expense_cents), 2
    )


def overlap_index(overlap_pair_count, denom):
    if denom == 0:
        return Decimal("0.0000")
    value = rhu(Decimal(overlap_pair_count) / Decimal(denom), 4)
    if value > Decimal("1.0000"):
        value = Decimal("1.0000")
    return value


def overlap_points(index):
    factor = Decimal(1) - (abs(index - Decimal("0.5")) * Decimal(2))
    return rhu(OVERLAP_MAX_POINTS * factor, 2)


def sustainability_points(reserve_months):
    if reserve_months >= Decimal("6.00"):
        return Decimal("30.00")
    if reserve_months >= Decimal("3.00"):
        return Decimal("20.00")
    if reserve_months >= Decimal("1.50"):
        return Decimal("10.00")
    return Decimal("0.00")


def composite_rating(score):
    if score >= Decimal("80.00"):
        return "STRONG"
    if score >= Decimal("60.00"):
        return "MODERATE"
    if score >= Decimal("40.00"):
        return "WEAK"
    return "NOT_VIABLE"


# ----------------------------------------------------------- restricted funds --

def fund_value(fund):
    return fund["principal_cents"] + fund["accumulated_appreciation_cents"]


def transferable_amount(fund, basis):
    """PRD 3.6: the two release rules differ, deliberately."""
    value = fund_value(fund)
    if basis == "JUDICIAL_MODIFICATION" and fund["fund_type"] == "PERM_ENDOWMENT":
        hdv = fund["historic_dollar_value_cents"]
        above_hdv = max(0, value - hdv)
        # The one deliberate truncation in the system (PRD 2.6).
        capped_slice = (hdv * ENDOWMENT_SPENDING_RATE_BPS) // 10000
        return above_hdv + capped_slice
    return value


# ----------------------------------------------------------------- ag filings --

def ag_filing_fee_cents(provisional_consideration_cents):
    if provisional_consideration_cents < FEE_TIER_1_CEILING_CENTS:
        return FEE_TIER_1_CENTS
    if provisional_consideration_cents < FEE_TIER_2_CEILING_CENTS:
        return FEE_TIER_2_CENTS
    return FEE_TIER_3_CENTS


def required_filing_type(asset_value_cents, perm_endowment_present):
    if asset_value_cents >= AG_PETITION_THRESHOLD_CENTS or perm_endowment_present:
        return "APPROVAL_PETITION"
    return "NOTICE"


def statutory_waiting_days(filing_type, asset_value_cents, structure_type,
                           judicial_basis_present):
    days = PETITION_WAITING_DAYS if filing_type == "APPROVAL_PETITION" else NOTICE_WAITING_DAYS
    if structure_type == "ASSET_ACQUISITION" and asset_value_cents >= AG_PETITION_THRESHOLD_CENTS:
        days += ASSET_ACQUISITION_SURCHARGE_DAYS
    if judicial_basis_present:
        days += JUDICIAL_BASIS_SURCHARGE_DAYS
    return days


# ---------------------------------------------------------------- board votes --

def board_vote(seats_total, recusals, votes_for, votes_against, abstentions,
               structure_type):
    eligible = seats_total - recusals
    quorum = -((-eligible) // 2)  # ceil(eligible / 2)
    attendance = votes_for + votes_against + abstentions
    votes_cast = votes_for + votes_against
    required = REQUIRED_RATIOS.get(structure_type, Decimal("0.5000"))
    if votes_cast == 0:
        ratio = Decimal("0.0000")
    else:
        ratio = rhu(Decimal(votes_for) / Decimal(votes_cast), 4)
    decision = "APPROVED" if (votes_cast > 0 and ratio >= required) else "REJECTED"
    return {
        "eligible_seats": eligible,
        "quorum_required": quorum,
        "attendance": attendance,
        "votes_cast": votes_cast,
        "required_ratio": required,
        "approval_ratio": ratio,
        "decision": decision,
    }
