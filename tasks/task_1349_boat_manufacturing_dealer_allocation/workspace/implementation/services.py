"""Business-logic services: pricing, deposits, HIN assignment, waitlist
promotion, floor-plan waterfall, carrying accrual, recall cascades.

Every rule here traces to SCAFFOLD §1.3 calculations and PRD §3 prose.
"""
import math
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from store import (DB, CLOCK, fmt_dt, rhu, touch, new_rec, next_seq,
                   recount_allocation, recompute_reserved, recompute_utilized,
                   tier_for, tier_for_ratio, TIER_RATES)
from util import ApiError


# ---------------------------------------------------------------- pricing
STANDING_DISCOUNT = {
    'PREFERRED': Decimal('0.10'),
    'STANDARD': Decimal('0.05'),
    'PROBATION': Decimal('0.00'),
}
STANDING_DELTA = {
    'PREFERRED': Decimal('-0.02'),
    'STANDARD': Decimal('0.00'),
    'PROBATION': Decimal('0.05'),
}
SOURCE_RATE = {
    'RETAIL': Decimal('0.10'),
    'FLEET': Decimal('0.15'),
}
MIN_RATE = Decimal('0.03')
MIN_DEPOSIT_CENTS = 50000
SURCHARGE_RATE = Decimal('0.03')


def make_lines(order_id, option_ids, dealer):
    """Create OrderOptionLine rows with price/standing snapshots.

    Per-line rounding is pinned: line_total = rhu(unit * (1 - discount)).
    OrderOptionLine carries only id and created_at (no updated_at/version).
    """
    created = []
    now = CLOCK.now()
    for oid in option_ids:
        opt = DB['options'][oid]
        unit = opt['price_cents']
        disc = STANDING_DISCOUNT[dealer['standing']]
        total = rhu(Decimal(unit) * (Decimal('1') - disc))
        line = {
            'id': str(uuid.uuid4()),
            'order_id': order_id,
            'option_package_id': oid,
            'unit_price_cents': unit,
            'discount_pct_applied': float(disc),
            'line_total_cents': total,
            'created_at': fmt_dt(now),
            '_cts': now,
            '_seq': next_seq(),
        }
        DB['lines'][line['id']] = line
        created.append(line)
    return created


def order_lines(order_id):
    return [l for l in DB['lines'].values() if l['order_id'] == order_id]


def delete_lines(order_id):
    for lid in [l['id'] for l in order_lines(order_id)]:
        del DB['lines'][lid]


def compute_pricing(order, lines):
    """order_invoice_total: base (locked) + sum of per-line rounded totals,
    then 3% surcharge rounded half up (pinned order 2 -> 3 -> 5)."""
    options_total = sum(l['line_total_cents'] for l in lines)
    subtotal = order['base_price_cents'] + options_total
    surcharge = rhu(Decimal(subtotal) * SURCHARGE_RATE)
    order['options_total_cents'] = options_total
    order['surcharge_cents'] = surcharge
    order['invoice_total_cents'] = subtotal + surcharge


def required_deposit_value(invoice_cents, source, standing, show_event_id):
    """max(50000, rhu(invoice * effective_rate)); rate floor 0.03."""
    if source == 'BOAT_SHOW':
        event = DB['shows'].get(show_event_id)
        base_rate = Decimal(str(event['surge_deposit_rate']))
    else:
        base_rate = SOURCE_RATE[source]
    effective = base_rate + STANDING_DELTA[standing]
    if effective < MIN_RATE:
        effective = MIN_RATE
    return max(MIN_DEPOSIT_CENTS, rhu(Decimal(invoice_cents) * effective))


def compute_required_deposit(order, dealer):
    order['required_deposit_cents'] = required_deposit_value(
        order['invoice_total_cents'], order['source'], dealer['standing'],
        order['show_event_id'])


def compute_production_hours(order, lines):
    model = DB['models'][order['model_id']]
    order['production_hours'] = (
        model['production_hours'] + sum(DB['options'][l['option_package_id']]['production_hours']
                                        for l in lines))


def preview_pricing(order, option_ids, dealer):
    """Candidate (options_total, hours, invoice, required) for a replacement
    option set — computed WITHOUT mutating the store (amend atomicity)."""
    model = DB['models'][order['model_id']]
    disc = STANDING_DISCOUNT[dealer['standing']]
    options_total = sum(
        rhu(Decimal(DB['options'][x]['price_cents']) * (Decimal('1') - disc))
        for x in option_ids)
    hours = model['production_hours'] + sum(
        DB['options'][x]['production_hours'] for x in option_ids)
    subtotal = order['base_price_cents'] + options_total
    invoice = subtotal + rhu(Decimal(subtotal) * SURCHARGE_RATE)
    required = required_deposit_value(invoice, order['source'],
                                      dealer['standing'],
                                      order['show_event_id'])
    return options_total, hours, invoice, required


def check_option_compatibility(model_id, option_ids):
    """ERR_OPTION_INCOMPATIBLE: option of a different model, or a declared
    incompatible pair in either direction (symmetric)."""
    opts = []
    for oid in option_ids:
        opt = DB['options'].get(oid)
        if opt is None:
            raise ApiError(404, 'ERR_OPTION_NOT_FOUND',
                           'OptionPackage not found: %s' % oid)
        opts.append(opt)
    for opt in opts:
        if opt['model_id'] != model_id:
            raise ApiError(422, 'ERR_OPTION_INCOMPATIBLE',
                           'Option %s belongs to a different model' % opt['option_code'])
    ids = set(option_ids)
    for opt in opts:
        other = opt.get('incompatible_with_option_id')
        if other and other in ids:
            raise ApiError(422, 'ERR_OPTION_INCOMPATIBLE',
                           'Option set contains a declared incompatible pair')


# ---------------------------------------------------------------- HIN
def month_letter(month):
    # A=Jan ... L=Dec (verified by PRD example: August -> H).
    return chr(ord('A') + month - 1)


def assign_hin(model, completed_dt):
    """serial per (model_id, model_year); HIN = BRW + serial(5) + month letter
    + last digit of completion year + model_year mod 100 (2)."""
    existing = [h['serial_no'] for h in DB['hulls'].values()
                if h['model_id'] == model['id']]
    serial = 1 + max(existing) if existing else 1
    hin = ('BRW' + '%05d' % serial
           + month_letter(completed_dt.month)
           + str(completed_dt.year % 10)
           + '%02d' % (model['model_year'] % 100))
    return serial, hin


# ---------------------------------------------------------------- waitlist
def promote_waitlist(freed_slot):
    """waitlist_promotion_selector: exactly one promotion per release event.
    Boost: BOAT_SHOW order whose event's closed window contains the clock date.
    Ranking: boost DESC, then created_at ASC (id never consulted)."""
    if freed_slot['status'] != 'OPEN':
        return
    run = DB['runs'][freed_slot['run_id']]
    if run['status'] != 'OPEN':
        return
    available = freed_slot['capacity_hours'] - recompute_reserved(freed_slot['id'])
    clock_date = CLOCK.now().date()

    def boosted(order):
        if order['source'] != 'BOAT_SHOW':
            return 0
        event = DB['shows'].get(order['show_event_id'])
        if event is None:
            return 0
        return 1 if event['_start'] <= clock_date <= event['_end'] else 0

    candidates = []
    for o in DB['orders'].values():
        if o['status'] != 'WAITLISTED':
            continue
        if o['production_hours'] > available:
            continue
        dealer = DB['dealers'][o['dealer_id']]
        if recount_allocation(dealer['id']) >= dealer['annual_allocation_quota']:
            continue
        candidates.append(o)
    if not candidates:
        return  # fallback: slot stays OPEN with freed hours; no error
    candidates.sort(key=lambda o: (-boosted(o), o['_cts'], o['_seq']))
    winner = candidates[0]
    winner['status'] = 'ALLOCATED'
    winner['slot_id'] = freed_slot['id']
    touch(winner)
    freed_slot['reserved_hours'] = recompute_reserved(freed_slot['id'])
    touch(freed_slot)
    dealer = DB['dealers'][winner['dealer_id']]
    dealer['allocation_used'] = recount_allocation(dealer['id'])
    touch(dealer)


# ---------------------------------------------------------------- floor plan
def interest_to_date(advance):
    """Whole days from last_accrual_date to clock date; rhu per settlement."""
    now = CLOCK.now()
    lad = advance['_last_accrual']
    base = datetime(lad.year, lad.month, lad.day, tzinfo=timezone.utc)
    days = math.floor((now - base).total_seconds() / 86400)
    if days <= 0:
        return 0
    rate = TIER_RATES[advance['rate_tier']]
    return rhu(Decimal(advance['outstanding_principal_cents']) * rate
               * Decimal(days) / Decimal(365))


def total_due(dealer_id):
    total = 0
    for a in DB['advances'].values():
        if a['dealer_id'] == dealer_id and a['status'] == 'OPEN':
            total += interest_to_date(a) + a['outstanding_principal_cents']
    return total


def apply_curtailment(dealer, amount_cents):
    """Waterfall: OPEN advances oldest first (opened_at ASC, created_at ASC
    tie-break); interest settles before principal within each advance."""
    opens = [a for a in DB['advances'].values()
             if a['dealer_id'] == dealer['id'] and a['status'] == 'OPEN']
    opens.sort(key=lambda a: (a['_opened_dt'], a['_cts'], a['_seq']))
    remaining = amount_cents
    for a in opens:
        if remaining <= 0:
            break
        owed = interest_to_date(a)
        paid_interest = min(remaining, owed)
        a['accrued_interest_cents'] += paid_interest
        a['last_accrual_date'] = CLOCK.now().date().isoformat()
        a['_last_accrual'] = CLOCK.now().date()
        remaining -= paid_interest
        paid_principal = min(remaining, a['outstanding_principal_cents'])
        a['outstanding_principal_cents'] -= paid_principal
        remaining -= paid_principal
        if a['outstanding_principal_cents'] == 0:
            a['status'] = 'PAID'
        touch(a)
    dealer['floor_plan_utilized_cents'] = recompute_utilized(dealer['id'])
    dealer['current_rate_tier'] = tier_for(dealer['floor_plan_utilized_cents'],
                                           dealer['floor_plan_limit_cents'])
    touch(dealer)


# ---------------------------------------------------------------- carrying
SEASON_FACTOR = {
    'PEAK': Decimal('1.25'),
    'SHOULDER': Decimal('1.00'),
    'OFF_PEAK': Decimal('0.60'),
}
DAILY_RATE_CENTS = 750


def carrying_for_hull(hull, run):
    """Whole days from completed_at to clock; actual = days*750;
    seasonal = rhu(actual * season_factor)."""
    now = CLOCK.now()
    days = math.floor((now - hull['_completed_dt']).total_seconds() / 86400)
    actual = days * DAILY_RATE_CENTS
    seasonal = rhu(Decimal(actual) * SEASON_FACTOR[run['season']])
    return actual, seasonal


# ---------------------------------------------------------------- recall
def remedy_notice(notice, path):
    """Shared remedy cascade: notice -> REMEDIED; hull hold lifted iff no
    other NOTIFIED notice remains; campaign open_notice_count -= 1 and
    auto-CLOSED at 0."""
    notice['status'] = 'REMEDIED'
    notice['remedy_path'] = path
    notice['remedied_at'] = fmt_dt(CLOCK.now())
    touch(notice)
    hull = DB['hulls'][notice['hull_id']]
    still_open = any(n['status'] == 'NOTIFIED'
                     for n in DB['notices'].values()
                     if n['hull_id'] == hull['id'])
    if not still_open and hull['certification_status'] == 'RECALL_HOLD':
        hull['certification_status'] = 'CERTIFIED'
        touch(hull)
    campaign = DB['campaigns'][notice['campaign_id']]
    campaign['open_notice_count'] -= 1
    touch(campaign)
    if campaign['open_notice_count'] == 0 and campaign['status'] == 'ISSUED':
        campaign['status'] = 'CLOSED'
        touch(campaign)


# ---------------------------------------------------------------- restocking
FEE_PCT = {
    'WAITLISTED': Decimal('0.00'),
    'ALLOCATED': Decimal('0.05'),
    'COMMITTED': Decimal('0.12'),
}


def restocking_fee(order):
    fee = rhu(Decimal(order['invoice_total_cents']) * FEE_PCT[order['status']])
    if order['source'] == 'BOAT_SHOW':
        fee = max(fee, order['deposit_paid_cents'])
    return fee
