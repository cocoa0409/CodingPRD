"""Routes: clean requests, staff, quality audits."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request as freq

from common import (ApiError, as_enum, as_int, as_number, as_str, authorize, do_list,
                    json_body, new_id, now, opt_field, parse_dt, req_field,
                    success_object)
from logic import (CERTIFICATIONS, CLEAN_TYPES, OPEN_REQUEST_STATUSES,
                   TERMINAL_REQUEST_STATUSES, audit_dict, audit_result, apply_fail,
                   apply_pass, bom_lines, certification_covers, create_clean_request,
                   item_by_code, on_hand, productivity_score, request_dict,
                   request_tier, reserved_qty, staff_dict, staff_window_conflict,
                   stat_eligible, touch, write_ledger)
from store import store

bp = Blueprint('work', __name__)


def get_request(request_id):
    r = store.requests.get(request_id)
    if r is None:
        raise ApiError('ERR_CLEAN_REQUEST_NOT_FOUND',
                       'Clean request %s not found' % request_id, 404)
    return r


def get_staff(staff_id):
    s = store.staff.get(staff_id)
    if s is None:
        raise ApiError('ERR_STAFF_NOT_FOUND', 'Staff member %s not found' % staff_id, 404)
    return s


def get_audit(audit_id):
    a = store.audits.get(audit_id)
    if a is None:
        raise ApiError('ERR_AUDIT_NOT_FOUND', 'Quality audit %s not found' % audit_id, 404)
    return a


def check_terminal_or(req, expected_statuses, wrong_state_error):
    if req['status'] in TERMINAL_REQUEST_STATUSES:
        raise ApiError('ERR_REQUEST_ALREADY_TERMINAL',
                       'Clean request is already in a terminal state', 409)
    if req['status'] not in expected_statuses:
        raise ApiError(wrong_state_error,
                       'Clean request is not in a valid state for this operation', 409)


def safety_gates(req, staff, reclean_check):
    if not certification_covers(staff, req['clean_type']):
        raise ApiError('ERR_STAFF_CERTIFICATION_MISMATCH',
                       'Staff certifications do not cover clean_type %s'
                       % req['clean_type'], 422)
    if request_tier(req) == 'STAT' and not stat_eligible(staff):
        raise ApiError('ERR_STAFF_NOT_STAT_ELIGIBLE',
                       'STAT-tier assignment requires a stat-eligible staff member', 422)
    if reclean_check and staff['id'] == req['last_completed_by_staff_id']:
        raise ApiError('ERR_RECLEAN_SAME_TECHNICIAN',
                       'Reclean must be assigned to a different technician', 422)


def buffer_check(req, staff, planned_start):
    planned_end = planned_start + timedelta(minutes=req['sla_target_minutes'])
    if staff_window_conflict(staff['id'], req['id'], planned_start, planned_end):
        raise ApiError('ERR_STAFF_DOUBLE_BOOKED',
                       'Planned window conflicts with another assigned window', 409)


# ----------------------------------------------------------- clean requests
@bp.route('/evs/clean-requests', methods=['POST'])
def create_request():
    body = json_body()
    bed_id = as_str(req_field(body, 'bed_id'), 'bed_id')
    clean_type = as_enum(req_field(body, 'clean_type'), 'clean_type', CLEAN_TYPES)
    authorize(['EVSDispatcher'])
    bed = store.beds.get(bed_id)
    if bed is None:
        raise ApiError('ERR_BED_NOT_FOUND', 'Bed %s not found' % bed_id, 404)
    from logic import standard_by_type
    if standard_by_type(clean_type) is None:
        raise ApiError('ERR_STANDARD_NOT_FOUND',
                       'No clean standard exists for clean_type %s' % clean_type, 404)
    if bed['bed_status'] != 'VACANT_DIRTY':
        raise ApiError('ERR_BED_NOT_DIRTY',
                       'Manual clean-request creation requires bed_status VACANT_DIRTY', 409)
    if any(r for r in store.requests.values()
           if r['bed_id'] == bed_id and r['status'] in OPEN_REQUEST_STATUSES):
        raise ApiError('ERR_OPEN_REQUEST_EXISTS',
                       'Bed already has an open clean request', 409)
    req = create_clean_request(bed, clean_type)
    return success_object(request_dict(req), 201)


@bp.route('/evs/clean-requests', methods=['GET'])
def list_requests():
    bed_id = freq.args.get('bed_id')
    unit_id = freq.args.get('unit_id')
    status = freq.args.get('status')
    assigned = freq.args.get('assigned_staff_id')
    tier = freq.args.get('priority_tier')

    def f(r):
        if bed_id is not None and r['bed_id'] != bed_id:
            return False
        if unit_id is not None and r['unit_id'] != unit_id:
            return False
        if status is not None and r['status'] != status:
            return False
        if assigned is not None and r['assigned_staff_id'] != assigned:
            return False
        if tier is not None and request_tier(r) != tier:
            return False
        return True

    return do_list(list(store.requests.values()), request_dict, f)


@bp.route('/evs/clean-requests/<request_id>', methods=['GET'])
def get_request_route(request_id):
    authorize(['Any'])
    return success_object(request_dict(get_request(request_id)))


@bp.route('/evs/clean-requests/<request_id>/assign', methods=['POST'])
def assign_request(request_id):
    body = json_body()
    staff_id = as_str(req_field(body, 'staff_id'), 'staff_id')
    planned_in = opt_field(body, 'planned_start_at')
    if planned_in is not None:
        planned_in = parse_dt(planned_in, 'planned_start_at')
    authorize(['EVSDispatcher'])
    req = get_request(request_id)
    staff = get_staff(staff_id)
    check_terminal_or(req, ['QUEUED', 'NEEDS_RECLEAN'], 'ERR_REQUEST_NOT_QUEUED')
    safety_gates(req, staff, reclean_check=(req['status'] == 'NEEDS_RECLEAN'))
    planned_start = planned_in if planned_in is not None else now()
    buffer_check(req, staff, planned_start)
    req['status'] = 'ASSIGNED'
    req['assigned_staff_id'] = staff['id']
    req['planned_start_at'] = planned_start
    touch(req)
    return success_object(request_dict(req))


@bp.route('/evs/clean-requests/<request_id>/reassign', methods=['POST'])
def reassign_request(request_id):
    body = json_body()
    staff_id = as_str(req_field(body, 'staff_id'), 'staff_id')
    expected = as_int(req_field(body, 'expected_clean_request_version'),
                      'expected_clean_request_version')
    planned_in = opt_field(body, 'planned_start_at')
    if planned_in is not None:
        planned_in = parse_dt(planned_in, 'planned_start_at')
    authorize(['EVSDispatcher'])
    req = get_request(request_id)
    staff = get_staff(staff_id)
    if expected != req['version']:
        raise ApiError('ERR_STALE_REQUEST_VERSION',
                       'expected_clean_request_version does not match the current version',
                       412)
    check_terminal_or(req, ['ASSIGNED'], 'ERR_REQUEST_NOT_ASSIGNED')
    safety_gates(req, staff, reclean_check=False)
    planned_start = planned_in if planned_in is not None else now()
    buffer_check(req, staff, planned_start)
    req['assigned_staff_id'] = staff['id']
    req['planned_start_at'] = planned_start
    touch(req)
    return success_object(request_dict(req))


@bp.route('/evs/clean-requests/<request_id>/unassign', methods=['POST'])
def unassign_request(request_id):
    json_body()
    authorize(['EVSDispatcher'])
    req = get_request(request_id)
    check_terminal_or(req, ['ASSIGNED'], 'ERR_REQUEST_NOT_ASSIGNED')
    req['status'] = 'QUEUED'
    req['assigned_staff_id'] = None
    req['planned_start_at'] = None
    touch(req)
    return success_object(request_dict(req))


@bp.route('/evs/clean-requests/<request_id>/start', methods=['POST'])
def start_request(request_id):
    json_body()
    ctx = authorize(['EVSTechnician'])
    req = get_request(request_id)
    if req['assigned_staff_id'] != ctx.user_id:
        raise ApiError('ERR_NOT_ASSIGNED_TECHNICIAN',
                       'Only the assigned technician may start this request', 403)
    check_terminal_or(req, ['ASSIGNED'], 'ERR_REQUEST_NOT_ASSIGNED')
    staff = ctx.staff
    if staff['shift_status'] != 'ON_SHIFT':
        raise ApiError('ERR_STAFF_NOT_ON_SHIFT', 'Start requires shift_status ON_SHIFT', 409)
    lines = bom_lines(req['clean_type'], req['reclean_count'])
    for code, qty in lines:
        item = item_by_code(code)
        available = (on_hand(item['id']) - reserved_qty(item)) if item is not None else 0
        if item is None or available < qty:
            raise ApiError('ERR_INSUFFICIENT_SUPPLY',
                           'Insufficient supply of %s for clean start' % code, 422)
    now_ = now()
    req['status'] = 'IN_PROGRESS'
    req['started_at'] = now_
    if req['first_started_at'] is None:
        req['first_started_at'] = now_
    req['supply_reserved'] = True
    req['_reserved_lines'] = {code: qty for code, qty in lines}
    touch(req)
    bed = store.beds[req['bed_id']]
    bed['bed_status'] = 'CLEAN_IN_PROGRESS'
    touch(bed)
    return success_object(request_dict(req))


@bp.route('/evs/clean-requests/<request_id>/complete', methods=['POST'])
def complete_request(request_id):
    json_body()
    ctx = authorize(['EVSTechnician'])
    req = get_request(request_id)
    if req['assigned_staff_id'] != ctx.user_id:
        raise ApiError('ERR_NOT_ASSIGNED_TECHNICIAN',
                       'Only the assigned technician may complete this request', 403)
    check_terminal_or(req, ['IN_PROGRESS'], 'ERR_REQUEST_NOT_IN_PROGRESS')
    now_ = now()
    req['status'] = 'PENDING_QA'
    req['completed_at'] = now_
    req['last_completed_by_staff_id'] = req['assigned_staff_id']
    for code, qty in (req['_reserved_lines'] or {}).items():
        item = item_by_code(code)
        write_ledger(item['id'], 'CONSUME', -qty, clean_request_id=req['id'])
    req['supply_reserved'] = False
    req['_reserved_lines'] = None
    req['assigned_staff_id'] = None
    req['planned_start_at'] = None
    touch(req)
    bed = store.beds[req['bed_id']]
    bed['bed_status'] = 'AWAITING_VERIFICATION'
    touch(bed)
    return success_object(request_dict(req))


@bp.route('/evs/clean-requests/<request_id>/cancel', methods=['POST'])
def cancel_request(request_id):
    json_body()
    authorize(['EVSDispatcher'])
    req = get_request(request_id)
    if req['status'] in TERMINAL_REQUEST_STATUSES:
        raise ApiError('ERR_REQUEST_ALREADY_TERMINAL',
                       'Clean request is already in a terminal state', 409)
    if req['status'] in ('QUEUED', 'ASSIGNED'):
        req['assigned_staff_id'] = None
        req['planned_start_at'] = None
    elif req['status'] == 'IN_PROGRESS':
        req['supply_reserved'] = False
        req['_reserved_lines'] = None
        req['assigned_staff_id'] = None
        req['planned_start_at'] = None
        bed = store.beds[req['bed_id']]
        bed['bed_status'] = 'VACANT_DIRTY'
        touch(bed)
    else:
        raise ApiError('ERR_REQUEST_NOT_QUEUED',
                       'Clean request cannot be cancelled from its current state', 409)
    req['status'] = 'CANCELLED'
    touch(req)
    return success_object(request_dict(req))


@bp.route('/evs/clean-requests/pull', methods=['POST'])
def pull_request():
    json_body()
    ctx = authorize(['EVSTechnician'])
    staff = ctx.staff
    if staff['shift_status'] != 'ON_SHIFT':
        raise ApiError('ERR_STAFF_NOT_ON_SHIFT', 'Pull requires shift_status ON_SHIFT', 409)
    from logic import request_score, TIER_RANK
    now_ = now()
    eligible = []
    for r in store.requests.values():
        if r['status'] != 'QUEUED':
            continue
        if not certification_covers(staff, r['clean_type']):
            continue
        if request_tier(r) == 'STAT' and not stat_eligible(staff):
            continue
        new_start = now_
        new_end = now_ + timedelta(minutes=r['sla_target_minutes'])
        if staff_window_conflict(staff['id'], r['id'], new_start, new_end):
            continue
        eligible.append(r)
    if not eligible:
        raise ApiError('ERR_QUEUE_EMPTY', 'No eligible queued clean request', 409)
    eligible.sort(key=lambda r: (-TIER_RANK[request_tier(r)], -request_score(r),
                                 r['sla_due_at'], r['created_at'], r['_seq']))
    chosen = eligible[0]
    chosen['status'] = 'ASSIGNED'
    chosen['assigned_staff_id'] = staff['id']
    chosen['planned_start_at'] = now_
    touch(chosen)
    return success_object(request_dict(chosen))


# -------------------------------------------------------------------- staff
@bp.route('/evs/staff', methods=['POST'])
def create_staff():
    body = json_body()
    employee_code = as_str(req_field(body, 'employee_code'), 'employee_code')
    display_name = as_str(req_field(body, 'display_name'), 'display_name')
    capabilities = req_field(body, 'capabilities')
    if not isinstance(capabilities, list) or len(capabilities) == 0:
        raise ApiError('ERR_INVALID_REQUEST',
                       'capabilities must be a non-empty list', 400)
    for c in capabilities:
        as_enum(c, 'capabilities', ['CLEAN', 'AUDIT'])
    certifications = opt_field(body, 'certifications', [])
    if not isinstance(certifications, list):
        raise ApiError('ERR_INVALID_REQUEST', 'certifications must be a list', 400)
    for c in certifications:
        as_enum(c, 'certifications', CERTIFICATIONS)
    authorize(['EVSAdministrator'])
    now_ = now()
    s = {'id': new_id(), 'employee_code': employee_code, 'display_name': display_name,
         'capabilities': capabilities, 'certifications': certifications,
         'shift_status': 'OFF_SHIFT', 'completed_clean_count': 0,
         'verified_credit_total': Decimal('0'), 'qa_fail_count': 0,
         'shift_seconds_today': 0, 'last_clock_in_at': None, 'break_started_at': None,
         'created_at': now_, 'updated_at': now_, 'version': 1, '_seq': store.next_seq()}
    store.staff[s['id']] = s
    return success_object(staff_dict(s), 201)


@bp.route('/evs/staff', methods=['GET'])
def list_staff():
    shift_status = freq.args.get('shift_status')

    def f(s):
        if shift_status is not None and s['shift_status'] != shift_status:
            return False
        return True

    return do_list(list(store.staff.values()), staff_dict, f)


@bp.route('/evs/staff/<staff_id>', methods=['GET'])
def get_staff_route(staff_id):
    authorize(['Any'])
    return success_object(staff_dict(get_staff(staff_id)))


@bp.route('/evs/staff/<staff_id>/productivity', methods=['GET'])
def get_productivity(staff_id):
    authorize(['Any'])
    s = get_staff(staff_id)
    return success_object({
        'productivity_score': float(productivity_score(s)),
        'verified_credit_total': float(s['verified_credit_total']),
        'qa_fail_count': s['qa_fail_count'],
        'shift_seconds_today': s['shift_seconds_today'],
        'stat_eligible': stat_eligible(s),
        'completed_clean_count': s['completed_clean_count'],
    })


def _shift_common(staff_id, roles=('EVSTechnician', 'QualityAuditor')):
    json_body()
    ctx = authorize(list(roles))
    staff = get_staff(staff_id)
    if ctx.user_id != staff_id:
        raise ApiError('ERR_STAFF_IDENTITY_MISMATCH',
                       'X-User-ID must equal the path staff_id', 403)
    return staff


@bp.route('/evs/staff/<staff_id>/clock-in', methods=['POST'])
def clock_in(staff_id):
    staff = _shift_common(staff_id)
    if staff['shift_status'] != 'OFF_SHIFT':
        raise ApiError('ERR_STAFF_ALREADY_ON_SHIFT', 'Clock-in requires OFF_SHIFT', 409)
    staff['shift_status'] = 'ON_SHIFT'
    staff['last_clock_in_at'] = now()
    touch(staff)
    return success_object(staff_dict(staff))


@bp.route('/evs/staff/<staff_id>/clock-out', methods=['POST'])
def clock_out(staff_id):
    staff = _shift_common(staff_id)
    if staff['shift_status'] == 'OFF_SHIFT':
        raise ApiError('ERR_STAFF_NOT_ON_SHIFT',
                       'Clock-out requires ON_SHIFT or ON_BREAK', 409)
    if any(r for r in store.requests.values()
           if r['assigned_staff_id'] == staff['id']
           and r['status'] in ('ASSIGNED', 'IN_PROGRESS')):
        raise ApiError('ERR_STAFF_HAS_ACTIVE_CLEANS',
                       'Clock-out is blocked while cleans are assigned or in progress', 409)
    if staff['shift_status'] == 'ON_SHIFT':
        staff['shift_seconds_today'] += int((now() - staff['last_clock_in_at']).total_seconds())
    staff['shift_status'] = 'OFF_SHIFT'
    staff['last_clock_in_at'] = None
    staff['break_started_at'] = None
    touch(staff)
    return success_object(staff_dict(staff))


@bp.route('/evs/staff/<staff_id>/break-start', methods=['POST'])
def break_start(staff_id):
    staff = _shift_common(staff_id)
    if staff['shift_status'] != 'ON_SHIFT':
        raise ApiError('ERR_STAFF_NOT_ON_SHIFT', 'Break-start requires ON_SHIFT', 409)
    if any(r for r in store.requests.values()
           if r['assigned_staff_id'] == staff['id'] and r['status'] == 'IN_PROGRESS'):
        raise ApiError('ERR_STAFF_HAS_ACTIVE_CLEANS',
                       'Break-start is blocked while a clean is in progress', 409)
    staff['shift_seconds_today'] += int((now() - staff['last_clock_in_at']).total_seconds())
    staff['break_started_at'] = now()
    staff['shift_status'] = 'ON_BREAK'
    touch(staff)
    return success_object(staff_dict(staff))


@bp.route('/evs/staff/<staff_id>/break-end', methods=['POST'])
def break_end(staff_id):
    staff = _shift_common(staff_id)
    if staff['shift_status'] != 'ON_BREAK':
        raise ApiError('ERR_STAFF_NOT_ON_BREAK', 'Break-end requires ON_BREAK', 409)
    staff['last_clock_in_at'] = now()
    staff['break_started_at'] = None
    staff['shift_status'] = 'ON_SHIFT'
    touch(staff)
    return success_object(staff_dict(staff))


# ------------------------------------------------------------ quality audits
@bp.route('/evs/quality-audits', methods=['POST'])
def create_audit():
    body = json_body()
    clean_request_id = as_str(req_field(body, 'clean_request_id'), 'clean_request_id')
    audit_method = as_enum(req_field(body, 'audit_method'), 'audit_method',
                           ['ATP_SWAB', 'FLUORESCENT_MARKER'])
    rlu = body.get('rlu_reading')
    marker = body.get('marker_fraction_removed')
    if audit_method == 'ATP_SWAB':
        if marker is not None:
            raise ApiError('ERR_AUDIT_METHOD_FIELD_MISMATCH',
                           'ATP_SWAB audits must not carry marker_fraction_removed', 400)
        if rlu is None:
            raise ApiError('ERR_AUDIT_METHOD_FIELD_MISMATCH',
                           'ATP_SWAB audits require rlu_reading', 400)
        rlu = as_int(rlu, 'rlu_reading')
    else:
        if rlu is not None:
            raise ApiError('ERR_AUDIT_METHOD_FIELD_MISMATCH',
                           'FLUORESCENT_MARKER audits must not carry rlu_reading', 400)
        if marker is None:
            raise ApiError('ERR_AUDIT_METHOD_FIELD_MISMATCH',
                           'FLUORESCENT_MARKER audits require marker_fraction_removed', 400)
        marker_dec = as_number(marker, 'marker_fraction_removed')
        if marker_dec < 0 or marker_dec > 1:
            raise ApiError('ERR_INVALID_REQUEST',
                           'marker_fraction_removed must be between 0 and 1 inclusive', 400)
    ctx = authorize(['QualityAuditor'])
    req = store.requests.get(clean_request_id)
    if req is None:
        raise ApiError('ERR_CLEAN_REQUEST_NOT_FOUND',
                       'Clean request %s not found' % clean_request_id, 404)
    check_terminal_or(req, ['PENDING_QA'], 'ERR_REQUEST_NOT_PENDING_QA')
    if ctx.user_id == req['last_completed_by_staff_id']:
        raise ApiError('ERR_AUDITOR_IS_CLEANER',
                       'The auditor may not verify their own work', 422)
    result, threshold_used = audit_result(req['clean_type'], audit_method, rlu, marker)
    unit = store.units[req['unit_id']]
    now_ = now()
    a = {'id': new_id(), 'clean_request_id': req['id'], 'auditor_id': ctx.user_id,
         'audit_method': audit_method,
         'rlu_reading': rlu if audit_method == 'ATP_SWAB' else None,
         'marker_fraction_removed': (float(Decimal(str(marker)))
                                     if audit_method == 'FLUORESCENT_MARKER' else None),
         'result': result, 'threshold_used': threshold_used, 'audit_status': 'SUBMITTED',
         'created_ops_run_index': unit['ops_run_index'],
         'created_at': now_, 'updated_at': now_, 'version': 1, '_seq': store.next_seq()}
    store.audits[a['id']] = a
    if result == 'PASS':
        apply_pass(req)
    else:
        apply_fail(req)
    return success_object(audit_dict(a), 201)


@bp.route('/evs/quality-audits', methods=['GET'])
def list_audits():
    clean_request_id = freq.args.get('clean_request_id')
    auditor_id = freq.args.get('auditor_id')
    result = freq.args.get('result')

    def f(a):
        if clean_request_id is not None and a['clean_request_id'] != clean_request_id:
            return False
        if auditor_id is not None and a['auditor_id'] != auditor_id:
            return False
        if result is not None and a['result'] != result:
            return False
        return True

    return do_list(list(store.audits.values()), audit_dict, f)


@bp.route('/evs/quality-audits/<audit_id>', methods=['GET'])
def get_audit_route(audit_id):
    authorize(['Any'])
    return success_object(audit_dict(get_audit(audit_id)))


@bp.route('/evs/quality-audits/<audit_id>/void', methods=['POST'])
def void_audit(audit_id):
    json_body()
    authorize(['InfectionPreventionist'])
    a = get_audit(audit_id)
    if a['audit_status'] != 'SUBMITTED':
        raise ApiError('ERR_AUDIT_NOT_SUBMITTED', 'Void requires audit_status SUBMITTED', 409)
    req = store.requests.get(a['clean_request_id'])
    if a['result'] != 'FAIL' or req is None or req['status'] != 'NEEDS_RECLEAN':
        raise ApiError('ERR_AUDIT_NOT_VOIDABLE',
                       'Void requires a FAIL audit with the request still NEEDS_RECLEAN', 409)
    unit = store.units[req['unit_id']]
    if a['created_ops_run_index'] != unit['ops_run_index']:
        raise ApiError('ERR_AUDIT_VOID_WINDOW_CLOSED',
                       'An ops-run has closed since the audit was submitted', 409)
    a['audit_status'] = 'VOIDED'
    touch(a)
    req['status'] = 'PENDING_QA'
    touch(req)
    completer = store.staff.get(req['last_completed_by_staff_id'])
    if completer is not None:
        completer['qa_fail_count'] -= 1
        touch(completer)
    bed = store.beds[req['bed_id']]
    bed['bed_status'] = 'AWAITING_VERIFICATION'
    touch(bed)
    return success_object(audit_dict(a))
