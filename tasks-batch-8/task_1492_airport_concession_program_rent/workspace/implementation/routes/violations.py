"""Policy violation endpoints (PRD section 3.9)."""
from flask import Blueprint, g, request

from db import db, base_fields
from errors import (ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST,
                    ERR_LEASE_NOT_ACTIVE, ERR_INVALID_AMOUNT,
                    ERR_VIOLATION_ALREADY_RESOLVED)
from middleware import require_roles, body_json, req_str, req_date, require_lease_owner
from response import ok, ok_list
from services.core import pub, touch, violation_penalty
from services.validation import check_enum, paginate

bp = Blueprint('violations', __name__)

VIOLATION_KINDS = ('STREET_PRICING', 'OPERATING_HOURS')
VIOLATION_STATUSES = ('OPEN', 'RESOLVED')


def get_violation_or_404(vid):
    v = db.violations.get(vid)
    if v is None:
        raise ApiError(ERR_NOT_FOUND, 404, 'Policy violation not found')
    return v


@bp.route('/concessions/violations', methods=['POST'])
def create_violation():
    require_roles('ConcessionAnalyst')
    body = body_json()
    lease_id = body.get('lease_id')
    if isinstance(lease_id, str) and lease_id not in db.leases:
        raise ApiError(ERR_NOT_FOUND, 404, 'Referenced lease does not exist')
    lease_id = req_str(body, 'lease_id')
    lease = db.leases.get(lease_id)
    if lease is None:
        raise ApiError(ERR_NOT_FOUND, 404, 'Referenced lease does not exist')
    kind = req_str(body, 'kind')
    observed_date = req_date(body, 'observed_date')
    check_enum(kind, VIOLATION_KINDS, 'kind')
    # Recording a violation requires an ACTIVE lease.
    if lease['status'] != 'ACTIVE':
        raise ApiError(ERR_LEASE_NOT_ACTIVE, 409,
                       'Violations are recorded against an ACTIVE lease')
    shortfall = None
    overcharge = None
    if kind == 'OPERATING_HOURS':
        shortfall = body.get('shortfall_minutes')
        if not isinstance(shortfall, int) or isinstance(shortfall, bool):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           'shortfall_minutes is required for OPERATING_HOURS')
        if shortfall <= 0:
            raise ApiError(ERR_INVALID_AMOUNT, 422, 'shortfall_minutes must be > 0')
    else:
        overcharge = body.get('overcharge_cents')
        if not isinstance(overcharge, int) or isinstance(overcharge, bool):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           'overcharge_cents is required for STREET_PRICING')
        if overcharge <= 0:
            raise ApiError(ERR_INVALID_AMOUNT, 422, 'overcharge_cents must be > 0')
    # The penalty is assessed once, at creation.
    penalty = violation_penalty(kind, shortfall, overcharge)
    rec = base_fields()
    rec.update({
        'lease_id': lease_id,
        'kind': kind,
        'observed_date': observed_date,
        'shortfall_minutes': shortfall,
        'overcharge_cents': overcharge,
        'penalty_cents': penalty,
        'status': 'OPEN',
    })
    db.violations[rec['id']] = rec
    return ok(pub(rec), status=201)


@bp.route('/concessions/violations', methods=['GET'])
def list_violations():
    require_roles('AirportAdmin', 'ConcessionAnalyst', 'Tenant')
    items = sorted(db.violations.values(), key=lambda v: v['_seq'])
    f_lease = request.args.get('lease_id')
    f_kind = request.args.get('kind')
    f_status = request.args.get('status')
    if f_kind is not None:
        check_enum(f_kind, VIOLATION_KINDS, 'kind')
    if f_status is not None:
        check_enum(f_status, VIOLATION_STATUSES, 'status')
    if g.role == 'Tenant':
        own = {l['id'] for l in db.leases.values() if l['tenant_id'] == g.user_id}
        items = [v for v in items if v['lease_id'] in own]
    if f_lease is not None:
        items = [v for v in items if v['lease_id'] == f_lease]
    if f_kind is not None:
        items = [v for v in items if v['kind'] == f_kind]
    if f_status is not None:
        items = [v for v in items if v['status'] == f_status]
    page, meta = paginate(items)
    return ok_list([pub(v) for v in page], meta)


@bp.route('/concessions/violations/<vid>', methods=['GET'])
def get_violation(vid):
    require_roles('AirportAdmin', 'ConcessionAnalyst', 'Tenant')
    v = get_violation_or_404(vid)
    if g.role == 'Tenant':
        require_lease_owner(db.leases[v['lease_id']])
    return ok(pub(v))


@bp.route('/concessions/violations/<vid>/resolve', methods=['POST'])
def resolve_violation(vid):
    require_roles('ConcessionAnalyst')
    v = get_violation_or_404(vid)
    if v['status'] != 'OPEN':
        raise ApiError(ERR_VIOLATION_ALREADY_RESOLVED, 409,
                       'Only an OPEN violation can be resolved')
    v['status'] = 'RESOLVED'
    touch(v)
    return ok(pub(v))
