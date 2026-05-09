"""Logistics WMS — core helpers, store, envelope, business logic."""

import math
import random
import string
import threading
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from flask import g, jsonify, request

# ============================================================================
# In-memory store
# ============================================================================

class Store:
    def __init__(self):
        self.warehouses = {}
        self.bins = {}
        self.lots = {}
        self.inbound_shipments = {}
        self.inbound_lines = {}
        self.inventory = {}
        self.waves = {}
        self.orders = {}
        self.pick_tasks = {}
        self.cycle_counts = {}
        # warehouse_id -> list of {at: datetime}
        self.abnormal_events = {}
        self.tracking_counter = 0

store = Store()
lock = threading.RLock()

# ============================================================================
# Errors
# ============================================================================

class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        self.error_id = error_id
        self.message = message
        self.http_status = http_status

# ============================================================================
# Time helpers
# ============================================================================

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

def now_dt():
    return datetime.now(timezone.utc)

def dt_to_iso(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{ms:03d}Z'

def parse_iso(s):
    if s is None:
        return None
    if isinstance(s, datetime):
        if s.tzinfo is None:
            s = s.replace(tzinfo=timezone.utc)
        return s
    if not isinstance(s, str):
        raise ApiError('ERR_INVALID_INPUT', 'Invalid datetime', 422)
    try:
        ss = s
        if ss.endswith('Z'):
            ss = ss[:-1] + '+00:00'
        dt = datetime.fromisoformat(ss)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        raise ApiError('ERR_INVALID_INPUT', 'Invalid datetime format', 422)

def gen_id():
    return str(uuid.uuid4())

def gen_request_id():
    return 'req_' + ''.join(random.choices(string.ascii_letters + string.digits, k=20))

def common_fields():
    now = now_dt()
    return {
        'id': gen_id(),
        'created_at': now,
        'updated_at': now,
        'version': 1,
    }

def bump(entity):
    entity['version'] += 1
    entity['updated_at'] = now_dt()

# ============================================================================
# Envelope
# ============================================================================

def get_request_id():
    rid = getattr(g, 'request_id', None)
    if not rid:
        rid = gen_request_id()
        g.request_id = rid
    return rid

def success(data, response_type='object', status=200, pagination=None):
    meta = {'api_request_id': get_request_id(), 'api_request_timestamp': dt_to_iso(now_dt())}
    if pagination is not None:
        meta.update(pagination)
    body = {'meta': meta, 'response_type': response_type, 'data': data}
    return jsonify(body), status

def error_response(error_id, message, http_status):
    meta = {'api_request_id': get_request_id(), 'api_request_timestamp': dt_to_iso(now_dt())}
    body = {'meta': meta, 'response_type': 'error',
            'data': {'error_id': error_id, 'message': message}}
    return jsonify(body), http_status

# ============================================================================
# Auth
# ============================================================================

ROLES = {'WarehouseStaff', 'Auditor', 'WarehouseManager'}

def authenticate():
    user_id = request.headers.get('X-User-ID', '').strip()
    user_role = request.headers.get('X-User-Role', '').strip()
    if not user_id or not user_role:
        raise ApiError('ERR_AUTH_REQUIRED', 'X-User-ID and X-User-Role headers required', 401)
    if user_role not in ROLES:
        raise ApiError('ERR_FORBIDDEN', f'Role "{user_role}" is not recognized', 403)
    g.user_id = user_id
    g.user_role = user_role
    return user_id, user_role

def require_roles(*allowed):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.user_role not in allowed:
                raise ApiError('ERR_FORBIDDEN', f'Role {g.user_role} not authorized', 403)
            return fn(*args, **kwargs)
        return wrapper
    return deco

# ============================================================================
# Validation primitives
# ============================================================================

def get_json_body():
    if request.method == 'GET' or request.method == 'DELETE':
        return {}
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False, force=True)
    except Exception:
        raise ApiError('ERR_INVALID_INPUT', 'Malformed JSON body', 422)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError('ERR_INVALID_INPUT', 'Body must be JSON object', 422)
    return body

def required_str(body, key):
    v = body.get(key)
    if v is None or not isinstance(v, str) or v == '':
        raise ApiError('ERR_INVALID_INPUT', f'Missing or invalid {key}', 422)
    return v

def required_int(body, key, *, allow_zero=True, allow_negative=False):
    v = body.get(key)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise ApiError('ERR_INVALID_INPUT', f'Missing or invalid {key}', 422)
    if not allow_zero and v == 0:
        raise ApiError('ERR_INVALID_INPUT', f'{key} must be positive', 422)
    if not allow_negative and v < 0:
        raise ApiError('ERR_INVALID_INPUT', f'{key} must be non-negative', 422)
    return v

def optional_int(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError('ERR_INVALID_INPUT', f'Invalid {key}', 422)
    return v

def required_enum(body, key, allowed, error_id='ERR_INVALID_INPUT'):
    v = body.get(key)
    if v is None or v not in allowed:
        raise ApiError(error_id, f'{key} must be one of {sorted(allowed)}', 422)
    return v

def optional_enum(body, key, allowed, default):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if v not in allowed:
        raise ApiError('ERR_INVALID_INPUT', f'{key} must be one of {sorted(allowed)}', 422)
    return v

# ============================================================================
# OCC check
# ============================================================================

def occ_check(entity, body):
    if 'version' in body and body['version'] is not None:
        v = body['version']
        if isinstance(v, bool) or not isinstance(v, int):
            raise ApiError('ERR_INVALID_INPUT', 'Invalid version', 422)
        if v != entity['version']:
            raise ApiError('ERR_VERSION_CONFLICT', 'Optimistic concurrency conflict', 409)

# ============================================================================
# Pagination
# ============================================================================

def paginate(items_iter):
    items = list(items_iter)
    try:
        limit = int(request.args.get('limit', 10))
    except (ValueError, TypeError):
        raise ApiError('ERR_INVALID_INPUT', 'Invalid limit', 422)
    try:
        offset = int(request.args.get('offset', 0))
    except (ValueError, TypeError):
        raise ApiError('ERR_INVALID_INPUT', 'Invalid offset', 422)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    items.sort(key=lambda x: x['created_at'])
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {'limit': limit, 'offset': offset, 'total_count': total,
                  'has_more': offset + limit < total}
    return page, pagination

# ============================================================================
# Lookup helpers (path existence)
# ============================================================================

def get_warehouse(warehouse_id):
    w = store.warehouses.get(warehouse_id)
    if not w:
        raise ApiError('ERR_NOT_FOUND', f'Warehouse {warehouse_id} not found', 404)
    return w

def get_bin(warehouse_id, bin_id):
    get_warehouse(warehouse_id)
    b = store.bins.get(bin_id)
    if not b or b['warehouse_id'] != warehouse_id:
        raise ApiError('ERR_NOT_FOUND', f'Bin {bin_id} not found', 404)
    return b

def get_lot(warehouse_id, lot_id):
    get_warehouse(warehouse_id)
    l = store.lots.get(lot_id)
    if not l or l['warehouse_id'] != warehouse_id:
        raise ApiError('ERR_NOT_FOUND', f'Lot {lot_id} not found', 404)
    return l

def get_inbound_shipment(warehouse_id, shipment_id):
    get_warehouse(warehouse_id)
    s = store.inbound_shipments.get(shipment_id)
    if not s or s['warehouse_id'] != warehouse_id:
        raise ApiError('ERR_NOT_FOUND', f'Inbound shipment {shipment_id} not found', 404)
    return s

def get_wave(warehouse_id, wave_id):
    get_warehouse(warehouse_id)
    w = store.waves.get(wave_id)
    if not w or w['warehouse_id'] != warehouse_id:
        raise ApiError('ERR_NOT_FOUND', f'Wave {wave_id} not found', 404)
    return w

def get_order(warehouse_id, order_id):
    get_warehouse(warehouse_id)
    o = store.orders.get(order_id)
    if not o or o['warehouse_id'] != warehouse_id:
        raise ApiError('ERR_NOT_FOUND', f'Order {order_id} not found', 404)
    return o

def get_pick_task(warehouse_id, pt_id):
    get_warehouse(warehouse_id)
    pt = store.pick_tasks.get(pt_id)
    if not pt:
        raise ApiError('ERR_NOT_FOUND', f'PickTask {pt_id} not found', 404)
    o = store.orders.get(pt['order_id'])
    if not o or o['warehouse_id'] != warehouse_id:
        raise ApiError('ERR_NOT_FOUND', f'PickTask {pt_id} not found', 404)
    return pt

def get_cycle_count(warehouse_id, cc_id):
    get_warehouse(warehouse_id)
    cc = store.cycle_counts.get(cc_id)
    if not cc or cc['warehouse_id'] != warehouse_id:
        raise ApiError('ERR_NOT_FOUND', f'CycleCount {cc_id} not found', 404)
    return cc

# ============================================================================
# Math / rounding
# ============================================================================

def round_half_up_decimals(value, decimals):
    q = Decimal(10) ** (-decimals)
    return Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)

def round_half_up_int(value):
    return int(Decimal(str(value)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))

def euclidean(x1, y1, x2, y2):
    return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)

# ============================================================================
# Inspection sample size
# ============================================================================

def inspection_sample_size(declared_total_units):
    n = declared_total_units
    if n <= 50:
        return 8
    if n <= 150:
        return 13
    if n <= 280:
        return 20
    if n <= 500:
        return 32
    return 50

# ============================================================================
# Bin capacity recompute
# ============================================================================

def recompute_bin_capacity(b):
    used_v = 0
    used_w = 0
    for inv in store.inventory.values():
        if inv['bin_id'] != b['id']:
            continue
        lot = store.lots.get(inv['lot_id'])
        if not lot:
            continue
        if lot['status'] == 'DISPOSED':
            continue
        used_v += inv['qty_units'] * lot['unit_volume_cm3']
        used_w += inv['qty_units'] * lot['unit_weight_g']
    b['used_volume_cm3'] = used_v
    b['used_weight_g'] = used_w

# ============================================================================
# Warehouse risk metrics recompute
# ============================================================================

def recompute_warehouse_metrics(w):
    """Recompute counters and risk_score/posture. Caller decides whether to bump version."""
    clock = w['clock_now']
    cutoff_24h = clock - timedelta(seconds=86400)
    cutoff_30d = clock - timedelta(days=30)

    # abnormal events: decay (drop events older than 24h ago)
    events = store.abnormal_events.get(w['id'], [])
    fresh = [e for e in events if e['at'] >= cutoff_24h]
    store.abnormal_events[w['id']] = fresh
    w['abnormal_event_count_24h'] = len(fresh)

    # shrinkage_value_30d_cents: sum of variance_value_cents for ADJUSTED
    # cycle counts approved within last 30 simulated days
    total = 0
    for cc in store.cycle_counts.values():
        if cc['warehouse_id'] != w['id']:
            continue
        if cc['status'] != 'ADJUSTED':
            continue
        approved_at = cc.get('approved_at')
        if approved_at is None:
            continue
        if approved_at < cutoff_30d:
            continue
        total += cc.get('variance_value_cents') or 0
    w['shrinkage_value_30d_cents'] = total

    # recall_count_open
    cnt = sum(1 for l in store.lots.values()
              if l['warehouse_id'] == w['id'] and l['status'] == 'RECALLED')
    w['recall_count_open'] = cnt

    # risk_score
    raw = (Decimal(w['shrinkage_value_30d_cents']) / Decimal(100)
           + Decimal(w['abnormal_event_count_24h']) * Decimal(10)
           + Decimal(w['recall_count_open']) * Decimal(100))
    score = raw.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    if score > Decimal('1000'):
        score = Decimal('1000')
    w['risk_score'] = float(score)

    if w['risk_score'] > 200:
        w['posture'] = 'FROZEN'
    elif w['risk_score'] > 100:
        w['posture'] = 'RESTRICTED'
    else:
        w['posture'] = 'OPEN'

def add_abnormal_event(w):
    events = store.abnormal_events.setdefault(w['id'], [])
    events.append({'at': w['clock_now']})

# ============================================================================
# Putaway selector
# ============================================================================

def select_putaway_bin(w, lot, received_units, *, returns_only=False):
    """Pick a bin per warehouse.putaway_strategy. Raises ERR_NO_BIN_AVAILABLE
    if no bin satisfies zone+capacity+ACTIVE filters."""
    needed_v = received_units * lot['unit_volume_cm3']
    needed_w = received_units * lot['unit_weight_g']

    candidates = []
    for b in store.bins.values():
        if b['warehouse_id'] != w['id']:
            continue
        if b['status'] != 'ACTIVE':
            continue
        if returns_only:
            if b['zone'] != 'RETURNS':
                continue
        else:
            if b['zone'] != lot['category']:
                continue
        recompute_bin_capacity(b)
        rem_v = b['capacity_volume_cm3'] - b['used_volume_cm3']
        rem_w = b['capacity_weight_g'] - b['used_weight_g']
        if rem_v < needed_v:
            continue
        if rem_w < needed_w:
            continue
        candidates.append(b)

    if not candidates:
        raise ApiError('ERR_NO_BIN_AVAILABLE',
                       'No bin satisfies zone, capacity, and ACTIVE filters',
                       409)

    if w['putaway_strategy'] == 'CAPACITY_OPTIMIZED':
        candidates.sort(key=lambda b: (
            -(b['capacity_volume_cm3'] - b['used_volume_cm3']),
            b['bin_code'],
        ))
    else:  # DISTANCE_OPTIMIZED (default)
        candidates.sort(key=lambda b: (b['distance_from_dock'], b['bin_code']))
    return candidates[0]

# ============================================================================
# Pick lot selector
# ============================================================================

def select_pick_inventory(w, sku, qty_units, pick_strategy):
    """Return list of (inventory_row, take_units) for this requested line.
    Raises ERR_INSUFFICIENT_INVENTORY if cannot fully satisfy."""
    candidate_invs = []
    for inv in store.inventory.values():
        if inv['warehouse_id'] != w['id']:
            continue
        lot = store.lots.get(inv['lot_id'])
        if not lot:
            continue
        if lot['sku'] != sku:
            continue
        if lot['status'] not in {'ACTIVE', 'NEAR_EXPIRY'}:
            continue
        avail = inv['qty_units'] - inv['reserved_units']
        if avail <= 0:
            continue
        candidate_invs.append((inv, lot, avail))

    if pick_strategy == 'FIFO':
        candidate_invs.sort(key=lambda t: (
            t[1].get('received_at') or datetime.max.replace(tzinfo=timezone.utc),
            t[1]['lot_code'],
        ))
    else:  # FEFO default
        candidate_invs.sort(key=lambda t: (t[1]['expiry_date'], t[1]['lot_code']))

    remaining = qty_units
    picks = []
    for inv, lot, avail in candidate_invs:
        if remaining == 0:
            break
        take = min(remaining, avail)
        picks.append((inv, take))
        remaining -= take

    if remaining > 0:
        raise ApiError('ERR_INSUFFICIENT_INVENTORY',
                       f'Insufficient inventory for sku {sku}', 409)
    return picks

# ============================================================================
# Carton count calculation
# ============================================================================

CARTON_VOLUME_CM3 = 50000
CARTON_WEIGHT_G = 20000

def carton_count_provisional(w, requested_lines):
    total_v = 0
    total_w = 0
    for line in requested_lines:
        sku = line['sku']
        qty = line['qty_units']
        # SKU-weighted average across ACTIVE/NEAR_EXPIRY lots
        weight_sum = 0
        vol_sum = 0
        wt_sum = 0
        for inv in store.inventory.values():
            if inv['warehouse_id'] != w['id']:
                continue
            lot = store.lots.get(inv['lot_id'])
            if not lot or lot['sku'] != sku:
                continue
            if lot['status'] not in {'ACTIVE', 'NEAR_EXPIRY'}:
                continue
            wq = inv['qty_units']
            if wq <= 0:
                continue
            weight_sum += wq
            vol_sum += wq * lot['unit_volume_cm3']
            wt_sum += wq * lot['unit_weight_g']
        if weight_sum > 0:
            avg_v = vol_sum / weight_sum
            avg_w = wt_sum / weight_sum
        else:
            # fallback to most recent PUTAWAY inbound line for this sku
            avg_v = None
            avg_w = None
            best_line = None
            best_at = None
            for il in store.inbound_lines.values():
                if il['status'] != 'PUTAWAY':
                    continue
                lot = store.lots.get(il['lot_id'])
                if not lot or lot['sku'] != sku:
                    continue
                ish = store.inbound_shipments.get(il['inbound_shipment_id'])
                if not ish or ish['warehouse_id'] != w['id']:
                    continue
                if best_at is None or il['updated_at'] > best_at:
                    best_at = il['updated_at']
                    best_line = il
            if best_line:
                lot = store.lots.get(best_line['lot_id'])
                avg_v = lot['unit_volume_cm3']
                avg_w = lot['unit_weight_g']
            else:
                # last-ditch: any lot of sku
                lot = next((l for l in store.lots.values()
                            if l['warehouse_id'] == w['id'] and l['sku'] == sku),
                           None)
                if lot:
                    avg_v = lot['unit_volume_cm3']
                    avg_w = lot['unit_weight_g']
                else:
                    avg_v = 0
                    avg_w = 0
        total_v += qty * avg_v
        total_w += qty * avg_w

    cartons_v = math.ceil(total_v / CARTON_VOLUME_CM3) if total_v > 0 else 0
    cartons_w = math.ceil(total_w / CARTON_WEIGHT_G) if total_w > 0 else 0
    return max(cartons_v, cartons_w, 1)

def carton_count_final(order):
    total_v = 0
    total_w = 0
    for pt in store.pick_tasks.values():
        if pt['order_id'] != order['id']:
            continue
        if pt['status'] != 'PICKED':
            continue
        lot = store.lots.get(pt['lot_id'])
        if not lot:
            continue
        total_v += pt['picked_units'] * lot['unit_volume_cm3']
        total_w += pt['picked_units'] * lot['unit_weight_g']
    cartons_v = math.ceil(total_v / CARTON_VOLUME_CM3) if total_v > 0 else 0
    cartons_w = math.ceil(total_w / CARTON_WEIGHT_G) if total_w > 0 else 0
    return max(cartons_v, cartons_w, 1)

# ============================================================================
# Wave path distance
# ============================================================================

def assign_wave_path(w, wave):
    pts = [pt for pt in store.pick_tasks.values()
           if pt.get('wave_id') == wave['id']]
    pts_sorted = sorted(pts, key=lambda pt: (
        store.bins[pt['bin_id']]['bin_code'], pt['id']))
    for i, pt in enumerate(pts_sorted, start=1):
        old = pt.get('sequence')
        pt['sequence'] = i
        if old != i:
            bump(pt)
    # path distance: dock -> bin1 -> ... -> binN -> dock
    dx = w['dock_position_x']
    dy = w['dock_position_y']
    d = Decimal('0')
    prev_x, prev_y = dx, dy
    for pt in pts_sorted:
        b = store.bins[pt['bin_id']]
        d += Decimal(str(euclidean(b['position_x'], b['position_y'], prev_x, prev_y)))
        prev_x, prev_y = b['position_x'], b['position_y']
    d += Decimal(str(euclidean(dx, dy, prev_x, prev_y)))
    wave['total_path_distance'] = float(d.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP))
    return pts_sorted

# ============================================================================
# Near-expiry scan / cascade
# ============================================================================

def near_expiry_scan(w):
    clock = w['clock_now']
    for lot in list(store.lots.values()):
        if lot['warehouse_id'] != w['id']:
            continue
        if lot['status'] not in {'ACTIVE', 'NEAR_EXPIRY'}:
            continue
        diff_seconds = (lot['expiry_date'] - clock).total_seconds()
        days_to_expiry = math.floor(diff_seconds / 86400)
        if days_to_expiry < 0:
            old_status = lot['status']
            lot['status'] = 'EXPIRED'
            bump(lot)
            # cascade: CREATED PickTasks → FAILED, release reservations
            for pt in list(store.pick_tasks.values()):
                if pt['lot_id'] == lot['id'] and pt['status'] == 'CREATED':
                    pt['status'] = 'FAILED'
                    bump(pt)
                    inv = store.inventory.get(pt['inventory_id'])
                    if inv:
                        inv['reserved_units'] = max(0, inv['reserved_units'] - pt['planned_units'])
                        bump(inv)
                    propagate_pick_terminal(w, pt)
        elif days_to_expiry <= 30 and lot['status'] == 'ACTIVE':
            lot['status'] = 'NEAR_EXPIRY'
            bump(lot)

# ============================================================================
# Cascades when a pick task hits a terminal state
# ============================================================================

def propagate_pick_terminal(w, pt):
    """After a pick task moves to terminal, possibly transition its order/wave."""
    # Order rollup
    order = store.orders.get(pt['order_id'])
    if order:
        siblings = [p for p in store.pick_tasks.values()
                    if p['order_id'] == order['id']]
        terminal_set = {'PICKED', 'SHORT_PICKED', 'FAILED', 'CANCELLED'}
        if all(p['status'] in terminal_set for p in siblings):
            has_picked = any(p['status'] == 'PICKED' for p in siblings)
            has_shortish = any(p['status'] in {'SHORT_PICKED', 'FAILED'} for p in siblings)
            if order['status'] == 'PICKING':
                if has_shortish:
                    order['status'] = 'SHORT_PICKED'
                    bump(order)
                    add_abnormal_event(w)
                elif has_picked:
                    order['status'] = 'PICKED'
                    bump(order)

    # Wave rollup
    wave_id = pt.get('wave_id')
    if wave_id:
        wave = store.waves.get(wave_id)
        if wave and wave['status'] == 'IN_PROGRESS':
            wave_pts = [p for p in store.pick_tasks.values()
                        if p.get('wave_id') == wave['id']]
            if wave_pts and all(
                p['status'] in {'PICKED', 'SHORT_PICKED', 'FAILED', 'CANCELLED'}
                for p in wave_pts):
                wave['status'] = 'COMPLETED'
                wave['completed_at'] = w['clock_now']
                bump(wave)

# ============================================================================
# Serialization
# ============================================================================

def ser_warehouse(w):
    recompute_warehouse_metrics(w)
    return {
        'id': w['id'],
        'created_at': dt_to_iso(w['created_at']),
        'updated_at': dt_to_iso(w['updated_at']),
        'version': w['version'],
        'name': w['name'],
        'dock_position_x': w['dock_position_x'],
        'dock_position_y': w['dock_position_y'],
        'putaway_strategy': w['putaway_strategy'],
        'ops_run_index': w['ops_run_index'],
        'clock_now': dt_to_iso(w['clock_now']),
        'shrinkage_value_30d_cents': w['shrinkage_value_30d_cents'],
        'abnormal_event_count_24h': w['abnormal_event_count_24h'],
        'recall_count_open': w['recall_count_open'],
        'risk_score': w['risk_score'],
        'posture': w['posture'],
    }

def ser_bin(b):
    recompute_bin_capacity(b)
    used_v = b['used_volume_cm3']
    used_w = b['used_weight_g']
    return {
        'id': b['id'],
        'created_at': dt_to_iso(b['created_at']),
        'updated_at': dt_to_iso(b['updated_at']),
        'version': b['version'],
        'warehouse_id': b['warehouse_id'],
        'bin_code': b['bin_code'],
        'zone': b['zone'],
        'position_x': b['position_x'],
        'position_y': b['position_y'],
        'capacity_volume_cm3': b['capacity_volume_cm3'],
        'capacity_weight_g': b['capacity_weight_g'],
        'used_volume_cm3': used_v,
        'used_weight_g': used_w,
        'remaining_volume_cm3': b['capacity_volume_cm3'] - used_v,
        'remaining_weight_g': b['capacity_weight_g'] - used_w,
        'status': b['status'],
        'frozen_by_cycle_count_id': b.get('frozen_by_cycle_count_id'),
        'distance_from_dock': b['distance_from_dock'],
    }

def ser_lot(l):
    return {
        'id': l['id'],
        'created_at': dt_to_iso(l['created_at']),
        'updated_at': dt_to_iso(l['updated_at']),
        'version': l['version'],
        'warehouse_id': l['warehouse_id'],
        'lot_code': l['lot_code'],
        'sku': l['sku'],
        'category': l['category'],
        'unit_weight_g': l['unit_weight_g'],
        'unit_volume_cm3': l['unit_volume_cm3'],
        'unit_value_cents': l['unit_value_cents'],
        'manufacture_date': dt_to_iso(l['manufacture_date']),
        'expiry_date': dt_to_iso(l['expiry_date']),
        'received_at': dt_to_iso(l.get('received_at')),
        'supplier_lot_ref': l['supplier_lot_ref'],
        'status': l['status'],
        'recalled_at': dt_to_iso(l.get('recalled_at')),
        'recall_reason': l.get('recall_reason'),
    }

def ser_inbound_line(il):
    return {
        'id': il['id'],
        'created_at': dt_to_iso(il['created_at']),
        'updated_at': dt_to_iso(il['updated_at']),
        'version': il['version'],
        'inbound_shipment_id': il['inbound_shipment_id'],
        'lot_id': il['lot_id'],
        'declared_units': il['declared_units'],
        'received_units': il.get('received_units'),
        'bin_id': il.get('bin_id'),
        'status': il['status'],
    }

def ser_inbound_shipment(s):
    lines = [ser_inbound_line(il) for il in store.inbound_lines.values()
             if il['inbound_shipment_id'] == s['id']]
    return {
        'id': s['id'],
        'created_at': dt_to_iso(s['created_at']),
        'updated_at': dt_to_iso(s['updated_at']),
        'version': s['version'],
        'warehouse_id': s['warehouse_id'],
        'asn_number': s['asn_number'],
        'supplier_name': s['supplier_name'],
        'declared_total_units': s['declared_total_units'],
        'inspection_sample_size': s.get('inspection_sample_size'),
        'inspection_defect_count': s.get('inspection_defect_count'),
        'defect_rate': s.get('defect_rate'),
        'status': s['status'],
        'lines': lines,
    }

def ser_inventory(inv):
    return {
        'id': inv['id'],
        'created_at': dt_to_iso(inv['created_at']),
        'updated_at': dt_to_iso(inv['updated_at']),
        'version': inv['version'],
        'warehouse_id': inv['warehouse_id'],
        'bin_id': inv['bin_id'],
        'lot_id': inv['lot_id'],
        'qty_units': inv['qty_units'],
        'reserved_units': inv['reserved_units'],
        'available_units': inv['qty_units'] - inv['reserved_units'],
    }

def ser_wave(wv):
    return {
        'id': wv['id'],
        'created_at': dt_to_iso(wv['created_at']),
        'updated_at': dt_to_iso(wv['updated_at']),
        'version': wv['version'],
        'warehouse_id': wv['warehouse_id'],
        'wave_code': wv['wave_code'],
        'strategy': wv['strategy'],
        'order_ids': wv['order_ids'],
        'planned_unit_count': wv.get('planned_unit_count', 0),
        'picked_unit_count': wv.get('picked_unit_count', 0),
        'total_path_distance': wv.get('total_path_distance'),
        'status': wv['status'],
        'released_at': dt_to_iso(wv.get('released_at')),
        'completed_at': dt_to_iso(wv.get('completed_at')),
    }

def ser_pick_task(pt):
    return {
        'id': pt['id'],
        'created_at': dt_to_iso(pt['created_at']),
        'updated_at': dt_to_iso(pt['updated_at']),
        'version': pt['version'],
        'order_id': pt['order_id'],
        'wave_id': pt.get('wave_id'),
        'bin_id': pt['bin_id'],
        'lot_id': pt['lot_id'],
        'inventory_id': pt['inventory_id'],
        'planned_units': pt['planned_units'],
        'picked_units': pt['picked_units'],
        'sequence': pt.get('sequence'),
        'status': pt['status'],
    }

def ser_order(o):
    pick_tasks = [ser_pick_task(pt) for pt in store.pick_tasks.values()
                  if pt['order_id'] == o['id']]
    return {
        'id': o['id'],
        'created_at': dt_to_iso(o['created_at']),
        'updated_at': dt_to_iso(o['updated_at']),
        'version': o['version'],
        'warehouse_id': o['warehouse_id'],
        'order_number': o['order_number'],
        'customer_name': o['customer_name'],
        'requested_lines': o['requested_lines'],
        'pick_strategy': o['pick_strategy'],
        'carrier': o['carrier'],
        'status': o['status'],
        'wave_id': o.get('wave_id'),
        'provisional_carton_count': o.get('provisional_carton_count'),
        'final_carton_count': o.get('final_carton_count'),
        'shipping_label_id': o.get('shipping_label_id'),
        'tracking_number': o.get('tracking_number'),
        'pick_tasks': pick_tasks,
    }

def ser_cycle_count(cc):
    return {
        'id': cc['id'],
        'created_at': dt_to_iso(cc['created_at']),
        'updated_at': dt_to_iso(cc['updated_at']),
        'version': cc['version'],
        'warehouse_id': cc['warehouse_id'],
        'bin_id': cc['bin_id'],
        'lot_id': cc['lot_id'],
        'book_qty': cc.get('book_qty'),
        'counted_qty': cc.get('counted_qty'),
        'variance_units': cc.get('variance_units'),
        'variance_value_cents': cc.get('variance_value_cents'),
        'status': cc['status'],
        'scheduled_at': dt_to_iso(cc.get('scheduled_at')),
        'submitted_by_user_id': cc.get('submitted_by_user_id'),
        'approved_by_user_id': cc.get('approved_by_user_id'),
        'approved_at': dt_to_iso(cc.get('approved_at')),
    }
