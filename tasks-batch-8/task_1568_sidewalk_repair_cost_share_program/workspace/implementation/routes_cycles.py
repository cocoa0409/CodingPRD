"""ProgramCycle endpoints: create/read/lock/close/appropriation-adjustments."""
from flask import Blueprint

from db import db, base_entity, touch
from errors import ApiError, not_found
from middleware import require_roles
from response import ok_object
from util import parse_date
from validation import get_body, validate

bp = Blueprint('cycles', __name__)


def _window_overlaps(start, end):
    """Closed-interval semantics: end == other's start IS an overlap."""
    for c in db.cycles.values():
        s = parse_date(c['window_start_date'])
        e = parse_date(c['window_end_date'])
        if start <= e and s <= end:
            return True
    return False


@bp.post('/program-cycles')
@require_roles('ProgramCoordinator')
def create_cycle():
    body = get_body()
    vals = validate(body, [
        ('cycle_year', 'int', True, {}),
        ('window_start_date', 'date', True, {}),
        ('window_end_date', 'date', True, {}),
        ('appropriation_cents', 'int', True, {'positive': True}),
    ])
    if not vals['window_end_date'] > vals['window_start_date']:
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'window_end_date must be strictly after window_start_date')
    if _window_overlaps(vals['window_start_date'], vals['window_end_date']):
        raise ApiError('ERR_CYCLE_WINDOW_OVERLAP', 409,
                       'Cycle window overlaps an existing cycle window')
    c = base_entity()
    c.update({
        'cycle_year': vals['cycle_year'],
        'window_start_date': vals['window_start_date'].isoformat(),
        'window_end_date': vals['window_end_date'].isoformat(),
        'appropriation_cents': vals['appropriation_cents'],
        'committed_cents': 0,
        'disbursed_cents': 0,
        'available_cents': vals['appropriation_cents'],
        'status': 'OPEN',
    })
    db.cycles[c['id']] = c
    from services import ser_cycle
    return ok_object(ser_cycle(c), 201)


@bp.get('/program-cycles/<cid>')
@require_roles(*['ProgramCoordinator', 'Inspector', 'PropertyOwner', 'Contractor',
                 'ForestryOfficer', 'FinanceOfficer', 'HearingOfficer'])
def get_cycle(cid):
    c = db.cycles.get(cid)
    if not c:
        raise not_found('cycle')
    from services import ser_cycle
    return ok_object(ser_cycle(c))


@bp.post('/program-cycles/<cid>/lock')
@require_roles('ProgramCoordinator')
def lock_cycle(cid):
    c = db.cycles.get(cid)
    if not c:
        raise not_found('cycle')
    if c['status'] != 'OPEN':
        raise ApiError('ERR_INVALID_CYCLE_STATE', 409, 'Cycle is not OPEN')
    c['status'] = 'LOCKED'
    touch(c)
    from services import ser_cycle
    return ok_object(ser_cycle(c))


@bp.post('/program-cycles/<cid>/close')
@require_roles('ProgramCoordinator')
def close_cycle(cid):
    c = db.cycles.get(cid)
    if not c:
        raise not_found('cycle')
    if c['status'] != 'LOCKED':
        raise ApiError('ERR_INVALID_CYCLE_STATE', 409, 'Cycle is not LOCKED')
    from services import IN_FLIGHT_APP_STATUSES
    if any(a['cycle_id'] == cid and a['review_status'] in IN_FLIGHT_APP_STATUSES
           for a in db.applications.values()):
        raise ApiError('ERR_CYCLE_HAS_OPEN_APPLICATIONS', 409,
                       'Cycle has in-flight applications')
    c['status'] = 'CLOSED'
    touch(c)
    from services import ser_cycle
    return ok_object(ser_cycle(c))


@bp.post('/program-cycles/<cid>/appropriation-adjustments')
@require_roles('FinanceOfficer')
def adjust_cycle(cid):
    body = get_body()
    vals = validate(body, [
        ('delta_cents', 'int', True, {}),
        ('expected_program_cycle_version', 'int', True, {}),
    ])
    c = db.cycles.get(cid)
    if not c:
        raise not_found('cycle')
    if vals['expected_program_cycle_version'] != c['version']:
        raise ApiError('ERR_STALE_CYCLE_VERSION', 412,
                       'expected_program_cycle_version does not match current version')
    new_app = c['appropriation_cents'] + vals['delta_cents']
    if new_app < c['committed_cents'] + c['disbursed_cents']:
        raise ApiError('ERR_APPROPRIATION_BELOW_OBLIGATIONS', 422,
                       'Appropriation would fall below committed plus disbursed')
    c['appropriation_cents'] = new_app
    from services import recompute_cycle_available
    recompute_cycle_available(c)
    touch(c)
    from services import ser_cycle
    return ok_object(ser_cycle(c))
