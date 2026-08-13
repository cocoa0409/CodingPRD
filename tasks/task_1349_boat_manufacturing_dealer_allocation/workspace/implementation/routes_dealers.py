"""Dealer endpoints (onboarding, OCC-guarded update, curtailments) and the
boat-show calendar."""
from flask import Blueprint, request

from store import DB, new_rec, serialize, touch, tier_for
from services import total_due, apply_curtailment
from util import (ApiError, respond, list_response, auth_context, require_roles,
                  json_body, present, need, as_str, as_int, as_num, as_enum,
                  as_date, invalid, get_or_404)

bp = Blueprint('dealers', __name__)

STANDINGS = {'PREFERRED', 'STANDARD', 'PROBATION'}


# ---------------------------------------------------------------- dealers
@bp.post('/dealers')
def create_dealer():
    uid, role = auth_context()
    require_roles(role, 'AllocationManager')
    data = json_body()
    dealer_code = as_str(need(data, 'dealer_code'), 'dealer_code')
    name = as_str(need(data, 'name'), 'name')
    region = as_str(need(data, 'region'), 'region')
    quota = as_int(need(data, 'annual_allocation_quota'),
                   'annual_allocation_quota')
    if quota < 0:
        invalid('annual_allocation_quota must be >= 0')
    limit = as_int(need(data, 'floor_plan_limit_cents'), 'floor_plan_limit_cents')
    if limit <= 0:
        invalid('floor_plan_limit_cents must be > 0')
    standing = 'STANDARD'
    if present(data, 'standing'):
        standing = as_enum(data['standing'], 'standing', STANDINGS)
    if any(d['dealer_code'] == dealer_code for d in DB['dealers'].values()):
        invalid('dealer_code must be unique across Dealer')
    rec = new_rec({
        'dealer_code': dealer_code,
        'name': name,
        'region': region,
        'standing': standing,
        'annual_allocation_quota': quota,
        'allocation_used': 0,
        'floor_plan_limit_cents': limit,
        'floor_plan_utilized_cents': 0,
        'current_rate_tier': 'TIER_STANDARD',
    })
    DB['dealers'][rec['id']] = rec
    return respond(serialize(rec), 201)


@bp.get('/dealers')
def list_dealers():
    auth_context()
    return list_response(list(DB['dealers'].values()), serialize)


@bp.get('/dealers/<did>')
def get_dealer(did):
    auth_context()
    rec = get_or_404(DB['dealers'], did, 'ERR_DEALER_NOT_FOUND', 'Dealer')
    return respond(serialize(rec), 200)


@bp.patch('/dealers/<did>')
def update_dealer(did):
    uid, role = auth_context()
    require_roles(role, 'AllocationManager')
    data = json_body()
    # family 3: schema/domain
    expected = as_int(need(data, 'expected_dealer_version'),
                      'expected_dealer_version')
    new_quota = new_limit = new_standing = None
    if present(data, 'annual_allocation_quota'):
        new_quota = as_int(data['annual_allocation_quota'],
                           'annual_allocation_quota')
        if new_quota < 0:
            invalid('annual_allocation_quota must be >= 0')
    if present(data, 'floor_plan_limit_cents'):
        new_limit = as_int(data['floor_plan_limit_cents'],
                           'floor_plan_limit_cents')
        if new_limit <= 0:
            invalid('floor_plan_limit_cents must be > 0')
    if present(data, 'standing'):
        new_standing = as_enum(data['standing'], 'standing', STANDINGS)
    # family 4: path existence
    dealer = get_or_404(DB['dealers'], did, 'ERR_DEALER_NOT_FOUND', 'Dealer')
    # family 6: OCC
    if expected != dealer['version']:
        raise ApiError(412, 'ERR_STALE_DEALER_VERSION',
                       'expected_dealer_version does not match current version')
    if new_quota is not None:
        dealer['annual_allocation_quota'] = new_quota
    if new_limit is not None:
        dealer['floor_plan_limit_cents'] = new_limit
        # tier re-derived whenever the limit itself changes (PRD §3.2)
        dealer['current_rate_tier'] = tier_for(
            dealer['floor_plan_utilized_cents'], dealer['floor_plan_limit_cents'])
    if new_standing is not None:
        dealer['standing'] = new_standing
    touch(dealer)
    return respond(serialize(dealer), 200)


@bp.post('/dealers/<did>/curtailments')
def post_curtailment(did):
    uid, role = auth_context()
    require_roles(role, 'DealerPrincipal')
    # family 2: DealerPrincipal acts only on own dealer (path id == X-User-ID)
    if did != uid:
        raise ApiError(403, 'ERR_INSUFFICIENT_PERMISSIONS',
                       'DealerPrincipal may only post curtailments for own dealer')
    data = json_body()
    expected = as_int(need(data, 'expected_dealer_version'),
                      'expected_dealer_version')
    amount = as_int(need(data, 'amount_cents'), 'amount_cents')
    if amount < 0:
        invalid('amount_cents must be >= 0')
    dealer = get_or_404(DB['dealers'], did, 'ERR_DEALER_NOT_FOUND', 'Dealer')
    if expected != dealer['version']:
        raise ApiError(412, 'ERR_STALE_DEALER_VERSION',
                       'expected_dealer_version does not match current version')
    # family 11: payment may not exceed total due (exact payoff allowed)
    if amount > total_due(dealer['id']):
        raise ApiError(422, 'ERR_CURTAILMENT_EXCEEDS_BALANCE',
                       'Curtailment exceeds total due across OPEN advances')
    apply_curtailment(dealer, amount)
    return respond(serialize(dealer), 200)


# ---------------------------------------------------------------- shows
@bp.post('/boat-show-events')
def create_show():
    uid, role = auth_context()
    require_roles(role, 'AllocationManager')
    data = json_body()
    event_name = as_str(need(data, 'event_name'), 'event_name')
    region = as_str(need(data, 'region'), 'region')
    start = as_date(need(data, 'start_date'), 'start_date')
    end = as_date(need(data, 'end_date'), 'end_date')
    if end < start:
        invalid('end_date must be >= start_date')
    surge = as_num(need(data, 'surge_deposit_rate'), 'surge_deposit_rate')
    boost = as_int(need(data, 'allocation_boost'), 'allocation_boost')
    # family 10: same-region closed windows may not overlap (shared day = conflict)
    for o in DB['shows'].values():
        if o['region'] == region and start <= o['_end'] and o['_start'] <= end:
            raise ApiError(409, 'ERR_SHOW_WINDOW_OVERLAP',
                           'Overlapping boat-show window in the same region')
    rec = new_rec({
        'event_name': event_name,
        'region': region,
        'start_date': start.isoformat(),
        'end_date': end.isoformat(),
        'surge_deposit_rate': surge,
        'allocation_boost': boost,
    })
    rec['_start'] = start
    rec['_end'] = end
    DB['shows'][rec['id']] = rec
    return respond(serialize(rec), 201)


@bp.get('/boat-show-events')
def list_shows():
    auth_context()
    items = list(DB['shows'].values())
    region = request.args.get('region')
    if region is not None:
        items = [s for s in items if s['region'] == region]
    return list_response(items, serialize)
