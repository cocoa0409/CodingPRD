"""Deliverable versioning, colour compliance and final shipping."""
import re

from flask import Blueprint

from calc import (COLOR_SPACES, D, by_created, deliverable_group, deliverable_out,
                  version_label)
from flows import (fk_lookup, get_deliverable, get_production, get_shot, require_phase)
from helpers import (ALL_READ, ApiError, PM, SUPERVISOR, arg, authenticate, body_json,
                     get_enum, get_int, get_number, get_str, paginate, success,
                     validation_error)
from store import base_row, db, now, touch

bp = Blueprint('deliverables', __name__)

DELIVERABLE_TYPES = ('MASTER_EXR', 'PROXY_MP4', 'AUDIO_STEM', 'SHOT_PLATE')
FRAME_RATES = ('23.976', '24.0', '25.0', '29.97', '30.0')
BIT_DEPTHS = (8, 10, 12, 16)
RESOLUTION_RE = re.compile(r'^[0-9]{3,5}x[0-9]{3,5}$')
CREATE_PHASES = ('PRODUCTION_ACTIVE', 'DELIVERY')


def _scope_shot_ids(deliverable):
    """The shot when shot_id is set, otherwise every shot of the production."""
    if deliverable['shot_id'] is not None:
        return {deliverable['shot_id']}
    return {s['id'] for s in db.shots.values()
            if s['production_id'] == deliverable['production_id']}


@bp.route('/studio/deliverables', methods=['POST'])
def create_deliverable():
    authenticate((PM,))
    body = body_json()
    production = fk_lookup(body, 'production_id', get_production)
    shot = fk_lookup(body, 'shot_id', get_shot)
    production_id = get_str(body, 'production_id', min_len=1)
    deliverable_type = get_enum(body, 'deliverable_type', DELIVERABLE_TYPES)
    color_space = get_enum(body, 'color_space', COLOR_SPACES)
    resolution = get_str(body, 'resolution', min_len=1)
    expected_version = get_int(body, 'expected_production_version')
    raw_shot = body.get('shot_id') if isinstance(body, dict) else None
    if raw_shot is not None and (not isinstance(raw_shot, str) or not raw_shot.strip()):
        raise validation_error('shot_id must be a non-empty string when supplied')
    frame_rate = get_number(body, 'frame_rate', required=False, default=D('24.0'),
                            places=None, choices=FRAME_RATES)
    bit_depth = get_int(body, 'bit_depth', required=False, default=16,
                        choices=BIT_DEPTHS)
    if not RESOLUTION_RE.match(resolution):
        raise validation_error('resolution must look like 3840x2160')
    if production is None:
        production = get_production(production_id)
    if expected_version != production['version']:
        raise ApiError('ERR_STALE_PRODUCTION_VERSION', 412,
                       'expected_production_version does not match the stored version')
    require_phase(production, CREATE_PHASES)
    if color_space not in production['approved_color_spaces']:
        raise ApiError('ERR_COLOR_PIPELINE_MISMATCH', 422,
                       '%s is not an approved color space of this production'
                       % color_space)
    if deliverable_type == 'MASTER_EXR' and color_space != production['master_color_space']:
        raise ApiError('ERR_COLOR_PIPELINE_MISMATCH', 422,
                       'a MASTER_EXR must carry the production master color space')
    if shot is not None and shot['production_id'] != production['id']:
        raise ApiError('ERR_CROSS_PRODUCTION_REFERENCE', 422,
                       'shot_id belongs to a different production')
    shot_id = shot['id'] if shot is not None else None
    group = deliverable_group(production['id'], deliverable_type, shot_id)
    for sibling in group:
        if sibling['status'] in ('DRAFT', 'SUBMITTED'):
            raise ApiError('ERR_DELIVERABLE_VERSION_CONFLICT', 409,
                           'a version of this group is already in flight')
    index = len(group) + 1
    deliverable = base_row()
    deliverable.update({
        'production_id': production['id'],
        'shot_id': shot_id,
        'deliverable_type': deliverable_type,
        'color_space': color_space,
        'resolution': resolution,
        'frame_rate': D(frame_rate),
        'bit_depth': bit_depth,
        'version_index': index,
        'version_label': version_label(index),
        'status': 'DRAFT',
        'qc_note': None,
        'delivered_at': None,
    })
    db.deliverables[deliverable['id']] = deliverable
    for sibling in by_created(group):
        if sibling['status'] == 'QC_PASSED':
            sibling['status'] = 'SUPERSEDED'
            touch(sibling)
    touch(production)
    return success(deliverable_out(deliverable), 201)


@bp.route('/studio/deliverables', methods=['GET'])
def list_deliverables():
    authenticate(ALL_READ)
    rows = list(db.deliverables.values())
    production_id = arg('production_id')
    if production_id is not None:
        rows = [r for r in rows if r['production_id'] == production_id]
    shot_id = arg('shot_id')
    if shot_id is not None:
        rows = [r for r in rows if r['shot_id'] == shot_id]
    deliverable_type = arg('deliverable_type')
    if deliverable_type is not None:
        rows = [r for r in rows if r['deliverable_type'] == deliverable_type]
    status = arg('status')
    if status is not None:
        rows = [r for r in rows if r['status'] == status]
    return paginate(by_created(rows), deliverable_out)


@bp.route('/studio/deliverables/<deliverable_id>', methods=['GET'])
def read_deliverable(deliverable_id):
    authenticate(ALL_READ)
    return success(deliverable_out(get_deliverable(deliverable_id)))


@bp.route('/studio/deliverables/<deliverable_id>/submit', methods=['POST'])
def submit_deliverable(deliverable_id):
    authenticate((PM,))
    deliverable = get_deliverable(deliverable_id)
    production = db.productions.get(deliverable['production_id'])
    require_phase(production, CREATE_PHASES)
    if deliverable['status'] != 'DRAFT':
        raise ApiError('ERR_DELIVERABLE_STATE_INVALID', 409,
                       'a deliverable in %s may not be submitted'
                       % deliverable['status'])
    scope = _scope_shot_ids(deliverable)
    for note in db.notes.values():
        if note['severity'] != 'BLOCKING':
            continue
        if note['status'] not in ('OPEN', 'RETAKE_ISSUED'):
            continue
        task = db.tasks.get(note['shot_stage_task_id'])
        if task is not None and task['shot_id'] in scope:
            raise ApiError('ERR_BLOCKING_NOTES_OPEN', 422,
                           'a BLOCKING director note is still open in scope')
    if deliverable['deliverable_type'] == 'MASTER_EXR':
        closed_client_review = any(
            s['production_id'] == deliverable['production_id']
            and s['session_type'] == 'CLIENT_REVIEW'
            and s['status'] == 'CLOSED'
            for s in db.sessions.values())
        if not closed_client_review:
            raise ApiError('ERR_CLIENT_REVIEW_REQUIRED', 422,
                           'a closed CLIENT_REVIEW session is required first')
    deliverable['status'] = 'SUBMITTED'
    touch(deliverable)
    return success(deliverable_out(deliverable))


@bp.route('/studio/deliverables/<deliverable_id>/qc-decision', methods=['POST'])
def qc_deliverable(deliverable_id):
    authenticate((SUPERVISOR,))
    deliverable = get_deliverable(deliverable_id)
    body = body_json()
    decision = get_enum(body, 'decision', ('PASS', 'FAIL'))
    qc_note = get_str(body, 'qc_note', required=False, default=None)
    production = db.productions.get(deliverable['production_id'])
    require_phase(production, CREATE_PHASES)
    if deliverable['status'] != 'SUBMITTED':
        raise ApiError('ERR_DELIVERABLE_STATE_INVALID', 409,
                       'a deliverable in %s may not be QC decided'
                       % deliverable['status'])
    if decision == 'FAIL' and (qc_note is None or not qc_note.strip()):
        raise validation_error('FAIL requires a non-empty qc_note')
    if qc_note is not None:
        deliverable['qc_note'] = qc_note
    deliverable['status'] = 'QC_PASSED' if decision == 'PASS' else 'QC_FAILED'
    touch(deliverable)
    return success(deliverable_out(deliverable))


@bp.route('/studio/deliverables/<deliverable_id>/deliver', methods=['POST'])
def deliver_deliverable(deliverable_id):
    authenticate((PM,))
    deliverable = get_deliverable(deliverable_id)
    production = db.productions.get(deliverable['production_id'])
    require_phase(production, ('DELIVERY',))
    if deliverable['status'] != 'QC_PASSED':
        raise ApiError('ERR_DELIVERABLE_STATE_INVALID', 409,
                       'a deliverable in %s may not be shipped'
                       % deliverable['status'])
    deliverable['status'] = 'DELIVERED'
    deliverable['delivered_at'] = now()
    touch(deliverable)
    return success(deliverable_out(deliverable))
