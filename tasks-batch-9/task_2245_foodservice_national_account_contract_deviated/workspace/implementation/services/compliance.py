"""Compliance measurement, rebate accrual and posture derivation
(SCAFFOLD calculations contracted_purchase_compliance_pct, rebate_accrual_split,
contract_compliance_posture)."""

from db import db, values
from util import cents, dec, pct
from services.pricing import (
    CONTRACT_MINIMUM_COMPLIANCE_PCT,
    DEVIATION_BREACH_POSTURE_LIMIT,
    MANUFACTURER_FUNDING_SHARE_PCT,
)

QUALIFYING_PRICING_STATUSES = ("INVOICED", "REPRICED")
REBATE_RATE_TIERS = (
    (dec("95.00"), dec("4.00")),
    (dec("90.00"), dec("3.00")),
    (dec("80.00"), dec("1.50")),
    (dec("0.00"), dec("0.00")),
)


def qualifying_lines(contract_id, period_start, period_end):
    rows = [ol for ol in values(db.order_lines)
            if ol["contract_id"] == contract_id
            and ol["pricing_status"] in QUALIFYING_PRICING_STATUSES
            and ol["order_date"] >= period_start
            and ol["order_date"] < period_end]
    return sorted(rows, key=lambda ol: (ol["order_date"], ol["created_at"], ol["_seq"]))


def measure(contract, period):
    qualifying = qualifying_lines(
        contract["id"], period["period_start"], period["period_end"])
    contracted = [ol for ol in qualifying if ol["is_contracted_item"] is True]

    gross_purchases_cents = sum(ol["extended_price_cents"] for ol in qualifying)
    contracted_purchases_cents = sum(ol["extended_price_cents"] for ol in contracted)
    qualifying_cases = sum(ol["quantity_cases"] for ol in qualifying)
    contracted_cases = sum(ol["quantity_cases"] for ol in contracted)

    if contract["compliance_basis"] == "DOLLAR_WEIGHTED":
        numerator = contracted_purchases_cents
        denominator = gross_purchases_cents
    else:
        numerator = contracted_cases
        denominator = qualifying_cases

    if denominator == 0:
        compliance_pct = dec("0.00")
    else:
        compliance_pct = pct(dec(numerator) * dec(100) / dec(denominator))

    return {
        "gross_purchases_cents": gross_purchases_cents,
        "contracted_purchases_cents": contracted_purchases_cents,
        "qualifying_cases": qualifying_cases,
        "contracted_cases": contracted_cases,
        "compliance_pct": compliance_pct,
        "_contracted_lines": contracted,
    }


def rate_for(compliance_pct):
    for floor, rate in REBATE_RATE_TIERS:
        if compliance_pct >= floor:
            return rate
    return dec("0.00")


def accrue(contracted_lines, rebate_rate_pct):
    """Rounded per contracted line, then summed (rounding order is pinned)."""
    total = 0
    for line in contracted_lines:
        total += cents(dec(line["extended_price_cents"]) * dec(rebate_rate_pct) / dec(100))
    manufacturer_funded = cents(
        dec(total) * dec(MANUFACTURER_FUNDING_SHARE_PCT) / dec(100))
    return total, manufacturer_funded, total - manufacturer_funded


def latest_final_period(contract_id):
    rows = [p for p in db.rebate_periods.values()
            if p["contract_id"] == contract_id and p["status"] in ("CLOSED", "SETTLED")]
    if not rows:
        return None
    rows.sort(key=lambda p: (p["period_start"], p["created_at"], p["_seq"]), reverse=True)
    return rows[0]


def recompute_posture(contract):
    """Derives compliance_posture in place; the caller owns the version bump."""
    latest = latest_final_period(contract["id"])
    if contract["deviation_breach_count"] >= DEVIATION_BREACH_POSTURE_LIMIT:
        posture = "RESTRICTED"
    elif latest is None:
        posture = "OPEN"
    elif dec(latest["compliance_pct"]) < CONTRACT_MINIMUM_COMPLIANCE_PCT:
        posture = "RESTRICTED"
    elif dec(latest["compliance_pct"]) < dec(contract["contracted_purchase_pct_target"]):
        posture = "WATCH"
    else:
        posture = "OPEN"
    contract["compliance_posture"] = posture
    return posture


def compliance_report(contract, evaluated_at):
    finals = [p for p in db.rebate_periods.values()
              if p["contract_id"] == contract["id"]
              and p["status"] in ("CLOSED", "SETTLED")]
    latest = latest_final_period(contract["id"])
    report = {
        "contract_id": contract["id"],
        "evaluated_at": evaluated_at,
        "closed_period_count": len(finals),
        "latest_period_id": None,
        "latest_compliance_pct": None,
        "latest_rebate_rate_pct": None,
        "contracted_purchase_pct_target": contract["contracted_purchase_pct_target"],
        "shortfall_pct": None,
        "compliance_basis": contract["compliance_basis"],
        "compliance_posture": contract["compliance_posture"],
    }
    if latest is not None:
        report["latest_period_id"] = latest["id"]
        report["latest_compliance_pct"] = latest["compliance_pct"]
        report["latest_rebate_rate_pct"] = latest["rebate_rate_pct"]
        if latest["compliance_pct"] is not None:
            report["shortfall_pct"] = pct(
                dec(contract["contracted_purchase_pct_target"])
                - dec(latest["compliance_pct"]))
    return report
