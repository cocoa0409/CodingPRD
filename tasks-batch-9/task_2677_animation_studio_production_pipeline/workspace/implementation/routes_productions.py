"""Productions, pre-production gates and the administrative logical clock."""
from flask import Blueprint

import calc
from calc import (COLOR_SPACES, GATE_TYPES, D, by_created, gate_out, production_out,
                  recompute_shot, spend_ceiling_cents)
from flows import get_gate, get_production, require_phase
from helpers import (ALL_READ, ApiError, DIRECTOR, PM, arg, authenticate, body_json,
                     get_bool, get_datetime, get_enum, get_int, get_number, get_str,
                     get_str_array, paginate, success, validation_error)
from store import base_row, db, iso, new_id, next_seq, now, set_clock, touch

bp = Blueprint('productions', __name__)

FORMATS = ('FEATURE', 'SERIES_EPISODE', 'SHORT')
PHASE_SUCCESSOR = {
    'PRE_PRODUCTION': 'PRODUCTION_ACTIVE',
    'PRODUCTION_ACTIVE': 'DELIVERY',
    'DELIVERY': 'WRAPPED',
    'WRAPPED': None,
}


def new_gate(production, gate_type, sequence_index):
    row = base_row()
    row.update({
        'production_id': production['id'],
        'gate_type': gate_type,
        'sequence_index': sequence_index,
        'status': 'DRAFT',
        'revision_count': 0,
        'package_url': None,
        'submitted_by_user_id': None,
        'decided_by_user_id': None,
        'decided_at': None,
    })
    db.gates[row['id']] = row
    return row


def production_gates(production_id):
    rows = [g for g in db.gates.values() if g['production_id'] == production_id]
    rows.sort(key=lambda g: g['sequence_index'])
    return rows


@bp.route('/studio/productions', methods=['POST'])
def create_production():
    authenticate((PM,))
    body = body_json()
    title = get_str(body, 'title', min_len=1, max_len=200)
    production_code = get_str(body, 'production_code', min_len=2, max_len=16,
                              pattern=r'^[A-Z0-9]{2,16}$')
    fmt = get_enum(body, 'format', FORMATS)
    budget_cents = get_int(body, 'budget_cents', minimum=0)
    render_allowance_cents = get_int(body, 'render_allowance_cents', minimum=0)
    master_color_space = get_enum(body, 'master_color_space', COLOR_SPACES)
    contingency_pct = get_number(body, 'contingency_pct', required=False,
                                 default=0.10, minimum=0, maximum=0.50, places=2)
    approved = get_str_array(body, 'approved_color_spaces', required=False, default=None)
    if approved is None:
        approved = [master_color_space]
    else:
        if not approved:
            raise validation_error('approved_color_spaces may not be empty')
        for item in approved:
            if item not in COLOR_SPACES:
                raise validation_error('approved_color_spaces holds an unknown color space')
        if master_color_space not in approved:
            raise validation_error('approved_color_spaces must contain master_color_space')
    gate_types = get_str_array(body, 'gate_types', required=False, default=None)
    if gate_types is None:
        gate_types = list(GATE_TYPES)
    else:
        if not gate_types:
            raise validation_error('gate_types may not be empty')
        for item in gate_types:
            if item not in GATE_TYPES:
                raise validation_error('gate_types holds an unknown gate type')
        gate_types = [g for g in GATE_TYPES if g in set(gate_types)]

    for row in db.productions.values():
        if row['production_code'] == production_code:
            raise ApiError('ERR_DUPLICATE_CODE', 409, 'production_code is already in use')

    production = base_row()
    production.update({
        'title': title,
        'production_code': production_code,
        'format': fmt,
        'phase': 'PRE_PRODUCTION',
        'budget_cents': budget_cents,
        'contingency_pct': D(contingency_pct).quantize(D('0.01')),
        'render_allowance_cents': render_allowance_cents,
        'master_color_space': master_color_space,
        'approved_color_spaces': approved,
        'gate_types': gate_types,
        'shot_count': 0,
        'completed_shot_count': 0,
        'at_risk_shot_count': 0,
        'total_retake_count': 0,
        'direct_committed_cents': 0,
        'overhead_fee_cents': 0,
        'total_committed_cents': 0,
        'available_cents': 0,
        'render_committed_cents': 0,
        'render_actual_cents': 0,
        'bcwp_cents': 0,
        'acwp_cents': 0,
        'cpi': None,
    })
    production['available_cents'] = spend_ceiling_cents(production)
    db.productions[production['id']] = production
    for index, gate_type in enumerate(gate_types, start=1):
        new_gate(production, gate_type, index)
    return success(production_out(production), 201)


@bp.route('/studio/productions', methods=['GET'])
def list_productions():
    authenticate(ALL_READ)
    rows = list(db.productions.values())
    phase = arg('phase')
    if phase is not None:
        rows = [r for r in rows if r['phase'] == phase]
    return paginate(by_created(rows), production_out)


@bp.route('/studio/productions/<production_id>', methods=['GET'])
def read_production(production_id):
    authenticate(ALL_READ)
    return success(production_out(get_production(production_id)))


@bp.route('/studio/productions/<production_id>/advance-phase', methods=['POST'])
def advance_phase(production_id):
    authenticate((PM,))
    production = get_production(production_id)
    body = body_json()
    to_phase = get_enum(body, 'to_phase', ('DELIVERY', 'WRAPPED'))
    current = production['phase']
    if current != 'PRE_PRODUCTION' and PHASE_SUCCESSOR[current] != to_phase:
        raise ApiError('ERR_PRODUCTION_PHASE_INVALID', 409,
                       '%s is not the legal successor of %s' % (to_phase, current))
    if current == 'PRE_PRODUCTION':
        raise ApiError('ERR_GATES_INCOMPLETE', 409,
                       'pre-production gates remain outstanding')
    if to_phase == 'DELIVERY':
        if production['completed_shot_count'] != production['shot_count']:
            raise ApiError('ERR_SHOTS_INCOMPLETE', 409,
                           'every shot must be COMPLETE before DELIVERY')
    else:
        deliverables = [d for d in db.deliverables.values()
                        if d['production_id'] == production['id']]
        delivered = [d for d in deliverables if d['status'] == 'DELIVERED']
        in_flight = [d for d in deliverables
                     if d['status'] in ('DRAFT', 'SUBMITTED', 'QC_PASSED')]
        if not delivered or in_flight:
            raise ApiError('ERR_DELIVERABLES_INCOMPLETE', 409,
                           'deliverables are not complete')
    production['phase'] = to_phase
    touch(production)
    return success(production_out(production))


# ----------------------------------------------------------- pre-production gates
@bp.route('/studio/pre-production-gates', methods=['GET'])
def list_gates():
    authenticate(ALL_READ)
    rows = list(db.gates.values())
    production_id = arg('production_id')
    if production_id is not None:
        rows = [r for r in rows if r['production_id'] == production_id]
    gate_type = arg('gate_type')
    if gate_type is not None:
        rows = [r for r in rows if r['gate_type'] == gate_type]
    status = arg('status')
    if status is not None:
        rows = [r for r in rows if r['status'] == status]
    rows.sort(key=lambda g: (g['sequence_index'], g['created_at'], g['_seq']))
    return paginate(rows, gate_out)


@bp.route('/studio/pre-production-gates/<gate_id>', methods=['GET'])
def read_gate(gate_id):
    authenticate(ALL_READ)
    return success(gate_out(get_gate(gate_id)))


@bp.route('/studio/pre-production-gates/<gate_id>/submit', methods=['POST'])
def submit_gate(gate_id):
    user_id, _role = authenticate((PM,))
    gate = get_gate(gate_id)
    body = body_json()
    package_url = get_str(body, 'package_url', min_len=1)
    production = db.productions.get(gate['production_id'])
    require_phase(production, ('PRE_PRODUCTION',))
    if gate['status'] not in ('DRAFT', 'CHANGES_REQUESTED'):
        raise ApiError('ERR_GATE_STATE_INVALID', 409,
                       'a gate in %s may not be submitted' % gate['status'])
    for sibling in production_gates(gate['production_id']):
        if sibling['sequence_index'] < gate['sequence_index'] and sibling['status'] != 'APPROVED':
            raise ApiError('ERR_GATE_SEQUENCE_VIOLATION', 409,
                           'gate %s must be approved first' % sibling['gate_type'])
    gate['status'] = 'IN_REVIEW'
    gate['package_url'] = package_url
    gate['submitted_by_user_id'] = user_id
    touch(gate)
    return success(gate_out(gate))


@bp.route('/studio/pre-production-gates/<gate_id>/review-decision', methods=['POST'])
def decide_gate(gate_id):
    user_id, _role = authenticate((DIRECTOR,))
    gate = get_gate(gate_id)
    body = body_json()
    decision = get_enum(body, 'decision', ('APPROVED', 'CHANGES_REQUESTED'))
    get_str(body, 'note', required=False)
    if gate['submitted_by_user_id'] is not None and gate['submitted_by_user_id'] == user_id:
        raise ApiError('ERR_SEGREGATION_OF_DUTIES', 403,
                       'the submitter may not decide this gate')
    production = db.productions.get(gate['production_id'])
    require_phase(production, ('PRE_PRODUCTION',))
    if gate['status'] != 'IN_REVIEW':
        raise ApiError('ERR_GATE_STATE_INVALID', 409,
                       'a gate in %s may not be decided' % gate['status'])
    gate['decided_by_user_id'] = user_id
    gate['decided_at'] = now()
    if decision == 'CHANGES_REQUESTED':
        gate['status'] = 'CHANGES_REQUESTED'
        gate['revision_count'] += 1
        touch(gate)
        return success(gate_out(gate))
    gate['status'] = 'APPROVED'
    touch(gate)
    siblings = production_gates(gate['production_id'])
    if siblings and all(g['status'] == 'APPROVED' for g in siblings):
        production['phase'] = 'PRODUCTION_ACTIVE'
        for sibling in siblings:
            sibling['status'] = 'LOCKED'
            touch(sibling)
        for shot in [s for s in db.shots.values()
                     if s['production_id'] == production['id']]:
            recompute_shot(shot, production)
        touch(production)
    return success(gate_out(gate))


# ------------------------------------------------------------------ logical clock
@bp.route('/_clock/set_current_utc', methods=['POST'])
def set_current_utc():
    authenticate((PM,))
    body = body_json()
    target = get_datetime(body, 'to_iso8601')
    set_clock(target)
    return success({'current_utc': iso(target)})
