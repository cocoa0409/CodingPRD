"""Calculation rules (SCAFFOLD §1.3, PRD §2.7 / §3.3 / §3.6 / §3.8 / §3.9)."""
from decimal import Decimal, ROUND_HALF_UP, getcontext

import constants as K

getcontext().prec = 60

_ONE = Decimal(1)
_CENT = Decimal(1)
_FOUR_DP = Decimal("0.0001")
_TWO_DP = Decimal("0.01")


def round_half_up_cents(value):
    return int(Decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP))


def round_half_up(value, places):
    quant = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# calculations.hardship_severity_score
# ---------------------------------------------------------------------------
def hardship_severity_score(reason, income_cents, expenses_cents, liquid_cents,
                            qualifying_document_count):
    """Terms accumulate at full precision; a SINGLE half-up rounding at the end."""
    income = Decimal(income_cents)
    expenses = Decimal(expenses_cents)
    liquid = Decimal(liquid_cents)

    deficit_ratio = (expenses - income) / income
    if deficit_ratio > _ONE:
        deficit_ratio = _ONE
    if deficit_ratio < 0:
        deficit_ratio = Decimal(0)

    reserve_months = liquid / expenses
    capped = reserve_months if reserve_months < K.RESERVE_CAP_MONTHS else K.RESERVE_CAP_MONTHS
    reserve_relief = _ONE - (capped / K.RESERVE_CAP_MONTHS)
    if reserve_relief < 0:
        reserve_relief = Decimal(0)

    doc_support = Decimal(qualifying_document_count) / Decimal(len(K.REQUIRED_DOCUMENT_TYPES))

    raw = (
        K.REASON_WEIGHT[reason]
        + K.DEFICIT_WEIGHT * deficit_ratio
        + K.RESERVE_WEIGHT * reserve_relief
        + K.DOC_WEIGHT * doc_support
    )
    return round_half_up(raw, 2)


# ---------------------------------------------------------------------------
# calculations.minimum_acceptable_net
# ---------------------------------------------------------------------------
def minimum_acceptable_net(final_value_cents, investor_type, upb_cents, mi_credit_cents):
    value_floor = round_half_up_cents(
        Decimal(final_value_cents) * K.MIN_NET_RATIO[investor_type]
    )
    upb_floor = round_half_up_cents(Decimal(upb_cents) * K.UPB_FLOOR_RATIO)
    return max(value_floor, upb_floor) - mi_credit_cents


# ---------------------------------------------------------------------------
# calculations.net_proceeds_to_first_lien
# ---------------------------------------------------------------------------
def net_sheet(variant, offer_price_cents, listing_commission_pct, title_escrow_cents,
              property_tax_arrears_cents, hoa_arrears_cents, junior_payoff_cents,
              mi_credit_cents):
    price = Decimal(offer_price_cents)

    if variant == "PRELIMINARY":
        commission_pct_applied = listing_commission_pct
    else:
        commission_pct_applied = min(listing_commission_pct, K.SERVICER_COMMISSION_CAP_PCT)

    # Six deduction lines, in this order.  ROUNDING ORDER IS PINNED: each line
    # is rounded on its own and only the already-rounded lines are summed.
    lines = [
        {
            "line_type": "COMMISSION",
            "basis": "PCT_OF_PRICE",
            "rate_or_amount": float(commission_pct_applied),
            "amount_cents": round_half_up_cents(price * commission_pct_applied),
        },
        {
            "line_type": "TITLE_AND_ESCROW",
            "basis": "FLAT",
            "rate_or_amount": title_escrow_cents,
            "amount_cents": title_escrow_cents,
        },
        {
            "line_type": "TRANSFER_TAX",
            "basis": "PCT_OF_PRICE",
            "rate_or_amount": float(K.TRANSFER_TAX_PCT),
            "amount_cents": round_half_up_cents(price * K.TRANSFER_TAX_PCT),
        },
        {
            "line_type": "PROPERTY_TAX_ARREARS",
            "basis": "FLAT",
            "rate_or_amount": property_tax_arrears_cents,
            "amount_cents": property_tax_arrears_cents,
        },
        {
            "line_type": "HOA_ARREARS",
            "basis": "FLAT",
            "rate_or_amount": hoa_arrears_cents,
            "amount_cents": hoa_arrears_cents,
        },
        {
            "line_type": "JUNIOR_LIEN_PAYOFF",
            "basis": "FLAT",
            "rate_or_amount": junior_payoff_cents,
            "amount_cents": junior_payoff_cents,
        },
    ]

    gross_deductions_cents = sum(line["amount_cents"] for line in lines)

    if variant == "PRELIMINARY":
        mi_contribution_credit_cents = 0
    else:
        mi_contribution_credit_cents = mi_credit_cents

    # Evaluation order pinned: the tier is keyed on the PRE-incentive base net.
    base_net_cents = offer_price_cents - gross_deductions_cents + mi_contribution_credit_cents

    if base_net_cents >= K.RELOCATION_TIER_HIGH_MIN_CENTS:
        relocation_incentive_cents = K.RELOCATION_HIGH_CENTS
    elif base_net_cents >= K.RELOCATION_TIER_MID_MIN_CENTS:
        relocation_incentive_cents = K.RELOCATION_MID_CENTS
    else:
        relocation_incentive_cents = K.RELOCATION_LOW_CENTS

    net_proceeds_cents = base_net_cents - relocation_incentive_cents

    return {
        "commission_pct_applied": float(commission_pct_applied),
        "line_items": lines,
        "gross_deductions_cents": gross_deductions_cents,
        "mi_contribution_credit_cents": mi_contribution_credit_cents,
        "base_net_cents": base_net_cents,
        "relocation_incentive_cents": relocation_incentive_cents,
        "net_proceeds_cents": net_proceeds_cents,
    }


# ---------------------------------------------------------------------------
# calculations.dispute_reconciliation
# ---------------------------------------------------------------------------
def variance_pct(claimed_value_cents, recorded_value_cents):
    diff = abs(Decimal(claimed_value_cents) - Decimal(recorded_value_cents))
    return round_half_up(diff / Decimal(recorded_value_cents), 4)


def resolved_value(resolution, claimed_value_cents, recorded_value_cents):
    if resolution == "SUSTAINED":
        return claimed_value_cents
    if resolution == "PARTIAL":
        return round_half_up_cents(
            (Decimal(claimed_value_cents) + Decimal(recorded_value_cents)) / Decimal(2)
        )
    return recorded_value_cents
