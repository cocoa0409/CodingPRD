"""Fair lifecycle: create, posture machine, settlement sweep, logical clock."""
from decimal import Decimal
from flask import Blueprint

import errors
import services
from db import store, new_record, touch, parse_dt, iso
from middleware import require_roles, authenticate
from response import success_object
from util import (
    body, require, require_int, require_num, require_str, require_dt,
    SPECIES, POSTURES,
)
from views import fair_view

bp = Blueprint('fairs', __name__)


@bp.post('/v1/fairs')
def create_fair():
    require_roles('FairBoardAdmin')
    b = body()
    name = require_str(b, 'name')
    ownership_deadline = require_dt(b, 'ownership_deadline_at')
    possession_deadline = require_dt(b, 'possession_deadline_at')
    budget = require_int(b, 'premium_budget_cents', minimum=0)
    commission_rate = require_num(b, 'commission_rate', minimum=0)
    buyer_premium_rate = require_num(b, 'buyer_premium_rate', minimum=0)
    yardage_fee = require_int(b, 'yardage_fee_cents', minimum=0)
    premium_cap = require_int(b, 'premium_cap_cents', minimum=0)
    premium_schedule = require(b, 'premium_schedule')
    if not isinstance(premium_schedule, dict):
        raise errors.invalid_request('premium_schedule must be an object')
    state_qualify_rank = require(b, 'state_qualify_rank')
    if not isinstance(state_qualify_rank, dict):
        raise errors.invalid_request('state_qualify_rank must be an object')
    sale_rank_threshold = require(b, 'sale_rank_threshold')
    if not isinstance(sale_rank_threshold, dict):
        raise errors.invalid_request('sale_rank_threshold must be an object')
    species_sale_order = require(b, 'species_sale_order')
    if (not isinstance(species_sale_order, list)
            or any(s not in SPECIES for s in species_sale_order)):
        raise errors.invalid_request('species_sale_order must be a list of species enums')

    large_min = b.get('large_class_min_entries', 8)
    if not isinstance(large_min, int) or isinstance(large_min, bool) or large_min < 0:
        raise errors.invalid_request('large_class_min_entries must be a non-negative integer')
    large_bonus = b.get('large_class_bonus_rate', 0.10)
    if not isinstance(large_bonus, (int, float)) or isinstance(large_bonus, bool) or large_bonus < 0:
        raise errors.invalid_request('large_class_bonus_rate must be a non-negative number')

    fair = new_record({
        'name': name,
        'ownership_deadline_at': ownership_deadline,
        'possession_deadline_at': possession_deadline,
        'premium_budget_cents': budget,
        'commission_rate': commission_rate,
        'buyer_premium_rate': buyer_premium_rate,
        'yardage_fee_cents': yardage_fee,
        'premium_cap_cents': premium_cap,
        'large_class_min_entries': large_min,
        'large_class_bonus_rate': large_bonus,
        'premium_schedule': premium_schedule,
        'state_qualify_rank': state_qualify_rank,
        'sale_rank_threshold': sale_rank_threshold,
        'species_sale_order': species_sale_order,
        'posture': 'SETUP',
    })
    store.fairs[fair['id']] = fair
    return success_object(fair_view(fair), status=201)


def get_fair_or_404(fair_id):
    fair = store.fairs.get(fair_id)
    if fair is None:
        raise errors.not_found('Fair not found')
    return fair


@bp.get('/v1/fairs/<fairId>')
def get_fair(fairId):
    authenticate()
    return success_object(fair_view(get_fair_or_404(fairId)))


@bp.post('/v1/fairs/<fairId>/advance-posture')
def advance_posture(fairId):
    require_roles('FairBoardAdmin')
    fair = get_fair_or_404(fairId)
    b = body()
    to_posture = require(b, 'to_posture')
    if to_posture not in POSTURES:
        raise errors.invalid_request('to_posture is not a declared posture')
    current = fair['posture']
    idx = POSTURES.index(current)
    # Strictly one step; skipping or going backward is invalid (CLOSED has no next).
    if idx + 1 >= len(POSTURES) or POSTURES[idx + 1] != to_posture:
        raise errors.invalid_state('Posture advance is strictly one step in canonical order')

    if current == 'AUCTION' and to_posture == 'SETTLEMENT':
        for lot in store.auction_lots.values():
            if lot['fair_id'] == fair['id'] and lot['status'] not in ('SOLD', 'NO_SALE'):
                raise errors.invalid_state('Every auction lot must be SOLD or NO_SALE before settlement')
    if current == 'SETTLEMENT' and to_posture == 'CLOSED':
        for inv in store.invoices.values():
            if inv['fair_id'] == fair['id'] and inv['status'] != 'PAID':
                raise errors.invalid_state('Every invoice must be PAID before closing')
        for award in services.awards_of_fair(fair['id']):
            if award['status'] not in ('PAID', 'FORFEITED'):
                raise errors.invalid_state('Every premium award must be PAID or FORFEITED before closing')
        entry_ids = {e['id'] for e in services.entries_of_fair(fair['id'])}
        for d in store.dispositions.values():
            if d['entry_id'] in entry_ids and d['status'] not in ('COMPLETED', 'REJECTED'):
                raise errors.invalid_state('Every disposition order must be COMPLETED or REJECTED before closing')

    fair['posture'] = to_posture
    touch(fair)
    return success_object(fair_view(fair))


@bp.post('/v1/fairs/<fairId>/reopen-entries')
def reopen_entries(fairId):
    require_roles('FairBoardAdmin')
    fair = get_fair_or_404(fairId)
    if fair['posture'] != 'ENTRIES_LOCKED':
        raise errors.invalid_state('Only ENTRIES_LOCKED can reopen to ENTRIES_OPEN')
    entry_ids = {e['id'] for e in services.entries_of_fair(fair['id'])}
    for t in store.weigh_tickets.values():
        if t['entry_id'] in entry_ids and t['status'] == 'ACTIVE':
            raise errors.invalid_state('Cannot reopen entries once an ACTIVE weigh ticket exists')
    fair['posture'] = 'ENTRIES_OPEN'
    touch(fair)
    return success_object(fair_view(fair))


@bp.post('/v1/fairs/<fairId>/run-settlement')
def run_settlement(fairId):
    require_roles('FairBoardAdmin')
    fair = get_fair_or_404(fairId)

    # Final premium amounts (premium_award_amount, final variant).
    outstanding_awards = [a for a in services.awards_of_fair(fair['id'])
                          if a['status'] in ('ACCRUED', 'APPROVED')]
    outstanding = sum(a['provisional_amount_cents'] for a in outstanding_awards)
    if outstanding == 0:
        scale = Decimal(1)
    else:
        scale = min(Decimal(1), Decimal(fair['premium_budget_cents']) / Decimal(outstanding))
    for a in outstanding_awards:
        final = services.floor_cents(Decimal(a['provisional_amount_cents']) * scale)
        if a['final_amount_cents'] != final:
            a['final_amount_cents'] = final
            touch(a)

    # Final exhibitor payouts (exhibitor_payout, final variant) for SOLD lots.
    for lot in store.auction_lots.values():
        if lot['fair_id'] == fair['id'] and lot['status'] == 'SOLD':
            final_payout = services.exhibitor_payout_final(fair, lot)
            if lot['final_payout_cents'] != final_payout:
                lot['final_payout_cents'] = final_payout
                touch(lot)

    touch(fair)
    return success_object(fair_view(fair))


@bp.post('/_clock/set_current_utc')
def set_clock():
    require_roles('FairBoardAdmin')
    b = body()
    raw = require(b, 'to_iso8601')
    dt = parse_dt(raw)
    if dt is None:
        raise errors.invalid_request('to_iso8601 must be an ISO 8601 datetime')
    store.logical_now = dt
    return success_object({'current_utc': iso(store.logical_now)})
