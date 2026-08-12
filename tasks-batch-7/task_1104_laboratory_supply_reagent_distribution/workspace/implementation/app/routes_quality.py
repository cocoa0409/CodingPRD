"""Recalls, kit definitions, kit assembly jobs, and the logical clock."""
from flask import Blueprint, request

from .db import db, fmt_logical
from .errors import ApiError
from .response import ok
from . import serializers as S
from . import services as svc
from .validators import (
    get_context, require_role, get_body, check_unknown, as_str, as_int,
    as_enum, as_datetime, get_path_resource, check_body_id, paginate,
    apply_filters,
)

bp = Blueprint('quality', __name__)
SEVERITY_CLASSES = ['CLASS_I', 'CLASS_II', 'CLASS_III']
SCOPE_TYPES = ['LOT_RANGE', 'PRODUCT_ALL']


def own_or_403(customer_id, uid, role):
    if role == 'Customer' and customer_id != uid:
        raise ApiError('ERR_RESOURCE_OWNERSHIP_VIOLATION',
                       'Resource belongs to a different customer')


# ----------------------------------------------------------- recalls

@bp.route('/recalls', methods=['POST'])
def create_recall():
    uid, role = get_context()
    require_role(role, ['QualityManager'])
    body = get_body()
    check_body_id(db.products, body, 'product_id', 'ERR_PRODUCT_NOT_FOUND')
    check_unknown(body, ['product_id', 'scope_type', 'scope_lot_seq_min',
                         'scope_lot_seq_max', 'severity_class', 'reason'])
    product_id = as_str(body, 'product_id')
    scope_type = as_enum(body, 'scope_type', SCOPE_TYPES)
    sev = as_enum(body, 'severity_class', SEVERITY_CLASSES)
    as_str(body, 'reason')
    if scope_type == 'LOT_RANGE':
        smin = as_int(body, 'scope_lot_seq_min', min_value=1)
        smax = as_int(body, 'scope_lot_seq_max', min_value=1)
        if smax < smin:
            raise ApiError('ERR_INVALID_REQUEST',
                           'scope_lot_seq_max must be >= scope_lot_seq_min')
    else:
        smin = smax = None
    r = db.new_common()
    r.update({'product_id': product_id, 'scope_type': scope_type,
              'scope_lot_seq_min': smin, 'scope_lot_seq_max': smax,
              'severity_class': sev, 'reason': body['reason'],
              'status': 'DRAFT'})
    db.recalls[r['id']] = r
    return ok(S.recall(r), 201)


@bp.route('/recalls', methods=['GET'])
def list_recalls():
    get_context()
    items = sorted(db.recalls.values(), key=lambda x: x['_seq'])
    items = apply_filters(items, {
        'product_id': request.args.get('product_id'),
        'status': request.args.get('status')})
    data, page = paginate(items, S.recall)
    return ok(data, 200, page)


@bp.route('/recalls/<recallId>', methods=['GET'])
def get_recall(recallId):
    get_context()
    r = get_path_resource(db.recalls, recallId, 'ERR_RECALL_NOT_FOUND')
    return ok(S.recall(r))


@bp.route('/recalls/<recallId>/issue', methods=['POST'])
def issue_recall(recallId):
    uid, role = get_context()
    require_role(role, ['QualityManager'])
    r = get_path_resource(db.recalls, recallId, 'ERR_RECALL_NOT_FOUND')
    get_body()
    if r['status'] != 'DRAFT':
        raise ApiError('ERR_RECALL_NOT_DRAFT', 'Recall is not DRAFT')
    touched = set()
    # hop 1: covered lots -> QUARANTINED, recall_id stamped
    covered = [l for l in sorted(db.lots.values(), key=lambda x: x['_seq'])
               if l['status'] in ('AVAILABLE', 'QUARANTINED')
               and svc.recall_covers_lot(r, l)]
    affected_lines = []
    for lot in covered:
        lot['status'] = 'QUARANTINED'
        lot['recall_id'] = r['id']
        db.touch('lots', lot['id'], touched)
    # hop 2: HELD reservations on covered lots -> RELEASED with compensation
    for lot in covered:
        for res in db.reservations.values():
            if res['lot_id'] == lot['id'] and res['status'] == 'HELD':
                svc._release_held_reservation(res, touched)
                affected_lines.append(res['order_line_id'])
    # hops 3-4: line/order demotions (recall rule: demote only at zero)
    svc.cascade_demotions(affected_lines, touched, zero_only=True)
    # PRODUCT_ALL also flips the product
    if r['scope_type'] == 'PRODUCT_ALL':
        p = db.products[r['product_id']]
        if p['status'] == 'LISTED':
            p['status'] = 'UNDER_RECALL'
            db.touch('products', p['id'], touched)
    r['status'] = 'ISSUED'
    db.touch('recalls', r['id'], touched)
    return ok(S.recall(r))


@bp.route('/recalls/<recallId>/close', methods=['POST'])
def close_recall(recallId):
    uid, role = get_context()
    require_role(role, ['QualityManager'])
    r = get_path_resource(db.recalls, recallId, 'ERR_RECALL_NOT_FOUND')
    get_body()
    if r['status'] != 'ISSUED':
        raise ApiError('ERR_RECALL_NOT_CLOSABLE', 'Recall is not ISSUED')
    covered = [l for l in db.lots.values() if l['recall_id'] == r['id']]
    for lot in covered:
        if lot['status'] != 'QUARANTINED' or lot['quantity_reserved'] != 0:
            raise ApiError('ERR_RECALL_LOTS_PENDING',
                           'A covered lot is not QUARANTINED with zero '
                           'reserved quantity')
    touched = set()
    for lot in covered:
        # lot pull: remaining on-hand written off into consumed
        lot['quantity_consumed'] += lot['quantity_on_hand'] \
            + lot['quantity_reserved']
        lot['quantity_on_hand'] = 0
        lot['quantity_reserved'] = 0
        lot['recall_id'] = None
        lot['status'] = 'RECALLED'
        db.touch('lots', lot['id'], touched)
    if r['scope_type'] == 'PRODUCT_ALL':
        p = db.products[r['product_id']]
        if p['status'] == 'UNDER_RECALL':
            p['status'] = 'LISTED'
            db.touch('products', p['id'], touched)
    r['status'] = 'CLOSED'
    db.touch('recalls', r['id'], touched)
    return ok(S.recall(r))


# ----------------------------------------------------------- kits

@bp.route('/kits', methods=['POST'])
def create_kit():
    uid, role = get_context()
    require_role(role, ['CatalogManager'])
    body = get_body()
    check_body_id(db.customers, body, 'customer_id', 'ERR_CUSTOMER_NOT_FOUND')
    comps_raw = body.get('components')
    if isinstance(comps_raw, list):
        for entry in comps_raw:
            if isinstance(entry, dict):
                pid = entry.get('product_id')
                if isinstance(pid, str) and pid not in db.products:
                    raise ApiError('ERR_PRODUCT_NOT_FOUND',
                                   'Product %s does not exist' % pid)
    check_unknown(body, ['customer_id', 'name', 'components'])
    customer_id = as_str(body, 'customer_id')
    name = as_str(body, 'name')
    if 'components' not in body or not isinstance(body['components'], list):
        raise ApiError('ERR_INVALID_REQUEST', 'components must be an array')
    seen = set()
    comps = []
    for entry in body['components']:
        if not isinstance(entry, dict):
            raise ApiError('ERR_INVALID_REQUEST',
                           'component entries must be objects')
        check_unknown(entry, ['product_id', 'quantity_per_kit'])
        pid = as_str(entry, 'product_id')
        qpk = as_int(entry, 'quantity_per_kit', min_value=1)
        if pid in seen:
            raise ApiError('ERR_KIT_DUPLICATE_COMPONENT',
                           'Duplicate component product_id')
        seen.add(pid)
        comps.append({'product_id': pid, 'quantity_per_kit': qpk})
    k = db.new_common()
    k.update({'customer_id': customer_id, 'name': name, 'components': comps,
              'kit_price_cents': None, 'status': 'DRAFT'})
    db.kits[k['id']] = k
    return ok(S.kit(k), 201)


def kit_visible_or_404(kitId, uid, role):
    k = db.kits.get(kitId)
    if k is not None:
        own_or_403(k['customer_id'], uid, role)
    return get_path_resource(db.kits, kitId, 'ERR_KIT_NOT_FOUND')


@bp.route('/kits', methods=['GET'])
def list_kits():
    uid, role = get_context()
    items = sorted(db.kits.values(), key=lambda x: x['_seq'])
    if role == 'Customer':
        items = [k for k in items if k['customer_id'] == uid]
    items = apply_filters(items, {
        'customer_id': request.args.get('customer_id'),
        'status': request.args.get('status')})
    data, page = paginate(items, S.kit)
    return ok(data, 200, page)


@bp.route('/kits/<kitId>', methods=['GET'])
def get_kit(kitId):
    uid, role = get_context()
    k = kit_visible_or_404(kitId, uid, role)
    return ok(S.kit(k))


@bp.route('/kits/<kitId>/activate', methods=['POST'])
def activate_kit(kitId):
    uid, role = get_context()
    require_role(role, ['CatalogManager'])
    k = get_path_resource(db.kits, kitId, 'ERR_KIT_NOT_FOUND')
    get_body()
    if k['status'] != 'DRAFT':
        raise ApiError('ERR_KIT_NOT_DRAFT', 'Kit is not DRAFT')
    # checks in global priority order: recall, empty, mixed storage, listing
    for c in k['components']:
        if svc.issued_recall_for_product(c['product_id']):
            raise ApiError('ERR_PRODUCT_UNDER_RECALL',
                           'A component product is covered by an issued recall')
    if not k['components']:
        raise ApiError('ERR_KIT_COMPONENTS_EMPTY',
                       'Kit has an empty components array')
    reqs = {db.products[c['product_id']]['storage_requirement']
            for c in k['components']}
    if len(reqs) > 1:
        raise ApiError('ERR_KIT_STORAGE_MIXED',
                       'Components do not share one storage_requirement')
    for c in k['components']:
        if db.products[c['product_id']]['status'] != 'LISTED':
            raise ApiError('ERR_PRODUCT_NOT_LISTED',
                           'A component product is not LISTED')
    # kit_price_rollup: fee tier keyed on the pre-fee component cost
    component_cost = sum(c['quantity_per_kit']
                         * db.products[c['product_id']]['unit_price_cents']
                         for c in k['components'])
    if component_cost < 100000:
        fee = 1500
    elif component_cost < 500000:
        fee = 4000
    else:
        fee = 9000
    k['kit_price_cents'] = component_cost + fee
    k['status'] = 'ACTIVE'
    db.touch('kits', k['id'], set())
    return ok(S.kit(k))


@bp.route('/kits/<kitId>/retire', methods=['POST'])
def retire_kit(kitId):
    uid, role = get_context()
    require_role(role, ['CatalogManager'])
    k = get_path_resource(db.kits, kitId, 'ERR_KIT_NOT_FOUND')
    get_body()
    if k['status'] != 'ACTIVE':
        raise ApiError('ERR_KIT_NOT_ACTIVE', 'Kit is not ACTIVE')
    k['status'] = 'RETIRED'
    db.touch('kits', k['id'], set())
    return ok(S.kit(k))


# ----------------------------------------------------------- kit assembly jobs

@bp.route('/kit-assembly-jobs', methods=['POST'])
def create_job():
    uid, role = get_context()
    require_role(role, ['InventoryClerk'])
    body = get_body()
    check_body_id(db.kits, body, 'kit_id', 'ERR_KIT_NOT_FOUND')
    check_body_id(db.warehouses, body, 'warehouse_id', 'ERR_WAREHOUSE_NOT_FOUND')
    check_unknown(body, ['kit_id', 'warehouse_id', 'quantity_to_build'])
    kit_id = as_str(body, 'kit_id')
    warehouse_id = as_str(body, 'warehouse_id')
    qty = as_int(body, 'quantity_to_build', min_value=1)
    kit = db.kits[kit_id]
    if kit['status'] != 'ACTIVE':
        raise ApiError('ERR_KIT_NOT_ACTIVE', 'Kit is not ACTIVE')
    j = db.new_common()
    j.update({'kit_id': kit_id, 'warehouse_id': warehouse_id,
              'quantity_to_build': qty, 'kits_built': 0,
              'consumption_summary': None, 'status': 'PLANNED'})
    db.jobs[j['id']] = j
    return ok(S.job(j), 201)


@bp.route('/kit-assembly-jobs', methods=['GET'])
def list_jobs():
    get_context()
    items = sorted(db.jobs.values(), key=lambda x: x['_seq'])
    items = apply_filters(items, {
        'kit_id': request.args.get('kit_id'),
        'warehouse_id': request.args.get('warehouse_id'),
        'status': request.args.get('status')})
    data, page = paginate(items, S.job)
    return ok(data, 200, page)


@bp.route('/kit-assembly-jobs/<jobId>', methods=['GET'])
def get_job(jobId):
    get_context()
    j = get_path_resource(db.jobs, jobId, 'ERR_KIT_ASSEMBLY_JOB_NOT_FOUND')
    return ok(S.job(j))


def kit_consumption_plan(kit, warehouse_id, qty_to_build):
    """FEFO waterfall over AVAILABLE lots per component; None when short."""
    plan = {}
    for comp in kit['components']:
        pid = comp['product_id']
        need = comp['quantity_per_kit'] * qty_to_build
        lots = [l for l in db.lots.values()
                if l['status'] == 'AVAILABLE' and l['product_id'] == pid
                and l['warehouse_id'] == warehouse_id]
        ranked = svc.rank_lots(lots)
        takes = []
        remaining = need
        for lot in ranked:
            if remaining <= 0:
                break
            take = min(remaining, lot['quantity_on_hand'])
            if take > 0:
                takes.append((lot, take))
                remaining -= take
        if remaining > 0:
            return None
        plan[pid] = takes
    return plan


@bp.route('/kit-assembly-jobs/<jobId>/execute', methods=['POST'])
def execute_job(jobId):
    uid, role = get_context()
    require_role(role, ['InventoryClerk'])
    j = get_path_resource(db.jobs, jobId, 'ERR_KIT_ASSEMBLY_JOB_NOT_FOUND')
    get_body()
    if j['status'] != 'PLANNED':
        raise ApiError('ERR_JOB_NOT_EXECUTABLE', 'Job is not PLANNED')
    kit = db.kits[j['kit_id']]
    if kit['status'] != 'ACTIVE':
        raise ApiError('ERR_KIT_NOT_ACTIVE', 'Kit is not ACTIVE')
    plan = kit_consumption_plan(kit, j['warehouse_id'], j['quantity_to_build'])
    if plan is None:
        raise ApiError('ERR_KIT_COMPONENT_SHORTAGE',
                       'Component stock cannot cover the build')
    touched = set()
    summary = {}
    for pid, takes in plan.items():
        summary[pid] = []
        for lot, take in takes:
            lot['quantity_on_hand'] -= take
            lot['quantity_consumed'] += take
            db.touch('lots', lot['id'], touched)
            if lot['quantity_on_hand'] == 0 and lot['status'] == 'AVAILABLE':
                lot['status'] = 'DEPLETED'
            summary[pid].append({'lot_id': lot['id'], 'quantity': take})
    j['kits_built'] = j['quantity_to_build']
    j['consumption_summary'] = summary
    j['status'] = 'COMPLETED'
    db.touch('jobs', j['id'], touched)
    return ok(S.job(j))


@bp.route('/kit-assembly-jobs/<jobId>/cancel', methods=['POST'])
def cancel_job(jobId):
    uid, role = get_context()
    require_role(role, ['InventoryClerk'])
    j = get_path_resource(db.jobs, jobId, 'ERR_KIT_ASSEMBLY_JOB_NOT_FOUND')
    get_body()
    if j['status'] != 'PLANNED':
        raise ApiError('ERR_JOB_NOT_CANCELLABLE', 'Job is not PLANNED')
    j['status'] = 'CANCELLED'
    db.touch('jobs', j['id'], set())
    return ok(S.job(j))


# ----------------------------------------------------------- logical clock

@bp.route('/_clock/set_current_utc', methods=['POST'])
def set_clock():
    uid, role = get_context()
    require_role(role, ['OpsAdmin'])
    body = get_body()
    check_unknown(body, ['to_iso8601'])
    dt = as_datetime(body, 'to_iso8601')
    db.clock = dt
    touched = set()
    lots_expired = svc.expiry_sweep(touched)
    run_count, orders_generated = svc.standing_order_sweep(touched)
    return ok({'current_utc': fmt_logical(db.clock),
               'lots_expired': lots_expired,
               'standing_orders_run': run_count,
               'orders_generated': orders_generated})
