"""Money and index arithmetic.

Every monetary figure is an integer number of cents.  Percentage arithmetic goes
through Decimal with ROUND_HALF_UP applied once, at the point the PRD names, and
never through binary floating point (PRD 2.6).
"""

from decimal import Decimal, ROUND_HALF_UP

ONE = Decimal(1)
HUNDREDTH = Decimal("0.01")

# scaffold constants
CREDIT_CARD_FEE_PCT = Decimal("2.5")
VARIANCE_TOLERANCE_PCT = Decimal("10.00")
VARIANCE_ESCALATION_PCT = Decimal("25.00")
COMP_ALLOWANCE_PCT = Decimal("3.00")
COOP_ARTIST_SHARE_PCT = Decimal("50")
COOP_CAP_PCT_OF_BASE = Decimal("5")
POSTURE_OPEN_MAX_PCT = Decimal("70")
POSTURE_WATCH_MAX_PCT = Decimal("90")
POSTURE_RESTRICTED_MAX_PCT = Decimal("100")
INSURANCE_DEDUCTIBLE_CENTS = 500000
INSURANCE_POLICY_CAP_CENTS = 25000000
INSURANCE_CLAIM_WINDOW_DAYS = 30
OFFER_TTL_HOURS = 72
NEGOTIATION_ROUND_LIMIT = 3
ARTIST_REST_BUFFER_HOURS = 36
CASH_PAYMENT_LIMIT_CENTS = 1000000
EXPOSURE_OVERRIDE_MULTIPLIER = 2


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value):
    """Round a Decimal to a whole cent, half away from zero."""
    return int(dec(value).quantize(ONE, rounding=ROUND_HALF_UP))


def rhu2(value):
    """Round to two decimal places, half away from zero (percentages)."""
    return dec(value).quantize(HUNDREDTH, rounding=ROUND_HALF_UP)


def pct_of(amount, percentage):
    """ROUND_HALF_UP(amount * percentage / 100) in whole cents."""
    return rhu(dec(amount) * dec(percentage) / Decimal(100))


def number(value):
    """JSON-friendly rendering of a percentage."""
    if isinstance(value, Decimal):
        return float(value)
    return value


# ---------------------------------------------------------------------------
# receipts waterfall (PRD 3.7)
# ---------------------------------------------------------------------------

def waterfall(gross_cents, ticket_count, venue):
    ticket_tax = pct_of(gross_cents, venue["ticket_tax_pct"])
    facility = venue["facility_fee_cents_per_ticket"] * ticket_count
    credit_card = pct_of(gross_cents - ticket_tax, CREDIT_CARD_FEE_PCT)
    adjusted = gross_cents - ticket_tax - facility - credit_card
    return {
        "gross_receipts_cents": gross_cents,
        "ticket_tax_cents": ticket_tax,
        "facility_fee_cents": facility,
        "credit_card_fee_cents": credit_card,
        "adjusted_gross_cents": adjusted,
    }


# ---------------------------------------------------------------------------
# artist earnings (PRD 3.7)
# ---------------------------------------------------------------------------

def artist_base_earnings(deal_structure, guarantee_cents, versus_pct,
                         backend_pct, adjusted_gross_cents,
                         allowed_expense_cents, breakeven_cents):
    if deal_structure == "VERSUS":
        net_receipts = adjusted_gross_cents - allowed_expense_cents
        return max(guarantee_cents, pct_of(net_receipts, versus_pct))
    if deal_structure == "GUARANTEE_PLUS_BACKEND":
        overage = max(0, adjusted_gross_cents - breakeven_cents)
        return guarantee_cents + pct_of(overage, backend_pct)
    return guarantee_cents


def coop_contribution(base_earnings_cents, marketing_expense_cents):
    share_leg = pct_of(marketing_expense_cents, COOP_ARTIST_SHARE_PCT)
    cap_leg = pct_of(base_earnings_cents, COOP_CAP_PCT_OF_BASE)
    return min(share_leg, cap_leg)


# ---------------------------------------------------------------------------
# venue reimbursement and the promoter split (PRD 3.7)
# ---------------------------------------------------------------------------

VENUE_PCT_FIELD = {
    "PRODUCTION": "venue_expense_pct_production",
    "MARKETING": "venue_expense_pct_marketing",
    "STAFFING": "venue_expense_pct_staffing",
    "HOSPITALITY": "venue_expense_pct_hospitality",
}


def venue_reimbursement(show, lines, amount_key):
    """CO_PROMOTE only: rounded per line against the category percentage, then summed."""
    if show["venue_arrangement"] != "CO_PROMOTE":
        return 0
    total = 0
    for line in lines:
        percentage = show[VENUE_PCT_FIELD[line["category"]]]
        total += pct_of(line[amount_key], percentage)
    return total


def promoter_split(show, adjusted_gross_cents, artist_earnings_cents,
                   total_expense_cents, reimbursement_cents):
    if show["venue_arrangement"] == "RENTAL":
        promoter_borne = total_expense_cents
        venue_share = show["rental_fee_cents"]
        promoter_net = (adjusted_gross_cents - artist_earnings_cents
                        - promoter_borne - venue_share)
        return promoter_borne, venue_share, promoter_net
    promoter_borne = total_expense_cents - reimbursement_cents
    net_before_split = adjusted_gross_cents - artist_earnings_cents - promoter_borne
    venue_share = pct_of(max(0, net_before_split),
                         show["copromote_venue_share_pct"])
    promoter_net = net_before_split - venue_share
    return promoter_borne, venue_share, promoter_net


# ---------------------------------------------------------------------------
# full settlement figures, shared by the FINAL and PROVISIONAL variants
# ---------------------------------------------------------------------------

def settlement_figures(show, venue, artist, offer, lines, gross_cents,
                       ticket_count, amount_key):
    figures = waterfall(gross_cents, ticket_count, venue)
    adjusted = figures["adjusted_gross_cents"]

    total_expense = sum(line[amount_key] for line in lines)
    deductible = sum(line[amount_key] for line in lines
                     if line["is_artist_deductible"])
    marketing = sum(line[amount_key] for line in lines
                    if line["category"] == "MARKETING")

    if offer is not None:
        deal_structure = offer["deal_structure"]
        guarantee = offer["guarantee_cents"]
        deposit = offer["deposit_cents"]
        expense_cap = offer["expense_cap_cents"]
        versus_pct = offer["versus_pct"]
        backend_pct = offer["backend_split_artist_pct"]
    else:
        deal_structure = None
        guarantee = 0
        deposit = 0
        expense_cap = None
        versus_pct = 0
        backend_pct = 0

    allowed = deductible if expense_cap is None else min(deductible, expense_cap)
    breakeven = guarantee + allowed

    base = artist_base_earnings(deal_structure, guarantee, versus_pct,
                                backend_pct, adjusted, allowed, breakeven)
    coop = coop_contribution(base, marketing)
    earnings = base - coop
    withholding = pct_of(earnings, artist["withholding_pct"])
    payment_due = earnings - withholding - deposit

    reimbursement = venue_reimbursement(show, lines, amount_key)
    promoter_borne, venue_share, promoter_net = promoter_split(
        show, adjusted, earnings, total_expense, reimbursement)

    figures.update({
        "deal_structure_applied": deal_structure,
        "total_settlement_expense_cents": total_expense,
        "allowed_expense_cents": allowed,
        "venue_expense_reimbursement_cents": reimbursement,
        "promoter_borne_expense_cents": promoter_borne,
        "breakeven_cents": breakeven,
        "artist_base_earnings_cents": base,
        "artist_coop_contribution_cents": coop,
        "artist_earnings_cents": earnings,
        "withholding_cents": withholding,
        "deposit_credit_cents": deposit,
        "payment_due_cents": payment_due,
        "venue_share_cents": venue_share,
        "promoter_net_cents": promoter_net,
    })
    return figures


# ---------------------------------------------------------------------------
# risk posture and insurance
# ---------------------------------------------------------------------------

def risk_posture(utilization_pct):
    if utilization_pct <= POSTURE_OPEN_MAX_PCT:
        return "OPEN"
    if utilization_pct <= POSTURE_WATCH_MAX_PCT:
        return "WATCH"
    if utilization_pct < POSTURE_RESTRICTED_MAX_PCT:
        return "RESTRICTED"
    return "FROZEN"


def utilization_pct(committed_cents, limit_cents):
    if not limit_cents:
        return Decimal("0.00")
    return rhu2(dec(committed_cents) * Decimal(100) / dec(limit_cents))


def insurance_amounts(claim_amount_cents, unrecovered_cost_cents):
    covered = min(claim_amount_cents, unrecovered_cost_cents,
                  INSURANCE_POLICY_CAP_CENTS)
    covered = max(0, covered)
    recovery = max(0, min(covered - INSURANCE_DEDUCTIBLE_CENTS,
                          INSURANCE_POLICY_CAP_CENTS))
    return covered, recovery
