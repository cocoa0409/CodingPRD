"""Calculation rules (PRD §3.3, §3.5, §3.7; SCAFFOLD §1.3).

All money is integer cents. Scores are carried to 2 decimal places. Rounding is
always round-half-up via Decimal.
"""
from decimal import Decimal, ROUND_HALF_UP

from db import db

MERIT_WEIGHT = Decimal("0.80")
PRICE_WEIGHT = Decimal("0.20")
ACCEPTABILITY_MIN = 70

RATING_VALUE = {
    "EXCEPTIONAL": 100,
    "VERY_GOOD": 85,
    "SATISFACTORY": 70,
    "MARGINAL": 50,
    "UNSATISFACTORY": 0,
}


def round_half_up_2(value):
    """Round a Decimal/number to 2 decimal places, half-up. Returns float."""
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    q = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)


def round_half_up_cents(value):
    """Round to a whole integer (cents), half-up."""
    d = Decimal(str(value)) if not isinstance(value, Decimal) else value
    q = d.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


# ----------------------------------------------------------------------------
# Scoring
# ----------------------------------------------------------------------------

def _factor_scores_of(proposal_id):
    return [fs for fs in db.factor_scores.values() if fs["proposal_id"] == proposal_id]


def non_price_scores(proposal_id):
    """FactorScores of a proposal whose factor.kind != PRICE."""
    result = []
    for fs in _factor_scores_of(proposal_id):
        factor = db.factors.get(fs["factor_id"])
        if factor is not None and factor["kind"] != "PRICE":
            result.append((fs, factor))
    return result


def is_acceptable(proposal_id):
    """Every non-PRICE raw_score >= 70."""
    nps = non_price_scores(proposal_id)
    return all(fs["raw_score"] >= ACCEPTABILITY_MIN for fs, _ in nps)


def compute_merit_score(proposal_id):
    """Weighted sum over non-PRICE factor scores, rounded 2dp, clamped 0..100."""
    nps = non_price_scores(proposal_id)
    raw = Decimal("0")
    for fs, factor in nps:
        raw += Decimal(str(fs["raw_score"])) * Decimal(str(factor["weight"]))
    merit = round_half_up_2(raw)
    if merit < 0:
        merit = 0.0
    if merit > 100:
        merit = 100.0
    return merit


def compute_value_score(proposal, solicitation, merit_score):
    """TRADEOFF value score. Pinned order: merit (rounded) -> price_norm (rounded)
    -> combine -> round once.

    min_price is taken over the ACCEPTABLE proposals of the solicitation, including
    the proposal currently being scored.
    """
    pool_prices = []
    for p in db.proposals.values():
        if p["solicitation_id"] != solicitation["id"]:
            continue
        if p["id"] == proposal["id"] or p["status"] == "ACCEPTABLE":
            pool_prices.append(p["total_price_cents"])
    if not pool_prices:
        pool_prices = [proposal["total_price_cents"]]
    min_price = min(pool_prices)

    own_price = proposal["total_price_cents"]
    if own_price == 0:
        # Avoid division by zero; lowest possible price earns full marks anyway.
        price_norm = round_half_up_2(Decimal("100")) if min_price == 0 else 0.0
    else:
        price_norm = round_half_up_2(
            (Decimal(str(min_price)) / Decimal(str(own_price))) * Decimal("100")
        )

    combined = (Decimal(str(merit_score)) * MERIT_WEIGHT
                + Decimal(str(price_norm)) * PRICE_WEIGHT)
    return round_half_up_2(combined)


# ----------------------------------------------------------------------------
# Fiscal aggregations
# ----------------------------------------------------------------------------

def modifications_of(contract_id):
    return [m for m in db.modifications.values() if m["contract_id"] == contract_id]


def invoices_of(contract_id):
    return [i for i in db.invoices.values() if i["contract_id"] == contract_id]


def clins_of(contract_id):
    return [c for c in db.clins.values() if c["contract_id"] == contract_id]


def compute_obligated_amount(contract):
    """base_value + approved OPTION_EXERCISE option_value + approved FUNDING delta."""
    total = contract["base_value_cents"]
    for m in modifications_of(contract["id"]):
        if m["status"] != "APPROVED":
            continue
        if m["mod_type"] == "OPTION_EXERCISE":
            total += m["option_value_cents"]
        elif m["mod_type"] == "FUNDING":
            total += m["delta_cents"]
    return total


def compute_cumulative_invoiced(contract):
    """Sum of amount_cents over APPROVED invoices of the contract."""
    return sum(i["amount_cents"] for i in invoices_of(contract["id"])
               if i["status"] == "APPROVED")


def compute_invoice_amount(invoice, contract):
    """Returns (amount_cents, fee_portion_cents)."""
    if contract["contract_type"] == "FFP":
        clin = db.clins.get(invoice["clin_id"])
        unit_price = clin["unit_price_cents"] if clin else 0
        amount = unit_price * invoice["invoiced_qty"]
        return amount, 0
    # CPFF: fee computed on the summed allowable_cost, rounded once.
    allowable = invoice["allowable_cost_cents"]
    tec = contract["total_estimated_cost_cents"]
    fixed_fee = contract["fixed_fee_cents"]
    fee_portion = round_half_up_cents(
        Decimal(str(fixed_fee)) * (Decimal(str(allowable)) / Decimal(str(tec)))
    )
    amount = allowable + fee_portion
    return amount, fee_portion


# ----------------------------------------------------------------------------
# Vendor performance index
# ----------------------------------------------------------------------------

def compute_performance_index(vendor_id):
    """Mean rating_value across CPARS reports of the vendor's contracts whose
    lifecycle_status in {ACTIVE, CLOSED}; null when none."""
    qualifying_contract_ids = [
        c["id"] for c in db.contracts.values()
        if c["vendor_id"] == vendor_id and c["lifecycle_status"] in ("ACTIVE", "CLOSED")
    ]
    qset = set(qualifying_contract_ids)
    values = [r["rating_value"] for r in db.cpars.values()
              if r["contract_id"] in qset]
    if not values:
        return None
    mean = Decimal(sum(values)) / Decimal(len(values))
    return round_half_up_2(mean)
