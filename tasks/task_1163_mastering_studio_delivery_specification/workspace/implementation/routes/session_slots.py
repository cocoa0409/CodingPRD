from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_TIME_BOUNDARY, ERR_SLOT_CONFLICT,
    ERR_ENTITY_NOT_ACTIVE, ERR_HOLD_EXPIRED, ERR_NOT_FOUND,
)
from middleware import (
    auth, require_roles, body, req_field, opt_field, as_str, as_datetime,
    pagination_args, get_or_404, ensure_state, check_client_owner,
)
from response import success, success_list
from services.capacity import engineer_overlap

bp = Blueprint('session_slots', __name__)


def _slot_owner_check(uid, role, slot):
    proj_id = slot.get('project_id')
    if role == 'Client' and proj_id:
        proj = db.projects.get(proj_id)
        if proj is not None:
            check_client_owner(uid, role, proj)


@bp.post('/studio/session-slots')
def create_slot():
    uid, role = auth()
    require_roles(role, ('Client', 'StudioManager'))
    data = body()
    engineer_id = as_str(req_field(data, 'engineer_id'), 'engineer_id')
    project_id = opt_field(data, 'project_id')
    start_raw = req_field(data, 'slot_start_at')
    end_raw = req_field(data, 'slot_end_at')
    # Guard 4: FK existence.
    get_or_404(db.engineers, engineer_id)
    proj = None
    if project_id is not None:
        if not isinstance(project_id, str):
            raise ApiError(ERR_INVALID_REQUEST, 400, 'project_id must be a string')
        proj = get_or_404(db.projects, project_id)
    if role == 'Client' and proj is not None:
        check_client_owner(uid, role, proj)
    start_dt = as_datetime(start_raw, 'slot_start_at')
    end_dt = as_datetime(end_raw, 'slot_end_at')
    if end_dt <= start_dt:
        raise ApiError(ERR_INVALID_REQUEST, 400, 'slot_end_at must be strictly after slot_start_at')
    # Guard 7: overlap (priority before boundary, per the guard chain).
    if engineer_overlap(engineer_id, start_dt, end_dt) is not None:
        raise ApiError(ERR_SLOT_CONFLICT, 409,
                       'Requested slot overlaps an existing BOOKED or HELD slot for this engineer')
    # Guard 9: 30-minute boundary.
    if not db.on_grid(start_dt) or not db.on_grid(end_dt):
        raise ApiError(ERR_INVALID_TIME_BOUNDARY, 400,
                       'slot_start_at and slot_end_at must land on a 30-minute boundary')
    now = db.now_dt()
    rec = db.new_record()
    rec.update({
        'engineer_id': engineer_id,
        'project_id': project_id,
        'slot_start_at': db.iso(start_dt),
        'slot_end_at': db.iso(end_dt),
        'status': 'HELD',
        'held_expires_at': db.iso(now + timedelta(minutes=db.HELD_TTL_MINUTES)),
    })
    db.session_slots[rec['id']] = rec
    return success(db.public(rec), 201)


@bp.get('/studio/session-slots')
def list_slots():
    uid, role = auth()
    require_roles(role, ('StudioManager', 'Client', 'Engineer', 'QAChecker'))
    limit, offset = pagination_args()
    items = list(db.session_slots.values())
    if role == 'Client':
        def visible(s):
            pid = s.get('project_id')
            if not pid:
                return True
            proj = db.projects.get(pid)
            return proj is not None and proj['client_id'] == uid
        items = [s for s in items if visible(s)]
    for f in ('engineer_id', 'project_id', 'status'):
        val = request.args.get(f)
        if val is not None:
            items = [s for s in items if s.get(f) == val]
    items.sort(key=lambda s: s['_seq'])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list(db.public_list(page), limit, offset, total)


@bp.get('/studio/session-slots/<sid>')
def get_slot(sid):
    uid, role = auth()
    require_roles(role, ('StudioManager', 'Client', 'Engineer', 'QAChecker'))
    slot = get_or_404(db.session_slots, sid)
    _slot_owner_check(uid, role, slot)
    return success(db.public(slot), 200)


@bp.post('/studio/session-slots/<sid>/confirm')
def confirm_slot(sid):
    uid, role = auth()
    require_roles(role, ('Client',))
    slot = get_or_404(db.session_slots, sid)
    _slot_owner_check(uid, role, slot)
    ensure_state('SessionSlot', slot, 'status', ('HELD',))
    # Guard 6: engineer must be AVAILABLE at confirmation time.
    eng = db.engineers.get(slot['engineer_id'])
    if eng is None:
        raise ApiError(ERR_NOT_FOUND, 404, 'Engineer not found')
    if eng['availability_status'] != 'AVAILABLE':
        raise ApiError(ERR_ENTITY_NOT_ACTIVE, 422, 'Engineer is not AVAILABLE')
    # Guard 16: hold expiry.
    if db.now_dt() >= db.parse_dt(slot['held_expires_at']):
        raise ApiError(ERR_HOLD_EXPIRED, 410, 'Hold has expired')
    slot['status'] = 'BOOKED'
    db.touch(slot)
    return success(db.public(slot), 200)


@bp.post('/studio/session-slots/<sid>/release')
def release_slot(sid):
    uid, role = auth()
    require_roles(role, ('Client', 'StudioManager'))
    slot = get_or_404(db.session_slots, sid)
    _slot_owner_check(uid, role, slot)
    ensure_state('SessionSlot', slot, 'status', ('HELD',))
    slot['status'] = 'RELEASED'
    db.touch(slot)
    return success(db.public(slot), 200)


@bp.post('/studio/session-slots/<sid>/cancel')
def cancel_slot(sid):
    uid, role = auth()
    require_roles(role, ('StudioManager',))
    slot = get_or_404(db.session_slots, sid)
    ensure_state('SessionSlot', slot, 'status', ('BOOKED',))
    slot['status'] = 'CANCELLED'
    db.touch(slot)
    # Cascade: pull the attached project into CANCELLED when still early-stage.
    proj_id = slot.get('project_id')
    if proj_id:
        proj = db.projects.get(proj_id)
        if proj is not None and proj['status'] in ('DRAFT', 'BOOKED', 'INTAKE'):
            eng_id = proj.get('assigned_engineer_id')
            if eng_id and proj['status'] in ('BOOKED', 'INTAKE'):
                eng = db.engineers.get(eng_id)
                if eng is not None:
                    eng['active_project_count'] -= 1
                    db.touch(eng)
            proj['status'] = 'CANCELLED'
            db.touch(proj)
    return success(db.public(slot), 200)
