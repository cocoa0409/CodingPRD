from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_NO_ACTIVE_ROUND, ERR_SLA_BREACH,
    ERR_STALE_VERSION, ERR_INSUFFICIENT_CREDIT,
)
from middleware import (
    auth, require_roles, body, req_field, opt_field, as_str, as_int,
    pagination_args, get_or_404, ensure_state,
    check_client_owner, check_engineer_assigned,
)
from response import success, success_list
from services import pricing
from routes.projects import _open_round

bp = Blueprint('rounds', __name__)


def _resolve_pair(pid, rid):
    """Left-to-right path existence; round must belong to the project."""
    proj = get_or_404(db.projects, pid)
    rnd = get_or_404(db.revision_rounds, rid)
    if rnd['project_id'] != pid:
        raise ApiError(ERR_NOT_FOUND, 404, 'Round does not belong to this project')
    return proj, rnd


@bp.get('/studio/projects/<pid>/rounds')
def list_rounds(pid):
    uid, role = auth()
    require_roles(role, ('StudioManager', 'Client', 'Engineer', 'QAChecker'))
    proj = get_or_404(db.projects, pid)
    check_client_owner(uid, role, proj)
    limit, offset = pagination_args()
    status = request.args.get('status')
    items = [r for r in db.revision_rounds.values() if r['project_id'] == pid]
    if status is not None:
        items = [r for r in items if r['status'] == status]
    items.sort(key=lambda r: r['_seq'])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list(db.public_list(page), limit, offset, total)


@bp.get('/studio/rounds/<rid>')
def get_round(rid):
    uid, role = auth()
    require_roles(role, ('StudioManager', 'Client', 'Engineer', 'QAChecker'))
    rnd = get_or_404(db.revision_rounds, rid)
    proj = db.projects.get(rnd['project_id'])
    if proj is not None:
        check_client_owner(uid, role, proj)
    return success(db.public(rnd), 200)


@bp.post('/studio/projects/<pid>/rounds/<rid>/submit')
def submit_round(pid, rid):
    uid, role = auth()
    require_roles(role, ('Engineer',))
    proj, rnd = _resolve_pair(pid, rid)
    check_engineer_assigned(uid, role, proj)
    data = body()
    expected_project_version = as_int(req_field(data, 'expected_project_version'),
                                      'expected_project_version')
    notes = opt_field(data, 'notes')
    if notes is not None:
        notes = as_str(notes, 'notes')
    # Guard 5: state admissibility.
    ensure_state('Project', proj, 'status', ('MASTERING',))
    ensure_state('RevisionRound', rnd, 'status', ('OPEN',))
    if proj['current_revision_round_id'] != rid:
        raise ApiError(ERR_NO_ACTIVE_ROUND, 409,
                       'Project has no current revision round in OPEN state for this operation')
    # Guard 15: revision deadline.
    if db.now_dt() > db.parse_dt(rnd['deadline_at']):
        raise ApiError(ERR_SLA_BREACH, 422, 'Round submission is after its deadline')
    # Guard 20 (last): optimistic concurrency on the project.
    if expected_project_version != proj['version']:
        raise ApiError(ERR_STALE_VERSION, 412,
                       'expected_project_version does not match current project version')
    rnd['status'] = 'SUBMITTED'
    rnd['submitted_at'] = db.now_iso()
    if notes is not None:
        rnd['notes'] = notes
    db.touch(rnd)
    proj['status'] = 'REVISION'
    db.touch(proj)
    return success(db.public(rnd), 200)


@bp.post('/studio/projects/<pid>/rounds/<rid>/approve')
def approve_round(pid, rid):
    uid, role = auth()
    require_roles(role, ('Client',))
    proj, rnd = _resolve_pair(pid, rid)
    check_client_owner(uid, role, proj)
    ensure_state('Project', proj, 'status', ('REVISION',))
    ensure_state('RevisionRound', rnd, 'status', ('SUBMITTED',))
    client = db.clients.get(proj['client_id'])
    if client is None:
        raise ApiError(ERR_NOT_FOUND, 404, 'Owning client not found')
    final_price = pricing.quote_final(proj)
    # Guard 14: credit sufficiency.
    if client['account_credit_cents'] - final_price < 0:
        raise ApiError(ERR_INSUFFICIENT_CREDIT, 402,
                       'Client balance would go negative after final price debit')
    rnd['status'] = 'APPROVED'
    rnd['resolved_at'] = db.now_iso()
    db.touch(rnd)
    proj['final_price_cents'] = final_price
    proj['status'] = 'APPROVED'
    db.touch(proj)
    client['account_credit_cents'] -= final_price
    db.touch(client)
    return success(db.public(rnd), 200)


@bp.post('/studio/projects/<pid>/rounds/<rid>/reject')
def reject_round(pid, rid):
    uid, role = auth()
    require_roles(role, ('Client',))
    proj, rnd = _resolve_pair(pid, rid)
    check_client_owner(uid, role, proj)
    data = body()
    notes = opt_field(data, 'notes')
    if notes is not None:
        notes = as_str(notes, 'notes')
    ensure_state('Project', proj, 'status', ('REVISION',))
    ensure_state('RevisionRound', rnd, 'status', ('SUBMITTED',))
    rnd['status'] = 'REJECTED'
    rnd['resolved_at'] = db.now_iso()
    if notes is not None:
        rnd['notes'] = notes
    db.touch(rnd)
    _open_round(proj)
    proj['status'] = 'MASTERING'
    db.touch(proj)
    return success(db.public(rnd), 200)
