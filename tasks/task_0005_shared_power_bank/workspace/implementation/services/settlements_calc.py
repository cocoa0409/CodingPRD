"""Revenue-share calculation for settlements (PRD §3.9). Pinned ordering: round per rental, then sum."""
from decimal import Decimal
from common import to_money, round_half_up
from db import db


def _qualifying_universe(settlement: dict) -> list:
    pid = settlement["location_partner_id"]
    p_start = settlement["period_start"]
    p_end = settlement["period_end"]
    out = []
    for r in db.rentals.values():
        if r["rental_status"] != "RETURNED":
            continue
        if r.get("returned_at") is None:
            continue
        if not (p_start <= r["returned_at"] < p_end):
            continue
        cab = db.cabinets.get(r["start_cabinet_id"])
        if cab is None or cab["location_partner_id"] != pid:
            continue
        out.append(r)
    return out


def compute_provisional(settlement: dict, partner: dict) -> dict:
    """Returns {gross_revenue, partner_amount, refund_adjustment} all as Decimal('0.00')-quantized values."""
    universe = _qualifying_universe(settlement)
    pct: Decimal = partner["revenue_share_pct"]
    billed = [r for r in universe if r["payment_status"] == "BILLED"]
    partner_amount = sum(
        (round_half_up(r["charged_amount"] * pct, 2) for r in billed),
        Decimal("0.00"),
    )
    gross_revenue = sum((r["charged_amount"] for r in billed), Decimal("0.00"))
    return {
        "gross_revenue": to_money(gross_revenue),
        "partner_amount": to_money(partner_amount),
        "refund_adjustment": Decimal("0.00"),
    }


def compute_settled(settlement: dict, partner: dict) -> dict:
    universe = _qualifying_universe(settlement)
    pct: Decimal = partner["revenue_share_pct"]
    billed = [r for r in universe if r["payment_status"] == "BILLED"]
    refunded = [r for r in universe if r["payment_status"] == "REFUNDED"]

    refund_adjustment = sum(
        (round_half_up((r["refund_amount"] or Decimal("0.00")) * pct, 2) for r in refunded),
        Decimal("0.00"),
    )
    billed_partner_sum = sum(
        (round_half_up(r["charged_amount"] * pct, 2) for r in billed),
        Decimal("0.00"),
    )
    partner_amount = billed_partner_sum - refund_adjustment

    gross_billed = sum((r["charged_amount"] for r in billed), Decimal("0.00"))
    gross_refunded = sum(((r["refund_amount"] or Decimal("0.00")) for r in refunded), Decimal("0.00"))
    gross_revenue = gross_billed - gross_refunded

    return {
        "gross_revenue": to_money(gross_revenue),
        "partner_amount": to_money(partner_amount),
        "refund_adjustment": to_money(refund_adjustment),
    }


def per_rental_partner_share(rental: dict, partner: dict, *, basis: str) -> Decimal:
    """Used as a cascade-leg helper when a refund affects an INVOICED settlement.
    basis: 'refund_amount' or 'charged_amount'.
    """
    pct: Decimal = partner["revenue_share_pct"]
    base = rental[basis] or Decimal("0.00")
    return to_money(round_half_up(base * pct, 2))
