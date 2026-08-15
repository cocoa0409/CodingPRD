"""Post-event cleanup reports and inspection."""
from datetime import timedelta
from flask import Blueprint

from auth import auth, own_or_403
from calc import (REPORT_WINDOW_HOURS, get_application, get_report, find_deposit,
                  find_report, post_charge)
from envelope import ok, created, ok_list
from errors import ApiError
from store import db, entity, now, touch
from validate import body, req, as_str, as_bool, as_int

bp = Blueprint('reports', __name__)

REPORT_ROLES = ['Organizer', 'PermitOfficer', 'CityAdmin']


@bp.route('/permit-applications/<aid>/post-event-reports', methods=['POST'])
def create_report(aid):
    uid, role = auth(['Organizer'])
    app = get_application(aid)
    own_or_403(role, uid, app['organizer_id'])
    if app['status'] != 'ISSUED':
        raise ApiError('ERR_INVALID_STATE', 'Application is not ISSUED', 409)
    t = now()
    if not (app['event_end_at'] < t
            <= app['event_end_at'] + timedelta(hours=REPORT_WINDOW_HOURS)):
        raise ApiError('ERR_REPORT_WINDOW_CLOSED',
                       'Report window (event_end_at, event_end_at + 72h] is closed', 422)
    if find_report(aid) is not None:
        raise ApiError('ERR_DUPLICATE_RESOURCE',
                       'A post-event report already exists for this application', 409)
    b = body()
    rep = entity(
        application_id=aid,
        cleanup_completed=as_bool(req(b, 'cleanup_completed'), 'cleanup_completed'),
        cleanup_notes=as_str(req(b, 'cleanup_notes'), 'cleanup_notes'),
        submitted_at=t,
        inspection_result='PENDING',
        inspected_by=None,
        cleaning_charge_cents=0,
    )
    db.reports[rep['id']] = rep
    return created(rep)


@bp.route('/permit-applications/<aid>/post-event-reports', methods=['GET'])
def list_reports(aid):
    uid, role = auth(REPORT_ROLES)
    app = get_application(aid)
    own_or_403(role, uid, app['organizer_id'])
    return ok_list([r for r in db.reports.values() if r['application_id'] == aid])


@bp.route('/post-event-reports/<rid>', methods=['GET'])
def get_one_report(rid):
    uid, role = auth(REPORT_ROLES)
    rep = get_report(rid)
    app = get_application(rep['application_id'])
    own_or_403(role, uid, app['organizer_id'])
    return ok(rep)


@bp.route('/post-event-reports/<rid>/inspect', methods=['POST'])
def inspect_report(rid):
    uid, role = auth(['PermitOfficer'])
    rep = get_report(rid)
    b = body()
    result = req(b, 'result')
    if result not in ('PASSED', 'FAILED'):
        raise ApiError('ERR_INVALID_REQUEST', 'result must be PASSED or FAILED', 400)
    if rep['inspection_result'] != 'PENDING':
        raise ApiError('ERR_INVALID_STATE', 'Report has already been inspected', 409)
    charge = 0
    if b.get('cleaning_charge_cents') is not None:
        charge = as_int(b['cleaning_charge_cents'], 'cleaning_charge_cents')
        if charge < 0:
            raise ApiError('ERR_INVALID_REQUEST', 'cleaning_charge_cents must be >= 0', 400)
    rep['inspection_result'] = result
    rep['inspected_by'] = uid
    if result == 'FAILED':
        rep['cleaning_charge_cents'] = charge
        if charge > 0:
            dep = find_deposit(rep['application_id'])
            if dep is not None and dep['status'] == 'HELD':
                post_charge(dep, 'CLEANING', charge,
                            'Cleaning charge from failed inspection',
                            source_reservation_id=None)
    touch(rep)
    return ok(rep)
