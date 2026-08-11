from db import db
from services import calc
from services.store import touch, new_entity
from util import D, now


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def order_tariff(order):
    return db.tariffs.get(order['tariff_id'])


def accepted_estimate_for(order):
    cands = [e for e in db.estimates.values()
             if e['order_id'] == order['id'] and e['status'] == 'ACCEPTED']
    if not cands:
        return None
    cands.sort(key=lambda e: (e['created_at'], e['id']))
    return cands[-1]


def elected_coverage_for(order):
    for c in db.coverages.values():
        if c['order_id'] == order['id'] and c['status'] == 'ELECTED':
            return c
    return None


def locked_coverage_for(order):
    for c in db.coverages.values():
        if c['order_id'] == order['id'] and c['status'] == 'LOCKED':
            return c
    return None


def confirmed_assignment(order_id, role):
    cands = [a for a in db.assignments.values()
             if a['order_id'] == order_id and a['role'] == role and a['status'] == 'CONFIRMED']
    if not cands:
        return None
    cands.sort(key=lambda a: (a['created_at'], a['id']))
    return cands[0]


def statement_for_order(order_id):
    for s in db.statements.values():
        if s['order_id'] == order_id:
            return s
    return None


# ---------------------------------------------------------------------------
# SIT lots
# ---------------------------------------------------------------------------

def sit_lot_live_fields(lot):
    """(days_stored, accrued_storage_cents) — live while IN_STORAGE, frozen after."""
    if lot['status'] == 'IN_STORAGE':
        order = db.orders.get(lot['order_id'])
        tariff = order_tariff(order) if order else None
        rate = tariff['sit_daily_rate_cents_per_cwt'] if tariff else 0
        days = calc.sit_days(lot['checked_in_at'], now())
        return days, calc.sit_accrual(lot['stored_weight_cwt'], rate, days)
    return lot['days_stored'], lot['accrued_storage_cents']


def reevaluate_lot(lot):
    """180-day rule: auto-convert an IN_STORAGE lot whose days_stored >= SIT_MAX_DAYS."""
    if lot['status'] != 'IN_STORAGE':
        return
    days = calc.sit_days(lot['checked_in_at'], now())
    if days < calc.SIT_MAX_DAYS:
        return
    order = db.orders.get(lot['order_id'])
    tariff = order_tariff(order) if order else None
    rate = tariff['sit_daily_rate_cents_per_cwt'] if tariff else 0
    lot['status'] = 'CONVERTED_PERMANENT'
    lot['days_stored'] = days
    lot['accrued_storage_cents'] = calc.sit_accrual(lot['stored_weight_cwt'], rate, days)
    wh = db.warehouses.get(lot['warehouse_id'])
    if wh is not None:
        wh['occupied_cwt'] -= lot['stored_weight_cwt']
        touch(wh)
    touch(lot)


def reevaluate_all_lots():
    for lot in list(db.sit_lots.values()):
        reevaluate_lot(lot)


def order_sit_accrual_total(order_id):
    total = 0
    for lot in db.sit_lots.values():
        if lot['order_id'] == order_id:
            reevaluate_lot(lot)
            total += sit_lot_live_fields(lot)[1]
    return total


# ---------------------------------------------------------------------------
# Chargeback / quality cascades
# ---------------------------------------------------------------------------

def apply_chargeback(order_id, amount_cents):
    """Add amount to the order's statement chargeback total and recompute the
    HAULING agent's quality score."""
    stmt = statement_for_order(order_id)
    if stmt is not None:
        stmt['chargeback_total_cents'] += amount_cents
        touch(stmt)
        total = stmt['chargeback_total_cents']
    else:
        total = amount_cents
    hauling = None
    for a in db.assignments.values():
        if a['order_id'] == order_id and a['role'] == 'HAULING':
            hauling = a
            break
    if hauling is not None:
        agent = db.agents.get(hauling['agent_id'])
        if agent is not None:
            agent['quality_score'] = calc.quality_score_for(total)
            touch(agent)


def settle_claim_cascade(claim, settled_amount_cents, offered_by_user_id):
    """Shared cascade for claim acceptance (negotiated or arbitrated).

    Negotiated accept: settled := current offer (already recorded on the claim).
    Arbitration: settled := decision and offered_by := the arbitrator; the last
    negotiated offer_amount_cents is left untouched."""
    claim['settled_amount_cents'] = settled_amount_cents
    claim['offered_by_user_id'] = offered_by_user_id
    claim['status'] = 'ACCEPTED'
    touch(claim)
    apply_chargeback(claim['order_id'], settled_amount_cents)


# ---------------------------------------------------------------------------
# Delivery cascade
# ---------------------------------------------------------------------------

def deliver_cascade(order, charges):
    """Create the PROVISIONAL RevenueStatement, complete CONFIRMED assignments,
    credit agent ledgers."""
    tariff = order_tariff(order)
    locked = locked_coverage_for(order)
    locked_premium = locked['premium_cents'] if locked else 0

    linehaul_revenue = charges['linehaul_cents'] + charges['fuel_surcharge_cents']

    origin_crew_total = sum(
        c['invoice_amount_cents'] for c in db.crews.values()
        if c['order_id'] == order['id'] and c['service_end'] == 'ORIGIN' and c['status'] == 'COMPLETED')
    dest_crew_total = sum(
        c['invoice_amount_cents'] for c in db.crews.values()
        if c['order_id'] == order['id'] and c['service_end'] == 'DESTINATION' and c['status'] == 'COMPLETED')
    sit_total = order_sit_accrual_total(order['id'])
    accessorial = origin_crew_total + dest_crew_total + sit_total + locked_premium

    split_pcts = {}
    assignments = {}
    for role in ('BOOKING', 'ORIGIN', 'HAULING', 'DESTINATION'):
        asg = confirmed_assignment(order['id'], role)
        assignments[role] = asg
        split_pcts[role] = D(str(asg['split_pct'])) if asg and asg['split_pct'] is not None else D('0')

    shares, van_line_share = calc.waterfall(linehaul_revenue, split_pcts, locked_premium)

    stmt = new_entity()
    stmt.update({
        'order_id': order['id'],
        'linehaul_revenue_cents': linehaul_revenue,
        'accessorial_revenue_cents': accessorial,
        'booking_share_cents': shares['BOOKING'],
        'origin_share_cents': shares['ORIGIN'],
        'hauling_share_cents': shares['HAULING'],
        'destination_share_cents': shares['DESTINATION'],
        'van_line_share_cents': van_line_share,
        'chargeback_total_cents': 0,
        'status': 'PROVISIONAL',
    })
    db.statements[stmt['id']] = stmt

    # hop 2 + hop 3: complete assignments, write split amounts, credit agents
    for role, asg in assignments.items():
        if asg is None:
            continue
        amount = shares[role]
        if role == 'ORIGIN':
            amount += origin_crew_total
        elif role == 'DESTINATION':
            amount += dest_crew_total + sit_total
        asg['split_amount_cents'] = amount
        asg['status'] = 'COMPLETED'
        touch(asg)
        agent = db.agents.get(asg['agent_id'])
        if agent is not None:
            agent['ytd_linehaul_share_cents'] += amount
            touch(agent)

    return stmt
