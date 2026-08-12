"""Pure calculation rules — SCAFFOLD §1.3. Integer cents, round-half-up."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

import db

FREIGHT_FLAT_MAX_GALLONS = 2000
FREIGHT_FLAT_CENTS = 15000
FREIGHT_MID_MAX_GALLONS = 6000
FREIGHT_MID_TC_PER_GAL = 40
FREIGHT_HIGH_TC_PER_GAL = 32

LATE_PENALTY_RATE = Decimal('0.05')
DUE_DATE_LAG_DAYS = 20
RENEWAL_INCENTIVE_PCT = Decimal('0.01')
FULFILLMENT_THRESHOLD_PCT = Decimal('95.00')


def D(x):
    return Decimal(str(x))


def rhu(dec):
    """Round half-up to integer."""
    return int(dec.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def rhu2(dec):
    """Round half-up to two decimals, returned as Decimal."""
    return dec.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def resolve_posted_posting(terminal_code, product_id, on_date_str):
    """POSTED posting for (terminal, product) with max effective_date <= D,
    tie broken by latest created_at (insertion seq breaks exact ties)."""
    best = None
    for p in db.STORE['postings'].values():
        if p['terminal_code'] != terminal_code or p['product_id'] != product_id:
            continue
        if p['status'] != 'POSTED':
            continue
        if p['effective_date'] > on_date_str:
            continue
        key = (p['effective_date'], p['created_at'], p['_seq'])
        if best is None or key > best[0]:
            best = (key, p)
    return best[1] if best else None


def invoice_amounts(gallons, price_tc_per_gal, product, station):
    """invoice_total_cents: each component rounded to cents BEFORE the sum."""
    fuel = rhu(D(gallons) * D(price_tc_per_gal) / 10)
    if gallons <= FREIGHT_FLAT_MAX_GALLONS:
        freight = FREIGHT_FLAT_CENTS
    elif gallons <= FREIGHT_MID_MAX_GALLONS:
        freight = rhu(D(gallons) * FREIGHT_MID_TC_PER_GAL / 10)
    else:
        freight = rhu(D(gallons) * FREIGHT_HIGH_TC_PER_GAL / 10)
    tax_rate = (product['federal_excise_tc_per_gal']
                + station['state_excise_tc_per_gal']
                + station['local_option_tc_per_gal'])
    tax = rhu(D(gallons) * D(tax_rate) / 10)
    return {
        'fuel_amount_cents': fuel,
        'freight_amount_cents': freight,
        'tax_amount_cents': tax,
        'total_cents': fuel + freight + tax,
    }


def fulfilled_gallons(agreement):
    """Sum of delivered_gallons over this station's RECONCILED drops whose
    delivery clock-date falls within [term_start_date, term_end_date]."""
    total = 0
    for d in db.STORE['drops'].values():
        if d['station_id'] != agreement['station_id']:
            continue
        if d['status'] != 'RECONCILED':
            continue
        ddate = d['delivered_at'].date().isoformat()
        if agreement['term_start_date'] <= ddate <= agreement['term_end_date']:
            total += d['delivered_gallons']
    return total


def buyout_figures(agreement):
    """buyout_base_cents (both variants) + buyout_net_settlement_cents."""
    start = date.fromisoformat(agreement['term_start_date'])
    end = date.fromisoformat(agreement['term_end_date'])
    total_days = (end - start).days
    remaining_days = max(0, (end - db.clock_now().date()).days)
    unfulfilled = max(0, agreement['committed_gallons']
                      - fulfilled_gallons(agreement))
    base_uad = rhu(D(agreement['imaging_allowance_cents'])
                   * D(remaining_days) / D(total_days))
    base_lm = rhu(D(unfulfilled) * D(agreement['margin_tc_per_gal']) / 10)
    penalty = rhu(D(unfulfilled)
                  * D(agreement['shortfall_penalty_tc_per_gal']) / 10)
    if agreement['buyout_method'] == 'UNAMORTIZED_DISCOUNT':
        base, alternate = base_uad, base_lm
    else:
        base, alternate = base_lm, base_uad
    net = max(0, base - penalty)
    return {
        'method': agreement['buyout_method'],
        'base_cents': base,
        'alternate_base_cents': alternate,
        'shortfall_penalty_cents': penalty,
        'net_settlement_cents': net,
    }


def recon_figures(station_id):
    """inventory_variance_gallons: book, physical gross, gross/net variance.

    Net is temperature-corrected per tank (round-half-up to whole gallons
    per tank before summing); tanks never gauged use temp 60.
    """
    tanks = [t for t in db.STORE['tanks'].values()
             if t['station_id'] == station_id]
    book = 0
    physical_gross = 0
    corrected_sum = 0
    for t in tanks:
        book += t['book_inventory_gallons']
        physical_gross += t['physical_gallons']
        temp = t['physical_temp_f'] if t['physical_temp_f'] is not None else 60
        product = db.STORE['products'][t['product_id']]
        coeff = D(product['temp_coeff'])
        corrected = rhu(D(t['physical_gallons'])
                        * (Decimal(1) + coeff * (D(temp) - D(60))))
        corrected_sum += corrected
    return {
        'book_gallons': book,
        'physical_gross_gallons': physical_gross,
        'variance_gross_gallons': physical_gross - book,
        'variance_net_gallons': corrected_sum - book,
    }


def book_inventory_gallons(tank):
    """book_inventory_gallons: opening + RECONCILED deliveries - all metered
    - tank-level losses in {VERIFIED, WRITTEN_OFF}."""
    total = tank['opening_physical_gallons']
    for d in db.STORE['drops'].values():
        if d['tank_id'] == tank['id'] and d['status'] == 'RECONCILED':
            total += d['delivered_gallons']
    for m in db.STORE['meters'].values():
        if m['tank_id'] == tank['id']:
            total -= m['metered_gallons']
    for le in db.STORE['losses'].values():
        if (le['tank_id'] == tank['id']
                and le['status'] in ('VERIFIED', 'WRITTEN_OFF')):
            total -= le['gallons']
    return total


def credit_band_for(exposure_cents, credit_limit_cents):
    """Exact integer band comparison: WATCH iff exposure*5 >= limit*4."""
    if exposure_cents * 5 >= credit_limit_cents * 4:
        return 'WATCH'
    return 'GOOD_STANDING'


def station_exposure_cents(station_id):
    """credit_exposure_cents: sum of totals over ISSUED/OVERDUE invoices."""
    return sum(i['total_cents'] for i in db.STORE['invoices'].values()
               if i['station_id'] == station_id
               and i['status'] in ('ISSUED', 'OVERDUE'))


def volume_fulfillment_pct(fulfilled, committed):
    return rhu2(D(100) * D(fulfilled) / D(committed))


def renewal_credit_cents(fulfilled, committed, imaging_allowance_cents):
    pct = volume_fulfillment_pct(fulfilled, committed)
    if pct >= FULFILLMENT_THRESHOLD_PCT:
        return rhu(RENEWAL_INCENTIVE_PCT * D(imaging_allowance_cents))
    return 0


def tax_remittance_figures(remittance):
    """tax_remittance_amount: per-category lines rounded BEFORE summing."""
    included = []
    for inv in db.STORE['invoices'].values():
        if inv['status'] not in ('ISSUED', 'OVERDUE', 'PAID'):
            continue
        if not (remittance['period_start'] <= inv['invoice_date']
                <= remittance['period_end']):
            continue
        station = db.STORE['stations'][inv['station_id']]
        if station['state_code'] != remittance['state_code']:
            continue
        included.append((inv, station))
    gasoline_gallons = 0
    diesel_gallons = 0
    lines = {}  # (category, state_excise_tc_per_gal) -> gallons
    for inv, station in included:
        product = db.STORE['products'][inv['product_id']]
        cat = product['category']
        if cat == 'GASOLINE':
            gasoline_gallons += inv['gallons_delivered']
        else:
            diesel_gallons += inv['gallons_delivered']
        key = (cat, station['state_excise_tc_per_gal'])
        lines[key] = lines.get(key, 0) + inv['gallons_delivered']
    tax = 0
    for (_cat, rate), gals in lines.items():
        tax += rhu(D(gals) * D(rate) / 10)
    if db.clock_date_str() > remittance['due_date']:
        penalty = rhu(LATE_PENALTY_RATE * D(tax))
    else:
        penalty = 0
    return {
        'gasoline_gallons': gasoline_gallons,
        'diesel_gallons': diesel_gallons,
        'tax_amount_cents': tax,
        'late_penalty_cents': penalty,
        'total_due_cents': tax + penalty,
    }
