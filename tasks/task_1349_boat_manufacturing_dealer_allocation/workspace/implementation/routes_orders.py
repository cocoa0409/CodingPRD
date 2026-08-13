"""Dealer orders: booking (explicit/auto slot), amendment, confirm, cancel
with tiered restocking fee and waitlist promotion cascade; option lines."""
from flask import Blueprint, request

from store import (DB, CLOCK, new_rec, serialize, touch,
                   recount_allocation, recompute_reserved)
from services import (make_lines, order_lines, delete_lines, compute_pricing,
                      compute_required_deposit, compute_production_hours,
                      check_option_compatibility, promote_waitlist,
                      restocking_fee, preview_pricing, required_deposit_value)
from util import (ApiError, respond, list_response, auth_context, require_roles,
                  json_body, present, need, as_str, as_int, as_enum, invalid,
                  get_or_404)

bp = Blueprint('orders', __name__)

SOURCES = {'RETAIL', 'FLEET', 'BOAT_SHOW'}


def _validate_option_ids(data, required):
    """Schema: list of unique option ids (family 3)."""
    if not present(data, 'option_package_ids'):
        if required:
            invalid('Missing required field: option_package_ids')
        return None
    ids = data['option_package_ids']
    if not isinstance(ids, list):
        invalid('option_package_ids must be a list')
    if not required and len(ids) == 0:
        # amendment: non-empty when provided
        invalid('option_package_ids must be non-empty when provided')
    for oid in ids:
        if not isinstance(oid, str) or not oid:
            invalid('option_package_ids elements must be strings')
    if len(set(ids)) != len(ids):
        invalid('duplicate option identifiers within one order')
    return ids


# ---------------------------------------------------------------- create
@bp.post('/dealer-orders')
def create_order():
    uid, role = auth_context()
    require_roles(role, 'DealerPrincipal')
    data = json_body()
    # family 2: DealerPrincipal ownership on booking (dealer_id == X-User-ID)
    if present(data, 'dealer_id') and data['dealer_id'] != uid:
        raise ApiError(403, 'ERR_INSUFFICIENT_PERMISSIONS',
                       'dealer_id must equal X-User-ID')
    # family 3: schema/domain
    dealer_id = as_str(need(data, 'dealer_id'), 'dealer_id')
    model_id = as_str(need(data, 'model_id'), 'model_id')
    source = as_enum(need(data, 'source'), 'source', SOURCES)
    deposit = as_int(need(data, 'deposit_paid_cents'), 'deposit_paid_cents')
    if deposit < 0:
        invalid('deposit_paid_cents must be >= 0')
    option_ids = _validate_option_ids(data, required=True)
    slot_id = None
    if present(data, 'slot_id'):
        slot_id = as_str(data['slot_id'], 'slot_id')
    show_event_id = None
    if present(data, 'show_event_id'):
        show_event_id = as_str(data['show_event_id'], 'show_event_id')
    if source == 'BOAT_SHOW' and show_event_id is None:
        invalid('show_event_id is required when source is BOAT_SHOW')
    if source != 'BOAT_SHOW' and show_event_id is not None:
        invalid('show_event_id is forbidden unless source is BOAT_SHOW')
    # family 5: body FK existence
    model = get_or_404(DB['models'], model_id, 'ERR_MODEL_NOT_FOUND',
                       'BoatModel')
    dealer = get_or_404(DB['dealers'], dealer_id, 'ERR_DEALER_NOT_FOUND',
                        'Dealer')
    slot = None
    if slot_id is not None:
        slot = get_or_404(DB['slots'], slot_id, 'ERR_SLOT_NOT_FOUND',
                          'BuildSlot')
    event = None
    if show_event_id is not None:
        event = get_or_404(DB['shows'], show_event_id,
                           'ERR_SHOW_EVENT_NOT_FOUND', 'BoatShowEvent')
    for oid in option_ids:
        get_or_404(DB['options'], oid, 'ERR_OPTION_NOT_FOUND',
                   'OptionPackage')
    # family 7: state preconditions
    if model['status'] != 'ORDERABLE':
        raise ApiError(409, 'ERR_MODEL_NOT_ORDERABLE',
                       'BoatModel is not ORDERABLE')
    if slot is not None:
        run = DB['runs'][slot['run_id']]
        if run['status'] != 'OPEN' or slot['status'] != 'OPEN':
            raise ApiError(409, 'ERR_RUN_NOT_OPEN',
                           "Chosen slot's run and slot must be OPEN")
    # family 9: show window (closed interval on the clock date)
    if source == 'BOAT_SHOW':
        clock_date = CLOCK.now().date()
        if not (event['_start'] <= clock_date <= event['_end']):
            raise ApiError(422, 'ERR_SHOW_EVENT_NOT_ACTIVE',
                           'BOAT_SHOW order created outside its event window')
    # family 10: option compatibility and model match
    check_option_compatibility(model_id, option_ids)

    # Pricing (pinned rounding order: per line, sum, then surcharge).
    order = {
        'dealer_id': dealer_id,
        'model_id': model_id,
        'slot_id': None,
        'show_event_id': show_event_id,
        'source': source,
        'status': 'WAITLISTED',
        'base_price_cents': model['base_price_cents'],  # price lock
        'deposit_paid_cents': deposit,
        'cancel_fee_cents': None,
        'refund_cents': None,
    }
    rec = new_rec(order)
    lines = make_lines(rec['id'], option_ids, dealer)
    compute_pricing(rec, lines)
    compute_required_deposit(rec, dealer)
    compute_production_hours(rec, lines)

    # family 11: fiscal guards + slot securing
    chosen = None
    if slot is not None:
        # explicit slot: quota headroom, then capacity, then deposit
        if recount_allocation(dealer_id) >= dealer['annual_allocation_quota']:
            raise ApiError(422, 'ERR_QUOTA_EXCEEDED',
                           'Dealer allocation quota reached')
        if (slot['reserved_hours'] + rec['production_hours']
                > slot['capacity_hours']):
            raise ApiError(422, 'ERR_SLOT_CAPACITY_EXCEEDED',
                           'Order production hours exceed slot capacity')
        if deposit < rec['required_deposit_cents']:
            raise ApiError(422, 'ERR_DEPOSIT_INSUFFICIENT',
                           'deposit_paid_cents below required_deposit_cents')
        chosen = slot
    else:
        # auto-select: OPEN runs' OPEN slots with capacity, ranked by
        # build_week_start ASC then slot_code ASC.
        candidates = []
        for s in DB['slots'].values():
            r = DB['runs'][s['run_id']]
            if r['status'] != 'OPEN' or s['status'] != 'OPEN':
                continue
            if (s['capacity_hours'] - s['reserved_hours']
                    >= rec['production_hours']):
                candidates.append((r['_start'], s['slot_code'], s['_seq'], s))
        candidates.sort(key=lambda t: (t[0], t[1], t[2]))
        if candidates:
            if (recount_allocation(dealer_id)
                    >= dealer['annual_allocation_quota']):
                raise ApiError(422, 'ERR_QUOTA_EXCEEDED',
                               'Dealer allocation quota reached')
            if deposit < rec['required_deposit_cents']:
                raise ApiError(422, 'ERR_DEPOSIT_INSUFFICIENT',
                               'deposit_paid_cents below required_deposit_cents')
            chosen = candidates[0][3]
        else:
            # no slot fits -> WAITLISTED; quota gate does not apply, deposit
            # still verified at booking (PRD §3.4).
            if deposit < rec['required_deposit_cents']:
                raise ApiError(422, 'ERR_DEPOSIT_INSUFFICIENT',
                               'deposit_paid_cents below required_deposit_cents')

    if chosen is not None:
        rec['status'] = 'ALLOCATED'
        rec['slot_id'] = chosen['id']
        DB['orders'][rec['id']] = rec
        chosen['reserved_hours'] = recompute_reserved(chosen['id'])
        touch(chosen)
        dealer['allocation_used'] = recount_allocation(dealer_id)
        touch(dealer)
    else:
        DB['orders'][rec['id']] = rec
    return respond(serialize(rec), 201)


# ---------------------------------------------------------------- read
@bp.get('/dealer-orders')
def list_orders():
    auth_context()
    items = list(DB['orders'].values())
    for param in ('dealer_id', 'model_id', 'slot_id', 'show_event_id',
                  'status'):
        v = request.args.get(param)
        if v is not None:
            items = [o for o in items if o[param] == v]
    return list_response(items, serialize)


@bp.get('/dealer-orders/<oid>')
def get_order(oid):
    auth_context()
    rec = get_or_404(DB['orders'], oid, 'ERR_ORDER_NOT_FOUND', 'DealerOrder')
    return respond(serialize(rec), 200)


# ---------------------------------------------------------------- amend
@bp.patch('/dealer-orders/<oid>')
def amend_order(oid):
    uid, role = auth_context()
    require_roles(role, 'DealerPrincipal')
    data = json_body()
    # family 3: schema/domain
    expected = as_int(need(data, 'expected_order_version'),
                      'expected_order_version')
    option_ids = _validate_option_ids(data, required=False)
    new_deposit = None
    if present(data, 'deposit_paid_cents'):
        new_deposit = as_int(data['deposit_paid_cents'], 'deposit_paid_cents')
        if new_deposit < 0:
            invalid('deposit_paid_cents must be >= 0')
    # family 4: path existence
    order = get_or_404(DB['orders'], oid, 'ERR_ORDER_NOT_FOUND',
                       'DealerOrder')
    # family 2: ownership (order's dealer must equal X-User-ID)
    if order['dealer_id'] != uid:
        raise ApiError(403, 'ERR_INSUFFICIENT_PERMISSIONS',
                       'DealerPrincipal may only amend own orders')
    # family 5: body FK existence (option ids)
    if option_ids is not None:
        for opt_id in option_ids:
            get_or_404(DB['options'], opt_id, 'ERR_OPTION_NOT_FOUND',
                       'OptionPackage')
    # family 6: OCC
    if expected != order['version']:
        raise ApiError(412, 'ERR_STALE_ORDER_VERSION',
                       'expected_order_version does not match current version')
    # family 7: amend only from WAITLISTED / ALLOCATED
    if order['status'] not in ('WAITLISTED', 'ALLOCATED'):
        raise ApiError(409, 'ERR_INVALID_ORDER_STATE',
                       'Order state forbids amendment')
    # family 9: cutoff applies to ALLOCATED orders (strictly before;
    # exactly at the cutoff rejects)
    if order['status'] == 'ALLOCATED':
        run = DB['runs'][DB['slots'][order['slot_id']]['run_id']]
        if not (CLOCK.now() < run['_cutoff']):
            raise ApiError(422, 'ERR_OPTION_CUTOFF_PASSED',
                           'Option change cutoff has passed')
    # family 10: replacement set compatibility / model match
    if option_ids is not None:
        check_option_compatibility(order['model_id'], option_ids)

    dealer = DB['dealers'][order['dealer_id']]
    old_hours = order['production_hours']
    # Precompute the amendment WITHOUT mutating the store (atomicity: all
    # preconditions are checked before any change is committed).
    if option_ids is not None:
        _, new_hours, _, required = preview_pricing(order, option_ids, dealer)
    else:
        new_hours = old_hours
        # required_deposit recomputed at every amendment (current standing)
        required = required_deposit_value(order['invoice_total_cents'],
                                          order['source'], dealer['standing'],
                                          order['show_event_id'])
    effective_deposit = new_deposit if new_deposit is not None \
        else order['deposit_paid_cents']

    # family 11: same-slot capacity for ALLOCATED, then deposit coverage
    if order['status'] == 'ALLOCATED':
        slot = DB['slots'][order['slot_id']]
        if (slot['reserved_hours'] - old_hours + new_hours
                > slot['capacity_hours']):
            raise ApiError(422, 'ERR_SLOT_CAPACITY_EXCEEDED',
                           'Amended build does not fit the same slot')
    if effective_deposit < required:
        raise ApiError(422, 'ERR_DEPOSIT_INSUFFICIENT',
                       'deposit_paid_cents below required_deposit_cents')

    # commit: atomic line replacement with fresh snapshots, then reprice
    if option_ids is not None:
        delete_lines(oid)
        lines = make_lines(oid, option_ids, dealer)
    else:
        lines = order_lines(oid)
    compute_pricing(order, lines)
    compute_required_deposit(order, dealer)
    compute_production_hours(order, lines)
    order['deposit_paid_cents'] = effective_deposit
    if order['status'] == 'ALLOCATED':
        slot['reserved_hours'] = recompute_reserved(slot['id'])
        touch(slot)
    touch(order)
    return respond(serialize(order), 200)


# ---------------------------------------------------------------- confirm
@bp.post('/dealer-orders/<oid>/confirm')
def confirm_order(oid):
    uid, role = auth_context()
    require_roles(role, 'DealerPrincipal')
    order = get_or_404(DB['orders'], oid, 'ERR_ORDER_NOT_FOUND',
                       'DealerOrder')
    if order['dealer_id'] != uid:
        raise ApiError(403, 'ERR_INSUFFICIENT_PERMISSIONS',
                       'DealerPrincipal may only confirm own orders')
    if order['status'] != 'ALLOCATED':
        raise ApiError(409, 'ERR_INVALID_ORDER_STATE',
                       'Confirm requires an ALLOCATED order')
    if order['deposit_paid_cents'] < order['required_deposit_cents']:
        raise ApiError(422, 'ERR_DEPOSIT_INSUFFICIENT',
                       'deposit_paid_cents below required_deposit_cents')
    order['status'] = 'COMMITTED'
    touch(order)
    return respond(serialize(order), 200)


# ---------------------------------------------------------------- cancel
@bp.post('/dealer-orders/<oid>/cancel')
def cancel_order(oid):
    uid, role = auth_context()
    require_roles(role, 'DealerPrincipal')
    order = get_or_404(DB['orders'], oid, 'ERR_ORDER_NOT_FOUND',
                       'DealerOrder')
    if order['dealer_id'] != uid:
        raise ApiError(403, 'ERR_INSUFFICIENT_PERMISSIONS',
                       'DealerPrincipal may only cancel own orders')
    if order['status'] not in ('WAITLISTED', 'ALLOCATED', 'COMMITTED'):
        raise ApiError(409, 'ERR_INVALID_ORDER_STATE',
                       'Order state forbids cancellation')
    had_slot = order['status'] in ('ALLOCATED', 'COMMITTED')
    fee = restocking_fee(order)
    order['cancel_fee_cents'] = fee
    order['refund_cents'] = max(0, order['deposit_paid_cents'] - fee)
    slot = DB['slots'][order['slot_id']] if had_slot else None
    order['status'] = 'CANCELLED'
    touch(order)
    if had_slot:
        # slot release, dealer recount, then the waitlist promotion cascade
        slot['reserved_hours'] = recompute_reserved(slot['id'])
        touch(slot)
        dealer = DB['dealers'][order['dealer_id']]
        dealer['allocation_used'] = recount_allocation(dealer['id'])
        touch(dealer)
        promote_waitlist(slot)
    return respond(serialize(order), 200)


# ---------------------------------------------------------------- lines
@bp.get('/order-option-lines')
def list_lines():
    auth_context()
    items = list(DB['lines'].values())
    order_id = request.args.get('order_id')
    if order_id is not None:
        items = [l for l in items if l['order_id'] == order_id]
    option_id = request.args.get('option_package_id')
    if option_id is not None:
        items = [l for l in items if l['option_package_id'] == option_id]
    return list_response(items, serialize)


@bp.get('/order-option-lines/<lid>')
def get_line(lid):
    auth_context()
    rec = get_or_404(DB['lines'], lid, 'ERR_OPTION_NOT_FOUND',
                     'OrderOptionLine')
    return respond(serialize(rec), 200)
