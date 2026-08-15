#!/usr/bin/env python3
"""Industrial MRO Distribution API - Flask implementation."""

import os
import uuid
import random
import string
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ============================================================================
# Logical Clock (default 2026-08-01T00:00:00Z, never wall-clock)
# ============================================================================

_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def clock_now():
    return _clock


def clock_set(dt):
    global _clock
    _clock = dt


def clock_iso():
    dt = _clock
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}Z'


def clock_today():
    return _clock.date()


def clock_minute_of_day():
    return _clock.hour * 60 + _clock.minute


# ============================================================================
# In-memory Data Store (starts empty every boot)
# ============================================================================

_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


customers = {}
items_db = {}
price_rules = {}
rebate_agreements = {}
locations = {}
stock_balances = {}  # (location_id, item_id) -> balance dict
carts = {}
orders = {}
order_lines_db = {}
returns_db = {}

# ============================================================================
# Errors
# ============================================================================


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# ============================================================================
# Response Envelope
# ============================================================================


def gen_request_id():
    return 'req_' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=20))


def success_obj(data, status=200):
    return jsonify({
        'meta': {
            'api_request_id': gen_request_id(),
            'api_request_timestamp': clock_iso(),
        },
        'response_type': 'object',
        'data': data,
    }), status


def success_list(items_list, total_count, limit, offset):
    has_more = (offset + len(items_list)) < total_count
    return jsonify({
        'meta': {
            'api_request_id': gen_request_id(),
            'api_request_timestamp': clock_iso(),
            'limit': limit,
            'offset': offset,
            'total_count': total_count,
            'has_more': has_more,
        },
        'response_type': 'array',
        'data': items_list,
    }), 200


@app.errorhandler(ApiError)
def handle_api_error(e):
    return jsonify({
        'meta': {
            'api_request_id': gen_request_id(),
            'api_request_timestamp': clock_iso(),
        },
        'response_type': 'error',
        'data': {
            'error_id': e.error_id,
            'message': e.message,
        },
    }), e.http_status


# ============================================================================
# Auth
# ============================================================================

ROLES = {'DistributionAdmin', 'CustomerBuyer', 'CustomerApprover', 'BranchManager', 'VendorRep'}
ENTITY_BACKED = {'CustomerBuyer', 'CustomerApprover'}


def get_auth():
    uid = request.headers.get('X-User-ID')
    urole = request.headers.get('X-User-Role')
    if not uid or not urole or urole not in ROLES:
        raise ApiError('ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER',
                       'X-User-ID and X-User-Role headers are required with a declared role', 400)
    return uid, urole


def require_roles(uid, urole, allowed):
    if urole not in allowed:
        raise ApiError('ERR_FORBIDDEN_ROLE',
                       f'Role {urole} is not permitted on this endpoint', 403)


def check_scope(customer_id, uid, urole):
    if urole in ENTITY_BACKED and uid != customer_id:
        raise ApiError('ERR_CUSTOMER_SCOPE_MISMATCH',
                       'Resource is owned by a different customer account', 403)


# ============================================================================
# Pagination
# ============================================================================


def parse_pagination():
    raw_limit = request.args.get('limit')
    raw_offset = request.args.get('offset')
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise ApiError('ERR_VALIDATION', 'limit must be an integer', 400)
        if limit < 1 or limit > 100:
            raise ApiError('ERR_VALIDATION', 'limit must be between 1 and 100', 400)
    else:
        limit = 10
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise ApiError('ERR_VALIDATION', 'offset must be an integer', 400)
        if offset < 0:
            raise ApiError('ERR_VALIDATION', 'offset must be >= 0', 400)
    else:
        offset = 0
    return limit, offset


def paginate(items_list):
    items_list.sort(key=lambda x: x['_seq'])
    total = len(items_list)
    limit, offset = parse_pagination()
    page = items_list[offset:offset + limit]
    return success_list([serialize(e) for e in page], total, limit, offset)


# ============================================================================
# Entity Helpers
# ============================================================================


def make_entity(fields):
    now = clock_iso()
    e = {
        'id': str(uuid.uuid4()),
        'created_at': now,
        'updated_at': now,
        'version': 1,
        '_seq': next_seq(),
    }
    e.update(fields)
    return e


def touch(entity):
    entity['version'] += 1
    entity['updated_at'] = clock_iso()


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith('_')}


def get_body(required=True):
    body = request.get_json(force=True, silent=True)
    if body is None:
        if required:
            raise ApiError('ERR_VALIDATION', 'Request body must be valid JSON', 400)
        return {}
    if not isinstance(body, dict):
        raise ApiError('ERR_VALIDATION', 'Request body must be a JSON object', 400)
    return body


# ============================================================================
# Validation Helpers
# ============================================================================

VALID_PRICE_TIERS = {'STANDARD', 'SILVER', 'GOLD', 'PLATINUM'}
VALID_ITEM_CLASSES = {'STOCKED', 'SPECIAL_ORDER', 'NON_RETURNABLE'}
VALID_HAZMAT = {'NONE', 'GROUND_ONLY', 'WILL_CALL_ONLY'}
VALID_RULE_TYPES = {'FIXED_PRICE', 'DISCOUNT_PCT'}
VALID_LOCATION_TYPES = {'BRANCH', 'CENTRAL'}
VALID_FULFILLMENT_METHODS = {'WILL_CALL', 'SAME_DAY', 'STANDARD'}
VALID_CONDITIONS = {'RESALEABLE', 'DAMAGED'}
VALID_CUSTOMER_STATUSES = {'ACTIVE', 'CREDIT_HOLD'}


def require_field(body, field):
    if field not in body or body[field] is None:
        raise ApiError('ERR_VALIDATION', f'Missing required field: {field}', 400)
    return body[field]


def validate_enum(value, valid_set, field_name):
    if not isinstance(value, str) or value not in valid_set:
        raise ApiError('ERR_VALIDATION', f'Invalid value for {field_name}', 400)
    return value


def validate_int(value, field_name, min_val=None, max_val=None):
    if not isinstance(value, int) or isinstance(value, bool):
        raise ApiError('ERR_VALIDATION', f'{field_name} must be an integer', 400)
    if min_val is not None and value < min_val:
        raise ApiError('ERR_VALIDATION', f'{field_name} must be >= {min_val}', 400)
    if max_val is not None and value > max_val:
        raise ApiError('ERR_VALIDATION', f'{field_name} must be <= {max_val}', 400)
    return value


def validate_date_str(value, field_name):
    if not isinstance(value, str):
        raise ApiError('ERR_VALIDATION', f'{field_name} must be a date string (YYYY-MM-DD)', 400)
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ApiError('ERR_VALIDATION', f'{field_name} must be a valid date (YYYY-MM-DD)', 400)
    return value


def parse_date(s):
    return date.fromisoformat(s)


# ============================================================================
# Calculation Helpers
# ============================================================================


def round_half_up(value):
    return int(Decimal(str(value)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def resolve_unit_price(customer, item, qty):
    """Resolve unit price per the contract price matrix + quantity tier."""
    today = clock_today()
    tier = customer['price_tier']

    item_rule = None
    class_rule = None
    for rule in price_rules.values():
        if rule['status'] != 'ACTIVE':
            continue
        if rule['customer_tier'] != tier:
            continue
        eff_from = parse_date(rule['effective_from'])
        eff_to = parse_date(rule['effective_to'])
        if not (eff_from <= today < eff_to):
            continue
        if rule.get('item_id') is not None and rule['item_id'] == item['id']:
            item_rule = rule
        elif rule.get('item_class') is not None and rule['item_class'] == item['item_class']:
            class_rule = rule

    rule = item_rule if item_rule is not None else class_rule

    if rule is None:
        base = item['list_price_cents']
    elif rule['rule_type'] == 'FIXED_PRICE':
        base = rule['contract_unit_price_cents']
    else:
        pct = Decimal(str(rule['discount_pct']))
        base = round_half_up(Decimal(item['list_price_cents']) * (Decimal(1) - pct / Decimal(100)))

    if qty >= 50:
        base = round_half_up(Decimal(base) * Decimal('0.95'))
    elif qty >= 10:
        base = round_half_up(Decimal(base) * Decimal('0.97'))

    return min(base, item['list_price_cents'])


def compute_freight(subtotal, fulfillment_method, lines_items):
    """lines_items: list of item dicts for the order's lines."""
    if fulfillment_method == 'WILL_CALL':
        base_freight = 0
    elif subtotal >= 25000:
        base_freight = 0
    elif fulfillment_method == 'SAME_DAY':
        base_freight = 1500
    else:
        base_freight = 795

    hazmat = 0
    if fulfillment_method != 'WILL_CALL':
        for item in lines_items:
            if item['hazmat_restriction'] != 'NONE':
                hazmat = 2500
                break

    return base_freight + hazmat


# ============================================================================
# Stock Balance Helpers
# ============================================================================


def read_balance(location_id, item_id):
    """Read balance; non-existent reads as zero."""
    key = (location_id, item_id)
    if key in stock_balances:
        return stock_balances[key]
    return {'on_hand_qty': 0, 'reserved_qty': 0, 'available_qty': 0}


def get_balance(location_id, item_id):
    return stock_balances.get((location_id, item_id))


def get_or_create_balance(location_id, item_id):
    key = (location_id, item_id)
    if key not in stock_balances:
        stock_balances[key] = make_entity({
            'location_id': location_id,
            'item_id': item_id,
            'on_hand_qty': 0,
            'reserved_qty': 0,
            'available_qty': 0,
        })
    return stock_balances[key]


def update_available(balance):
    balance['available_qty'] = balance['on_hand_qty'] - balance['reserved_qty']


def get_order_lines(order_id):
    """Return order lines in creation order."""
    result = [l for l in order_lines_db.values() if l['order_id'] == order_id]
    result.sort(key=lambda l: l['_seq'])
    return result


# ============================================================================
# Allocation Waterfall + Backorder Auto-fill
# ============================================================================


def derive_fulfillment_source(line):
    qty = line['qty']
    if qty == line['qty_branch']:
        return 'BRANCH_ONLY'
    if qty == line['qty_drop_ship']:
        return 'DROP_SHIP_ONLY'
    if qty == line['qty_backordered']:
        return 'BACKORDER_ONLY'
    if qty == line['qty_branch'] + line['qty_central']:
        return 'SPLIT_STOCK'
    return 'MIXED'


def select_central(item_id):
    """Select ONE central location: available DESC, created_at ASC (via _seq)."""
    best = None
    best_key = None
    for loc in locations.values():
        if loc['location_type'] != 'CENTRAL':
            continue
        bal = read_balance(loc['id'], item_id)
        if bal['available_qty'] <= 0:
            continue
        key = (-bal['available_qty'], loc['_seq'])
        if best is None or key < best_key:
            best = loc
            best_key = key
    return best


def run_allocation_for_line(line, order):
    """Run the allocation waterfall for a single line at confirm time."""
    item = items_db[line['item_id']]
    remaining = line['qty']

    # 1. Branch bucket
    branch_bal = read_balance(order['fulfillment_branch_id'], line['item_id'])
    take = min(branch_bal['available_qty'], remaining)
    line['qty_branch'] = take
    if take > 0:
        real_bal = get_or_create_balance(order['fulfillment_branch_id'], line['item_id'])
        real_bal['reserved_qty'] += take
        update_available(real_bal)
        touch(real_bal)
    remaining -= take

    # 2. Central bucket (single location)
    line['qty_central'] = 0
    line['_central_location_id'] = None
    if remaining > 0:
        central = select_central(line['item_id'])
        if central is not None:
            central_bal = read_balance(central['id'], line['item_id'])
            take = min(central_bal['available_qty'], remaining)
            if take > 0:
                line['qty_central'] = take
                line['_central_location_id'] = central['id']
                real_bal = get_or_create_balance(central['id'], line['item_id'])
                real_bal['reserved_qty'] += take
                update_available(real_bal)
                touch(real_bal)
                remaining -= take

    # 3. Drop-ship bucket
    line['qty_drop_ship'] = 0
    if remaining > 0 and item['drop_ship_eligible']:
        line['qty_drop_ship'] = remaining
        remaining = 0

    # 4. Backorder bucket
    line['qty_backordered'] = remaining

    line['fulfillment_source'] = derive_fulfillment_source(line)

    # Provisional drop-ship margin
    if line['qty_drop_ship'] > 0:
        line['provisional_margin_cents'] = (
            line['qty_drop_ship'] * line['unit_price_cents']
            - (line['qty_drop_ship'] * item['vendor_cost_estimate_cents']
               + item['vendor_freight_estimate_cents'])
        )
        line['margin_status'] = 'PROVISIONAL'
    else:
        line['provisional_margin_cents'] = None
        line['margin_status'] = 'NOT_APPLICABLE'

    touch(line)


def run_backorder_autofill(location_id, item_id):
    """Fill eligible backordered lines at a freed location for an item."""
    balance = get_balance(location_id, item_id)
    if balance is None:
        return
    loc = locations.get(location_id)
    if loc is None:
        return

    eligible = []
    for line in order_lines_db.values():
        if line['item_id'] != item_id or line['qty_backordered'] <= 0:
            continue
        order = orders.get(line['order_id'])
        if order is None or order['status'] != 'CONFIRMED':
            continue
        if loc['location_type'] == 'BRANCH':
            if order['fulfillment_branch_id'] != location_id:
                continue
        elif loc['location_type'] == 'CENTRAL':
            if line.get('_central_location_id') != location_id:
                continue
        else:
            continue
        eligible.append((order['_seq'], line['_seq'], line, order))

    eligible.sort(key=lambda x: (x[0], x[1]))

    for _, _, line, order in eligible:
        avail = balance['available_qty']
        if avail <= 0:
            break
        fill = min(avail, line['qty_backordered'])
        line['qty_backordered'] -= fill
        if loc['location_type'] == 'BRANCH':
            line['qty_branch'] += fill
        else:
            line['qty_central'] += fill
        balance['reserved_qty'] += fill
        update_available(balance)
        touch(balance)
        line['fulfillment_source'] = derive_fulfillment_source(line)
        touch(line)

        if line['qty_backordered'] == 0:
            o_lines = get_order_lines(order['id'])
            if all(l['qty_backordered'] == 0 for l in o_lines):
                if order['fulfillment_status'] == 'PARTIALLY_ALLOCATED':
                    order['fulfillment_status'] = 'ALLOCATED'
                    touch(order)


# ============================================================================
# Rebate Helpers
# ============================================================================


def recompute_tier_and_provisional(agreement):
    tiers = agreement['tiers']
    accrued = agreement['accrued_spend_cents']
    idx = 0
    for i, t in enumerate(tiers):
        if t['threshold_cents'] <= accrued:
            idx = i
        else:
            break
    agreement['current_tier_index'] = idx
    agreement['provisional_rebate_cents'] = round_half_up(
        Decimal(accrued) * Decimal(tiers[idx]['rebate_bps']) / Decimal(10000)
    )


def compute_final_rebate(agreement):
    """Marginal-band rebate at close."""
    tiers = agreement['tiers']
    accrued = agreement['accrued_spend_cents']
    total = Decimal(0)
    n = len(tiers)
    for i, t in enumerate(tiers):
        lo = t['threshold_cents']
        hi = tiers[i + 1]['threshold_cents'] if i + 1 < n else None
        if hi is None:
            band = max(0, accrued - lo)
        else:
            band = max(0, min(accrued, hi) - lo)
        total += Decimal(band) * Decimal(t['rebate_bps']) / Decimal(10000)
    return round_half_up(total)


def accrue_rebates(customer_id, amount_cents, event_date):
    """Add spend to every ACTIVE agreement of the customer whose period contains the date."""
    for ag in rebate_agreements.values():
        if ag['customer_id'] != customer_id or ag['status'] != 'ACTIVE':
            continue
        if parse_date(ag['period_start']) <= event_date <= parse_date(ag['period_end']):
            ag['accrued_spend_cents'] += amount_cents
            recompute_tier_and_provisional(ag)
            touch(ag)


def decrement_rebates(customer_id, credit_cents, event_date):
    """Subtract credit from every ACTIVE agreement whose period contains the date."""
    for ag in rebate_agreements.values():
        if ag['customer_id'] != customer_id or ag['status'] != 'ACTIVE':
            continue
        if parse_date(ag['period_start']) <= event_date <= parse_date(ag['period_end']):
            ag['accrued_spend_cents'] -= credit_cents
            recompute_tier_and_provisional(ag)
            touch(ag)


# ============================================================================
# Routes: Clock
# ============================================================================


@app.route('/_clock/set_current_utc', methods=['POST'])
def set_clock_endpoint():
    uid, urole = get_auth()
    require_roles(uid, urole, {'DistributionAdmin'})
    body = get_body()
    to_iso = require_field(body, 'to_iso8601')
    if not isinstance(to_iso, str):
        raise ApiError('ERR_VALIDATION', 'to_iso8601 must be an ISO8601 string', 400)
    try:
        s = to_iso.replace('Z', '+00:00')
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
    except ValueError:
        raise ApiError('ERR_VALIDATION', 'to_iso8601 must be a valid ISO8601 timestamp', 400)
    clock_set(dt)
    return success_obj({'current_utc': clock_iso()})


# ============================================================================
# Routes: Customers
# ============================================================================


@app.route('/mro/customers', methods=['POST'])
def create_customer():
    uid, urole = get_auth()
    require_roles(uid, urole, {'DistributionAdmin'})
    body = get_body()

    account_number = require_field(body, 'account_number')
    display_name = require_field(body, 'display_name')
    credit_limit_cents = require_field(body, 'credit_limit_cents')
    primary_ship_to_state = require_field(body, 'primary_ship_to_state')

    price_tier = body.get('price_tier', 'STANDARD')
    is_national_account = body.get('is_national_account', False)
    approval_threshold_cents = body.get('approval_threshold_cents', 0)

    # Shape validation
    if not isinstance(account_number, str) or not account_number:
        raise ApiError('ERR_VALIDATION', 'account_number must be a non-empty string', 400)
    if not isinstance(display_name, str) or not display_name:
        raise ApiError('ERR_VALIDATION', 'display_name must be a non-empty string', 400)
    validate_int(credit_limit_cents, 'credit_limit_cents', min_val=0)
    if not isinstance(primary_ship_to_state, str) or not primary_ship_to_state:
        raise ApiError('ERR_VALIDATION', 'primary_ship_to_state must be a non-empty string', 400)
    validate_enum(price_tier, VALID_PRICE_TIERS, 'price_tier')
    if not isinstance(is_national_account, bool):
        raise ApiError('ERR_VALIDATION', 'is_national_account must be a boolean', 400)
    validate_int(approval_threshold_cents, 'approval_threshold_cents', min_val=0)

    # Uniqueness
    for c in customers.values():
        if c['account_number'] == account_number:
            raise ApiError('ERR_ACCOUNT_NUMBER_EXISTS', 'account_number already exists', 409)

    customer = make_entity({
        'account_number': account_number,
        'display_name': display_name,
        'price_tier': price_tier,
        'is_national_account': is_national_account,
        'credit_limit_cents': credit_limit_cents,
        'approval_threshold_cents': approval_threshold_cents,
        'primary_ship_to_state': primary_ship_to_state,
        'status': 'ACTIVE',
        'net_spend_cents': 0,
        'open_credit_exposure_cents': 0,
    })
    customers[customer['id']] = customer
    return success_obj(serialize(customer), 201)


@app.route('/mro/customers/<customer_id>', methods=['GET'])
def get_customer(customer_id):
    uid, urole = get_auth()
    require_roles(uid, urole, ROLES)
    check_scope(customer_id, uid, urole)
    customer = customers.get(customer_id)
    if customer is None:
        raise ApiError('ERR_CUSTOMER_NOT_FOUND', 'Customer not found', 404)
    return success_obj(serialize(customer))


@app.route('/mro/customers/<customer_id>', methods=['PUT'])
def update_customer(customer_id):
    uid, urole = get_auth()
    require_roles(uid, urole, {'DistributionAdmin'})
    customer = customers.get(customer_id)
    if customer is None:
        raise ApiError('ERR_CUSTOMER_NOT_FOUND', 'Customer not found', 404)
    body = get_body()

    expected = require_field(body, 'expected_customer_version')
    validate_int(expected, 'expected_customer_version')

    # Shape validation for optional fields
    if 'price_tier' in body and body['price_tier'] is not None:
        validate_enum(body['price_tier'], VALID_PRICE_TIERS, 'price_tier')
    if 'is_national_account' in body and body['is_national_account'] is not None:
        if not isinstance(body['is_national_account'], bool):
            raise ApiError('ERR_VALIDATION', 'is_national_account must be a boolean', 400)
    if 'credit_limit_cents' in body and body['credit_limit_cents'] is not None:
        validate_int(body['credit_limit_cents'], 'credit_limit_cents', min_val=0)
    if 'approval_threshold_cents' in body and body['approval_threshold_cents'] is not None:
        validate_int(body['approval_threshold_cents'], 'approval_threshold_cents', min_val=0)
    if 'primary_ship_to_state' in body and body['primary_ship_to_state'] is not None:
        if not isinstance(body['primary_ship_to_state'], str) or not body['primary_ship_to_state']:
            raise ApiError('ERR_VALIDATION', 'primary_ship_to_state must be a non-empty string', 400)
    if 'status' in body and body['status'] is not None:
        validate_enum(body['status'], VALID_CUSTOMER_STATUSES, 'status')

    # OCC check
    if expected != customer['version']:
        raise ApiError('ERR_STALE_VERSION', 'expected_customer_version does not match current version', 412)

    # Apply updates
    if 'price_tier' in body and body['price_tier'] is not None:
        customer['price_tier'] = body['price_tier']
    if 'is_national_account' in body and body['is_national_account'] is not None:
        customer['is_national_account'] = body['is_national_account']
    if 'credit_limit_cents' in body and body['credit_limit_cents'] is not None:
        customer['credit_limit_cents'] = body['credit_limit_cents']
    if 'approval_threshold_cents' in body and body['approval_threshold_cents'] is not None:
        customer['approval_threshold_cents'] = body['approval_threshold_cents']
    if 'primary_ship_to_state' in body and body['primary_ship_to_state'] is not None:
        customer['primary_ship_to_state'] = body['primary_ship_to_state']
    if 'status' in body and body['status'] is not None:
        customer['status'] = body['status']

    touch(customer)
    return success_obj(serialize(customer))


@app.route('/mro/customers/<customer_id>/rebate-agreements', methods=['GET'])
def list_customer_rebate_agreements(customer_id):
    uid, urole = get_auth()
    require_roles(uid, urole, ROLES)
    check_scope(customer_id, uid, urole)
    customer = customers.get(customer_id)
    if customer is None:
        raise ApiError('ERR_CUSTOMER_NOT_FOUND', 'Customer not found', 404)
    result = [a for a in rebate_agreements.values() if a['customer_id'] == customer_id]
    return paginate(result)


@app.route('/mro/customers/<customer_id>/carts', methods=['GET'])
def list_customer_carts(customer_id):
    uid, urole = get_auth()
    require_roles(uid, urole, ROLES)
    check_scope(customer_id, uid, urole)
    customer = customers.get(customer_id)
    if customer is None:
        raise ApiError('ERR_CUSTOMER_NOT_FOUND', 'Customer not found', 404)
    result = [c for c in carts.values() if c['customer_id'] == customer_id]
    return paginate(result)


# ============================================================================
# Routes: Items
# ============================================================================


@app.route('/mro/items', methods=['POST'])
def create_item():
    uid, urole = get_auth()
    require_roles(uid, urole, {'DistributionAdmin'})
    body = get_body()

    sku = require_field(body, 'sku')
    description = require_field(body, 'description')
    item_class = require_field(body, 'item_class')
    list_price_cents = require_field(body, 'list_price_cents')

    hazmat_restriction = body.get('hazmat_restriction', 'NONE')
    restricted_states = body.get('restricted_states', [])
    drop_ship_eligible = body.get('drop_ship_eligible', False)
    vendor_cost_estimate_cents = body.get('vendor_cost_estimate_cents', 0)
    vendor_freight_estimate_cents = body.get('vendor_freight_estimate_cents', 0)

    if not isinstance(sku, str) or not sku:
        raise ApiError('ERR_VALIDATION', 'sku must be a non-empty string', 400)
    if not isinstance(description, str):
        raise ApiError('ERR_VALIDATION', 'description must be a string', 400)
    validate_enum(item_class, VALID_ITEM_CLASSES, 'item_class')
    validate_int(list_price_cents, 'list_price_cents', min_val=1)
    validate_enum(hazmat_restriction, VALID_HAZMAT, 'hazmat_restriction')
    if not isinstance(restricted_states, list):
        raise ApiError('ERR_VALIDATION', 'restricted_states must be an array', 400)
    if not isinstance(drop_ship_eligible, bool):
        raise ApiError('ERR_VALIDATION', 'drop_ship_eligible must be a boolean', 400)
    validate_int(vendor_cost_estimate_cents, 'vendor_cost_estimate_cents', min_val=0)
    validate_int(vendor_freight_estimate_cents, 'vendor_freight_estimate_cents', min_val=0)

    for it in items_db.values():
        if it['sku'] == sku:
            raise ApiError('ERR_SKU_ALREADY_EXISTS', 'sku already exists', 409)

    item = make_entity({
        'sku': sku,
        'description': description,
        'item_class': item_class,
        'hazmat_restriction': hazmat_restriction,
        'restricted_states': restricted_states,
        'list_price_cents': list_price_cents,
        'drop_ship_eligible': drop_ship_eligible,
        'vendor_cost_estimate_cents': vendor_cost_estimate_cents,
        'vendor_freight_estimate_cents': vendor_freight_estimate_cents,
    })
    items_db[item['id']] = item
    return success_obj(serialize(item), 201)


@app.route('/mro/items/<item_id>', methods=['GET'])
def get_item(item_id):
    uid, urole = get_auth()
    require_roles(uid, urole, ROLES)
    item = items_db.get(item_id)
    if item is None:
        raise ApiError('ERR_ITEM_NOT_FOUND', 'Item not found', 404)
    return success_obj(serialize(item))


@app.route('/mro/items/<item_id>/stock-balances', methods=['GET'])
def list_item_stock_balances(item_id):
    uid, urole = get_auth()
    require_roles(uid, urole, ROLES)
    item = items_db.get(item_id)
    if item is None:
        raise ApiError('ERR_ITEM_NOT_FOUND', 'Item not found', 404)
    result = [b for b in stock_balances.values() if b['item_id'] == item_id]
    return paginate(result)


@app.route('/mro/items/<item_id>/order-lines', methods=['GET'])
def list_item_order_lines(item_id):
    uid, urole = get_auth()
    require_roles(uid, urole, ROLES)
    item = items_db.get(item_id)
    if item is None:
        raise ApiError('ERR_ITEM_NOT_FOUND', 'Item not found', 404)
    result = [l for l in order_lines_db.values() if l['item_id'] == item_id]
    if urole in ENTITY_BACKED:
        result = [l for l in result
                  if orders.get(l['order_id']) is not None
                  and orders[l['order_id']]['customer_id'] == uid]
    return paginate(result)


# ============================================================================
# Routes: Price Matrix Rules
# ============================================================================


def validate_rule_value_fields(body, rule_type, require_all=True):
    """Validate rule_type-dependent fields. Returns (contract_price, discount_pct)."""
    contract_price = body.get('contract_unit_price_cents')
    discount_pct = body.get('discount_pct')
    if rule_type == 'FIXED_PRICE':
        if require_all and contract_price is None:
            raise ApiError('ERR_VALIDATION', 'contract_unit_price_cents is required for FIXED_PRICE', 400)
        if contract_price is not None:
            validate_int(contract_price, 'contract_unit_price_cents', min_val=0)
        if require_all and discount_pct is not None:
            raise ApiError('ERR_VALIDATION', 'discount_pct must be omitted for FIXED_PRICE', 400)
    elif rule_type == 'DISCOUNT_PCT':
        if require_all and discount_pct is None:
            raise ApiError('ERR_VALIDATION', 'discount_pct is required for DISCOUNT_PCT', 400)
        if discount_pct is not None:
            if not isinstance(discount_pct, (int, float)) or isinstance(discount_pct, bool):
                raise ApiError('ERR_VALIDATION', 'discount_pct must be a number', 400)
            if not (0 < discount_pct < 100):
                raise ApiError('ERR_VALIDATION', 'discount_pct must be strictly between 0 and 100', 400)
        if require_all and contract_price is not None:
            raise ApiError('ERR_VALIDATION', 'contract_unit_price_cents must be omitted for DISCOUNT_PCT', 400)
    return contract_price, discount_pct


def check_rule_overlap(candidate, exclude_id=None):
    """Check half-open window overlap against ACTIVE rules with the same scope key."""
    c_from = parse_date(candidate['effective_from'])
    c_to = parse_date(candidate['effective_to'])
    for rule in price_rules.values():
        if exclude_id is not None and rule['id'] == exclude_id:
            continue
        if rule['status'] != 'ACTIVE':
            continue
        if rule['customer_tier'] != candidate['customer_tier']:
            continue
        # Same scope key: (tier, item_id) or (tier, item_class)
        if candidate.get('item_id') is not None:
            if rule.get('item_id') != candidate['item_id']:
                continue
        elif candidate.get('item_class') is not None:
            if rule.get('item_class') != candidate['item_class']:
                continue
            if rule.get('item_id') is not None:
                continue
        else:
            continue
        # For item_id scope, also ensure other rule is item-scoped (not class)
        if candidate.get('item_id') is not None and rule.get('item_id') is None:
            continue
        r_from = parse_date(rule['effective_from'])
        r_to = parse_date(rule['effective_to'])
        # Half-open overlap: [c_from, c_to) shares a day with [r_from, r_to)
        if c_from < r_to and r_from < c_to:
            raise ApiError('ERR_PRICE_RULE_WINDOW_OVERLAP',
                           'Window overlaps an ACTIVE rule with the same scope key', 409)


@app.route('/mro/price-rules', methods=['POST'])
def create_price_rule():
    uid, urole = get_auth()
    require_roles(uid, urole, {'DistributionAdmin'})
    body = get_body()

    customer_tier = require_field(body, 'customer_tier')
    rule_type = require_field(body, 'rule_type')
    effective_from = require_field(body, 'effective_from')
    effective_to = require_field(body, 'effective_to')

    item_id = body.get('item_id')
    item_class = body.get('item_class')

    validate_enum(customer_tier, VALID_PRICE_TIERS, 'customer_tier')
    validate_enum(rule_type, VALID_RULE_TYPES, 'rule_type')
    validate_date_str(effective_from, 'effective_from')
    validate_date_str(effective_to, 'effective_to')

    # Exactly one of item_id / item_class
    if (item_id is None) == (item_class is None):
        raise ApiError('ERR_VALIDATION', 'Exactly one of item_id / item_class must be set', 400)
    if item_class is not None:
        validate_enum(item_class, VALID_ITEM_CLASSES, 'item_class')

    # effective_to > effective_from
    if parse_date(effective_to) <= parse_date(effective_from):
        raise ApiError('ERR_VALIDATION', 'effective_to must be after effective_from', 400)

    # Value fields per rule_type
    contract_price, discount_pct = validate_rule_value_fields(body, rule_type, require_all=True)

    # Existence: item_id reference
    if item_id is not None and item_id not in items_db:
        raise ApiError('ERR_ITEM_NOT_FOUND', 'Item not found', 404)

    rule = make_entity({
        'customer_tier': customer_tier,
        'item_id': item_id,
        'item_class': item_class,
        'rule_type': rule_type,
        'contract_unit_price_cents': contract_price,
        'discount_pct': discount_pct,
        'effective_from': effective_from,
        'effective_to': effective_to,
        'status': 'DRAFT',
    })
    price_rules[rule['id']] = rule
    return success_obj(serialize(rule), 201)


@app.route('/mro/price-rules', methods=['GET'])
def list_price_rules():
    uid, urole = get_auth()
    require_roles(uid, urole, ROLES)
    result = list(price_rules.values())
    f_tier = request.args.get('customer_tier')
    f_item_id = request.args.get('item_id')
    f_item_class = request.args.get('item_class')
    f_status = request.args.get('status')
    if f_tier is not None:
        result = [r for r in result if r['customer_tier'] == f_tier]
    if f_item_id is not None:
        result = [r for r in result if r.get('item_id') == f_item_id]
    if f_item_class is not None:
        result = [r for r in result if r.get('item_class') == f_item_class]
    if f_status is not None:
        result = [r for r in result if r['status'] == f_status]
    return paginate(result)


@app.route('/mro/price-rules/<rule_id>', methods=['GET'])
def get_price_rule(rule_id):
    uid, urole = get_auth()
    require_roles(uid, urole, ROLES)
    rule = price_rules.get(rule_id)
    if rule is None:
        raise ApiError('ERR_PRICE_RULE_NOT_FOUND', 'Price rule not found', 404)
    return success_obj(serialize(rule))


@app.route('/mro/price-rules/<rule_id>', methods=['PUT'])
def update_price_rule(rule_id):
    uid, urole = get_auth()
    require_roles(uid, urole, {'DistributionAdmin'})
    rule = price_rules.get(rule_id)
    if rule is None:
        raise ApiError('ERR_PRICE_RULE_NOT_FOUND', 'Price rule not found', 404)
    body = get_body()

    expected = require_field(body, 'expected_price_rule_version')
    validate_int(expected, 'expected_price_rule_version')

    # Shape validation
    new_rule_type = body.get('rule_type', rule['rule_type'])
    if 'rule_type' in body and body['rule_type'] is not None:
        validate_enum(body['rule_type'], VALID_RULE_TYPES, 'rule_type')
    else:
        new_rule_type = rule['rule_type']

    new_from = body.get('effective_from', rule['effective_from'])
    new_to = body.get('effective_to', rule['effective_to'])
    if 'effective_from' in body and body['effective_from'] is not None:
        validate_date_str(body['effective_from'], 'effective_from')
        new_from = body['effective_from']
    else:
        new_from = rule['effective_from']
    if 'effective_to' in body and body['effective_to'] is not None:
        validate_date_str(body['effective_to'], 'effective_to')
        new_to = body['effective_to']
    else:
        new_to = rule['effective_to']

    if parse_date(new_to) <= parse_date(new_from):
        raise ApiError('ERR_VALIDATION', 'effective_to must be after effective_from', 400)

    # Value fields: merge with existing
    merged = {
        'contract_unit_price_cents': body.get('contract_unit_price_cents', rule['contract_unit_price_cents']),
        'discount_pct': body.get('discount_pct', rule['discount_pct']),
    }
    # If rule_type is changing, validate accordingly
    if new_rule_type == 'FIXED_PRICE':
        if merged['contract_unit_price_cents'] is None:
            raise ApiError('ERR_VALIDATION', 'contract_unit_price_cents is required for FIXED_PRICE', 400)
        validate_int(merged['contract_unit_price_cents'], 'contract_unit_price_cents', min_val=0)
        merged['discount_pct'] = None
    else:
        if merged['discount_pct'] is None:
            raise ApiError('ERR_VALIDATION', 'discount_pct is required for DISCOUNT_PCT', 400)
        dp = merged['discount_pct']
        if not isinstance(dp, (int, float)) or isinstance(dp, bool):
            raise ApiError('ERR_VALIDATION', 'discount_pct must be a number', 400)
        if not (0 < dp < 100):
            raise ApiError('ERR_VALIDATION', 'discount_pct must be strictly between 0 and 100', 400)
        merged['contract_unit_price_cents'] = None

    # OCC check
    if expected != rule['version']:
        raise ApiError('ERR_STALE_VERSION', 'expected_price_rule_version does not match current version', 412)

    # Window change on ACTIVE rule re-runs overlap check
    window_changed = (new_from != rule['effective_from']) or (new_to != rule['effective_to'])
    if rule['status'] == 'ACTIVE' and window_changed:
        candidate = dict(rule)
        candidate['effective_from'] = new_from
        candidate['effective_to'] = new_to
        check_rule_overlap(candidate, exclude_id=rule['id'])

    # Apply
    rule['rule_type'] = new_rule_type
    rule['contract_unit_price_cents'] = merged['contract_unit_price_cents']
    rule['discount_pct'] = merged['discount_pct']
    rule['effective_from'] = new_from
    rule['effective_to'] = new_to
    touch(rule)
    return success_obj(serialize(rule))


@app.route('/mro/price-rules/<rule_id>/activate', methods=['POST'])
def activate_price_rule(rule_id):
    uid, urole = get_auth()
    require_roles(uid, urole, {'DistributionAdmin'})
    rule = price_rules.get(rule_id)
    if rule is None:
        raise ApiError('ERR_PRICE_RULE_NOT_FOUND', 'Price rule not found', 404)
    if rule['status'] != 'DRAFT':
        raise ApiError('ERR_INVALID_STATE_TRANSITION', 'Only DRAFT rules can be activated', 409)
    check_rule_overlap(rule, exclude_id=rule['id'])
    rule['status'] = 'ACTIVE'
    touch(rule)
    return success_obj(serialize(rule))


# ============================================================================
# Routes: Rebate Agreements
# ============================================================================


def validate_tiers(tiers):
    if not isinstance(tiers, list) or len(tiers) < 1:
        raise ApiError('ERR_VALIDATION', 'tiers must be an array with at least 1 entry', 400)
    prev = None
    for i, t in enumerate(tiers):
        if not isinstance(t, dict):
            raise ApiError('ERR_VALIDATION', 'each tier must be an object', 400)
        if 'threshold_cents' not in t or 'rebate_bps' not in t:
            raise ApiError('ERR_VALIDATION', 'each tier requires threshold_cents and rebate_bps', 400)
        tc = t['threshold_cents']
        rb = t['rebate_bps']
        validate_int(tc, 'threshold_cents', min_val=0)
        validate_int(rb, 'rebate_bps', min_val=0, max_val=10000)
        if i == 0 and tc != 0:
            raise ApiError('ERR_VALIDATION', 'first tier threshold_cents must be 0', 400)
        if prev is not None and tc <= prev:
            raise ApiError('ERR_VALIDATION', 'tier thresholds must strictly ascend', 400)
        prev = tc
    return tiers


@app.route('/mro/customers/<customer_id>/rebate-agreements', methods=['POST'])
def create_rebate_agreement(customer_id):
    uid, urole = get_auth()
    require_roles(uid, urole, {'DistributionAdmin'})
    customer = customers.get(customer_id)
    if customer is None:
        raise ApiError('ERR_CUSTOMER_NOT_FOUND', 'Customer not found', 404)
    body = get_body()

    period_start = require_field(body, 'period_start')
    period_end = require_field(body, 'period_end')
    tiers = require_field(body, 'tiers')

    validate_date_str(period_start, 'period_start')
    validate_date_str(period_end, 'period_end')
    if parse_date(period_end) <= parse_date(period_start):
        raise ApiError('ERR_VALIDATION', 'period_end must be after period_start', 400)
    validate_tiers(tiers)

    # National-account gate
    if not customer['is_national_account']:
        raise ApiError('ERR_CUSTOMER_NOT_NATIONAL_ACCOUNT',
                       'Customer is not a national account', 422)

    # Closed-interval overlap with other agreements of the same customer
    ps = parse_date(period_start)
    pe = parse_date(period_end)
    for ag in rebate_agreements.values():
        if ag['customer_id'] != customer_id:
            continue
        aps = parse_date(ag['period_start'])
        ape = parse_date(ag['period_end'])
        if ps <= ape and aps <= pe:
            raise ApiError('ERR_AGREEMENT_WINDOW_OVERLAP',
                           'Period overlaps another agreement of this customer', 409)

    agreement = make_entity({
        'customer_id': customer_id,
        'period_start': period_start,
        'period_end': period_end,
        'tiers': tiers,
        'status': 'DRAFT',
        'accrued_spend_cents': 0,
        'current_tier_index': 0,
        'provisional_rebate_cents': 0,
        'final_rebate_cents': None,
        'true_up_delta_cents': None,
        'settled_credit_cents': None,
    })
    rebate_agreements[agreement['id']] = agreement
    return success_obj(serialize(agreement), 201)


@app.route('/mro/rebate-agreements/<agreement_id>', methods=['GET'])
def get_rebate_agreement(agreement_id):
    uid, urole = get_auth()
    require_roles(uid, urole, ROLES)
    ag = rebate_agreements.get(agreement_id)
    if ag is None:
        raise ApiError('ERR_REBATE_AGREEMENT_NOT_FOUND', 'Rebate agreement not found', 404)
    check_scope(ag['customer_id'], uid, urole)
    return success_obj(serialize(ag))


@app.route('/mro/rebate-agreements/<agreement_id>/activate', methods=['POST'])
def activate_rebate_agreement(agreement_id):
    uid, urole = get_auth()
    require_roles(uid, urole, {'DistributionAdmin'})
    ag = rebate_agreements.get(agreement_id)
    if ag is None:
        raise ApiError('ERR_REBATE_AGREEMENT_NOT_FOUND', 'Rebate agreement not found', 404)
    if ag['status'] != 'DRAFT':
        raise ApiError('ERR_INVALID_STATE_TRANSITION', 'Only DRAFT agreements can be activated', 409)
    if clock_today() > parse_date(ag['period_end']):
        raise ApiError('ERR_AGREEMENT_PERIOD_EXPIRED',
                       'Logical-clock date is after period_end', 409)
    ag['status'] = 'ACTIVE'
    touch(ag)
    return success_obj(serialize(ag))


@app.route('/mro/rebate-agreements/<agreement_id>/close', methods=['POST'])
def close_rebate_agreement(agreement_id):
    uid, urole = get_auth()
    require_roles(uid, urole, {'DistributionAdmin'})
    ag = rebate_agreements.get(agreement_id)
    if ag is None:
        raise ApiError('ERR_REBATE_AGREEMENT_NOT_FOUND', 'Rebate agreement not found', 404)
    if ag['status'] != 'ACTIVE':
        raise ApiError('ERR_INVALID_STATE_TRANSITION', 'Only ACTIVE agreements can be closed', 409)
    if clock_today() <= parse_date(ag['period_end']):
        raise ApiError('ERR_AGREEMENT_PERIOD_NOT_ENDED',
                       'Logical-clock date is not past period_end', 409)
    final = compute_final_rebate(ag)
    ag['final_rebate_cents'] = final
    ag['true_up_delta_cents'] = final - ag['provisional_rebate_cents']
    ag['status'] = 'CLOSED'
    touch(ag)
    return success_obj(serialize(ag))


@app.route('/mro/rebate-agreements/<agreement_id>/settle', methods=['POST'])
def settle_rebate_agreement(agreement_id):
    uid, urole = get_auth()
    require_roles(uid, urole, {'DistributionAdmin'})
    ag = rebate_agreements.get(agreement_id)
    if ag is None:
        raise ApiError('ERR_REBATE_AGREEMENT_NOT_FOUND', 'Rebate agreement not found', 404)
    if ag['status'] != 'CLOSED':
        raise ApiError('ERR_INVALID_STATE_TRANSITION', 'Only CLOSED agreements can be settled', 409)
    ag['settled_credit_cents'] = ag['final_rebate_cents']
    ag['status'] = 'SETTLED'
    touch(ag)
    return success_obj(serialize(ag))


# ============================================================================
# Routes: Stock Locations / Balances
# ============================================================================


@app.route('/mro/locations', methods=['POST'])
def create_location():
    uid, urole = get_auth()
    require_roles(uid, urole, {'DistributionAdmin'})
    body = get_body()

    location_code = require_field(body, 'location_code')
    location_type = require_field(body, 'location_type')
    region_state = require_field(body, 'region_state')

    if not isinstance(location_code, str) or not location_code:
        raise ApiError('ERR_VALIDATION', 'location_code must be a non-empty string', 400)
    validate_enum(location_type, VALID_LOCATION_TYPES, 'location_type')
    if not isinstance(region_state, str) or not region_state:
        raise ApiError('ERR_VALIDATION', 'region_state must be a non-empty string', 400)

    cutoff = body.get('same_day_cutoff_minute')
    if location_type == 'BRANCH':
        if cutoff is None:
            raise ApiError('ERR_VALIDATION', 'same_day_cutoff_minute is required for BRANCH', 400)
        validate_int(cutoff, 'same_day_cutoff_minute', min_val=0, max_val=1439)
    else:  # CENTRAL
        if cutoff is not None:
            raise ApiError('ERR_VALIDATION', 'same_day_cutoff_minute must be omitted for CENTRAL', 400)

    for loc in locations.values():
        if loc['location_code'] == location_code:
            raise ApiError('ERR_LOCATION_CODE_EXISTS', 'location_code already exists', 409)

    loc = make_entity({
        'location_code': location_code,
        'location_type': location_type,
        'region_state': region_state,
        'same_day_cutoff_minute': cutoff,
    })
    locations[loc['id']] = loc
    return success_obj(serialize(loc), 201)


@app.route('/mro/locations/<location_id>', methods=['GET'])
def get_location(location_id):
    uid, urole = get_auth()
    require_roles(uid, urole, ROLES)
    loc = locations.get(location_id)
    if loc is None:
        raise ApiError('ERR_LOCATION_NOT_FOUND', 'Location not found', 404)
    return success_obj(serialize(loc))


@app.route('/mro/locations/<location_id>/restock', methods=['POST'])
def restock_location(location_id):
    uid, urole = get_auth()
    require_roles(uid, urole, {'DistributionAdmin'})
    loc = locations.get(location_id)
    if loc is None:
        raise ApiError('ERR_LOCATION_NOT_FOUND', 'Location not found', 404)
    body = get_body()

    item_id = require_field(body, 'item_id')
    qty = require_field(body, 'qty')

    if not isinstance(item_id, str):
        raise ApiError('ERR_VALIDATION', 'item_id must be a string', 400)
    validate_int(qty, 'qty', min_val=1)

    item = items_db.get(item_id)
    if item is None:
        raise ApiError('ERR_ITEM_NOT_FOUND', 'Item not found', 404)

    balance = get_or_create_balance(location_id, item_id)
    balance['on_hand_qty'] += qty
    update_available(balance)
    touch(balance)

    # Backorder auto-fill chain
    run_backorder_autofill(location_id, item_id)

    return success_obj(serialize(balance))


@app.route('/mro/locations/<location_id>/stock-balances', methods=['GET'])
def list_location_stock_balances(location_id):
    uid, urole = get_auth()
    require_roles(uid, urole, ROLES)
    loc = locations.get(location_id)
    if loc is None:
        raise ApiError('ERR_LOCATION_NOT_FOUND', 'Location not found', 404)
    result = [b for b in stock_balances.values() if b['location_id'] == location_id]
    return paginate(result)


# ============================================================================
# Routes: Requisition Carts
# ============================================================================


def validate_cart_lines(lines):
    if not isinstance(lines, list) or len(lines) < 1:
        raise ApiError('ERR_VALIDATION', 'lines must contain at least 1 line', 400)
    for ln in lines:
        if not isinstance(ln, dict):
            raise ApiError('ERR_VALIDATION', 'each line must be an object', 400)
        if 'item_id' not in ln or ln['item_id'] is None:
            raise ApiError('ERR_VALIDATION', 'each line requires item_id', 400)
        if 'qty' not in ln or ln['qty'] is None:
            raise ApiError('ERR_VALIDATION', 'each line requires qty', 400)
        validate_int(ln['qty'], 'qty', min_val=1)
    return lines


@app.route('/mro/carts', methods=['POST'])
def create_cart():
    uid, urole = get_auth()
    require_roles(uid, urole, {'CustomerBuyer'})
    body = get_body()

    customer_id = require_field(body, 'customer_id')
    lines = require_field(body, 'lines')

    if not isinstance(customer_id, str):
        raise ApiError('ERR_VALIDATION', 'customer_id must be a string', 400)

    # Scope check (buyer must belong to customer)
    check_scope(customer_id, uid, urole)

    # Existence
    customer = customers.get(customer_id)
    if customer is None:
        raise ApiError('ERR_CUSTOMER_NOT_FOUND', 'Customer not found', 404)

    # Shape
    validate_cart_lines(lines)
    for ln in lines:
        if not isinstance(ln['item_id'], str):
            raise ApiError('ERR_VALIDATION', 'item_id must be a string', 400)
        if ln['item_id'] not in items_db:
            raise ApiError('ERR_ITEM_NOT_FOUND', 'Item not found', 404)

    punch_out_external_ref = body.get('punch_out_external_ref')

    cart = make_entity({
        'customer_id': customer_id,
        'punch_out_external_ref': punch_out_external_ref,
        'lines': [{'item_id': l['item_id'], 'qty': l['qty']} for l in lines],
        'estimated_total_cents': 0,
        'status': 'OPEN',
        'rejection_reason': None,
    })
    carts[cart['id']] = cart
    return success_obj(serialize(cart), 201)


@app.route('/mro/carts/<cart_id>', methods=['GET'])
def get_cart(cart_id):
    uid, urole = get_auth()
    require_roles(uid, urole, ROLES)
    cart = carts.get(cart_id)
    if cart is None:
        raise ApiError('ERR_CART_NOT_FOUND', 'Cart not found', 404)
    check_scope(cart['customer_id'], uid, urole)
    return success_obj(serialize(cart))


@app.route('/mro/carts/<cart_id>', methods=['PUT'])
def revise_cart(cart_id):
    uid, urole = get_auth()
    require_roles(uid, urole, {'CustomerBuyer'})
    cart = carts.get(cart_id)
    if cart is None:
        raise ApiError('ERR_CART_NOT_FOUND', 'Cart not found', 404)
    check_scope(cart['customer_id'], uid, urole)
    body = get_body()

    lines = require_field(body, 'lines')
    validate_cart_lines(lines)
    for ln in lines:
        if not isinstance(ln['item_id'], str):
            raise ApiError('ERR_VALIDATION', 'item_id must be a string', 400)
        if ln['item_id'] not in items_db:
            raise ApiError('ERR_ITEM_NOT_FOUND', 'Item not found', 404)

    if cart['status'] not in ('OPEN', 'REJECTED'):
        raise ApiError('ERR_INVALID_STATE_TRANSITION',
                       'Cart lines can only be revised while OPEN or REJECTED', 409)

    cart['lines'] = [{'item_id': l['item_id'], 'qty': l['qty']} for l in lines]
    if cart['status'] == 'REJECTED':
        cart['status'] = 'OPEN'
        cart['rejection_reason'] = None
    touch(cart)
    return success_obj(serialize(cart))


@app.route('/mro/carts/<cart_id>/submit', methods=['POST'])
def submit_cart(cart_id):
    uid, urole = get_auth()
    require_roles(uid, urole, {'CustomerBuyer'})
    cart = carts.get(cart_id)
    if cart is None:
        raise ApiError('ERR_CART_NOT_FOUND', 'Cart not found', 404)
    check_scope(cart['customer_id'], uid, urole)

    if cart['status'] != 'OPEN':
        raise ApiError('ERR_INVALID_STATE_TRANSITION', 'Only OPEN carts can be submitted', 409)
    if not cart['lines'] or len(cart['lines']) < 1:
        raise ApiError('ERR_VALIDATION', 'Cart must contain at least 1 line', 400)

    customer = customers[cart['customer_id']]
    total = 0
    for ln in cart['lines']:
        item = items_db[ln['item_id']]
        unit = resolve_unit_price(customer, item, ln['qty'])
        total += ln['qty'] * unit
    cart['estimated_total_cents'] = total

    if total > customer['approval_threshold_cents']:
        cart['status'] = 'PENDING_APPROVAL'
    else:
        cart['status'] = 'APPROVED'
    touch(cart)
    return success_obj(serialize(cart))


@app.route('/mro/carts/<cart_id>/approve', methods=['POST'])
def approve_cart(cart_id):
    uid, urole = get_auth()
    require_roles(uid, urole, {'CustomerApprover'})
    cart = carts.get(cart_id)
    if cart is None:
        raise ApiError('ERR_CART_NOT_FOUND', 'Cart not found', 404)
    check_scope(cart['customer_id'], uid, urole)
    if cart['status'] != 'PENDING_APPROVAL':
        raise ApiError('ERR_INVALID_STATE_TRANSITION',
                       'Only PENDING_APPROVAL carts can be approved', 409)
    cart['status'] = 'APPROVED'
    touch(cart)
    return success_obj(serialize(cart))


@app.route('/mro/carts/<cart_id>/reject', methods=['POST'])
def reject_cart(cart_id):
    uid, urole = get_auth()
    require_roles(uid, urole, {'CustomerApprover'})
    cart = carts.get(cart_id)
    if cart is None:
        raise ApiError('ERR_CART_NOT_FOUND', 'Cart not found', 404)
    check_scope(cart['customer_id'], uid, urole)
    body = get_body()
    reason = require_field(body, 'reason')
    if not isinstance(reason, str):
        raise ApiError('ERR_VALIDATION', 'reason must be a string', 400)
    if cart['status'] != 'PENDING_APPROVAL':
        raise ApiError('ERR_INVALID_STATE_TRANSITION',
                       'Only PENDING_APPROVAL carts can be rejected', 409)
    cart['status'] = 'REJECTED'
    cart['rejection_reason'] = reason
    touch(cart)
    return success_obj(serialize(cart))


# ============================================================================
# Routes: Sales Orders
# ============================================================================


@app.route('/mro/orders', methods=['POST'])
def create_order():
    uid, urole = get_auth()
    require_roles(uid, urole, {'CustomerBuyer', 'DistributionAdmin'})
    body = get_body()

    customer_id = body.get('customer_id')
    fulfillment_branch_id = body.get('fulfillment_branch_id')
    fulfillment_method = body.get('fulfillment_method')
    lines = body.get('lines')
    source_cart_id = body.get('source_cart_id')

    # Scope check for buyers (before existence, per cascade priority 3)
    if urole in ENTITY_BACKED:
        if customer_id is not None and customer_id != uid:
            raise ApiError('ERR_CUSTOMER_SCOPE_MISMATCH',
                           'Cannot create orders for another account', 403)

    # Existence checks (left-to-right): customer, branch, cart
    if customer_id is not None:
        if not isinstance(customer_id, str):
            raise ApiError('ERR_VALIDATION', 'customer_id must be a string', 400)
        customer = customers.get(customer_id)
        if customer is None:
            raise ApiError('ERR_CUSTOMER_NOT_FOUND', 'Customer not found', 404)
    if fulfillment_branch_id is not None:
        if not isinstance(fulfillment_branch_id, str):
            raise ApiError('ERR_VALIDATION', 'fulfillment_branch_id must be a string', 400)
        branch = locations.get(fulfillment_branch_id)
        if branch is None:
            raise ApiError('ERR_LOCATION_NOT_FOUND', 'Location not found', 404)
    cart = None
    if source_cart_id is not None:
        if not isinstance(source_cart_id, str):
            raise ApiError('ERR_VALIDATION', 'source_cart_id must be a string', 400)
        cart = carts.get(source_cart_id)
        if cart is None:
            raise ApiError('ERR_CART_NOT_FOUND', 'Cart not found', 404)

    # Shape validation
    if customer_id is None:
        raise ApiError('ERR_VALIDATION', 'Missing required field: customer_id', 400)
    if fulfillment_branch_id is None:
        raise ApiError('ERR_VALIDATION', 'Missing required field: fulfillment_branch_id', 400)
    if fulfillment_method is None:
        raise ApiError('ERR_VALIDATION', 'Missing required field: fulfillment_method', 400)
    validate_enum(fulfillment_method, VALID_FULFILLMENT_METHODS, 'fulfillment_method')

    # Exactly one of lines / source_cart_id
    if (lines is None) == (source_cart_id is None):
        raise ApiError('ERR_VALIDATION', 'Exactly one of lines / source_cart_id must be supplied', 400)

    if lines is not None:
        validate_cart_lines(lines)
        for ln in lines:
            if not isinstance(ln['item_id'], str):
                raise ApiError('ERR_VALIDATION', 'item_id must be a string', 400)
            if ln['item_id'] not in items_db:
                raise ApiError('ERR_ITEM_NOT_FOUND', 'Item not found', 404)

    # State: cart must be APPROVED
    if cart is not None and cart['status'] != 'APPROVED':
        raise ApiError('ERR_INVALID_STATE_TRANSITION',
                       'source cart must be APPROVED to convert', 409)

    # Referential: branch must be BRANCH type
    if branch['location_type'] != 'BRANCH':
        raise ApiError('ERR_BRANCH_TYPE_REQUIRED',
                       'fulfillment_branch_id must reference a BRANCH location', 422)

    # Referential: cart customer match
    if cart is not None and cart['customer_id'] != customer_id:
        raise ApiError('ERR_CART_CUSTOMER_MISMATCH',
                       'source_cart_id cart belongs to a different customer', 422)

    customer = customers[customer_id]

    # Build effective lines
    if cart is not None:
        effective_lines = [{'item_id': l['item_id'], 'qty': l['qty']} for l in cart['lines']]
    else:
        effective_lines = [{'item_id': l['item_id'], 'qty': l['qty']} for l in lines]

    # Pricing snapshot at creation
    order = make_entity({
        'customer_id': customer_id,
        'fulfillment_branch_id': fulfillment_branch_id,
        'source_cart_id': source_cart_id,
        'fulfillment_method': fulfillment_method,
        'status': 'SUBMITTED',
        'fulfillment_status': 'UNALLOCATED',
        'subtotal_cents': 0,
        'freight_cents': 0,
        'total_cents': 0,
        'promise_date': None,
        'sla_breach': False,
        'confirmed_at': None,
        'fulfilled_at': None,
        'completed_at': None,
    })
    orders[order['id']] = order

    subtotal = 0
    line_items = []
    for el in effective_lines:
        item = items_db[el['item_id']]
        unit = resolve_unit_price(customer, item, el['qty'])
        line_total = el['qty'] * unit
        line = make_entity({
            'order_id': order['id'],
            'item_id': el['item_id'],
            'qty': el['qty'],
            'unit_price_cents': unit,
            'line_total_cents': line_total,
            'qty_branch': 0,
            'qty_central': 0,
            'qty_drop_ship': 0,
            'qty_backordered': 0,
            'fulfillment_source': 'UNRESOLVED',
            'qty_vendor_confirmed': 0,
            'vendor_cost_actual_cents': None,
            'freight_actual_cents': None,
            'provisional_margin_cents': None,
            'final_margin_cents': None,
            'margin_status': 'NOT_APPLICABLE',
            '_central_location_id': None,
        })
        order_lines_db[line['id']] = line
        subtotal += line_total
        line_items.append(item)

    freight = compute_freight(subtotal, fulfillment_method, line_items)
    order['subtotal_cents'] = subtotal
    order['freight_cents'] = freight
    order['total_cents'] = subtotal + freight

    # Cart conversion
    if cart is not None:
        cart['status'] = 'CONVERTED'
        touch(cart)

    return success_obj(serialize(order), 201)


@app.route('/mro/orders', methods=['GET'])
def list_orders():
    uid, urole = get_auth()
    require_roles(uid, urole, ROLES)

    f_customer = request.args.get('customer_id')
    f_branch = request.args.get('fulfillment_branch_id')
    f_cart = request.args.get('source_cart_id')
    f_status = request.args.get('status')

    # Scope: entity-backed roles confined to own account
    if urole in ENTITY_BACKED:
        if f_customer is not None and f_customer != uid:
            raise ApiError('ERR_CUSTOMER_SCOPE_MISMATCH',
                           'Cannot list orders of another account', 403)
        f_customer = uid

    result = list(orders.values())
    if f_customer is not None:
        result = [o for o in result if o['customer_id'] == f_customer]
    if f_branch is not None:
        result = [o for o in result if o['fulfillment_branch_id'] == f_branch]
    if f_cart is not None:
        result = [o for o in result if o.get('source_cart_id') == f_cart]
    if f_status is not None:
        result = [o for o in result if o['status'] == f_status]
    return paginate(result)


@app.route('/mro/orders/<order_id>', methods=['GET'])
def get_order(order_id):
    uid, urole = get_auth()
    require_roles(uid, urole, ROLES)
    order = orders.get(order_id)
    if order is None:
        raise ApiError('ERR_ORDER_NOT_FOUND', 'Order not found', 404)
    check_scope(order['customer_id'], uid, urole)
    return success_obj(serialize(order))


@app.route('/mro/orders/<order_id>/confirm', methods=['POST'])
def confirm_order(order_id):
    uid, urole = get_auth()
    require_roles(uid, urole, {'DistributionAdmin'})
    order = orders.get(order_id)
    if order is None:
        raise ApiError('ERR_ORDER_NOT_FOUND', 'Order not found', 404)

    # State: must be SUBMITTED
    if order['status'] != 'SUBMITTED':
        raise ApiError('ERR_INVALID_STATE_TRANSITION', 'Only SUBMITTED orders can be confirmed', 409)

    customer = customers[order['customer_id']]

    # State: customer must be ACTIVE
    if customer['status'] != 'ACTIVE':
        raise ApiError('ERR_CUSTOMER_NOT_ACTIVE', 'Customer account is not ACTIVE', 409)

    o_lines = get_order_lines(order_id)

    # Hazmat method restrictions
    if order['fulfillment_method'] != 'WILL_CALL':
        for line in o_lines:
            item = items_db[line['item_id']]
            if item['hazmat_restriction'] == 'WILL_CALL_ONLY':
                raise ApiError('ERR_HAZMAT_METHOD_RESTRICTED',
                               'WILL_CALL_ONLY item cannot be delivered', 422)
            if order['fulfillment_method'] == 'SAME_DAY' and item['hazmat_restriction'] == 'GROUND_ONLY':
                raise ApiError('ERR_HAZMAT_METHOD_RESTRICTED',
                               'GROUND_ONLY item cannot ship SAME_DAY', 422)
        # Hazmat region restrictions
        ship_state = customer['primary_ship_to_state']
        for line in o_lines:
            item = items_db[line['item_id']]
            if ship_state in item.get('restricted_states', []):
                raise ApiError('ERR_HAZMAT_REGION_RESTRICTED',
                               'Item delivery is restricted in the customer ship-to state', 422)

    # Credit gate (last)
    if customer['open_credit_exposure_cents'] + order['total_cents'] > customer['credit_limit_cents']:
        raise ApiError('ERR_CREDIT_LIMIT_EXCEEDED',
                       'Confirmation would exceed the credit limit', 402)

    # === Side effects ===
    order['status'] = 'CONFIRMED'
    order['confirmed_at'] = clock_iso()

    # Promise date for express methods
    if order['fulfillment_method'] in ('WILL_CALL', 'SAME_DAY'):
        branch = locations[order['fulfillment_branch_id']]
        cutoff = branch['same_day_cutoff_minute']
        if clock_minute_of_day() <= cutoff:
            order['promise_date'] = str(clock_today())
        else:
            order['promise_date'] = str(clock_today() + timedelta(days=1))

    # Allocation waterfall per line in creation order
    any_backordered = False
    for line in o_lines:
        run_allocation_for_line(line, order)
        if line['qty_backordered'] > 0:
            any_backordered = True

    order['fulfillment_status'] = 'PARTIALLY_ALLOCATED' if any_backordered else 'ALLOCATED'

    # Debit credit exposure
    customer['open_credit_exposure_cents'] += order['total_cents']
    touch(customer)

    touch(order)
    return success_obj(serialize(order))


@app.route('/mro/orders/<order_id>/cancel', methods=['POST'])
def cancel_order(order_id):
    uid, urole = get_auth()
    require_roles(uid, urole, {'CustomerBuyer', 'DistributionAdmin'})
    order = orders.get(order_id)
    if order is None:
        raise ApiError('ERR_ORDER_NOT_FOUND', 'Order not found', 404)
    check_scope(order['customer_id'], uid, urole)

    if order['status'] == 'SUBMITTED':
        order['status'] = 'CANCELLED'
        touch(order)
        return success_obj(serialize(order))

    if order['status'] != 'CONFIRMED':
        raise ApiError('ERR_INVALID_STATE_TRANSITION',
                       'Only SUBMITTED or CONFIRMED orders can be cancelled', 409)

    if order['fulfillment_status'] not in ('ALLOCATED', 'PARTIALLY_ALLOCATED'):
        raise ApiError('ERR_INVALID_STATE_TRANSITION',
                       'Readied/shipped/fulfilled orders cannot be cancelled', 409)

    # Transition first so auto-fill skips this order (no longer CONFIRMED)
    order['status'] = 'CANCELLED'

    o_lines = get_order_lines(order_id)
    freed = []
    freed_seen = set()
    for line in o_lines:
        if line['qty_branch'] > 0:
            bal = get_balance(order['fulfillment_branch_id'], line['item_id'])
            if bal is not None:
                bal['reserved_qty'] -= line['qty_branch']
                update_available(bal)
                touch(bal)
            key = (order['fulfillment_branch_id'], line['item_id'])
            if key not in freed_seen:
                freed_seen.add(key)
                freed.append(key)
        if line['qty_central'] > 0 and line.get('_central_location_id'):
            bal = get_balance(line['_central_location_id'], line['item_id'])
            if bal is not None:
                bal['reserved_qty'] -= line['qty_central']
                update_available(bal)
                touch(bal)
            key = (line['_central_location_id'], line['item_id'])
            if key not in freed_seen:
                freed_seen.add(key)
                freed.append(key)

    # Backorder auto-fill chain per freed (location, item)
    for loc_id, item_id in freed:
        run_backorder_autofill(loc_id, item_id)

    # Release credit exposure
    customer = customers[order['customer_id']]
    customer['open_credit_exposure_cents'] -= order['total_cents']
    touch(customer)

    touch(order)
    return success_obj(serialize(order))


@app.route('/mro/orders/<order_id>/mark-ready', methods=['POST'])
def mark_ready_order(order_id):
    uid, urole = get_auth()
    require_roles(uid, urole, {'BranchManager'})
    order = orders.get(order_id)
    if order is None:
        raise ApiError('ERR_ORDER_NOT_FOUND', 'Order not found', 404)

    if order['status'] != 'CONFIRMED':
        raise ApiError('ERR_INVALID_STATE_TRANSITION',
                       'Order must be CONFIRMED to mark ready', 409)
    if order['fulfillment_status'] not in ('ALLOCATED', 'PARTIALLY_ALLOCATED'):
        raise ApiError('ERR_INVALID_STATE_TRANSITION',
                       'Order must be ALLOCATED or PARTIALLY_ALLOCATED to mark ready', 409)

    if order['fulfillment_method'] == 'WILL_CALL':
        order['fulfillment_status'] = 'READY_FOR_WILL_CALL'
    else:
        order['fulfillment_status'] = 'SHIPPED'

    # SLA breach adjudication
    if order['promise_date'] is not None:
        order['sla_breach'] = clock_today() > parse_date(order['promise_date'])
    else:
        order['sla_breach'] = False

    touch(order)
    return success_obj(serialize(order))


@app.route('/mro/orders/<order_id>/mark-fulfilled', methods=['POST'])
def mark_fulfilled_order(order_id):
    uid, urole = get_auth()
    require_roles(uid, urole, {'BranchManager'})
    order = orders.get(order_id)
    if order is None:
        raise ApiError('ERR_ORDER_NOT_FOUND', 'Order not found', 404)

    if order['fulfillment_status'] not in ('READY_FOR_WILL_CALL', 'SHIPPED'):
        raise ApiError('ERR_INVALID_STATE_TRANSITION',
                       'Order must be READY_FOR_WILL_CALL or SHIPPED to mark fulfilled', 409)

    # Drop-ship vendor confirmation gate
    o_lines = get_order_lines(order_id)
    for line in o_lines:
        if line['qty_drop_ship'] > line['qty_vendor_confirmed']:
            raise ApiError('ERR_DROP_SHIP_UNCONFIRMED',
                           'Drop-ship lines must be vendor-confirmed before fulfillment', 409)

    # Physical decrements
    for line in o_lines:
        if line['qty_branch'] > 0:
            bal = get_balance(order['fulfillment_branch_id'], line['item_id'])
            if bal is not None:
                bal['on_hand_qty'] -= line['qty_branch']
                bal['reserved_qty'] -= line['qty_branch']
                update_available(bal)
                touch(bal)
        if line['qty_central'] > 0 and line.get('_central_location_id'):
            bal = get_balance(line['_central_location_id'], line['item_id'])
            if bal is not None:
                bal['on_hand_qty'] -= line['qty_central']
                bal['reserved_qty'] -= line['qty_central']
                update_available(bal)
                touch(bal)

    order['fulfillment_status'] = 'FULFILLED'
    order['fulfilled_at'] = clock_iso()
    touch(order)
    return success_obj(serialize(order))


@app.route('/mro/orders/<order_id>/vendor-confirm', methods=['POST'])
def vendor_confirm_order(order_id):
    uid, urole = get_auth()
    require_roles(uid, urole, {'VendorRep'})
    order = orders.get(order_id)
    if order is None:
        raise ApiError('ERR_ORDER_NOT_FOUND', 'Order not found', 404)
    body = get_body()

    actual_costs = require_field(body, 'actual_costs')
    if not isinstance(actual_costs, list):
        raise ApiError('ERR_VALIDATION', 'actual_costs must be an array', 400)

    o_lines = get_order_lines(order_id)
    unconfirmed = {l['id']: l for l in o_lines
                   if l['qty_drop_ship'] > 0 and l['qty_vendor_confirmed'] < l['qty_drop_ship']}

    seen = set()
    for entry in actual_costs:
        if not isinstance(entry, dict):
            raise ApiError('ERR_VALIDATION', 'each actual_costs entry must be an object', 400)
        lid = entry.get('order_line_id')
        if lid is None:
            raise ApiError('ERR_VALIDATION', 'each entry requires order_line_id', 400)
        seen.add(lid)

    if seen != set(unconfirmed.keys()):
        raise ApiError('ERR_VENDOR_LINES_MISMATCH',
                       'actual_costs must cover exactly the unconfirmed drop-ship lines', 422)

    # Apply actuals
    for entry in actual_costs:
        line = unconfirmed[entry['order_line_id']]
        vca = entry.get('vendor_cost_actual_cents')
        fa = entry.get('freight_actual_cents')
        if vca is None or fa is None:
            raise ApiError('ERR_VALIDATION',
                           'each entry requires vendor_cost_actual_cents and freight_actual_cents', 400)
        validate_int(vca, 'vendor_cost_actual_cents', min_val=0)
        validate_int(fa, 'freight_actual_cents', min_val=0)
        line['vendor_cost_actual_cents'] = vca
        line['freight_actual_cents'] = fa
        line['qty_vendor_confirmed'] = line['qty_drop_ship']
        line['final_margin_cents'] = (
            line['qty_drop_ship'] * line['unit_price_cents']
            - (line['qty_drop_ship'] * vca + fa)
        )
        line['margin_status'] = 'FINALIZED'
        touch(line)

    touch(order)
    return success_obj(serialize(order))


@app.route('/mro/orders/<order_id>/complete', methods=['POST'])
def complete_order(order_id):
    uid, urole = get_auth()
    require_roles(uid, urole, {'DistributionAdmin'})
    order = orders.get(order_id)
    if order is None:
        raise ApiError('ERR_ORDER_NOT_FOUND', 'Order not found', 404)

    if order['status'] != 'CONFIRMED':
        raise ApiError('ERR_INVALID_STATE_TRANSITION',
                       'Only CONFIRMED orders can be completed', 409)

    if order['fulfillment_status'] != 'FULFILLED':
        raise ApiError('ERR_ORDER_NOT_FULFILLED',
                       'Order fulfillment_status must be FULFILLED to complete', 409)

    order['status'] = 'COMPLETED'
    order['completed_at'] = clock_iso()

    customer = customers[order['customer_id']]
    customer['net_spend_cents'] += order['total_cents']
    customer['open_credit_exposure_cents'] -= order['total_cents']
    touch(customer)

    # Rebate accrual cascade against completion date
    accrue_rebates(order['customer_id'], order['total_cents'], clock_today())

    touch(order)
    return success_obj(serialize(order))


@app.route('/mro/orders/<order_id>/lines', methods=['GET'])
def list_order_lines(order_id):
    uid, urole = get_auth()
    require_roles(uid, urole, ROLES)
    order = orders.get(order_id)
    if order is None:
        raise ApiError('ERR_ORDER_NOT_FOUND', 'Order not found', 404)
    check_scope(order['customer_id'], uid, urole)
    result = get_order_lines(order_id)
    return paginate(result)


@app.route('/mro/orders/<order_id>/returns', methods=['GET'])
def list_order_returns(order_id):
    uid, urole = get_auth()
    require_roles(uid, urole, ROLES)
    order = orders.get(order_id)
    if order is None:
        raise ApiError('ERR_ORDER_NOT_FOUND', 'Order not found', 404)
    check_scope(order['customer_id'], uid, urole)
    result = [r for r in returns_db.values() if r['order_id'] == order_id]
    return paginate(result)


# ============================================================================
# Routes: Return Authorizations
# ============================================================================

RETURN_WINDOWS = {'STOCKED': 60, 'SPECIAL_ORDER': 30}
RESTOCK_PCTS = {'STOCKED': 0, 'SPECIAL_ORDER': 20}


@app.route('/mro/returns', methods=['POST'])
def create_return():
    uid, urole = get_auth()
    require_roles(uid, urole, {'CustomerBuyer', 'DistributionAdmin'})
    body = get_body()

    order_id = body.get('order_id')
    lines = body.get('lines')

    # Scope check for buyers where possible
    order = None
    if order_id is not None:
        if not isinstance(order_id, str):
            raise ApiError('ERR_VALIDATION', 'order_id must be a string', 400)
        order = orders.get(order_id)
        if order is None:
            raise ApiError('ERR_ORDER_NOT_FOUND', 'Order not found', 404)
        check_scope(order['customer_id'], uid, urole)

    # Shape
    if order_id is None:
        raise ApiError('ERR_VALIDATION', 'Missing required field: order_id', 400)
    if lines is None:
        raise ApiError('ERR_VALIDATION', 'Missing required field: lines', 400)
    if not isinstance(lines, list) or len(lines) < 1:
        raise ApiError('ERR_VALIDATION', 'lines must contain at least 1 line', 400)
    for ln in lines:
        if not isinstance(ln, dict):
            raise ApiError('ERR_VALIDATION', 'each line must be an object', 400)
        if 'order_line_id' not in ln or ln['order_line_id'] is None:
            raise ApiError('ERR_VALIDATION', 'each line requires order_line_id', 400)
        if 'qty' not in ln or ln['qty'] is None:
            raise ApiError('ERR_VALIDATION', 'each line requires qty', 400)
        validate_int(ln['qty'], 'qty', min_val=1)
        if 'condition' not in ln or ln['condition'] is None:
            raise ApiError('ERR_VALIDATION', 'each line requires condition', 400)
        validate_enum(ln['condition'], VALID_CONDITIONS, 'condition')

    # State: order must be returnable
    returnable = (order['status'] == 'COMPLETED') or (
        order['status'] == 'CONFIRMED' and order['fulfillment_status'] == 'FULFILLED')
    if not returnable:
        raise ApiError('ERR_ORDER_NOT_RETURNABLE',
                       'Order must be COMPLETED or CONFIRMED+FULFILLED to return against', 409)

    # Temporal: per-line return window
    fulfilled_date = parse_date(order['fulfilled_at'][:10])
    today = clock_today()
    for ln in lines:
        o_line = order_lines_db.get(ln['order_line_id'])
        if o_line is not None and o_line['order_id'] == order_id:
            item = items_db[o_line['item_id']]
            window = RETURN_WINDOWS.get(item['item_class'])
            if window is not None:
                if today > fulfilled_date + timedelta(days=window):
                    raise ApiError('ERR_RETURN_WINDOW_EXPIRED',
                                   'Return window has expired for this item class', 422)

    # Referential: lines belong to order, item returnable, cumulative qty
    for ln in lines:
        o_line = order_lines_db.get(ln['order_line_id'])
        if o_line is None or o_line['order_id'] != order_id:
            raise ApiError('ERR_RETURN_LINE_INVALID',
                           'Return line does not reference a line of this order', 422)
        item = items_db[o_line['item_id']]
        if item['item_class'] == 'NON_RETURNABLE':
            raise ApiError('ERR_ITEM_NOT_RETURNABLE',
                           'NON_RETURNABLE items cannot be returned', 422)

    # Cumulative qty check across non-rejected returns
    for ln in lines:
        o_line = order_lines_db[ln['order_line_id']]
        already = 0
        for r in returns_db.values():
            if r['order_id'] != order_id or r['status'] == 'REJECTED':
                continue
            for rl in r['lines']:
                if rl['order_line_id'] == ln['order_line_id']:
                    already += rl['qty']
        # Also count duplicates within this same request
        for other in lines:
            if other is ln:
                continue
            pass
        in_request = sum(x['qty'] for x in lines if x['order_line_id'] == ln['order_line_id'])
        if already + in_request > o_line['qty']:
            raise ApiError('ERR_RETURN_LINE_INVALID',
                           'Cumulative returned qty would exceed the order line qty', 422)

    ret = make_entity({
        'order_id': order_id,
        'lines': [{'order_line_id': l['order_line_id'], 'qty': l['qty'], 'condition': l['condition']}
                  for l in lines],
        'status': 'REQUESTED',
        'rejection_reason': None,
        'credit_cents': None,
        'restocking_fee_cents': None,
    })
    returns_db[ret['id']] = ret
    return success_obj(serialize(ret), 201)


@app.route('/mro/returns/<return_id>', methods=['GET'])
def get_return(return_id):
    uid, urole = get_auth()
    require_roles(uid, urole, ROLES)
    ret = returns_db.get(return_id)
    if ret is None:
        raise ApiError('ERR_RETURN_NOT_FOUND', 'Return not found', 404)
    order = orders.get(ret['order_id'])
    if order is not None:
        check_scope(order['customer_id'], uid, urole)
    return success_obj(serialize(ret))


@app.route('/mro/returns/<return_id>/approve', methods=['POST'])
def approve_return(return_id):
    uid, urole = get_auth()
    require_roles(uid, urole, {'DistributionAdmin'})
    ret = returns_db.get(return_id)
    if ret is None:
        raise ApiError('ERR_RETURN_NOT_FOUND', 'Return not found', 404)
    if ret['status'] != 'REQUESTED':
        raise ApiError('ERR_INVALID_STATE_TRANSITION',
                       'Only REQUESTED returns can be approved', 409)
    ret['status'] = 'APPROVED'
    touch(ret)
    return success_obj(serialize(ret))


@app.route('/mro/returns/<return_id>/reject', methods=['POST'])
def reject_return(return_id):
    uid, urole = get_auth()
    require_roles(uid, urole, {'DistributionAdmin'})
    ret = returns_db.get(return_id)
    if ret is None:
        raise ApiError('ERR_RETURN_NOT_FOUND', 'Return not found', 404)
    body = get_body()
    reason = require_field(body, 'reason')
    if not isinstance(reason, str):
        raise ApiError('ERR_VALIDATION', 'reason must be a string', 400)
    if ret['status'] != 'REQUESTED':
        raise ApiError('ERR_INVALID_STATE_TRANSITION',
                       'Only REQUESTED returns can be rejected', 409)
    ret['status'] = 'REJECTED'
    ret['rejection_reason'] = reason
    touch(ret)
    return success_obj(serialize(ret))


@app.route('/mro/returns/<return_id>/receive', methods=['POST'])
def receive_return(return_id):
    uid, urole = get_auth()
    require_roles(uid, urole, {'BranchManager'})
    ret = returns_db.get(return_id)
    if ret is None:
        raise ApiError('ERR_RETURN_NOT_FOUND', 'Return not found', 404)
    if ret['status'] != 'APPROVED':
        raise ApiError('ERR_INVALID_STATE_TRANSITION',
                       'Only APPROVED returns can be received', 409)

    order = orders[ret['order_id']]
    branch_id = order['fulfillment_branch_id']

    # Restock RESALEABLE STOCKED lines at the fulfilling branch
    restocked = []
    restocked_seen = set()
    for rl in ret['lines']:
        o_line = order_lines_db[rl['order_line_id']]
        item = items_db[o_line['item_id']]
        if rl['condition'] == 'RESALEABLE' and item['item_class'] == 'STOCKED':
            bal = get_or_create_balance(branch_id, o_line['item_id'])
            bal['on_hand_qty'] += rl['qty']
            update_available(bal)
            touch(bal)
            key = (branch_id, o_line['item_id'])
            if key not in restocked_seen:
                restocked_seen.add(key)
                restocked.append(key)

    ret['status'] = 'RECEIVED'
    touch(ret)

    # Backorder auto-fill chain
    for loc_id, item_id in restocked:
        run_backorder_autofill(loc_id, item_id)

    return success_obj(serialize(ret))


@app.route('/mro/returns/<return_id>/credit', methods=['POST'])
def credit_return(return_id):
    uid, urole = get_auth()
    require_roles(uid, urole, {'DistributionAdmin'})
    ret = returns_db.get(return_id)
    if ret is None:
        raise ApiError('ERR_RETURN_NOT_FOUND', 'Return not found', 404)
    if ret['status'] != 'RECEIVED':
        raise ApiError('ERR_INVALID_STATE_TRANSITION',
                       'Only RECEIVED returns can be credited', 409)

    order = orders[ret['order_id']]

    # Per-line rounding, then sum
    total_gross = 0
    total_credit = 0
    for rl in ret['lines']:
        o_line = order_lines_db[rl['order_line_id']]
        item = items_db[o_line['item_id']]
        gross = rl['qty'] * o_line['unit_price_cents']
        pct = RESTOCK_PCTS.get(item['item_class'], 0)
        credit = round_half_up(Decimal(gross) * (Decimal(1) - Decimal(pct) / Decimal(100)))
        total_gross += gross
        total_credit += credit

    ret['credit_cents'] = total_credit
    ret['restocking_fee_cents'] = total_gross - total_credit
    ret['status'] = 'CREDITED'
    touch(ret)

    # Fiscal unwind + rebate decrement cascade at credit date
    customer = customers[order['customer_id']]
    customer['net_spend_cents'] -= total_credit
    touch(customer)

    decrement_rebates(order['customer_id'], total_credit, clock_today())

    return success_obj(serialize(ret))


# ============================================================================
# Fallback error handlers (keep envelope shape for unexpected errors)
# ============================================================================


@app.errorhandler(404)
def not_found(e):
    return jsonify({
        'meta': {
            'api_request_id': gen_request_id(),
            'api_request_timestamp': clock_iso(),
        },
        'response_type': 'error',
        'data': {'error_id': 'ERR_VALIDATION', 'message': 'Resource not found'},
    }), 404


@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({
        'meta': {
            'api_request_id': gen_request_id(),
            'api_request_timestamp': clock_iso(),
        },
        'response_type': 'error',
        'data': {'error_id': 'ERR_VALIDATION', 'message': 'Method not allowed'},
    }), 405


@app.errorhandler(Exception)
def unhandled(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return jsonify({
        'meta': {
            'api_request_id': gen_request_id(),
            'api_request_timestamp': clock_iso(),
        },
        'response_type': 'error',
        'data': {'error_id': 'ERR_VALIDATION', 'message': str(e)},
    }), 400


# ============================================================================
# Main
# ============================================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '10000'))
    app.run(host='0.0.0.0', port=port)
