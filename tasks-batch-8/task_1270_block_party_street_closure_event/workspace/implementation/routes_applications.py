"""Permit applications: CRUD, OCC-guarded patch, and lifecycle transitions."""
from datetime import timedelta
from flask import Blueprint, request

from auth import auth, own_or_403, REVIEW_ROLES
from calc import (APP_STATUSES, LEAD_DAYS, ensure_fresh, get_application,
                  get_petition, get_segment, find_tcp, find_sound, find_pool,
                  find_deposit, find_report, app_reservations, check_event_window,
                  segment_conflict, provisional_fee, final_fee, invoice_line,
                  release_reservations, deposit_auto_settle, pool_refund_chain,
                  unwind_pre_issuance)
from envelope import ok, created, ok_list
from errors import ApiError
from store import db, entity, now, touch
from validate import body, req, as_str, as_int, as_dt, opt_bool
from routes_petitions import _acting_organizer

bp = Blueprint('applications', __name__)


def _validate_window(start, end):
    check_event_window(start, end)


@bp.route('/permit-applications', methods=['POST'])
def create_application():
    uid, role = auth(['Organizer'])
    _acting_organizer(uid)
    b = body()
    petition_id = as_str(req(b, 'petition_id'), 'petition_id')
    start = as_dt(req(b, 'event_start_at'), 'event_start_at')
    end = as_dt(req(b, 'event_end_at'), 'event_end_at')
    att = as_int(req(b, 'expected_attendance'), 'expected_attendance')
    if att <= 0:
        raise ApiError('ERR_INVALID_REQUEST', 'expected_attendance must be > 0', 400)
    pet = get_petition(petition_id)
    if pet['organizer_id'] != uid:
        raise ApiError('ERR_NOT_RESOURCE_OWNER', 'Petition belongs to another organizer', 403)
    if pet['status'] not in ('COLLECTING', 'SUBMITTED', 'VERIFIED', 'DEFICIENT'):
        raise ApiError('ERR_INVALID_STATE',
                       'Backing petition is not in a state that accepts applications', 409)
    _validate_window(start, end)
    app = entity(
        organizer_id=uid,
        petition_id=pet['id'],
        segment_id=pet['segment_id'],
        event_start_at=start,
        event_end_at=end,
        expected_attendance=att,
        amplified_sound=opt_bool(b, 'amplified_sound', False),
        alcohol_served=opt_bool(b, 'alcohol_served', False),
        food_vendors=opt_bool(b, 'food_vendors', False),
        status='DRAFT',
        provisional_fee_cents=None,
        final_fee_cents=None,
        equipment_total_cents=None,
        decision_reason=None,
    )
    db.applications[app['id']] = app
    return created(app)


@bp.route('/permit-applications', methods=['GET'])
def list_applications():
    auth(['PermitOfficer', 'CityAdmin'])
    rows = list(db.applications.values())
    for a in rows:
        ensure_fresh(a)
    status = request.args.get('status')
    if status is not None:
        if status not in APP_STATUSES:
            raise ApiError('ERR_INVALID_REQUEST', 'Unknown status filter', 400)
        rows = [a for a in rows if a['status'] == status]
    organizer_id = request.args.get('organizer_id')
    if organizer_id is not None:
        rows = [a for a in rows if a['organizer_id'] == organizer_id]
    return ok_list(rows)


@bp.route('/permit-applications/<aid>', methods=['GET'])
def get_one_application(aid):
    uid, role = auth(REVIEW_ROLES)
    app = get_application(aid)
    own_or_403(role, uid, app['organizer_id'])
    return ok(app)


@bp.route('/permit-applications/<aid>', methods=['PATCH'])
def patch_application(aid):
    uid, role = auth(['Organizer'])
    app = get_application(aid)
    own_or_403(role, uid, app['organizer_id'])
    b = body()
    expected = as_int(req(b, 'expected_application_version'), 'expected_application_version')
    if expected != app['version']:
        raise ApiError('ERR_STALE_APPLICATION_VERSION',
                       'expected_application_version does not match the current version', 412)
    if app['status'] != 'DRAFT':
        raise ApiError('ERR_INVALID_STATE', 'Only DRAFT applications can be updated', 409)
    start = as_dt(b['event_start_at'], 'event_start_at') if b.get('event_start_at') is not None else app['event_start_at']
    end = as_dt(b['event_end_at'], 'event_end_at') if b.get('event_end_at') is not None else app['event_end_at']
    att = app['expected_attendance']
    if b.get('expected_attendance') is not None:
        att = as_int(b['expected_attendance'], 'expected_attendance')
        if att <= 0:
            raise ApiError('ERR_INVALID_REQUEST', 'expected_attendance must be > 0', 400)
    _validate_window(start, end)
    app['event_start_at'] = start
    app['event_end_at'] = end
    app['expected_attendance'] = att
    for f in ('amplified_sound', 'alcohol_served', 'food_vendors'):
        if b.get(f) is not None:
            app[f] = opt_bool(b, f, app[f])
    touch(app)
    return ok(app)


@bp.route('/permit-applications/<aid>/submit', methods=['POST'])
def submit_application(aid):
    uid, role = auth(['Organizer'])
    app = get_application(aid)
    own_or_403(role, uid, app['organizer_id'])
    if app['status'] != 'DRAFT':
        raise ApiError('ERR_INVALID_STATE', 'Application is not DRAFT', 409)
    pet = get_petition(app['petition_id'])
    if pet['status'] != 'VERIFIED':
        raise ApiError('ERR_PETITION_NOT_VERIFIED', 'Backing petition is not VERIFIED', 409)
    seg = get_segment(app['segment_id'])
    deadline = now() + timedelta(days=LEAD_DAYS[seg['jurisdiction']])
    if app['event_start_at'] < deadline:
        raise ApiError('ERR_LEAD_TIME_INSUFFICIENT',
                       'event_start_at is earlier than the jurisdiction lead time', 422)
    if segment_conflict(app):
        raise ApiError('ERR_SEGMENT_WINDOW_CONFLICT',
                       'Window overlaps another application on the same segment', 409)
    app['provisional_fee_cents'] = provisional_fee(app, seg, find_tcp(aid))
    app['status'] = 'UNDER_REVIEW'
    touch(app)
    return ok(app)


@bp.route('/permit-applications/<aid>/approve', methods=['POST'])
def approve_application(aid):
    auth(['PermitOfficer'])
    app = get_application(aid)
    if app['status'] != 'UNDER_REVIEW':
        raise ApiError('ERR_INVALID_STATE', 'Application is not UNDER_REVIEW', 409)
    pet = get_petition(app['petition_id'])
    if pet['status'] != 'VERIFIED':
        raise ApiError('ERR_PETITION_NOT_VERIFIED', 'Backing petition is not VERIFIED', 409)
    tcp = find_tcp(aid)
    if tcp is None or tcp['status'] != 'TCP_APPROVED':
        raise ApiError('ERR_TCP_NOT_APPROVED',
                       'Traffic control plan missing or not TCP_APPROVED', 409)
    if app['amplified_sound']:
        sp = find_sound(aid)
        if sp is None or sp['status'] != 'SOUND_APPROVED':
            raise ApiError('ERR_SOUND_PLAN_NOT_APPROVED',
                           'Sound plan missing or not SOUND_APPROVED', 409)
    insured = any(r['application_id'] == aid and r['status'] in ('VERIFIED', 'WAIVER_GRANTED')
                  for r in db.insurance.values())
    if not insured:
        raise ApiError('ERR_INSURANCE_NOT_SATISFIED',
                       'No insurance record in VERIFIED or WAIVER_GRANTED', 409)
    planned = {'BARRICADE': tcp['barricade_count'], 'CONE': tcp['cone_count'],
               'SIGN': tcp['sign_count']}
    held = {'BARRICADE': 0, 'CONE': 0, 'SIGN': 0}
    for r in app_reservations(aid):
        if r['reservation_status'] in ('HELD', 'CONFIRMED'):
            held[r['equipment_kind']] += r['units']
    for kind, need in planned.items():
        if held[kind] < need:
            raise ApiError('ERR_EQUIPMENT_NOT_RESERVED',
                           'Held/confirmed reservations do not cover the planned %s count' % kind,
                           409)
    dep = find_deposit(aid)
    if dep is None or dep['status'] != 'HELD':
        raise ApiError('ERR_DEPOSIT_REQUIRED', 'No deposit in HELD status', 409)
    app['status'] = 'APPROVED'
    touch(app)
    return ok(app)


@bp.route('/permit-applications/<aid>/deny', methods=['POST'])
def deny_application(aid):
    auth(['PermitOfficer'])
    app = get_application(aid)
    b = body()
    reason = as_str(req(b, 'reason'), 'reason')
    if app['status'] != 'UNDER_REVIEW':
        raise ApiError('ERR_INVALID_STATE', 'Application is not UNDER_REVIEW', 409)
    app['status'] = 'DENIED'
    app['decision_reason'] = reason
    touch(app)
    unwind_pre_issuance(app)
    return ok(app)


@bp.route('/permit-applications/<aid>/issue', methods=['POST'])
def issue_application(aid):
    auth(['PermitOfficer'])
    app = get_application(aid)
    if app['status'] != 'APPROVED':
        raise ApiError('ERR_INVALID_STATE', 'Application is not APPROVED', 409)
    pet = get_petition(app['petition_id'])
    if pet['status'] != 'VERIFIED':
        raise ApiError('ERR_PETITION_NOT_VERIFIED', 'Backing petition is not VERIFIED', 409)
    if segment_conflict(app):
        raise ApiError('ERR_SEGMENT_WINDOW_CONFLICT',
                       'Window overlaps another application on the same segment', 409)
    # Lock the petition.
    pet['status'] = 'LOCKED'
    touch(pet)
    # Lock approved plans, pinning their current versions.
    tcp = find_tcp(aid)
    if tcp is not None and tcp['status'] == 'TCP_APPROVED':
        tcp['locked_at_version'] = tcp['version']
        tcp['status'] = 'LOCKED'
        touch(tcp)
    sp = find_sound(aid)
    if sp is not None and sp['status'] == 'SOUND_APPROVED':
        sp['locked_at_version'] = sp['version']
        sp['status'] = 'LOCKED'
        touch(sp)
    # Confirm held reservations; per-line pretax + per-line tax.
    equipment_total = 0
    for r in app_reservations(aid):
        if r['reservation_status'] == 'HELD':
            r['reservation_status'] = 'CONFIRMED'
            if r['billing_status'] == 'UNBILLED':
                r['billing_status'] = 'INVOICED'
            r['invoice_cents'] = invoice_line(r['units'], r['equipment_kind'])
            equipment_total += r['invoice_cents']
            touch(r)
    seg = get_segment(app['segment_id'])
    app['equipment_total_cents'] = equipment_total
    app['final_fee_cents'] = final_fee(app, seg, equipment_total)
    app['status'] = 'ISSUED'
    touch(app)
    return ok(app)


@bp.route('/permit-applications/<aid>/cancel', methods=['POST'])
def cancel_application(aid):
    uid, role = auth(['Organizer'])
    app = get_application(aid)
    own_or_403(role, uid, app['organizer_id'])
    b = body()
    reason = b.get('reason')
    if reason is not None:
        reason = as_str(reason, 'reason')
    st = app['status']
    if st == 'DRAFT':
        app['status'] = 'CANCELLED'
        app['decision_reason'] = reason
        touch(app)
        return ok(app)
    if st in ('UNDER_REVIEW', 'SUSPENDED', 'APPROVED'):
        app['status'] = 'CANCELLED'
        app['decision_reason'] = reason
        touch(app)
        unwind_pre_issuance(app)
        return ok(app)
    if st == 'ISSUED':
        if any(r['reservation_status'] == 'DISPATCHED' for r in app_reservations(aid)):
            raise ApiError('ERR_INVALID_STATE',
                           'Equipment is dispatched; return it before cancelling', 409)
        app['status'] = 'CANCELLED'
        app['decision_reason'] = reason
        touch(app)
        release_reservations(app, recall=False)
        deposit_auto_settle(app)
        pool_refund_chain(app)
        return ok(app)
    raise ApiError('ERR_INVALID_STATE', 'Application cannot be cancelled from %s' % st, 409)


@bp.route('/permit-applications/<aid>/revoke', methods=['POST'])
def revoke_application(aid):
    auth(['PermitOfficer'])
    app = get_application(aid)
    b = body()
    reason = as_str(req(b, 'reason'), 'reason')
    if app['status'] != 'ISSUED':
        raise ApiError('ERR_INVALID_STATE', 'Application is not ISSUED', 409)
    if any(r['reservation_status'] == 'DISPATCHED' for r in app_reservations(aid)):
        raise ApiError('ERR_INVALID_STATE',
                       'Equipment is dispatched; return it before revoking', 409)
    app['status'] = 'REVOKED'
    app['decision_reason'] = reason
    touch(app)
    release_reservations(app, recall=True)
    deposit_auto_settle(app)
    pool_refund_chain(app)
    return ok(app)


@bp.route('/permit-applications/<aid>/complete', methods=['POST'])
def complete_application(aid):
    auth(['PermitOfficer'])
    app = get_application(aid)
    if app['status'] != 'ISSUED':
        raise ApiError('ERR_INVALID_STATE', 'Application is not ISSUED', 409)
    def unmet(msg):
        raise ApiError('ERR_COMPLETION_PRECONDITIONS', msg, 409)
    if now() <= app['event_end_at']:
        unmet('Event has not ended yet')
    rep = find_report(aid)
    if rep is None or rep['inspection_result'] != 'PASSED':
        unmet('Latest post-event report has not PASSED inspection')
    for r in app_reservations(aid):
        if r['reservation_status'] not in ('CLOSED', 'CANCELLED', 'RECALLED'):
            unmet('Not all equipment reservations are terminal')
    dep = find_deposit(aid)
    if dep is not None and dep['status'] not in ('SETTLED', 'FORFEITED'):
        unmet('Deposit is not settled')
    pool = find_pool(aid)
    if pool is not None and pool['status'] not in ('CLOSED', 'REFUNDED'):
        unmet('Cost-share pool is not closed or refunded')
    app['status'] = 'COMPLETED'
    touch(app)
    return ok(app)
