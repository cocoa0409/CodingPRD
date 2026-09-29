"""Screening rooms, review sessions and director notes."""
from datetime import timedelta

from flask import Blueprint

from calc import (COLOR_SPACES, by_created, calibration_status, note_out,
                  recompute_note_count, room_out, session_notes, session_out)
from flows import (enter_retake, fk_lookup, get_note, get_production, get_room,
                   get_session, get_task, reconcile_tasks, require_phase)
from helpers import (ALL_READ, ApiError, DIRECTOR, PM, arg, authenticate, body_json,
                     get_datetime, get_enum, get_int, get_str, paginate, success)
from store import base_row, db, now, touch

bp = Blueprint('rooms', __name__)

SESSION_TYPES = ('DAILIES', 'DIRECTOR_REVIEW', 'CLIENT_REVIEW')
SEVERITIES = ('MINOR', 'MAJOR', 'BLOCKING')
NOT_WRAPPED = ('PRE_PRODUCTION', 'PRODUCTION_ACTIVE', 'DELIVERY')


@bp.route('/studio/screening-rooms', methods=['POST'])
def create_room():
    authenticate((PM,))
    body = body_json()
    name = get_str(body, 'name', min_len=1)
    seat_capacity = get_int(body, 'seat_capacity', minimum=1)
    room_color_space = get_enum(body, 'room_color_space', COLOR_SPACES)
    turnover = get_int(body, 'turnover_buffer_minutes', required=False, default=30,
                       minimum=0)
    valid_days = get_int(body, 'calibration_valid_days', required=False, default=30,
                         minimum=1)
    room = base_row()
    room.update({
        'name': name,
        'seat_capacity': seat_capacity,
        'turnover_buffer_minutes': turnover,
        'room_color_space': room_color_space,
        'calibration_valid_days': valid_days,
        'last_calibrated_at': None,
    })
    db.rooms[room['id']] = room
    return success(room_out(room), 201)


@bp.route('/studio/screening-rooms', methods=['GET'])
def list_rooms():
    authenticate(ALL_READ)
    rows = list(db.rooms.values())
    status = arg('calibration_status')
    if status is not None:
        rows = [r for r in rows if calibration_status(r) == status]
    return paginate(by_created(rows), room_out)


@bp.route('/studio/screening-rooms/<room_id>', methods=['GET'])
def read_room(room_id):
    authenticate(ALL_READ)
    return success(room_out(get_room(room_id)))


@bp.route('/studio/screening-rooms/<room_id>/calibrate', methods=['POST'])
def calibrate_room(room_id):
    authenticate((PM,))
    room = get_room(room_id)
    room['last_calibrated_at'] = now()
    touch(room)
    return success(room_out(room))


# --------------------------------------------------------------- review sessions
@bp.route('/studio/review-sessions', methods=['POST'])
def create_session():
    authenticate((DIRECTOR,))
    body = body_json()
    production = fk_lookup(body, 'production_id', get_production)
    room = fk_lookup(body, 'screening_room_id', get_room)
    production_id = get_str(body, 'production_id', min_len=1)
    room_id = get_str(body, 'screening_room_id', min_len=1)
    session_type = get_enum(body, 'session_type', SESSION_TYPES)
    window_start = get_datetime(body, 'window_start')
    window_end = get_datetime(body, 'window_end')
    attendee_count = get_int(body, 'attendee_count', required=False, default=1, minimum=1)
    if production is None:
        production = get_production(production_id)
    if room is None:
        room = get_room(room_id)
    require_phase(production, ('PRODUCTION_ACTIVE',))
    if session_type == 'CLIENT_REVIEW':
        if room['room_color_space'] not in production['approved_color_spaces']:
            raise ApiError('ERR_COLOR_PIPELINE_MISMATCH', 422,
                           'the room color space is not approved for this production')
    if room['last_calibrated_at'] is None:
        raise ApiError('ERR_ROOM_NOT_CALIBRATED', 422,
                       'the room has never been calibrated')
    if not window_start < window_end or window_start < now():
        raise ApiError('ERR_INVALID_WINDOW', 422,
                       'the session window is not a future half-open interval')
    buffer_delta = timedelta(minutes=room['turnover_buffer_minutes'])
    expanded_start = window_start - buffer_delta
    expanded_end = window_end + buffer_delta
    for other in db.sessions.values():
        if other['screening_room_id'] != room['id']:
            continue
        if other['status'] not in ('SCHEDULED', 'IN_PROGRESS'):
            continue
        if expanded_start < other['window_end'] and expanded_end > other['window_start']:
            raise ApiError('ERR_ROOM_WINDOW_CONFLICT', 409,
                           'the room is not free for the buffered window')
    if attendee_count > room['seat_capacity']:
        raise ApiError('ERR_ROOM_SEAT_CAPACITY_EXCEEDED', 422,
                       'attendee_count exceeds the room seat capacity')
    session = base_row()
    session.update({
        'production_id': production['id'],
        'screening_room_id': room['id'],
        'session_type': session_type,
        'window_start': window_start,
        'window_end': window_end,
        'attendee_count': attendee_count,
        'status': 'SCHEDULED',
        'opened_at': None,
        'closed_at': None,
        'note_count': 0,
        'retake_issued_count': 0,
    })
    db.sessions[session['id']] = session
    return success(session_out(session), 201)


@bp.route('/studio/review-sessions', methods=['GET'])
def list_sessions():
    authenticate(ALL_READ)
    rows = list(db.sessions.values())
    production_id = arg('production_id')
    if production_id is not None:
        rows = [r for r in rows if r['production_id'] == production_id]
    room_id = arg('screening_room_id')
    if room_id is not None:
        rows = [r for r in rows if r['screening_room_id'] == room_id]
    session_type = arg('session_type')
    if session_type is not None:
        rows = [r for r in rows if r['session_type'] == session_type]
    status = arg('status')
    if status is not None:
        rows = [r for r in rows if r['status'] == status]
    rows.sort(key=lambda s: (s['window_start'], s['created_at'], s['_seq']))
    return paginate(rows, session_out)


@bp.route('/studio/review-sessions/<session_id>', methods=['GET'])
def read_session(session_id):
    authenticate(ALL_READ)
    return success(session_out(get_session(session_id)))


@bp.route('/studio/review-sessions/<session_id>/start', methods=['POST'])
def start_session(session_id):
    authenticate((DIRECTOR,))
    session = get_session(session_id)
    production = db.productions.get(session['production_id'])
    require_phase(production, ('PRODUCTION_ACTIVE', 'DELIVERY'))
    if session['status'] != 'SCHEDULED':
        raise ApiError('ERR_SESSION_STATE_INVALID', 409,
                       'a session in %s may not be started' % session['status'])
    room = db.rooms.get(session['screening_room_id'])
    if room is None or calibration_status(room) != 'CALIBRATED':
        raise ApiError('ERR_CALIBRATION_EXPIRED', 422,
                       'the room calibration is not currently valid')
    session['status'] = 'IN_PROGRESS'
    session['opened_at'] = now()
    touch(session)
    return success(session_out(session))


@bp.route('/studio/review-sessions/<session_id>/close', methods=['POST'])
def close_session(session_id):
    authenticate((DIRECTOR,))
    session = get_session(session_id)
    production = db.productions.get(session['production_id'])
    require_phase(production, NOT_WRAPPED)
    if session['status'] != 'IN_PROGRESS':
        raise ApiError('ERR_SESSION_STATE_INVALID', 409,
                       'a session in %s may not be closed' % session['status'])
    session['status'] = 'CLOSED'
    session['closed_at'] = now()
    issued = 0
    retaken = []
    for note in session_notes(session):
        if note['status'] != 'OPEN' or note['severity'] not in ('MAJOR', 'BLOCKING'):
            continue
        note['status'] = 'RETAKE_ISSUED'
        touch(note)
        issued += 1
        task = db.tasks.get(note['shot_stage_task_id'])
        if task is not None and task['status'] in ('SUBMITTED', 'IN_REVIEW', 'APPROVED'):
            enter_retake(task)
            retaken.append(task)
    session['retake_issued_count'] = issued
    touch(session)
    reconcile_tasks(retaken)
    return success(session_out(session))


@bp.route('/studio/review-sessions/<session_id>/cancel', methods=['POST'])
def cancel_session(session_id):
    authenticate((DIRECTOR, PM))
    session = get_session(session_id)
    body = body_json()
    get_str(body, 'reason', required=False)
    production = db.productions.get(session['production_id'])
    require_phase(production, NOT_WRAPPED)
    if session['status'] not in ('SCHEDULED', 'IN_PROGRESS'):
        raise ApiError('ERR_SESSION_STATE_INVALID', 409,
                       'a session in %s may not be cancelled' % session['status'])
    session['status'] = 'CANCELLED'
    session['closed_at'] = now()
    for note in session_notes(session):
        if note['status'] == 'OPEN':
            note['status'] = 'WAIVED'
            note['resolved_by_user_id'] = None
            touch(note)
    touch(session)
    return success(session_out(session))


# ---------------------------------------------------------------- director notes
@bp.route('/studio/director-notes', methods=['POST'])
def create_note():
    user_id, _role = authenticate((DIRECTOR,))
    body = body_json()
    session = fk_lookup(body, 'review_session_id', get_session)
    task = fk_lookup(body, 'shot_stage_task_id', get_task)
    session_id = get_str(body, 'review_session_id', min_len=1)
    task_id = get_str(body, 'shot_stage_task_id', min_len=1)
    severity = get_enum(body, 'severity', SEVERITIES)
    note_text = get_str(body, 'note_text', min_len=1, max_len=2000)
    if session is None:
        session = get_session(session_id)
    if task is None:
        task = get_task(task_id)
    production = db.productions.get(session['production_id'])
    require_phase(production, ('PRODUCTION_ACTIVE',))
    if session['status'] != 'IN_PROGRESS':
        raise ApiError('ERR_SESSION_STATE_INVALID', 409,
                       'notes may only be raised on an IN_PROGRESS session')
    shot = db.shots.get(task['shot_id'])
    if shot is None or shot['production_id'] != session['production_id']:
        raise ApiError('ERR_CROSS_PRODUCTION_REFERENCE', 422,
                       'the target task belongs to another production')
    note = base_row()
    note.update({
        'review_session_id': session['id'],
        'shot_stage_task_id': task['id'],
        'severity': severity,
        'note_text': note_text,
        'status': 'OPEN',
        'raised_by_user_id': user_id,
        'resolved_by_user_id': None,
    })
    db.notes[note['id']] = note
    if recompute_note_count(session):
        touch(session)
    if task['status'] == 'SUBMITTED':
        task['status'] = 'IN_REVIEW'
        touch(task)
    return success(note_out(note), 201)


@bp.route('/studio/director-notes', methods=['GET'])
def list_notes():
    authenticate(ALL_READ)
    rows = list(db.notes.values())
    session_id = arg('review_session_id')
    if session_id is not None:
        rows = [r for r in rows if r['review_session_id'] == session_id]
    task_id = arg('shot_stage_task_id')
    if task_id is not None:
        rows = [r for r in rows if r['shot_stage_task_id'] == task_id]
    severity = arg('severity')
    if severity is not None:
        rows = [r for r in rows if r['severity'] == severity]
    status = arg('status')
    if status is not None:
        rows = [r for r in rows if r['status'] == status]
    return paginate(by_created(rows), note_out)


@bp.route('/studio/director-notes/<note_id>', methods=['GET'])
def read_note(note_id):
    authenticate(ALL_READ)
    return success(note_out(get_note(note_id)))


@bp.route('/studio/director-notes/<note_id>/resolution', methods=['POST'])
def resolve_note(note_id):
    user_id, _role = authenticate((DIRECTOR,))
    note = get_note(note_id)
    body = body_json()
    resolution = get_enum(body, 'resolution', ('RESOLVED', 'WAIVED'))
    session = db.sessions.get(note['review_session_id'])
    production = db.productions.get(session['production_id']) if session else None
    require_phase(production, NOT_WRAPPED)
    if note['status'] not in ('OPEN', 'RETAKE_ISSUED'):
        raise ApiError('ERR_NOTE_STATE_INVALID', 409,
                       'a note in %s may not be resolved' % note['status'])
    if resolution == 'RESOLVED':
        task = db.tasks.get(note['shot_stage_task_id'])
        if task is None or task['status'] != 'APPROVED':
            raise ApiError('ERR_TASK_STATE_INVALID', 409,
                           'the target stage task is not APPROVED')
    note['status'] = resolution
    note['resolved_by_user_id'] = user_id
    touch(note)
    return success(note_out(note))
