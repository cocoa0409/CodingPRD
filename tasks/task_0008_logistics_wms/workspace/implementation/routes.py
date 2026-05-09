"""All API endpoints for the Logistics WMS."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from core import (
    ApiError, store, lock,
    success, error_response, get_request_id,
    authenticate, require_roles,
    get_json_body, required_str, required_int, optional_int,
    required_enum, optional_enum,
    occ_check, paginate,
    get_warehouse, get_bin, get_lot, get_inbound_shipment,
    get_wave, get_order, get_pick_task, get_cycle_count,
    common_fields, bump,
    parse_iso, dt_to_iso, now_dt, gen_id,
    round_half_up_decimals, round_half_up_int, euclidean,
    inspection_sample_size, recompute_bin_capacity,
    recompute_warehouse_metrics, add_abnormal_event,
    select_putaway_bin, select_pick_inventory,
    carton_count_provisional, carton_count_final,
    assign_wave_path, near_expiry_scan, propagate_pick_terminal,
    ser_warehouse, ser_bin, ser_lot, ser_inbound_shipment,
    ser_inventory, ser_wave, ser_order, ser_pick_task,
    ser_cycle_count, EPOCH,
)

bp = Blueprint('wms', __name__)

# ============================================================================
# Warehouse
# ============================================================================

@bp.route('/warehouses', methods=['POST'])
@require_roles('WarehouseManager')
def create_warehouse():
    body = get_json_body()
    name = required_str(body, 'name')
    dx = required_int(body, 'dock_position_x', allow_negative=True)
    dy = required_int(body, 'dock_position_y', allow_negative=True)
    strategy = optional_enum(body, 'putaway_strategy',
                             {'DISTANCE_OPTIMIZED', 'CAPACITY_OPTIMIZED'},
                             'DISTANCE_OPTIMIZED')
    with lock:
        w = {**common_fields(),
             'name': name,
             'dock_position_x': dx,
             'dock_position_y': dy,
             'putaway_strategy': strategy,
             'ops_run_index': 0,
             'clock_now': EPOCH,
             'shrinkage_value_30d_cents': 0,
             'abnormal_event_count_24h': 0,
             'recall_count_open': 0,
             'risk_score': 0.0,
             'posture': 'OPEN'}
        store.warehouses[w['id']] = w
        return success(ser_warehouse(w), status=201)

@bp.route('/warehouses/<warehouse_id>', methods=['GET'])
@require_roles('WarehouseStaff', 'Auditor', 'WarehouseManager')
def fetch_warehouse(warehouse_id):
    with lock:
        w = get_warehouse(warehouse_id)
        return success(ser_warehouse(w))

@bp.route('/warehouses/<warehouse_id>/run_ops', methods=['POST'])
@require_roles('WarehouseManager')
def run_ops(warehouse_id):
    body = get_json_body()
    with lock:
        w = get_warehouse(warehouse_id)
        occ_check(w, body)
        w['ops_run_index'] += 1
        bump(w)
        # near-expiry scan
        near_expiry_scan(w)
        # close any inbound shipment whose lines are all PUTAWAY or all QUARANTINED
        for s in list(store.inbound_shipments.values()):
            if s['warehouse_id'] != w['id']:
                continue
            if s['status'] not in {'PUTAWAY', 'QUARANTINED'}:
                continue
            lines = [il for il in store.inbound_lines.values()
                     if il['inbound_shipment_id'] == s['id']]
            if not lines:
                continue
            if s['status'] == 'PUTAWAY' and all(l['status'] == 'PUTAWAY' for l in lines):
                s['status'] = 'CLOSED'
                bump(s)
            elif s['status'] == 'QUARANTINED' and all(l['status'] == 'QUARANTINED' for l in lines):
                s['status'] = 'CLOSED'
                bump(s)
        recompute_warehouse_metrics(w)
        return success(ser_warehouse(w))

# ============================================================================
# Bin
# ============================================================================

@bp.route('/warehouses/<warehouse_id>/bins', methods=['POST'])
@require_roles('WarehouseManager')
def create_bin(warehouse_id):
    body = get_json_body()
    with lock:
        w = get_warehouse(warehouse_id)
        bin_code = required_str(body, 'bin_code')
        zone = required_enum(body, 'zone', {'AMBIENT', 'COLD', 'HAZMAT', 'RETURNS'})
        px = required_int(body, 'position_x', allow_negative=True)
        py = required_int(body, 'position_y', allow_negative=True)
        cap_v = required_int(body, 'capacity_volume_cm3', allow_zero=False)
        cap_w = required_int(body, 'capacity_weight_g', allow_zero=False)
        # uniqueness within warehouse
        for existing in store.bins.values():
            if existing['warehouse_id'] == warehouse_id and existing['bin_code'] == bin_code:
                raise ApiError('ERR_INVALID_INPUT', 'bin_code already exists', 422)
        dist = euclidean(px, py, w['dock_position_x'], w['dock_position_y'])
        dist = float(round_half_up_decimals(dist, 4))
        b = {**common_fields(),
             'warehouse_id': warehouse_id,
             'bin_code': bin_code,
             'zone': zone,
             'position_x': px,
             'position_y': py,
             'capacity_volume_cm3': cap_v,
             'capacity_weight_g': cap_w,
             'used_volume_cm3': 0,
             'used_weight_g': 0,
             'status': 'ACTIVE',
             'frozen_by_cycle_count_id': None,
             'distance_from_dock': dist}
        store.bins[b['id']] = b
        return success(ser_bin(b), status=201)

@bp.route('/warehouses/<warehouse_id>/bins/<bin_id>', methods=['GET'])
@require_roles('WarehouseStaff', 'Auditor', 'WarehouseManager')
def fetch_bin(warehouse_id, bin_id):
    with lock:
        b = get_bin(warehouse_id, bin_id)
        return success(ser_bin(b))

@bp.route('/warehouses/<warehouse_id>/bins', methods=['GET'])
@require_roles('WarehouseStaff', 'Auditor', 'WarehouseManager')
def list_bins(warehouse_id):
    with lock:
        get_warehouse(warehouse_id)
        items = [b for b in store.bins.values() if b['warehouse_id'] == warehouse_id]
        zone_filter = request.args.get('zone')
        status_filter = request.args.get('status')
        if zone_filter:
            items = [b for b in items if b['zone'] == zone_filter]
        if status_filter:
            items = [b for b in items if b['status'] == status_filter]
        page, pagination = paginate(items)
        return success([ser_bin(b) for b in page], response_type='array',
                       pagination=pagination)

# ============================================================================
# Lot
# ============================================================================

@bp.route('/warehouses/<warehouse_id>/lots', methods=['POST'])
@require_roles('WarehouseManager')
def create_lot(warehouse_id):
    body = get_json_body()
    with lock:
        get_warehouse(warehouse_id)
        lot_code = required_str(body, 'lot_code')
        sku = required_str(body, 'sku')
        category = required_enum(body, 'category', {'AMBIENT', 'COLD', 'HAZMAT', 'RETURNS'})
        uw = required_int(body, 'unit_weight_g', allow_zero=False)
        uv = required_int(body, 'unit_volume_cm3', allow_zero=False)
        uvc = required_int(body, 'unit_value_cents')
        mfg = parse_iso(required_str(body, 'manufacture_date'))
        exp = parse_iso(required_str(body, 'expiry_date'))
        supplier_ref = required_str(body, 'supplier_lot_ref')
        for existing in store.lots.values():
            if existing['warehouse_id'] == warehouse_id and existing['lot_code'] == lot_code:
                raise ApiError('ERR_INVALID_INPUT', 'lot_code already exists', 422)
        l = {**common_fields(),
             'warehouse_id': warehouse_id,
             'lot_code': lot_code,
             'sku': sku,
             'category': category,
             'unit_weight_g': uw,
             'unit_volume_cm3': uv,
             'unit_value_cents': uvc,
             'manufacture_date': mfg,
             'expiry_date': exp,
             'received_at': None,
             'supplier_lot_ref': supplier_ref,
             'status': 'ACTIVE',
             'recalled_at': None,
             'recall_reason': None}
        store.lots[l['id']] = l
        return success(ser_lot(l), status=201)

@bp.route('/warehouses/<warehouse_id>/lots/<lot_id>', methods=['GET'])
@require_roles('WarehouseStaff', 'Auditor', 'WarehouseManager')
def fetch_lot(warehouse_id, lot_id):
    with lock:
        l = get_lot(warehouse_id, lot_id)
        return success(ser_lot(l))

@bp.route('/warehouses/<warehouse_id>/lots/<lot_id>/recall', methods=['POST'])
@require_roles('WarehouseManager')
def recall_lot(warehouse_id, lot_id):
    body = get_json_body()
    with lock:
        w = get_warehouse(warehouse_id)
        l = get_lot(warehouse_id, lot_id)
        if l['status'] not in {'ACTIVE', 'NEAR_EXPIRY'}:
            raise ApiError('ERR_INVALID_STATE',
                           f'Cannot recall lot in status {l["status"]}', 409)
        occ_check(l, body)
        recall_reason = required_enum(body, 'recall_reason',
                                       {'SUPPLIER_RECALL', 'SAFETY_ISSUE', 'EXPIRY_BATCH'})
        l['status'] = 'RECALLED'
        l['recalled_at'] = w['clock_now']
        l['recall_reason'] = recall_reason
        bump(l)
        # cascade: CREATED|PICKING PickTasks → FAILED
        for pt in list(store.pick_tasks.values()):
            if pt['lot_id'] == l['id'] and pt['status'] in {'CREATED', 'PICKING'}:
                pt['status'] = 'FAILED'
                bump(pt)
                inv = store.inventory.get(pt['inventory_id'])
                if inv:
                    inv['reserved_units'] = max(0, inv['reserved_units'] - pt['planned_units'])
                    bump(inv)
                propagate_pick_terminal(w, pt)
        recompute_warehouse_metrics(w)
        bump(w)
        return success(ser_lot(l))

@bp.route('/warehouses/<warehouse_id>/lots/<lot_id>/dispose', methods=['POST'])
@require_roles('WarehouseStaff')
def dispose_lot(warehouse_id, lot_id):
    body = get_json_body()
    with lock:
        w = get_warehouse(warehouse_id)
        l = get_lot(warehouse_id, lot_id)
        if l['status'] not in {'EXPIRED', 'RECALLED', 'QUARANTINED'}:
            raise ApiError('ERR_INVALID_STATE',
                           f'Cannot dispose lot in status {l["status"]}', 409)
        occ_check(l, body)
        # check no PickTask in CREATED|PICKING references this lot
        for pt in store.pick_tasks.values():
            if pt['lot_id'] == l['id'] and pt['status'] in {'CREATED', 'PICKING'}:
                raise ApiError('ERR_LOT_HAS_OPEN_PICKS',
                               'Lot has open pick tasks', 409)
        prev_status = l['status']
        l['status'] = 'DISPOSED'
        bump(l)
        # zero inventory; recompute affected bins
        affected_bin_ids = set()
        for inv in store.inventory.values():
            if inv['lot_id'] == l['id']:
                if inv['qty_units'] != 0:
                    inv['qty_units'] = 0
                    bump(inv)
                affected_bin_ids.add(inv['bin_id'])
        for bid in affected_bin_ids:
            b = store.bins.get(bid)
            if b:
                recompute_bin_capacity(b)
                bump(b)
        if prev_status == 'RECALLED':
            recompute_warehouse_metrics(w)
            bump(w)
        return success(ser_lot(l))

# ============================================================================
# InboundShipment
# ============================================================================

@bp.route('/warehouses/<warehouse_id>/inbound_shipments', methods=['POST'])
@require_roles('WarehouseStaff')
def create_inbound_shipment(warehouse_id):
    body = get_json_body()
    with lock:
        get_warehouse(warehouse_id)
        asn_number = required_str(body, 'asn_number')
        supplier_name = required_str(body, 'supplier_name')
        declared_total = required_int(body, 'declared_total_units')
        lines = body.get('lines')
        if not isinstance(lines, list) or len(lines) == 0:
            raise ApiError('ERR_INVALID_INPUT', 'lines must be non-empty array', 422)
        for existing in store.inbound_shipments.values():
            if (existing['warehouse_id'] == warehouse_id
                    and existing['asn_number'] == asn_number):
                raise ApiError('ERR_INVALID_INPUT', 'asn_number already exists', 422)
        # body FK existence: lot_ids must exist in warehouse
        for ln in lines:
            if not isinstance(ln, dict):
                raise ApiError('ERR_INVALID_INPUT', 'each line must be object', 422)
            lot_id = ln.get('lot_id')
            if not lot_id or not isinstance(lot_id, str):
                raise ApiError('ERR_INVALID_INPUT', 'line.lot_id required', 422)
            lot = store.lots.get(lot_id)
            if not lot or lot['warehouse_id'] != warehouse_id:
                raise ApiError('ERR_NOT_FOUND', f'Lot {lot_id} not found', 404)
            du = ln.get('declared_units')
            if isinstance(du, bool) or not isinstance(du, int) or du < 0:
                raise ApiError('ERR_INVALID_INPUT', 'declared_units invalid', 422)
        s = {**common_fields(),
             'warehouse_id': warehouse_id,
             'asn_number': asn_number,
             'supplier_name': supplier_name,
             'declared_total_units': declared_total,
             'inspection_sample_size': None,
             'inspection_defect_count': None,
             'defect_rate': None,
             'status': 'ASN_RECEIVED'}
        store.inbound_shipments[s['id']] = s
        for ln in lines:
            il = {**common_fields(),
                  'inbound_shipment_id': s['id'],
                  'lot_id': ln['lot_id'],
                  'declared_units': ln['declared_units'],
                  'received_units': None,
                  'bin_id': None,
                  'status': 'PENDING_INSPECTION'}
            store.inbound_lines[il['id']] = il
        return success(ser_inbound_shipment(s), status=201)

@bp.route('/warehouses/<warehouse_id>/inbound_shipments/<shipment_id>', methods=['GET'])
@require_roles('WarehouseStaff', 'Auditor', 'WarehouseManager')
def fetch_inbound_shipment(warehouse_id, shipment_id):
    with lock:
        s = get_inbound_shipment(warehouse_id, shipment_id)
        return success(ser_inbound_shipment(s))

@bp.route('/warehouses/<warehouse_id>/inbound_shipments/<shipment_id>/start_inspection',
          methods=['POST'])
@require_roles('WarehouseStaff')
def start_inspection(warehouse_id, shipment_id):
    body = get_json_body()
    with lock:
        get_warehouse(warehouse_id)
        s = get_inbound_shipment(warehouse_id, shipment_id)
        if s['status'] != 'ASN_RECEIVED':
            raise ApiError('ERR_INVALID_STATE',
                           f'Cannot start inspection from {s["status"]}', 409)
        occ_check(s, body)
        # ASN match
        lines = [il for il in store.inbound_lines.values()
                 if il['inbound_shipment_id'] == s['id']]
        total = sum(il['declared_units'] for il in lines)
        if total != s['declared_total_units']:
            raise ApiError('ERR_ASN_MISMATCH',
                           'Sum of declared_units does not match declared_total_units', 409)
        # all lots must be ACTIVE
        for il in lines:
            lot = store.lots.get(il['lot_id'])
            if not lot or lot['status'] != 'ACTIVE':
                raise ApiError('ERR_LOT_NOT_ACTIVE',
                               f'Lot {il["lot_id"]} is not ACTIVE', 409)
        s['inspection_sample_size'] = inspection_sample_size(s['declared_total_units'])
        s['status'] = 'INSPECTING'
        bump(s)
        return success(ser_inbound_shipment(s))

@bp.route('/warehouses/<warehouse_id>/inbound_shipments/<shipment_id>/complete_inspection',
          methods=['POST'])
@require_roles('WarehouseStaff')
def complete_inspection(warehouse_id, shipment_id):
    body = get_json_body()
    with lock:
        w = get_warehouse(warehouse_id)
        s = get_inbound_shipment(warehouse_id, shipment_id)
        if s['status'] != 'INSPECTING':
            raise ApiError('ERR_INVALID_STATE',
                           f'Cannot complete inspection from {s["status"]}', 409)
        occ_check(s, body)
        defect_count = body.get('inspection_defect_count')
        if isinstance(defect_count, bool) or not isinstance(defect_count, int):
            raise ApiError('ERR_INVALID_INPUT', 'inspection_defect_count required int', 422)
        sample = s['inspection_sample_size']
        if defect_count < 0 or defect_count > sample:
            raise ApiError('ERR_INVALID_INPUT',
                           'inspection_defect_count out of range', 422)
        # update received_units per line
        lines_input = body.get('lines') or []
        if not isinstance(lines_input, list):
            raise ApiError('ERR_INVALID_INPUT', 'lines must be array', 422)
        rec_map = {}
        for ln in lines_input:
            if not isinstance(ln, dict):
                raise ApiError('ERR_INVALID_INPUT', 'each line must be object', 422)
            lot_id = ln.get('lot_id')
            ru = ln.get('received_units')
            if isinstance(ru, bool) or not isinstance(ru, int) or ru < 0:
                raise ApiError('ERR_INVALID_INPUT', 'received_units invalid', 422)
            rec_map[lot_id] = ru
        all_lines = [il for il in store.inbound_lines.values()
                     if il['inbound_shipment_id'] == s['id']]
        for il in all_lines:
            if il['lot_id'] in rec_map:
                il['received_units'] = rec_map[il['lot_id']]
                bump(il)
        defect_rate = round_half_up_decimals(
            Decimal(defect_count) / Decimal(sample), 4)
        s['inspection_defect_count'] = defect_count
        s['defect_rate'] = float(defect_rate)
        if defect_rate <= Decimal('0.025'):
            s['status'] = 'PASSED'
            for il in all_lines:
                il['status'] = 'INSPECTED_PASS'
                bump(il)
        else:
            s['status'] = 'FAILED'
            for il in all_lines:
                il['status'] = 'INSPECTED_FAIL'
                bump(il)
            add_abnormal_event(w)
            recompute_warehouse_metrics(w)
            bump(w)
        bump(s)
        return success(ser_inbound_shipment(s))

@bp.route('/warehouses/<warehouse_id>/inbound_shipments/<shipment_id>/rework',
          methods=['POST'])
@require_roles('WarehouseStaff')
def rework_inspection(warehouse_id, shipment_id):
    body = get_json_body()
    with lock:
        get_warehouse(warehouse_id)
        s = get_inbound_shipment(warehouse_id, shipment_id)
        if s['status'] != 'FAILED':
            raise ApiError('ERR_INVALID_STATE',
                           f'Cannot rework from {s["status"]}', 409)
        occ_check(s, body)
        s['status'] = 'INSPECTING'
        s['inspection_defect_count'] = None
        s['defect_rate'] = None
        bump(s)
        for il in store.inbound_lines.values():
            if il['inbound_shipment_id'] == s['id']:
                if il['status'] == 'INSPECTED_FAIL':
                    il['status'] = 'PENDING_INSPECTION'
                    bump(il)
        return success(ser_inbound_shipment(s))

@bp.route('/warehouses/<warehouse_id>/inbound_shipments/<shipment_id>/putaway',
          methods=['POST'])
@require_roles('WarehouseStaff')
def putaway_shipment(warehouse_id, shipment_id):
    body = get_json_body()
    with lock:
        w = get_warehouse(warehouse_id)
        s = get_inbound_shipment(warehouse_id, shipment_id)
        if s['status'] != 'PASSED':
            raise ApiError('ERR_INVALID_STATE',
                           f'Cannot putaway from {s["status"]}', 409)
        occ_check(s, body)
        lines = [il for il in store.inbound_lines.values()
                 if il['inbound_shipment_id'] == s['id']]
        # Each line's received_units > 0 — else ERR_NO_BIN_AVAILABLE
        for il in lines:
            if not il.get('received_units') or il['received_units'] <= 0:
                raise ApiError('ERR_NO_BIN_AVAILABLE',
                               'Line has no positive received_units', 409)
        # Pre-validate zone for each line BEFORE selecting bins (priority 8 ZONE_MISMATCH)
        # Per PRD priority: zone check (8) precedes bin freeze (10) and bin capacity (12).
        # We surface ERR_ZONE_MISMATCH if there's literally no bin in the lot's zone.
        for il in lines:
            lot = store.lots.get(il['lot_id'])
            zone_bins = [b for b in store.bins.values()
                         if b['warehouse_id'] == w['id']
                         and b['zone'] == lot['category']]
            if not zone_bins:
                raise ApiError('ERR_ZONE_MISMATCH',
                               f'No bin with zone {lot["category"]}', 409)
            # bin freeze priority — if all matching-zone bins are FROZEN, surface ERR_BIN_FROZEN
            non_frozen = [b for b in zone_bins if b['status'] == 'ACTIVE']
            if not non_frozen:
                raise ApiError('ERR_BIN_FROZEN',
                               f'All zone bins frozen for lot {il["lot_id"]}', 409)
        # Now select bins
        # Pre-snapshot of bin capacities so multi-line putaway uses incremental usage
        chosen = []
        affected_bins = set()
        for il in lines:
            lot = store.lots.get(il['lot_id'])
            b = select_putaway_bin(w, lot, il['received_units'])
            chosen.append((il, lot, b))
            # tentatively update bin's used capacity for next iteration
            inv = next((iv for iv in store.inventory.values()
                        if iv['warehouse_id'] == w['id']
                        and iv['bin_id'] == b['id']
                        and iv['lot_id'] == lot['id']), None)
            if inv:
                inv['qty_units'] += il['received_units']
                bump(inv)
            else:
                inv = {**common_fields(),
                       'warehouse_id': w['id'],
                       'bin_id': b['id'],
                       'lot_id': lot['id'],
                       'qty_units': il['received_units'],
                       'reserved_units': 0}
                store.inventory[inv['id']] = inv
            il['bin_id'] = b['id']
            il['status'] = 'PUTAWAY'
            bump(il)
            affected_bins.add(b['id'])
            recompute_bin_capacity(b)
            bump(b)
            if lot.get('received_at') is None:
                lot['received_at'] = w['clock_now']
                bump(lot)
        s['status'] = 'PUTAWAY'
        bump(s)
        return success(ser_inbound_shipment(s))

@bp.route('/warehouses/<warehouse_id>/inbound_shipments/<shipment_id>/quarantine',
          methods=['POST'])
@require_roles('WarehouseStaff')
def quarantine_shipment(warehouse_id, shipment_id):
    body = get_json_body()
    with lock:
        w = get_warehouse(warehouse_id)
        s = get_inbound_shipment(warehouse_id, shipment_id)
        if s['status'] != 'FAILED':
            raise ApiError('ERR_INVALID_STATE',
                           f'Cannot quarantine from {s["status"]}', 409)
        occ_check(s, body)
        lines = [il for il in store.inbound_lines.values()
                 if il['inbound_shipment_id'] == s['id']]
        for il in lines:
            if not il.get('received_units') or il['received_units'] <= 0:
                raise ApiError('ERR_NO_BIN_AVAILABLE',
                               'Line has no positive received_units', 409)
        # quarantine bins must be RETURNS-zone
        for il in lines:
            zone_bins = [b for b in store.bins.values()
                         if b['warehouse_id'] == w['id']
                         and b['zone'] == 'RETURNS']
            if not zone_bins:
                raise ApiError('ERR_ZONE_MISMATCH',
                               'No RETURNS-zone bin available', 409)
        for il in lines:
            lot = store.lots.get(il['lot_id'])
            b = select_putaway_bin(w, lot, il['received_units'], returns_only=True)
            inv = next((iv for iv in store.inventory.values()
                        if iv['warehouse_id'] == w['id']
                        and iv['bin_id'] == b['id']
                        and iv['lot_id'] == lot['id']), None)
            if inv:
                inv['qty_units'] += il['received_units']
                bump(inv)
            else:
                inv = {**common_fields(),
                       'warehouse_id': w['id'],
                       'bin_id': b['id'],
                       'lot_id': lot['id'],
                       'qty_units': il['received_units'],
                       'reserved_units': 0}
                store.inventory[inv['id']] = inv
            il['bin_id'] = b['id']
            il['status'] = 'QUARANTINED'
            bump(il)
            recompute_bin_capacity(b)
            bump(b)
            if lot['status'] == 'ACTIVE':
                lot['status'] = 'QUARANTINED'
                bump(lot)
        s['status'] = 'QUARANTINED'
        bump(s)
        return success(ser_inbound_shipment(s))

# ============================================================================
# Inventory
# ============================================================================

@bp.route('/warehouses/<warehouse_id>/inventory', methods=['GET'])
@require_roles('WarehouseStaff', 'Auditor', 'WarehouseManager')
def list_inventory(warehouse_id):
    with lock:
        get_warehouse(warehouse_id)
        items = [inv for inv in store.inventory.values()
                 if inv['warehouse_id'] == warehouse_id]
        bin_id = request.args.get('bin_id')
        lot_id = request.args.get('lot_id')
        sku = request.args.get('sku')
        if bin_id:
            items = [i for i in items if i['bin_id'] == bin_id]
        if lot_id:
            items = [i for i in items if i['lot_id'] == lot_id]
        if sku:
            items = [i for i in items
                     if (store.lots.get(i['lot_id']) or {}).get('sku') == sku]
        page, pagination = paginate(items)
        return success([ser_inventory(i) for i in page],
                       response_type='array', pagination=pagination)

# ============================================================================
# Order
# ============================================================================

@bp.route('/warehouses/<warehouse_id>/orders', methods=['POST'])
@require_roles('WarehouseStaff')
def create_order(warehouse_id):
    body = get_json_body()
    with lock:
        get_warehouse(warehouse_id)
        order_number = required_str(body, 'order_number')
        customer_name = required_str(body, 'customer_name')
        requested_lines = body.get('requested_lines')
        if (not isinstance(requested_lines, list) or len(requested_lines) == 0):
            raise ApiError('ERR_INVALID_INPUT',
                           'requested_lines must be non-empty array', 422)
        for ln in requested_lines:
            if not isinstance(ln, dict):
                raise ApiError('ERR_INVALID_INPUT', 'each line must be object', 422)
            sku = ln.get('sku')
            qu = ln.get('qty_units')
            if not sku or not isinstance(sku, str):
                raise ApiError('ERR_INVALID_INPUT', 'line.sku required', 422)
            if isinstance(qu, bool) or not isinstance(qu, int) or qu < 1:
                raise ApiError('ERR_INVALID_INPUT', 'line.qty_units must be positive', 422)
        pick_strategy = optional_enum(body, 'pick_strategy', {'FEFO', 'FIFO'}, 'FEFO')
        carrier = required_enum(body, 'carrier', {'UPS', 'FEDEX', 'USPS'})
        for existing in store.orders.values():
            if (existing['warehouse_id'] == warehouse_id
                    and existing['order_number'] == order_number):
                raise ApiError('ERR_INVALID_INPUT', 'order_number already exists', 422)
        o = {**common_fields(),
             'warehouse_id': warehouse_id,
             'order_number': order_number,
             'customer_name': customer_name,
             'requested_lines': requested_lines,
             'pick_strategy': pick_strategy,
             'carrier': carrier,
             'status': 'CREATED',
             'wave_id': None,
             'provisional_carton_count': None,
             'final_carton_count': None,
             'shipping_label_id': None,
             'tracking_number': None}
        store.orders[o['id']] = o
        return success(ser_order(o), status=201)

@bp.route('/warehouses/<warehouse_id>/orders/<order_id>', methods=['GET'])
@require_roles('WarehouseStaff', 'Auditor', 'WarehouseManager')
def fetch_order(warehouse_id, order_id):
    with lock:
        o = get_order(warehouse_id, order_id)
        return success(ser_order(o))

@bp.route('/warehouses/<warehouse_id>/orders/<order_id>/allocate', methods=['POST'])
@require_roles('WarehouseStaff')
def allocate_order(warehouse_id, order_id):
    body = get_json_body()
    with lock:
        w = get_warehouse(warehouse_id)
        o = get_order(warehouse_id, order_id)
        if o['status'] != 'CREATED':
            raise ApiError('ERR_INVALID_STATE',
                           f'Cannot allocate order in status {o["status"]}', 409)
        occ_check(o, body)
        recompute_warehouse_metrics(w)
        # Inventory sufficiency (priority 13) is evaluated BEFORE posture gate (priority 14).
        # Check inventory sufficiency for each line first (no side effects yet)
        plan = []  # list of (sku, qty, picks_list)
        # we must atomically reserve, so simulate without committing
        sim_reserved = {}  # inventory_id -> already-reserved-in-this-allocate
        for line in o['requested_lines']:
            sku = line['sku']
            qty = line['qty_units']
            remaining = qty
            candidates = []
            for inv in store.inventory.values():
                if inv['warehouse_id'] != w['id']:
                    continue
                lot = store.lots.get(inv['lot_id'])
                if not lot or lot['sku'] != sku:
                    continue
                if lot['status'] not in {'ACTIVE', 'NEAR_EXPIRY'}:
                    continue
                avail = inv['qty_units'] - inv['reserved_units'] - sim_reserved.get(inv['id'], 0)
                if avail <= 0:
                    continue
                candidates.append((inv, lot, avail))
            if o['pick_strategy'] == 'FIFO':
                candidates.sort(key=lambda t: (
                    t[1].get('received_at') or now_dt(),
                    t[1]['lot_code'],
                ))
            else:
                candidates.sort(key=lambda t: (t[1]['expiry_date'], t[1]['lot_code']))
            picks = []
            for inv, lot, avail in candidates:
                if remaining == 0:
                    break
                take = min(remaining, avail)
                picks.append((inv, lot, take))
                sim_reserved[inv['id']] = sim_reserved.get(inv['id'], 0) + take
                remaining -= take
            if remaining > 0:
                raise ApiError('ERR_INSUFFICIENT_INVENTORY',
                               f'Insufficient inventory for sku {sku}', 409)
            plan.append((sku, qty, picks))
        # Posture gate (priority 14) — evaluated AFTER inventory sufficiency.
        if w['posture'] == 'FROZEN':
            raise ApiError('ERR_POSTURE_FROZEN',
                           'Warehouse posture is FROZEN', 409)
        # Commit: create pick tasks, increment reservations
        for sku, qty, picks in plan:
            for inv, lot, take in picks:
                inv['reserved_units'] += take
                bump(inv)
                pt = {**common_fields(),
                      'order_id': o['id'],
                      'wave_id': None,
                      'bin_id': inv['bin_id'],
                      'lot_id': lot['id'],
                      'inventory_id': inv['id'],
                      'planned_units': take,
                      'picked_units': 0,
                      'sequence': None,
                      'status': 'CREATED'}
                store.pick_tasks[pt['id']] = pt
        o['status'] = 'ALLOCATED'
        o['provisional_carton_count'] = carton_count_provisional(w, o['requested_lines'])
        bump(o)
        return success(ser_order(o))

@bp.route('/warehouses/<warehouse_id>/orders/<order_id>/cancel', methods=['POST'])
@require_roles('WarehouseStaff')
def cancel_order(warehouse_id, order_id):
    body = get_json_body()
    with lock:
        get_warehouse(warehouse_id)
        o = get_order(warehouse_id, order_id)
        if o['status'] in {'SHIPPED', 'CANCELLED', 'PACKED', 'PICKED'}:
            raise ApiError('ERR_INVALID_STATE',
                           f'Cannot cancel order in status {o["status"]}', 409)
        occ_check(o, body)
        if o['status'] == 'PICKING':
            for pt in store.pick_tasks.values():
                if pt['order_id'] == o['id'] and pt['status'] == 'PICKED':
                    raise ApiError('ERR_INVALID_STATE',
                                   'Cannot cancel order with already-PICKED tasks', 409)
        # Cascade cancellation
        for pt in list(store.pick_tasks.values()):
            if pt['order_id'] != o['id']:
                continue
            if pt['status'] in {'CREATED', 'PICKING'}:
                # release reservations
                inv = store.inventory.get(pt['inventory_id'])
                if inv:
                    # release based on current planned vs picked
                    release = pt['planned_units']
                    inv['reserved_units'] = max(0, inv['reserved_units'] - release)
                    bump(inv)
                pt['status'] = 'CANCELLED'
                bump(pt)
        o['status'] = 'CANCELLED'
        bump(o)
        return success(ser_order(o))

@bp.route('/warehouses/<warehouse_id>/orders/<order_id>/replan', methods=['POST'])
@require_roles('WarehouseStaff')
def replan_order(warehouse_id, order_id):
    body = get_json_body()
    with lock:
        w = get_warehouse(warehouse_id)
        o = get_order(warehouse_id, order_id)
        if o['status'] != 'SHORT_PICKED':
            raise ApiError('ERR_INVALID_STATE',
                           f'Cannot replan order in status {o["status"]}', 409)
        occ_check(o, body)
        recompute_warehouse_metrics(w)
        # Inventory sufficiency (priority 13) is evaluated BEFORE posture gate (priority 14).
        # compute residual per requested line by sku
        residuals = []
        for line in o['requested_lines']:
            sku = line['sku']
            qty = line['qty_units']
            picked_for_sku = 0
            for pt in store.pick_tasks.values():
                if pt['order_id'] != o['id']:
                    continue
                lot = store.lots.get(pt['lot_id'])
                if not lot or lot['sku'] != sku:
                    continue
                if pt['status'] in {'PICKED', 'SHORT_PICKED'}:
                    picked_for_sku += pt['picked_units']
            residual = max(0, qty - picked_for_sku)
            if residual > 0:
                residuals.append({'sku': sku, 'qty_units': residual})
        # Validate inventory sufficiency
        sim_reserved = {}
        plan = []
        for line in residuals:
            sku = line['sku']
            qty = line['qty_units']
            remaining = qty
            candidates = []
            for inv in store.inventory.values():
                if inv['warehouse_id'] != w['id']:
                    continue
                lot = store.lots.get(inv['lot_id'])
                if not lot or lot['sku'] != sku:
                    continue
                if lot['status'] not in {'ACTIVE', 'NEAR_EXPIRY'}:
                    continue
                avail = inv['qty_units'] - inv['reserved_units'] - sim_reserved.get(inv['id'], 0)
                if avail <= 0:
                    continue
                candidates.append((inv, lot, avail))
            if o['pick_strategy'] == 'FIFO':
                candidates.sort(key=lambda t: (
                    t[1].get('received_at') or now_dt(), t[1]['lot_code']))
            else:
                candidates.sort(key=lambda t: (t[1]['expiry_date'], t[1]['lot_code']))
            picks = []
            for inv, lot, avail in candidates:
                if remaining == 0:
                    break
                take = min(remaining, avail)
                picks.append((inv, lot, take))
                sim_reserved[inv['id']] = sim_reserved.get(inv['id'], 0) + take
                remaining -= take
            if remaining > 0:
                raise ApiError('ERR_INSUFFICIENT_INVENTORY',
                               f'Insufficient inventory for sku {sku}', 409)
            plan.append((sku, qty, picks))
        # Posture gate (priority 14) — evaluated AFTER inventory sufficiency.
        if w['posture'] == 'FROZEN':
            raise ApiError('ERR_POSTURE_FROZEN',
                           'Warehouse posture is FROZEN', 409)
        # commit
        for sku, qty, picks in plan:
            for inv, lot, take in picks:
                inv['reserved_units'] += take
                bump(inv)
                pt = {**common_fields(),
                      'order_id': o['id'],
                      'wave_id': None,
                      'bin_id': inv['bin_id'],
                      'lot_id': lot['id'],
                      'inventory_id': inv['id'],
                      'planned_units': take,
                      'picked_units': 0,
                      'sequence': None,
                      'status': 'CREATED'}
                store.pick_tasks[pt['id']] = pt
        o['status'] = 'ALLOCATED'
        o['provisional_carton_count'] = carton_count_provisional(w, o['requested_lines'])
        bump(o)
        return success(ser_order(o))

@bp.route('/warehouses/<warehouse_id>/orders/<order_id>/pack', methods=['POST'])
@require_roles('WarehouseStaff')
def pack_order(warehouse_id, order_id):
    body = get_json_body()
    with lock:
        get_warehouse(warehouse_id)
        o = get_order(warehouse_id, order_id)
        if o['status'] not in {'PICKED', 'SHORT_PICKED'}:
            raise ApiError('ERR_INVALID_STATE',
                           f'Cannot pack order in status {o["status"]}', 409)
        occ_check(o, body)
        pts = [pt for pt in store.pick_tasks.values() if pt['order_id'] == o['id']]
        if o['status'] == 'PICKED':
            if any(pt['status'] in {'SHORT_PICKED', 'FAILED'} for pt in pts):
                raise ApiError('ERR_INVALID_STATE',
                               'Cannot pack order with SHORT_PICKED or FAILED tasks', 409)
        else:  # SHORT_PICKED
            allow_partial = body.get('allow_partial')
            if allow_partial is not True:
                raise ApiError('ERR_INVALID_STATE',
                               'allow_partial must be true to pack SHORT_PICKED', 409)
            if not any(pt['status'] == 'PICKED' for pt in pts):
                raise ApiError('ERR_INVALID_STATE',
                               'No PICKED pick task to pack', 409)
        o['final_carton_count'] = carton_count_final(o)
        o['status'] = 'PACKED'
        bump(o)
        return success(ser_order(o))

@bp.route('/warehouses/<warehouse_id>/orders/<order_id>/ship', methods=['POST'])
@require_roles('WarehouseStaff')
def ship_order(warehouse_id, order_id):
    body = get_json_body()
    with lock:
        w = get_warehouse(warehouse_id)
        o = get_order(warehouse_id, order_id)
        if o['status'] != 'PACKED':
            raise ApiError('ERR_INVALID_STATE',
                           f'Cannot ship order in status {o["status"]}', 409)
        occ_check(o, body)
        pts = [pt for pt in store.pick_tasks.values() if pt['order_id'] == o['id']]
        for pt in pts:
            if pt['status'] != 'PICKED':
                continue
            lot = store.lots.get(pt['lot_id'])
            if lot and lot['status'] in {'RECALLED', 'EXPIRED', 'QUARANTINED'}:
                raise ApiError('ERR_LOT_NOT_SHIPPABLE',
                               f'Lot {lot["id"]} not shippable', 409)
        # mint label / tracking
        o['shipping_label_id'] = 'lbl_' + gen_id()
        store.tracking_counter += 1
        prefix = {'UPS': '1Z', 'FEDEX': 'FX', 'USPS': 'US'}[o['carrier']]
        o['tracking_number'] = f'{prefix}-{store.tracking_counter:09d}'
        # debit inventory
        affected_bins = set()
        for pt in pts:
            if pt['status'] != 'PICKED':
                continue
            inv = store.inventory.get(pt['inventory_id'])
            if inv:
                inv['qty_units'] -= pt['picked_units']
                inv['reserved_units'] -= pt['picked_units']
                if inv['qty_units'] < 0:
                    inv['qty_units'] = 0
                if inv['reserved_units'] < 0:
                    inv['reserved_units'] = 0
                bump(inv)
                affected_bins.add(inv['bin_id'])
        for bid in affected_bins:
            b = store.bins.get(bid)
            if b:
                recompute_bin_capacity(b)
                bump(b)
        o['status'] = 'SHIPPED'
        bump(o)
        return success(ser_order(o))

# ============================================================================
# Wave
# ============================================================================

@bp.route('/warehouses/<warehouse_id>/waves', methods=['POST'])
@require_roles('WarehouseStaff')
def create_wave(warehouse_id):
    body = get_json_body()
    with lock:
        get_warehouse(warehouse_id)
        wave_code = required_str(body, 'wave_code')
        strategy = required_enum(body, 'strategy', {'BATCH', 'ZONE', 'ORDER'})
        order_ids = body.get('order_ids')
        if not isinstance(order_ids, list) or len(order_ids) == 0:
            raise ApiError('ERR_INVALID_INPUT',
                           'order_ids must be non-empty array', 422)
        for oid in order_ids:
            o = store.orders.get(oid)
            if not o or o['warehouse_id'] != warehouse_id:
                raise ApiError('ERR_NOT_FOUND', f'Order {oid} not found', 404)
        for existing in store.waves.values():
            if (existing['warehouse_id'] == warehouse_id
                    and existing['wave_code'] == wave_code):
                raise ApiError('ERR_INVALID_INPUT', 'wave_code already exists', 422)
        wv = {**common_fields(),
              'warehouse_id': warehouse_id,
              'wave_code': wave_code,
              'strategy': strategy,
              'order_ids': list(order_ids),
              'planned_unit_count': 0,
              'picked_unit_count': 0,
              'total_path_distance': None,
              'status': 'PLANNED',
              'released_at': None,
              'completed_at': None}
        store.waves[wv['id']] = wv
        # set wave_id on orders, compute planned_unit_count
        plan_total = 0
        for oid in order_ids:
            o = store.orders[oid]
            o['wave_id'] = wv['id']
            bump(o)
            for pt in store.pick_tasks.values():
                if pt['order_id'] == oid:
                    plan_total += pt['planned_units']
        wv['planned_unit_count'] = plan_total
        return success(ser_wave(wv), status=201)

@bp.route('/warehouses/<warehouse_id>/waves/<wave_id>', methods=['GET'])
@require_roles('WarehouseStaff', 'Auditor', 'WarehouseManager')
def fetch_wave(warehouse_id, wave_id):
    with lock:
        wv = get_wave(warehouse_id, wave_id)
        return success(ser_wave(wv))

@bp.route('/warehouses/<warehouse_id>/waves/<wave_id>/release', methods=['POST'])
@require_roles('WarehouseStaff')
def release_wave(warehouse_id, wave_id):
    body = get_json_body()
    with lock:
        w = get_warehouse(warehouse_id)
        wv = get_wave(warehouse_id, wave_id)
        if wv['status'] != 'PLANNED':
            raise ApiError('ERR_INVALID_STATE',
                           f'Cannot release wave in status {wv["status"]}', 409)
        occ_check(wv, body)
        # wave overlap
        for other in store.waves.values():
            if (other['warehouse_id'] == warehouse_id and other['id'] != wv['id']
                    and other['status'] in {'RELEASED', 'IN_PROGRESS'}):
                raise ApiError('ERR_WAVE_OVERLAP',
                               'Another wave is RELEASED or IN_PROGRESS', 409)
        # all order_ids must be ALLOCATED
        for oid in wv['order_ids']:
            o = store.orders.get(oid)
            if not o or o['status'] != 'ALLOCATED':
                raise ApiError('ERR_INVALID_STATE',
                               f'Order {oid} not ALLOCATED', 409)
        # stamp wave_id on pick tasks
        for oid in wv['order_ids']:
            for pt in store.pick_tasks.values():
                if pt['order_id'] == oid:
                    pt['wave_id'] = wv['id']
                    bump(pt)
        wv['status'] = 'RELEASED'
        wv['released_at'] = w['clock_now']
        bump(wv)
        assign_wave_path(w, wv)
        bump(wv)
        return success(ser_wave(wv))

@bp.route('/warehouses/<warehouse_id>/waves/<wave_id>/cancel', methods=['POST'])
@require_roles('WarehouseStaff')
def cancel_wave(warehouse_id, wave_id):
    body = get_json_body()
    with lock:
        get_warehouse(warehouse_id)
        wv = get_wave(warehouse_id, wave_id)
        if wv['status'] != 'PLANNED':
            raise ApiError('ERR_INVALID_STATE',
                           f'Cannot cancel wave in status {wv["status"]}', 409)
        occ_check(wv, body)
        wv['status'] = 'CANCELLED'
        bump(wv)
        return success(ser_wave(wv))

# ============================================================================
# PickTask
# ============================================================================

@bp.route('/warehouses/<warehouse_id>/pick_tasks/<pt_id>', methods=['GET'])
@require_roles('WarehouseStaff', 'Auditor', 'WarehouseManager')
def fetch_pick_task(warehouse_id, pt_id):
    with lock:
        pt = get_pick_task(warehouse_id, pt_id)
        return success(ser_pick_task(pt))

@bp.route('/warehouses/<warehouse_id>/pick_tasks/<pt_id>/start', methods=['POST'])
@require_roles('WarehouseStaff')
def start_pick_task(warehouse_id, pt_id):
    body = get_json_body()
    with lock:
        w = get_warehouse(warehouse_id)
        pt = get_pick_task(warehouse_id, pt_id)
        if pt['status'] != 'CREATED':
            raise ApiError('ERR_INVALID_STATE',
                           f'Cannot start pick task in status {pt["status"]}', 409)
        # parent wave must be RELEASED or IN_PROGRESS
        wv = store.waves.get(pt.get('wave_id')) if pt.get('wave_id') else None
        if not wv or wv['status'] not in {'RELEASED', 'IN_PROGRESS'}:
            raise ApiError('ERR_INVALID_STATE',
                           'Parent wave is not RELEASED or IN_PROGRESS', 409)
        occ_check(pt, body)
        lot = store.lots.get(pt['lot_id'])
        if not lot or lot['status'] not in {'ACTIVE', 'NEAR_EXPIRY'}:
            raise ApiError('ERR_LOT_NOT_PICKABLE',
                           f'Lot is in unpickable status', 409)
        b = store.bins.get(pt['bin_id'])
        if not b or b['status'] != 'ACTIVE':
            raise ApiError('ERR_BIN_FROZEN', 'Bin is FROZEN', 409)
        pt['status'] = 'PICKING'
        bump(pt)
        # cascade order/wave
        order = store.orders.get(pt['order_id'])
        if order and order['status'] == 'ALLOCATED':
            order['status'] = 'PICKING'
            bump(order)
        if wv['status'] == 'RELEASED':
            wv['status'] = 'IN_PROGRESS'
            bump(wv)
        return success(ser_pick_task(pt))

@bp.route('/warehouses/<warehouse_id>/pick_tasks/<pt_id>/complete', methods=['POST'])
@require_roles('WarehouseStaff')
def complete_pick_task(warehouse_id, pt_id):
    body = get_json_body()
    with lock:
        w = get_warehouse(warehouse_id)
        pt = get_pick_task(warehouse_id, pt_id)
        if pt['status'] != 'PICKING':
            raise ApiError('ERR_INVALID_STATE',
                           f'Cannot complete pick task in status {pt["status"]}', 409)
        occ_check(pt, body)
        picked = body.get('picked_units')
        if isinstance(picked, bool) or not isinstance(picked, int):
            raise ApiError('ERR_INVALID_INPUT', 'picked_units required int', 422)
        if picked < 0 or picked > pt['planned_units']:
            raise ApiError('ERR_INVALID_INPUT', 'picked_units out of range', 422)
        pt['picked_units'] = picked
        if picked == pt['planned_units']:
            pt['status'] = 'PICKED'
        else:
            pt['status'] = 'SHORT_PICKED'
            inv = store.inventory.get(pt['inventory_id'])
            if inv:
                inv['reserved_units'] = max(0, inv['reserved_units']
                                            - (pt['planned_units'] - picked))
                bump(inv)
        bump(pt)
        # update wave.picked_unit_count
        wv = store.waves.get(pt.get('wave_id')) if pt.get('wave_id') else None
        if wv:
            wv['picked_unit_count'] = wv.get('picked_unit_count', 0) + picked
            bump(wv)
        propagate_pick_terminal(w, pt)
        # if propagation made warehouse counters change (abnormal event), recompute
        recompute_warehouse_metrics(w)
        bump(w)
        return success(ser_pick_task(pt))

# ============================================================================
# CycleCount
# ============================================================================

@bp.route('/warehouses/<warehouse_id>/cycle_counts', methods=['POST'])
@require_roles('WarehouseStaff', 'Auditor')
def create_cycle_count(warehouse_id):
    body = get_json_body()
    with lock:
        w = get_warehouse(warehouse_id)
        bin_id = required_str(body, 'bin_id')
        lot_id = required_str(body, 'lot_id')
        b = store.bins.get(bin_id)
        if not b or b['warehouse_id'] != warehouse_id:
            raise ApiError('ERR_NOT_FOUND', f'Bin {bin_id} not found', 404)
        lot = store.lots.get(lot_id)
        if not lot or lot['warehouse_id'] != warehouse_id:
            raise ApiError('ERR_NOT_FOUND', f'Lot {lot_id} not found', 404)
        if b['status'] != 'ACTIVE':
            raise ApiError('ERR_BIN_FROZEN', 'Bin is already frozen', 409)
        # find inventory row (or 0)
        inv = next((i for i in store.inventory.values()
                    if i['warehouse_id'] == warehouse_id
                    and i['bin_id'] == bin_id and i['lot_id'] == lot_id), None)
        book_qty = inv['qty_units'] if inv else 0
        cc = {**common_fields(),
              'warehouse_id': warehouse_id,
              'bin_id': bin_id,
              'lot_id': lot_id,
              'book_qty': book_qty,
              'counted_qty': None,
              'variance_units': None,
              'variance_value_cents': None,
              'status': 'SCHEDULED',
              'scheduled_at': w['clock_now'],
              'submitted_by_user_id': None,
              'approved_by_user_id': None,
              'approved_at': None}
        store.cycle_counts[cc['id']] = cc
        b['status'] = 'FROZEN'
        b['frozen_by_cycle_count_id'] = cc['id']
        bump(b)
        return success(ser_cycle_count(cc), status=201)

@bp.route('/warehouses/<warehouse_id>/cycle_counts/<cc_id>', methods=['GET'])
@require_roles('WarehouseStaff', 'Auditor', 'WarehouseManager')
def fetch_cycle_count(warehouse_id, cc_id):
    with lock:
        cc = get_cycle_count(warehouse_id, cc_id)
        return success(ser_cycle_count(cc))

@bp.route('/warehouses/<warehouse_id>/cycle_counts/<cc_id>/start', methods=['POST'])
@require_roles('WarehouseStaff', 'Auditor')
def start_cycle_count(warehouse_id, cc_id):
    body = get_json_body()
    with lock:
        get_warehouse(warehouse_id)
        cc = get_cycle_count(warehouse_id, cc_id)
        if cc['status'] != 'SCHEDULED':
            raise ApiError('ERR_INVALID_STATE',
                           f'Cannot start cycle count in status {cc["status"]}', 409)
        occ_check(cc, body)
        cc['status'] = 'COUNTING'
        bump(cc)
        return success(ser_cycle_count(cc))

@bp.route('/warehouses/<warehouse_id>/cycle_counts/<cc_id>/submit_count', methods=['POST'])
@require_roles('WarehouseStaff', 'Auditor')
def submit_cycle_count(warehouse_id, cc_id):
    body = get_json_body()
    with lock:
        w = get_warehouse(warehouse_id)
        cc = get_cycle_count(warehouse_id, cc_id)
        if cc['status'] != 'COUNTING':
            raise ApiError('ERR_INVALID_STATE',
                           f'Cannot submit count in status {cc["status"]}', 409)
        occ_check(cc, body)
        counted = body.get('counted_qty')
        if isinstance(counted, bool) or not isinstance(counted, int) or counted < 0:
            raise ApiError('ERR_INVALID_INPUT',
                           'counted_qty must be non-negative integer', 422)
        cc['counted_qty'] = counted
        cc['submitted_by_user_id'] = g_user_id_for_log()
        if counted == cc['book_qty']:
            cc['variance_units'] = 0
            cc['variance_value_cents'] = 0
            cc['status'] = 'RECONCILED'
            # unfreeze bin
            b = store.bins.get(cc['bin_id'])
            if b:
                b['status'] = 'ACTIVE'
                b['frozen_by_cycle_count_id'] = None
                bump(b)
        else:
            cc['variance_units'] = counted - cc['book_qty']
            lot = store.lots.get(cc['lot_id'])
            unit_value = lot['unit_value_cents'] if lot else 0
            raw = abs(cc['variance_units']) * unit_value
            cc['variance_value_cents'] = round_half_up_int(raw)
            cc['status'] = 'VARIANCE_FOUND'
            add_abnormal_event(w)
            recompute_warehouse_metrics(w)
            bump(w)
        bump(cc)
        return success(ser_cycle_count(cc))

def g_user_id_for_log():
    from flask import g
    return getattr(g, 'user_id', None)

@bp.route('/warehouses/<warehouse_id>/cycle_counts/<cc_id>/approve_adjustment',
          methods=['POST'])
@require_roles('Auditor')
def approve_cycle_count(warehouse_id, cc_id):
    body = get_json_body()
    with lock:
        w = get_warehouse(warehouse_id)
        cc = get_cycle_count(warehouse_id, cc_id)
        if cc['status'] != 'VARIANCE_FOUND':
            raise ApiError('ERR_INVALID_STATE',
                           f'Cannot approve in status {cc["status"]}', 409)
        occ_check(cc, body)
        # segregation of duties
        approver_id = g_user_id_for_log()
        if cc['submitted_by_user_id'] == approver_id:
            raise ApiError('ERR_SEGREGATION_OF_DUTIES',
                           'Approver cannot be the submitter', 403)
        # apply adjustment
        inv = next((i for i in store.inventory.values()
                    if i['warehouse_id'] == warehouse_id
                    and i['bin_id'] == cc['bin_id']
                    and i['lot_id'] == cc['lot_id']), None)
        if inv is None:
            inv = {**common_fields(),
                   'warehouse_id': warehouse_id,
                   'bin_id': cc['bin_id'],
                   'lot_id': cc['lot_id'],
                   'qty_units': cc['counted_qty'],
                   'reserved_units': 0}
            store.inventory[inv['id']] = inv
        else:
            inv['qty_units'] = cc['counted_qty']
            bump(inv)
        b = store.bins.get(cc['bin_id'])
        if b:
            recompute_bin_capacity(b)
            b['status'] = 'ACTIVE'
            b['frozen_by_cycle_count_id'] = None
            bump(b)
        cc['approved_by_user_id'] = approver_id
        cc['approved_at'] = w['clock_now']
        cc['status'] = 'ADJUSTED'
        bump(cc)
        recompute_warehouse_metrics(w)
        bump(w)
        return success(ser_cycle_count(cc))

@bp.route('/warehouses/<warehouse_id>/cycle_counts/<cc_id>/dispute', methods=['POST'])
@require_roles('WarehouseStaff', 'Auditor')
def dispute_cycle_count(warehouse_id, cc_id):
    body = get_json_body()
    with lock:
        get_warehouse(warehouse_id)
        cc = get_cycle_count(warehouse_id, cc_id)
        if cc['status'] != 'VARIANCE_FOUND':
            raise ApiError('ERR_INVALID_STATE',
                           f'Cannot dispute in status {cc["status"]}', 409)
        occ_check(cc, body)
        cc['status'] = 'DISPUTED'
        bump(cc)
        b = store.bins.get(cc['bin_id'])
        if b:
            b['status'] = 'ACTIVE'
            b['frozen_by_cycle_count_id'] = None
            bump(b)
        return success(ser_cycle_count(cc))

# ============================================================================
# Clock advance (test driver)
# ============================================================================

@bp.route('/_clock/advance', methods=['POST'])
@require_roles('WarehouseManager')
def clock_advance():
    body = get_json_body()
    warehouse_id = required_str(body, 'warehouse_id')
    new_time_s = required_str(body, 'new_time')
    new_time = parse_iso(new_time_s)
    with lock:
        w = store.warehouses.get(warehouse_id)
        if not w:
            raise ApiError('ERR_NOT_FOUND', f'Warehouse {warehouse_id} not found', 404)
        w['clock_now'] = new_time
        bump(w)
        near_expiry_scan(w)
        recompute_warehouse_metrics(w)
        return success(ser_warehouse(w))
