"""Calculation rules (PRD 3.3, 3.6, 3.5) with integer-cent, round-half-up precision."""

from decimal import Decimal, ROUND_CEILING

from store import db
from util import D, rhu, num_out


def project_valuation(project, variant):
    """Pinned eleven-step valuation (PRD 3.3).

    variant == 'estimate' : billable quantity = measured_quantity*(1+waste_factor),
                            live Product.unit_price_cents.
    variant == 'as_built' : installed_quantity (no waste), pinned_unit_price_cents.

    Returns (total_cents, prompt_pay_discount_cents).
    """
    lines = [l for l in db.line_items.values() if l['project_id'] == project['id']]
    measurements = [m for m in db.site_measurements.values() if m['project_id'] == project['id']]

    material_subtotal = 0          # int cents (sum of per-line rounded charges)
    paver_sqft = Decimal(0)
    wall_qty = Decimal(0)
    feature_count = 0

    for line in lines:
        product = db.products[line['product_id']]
        if variant == 'estimate':
            qty = D(line['measured_quantity']) * (Decimal(1) + D(product['waste_factor']))
            unit_price = D(product['unit_price_cents'])
        else:  # as_built
            iq = line.get('installed_quantity')
            qty = D(iq) if iq is not None else Decimal(0)
            pp = line.get('pinned_unit_price_cents')
            unit_price = D(pp) if pp is not None else Decimal(0)

        # 1. per-line material, rounded half up
        material_subtotal += rhu(qty * unit_price)

        if line['category'] == 'PAVER':
            paver_sqft += qty
        if line['category'] == 'WALL_BLOCK':
            wall_qty += qty
        if product['is_feature']:
            feature_count += 1

    # 3. paver labor — flat rate by tier applied to the whole paver sqft
    if paver_sqft <= 200:
        rate = 700
    elif paver_sqft <= 500:
        rate = 600
    else:
        rate = 525
    base_paver_labor = paver_sqft * rate

    complex_site = any(D(m['wall_height_in']) >= 48 for m in measurements)
    if complex_site:
        base_paver_labor = Decimal(rhu(base_paver_labor * Decimal('1.15')))

    # 4-5. wall + feature labor
    wall_labor = wall_qty * 900
    feature_labor = feature_count * 25000

    # 6-7.
    labor_cost = base_paver_labor + wall_labor + feature_labor
    pre_tax = Decimal(material_subtotal) + labor_cost

    # 8. prompt-pay discount
    if pre_tax >= 2000000:
        prompt_pay = rhu(pre_tax * Decimal('0.02'))
    else:
        prompt_pay = 0

    # 9. tax on material only
    tax = rhu(Decimal(material_subtotal) * Decimal('0.0725'))

    # 10. permit fee
    permit_fee = 35000 if project['permit_required'] else 0

    # 11. total
    total = pre_tax - Decimal(prompt_pay) + Decimal(tax) + Decimal(permit_fee)
    return int(rhu(total)), int(prompt_pay)


def material_order_pallets(order):
    """Pinned rounding order: ceil per line to whole pallets, THEN sum (PRD 3.6).

    Returns (total_pallets, total_sqft_ordered).
    """
    total_pallets = 0
    total_sqft = Decimal(0)
    for lid in order['line_item_ids']:
        line = db.line_items[lid]
        product = db.products[line['product_id']]
        if product['unit'] not in ('SQFT', 'FACE_SQFT'):
            continue
        coverage = D(product['coverage_per_pallet_sqft'])
        if coverage <= 0:
            continue
        billable = D(line['measured_quantity']) * (Decimal(1) + D(product['waste_factor']))
        pallets = int((billable / coverage).to_integral_value(rounding=ROUND_CEILING))
        total_pallets += pallets
        total_sqft += Decimal(pallets) * coverage
    return total_pallets, num_out(total_sqft)


def deposit_cap(project):
    """min(round_half_up(contract_value*0.10), 100000) (PRD 3.5)."""
    return min(rhu(D(project['contract_value_cents']) * Decimal('0.10')), 100000)
