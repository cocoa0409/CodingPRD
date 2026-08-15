"""Routes: supplies, outbreaks, bed-ready notifications, placement demands."""
from flask import Blueprint, request as freq

from common import (ApiError, as_enum, as_int, as_str, authorize, do_list,
                    json_body, new_id, now, opt_field, parse_dt, req_field,
                    success_object)
from logic import (ITEM_CODES, PATHOGEN_CLASSES, URGENCY_TIERS, BED_KINDS,
                   demand_dict, item_by_code, ledger_dict, notification_dict,
                   on_hand, outbreak_dict, pin_request, standard_by_type,
                   supply_item_dict, touch)
from store import store

bp = Blueprint('flow', __name__)


# ---------------------------------------------------------------- supplies
@bp.route('/evs/supply-items', methods=['POST'])
def create_supply_item():
    body = json_body()
    item_code = as_enum(req_field(body, 'item_code'), 'item_code', ITEM_CODES)
    display_name = as_str(req_field(body, 'display_name'), 'display_name')
    initial_on_hand = as_int(req_field(body, 'initial_on_hand'), 'initial_on_hand',
                             min_value=0)
    reorder_threshold = as_int(req_field(body, 'reorder_threshold'), 'reorder_threshold',
                               min_value=0)
    note = opt_field(body, 'note')
    if note is not None:
        note = as_str(note, 'note')
    authorize(['EVSAdministrator'])
    if item_by_code(item_code) is not None:
        raise ApiError('ERR_INVALID_REQUEST',
                       'A supply item already exists for item_code %s' % item_code, 400)
    now_ = now()
    item = {'id': new_id(), 'item_code': item_code, 'display_name': display_name,
            'reorder_threshold': reorder_threshold,
            'created_at': now_, 'updated_at': now_, 'version': 1, '_seq': store.next_seq()}
    store.supply_items[item['id']] = item
    from logic import write_ledger
    write_ledger(item['id'], 'RESTOCK', initial_on_hand, note=note)
    return success_object(supply_item_dict(item), 201)


@bp.route('/evs/supply-items', methods=['GET'])
def list_supply_items():
    return do_list(list(store.supply_items.values()), supply_item_dict)


def get_item(item_id):
    i = store.supply_items.get(item_id)
    if i is None:
        raise ApiError('ERR_SUPPLY_ITEM_NOT_FOUND',
                       'Supply item %s not found' % item_id, 404)
    return i


@bp.route('/evs/supply-items/<item_id>', methods=['GET'])
def get_supply_item(item_id):
    authorize(['Any'])
    return success_object(supply_item_dict(get_item(item_id)))


@bp.route('/evs/supply-items/<item_id>/restock', methods=['POST'])
def restock_item(item_id):
    body = json_body()
    quantity = as_int(req_field(body, 'quantity'), 'quantity', min_value=1)
    note = opt_field(body, 'note')
    if note is not None:
        note = as_str(note, 'note')
    authorize(['EVSAdministrator'])
    item = get_item(item_id)
    from logic import write_ledger
    write_ledger(item['id'], 'RESTOCK', quantity, note=note)
    touch(item)
    return success_object(supply_item_dict(item))


@bp.route('/evs/supply-items/<item_id>/recount', methods=['POST'])
def recount_item(item_id):
    body = json_body()
    counted = as_int(req_field(body, 'counted_on_hand'), 'counted_on_hand', min_value=0)
    expected = as_int(req_field(body, 'expected_supply_item_version'),
                      'expected_supply_item_version')
    note = opt_field(body, 'note')
    if note is not None:
        note = as_str(note, 'note')
    authorize(['EVSAdministrator'])
    item = get_item(item_id)
    if expected != item['version']:
        raise ApiError('ERR_STALE_SUPPLY_VERSION',
                       'expected_supply_item_version does not match the current version',
                       412)
    from logic import write_ledger
    delta = counted - on_hand(item['id'])
    write_ledger(item['id'], 'RECOUNT_ADJUSTMENT', delta, note=note)
    touch(item)
    return success_object(supply_item_dict(item))


@bp.route('/evs/supply-ledger-entries', methods=['GET'])
def list_ledger():
    supply_item_id = freq.args.get('supply_item_id')
    clean_request_id = freq.args.get('clean_request_id')

    def f(e):
        if supply_item_id is not None and e['supply_item_id'] != supply_item_id:
            return False
        if clean_request_id is not None and e['clean_request_id'] != clean_request_id:
            return False
        return True

    return do_list(list(store.ledger.values()), ledger_dict, f)


@bp.route('/evs/supply-ledger-entries/<entry_id>', methods=['GET'])
def get_ledger_entry(entry_id):
    authorize(['Any'])
    e = store.ledger.get(entry_id)
    if e is None:
        raise ApiError('ERR_SUPPLY_ITEM_NOT_FOUND',
                       'Ledger entry %s not found' % entry_id, 404)
    return success_object(ledger_dict(e))


# --------------------------------------------------------------- outbreaks
@bp.route('/evs/outbreak-events', methods=['POST'])
def create_outbreak():
    body = json_body()
    unit_id = as_str(req_field(body, 'unit_id'), 'unit_id')
    pathogen_class = as_enum(req_field(body, 'pathogen_class'), 'pathogen_class',
                             PATHOGEN_CLASSES)
    declared_reason = opt_field(body, 'declared_reason')
    if declared_reason is not None:
        declared_reason = as_str(declared_reason, 'declared_reason')
    authorize(['InfectionPreventionist'])
    unit = store.units.get(unit_id)
    if unit is None:
        raise ApiError('ERR_UNIT_NOT_FOUND', 'Unit %s not found' % unit_id, 404)
    now_ = now()
    o = {'id': new_id(), 'unit_id': unit_id, 'pathogen_class': pathogen_class,
         'declared_reason': declared_reason, 'status': 'DECLARED',
         'activated_at': None, 'lifted_at': None,
         'created_at': now_, 'updated_at': now_, 'version': 1, '_seq': store.next_seq()}
    store.outbreaks[o['id']] = o
    return success_object(outbreak_dict(o), 201)


@bp.route('/evs/outbreak-events', methods=['GET'])
def list_outbreaks():
    unit_id = freq.args.get('unit_id')
    status = freq.args.get('status')

    def f(o):
        if unit_id is not None and o['unit_id'] != unit_id:
            return False
        if status is not None and o['status'] != status:
            return False
        return True

    return do_list(list(store.outbreaks.values()), outbreak_dict, f)


def get_outbreak(event_id):
    o = store.outbreaks.get(event_id)
    if o is None:
        raise ApiError('ERR_OUTBREAK_NOT_FOUND',
                       'Outbreak event %s not found' % event_id, 404)
    return o


@bp.route('/evs/outbreak-events/<event_id>', methods=['GET'])
def get_outbreak_route(event_id):
    authorize(['Any'])
    return success_object(outbreak_dict(get_outbreak(event_id)))


@bp.route('/evs/outbreak-events/<event_id>/activate', methods=['POST'])
def activate_outbreak(event_id):
    json_body()
    authorize(['InfectionPreventionist'])
    o = get_outbreak(event_id)
    if o['status'] != 'DECLARED':
        raise ApiError('ERR_OUTBREAK_INVALID_STATE',
                       'Activate requires status DECLARED', 409)
    if any(e for e in store.outbreaks.values()
           if e['unit_id'] == o['unit_id'] and e['status'] == 'ACTIVE'):
        raise ApiError('ERR_OUTBREAK_ALREADY_ACTIVE',
                       'Unit already has an ACTIVE outbreak event', 409)
    now_ = now()
    o['status'] = 'ACTIVE'
    o['activated_at'] = now_
    touch(o)
    unit = store.units[o['unit_id']]
    unit['outbreak_posture'] = 'OUTBREAK'
    touch(unit)
    # Upgrade in-flight QUEUED/ASSIGNED ISOLATION-bed requests to TERMINAL.
    terminal_std = standard_by_type('TERMINAL')
    if terminal_std is not None:
        for r in store.requests.values():
            if r['unit_id'] != unit['id'] or r['status'] not in ('QUEUED', 'ASSIGNED'):
                continue
            if r['clean_type'] == 'TERMINAL':
                continue
            bed = store.beds.get(r['bed_id'])
            if bed is None or bed['bed_kind'] != 'ISOLATION':
                continue
            r['clean_type'] = 'TERMINAL'
            pin_request(r, terminal_std, 'OUTBREAK')
            touch(r)
    return success_object(outbreak_dict(o))


@bp.route('/evs/outbreak-events/<event_id>/lift', methods=['POST'])
def lift_outbreak(event_id):
    json_body()
    authorize(['InfectionPreventionist'])
    o = get_outbreak(event_id)
    if o['status'] != 'ACTIVE':
        raise ApiError('ERR_OUTBREAK_INVALID_STATE', 'Lift requires status ACTIVE', 409)
    now_ = now()
    o['status'] = 'LIFTED'
    o['lifted_at'] = now_
    touch(o)
    unit = store.units[o['unit_id']]
    still_active = any(e for e in store.outbreaks.values()
                       if e['unit_id'] == o['unit_id'] and e['status'] == 'ACTIVE')
    unit['outbreak_posture'] = 'OUTBREAK' if still_active else 'NORMAL'
    touch(unit)
    return success_object(outbreak_dict(o))


@bp.route('/evs/outbreak-events/<event_id>/cancel', methods=['POST'])
def cancel_outbreak(event_id):
    json_body()
    authorize(['InfectionPreventionist'])
    o = get_outbreak(event_id)
    if o['status'] != 'DECLARED':
        raise ApiError('ERR_OUTBREAK_INVALID_STATE',
                       'Cancel requires status DECLARED', 409)
    o['status'] = 'CANCELLED'
    touch(o)
    return success_object(outbreak_dict(o))


# ---------------------------------------------------- bed-ready notifications
@bp.route('/evs/bed-ready-notifications', methods=['GET'])
def list_notifications():
    bed_id = freq.args.get('bed_id')
    demand_id = freq.args.get('demand_id')
    status = freq.args.get('status')

    def f(n):
        if bed_id is not None and n['bed_id'] != bed_id:
            return False
        if demand_id is not None and n['demand_id'] != demand_id:
            return False
        if status is not None and n['status'] != status:
            return False
        return True

    return do_list(list(store.notifications.values()), notification_dict, f)


def get_notification(notification_id):
    n = store.notifications.get(notification_id)
    if n is None:
        raise ApiError('ERR_NOTIFICATION_NOT_FOUND',
                       'Notification %s not found' % notification_id, 404)
    return n


@bp.route('/evs/bed-ready-notifications/<notification_id>', methods=['GET'])
def get_notification_route(notification_id):
    authorize(['Any'])
    return success_object(notification_dict(get_notification(notification_id)))


@bp.route('/evs/bed-ready-notifications/<notification_id>/acknowledge', methods=['POST'])
def acknowledge_notification(notification_id):
    json_body()
    authorize(['BedPlacementCoordinator'])
    n = get_notification(notification_id)
    if n['status'] != 'SENT':
        raise ApiError('ERR_NOTIFICATION_NOT_SENT',
                       'Acknowledge requires status SENT', 409)
    n['status'] = 'ACKNOWLEDGED'
    n['acknowledged_at'] = now()
    touch(n)
    return success_object(notification_dict(n))


# --------------------------------------------------------- placement demands
@bp.route('/evs/placement-demands', methods=['POST'])
def create_demand():
    body = json_body()
    unit_id = as_str(req_field(body, 'unit_id'), 'unit_id')
    required_bed_kind = as_enum(req_field(body, 'required_bed_kind'),
                                'required_bed_kind', BED_KINDS)
    urgency_tier = as_enum(req_field(body, 'urgency_tier'), 'urgency_tier', URGENCY_TIERS)
    needed_by = parse_dt(req_field(body, 'needed_by'), 'needed_by')
    authorize(['BedPlacementCoordinator'])
    unit = store.units.get(unit_id)
    if unit is None:
        raise ApiError('ERR_UNIT_NOT_FOUND', 'Unit %s not found' % unit_id, 404)
    now_ = now()
    d = {'id': new_id(), 'unit_id': unit_id, 'required_bed_kind': required_bed_kind,
         'urgency_tier': urgency_tier, 'needed_by': needed_by, 'status': 'OPEN',
         'matched_bed_id': None, 'fulfilled_at': None,
         'created_at': now_, 'updated_at': now_, 'version': 1, '_seq': store.next_seq()}
    store.demands[d['id']] = d
    return success_object(demand_dict(d), 201)


@bp.route('/evs/placement-demands', methods=['GET'])
def list_demands():
    unit_id = freq.args.get('unit_id')
    status = freq.args.get('status')
    matched_bed_id = freq.args.get('matched_bed_id')
    required_bed_kind = freq.args.get('required_bed_kind')

    def f(d):
        if unit_id is not None and d['unit_id'] != unit_id:
            return False
        if status is not None and d['status'] != status:
            return False
        if matched_bed_id is not None and d['matched_bed_id'] != matched_bed_id:
            return False
        if required_bed_kind is not None and d['required_bed_kind'] != required_bed_kind:
            return False
        return True

    return do_list(list(store.demands.values()), demand_dict, f)


def get_demand(demand_id):
    d = store.demands.get(demand_id)
    if d is None:
        raise ApiError('ERR_PLACEMENT_DEMAND_NOT_FOUND',
                       'Placement demand %s not found' % demand_id, 404)
    return d


@bp.route('/evs/placement-demands/<demand_id>', methods=['GET'])
def get_demand_route(demand_id):
    authorize(['Any'])
    return success_object(demand_dict(get_demand(demand_id)))


@bp.route('/evs/placement-demands/<demand_id>/cancel', methods=['POST'])
def cancel_demand(demand_id):
    json_body()
    authorize(['BedPlacementCoordinator'])
    d = get_demand(demand_id)
    if d['status'] not in ('OPEN', 'MATCHED'):
        raise ApiError('ERR_DEMAND_NOT_OPEN',
                       'Cancel requires status OPEN or MATCHED', 409)
    if d['status'] == 'MATCHED':
        for n in store.notifications.values():
            if n['demand_id'] == d['id'] and n['status'] == 'SENT':
                n['status'] = 'RETRACTED'
                touch(n)
        d['matched_bed_id'] = None
    d['status'] = 'CANCELLED'
    touch(d)
    return success_object(demand_dict(d))


@bp.route('/evs/placement-demands/<demand_id>/regrade', methods=['POST'])
def regrade_demand(demand_id):
    body = json_body()
    urgency_tier = as_enum(req_field(body, 'urgency_tier'), 'urgency_tier', URGENCY_TIERS)
    authorize(['BedPlacementCoordinator'])
    d = get_demand(demand_id)
    if d['status'] != 'OPEN':
        raise ApiError('ERR_DEMAND_NOT_OPEN', 'Regrade requires status OPEN', 409)
    d['urgency_tier'] = urgency_tier
    touch(d)
    return success_object(demand_dict(d))
