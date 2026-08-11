"""Warehouses, storage zones, products, reagent lots."""
from datetime import date, timedelta

from flask import Blueprint

from .db import db, fmt_logical
from .errors import ApiError
from .response import ok
from . import serializers as S
from . import services as svc
from .validators import (
    get_context, require_role, get_body, check_unknown, as_str, as_bool,
    as_int, as_enum, as_date, get_path_resource, check_body_id, paginate,
    apply_filters,
)
from flask import request

bp = Blueprint('core', __name__)
ALL = ['OpsAdmin', 'CatalogManager', 'InventoryClerk', 'QualityManager',
       'AccountManager', 'Customer']
ZONE_CLASSES = ['AMBIENT', 'REFRIGERATED_2_8', 'FROZEN_MINUS_20',
                'ULTRACOLD_MINUS_80']
HAZARD_CLASSES = ['NON_HAZARDOUS', 'FLAMMABLE', 'CORROSIVE', 'TOXIC', 'OXIDIZER']


# ----------------------------------------------------------- warehouses

@bp.route('/warehouses', methods=['POST'])
def create_warehouse():
    uid, role = get_context()
    require_role(role, ['OpsAdmin'])
    body = get_body()
    check_unknown(body, ['name', 'region_code', 'hazmat_certified'])
    name = as_str(body, 'name')
    region_code = as_str(body, 'region_code')
    haz = as_bool(body, 'hazmat_certified')
    w = db.new_common()
    w.update({'name': name, 'region_code': region_code,
              'hazmat_certified': haz, 'status': 'OPERATIONAL'})
    db.warehouses[w['id']] = w
    return ok(S.warehouse(w), 201)


@bp.route('/warehouses', methods=['GET'])
def list_warehouses():
    get_context()
    items = sorted(db.warehouses.values(), key=lambda x: x['_seq'])
    items = apply_filters(items, {'status': request.args.get('status')})
    data, page = paginate(items, S.warehouse)
    return ok(data, 200, page)


@bp.route('/warehouses/<warehouseId>', methods=['GET'])
def get_warehouse(warehouseId):
    get_context()
    w = get_path_resource(db.warehouses, warehouseId, 'ERR_WAREHOUSE_NOT_FOUND')
    return ok(S.warehouse(w))


@bp.route('/warehouses/<warehouseId>/suspend', methods=['POST'])
def suspend_warehouse(warehouseId):
    uid, role = get_context()
    require_role(role, ['OpsAdmin'])
    w = get_path_resource(db.warehouses, warehouseId, 'ERR_WAREHOUSE_NOT_FOUND')
    get_body()
    if w['status'] != 'OPERATIONAL':
        raise ApiError('ERR_WAREHOUSE_NOT_OPERATIONAL',
                       'Warehouse is not OPERATIONAL')
    w['status'] = 'SUSPENDED'
    db.touch('warehouses', w['id'], set())
    return ok(S.warehouse(w))


@bp.route('/warehouses/<warehouseId>/resume', methods=['POST'])
def resume_warehouse(warehouseId):
    uid, role = get_context()
    require_role(role, ['OpsAdmin'])
    w = get_path_resource(db.warehouses, warehouseId, 'ERR_WAREHOUSE_NOT_FOUND')
    get_body()
    if w['status'] != 'SUSPENDED':
        raise ApiError('ERR_WAREHOUSE_NOT_SUSPENDED', 'Warehouse is not SUSPENDED')
    w['status'] = 'OPERATIONAL'
    db.touch('warehouses', w['id'], set())
    return ok(S.warehouse(w))


# ----------------------------------------------------------- storage zones

@bp.route('/storage-zones', methods=['POST'])
def create_zone():
    uid, role = get_context()
    require_role(role, ['OpsAdmin'])
    body = get_body()
    check_body_id(db.warehouses, body, 'warehouse_id', 'ERR_WAREHOUSE_NOT_FOUND')
    check_unknown(body, ['warehouse_id', 'zone_class', 'capacity_units',
                         'rotation_policy'])
    wh = as_str(body, 'warehouse_id')
    zc = as_enum(body, 'zone_class', ZONE_CLASSES)
    cap = as_int(body, 'capacity_units', min_value=1)
    rot = as_enum(body, 'rotation_policy', ['FEFO', 'FIFO'], required=False,
                  default='FEFO')
    z = db.new_common()
    z.update({'warehouse_id': wh, 'zone_class': zc, 'capacity_units': cap,
              'rotation_policy': rot})
    db.zones[z['id']] = z
    return ok(S.zone(z), 201)


@bp.route('/storage-zones', methods=['GET'])
def list_zones():
    get_context()
    items = sorted(db.zones.values(), key=lambda x: x['_seq'])
    items = apply_filters(items, {
        'warehouse_id': request.args.get('warehouse_id'),
        'zone_class': request.args.get('zone_class')})
    data, page = paginate(items, S.zone)
    return ok(data, 200, page)


@bp.route('/storage-zones/<zoneId>', methods=['GET'])
def get_zone(zoneId):
    get_context()
    z = get_path_resource(db.zones, zoneId, 'ERR_STORAGE_ZONE_NOT_FOUND')
    return ok(S.zone(z))


# ----------------------------------------------------------- products

@bp.route('/products', methods=['POST'])
def create_product():
    uid, role = get_context()
    require_role(role, ['CatalogManager'])
    body = get_body()
    check_unknown(body, ['sku', 'name', 'storage_requirement', 'hazard_class',
                         'unit_haz_factor', 'max_qty_per_shipment',
                         'unit_price_cents', 'requires_cold_chain',
                         'shelf_life_days', 'min_remaining_shelf_life_days'])
    sku = as_str(body, 'sku')
    name = as_str(body, 'name')
    sr = as_enum(body, 'storage_requirement', ZONE_CLASSES)
    hc = as_enum(body, 'hazard_class', HAZARD_CLASSES)
    uhf = as_int(body, 'unit_haz_factor', required=False, default=1, min_value=1)
    mqs = as_int(body, 'max_qty_per_shipment', min_value=1)
    upc = as_int(body, 'unit_price_cents', min_value=1)
    rcc = as_bool(body, 'requires_cold_chain')
    sld = as_int(body, 'shelf_life_days', min_value=1)
    mrsl = as_int(body, 'min_remaining_shelf_life_days', required=False,
                  default=7, min_value=0)
    for p in db.products.values():
        if p['sku'] == sku:
            raise ApiError('ERR_INVALID_REQUEST',
                           'sku %s already exists' % sku)
    p = db.new_common()
    p.update({'sku': sku, 'name': name, 'storage_requirement': sr,
              'hazard_class': hc, 'unit_haz_factor': uhf,
              'max_qty_per_shipment': mqs, 'unit_price_cents': upc,
              'requires_cold_chain': rcc, 'shelf_life_days': sld,
              'min_remaining_shelf_life_days': mrsl, 'status': 'LISTED'})
    db.products[p['id']] = p
    return ok(S.product(p), 201)


@bp.route('/products', methods=['GET'])
def list_products():
    get_context()
    items = sorted(db.products.values(), key=lambda x: x['_seq'])
    items = apply_filters(items, {
        'status': request.args.get('status'),
        'hazard_class': request.args.get('hazard_class')})
    data, page = paginate(items, S.product)
    return ok(data, 200, page)


@bp.route('/products/<productId>', methods=['GET'])
def get_product(productId):
    get_context()
    p = get_path_resource(db.products, productId, 'ERR_PRODUCT_NOT_FOUND')
    return ok(S.product(p))


@bp.route('/products/<productId>/discontinue', methods=['POST'])
def discontinue_product(productId):
    uid, role = get_context()
    require_role(role, ['CatalogManager'])
    p = get_path_resource(db.products, productId, 'ERR_PRODUCT_NOT_FOUND')
    get_body()
    if p['status'] not in ('LISTED', 'UNDER_RECALL'):
        raise ApiError('ERR_PRODUCT_NOT_LISTED', 'Product is not LISTED')
    p['status'] = 'DISCONTINUED'
    db.touch('products', p['id'], set())
    return ok(S.product(p))


# ----------------------------------------------------------- reagent lots

@bp.route('/lots', methods=['POST'])
def receive_lot():
    uid, role = get_context()
    require_role(role, ['InventoryClerk'])
    body = get_body()
    # stage 4: body-referenced ids in declared input order
    check_body_id(db.products, body, 'product_id', 'ERR_PRODUCT_NOT_FOUND')
    check_body_id(db.warehouses, body, 'warehouse_id', 'ERR_WAREHOUSE_NOT_FOUND')
    check_body_id(db.zones, body, 'storage_zone_id', 'ERR_STORAGE_ZONE_NOT_FOUND')
    check_unknown(body, ['product_id', 'warehouse_id', 'storage_zone_id',
                         'quantity_received', 'manufacture_date'])
    product_id = as_str(body, 'product_id')
    warehouse_id = as_str(body, 'warehouse_id')
    zone_id = as_str(body, 'storage_zone_id')
    qty = as_int(body, 'quantity_received', min_value=1)
    mfg = as_date(body, 'manufacture_date')
    product = db.products[product_id]
    warehouse = db.warehouses[warehouse_id]
    zone = db.zones[zone_id]
    # business checks in order
    if product['hazard_class'] != 'NON_HAZARDOUS' \
            and not warehouse['hazmat_certified']:
        raise ApiError('ERR_HAZMAT_WAREHOUSE_NOT_CERTIFIED',
                       'Warehouse is not hazmat certified')
    if svc.COLDNESS[zone['zone_class']] < svc.COLDNESS[product['storage_requirement']]:
        raise ApiError('ERR_STORAGE_ZONE_INCOMPATIBLE',
                       'Zone class is warmer than the storage requirement')
    if S.zone_occupied(zone_id) + qty > zone['capacity_units']:
        raise ApiError('ERR_ZONE_CAPACITY_EXCEEDED', 'Zone capacity exceeded')
    if zone['warehouse_id'] != warehouse_id:
        raise ApiError('ERR_ZONE_WAREHOUSE_MISMATCH',
                       'Zone does not belong to the declared warehouse')
    seq = 1 + max([l['lot_sequence_number'] for l in db.lots.values()
                   if l['product_id'] == product_id], default=0)
    expiry = (date.fromisoformat(mfg)
              + timedelta(days=product['shelf_life_days'])).isoformat()
    touched = set()
    l = db.new_common()
    l.update({'product_id': product_id, 'warehouse_id': warehouse_id,
              'storage_zone_id': zone_id, 'lot_sequence_number': seq,
              'quantity_received': qty, 'quantity_on_hand': qty,
              'quantity_reserved': 0, 'quantity_consumed': 0,
              'adjustment_total': 0, 'manufacture_date': mfg,
              'expiry_date': expiry, '_received_dt': db.clock,
              'recall_id': None, 'status': 'AVAILABLE'})
    db.lots[l['id']] = l
    svc.waitlist_retry(touched)
    return ok(S.lot(l), 201)


@bp.route('/lots', methods=['GET'])
def list_lots():
    get_context()
    items = sorted(db.lots.values(), key=lambda x: x['_seq'])
    items = apply_filters(items, {
        'product_id': request.args.get('product_id'),
        'warehouse_id': request.args.get('warehouse_id'),
        'storage_zone_id': request.args.get('storage_zone_id'),
        'recall_id': request.args.get('recall_id'),
        'status': request.args.get('status')})
    data, page = paginate(items, S.lot)
    return ok(data, 200, page)


@bp.route('/lots/<lotId>', methods=['GET'])
def get_lot(lotId):
    get_context()
    l = get_path_resource(db.lots, lotId, 'ERR_LOT_NOT_FOUND')
    return ok(S.lot(l))


@bp.route('/lots/<lotId>/adjustments', methods=['POST'])
def adjust_lot(lotId):
    uid, role = get_context()
    require_role(role, ['InventoryClerk'])
    l = get_path_resource(db.lots, lotId, 'ERR_LOT_NOT_FOUND')
    body = get_body()
    check_unknown(body, ['delta', 'reason', 'expected_lot_version'])
    delta = as_int(body, 'delta')
    as_str(body, 'reason')
    expected = as_int(body, 'expected_lot_version')
    if expected != l['version']:
        raise ApiError('ERR_STALE_LOT_VERSION',
                       'expected_lot_version does not match the lot version')
    if l['quantity_on_hand'] + delta < 0:
        raise ApiError('ERR_ADJUSTMENT_BELOW_ZERO',
                       'Adjustment would drive quantity_on_hand below zero')
    touched = set()
    l['quantity_on_hand'] += delta
    l['adjustment_total'] += delta
    db.touch('lots', l['id'], touched)
    if l['quantity_on_hand'] == 0 and l['status'] == 'AVAILABLE':
        l['status'] = 'DEPLETED'
    return ok(S.lot(l), 201)


@bp.route('/lots/<lotId>/quarantine', methods=['POST'])
def quarantine_lot(lotId):
    uid, role = get_context()
    require_role(role, ['QualityManager'])
    l = get_path_resource(db.lots, lotId, 'ERR_LOT_NOT_FOUND')
    get_body()
    if l['status'] != 'AVAILABLE':
        raise ApiError('ERR_LOT_NOT_AVAILABLE', 'Lot is not AVAILABLE')
    touched = set()
    l['status'] = 'QUARANTINED'
    db.touch('lots', l['id'], touched)
    svc.quarantine_cascade(l, touched, zero_only=False)
    return ok(S.lot(l))


@bp.route('/lots/<lotId>/release-quarantine', methods=['POST'])
def release_quarantine(lotId):
    uid, role = get_context()
    require_role(role, ['QualityManager'])
    l = get_path_resource(db.lots, lotId, 'ERR_LOT_NOT_FOUND')
    get_body()
    if l['status'] != 'QUARANTINED':
        raise ApiError('ERR_LOT_NOT_QUARANTINED', 'Lot is not QUARANTINED')
    if svc.issued_recall_covers_lot(l):
        raise ApiError('ERR_RECALL_ACTIVE_FOR_LOT',
                       'An issued recall covers this lot')
    l['status'] = 'AVAILABLE'
    db.touch('lots', l['id'], set())
    return ok(S.lot(l))
