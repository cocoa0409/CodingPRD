"""Routes: clock, units, beds, maintenance windows, clean standards."""
from datetime import timedelta

from flask import Blueprint

from common import (ApiError, as_enum, as_int, as_str, authorize, do_list, fmt_dt,
                    json_body, new_id, now, opt_field, parse_dt, req_field,
                    success_object)
from logic import (BED_KINDS, CLEAN_TYPES, OPEN_REQUEST_STATUSES,
                   bed_dict, create_clean_request, maintenance_capacity_ok,
                   notification_dict, ops_run, retract_bed_notifications,
                   snapshot_dict, standard_by_type, standard_dict, touch,
                   unit_dict, window_dict)
from store import store

bp = Blueprint('core', __name__)


def get_unit(unit_id):
    u = store.units.get(unit_id)
    if u is None:
        raise ApiError('ERR_UNIT_NOT_FOUND', 'Unit %s not found' % unit_id, 404)
    return u


def get_bed(bed_id):
    b = store.beds.get(bed_id)
    if b is None:
        raise ApiError('ERR_BED_NOT_FOUND', 'Bed %s not found' % bed_id, 404)
    return b


def get_window(window_id):
    w = store.windows.get(window_id)
    if w is None:
        raise ApiError('ERR_WINDOW_NOT_FOUND', 'Maintenance window %s not found' % window_id, 404)
    return w


def has_open_request(bed_id):
    return any(r for r in store.requests.values()
               if r['bed_id'] == bed_id and r['status'] in OPEN_REQUEST_STATUSES)


# -------------------------------------------------------------------- clock
@bp.route('/_clock/set_current_utc', methods=['POST'])
def set_clock():
    body = json_body()
    to = parse_dt(req_field(body, 'to_iso8601'), 'to_iso8601')
    if to < store.clock:
        raise ApiError('ERR_CLOCK_REGRESSION',
                       'to_iso8601 is earlier than the current logical time', 400)
    authorize(['EVSAdministrator'])
    store.clock = to
    return success_object({'current_utc': fmt_dt(store.clock)})


# -------------------------------------------------------------------- units
@bp.route('/evs/units', methods=['POST'])
def create_unit():
    body = json_body()
    unit_code = as_str(req_field(body, 'unit_code'), 'unit_code')
    display_name = as_str(req_field(body, 'display_name'), 'display_name')
    authorize(['EVSAdministrator'])
    now_ = now()
    u = {'id': new_id(), 'unit_code': unit_code, 'display_name': display_name,
         'outbreak_posture': 'NORMAL', 'ops_run_index': 0,
         'created_at': now_, 'updated_at': now_, 'version': 1, '_seq': store.next_seq()}
    store.units[u['id']] = u
    return success_object(unit_dict(u), 201)


@bp.route('/evs/units', methods=['GET'])
def list_units():
    return do_list(list(store.units.values()), unit_dict)


@bp.route('/evs/units/<unit_id>', methods=['GET'])
def get_unit_route(unit_id):
    authorize(['Any'])
    return success_object(unit_dict(get_unit(unit_id)))


@bp.route('/evs/units/<unit_id>/ops-runs', methods=['POST'])
def run_ops(unit_id):
    json_body()
    authorize(['EVSAdministrator'])
    unit = get_unit(unit_id)
    snap = ops_run(unit)
    return success_object(snapshot_dict(snap), 201)


@bp.route('/evs/units/<unit_id>/turnaround-snapshots', methods=['GET'])
def list_unit_snapshots(unit_id):
    from common import pagination_params, success_list
    limit, offset = pagination_params()
    authorize(['Any'])
    get_unit(unit_id)
    items = [s for s in store.snapshots.values() if s['unit_id'] == unit_id]
    items.sort(key=lambda e: (e['created_at'], e['_seq']))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([snapshot_dict(s) for s in page], limit, offset, total)


@bp.route('/evs/turnaround-snapshots/<snapshot_id>', methods=['GET'])
def get_snapshot(snapshot_id):
    authorize(['Any'])
    s = store.snapshots.get(snapshot_id)
    if s is None:
        raise ApiError('ERR_SNAPSHOT_NOT_FOUND', 'Snapshot %s not found' % snapshot_id, 404)
    return success_object(snapshot_dict(s))


# --------------------------------------------------------------------- beds
@bp.route('/evs/beds', methods=['POST'])
def create_bed():
    body = json_body()
    unit_id = as_str(req_field(body, 'unit_id'), 'unit_id')
    bed_code = as_str(req_field(body, 'bed_code'), 'bed_code')
    bed_kind = as_enum(req_field(body, 'bed_kind'), 'bed_kind', BED_KINDS)
    authorize(['EVSAdministrator'])
    get_unit(unit_id)
    now_ = now()
    b = {'id': new_id(), 'unit_id': unit_id, 'bed_code': bed_code, 'bed_kind': bed_kind,
         'bed_status': 'VACANT_DIRTY', 'last_discharge_at': None, 'last_ready_at': None,
         'tat_total_minutes': None, 'tat_clean_minutes': None,
         'created_at': now_, 'updated_at': now_, 'version': 1, '_seq': store.next_seq()}
    store.beds[b['id']] = b
    return success_object(bed_dict(b), 201)


@bp.route('/evs/beds', methods=['GET'])
def list_beds():
    from flask import request as freq
    unit_id = freq.args.get('unit_id')
    bed_status = freq.args.get('bed_status')
    bed_kind = freq.args.get('bed_kind')

    def f(b):
        if unit_id is not None and b['unit_id'] != unit_id:
            return False
        if bed_status is not None and b['bed_status'] != bed_status:
            return False
        if bed_kind is not None and b['bed_kind'] != bed_kind:
            return False
        return True

    return do_list(list(store.beds.values()), bed_dict, f)


@bp.route('/evs/beds/<bed_id>', methods=['GET'])
def get_bed_route(bed_id):
    authorize(['Any'])
    return success_object(bed_dict(get_bed(bed_id)))


@bp.route('/evs/beds/<bed_id>/discharge', methods=['POST'])
def discharge_bed(bed_id):
    body = json_body()
    clean_type_in = opt_field(body, 'clean_type')
    if clean_type_in is not None:
        clean_type_in = as_enum(clean_type_in, 'clean_type', CLEAN_TYPES)
    authorize(['BedPlacementCoordinator'])
    bed = get_bed(bed_id)
    unit = store.units[bed['unit_id']]
    if clean_type_in is not None:
        ct = clean_type_in
    elif bed['bed_kind'] == 'ISOLATION':
        ct = 'ISOLATION'
    else:
        ct = 'ROUTINE'
    if unit['outbreak_posture'] == 'OUTBREAK' and bed['bed_kind'] == 'ISOLATION':
        ct = 'TERMINAL'
    if standard_by_type(ct) is None:
        raise ApiError('ERR_STANDARD_NOT_FOUND',
                       'No clean standard exists for clean_type %s' % ct, 404)
    if bed['bed_status'] != 'OCCUPIED':
        raise ApiError('ERR_BED_NOT_OCCUPIED',
                       'Discharge requires bed_status OCCUPIED', 409)
    if has_open_request(bed['id']):
        raise ApiError('ERR_OPEN_REQUEST_EXISTS',
                       'Bed already has an open clean request', 409)
    now_ = now()
    bed['bed_status'] = 'VACANT_DIRTY'
    bed['last_discharge_at'] = now_
    touch(bed)
    create_clean_request(bed, ct)
    return success_object(bed_dict(bed))


@bp.route('/evs/beds/<bed_id>/admit', methods=['POST'])
def admit_bed(bed_id):
    json_body()
    authorize(['BedPlacementCoordinator'])
    bed = get_bed(bed_id)
    if bed['bed_status'] != 'READY':
        raise ApiError('ERR_BED_NOT_READY', 'Admit requires bed_status READY', 409)
    now_ = now()
    bed['bed_status'] = 'OCCUPIED'
    touch(bed)
    for d in store.demands.values():
        if d['status'] == 'MATCHED' and d['matched_bed_id'] == bed['id']:
            d['status'] = 'FULFILLED'
            d['fulfilled_at'] = now_
            touch(d)
            for n in store.notifications.values():
                if n['demand_id'] == d['id'] and n['bed_id'] == bed['id'] and n['status'] == 'SENT':
                    n['status'] = 'ACKNOWLEDGED'
                    n['acknowledged_at'] = now_
                    touch(n)
    return success_object(bed_dict(bed))


@bp.route('/evs/beds/<bed_id>/mark-soiled', methods=['POST'])
def mark_soiled_bed(bed_id):
    json_body()
    authorize(['BedPlacementCoordinator'])
    bed = get_bed(bed_id)
    if standard_by_type('ROUTINE') is None:
        raise ApiError('ERR_STANDARD_NOT_FOUND',
                       'No clean standard exists for clean_type ROUTINE', 404)
    if bed['bed_status'] != 'READY':
        raise ApiError('ERR_BED_NOT_READY', 'Mark-soiled requires bed_status READY', 409)
    bed['bed_status'] = 'VACANT_DIRTY'
    touch(bed)
    retract_bed_notifications(bed)
    create_clean_request(bed, 'ROUTINE')
    return success_object(bed_dict(bed))


# -------------------------------------------------------- maintenance windows
@bp.route('/evs/maintenance-windows', methods=['POST'])
def create_window():
    body = json_body()
    bed_id = as_str(req_field(body, 'bed_id'), 'bed_id')
    start_at = parse_dt(req_field(body, 'start_at'), 'start_at')
    end_at = parse_dt(req_field(body, 'end_at'), 'end_at')
    reason = opt_field(body, 'reason')
    if reason is not None:
        reason = as_str(reason, 'reason')
    if end_at <= start_at:
        raise ApiError('ERR_INVALID_WINDOW', 'end_at must be strictly after start_at', 400)
    authorize(['EVSAdministrator'])
    bed = get_bed(bed_id)
    if not maintenance_capacity_ok(bed, start_at, end_at):
        raise ApiError('ERR_CAPACITY_EXCEEDED',
                       'Maintenance window would exceed the unit capacity cap', 422)
    now_ = now()
    w = {'id': new_id(), 'bed_id': bed_id, 'start_at': start_at, 'end_at': end_at,
         'reason': reason, 'status': 'SCHEDULED',
         'created_at': now_, 'updated_at': now_, 'version': 1, '_seq': store.next_seq()}
    store.windows[w['id']] = w
    return success_object(window_dict(w), 201)


@bp.route('/evs/maintenance-windows', methods=['GET'])
def list_windows():
    from flask import request as freq
    bed_id = freq.args.get('bed_id')
    status = freq.args.get('status')

    def f(w):
        if bed_id is not None and w['bed_id'] != bed_id:
            return False
        if status is not None and w['status'] != status:
            return False
        return True

    return do_list(list(store.windows.values()), window_dict, f)


@bp.route('/evs/maintenance-windows/<window_id>', methods=['GET'])
def get_window_route(window_id):
    authorize(['Any'])
    return success_object(window_dict(get_window(window_id)))


@bp.route('/evs/maintenance-windows/<window_id>/activate', methods=['POST'])
def activate_window(window_id):
    json_body()
    authorize(['EVSAdministrator'])
    w = get_window(window_id)
    if w['status'] != 'SCHEDULED':
        raise ApiError('ERR_WINDOW_INVALID_STATE',
                       'Activate requires status SCHEDULED', 409)
    bed = store.beds[w['bed_id']]
    if bed['bed_status'] not in ('VACANT_DIRTY', 'READY'):
        raise ApiError('ERR_BED_NOT_AVAILABLE_FOR_MAINTENANCE',
                       'Bed is not available for maintenance', 409)
    if has_open_request(bed['id']):
        raise ApiError('ERR_OPEN_REQUEST_EXISTS',
                       'Bed has an open clean request', 409)
    if not maintenance_capacity_ok(bed, w['start_at'], w['end_at'], exclude_id=w['id']):
        raise ApiError('ERR_CAPACITY_EXCEEDED',
                       'Maintenance window would exceed the unit capacity cap', 422)
    was_ready = bed['bed_status'] == 'READY'
    w['status'] = 'ACTIVE'
    touch(w)
    if was_ready:
        retract_bed_notifications(bed)
    bed['bed_status'] = 'OUT_OF_SERVICE'
    touch(bed)
    return success_object(window_dict(w))


@bp.route('/evs/maintenance-windows/<window_id>/close', methods=['POST'])
def close_window(window_id):
    json_body()
    authorize(['EVSAdministrator'])
    w = get_window(window_id)
    if w['status'] != 'ACTIVE':
        raise ApiError('ERR_WINDOW_INVALID_STATE', 'Close requires status ACTIVE', 409)
    bed = store.beds[w['bed_id']]
    if standard_by_type('ROUTINE') is None:
        raise ApiError('ERR_STANDARD_NOT_FOUND',
                       'No clean standard exists for clean_type ROUTINE', 404)
    w['status'] = 'CLOSED'
    touch(w)
    bed['bed_status'] = 'VACANT_DIRTY'
    touch(bed)
    create_clean_request(bed, 'ROUTINE')
    return success_object(window_dict(w))


@bp.route('/evs/maintenance-windows/<window_id>/cancel', methods=['POST'])
def cancel_window(window_id):
    json_body()
    authorize(['EVSAdministrator'])
    w = get_window(window_id)
    if w['status'] != 'SCHEDULED':
        raise ApiError('ERR_WINDOW_INVALID_STATE', 'Cancel requires status SCHEDULED', 409)
    w['status'] = 'CANCELLED'
    touch(w)
    return success_object(window_dict(w))


# ----------------------------------------------------------- clean standards
@bp.route('/evs/clean-standards', methods=['POST'])
def create_standard():
    body = json_body()
    clean_type = as_enum(req_field(body, 'clean_type'), 'clean_type', CLEAN_TYPES)
    base_minutes = as_int(req_field(body, 'base_minutes'), 'base_minutes', min_value=1)
    mult = as_int(req_field(body, 'outbreak_multiplier_bps'), 'outbreak_multiplier_bps',
                  min_value=10000)
    threshold = as_int(req_field(body, 'atp_rlu_threshold'), 'atp_rlu_threshold', min_value=1)
    authorize(['EVSAdministrator'])
    if standard_by_type(clean_type) is not None:
        raise ApiError('ERR_DUPLICATE_STANDARD',
                       'A clean standard already exists for %s' % clean_type, 409)
    now_ = now()
    s = {'id': new_id(), 'clean_type': clean_type, 'base_minutes': base_minutes,
         'outbreak_multiplier_bps': mult, 'atp_rlu_threshold': threshold,
         'created_at': now_, 'updated_at': now_, 'version': 1, '_seq': store.next_seq()}
    store.standards[s['id']] = s
    return success_object(standard_dict(s), 201)


@bp.route('/evs/clean-standards', methods=['GET'])
def list_standards():
    return do_list(list(store.standards.values()), standard_dict)


@bp.route('/evs/clean-standards/<clean_type>', methods=['GET'])
def get_standard(clean_type):
    authorize(['Any'])
    s = standard_by_type(clean_type)
    if s is None:
        raise ApiError('ERR_STANDARD_NOT_FOUND',
                       'No clean standard exists for clean_type %s' % clean_type, 404)
    return success_object(standard_dict(s))


@bp.route('/evs/clean-standards/<clean_type>', methods=['PUT'])
def update_standard(clean_type):
    body = json_body()
    base_minutes = as_int(req_field(body, 'base_minutes'), 'base_minutes', min_value=1)
    mult = as_int(req_field(body, 'outbreak_multiplier_bps'), 'outbreak_multiplier_bps',
                  min_value=10000)
    threshold = as_int(req_field(body, 'atp_rlu_threshold'), 'atp_rlu_threshold', min_value=1)
    expected = as_int(req_field(body, 'expected_standard_version'),
                      'expected_standard_version')
    authorize(['EVSAdministrator'])
    s = standard_by_type(clean_type)
    if s is None:
        raise ApiError('ERR_STANDARD_NOT_FOUND',
                       'No clean standard exists for clean_type %s' % clean_type, 404)
    if expected != s['version']:
        raise ApiError('ERR_STALE_STANDARD_VERSION',
                       'expected_standard_version does not match the current version', 412)
    s['base_minutes'] = base_minutes
    s['outbreak_multiplier_bps'] = mult
    s['atp_rlu_threshold'] = threshold
    touch(s)
    return success_object(standard_dict(s))
