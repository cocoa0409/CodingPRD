"""Tenant-improvement draw endpoints (PRD section 3.9)."""
from flask import Blueprint, g, request

from db import db, base_fields
from errors import (ApiError, ERR_NOT_FOUND, ERR_FORBIDDEN,
                    ERR_LEASE_NOT_ACTIVE, ERR_BUILDOUT_WINDOW_CLOSED,
                    ERR_INVALID_AMOUNT, ERR_TI_ALLOWANCE_EXCEEDED,
                    ERR_DRAW_STATE_FORBIDS)
from middleware import (require_roles, body_json, req_str, req_int,
                        require_lease_owner)
from response import ok, ok_list
from services.core import pub, touch, parse_date, recompute_ti
from services.validation import check_enum, paginate

bp = Blueprint('draws', __name__)

MILESTONES = ('DESIGN', 'CONSTRUCTION', 'FIXTURES', 'GRAND_OPENING')
DRAW_ACTIONS = ('APPROVE', 'REJECT', 'DISBURSE', 'CANCEL')
DRAW_STATUSES = ('REQUESTED', 'APPROVED', 'REJECTED', 'DISBURSED', 'CANCELLED')


def get_draw_or_404(did):
    d = db.draws.get(did)
    if d is None:
        raise ApiError(ERR_NOT_FOUND, 404, 'TI draw not found')
    return d


@bp.route('/concessions/ti-draws', methods=['POST'])
def create_draw():
    require_roles('Tenant')
    body = body_json()
    lease_id = body.get('lease_id')
    if isinstance(lease_id, str) and lease_id not in db.leases:
        raise ApiError(ERR_NOT_FOUND, 404, 'Referenced lease does not exist')
    lease_id = req_str(body, 'lease_id')
    lease = db.leases.get(lease_id)
    if lease is None:
        raise ApiError(ERR_NOT_FOUND, 404, 'Referenced lease does not exist')
    require_lease_owner(lease)
    amount = req_int(body, 'amount_cents')
    milestone = req_str(body, 'milestone')
    check_enum(milestone, MILESTONES, 'milestone')
    # Guards in pipeline order: lease ACTIVE -> buildout window -> positive
    # amount -> within the remaining allowance.
    if lease['status'] != 'ACTIVE':
        raise ApiError(ERR_LEASE_NOT_ACTIVE, 409,
                       'Draw requests require an ACTIVE lease')
    if not db.clock.date() <= parse_date(lease['buildout_deadline']):
        raise ApiError(ERR_BUILDOUT_WINDOW_CLOSED, 422,
                       'The buildout window has closed')
    if amount <= 0:
        raise ApiError(ERR_INVALID_AMOUNT, 422, 'amount_cents must be > 0')
    if amount > lease['ti_remaining_cents']:
        raise ApiError(ERR_TI_ALLOWANCE_EXCEEDED, 422,
                       'Draw exceeds the remaining TI allowance')
    rec = base_fields()
    rec.update({
        'lease_id': lease_id,
        'amount_cents': amount,
        'milestone': milestone,
        'status': 'REQUESTED',
    })
    db.draws[rec['id']] = rec
    return ok(pub(rec), status=201)


@bp.route('/concessions/ti-draws', methods=['GET'])
def list_draws():
    require_roles('AirportAdmin', 'ConcessionAnalyst', 'Tenant')
    items = sorted(db.draws.values(), key=lambda d: d['_seq'])
    f_lease = request.args.get('lease_id')
    f_status = request.args.get('status')
    if f_status is not None:
        check_enum(f_status, DRAW_STATUSES, 'status')
    if g.role == 'Tenant':
        own = {l['id'] for l in db.leases.values() if l['tenant_id'] == g.user_id}
        items = [d for d in items if d['lease_id'] in own]
    if f_lease is not None:
        items = [d for d in items if d['lease_id'] == f_lease]
    if f_status is not None:
        items = [d for d in items if d['status'] == f_status]
    page, meta = paginate(items)
    return ok_list([pub(d) for d in page], meta)


@bp.route('/concessions/ti-draws/<did>', methods=['GET'])
def get_draw(did):
    require_roles('AirportAdmin', 'ConcessionAnalyst', 'Tenant')
    d = get_draw_or_404(did)
    if g.role == 'Tenant':
        require_lease_owner(db.leases[d['lease_id']])
    return ok(pub(d))


@bp.route('/concessions/ti-draws/<did>/transition', methods=['POST'])
def transition_draw(did):
    require_roles('AirportAdmin', 'Tenant')
    d = get_draw_or_404(did)
    body = body_json()
    action = req_str(body, 'action')
    check_enum(action, DRAW_ACTIONS, 'action')
    lease = db.leases[d['lease_id']]

    if action == 'CANCEL':
        # CANCEL is the owning tenant's action.
        if g.role != 'Tenant':
            raise ApiError(ERR_FORBIDDEN, 403, 'CANCEL is a Tenant action')
        require_lease_owner(lease)
        if d['status'] not in ('REQUESTED', 'APPROVED'):
            raise ApiError(ERR_DRAW_STATE_FORBIDS, 409,
                           'CANCEL is valid only from REQUESTED or APPROVED')
        was_approved = d['status'] == 'APPROVED'
        d['status'] = 'CANCELLED'
        touch(d)
        if was_approved:
            # Cancelling an APPROVED draw releases the reserve.
            recompute_ti(lease)
        return ok(pub(d))

    # APPROVE / REJECT / DISBURSE are AirportAdmin actions.
    if g.role != 'AirportAdmin':
        raise ApiError(ERR_FORBIDDEN, 403,
                       'APPROVE, REJECT and DISBURSE are AirportAdmin actions')
    if action == 'APPROVE':
        # Any failed precondition at decision time is ERR_DRAW_STATE_FORBIDS.
        if (d['status'] != 'REQUESTED' or lease['status'] != 'ACTIVE'
                or not db.clock.date() <= parse_date(lease['buildout_deadline'])):
            raise ApiError(ERR_DRAW_STATE_FORBIDS, 409,
                           'APPROVE requires REQUESTED status, an ACTIVE lease, '
                           'and an open buildout window')
        d['status'] = 'APPROVED'
        touch(d)
        # Approval converts the amount into the approved-pending reserve.
        recompute_ti(lease)
    elif action == 'REJECT':
        if d['status'] != 'REQUESTED':
            raise ApiError(ERR_DRAW_STATE_FORBIDS, 409,
                           'REJECT is valid only from REQUESTED')
        d['status'] = 'REJECTED'
        touch(d)
    elif action == 'DISBURSE':
        if d['status'] != 'APPROVED':
            raise ApiError(ERR_DRAW_STATE_FORBIDS, 409,
                           'DISBURSE is valid only from APPROVED')
        d['status'] = 'DISBURSED'
        touch(d)
        # The reserve converts to a disbursed amount.
        recompute_ti(lease)
    return ok(pub(d))
