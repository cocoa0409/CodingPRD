"""negotiated_capital_price and five_year_tco (PRD sections 3.8 and 3.4)."""

from decimal import Decimal

from db import db
from numeric import dec, r0

HORIZON_YEARS = 5
BUDGETARY_ESCALATION_PCT = Decimal("0.05")
YEAR1_UTILIZATION_RAMP = Decimal("0.85")
WARRANTY_WAIVES_YEAR1_MONTHS = 12
WARRANTY_WAIVES_YEAR2_MONTHS = 24


def price_quote(quote, contract):
    """The six ordered steps of negotiated_capital_price."""
    list_price = quote["list_price_cents"]

    # Step 1 — tier from the list price alone, floors inclusive.
    if list_price >= contract["tier_large_floor_cents"]:
        tier = "LARGE"
        tier_pct = dec(contract["large_tier_pct"])
    elif list_price >= contract["tier_mid_floor_cents"]:
        tier = "MID"
        tier_pct = dec(contract["mid_tier_pct"])
    else:
        tier = "SMALL"
        tier_pct = dec(contract["small_tier_pct"])

    # Step 2 — the GPO discount.
    discount = r0(Decimal(list_price) * tier_pct)

    # Step 3 — the multi-unit addendum, applied to the post-discount amount.
    if quote["multi_unit_count"] >= 2:
        addendum = r0(Decimal(list_price - discount)
                      * dec(contract["multi_unit_addendum_pct"]))
    else:
        addendum = 0

    # Step 4 — the subtotal.
    subtotal = list_price - discount - addendum

    # Step 5 — the trade-in credit, capped against the subtotal.
    if quote.get("trade_in_asset_id"):
        cap = r0(Decimal(subtotal) * dec(contract["trade_in_cap_pct"]))
        credit = min(quote["trade_in_offer_cents"], cap)
    else:
        credit = 0

    # Step 6 — the net capital price of one unit.
    net = subtotal - credit

    quote["gpo_tier"] = tier
    quote["gpo_discount_cents"] = discount
    quote["multi_unit_addendum_cents"] = addendum
    quote["subtotal_cents"] = subtotal
    quote["trade_in_credit_cents"] = credit
    quote["net_capital_cents"] = net
    return quote


def five_year_tco(request, variant, quote=None):
    """Returns (operating_5y_cents, tco_cents, baseline_year1_opex_cents)."""
    negotiated = variant == "negotiated"
    if negotiated:
        escalation = dec(quote["service_escalation_pct"])
        warranty = quote["warranty_months"]
        capital = quote["net_capital_cents"] + request["facility_modification_cents"]
    else:
        escalation = BUDGETARY_ESCALATION_PCT
        warranty = 0
        capital = (request["estimated_capital_cents"]
                   + request["facility_modification_cents"])

    service_contract = Decimal(request["annual_service_contract_cents"])
    disposable_base = (Decimal(request["projected_annual_volume"])
                       * Decimal(request["disposable_unit_cents"]))

    operating = 0
    first_year = 0
    for year in range(1, HORIZON_YEARS + 1):
        waived = negotiated and (
            (warranty >= WARRANTY_WAIVES_YEAR1_MONTHS and year == 1)
            or (warranty >= WARRANTY_WAIVES_YEAR2_MONTHS and year <= 2))
        if waived:
            service_year = 0
        else:
            service_year = r0(service_contract
                              * ((Decimal(1) + escalation) ** (year - 1)))
        if year == 1:
            disposables_year = r0(disposable_base * YEAR1_UTILIZATION_RAMP)
        else:
            disposables_year = r0(disposable_base)
        operating += service_year + disposables_year
        if year == 1:
            first_year = service_year + disposables_year

    return operating, capital + operating, first_year


def write_budgetary(request):
    operating, tco, baseline = five_year_tco(request, "budgetary")
    request["budgetary_operating_5y_cents"] = operating
    request["budgetary_tco_cents"] = tco
    if request.get("negotiated_tco_cents") is None:
        request["baseline_year1_opex_cents"] = baseline
    return request


def write_negotiated(request, quote):
    operating, tco, baseline = five_year_tco(request, "negotiated", quote)
    request["negotiated_operating_5y_cents"] = operating
    request["negotiated_tco_cents"] = tco
    request["baseline_year1_opex_cents"] = baseline
    return request


def clear_negotiated(request):
    request["negotiated_operating_5y_cents"] = None
    request["negotiated_tco_cents"] = None
    _, _, baseline = five_year_tco(request, "budgetary")
    request["baseline_year1_opex_cents"] = baseline
    return request


def funded_amount(request):
    """request_funded_amount (PRD 3.9)."""
    accepted = None
    for row in db.quotes.values():
        if row["request_id"] == request["id"] and row["status"] == "ACCEPTED":
            accepted = row
            break
    capital = (accepted["net_capital_cents"] if accepted is not None
               else request["estimated_capital_cents"])
    return capital + request["facility_modification_cents"]
