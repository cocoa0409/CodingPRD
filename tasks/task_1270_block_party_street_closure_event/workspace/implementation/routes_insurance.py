"""Insurance certificates / waiver requests (OCC-guarded create, supersede)."""
from flask import Blueprint

from auth import auth, own_or_403
from calc import (MIN_COVERAGE_CENTS, WAIVER_MAX_ATTENDANCE, get_application,
                  get_insurance, get_segment)
from envelope import ok, created, ok_list
from errors import ApiError
from store import db, entity, touch
from validate import body, req, as_str, as_int, as_enum, as_date

bp = Blueprint('insurance', __name__)

INS_ROLES = ['Organizer', 'SafetyReviewer', 'PermitOfficer', 'CityAdmin']
KINDS = ['CERTIFICATE', 'WAIVER_REQUEST']


@bp.route('/permit-applications/<aid>/insurance-certificates', methods=['POST'])
def create_insurance(aid):
    uid, role = auth(['Organizer'])
    app = get_application(aid)
    own_or_403(role, uid, app['organizer_id'])
    b = body()
    kind = as_enum(req(b, 'kind'), 'kind', KINDS)
    expected = as_int(req(b, 'expected_application_version'), 'expected_application_version')
    fields = {}
    if kind == 'CERTIFICATE':
        fields = {
            'insurer_name': as_str(req(b, 'insurer_name'), 'insurer_name'),
            'policy_number': as_str(req(b, 'policy_number'), 'policy_number'),
            'coverage_amount_cents': as_int(req(b, 'coverage_amount_cents'), 'coverage_amount_cents'),
            'expires_on': as_date(req(b, 'expires_on'), 'expires_on'),
        }
    else:
        fields = {
            'insurer_name': b.get('insurer_name'),
            'policy_number': b.get('policy_number'),
            'coverage_amount_cents': b.get('coverage_amount_cents'),
            'expires_on': as_date(b['expires_on'], 'expires_on') if b.get('expires_on') is not None else None,
        }
    if expected != app['version']:
        raise ApiError('ERR_STALE_APPLICATION_VERSION',
                       'expected_application_version does not match the current version', 412)
    if app['status'] not in ('UNDER_REVIEW', 'SUSPENDED', 'APPROVED'):
        raise ApiError('ERR_INVALID_STATE',
                       'Application state %s does not permit insurance filing' % app['status'], 409)
    for r in db.insurance.values():
        if r['application_id'] == aid and r['status'] in ('VERIFIED', 'WAIVER_GRANTED'):
            raise ApiError('ERR_INVALID_STATE',
                           'Insurance is already satisfied for this application', 409)
    rec = entity(application_id=aid, kind=kind, status='SUBMITTED',
                 reviewed_by=None, review_note=None, superseded_by_id=None, **fields)
    db.insurance[rec['id']] = rec
    for r in db.insurance.values():
        if (r['application_id'] == aid and r['id'] != rec['id']
                and r['status'] in ('SUBMITTED', 'REJECTED', 'WAIVER_DENIED')):
            r['status'] = 'SUPERSEDED'
            r['superseded_by_id'] = rec['id']
            touch(r)
    touch(app)  # creating a record bumps the parent application version
    return created(rec)


@bp.route('/permit-applications/<aid>/insurance-certificates', methods=['GET'])
def list_insurance(aid):
    uid, role = auth(INS_ROLES)
    app = get_application(aid)
    own_or_403(role, uid, app['organizer_id'])
    return ok_list([r for r in db.insurance.values() if r['application_id'] == aid])


@bp.route('/insurance-certificates/<iid>', methods=['GET'])
def get_one_insurance(iid):
    uid, role = auth(INS_ROLES)
    rec = get_insurance(iid)
    app = get_application(rec['application_id'])
    own_or_403(role, uid, app['organizer_id'])
    return ok(rec)


@bp.route('/insurance-certificates/<iid>/review', methods=['POST'])
def review_insurance(iid):
    uid, role = auth(['SafetyReviewer'])
    rec = get_insurance(iid)
    b = body()
    decision = req(b, 'decision')
    if decision not in ('APPROVE', 'DENY'):
        raise ApiError('ERR_INVALID_REQUEST', 'decision must be APPROVE or DENY', 400)
    if rec['status'] != 'SUBMITTED':
        raise ApiError('ERR_INVALID_STATE', 'Insurance record is not SUBMITTED', 409)
    app = get_application(rec['application_id'])
    if decision == 'APPROVE':
        if rec['kind'] == 'CERTIFICATE':
            if rec['expires_on'] < app['event_start_at'].date():
                raise ApiError('ERR_INSURANCE_EXPIRED',
                               'Policy expires before the event date', 422)
            if rec['coverage_amount_cents'] < MIN_COVERAGE_CENTS:
                raise ApiError('ERR_INSURANCE_COVERAGE_INSUFFICIENT',
                               'Coverage is below the $1M minimum', 422)
            rec['status'] = 'VERIFIED'
        else:
            seg = get_segment(app['segment_id'])
            if not (app['expected_attendance'] <= WAIVER_MAX_ATTENDANCE
                    and not app['alcohol_served']
                    and seg['segment_kind'] == 'RESIDENTIAL'):
                raise ApiError('ERR_WAIVER_INELIGIBLE',
                               'Application does not qualify for an insurance waiver', 422)
            rec['status'] = 'WAIVER_GRANTED'
        rec['reviewed_by'] = uid
    else:
        rec['status'] = 'REJECTED' if rec['kind'] == 'CERTIFICATE' else 'WAIVER_DENIED'
        rec['reviewed_by'] = uid
        rec['review_note'] = b.get('note')
    touch(rec)
    return ok(rec)
