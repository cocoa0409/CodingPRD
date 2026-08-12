"""Traffic control plans and sound plans."""
from flask import Blueprint

from auth import auth, own_or_403
from calc import ceil_div, get_application, get_segment, get_tcp, get_sound, find_tcp, find_sound
from envelope import ok, created, ok_list
from errors import ApiError
from store import db, entity, touch
from validate import body, req, as_str, as_int, as_num, as_bool, as_hhmm

bp = Blueprint('plans', __name__)

TCP_ROLES = ['Organizer', 'TrafficReviewer', 'PermitOfficer', 'CityAdmin']
SOUND_ROLES = ['Organizer', 'SafetyReviewer', 'PermitOfficer', 'CityAdmin']


def _validate_tcp_fields(b, cur=None):
    def pick(name, validate):
        v = b.get(name)
        if v is None:
            if cur is None:
                return validate(req(b, name), name)
            return cur[name]
        return validate(v, name)
    out = {
        'barricade_count': pick('barricade_count', as_int),
        'cone_count': pick('cone_count', as_int),
        'sign_count': pick('sign_count', as_int),
        'emergency_lane_width_m': pick('emergency_lane_width_m', as_num),
        'emergency_lane_continuous': pick('emergency_lane_continuous', as_bool),
        'placement_notes': pick('placement_notes', as_str),
    }
    for k in ('barricade_count', 'cone_count', 'sign_count'):
        if out[k] < 0:
            raise ApiError('ERR_INVALID_REQUEST', '%s must be >= 0' % k, 400)
    return out


@bp.route('/permit-applications/<aid>/traffic-control-plans', methods=['POST'])
def create_tcp(aid):
    uid, role = auth(['Organizer'])
    app = get_application(aid)
    own_or_403(role, uid, app['organizer_id'])
    if app['status'] not in ('DRAFT', 'UNDER_REVIEW', 'SUSPENDED'):
        raise ApiError('ERR_INVALID_STATE',
                       'Application state %s does not permit plan creation' % app['status'], 409)
    if find_tcp(aid) is not None:
        raise ApiError('ERR_DUPLICATE_RESOURCE',
                       'A traffic control plan already exists for this application', 409)
    fields = _validate_tcp_fields(body())
    tcp = entity(application_id=aid, status='DRAFT', reviewed_by=None,
                 review_note=None, locked_at_version=None, **fields)
    db.tcps[tcp['id']] = tcp
    return created(tcp)


@bp.route('/permit-applications/<aid>/traffic-control-plans', methods=['GET'])
def list_tcps(aid):
    uid, role = auth(TCP_ROLES)
    app = get_application(aid)
    own_or_403(role, uid, app['organizer_id'])
    return ok_list([t for t in db.tcps.values() if t['application_id'] == aid])


@bp.route('/traffic-control-plans/<tid>', methods=['GET'])
def get_one_tcp(tid):
    uid, role = auth(TCP_ROLES)
    tcp = get_tcp(tid)
    app = get_application(tcp['application_id'])
    own_or_403(role, uid, app['organizer_id'])
    return ok(tcp)


@bp.route('/traffic-control-plans/<tid>', methods=['PATCH'])
def patch_tcp(tid):
    uid, role = auth(['Organizer'])
    tcp = get_tcp(tid)
    app = get_application(tcp['application_id'])
    own_or_403(role, uid, app['organizer_id'])
    if tcp['status'] not in ('DRAFT', 'CHANGES_REQUESTED'):
        raise ApiError('ERR_INVALID_STATE',
                       'Only DRAFT or CHANGES_REQUESTED plans can be updated', 409)
    fields = _validate_tcp_fields(body(), cur=tcp)
    tcp.update(fields)
    touch(tcp)
    return ok(tcp)


@bp.route('/traffic-control-plans/<tid>/submit', methods=['POST'])
def submit_tcp(tid):
    uid, role = auth(['Organizer'])
    tcp = get_tcp(tid)
    app = get_application(tcp['application_id'])
    own_or_403(role, uid, app['organizer_id'])
    if tcp['status'] not in ('DRAFT', 'CHANGES_REQUESTED'):
        raise ApiError('ERR_INVALID_STATE', 'Plan is not in a submittable state', 409)
    if app['status'] not in ('UNDER_REVIEW', 'SUSPENDED'):
        raise ApiError('ERR_INVALID_STATE',
                       'Application must be UNDER_REVIEW or SUSPENDED to submit the plan', 409)
    if not tcp['emergency_lane_continuous'] or tcp['emergency_lane_width_m'] < 6.0:
        raise ApiError('ERR_EMERGENCY_LANE_VIOLATION',
                       'Emergency lane must be continuous and at least 6.0m wide', 422)
    seg = get_segment(app['segment_id'])
    required = ceil_div(seg['length_m'], 12) + (4 if seg['intersects_arterial'] else 0)
    if tcp['barricade_count'] < required:
        raise ApiError('ERR_BARRICADE_PLAN_INSUFFICIENT',
                       'barricade_count below the required minimum of %d' % required, 422)
    tcp['status'] = 'SUBMITTED'
    touch(tcp)
    return ok(tcp)


@bp.route('/traffic-control-plans/<tid>/review', methods=['POST'])
def review_tcp(tid):
    uid, role = auth(['TrafficReviewer'])
    tcp = get_tcp(tid)
    b = body()
    decision = req(b, 'decision')
    if decision not in ('APPROVE', 'REQUEST_CHANGES'):
        raise ApiError('ERR_INVALID_REQUEST',
                       'decision must be APPROVE or REQUEST_CHANGES', 400)
    if tcp['status'] != 'SUBMITTED':
        raise ApiError('ERR_INVALID_STATE', 'Plan is not SUBMITTED', 409)
    tcp['status'] = 'TCP_APPROVED' if decision == 'APPROVE' else 'CHANGES_REQUESTED'
    tcp['reviewed_by'] = uid
    tcp['review_note'] = b.get('note')
    touch(tcp)
    return ok(tcp)


# ---------------------------------------------------------------- sound ---

@bp.route('/permit-applications/<aid>/sound-plans', methods=['POST'])
def create_sound(aid):
    uid, role = auth(['Organizer'])
    app = get_application(aid)
    own_or_403(role, uid, app['organizer_id'])
    if app['status'] not in ('UNDER_REVIEW', 'SUSPENDED'):
        raise ApiError('ERR_INVALID_STATE',
                       'Application state %s does not permit sound plan creation' % app['status'], 409)
    if not app['amplified_sound']:
        raise ApiError('ERR_SOUND_NOT_REQUESTED',
                       'The application does not request amplified sound', 409)
    if find_sound(aid) is not None:
        raise ApiError('ERR_DUPLICATE_RESOURCE',
                       'A sound plan already exists for this application', 409)
    b = body()
    speaker_count = as_int(req(b, 'speaker_count'), 'speaker_count')
    if speaker_count <= 0:
        raise ApiError('ERR_INVALID_REQUEST', 'speaker_count must be > 0', 400)
    max_db = as_int(req(b, 'max_db_at_property_line'), 'max_db_at_property_line')
    if max_db <= 0:
        raise ApiError('ERR_INVALID_REQUEST', 'max_db_at_property_line must be > 0', 400)
    planned = as_hhmm(req(b, 'planned_sound_end'), 'planned_sound_end')
    sp = entity(application_id=aid, speaker_count=speaker_count,
                max_db_at_property_line=max_db,
                planned_sound_end='%02d:%02d' % planned,
                status='DRAFT', reviewed_by=None, review_note=None,
                locked_at_version=None)
    db.sound_plans[sp['id']] = sp
    return created(sp)


@bp.route('/permit-applications/<aid>/sound-plans', methods=['GET'])
def list_sound(aid):
    uid, role = auth(SOUND_ROLES)
    app = get_application(aid)
    own_or_403(role, uid, app['organizer_id'])
    return ok_list([s for s in db.sound_plans.values() if s['application_id'] == aid])


@bp.route('/sound-plans/<sid>', methods=['GET'])
def get_one_sound(sid):
    uid, role = auth(SOUND_ROLES)
    sp = get_sound(sid)
    app = get_application(sp['application_id'])
    own_or_403(role, uid, app['organizer_id'])
    return ok(sp)


@bp.route('/sound-plans/<sid>/submit', methods=['POST'])
def submit_sound(sid):
    uid, role = auth(['Organizer'])
    sp = get_sound(sid)
    app = get_application(sp['application_id'])
    own_or_403(role, uid, app['organizer_id'])
    if sp['status'] not in ('DRAFT', 'CHANGES_REQUESTED'):
        raise ApiError('ERR_INVALID_STATE', 'Sound plan is not in a submittable state', 409)
    if app['status'] not in ('UNDER_REVIEW', 'SUSPENDED'):
        raise ApiError('ERR_INVALID_STATE',
                       'Application must be UNDER_REVIEW or SUSPENDED to submit the plan', 409)
    if sp['max_db_at_property_line'] > 70:
        raise ApiError('ERR_SOUND_DB_EXCEEDED',
                       'max_db_at_property_line exceeds the 70 dB cap', 422)
    cutoff = (22, 0) if app['event_start_at'].weekday() in (4, 5) else (21, 0)
    h, m = (int(sp['planned_sound_end'][:2]), int(sp['planned_sound_end'][3:5]))
    if (h, m) > cutoff:
        raise ApiError('ERR_SOUND_CUTOFF_VIOLATION',
                       'planned_sound_end is past the %02d:%02d cutoff for the event day' % cutoff,
                       422)
    sp['status'] = 'SUBMITTED'
    touch(sp)
    return ok(sp)


@bp.route('/sound-plans/<sid>/review', methods=['POST'])
def review_sound(sid):
    uid, role = auth(['SafetyReviewer'])
    sp = get_sound(sid)
    b = body()
    decision = req(b, 'decision')
    if decision not in ('APPROVE', 'REQUEST_CHANGES'):
        raise ApiError('ERR_INVALID_REQUEST',
                       'decision must be APPROVE or REQUEST_CHANGES', 400)
    if sp['status'] != 'SUBMITTED':
        raise ApiError('ERR_INVALID_STATE', 'Sound plan is not SUBMITTED', 409)
    sp['status'] = 'SOUND_APPROVED' if decision == 'APPROVE' else 'CHANGES_REQUESTED'
    sp['reviewed_by'] = uid
    sp['review_note'] = b.get('note')
    touch(sp)
    return ok(sp)
