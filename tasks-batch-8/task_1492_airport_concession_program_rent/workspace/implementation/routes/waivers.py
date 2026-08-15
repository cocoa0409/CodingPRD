"""Operating-hours closure waiver endpoints (PRD section 3.9)."""
from flask import Blueprint, g, request

from db import db, base_fields
from errors import (ApiError, ERR_NOT_FOUND, ERR_LEASE_NOT_ACTIVE,
                    ERR_INVALID_DATE_RANGE, ERR_WAIVER_STATE_FORBIDS,
                    ERR_WAIVER_BUFFER_VIOLATION)
from middleware import (require_roles, body_json, req_str, req_date,
                        require_lease_owner)
from response import ok, ok_list
from services.core import pub, touch, parse_date
from services.validation import check_enum, paginate

bp = Blueprint('waivers', __name__)

WAIVER_ACTIONS = ('APPROVE', 'REJECT')
WAIVER_STATUSES = ('REQUESTED', 'APPROVED', 'REJECTED')
BUFFER_DAYS = 14


def get_waiver_or_404(wid):
    w = db.waivers.get(wid)
    if w is None:
        raise ApiError(ERR_NOT_FOUND, 404, 'Operating-hours waiver not found')
    return w


@bp.route('/concessions/waivers', methods=['POST'])
def create_waiver():
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
    start = req_date(body, 'closure_start_date')
    end = req_date(body, 'closure_end_date')
    reason = req_str(body, 'reason')
    # The cross-entity active-lease gate (stage 6) precedes date coherence.
    if lease['status'] != 'ACTIVE':
        raise ApiError(ERR_LEASE_NOT_ACTIVE, 409,
                       'Waiver requests require an ACTIVE lease')
    # Both closure days inclusive; the start must not be after the end.
    if parse_date(start) > parse_date(end):
        raise ApiError(ERR_INVALID_DATE_RANGE, 422,
                       'closure_start_date must not be after closure_end_date')
    rec = base_fields()
    rec.update({
        'lease_id': lease_id,
        'closure_start_date': start,
        'closure_end_date': end,
        'reason': reason,
        'status': 'REQUESTED',
    })
    db.waivers[rec['id']] = rec
    return ok(pub(rec), status=201)


@bp.route('/concessions/waivers', methods=['GET'])
def list_waivers():
    require_roles('AirportAdmin', 'ConcessionAnalyst', 'Tenant')
    items = sorted(db.waivers.values(), key=lambda w: w['_seq'])
    f_lease = request.args.get('lease_id')
    f_status = request.args.get('status')
    if f_status is not None:
        check_enum(f_status, WAIVER_STATUSES, 'status')
    if g.role == 'Tenant':
        own = {l['id'] for l in db.leases.values() if l['tenant_id'] == g.user_id}
        items = [w for w in items if w['lease_id'] in own]
    if f_lease is not None:
        items = [w for w in items if w['lease_id'] == f_lease]
    if f_status is not None:
        items = [w for w in items if w['status'] == f_status]
    page, meta = paginate(items)
    return ok_list([pub(w) for w in page], meta)


@bp.route('/concessions/waivers/<wid>', methods=['GET'])
def get_waiver(wid):
    require_roles('AirportAdmin', 'ConcessionAnalyst', 'Tenant')
    w = get_waiver_or_404(wid)
    if g.role == 'Tenant':
        require_lease_owner(db.leases[w['lease_id']])
    return ok(pub(w))


@bp.route('/concessions/waivers/<wid>/transition', methods=['POST'])
def transition_waiver(wid):
    require_roles('AirportAdmin')
    w = get_waiver_or_404(wid)
    body = body_json()
    action = req_str(body, 'action')
    check_enum(action, WAIVER_ACTIONS, 'action')
    if w['status'] != 'REQUESTED':
        raise ApiError(ERR_WAIVER_STATE_FORBIDS, 409,
                       'Waiver decisions are valid only from REQUESTED')
    if action == 'APPROVE':
        # Fourteen-day buffer against every other APPROVED waiver of the same
        # lease: at least one direction must yield a gap of >= 14 days.
        ns, ne = parse_date(w['closure_start_date']), parse_date(w['closure_end_date'])
        for other in db.waivers.values():
            if other['id'] == w['id']:
                continue
            if other['lease_id'] != w['lease_id'] or other['status'] != 'APPROVED':
                continue
            os_ = parse_date(other['closure_start_date'])
            oe = parse_date(other['closure_end_date'])
            gap = max((os_ - ne).days, (ns - oe).days)
            if gap < BUFFER_DAYS:
                raise ApiError(ERR_WAIVER_BUFFER_VIOLATION, 409,
                               'Approved closure window would sit within 14 days '
                               'of another approved waiver of the same lease')
        w['status'] = 'APPROVED'
    else:
        w['status'] = 'REJECTED'
    touch(w)
    return ok(pub(w))
