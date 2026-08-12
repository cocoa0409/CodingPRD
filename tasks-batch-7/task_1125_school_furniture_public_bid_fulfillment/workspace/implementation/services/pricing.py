"""Calculation rules (SCAFFOLD.yaml §1.3): coop tiered pricing, install closeout,
warranty coverage, replacement deadline. Money is integer cents; rounding is
round-half-up via Decimal."""
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from db import store
from services.cascade import award_of_po, po_of_line, spec_of_line
from validation import add_years, pdate

EARLY_COMPLETION_CREDIT_PCT = Decimal("0.03")
REPLACEMENT_BUFFER_DAYS = 14
MAX_REPLACEMENT_DAYS = 21


def _round_half_up_int(d):
    return int(Decimal(d).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ------------------------------------------------------- coop tiered pricing

def district_ytd_coop_volume(agreement_id, district_id, fiscal_year):
    """Sum of ordered_qty over non-CANCELLED POLines referencing the agreement,
    on POs of the same district whose fiscal_year == agreement.contract_year."""
    volume = 0
    for line in store.po_lines.values():
        if line["status"] == "CANCELLED":
            continue
        if line.get("coop_agreement_id") != agreement_id:
            continue
        po = po_of_line(line)
        if po is None or po["fiscal_year"] != fiscal_year:
            continue
        award = award_of_po(po)
        if award is None or award["district_id"] != district_id:
            continue
        volume += line["ordered_qty"]
    return volume


def coop_tiered_price(award, po, spec_line, ordered_qty):
    """Returns (computed_unit_price_cents, line_total_cents).

    COOP_TIERED: marginal per-unit pricing keyed on cumulative district volume.
    AWARD_FLAT: pinned flat unit price.
    """
    if award["pricing_mode"] == "AWARD_FLAT":
        unit = award["flat_unit_price_cents"]
        return unit, ordered_qty * unit

    agreement = store.coop_agreements.get(award.get("coop_agreement_id"))
    tiers = agreement["tier_table"] if agreement else []
    c = district_ytd_coop_volume(award["coop_agreement_id"], award["district_id"], po["fiscal_year"])
    total = 0
    for u in range(c + 1, c + ordered_qty + 1):
        best = None
        for row in tiers:
            if u >= row["min_qty"] and (best is None or row["min_qty"] > best["min_qty"]):
                best = row
        if best is not None:
            total += best["unit_price_cents"]
    unit = _round_half_up_int(Decimal(total) / Decimal(ordered_qty))
    return unit, total


# ----------------------------------------------------------- install closeout

def install_closeout_total(po):
    """Pinned order (do not reorder): per-line whole-dollar rounding, then sum,
    then midpoint early-completion credit, then subtract."""
    award = award_of_po(po)
    spec = store.bid_specs.get(award["bid_spec_id"])
    lines = [l for l in store.po_lines.values()
             if l["purchase_order_id"] == po["id"] and l["status"] != "CANCELLED"]

    subtotal = 0
    for line in lines:
        charge = _round_half_up_int(
            Decimal(line["ordered_qty"] * award["install_rate_cents"]) / Decimal(100)
        ) * 100
        subtotal += charge

    start = pdate(spec["delivery_window_start"])
    end = pdate(spec["delivery_window_end"])
    mid_date = start + timedelta(days=(end - start).days // 2)

    installed_dates = [l["installed_at"][:10] for l in lines if l.get("installed_at")]
    credit = 0
    if installed_dates and max(installed_dates) <= mid_date.isoformat():
        credit = _round_half_up_int(
            Decimal(subtotal) * EARLY_COMPLETION_CREDIT_PCT / Decimal(100)
        ) * 100

    return subtotal - credit


# --------------------------------------------------------- warranty coverage

def warranty_term_end(award, district, installed_date):
    """Latest filing date allowed (inclusive)."""
    base_end = add_years(installed_date, award["warranty_years"])
    if district.get("extended_warranty_enrolled"):
        base_end = add_years(base_end, award.get("extended_years", 0))
    return base_end


def warranty_base_end(award, installed_date):
    return add_years(installed_date, award["warranty_years"])


def warranty_coverage(claim, line, award, district):
    """STANDARD_TERM: full parts cost. EXTENDED_PRORATED: declines by
    1/extended_years per started year past the base term end."""
    if not district.get("extended_warranty_enrolled"):
        return claim["parts_cost_cents"]

    installed_date = pdate(line["installed_at"][:10])
    base_end = warranty_base_end(award, installed_date)
    claim_date = pdate(claim["filed_date"])
    days_past = max(0, (claim_date - base_end).days)
    years_started = (days_past + 364) // 365 if days_past > 0 else 0
    extended_years = award.get("extended_years", 0)
    if extended_years <= 0:
        pct = Decimal(1) if years_started == 0 else Decimal(0)
    else:
        pct = max(Decimal(0), Decimal(extended_years - years_started) / Decimal(extended_years))
    return _round_half_up_int(Decimal(claim["parts_cost_cents"]) * pct)


# ------------------------------------------------------ replacement deadline

def replacement_deadline(line, reported_date):
    """min(delivery_window_end + 14d, reported_date + 21d)."""
    spec = spec_of_line(line)
    window_end = pdate(spec["delivery_window_end"])
    return min(window_end + timedelta(days=REPLACEMENT_BUFFER_DAYS),
               reported_date + timedelta(days=MAX_REPLACEMENT_DAYS))
