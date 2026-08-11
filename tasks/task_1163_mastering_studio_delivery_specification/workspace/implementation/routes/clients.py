from flask import Blueprint, request

import db
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_INSUFFICIENT_CREDIT
from middleware import (
    auth, require_roles, body, req_field, as_str, as_int, pagination_args,
    get_or_404, ensure_state, check_client_owner_id,
)
from response import success, success_list

bp = Blueprint('clients', __name__)

IN_FLIGHT_STATES = ('BOOKED', 'INTAKE', 'QC_PASSED', 'MASTERING', 'REVISION', 'APPROVED', 'DELIVERING')


def _touch(rec):
    db.touch(rec)


@bp.post('/studio/clients')
def create_client():
    uid, role = auth()
    require_roles(role, ('StudioManager',))
    data = body()
    legal_name = as_str(req_field(data, 'legal_name'), 'legal_name')
    contact_email = as_str(req_field(data, 'contact_email'), 'contact_email')
    for c in db.clients.values():
        if c['contact_email'] == contact_email:
            raise ApiError(ERR_INVALID_REQUEST, 409, 'contact_email already registered')
    rec = db.new_record()
    rec.update({
        'legal_name': legal_name,
        'contact_email': contact_email,
        'status': 'PROSPECT',
        'account_credit_cents': 0,
        'lifetime_revision_count': 0,
    })
    db.clients[rec['id']] = rec
    return success(db.public(rec), 201)


@bp.get('/studio/clients')
def list_clients():
    uid, role = auth()
    require_roles(role, ('StudioManager', 'QAChecker', 'Engineer'))
    limit, offset = pagination_args()
    status = request.args.get('status')
    items = list(db.clients.values())
    if status is not None:
        items = [c for c in items if c['status'] == status]
    items.sort(key=lambda c: c['_seq'])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list(db.public_list(page), limit, offset, total)


@bp.get('/studio/clients/<cid>')
def get_client(cid):
    uid, role = auth()
    require_roles(role, ('StudioManager', 'Client', 'QAChecker'))
    client = get_or_404(db.clients, cid)
    check_client_owner_id(uid, role, cid)
    return success(db.public(client), 200)


@bp.post('/studio/clients/<cid>/activate')
def activate_client(cid):
    uid, role = auth()
    require_roles(role, ('StudioManager',))
    client = get_or_404(db.clients, cid)
    st = ensure_state('Client', client, 'status', ('PROSPECT', 'SUSPENDED'))
    if st == 'PROSPECT':
        has_project = any(p['client_id'] == cid for p in db.projects.values())
        if not has_project:
            raise ApiError(ERR_INVALID_STATE, 409,
                           'Client has no project; first activation requires at least one project')
    client['status'] = 'ACTIVE'
    _touch(client)
    return success(db.public(client), 200)


@bp.post('/studio/clients/<cid>/suspend')
def suspend_client(cid):
    uid, role = auth()
    require_roles(role, ('StudioManager',))
    client = get_or_404(db.clients, cid)
    ensure_state('Client', client, 'status', ('ACTIVE',))
    # Cascade: release HELD slots attached to this client's projects.
    owned_project_ids = {p['id'] for p in db.projects.values() if p['client_id'] == cid}
    for slot in db.session_slots.values():
        if slot.get('project_id') in owned_project_ids and slot['status'] == 'HELD':
            slot['status'] = 'RELEASED'
            db.touch(slot)
    # Cascade: cancel projects still in DRAFT/BOOKED/INTAKE.
    for proj in db.projects.values():
        if proj['client_id'] == cid and proj['status'] in ('DRAFT', 'BOOKED', 'INTAKE'):
            eng_id = proj.get('assigned_engineer_id')
            if eng_id and proj['status'] in ('BOOKED', 'INTAKE'):
                eng = db.engineers.get(eng_id)
                if eng is not None:
                    eng['active_project_count'] -= 1
                    db.touch(eng)
            proj['status'] = 'CANCELLED'
            db.touch(proj)
    client['status'] = 'SUSPENDED'
    _touch(client)
    return success(db.public(client), 200)


@bp.post('/studio/clients/<cid>/terminate')
def terminate_client(cid):
    uid, role = auth()
    require_roles(role, ('StudioManager',))
    client = get_or_404(db.clients, cid)
    ensure_state('Client', client, 'status', ('ACTIVE', 'SUSPENDED'))
    in_flight = any(p['client_id'] == cid and p['status'] in IN_FLIGHT_STATES
                    for p in db.projects.values())
    if in_flight:
        raise ApiError(ERR_INVALID_STATE, 409,
                       'Client has in-flight projects; termination not permitted')
    client['status'] = 'TERMINATED'
    _touch(client)
    return success(db.public(client), 200)


@bp.post('/studio/clients/<cid>/credit-adjustments')
def credit_adjustment(cid):
    uid, role = auth()
    require_roles(role, ('StudioManager',))
    client = get_or_404(db.clients, cid)
    data = body()
    amount = as_int(req_field(data, 'amount_cents'), 'amount_cents')
    as_str(req_field(data, 'reason'), 'reason')
    new_balance = client['account_credit_cents'] + amount
    if new_balance < 0:
        raise ApiError(ERR_INSUFFICIENT_CREDIT, 402,
                       'Adjustment would drive client balance negative')
    client['account_credit_cents'] = new_balance
    _touch(client)
    return success(db.public(client), 201)
