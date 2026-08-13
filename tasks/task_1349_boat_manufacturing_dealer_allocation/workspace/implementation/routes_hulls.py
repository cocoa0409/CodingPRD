"""Hulls: production completion (HIN assignment), segregated certification,
and the delivery cascade that opens the floor-plan advance."""
from flask import Blueprint, request

from store import (DB, CLOCK, fmt_dt, new_rec, serialize, touch,
                   recompute_utilized, tier_for, tier_for_ratio, TIER_RATES)
from services import assign_hin
from util import (ApiError, respond, list_response, auth_context, require_roles,
                  json_body, need, as_str, get_or_404)
from decimal import Decimal

bp = Blueprint('hulls', __name__)


# ---------------------------------------------------------------- create
@bp.post('/hulls')
def create_hull():
    uid, role = auth_context()
    require_roles(role, 'ProductionPlanner')
    data = json_body()
    order_id = as_str(need(data, 'order_id'), 'order_id')
    order = get_or_404(DB['orders'], order_id, 'ERR_ORDER_NOT_FOUND',
                       'DealerOrder')
    # family 7: exactly one hull per order (a second attempt draws
    # ERR_HULL_ALREADY_EXISTS per PRD §3.6); then the COMMITTED gate.
    if any(h['order_id'] == order_id for h in DB['hulls'].values()):
        raise ApiError(409, 'ERR_HULL_ALREADY_EXISTS',
                       'A hull already exists for this order')
    if order['status'] != 'COMMITTED':
        raise ApiError(409, 'ERR_INVALID_ORDER_STATE',
                       'Hull creation requires a COMMITTED order')
    model = DB['models'][order['model_id']]
    now = CLOCK.now()
    serial, hin = assign_hin(model, now)
    rec = new_rec({
        'hin': hin,
        'serial_no': serial,
        'order_id': order_id,
        'slot_id': order['slot_id'],
        'model_id': order['model_id'],
        'certification_status': 'UNCERTIFIED',
        'delivery_status': 'AT_PLANT',
        'completed_at': fmt_dt(now),
        'delivered_at': None,
        'created_by_user_id': uid,
        'carrying_cost_cents': 0,
    })
    rec['_completed_dt'] = now
    DB['hulls'][rec['id']] = rec
    # completion advances the order COMMITTED -> IN_PRODUCTION
    order['status'] = 'IN_PRODUCTION'
    touch(order)
    return respond(serialize(rec), 201)


@bp.get('/hulls')
def list_hulls():
    auth_context()
    items = list(DB['hulls'].values())
    for param in ('order_id', 'slot_id', 'model_id'):
        v = request.args.get(param)
        if v is not None:
            items = [h for h in items if h[param] == v]
    return list_response(items, serialize)


@bp.get('/hulls/<hid>')
def get_hull(hid):
    auth_context()
    rec = get_or_404(DB['hulls'], hid, 'ERR_HULL_NOT_FOUND', 'Hull')
    return respond(serialize(rec), 200)


# ---------------------------------------------------------------- certify
@bp.post('/hulls/<hid>/certify')
def certify_hull(hid):
    uid, role = auth_context()
    require_roles(role, 'ComplianceOfficer')
    hull = get_or_404(DB['hulls'], hid, 'ERR_HULL_NOT_FOUND', 'Hull')
    # family 7 (state) before family 8 (safety)
    if hull['certification_status'] != 'UNCERTIFIED':
        raise ApiError(409, 'ERR_INVALID_HULL_STATE',
                       'Certify requires an UNCERTIFIED hull')
    if uid == hull['created_by_user_id']:
        raise ApiError(403, 'ERR_SEGREGATION_OF_DUTY',
                       'Certifier must differ from the creating planner')
    hull['certification_status'] = 'CERTIFIED'
    touch(hull)
    return respond(serialize(hull), 200)


# ---------------------------------------------------------------- deliver
@bp.post('/hulls/<hid>/deliver')
def deliver_hull(hid):
    uid, role = auth_context()
    require_roles(role, 'ProductionPlanner')
    hull = get_or_404(DB['hulls'], hid, 'ERR_HULL_NOT_FOUND', 'Hull')
    if hull['delivery_status'] != 'AT_PLANT':
        raise ApiError(409, 'ERR_INVALID_HULL_STATE',
                       'Deliver requires delivery_status AT_PLANT')
    if hull['certification_status'] == 'RECALL_HOLD':
        raise ApiError(409, 'ERR_HULL_RECALL_HOLD',
                       'Hull is under recall hold')
    if hull['certification_status'] != 'CERTIFIED':
        raise ApiError(409, 'ERR_HULL_NOT_CERTIFIED',
                       'Hull is not CERTIFIED')
    order = DB['orders'][hull['order_id']]
    dealer = DB['dealers'][order['dealer_id']]
    # family 11: floor-plan headroom (landing exactly at the limit allowed)
    if (dealer['floor_plan_utilized_cents'] + order['invoice_total_cents']
            > dealer['floor_plan_limit_cents']):
        raise ApiError(402, 'ERR_FLOOR_PLAN_LIMIT_EXCEEDED',
                       'Delivery would exceed the floor-plan limit')

    now = CLOCK.now()
    # Hop 1: advance opens; tier locked from utilization INCLUDING it.
    principal = order['invoice_total_cents']
    ratio = (Decimal(dealer['floor_plan_utilized_cents'] + principal)
             / Decimal(dealer['floor_plan_limit_cents']))
    locked_tier = tier_for_ratio(ratio)
    advance = new_rec({
        'dealer_id': dealer['id'],
        'hull_id': hull['id'],
        'principal_cents': principal,
        'outstanding_principal_cents': principal,
        'accrued_interest_cents': 0,
        'rate_tier': locked_tier,
        'annual_rate': float(TIER_RATES[locked_tier]),
        'opened_at': fmt_dt(now),
        'last_accrual_date': now.date().isoformat(),
        'status': 'OPEN',
    })
    advance['_opened_dt'] = now
    advance['_last_accrual'] = now.date()
    DB['advances'][advance['id']] = advance
    # Hop 2: dealer utilization rises (recomputed from source rows).
    dealer['floor_plan_utilized_cents'] = recompute_utilized(dealer['id'])
    # Hop 3: dealer tier re-derived from the new ratio.
    dealer['current_rate_tier'] = tier_for(dealer['floor_plan_utilized_cents'],
                                           dealer['floor_plan_limit_cents'])
    touch(dealer)
    # Hop 4: order IN_PRODUCTION -> DELIVERED.
    order['status'] = 'DELIVERED'
    touch(order)
    # Hop 5: hull delivered.
    hull['delivery_status'] = 'DELIVERED'
    hull['delivered_at'] = fmt_dt(now)
    touch(hull)
    return respond(serialize(hull), 200)


# ---------------------------------------------------------------- advances
@bp.get('/floor-plan-advances')
def list_advances():
    auth_context()
    items = list(DB['advances'].values())
    for param in ('dealer_id', 'hull_id', 'status'):
        v = request.args.get(param)
        if v is not None:
            items = [a for a in items if a[param] == v]
    return list_response(items, serialize)


@bp.get('/floor-plan-advances/<aid>')
def get_advance(aid):
    auth_context()
    rec = get_or_404(DB['advances'], aid, 'ERR_ADVANCE_NOT_FOUND',
                     'FloorPlanAdvance')
    return respond(serialize(rec), 200)
