"""Transaction settlement engine (PRD §3.4, §3.5; calculations
line_item_tax, sourcing_resolution, remittance_responsibility).
"""
from decimal import Decimal, ROUND_HALF_UP

import db
from services import common, nexus


def _round2(d):
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _jurisdiction_by_state_code(code):
    for j in db.tax_jurisdictions.values():
        if j["state_code"] == code:
            return j
    return None


def _category_for(jurisdiction_id, category_code):
    for c in db.product_categories.values():
        if c["jurisdiction_id"] == jurisdiction_id and c["category_code"] == category_code:
            return c
    return None


def _line_items_for(txn_id):
    items = [li for li in db.line_items.values() if li["transaction_id"] == txn_id]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))  # insertion order
    return items


def _certificate_exempts(txn, sourced_state, category_code):
    """True iff customer_exempt_requested AND an ACTIVE matching certificate is
    valid against the current clock (valid_from <= clock < valid_to)."""
    if not txn["customer_exempt_requested"]:
        return False
    clock = db.now()
    for cert in db.exemption_certificates.values():
        if cert["status"] != "ACTIVE":
            continue
        if cert["seller_id"] != txn["seller_id"]:
            continue
        if cert["jurisdiction_id"] != sourced_state["id"]:
            continue
        if cert["customer_ref"] != txn["customer_ref"]:
            continue
        if cert["exempt_category_code"] != category_code:
            continue
        if cert["valid_from"] <= clock < cert["valid_to"]:
            return True
    return False


def resolve_sourcing(txn):
    """Return (sourcing_used, applied_rate, sourced_state) per §3.4.

    applied_rate is the sourced state's combined_rate. sourced_state is the
    jurisdiction record used for category lookup and nexus accrual.
    Raises if ORIGIN sourcing names a state with no matching jurisdiction.
    """
    dest = db.tax_jurisdictions[txn["jurisdiction_id"]]
    if dest["sourcing_rule"] == "ORIGIN":
        seller = db.sellers[txn["seller_id"]]
        origin = _jurisdiction_by_state_code(seller["origin_state_code"])
        if origin is None:
            # No jurisdiction configured for the seller's origin state.
            from errors import APIError, ERR_INVALID_STATE
            raise APIError(ERR_INVALID_STATE,
                           "no tax jurisdiction configured for the seller's origin state")
        return "ORIGIN", origin["combined_rate"], origin
    return "DESTINATION", dest["combined_rate"], dest


def settle(txn):
    """Perform the settlement calculation and accrual side effects in place.

    Caller has already verified state preconditions (PENDING, has line items,
    seller ACTIVE). This populates the computed fields and accrues nexus.
    """
    sourcing_used, applied_rate, sourced_state = resolve_sourcing(txn)

    lines = _line_items_for(txn["id"])
    applied_rate_d = Decimal(str(applied_rate))
    reduced_rate_d = Decimal(str(sourced_state["reduced_rate"]))

    taxable_subtotal = Decimal("0")
    tax_collected = Decimal("0")

    for li in lines:
        qty = Decimal(str(li["quantity"]))
        unit = Decimal(str(li["unit_price"]))
        base = qty * unit

        cat = _category_for(sourced_state["id"], li["category_code"])
        cat_taxability = cat["taxability"] if cat else "FULL"
        cert_exempt = _certificate_exempts(txn, sourced_state, li["category_code"])

        if cert_exempt or cat_taxability == "EXEMPT":
            li["line_taxability"] = "EXEMPT"
            li["line_tax"] = 0.00
            # excluded from taxable_subtotal
        elif cat_taxability == "REDUCED":
            li["line_taxability"] = "REDUCED"
            line_tax = _round2(base * reduced_rate_d)
            li["line_tax"] = float(line_tax)
            taxable_subtotal += base
            tax_collected += line_tax
        else:
            li["line_taxability"] = "FULL"
            line_tax = _round2(base * applied_rate_d)
            li["line_tax"] = float(line_tax)
            taxable_subtotal += base
            tax_collected += line_tax

    taxable_subtotal = _round2(taxable_subtotal)
    # round-then-sum: per-line amounts were already rounded; their sum is exact.

    txn["sourcing_used"] = sourcing_used
    txn["applied_rate"] = applied_rate
    txn["taxable_subtotal"] = float(taxable_subtotal)
    txn["tax_collected"] = float(tax_collected)

    # ---- Remittance responsibility (§3.5) ----
    responsibility = _remittance_responsibility(txn)
    txn["remittance_responsibility"] = responsibility

    # ---- Nexus accrual (only when SELLER-responsible) ----
    if responsibility == "SELLER":
        profile = nexus.find_profile(txn["seller_id"], sourced_state["id"])
        if profile is not None:
            profile["cumulative_taxable_sales"] = float(
                _round2(Decimal(str(profile["cumulative_taxable_sales"])) + taxable_subtotal)
            )
            profile["cumulative_txn_count"] += 1
            nexus.recompute_status(profile)
            common.touch(profile)

    txn["settlement_status"] = "SETTLED"
    # remember which state nexus accrued to, for void de-accrual and return sweep
    txn["_sourced_state_id"] = sourced_state["id"]


def _remittance_responsibility(txn):
    dest = db.tax_jurisdictions[txn["jurisdiction_id"]]
    fac_id = txn["facilitator_id"]
    if fac_id is not None:
        fac = db.marketplace_facilitators.get(fac_id)
        if fac is not None and dest["state_code"] in fac["collecting_state_codes"]:
            return "MARKETPLACE"
    return "SELLER"


def void(txn):
    """De-accrue nexus for a SELLER-responsible transaction (§3.5)."""
    if txn["remittance_responsibility"] == "SELLER":
        sourced_state_id = txn.get("_sourced_state_id")
        if sourced_state_id is not None:
            profile = nexus.find_profile(txn["seller_id"], sourced_state_id)
            if profile is not None:
                new_sales = (
                    Decimal(str(profile["cumulative_taxable_sales"]))
                    - Decimal(str(txn["taxable_subtotal"]))
                )
                profile["cumulative_taxable_sales"] = float(_round2(new_sales))
                profile["cumulative_txn_count"] -= 1
                # recompute; REGISTERED stays sticky inside recompute_status
                nexus.recompute_status(profile)
                common.touch(profile)
    txn["settlement_status"] = "VOIDED"
