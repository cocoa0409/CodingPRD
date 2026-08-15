"""ACDBE participation review endpoints (PRD section 3.7)."""
from flask import Blueprint, g, request

from db import db, base_fields
from errors import (ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST,
                    ERR_REVIEW_STATE_FORBIDS, ERR_CURE_INSUFFICIENT)
from middleware import (require_roles, body_json, req_int, require_lease_owner)
from response import ok, ok_list
from services.core import pub, touch, acdbe_total_gross, acdbe_attainment_bp
from services.validation import check_enum, paginate

bp = Blueprint('reviews', __name__)

REVIEW_STATUSES = ('SCHEDULED', 'COMPLIANT', 'DEFICIENT', 'CURED')


def get_review_or_404(rid):
    rv = db.reviews.get(rid)
    if rv is None:
        raise ApiError(ERR_NOT_FOUND, 404, 'ACDBE review not found')
    return rv


@bp.route('/concessions/acdbe-reviews', methods=['POST'])
def create_review():
    require_roles('ConcessionAnalyst')
    body = body_json()
    lease_id = body.get('lease_id')
    if isinstance(lease_id, str) and lease_id not in db.leases:
        raise ApiError(ERR_NOT_FOUND, 404, 'Referenced lease does not exist')
    from middleware import req_str
    lease_id = req_str(body, 'lease_id')
    if lease_id not in db.leases:
        raise ApiError(ERR_NOT_FOUND, 404, 'Referenced lease does not exist')
    year = req_int(body, 'period_year')
    rec = base_fields()
    rec.update({
        'lease_id': lease_id,
        'period_year': year,
        'certified_revenue_cents': None,
        'cure_additional_certified_cents': 0,
        'total_gross_cents': None,
        'attainment_bp': None,
        'status': 'SCHEDULED',
    })
    db.reviews[rec['id']] = rec
    return ok(pub(rec), status=201)


@bp.route('/concessions/acdbe-reviews', methods=['GET'])
def list_reviews():
    require_roles('AirportAdmin', 'ConcessionAnalyst', 'Tenant')
    items = sorted(db.reviews.values(), key=lambda r: r['_seq'])
    f_lease = request.args.get('lease_id')
    f_status = request.args.get('status')
    if f_status is not None:
        check_enum(f_status, REVIEW_STATUSES, 'status')
    if g.role == 'Tenant':
        own = {l['id'] for l in db.leases.values() if l['tenant_id'] == g.user_id}
        items = [r for r in items if r['lease_id'] in own]
    if f_lease is not None:
        items = [r for r in items if r['lease_id'] == f_lease]
    if f_status is not None:
        items = [r for r in items if r['status'] == f_status]
    page, meta = paginate(items)
    return ok_list([pub(r) for r in page], meta)


@bp.route('/concessions/acdbe-reviews/<rid>', methods=['GET'])
def get_review(rid):
    require_roles('AirportAdmin', 'ConcessionAnalyst', 'Tenant')
    rv = get_review_or_404(rid)
    if g.role == 'Tenant':
        require_lease_owner(db.leases[rv['lease_id']])
    return ok(pub(rv))


@bp.route('/concessions/acdbe-reviews/<rid>/evaluate', methods=['POST'])
def evaluate_review(rid):
    require_roles('ConcessionAnalyst')
    rv = get_review_or_404(rid)
    body = body_json()
    certified = req_int(body, 'certified_revenue_cents')
    if certified < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       'certified_revenue_cents must be >= 0')
    # Evaluation is valid only from SCHEDULED.
    if rv['status'] != 'SCHEDULED':
        raise ApiError(ERR_REVIEW_STATE_FORBIDS, 409,
                       'Evaluation is valid only from SCHEDULED')
    lease = db.leases[rv['lease_id']]
    total = acdbe_total_gross(rv['lease_id'], rv['period_year'])
    if total == 0:
        attainment = 0
        status = 'DEFICIENT'
    else:
        attainment = acdbe_attainment_bp(certified, total)
        # Meeting the goal exactly attains it.
        status = 'COMPLIANT' if attainment >= lease['acdbe_goal_bp'] else 'DEFICIENT'
    rv['certified_revenue_cents'] = certified
    rv['total_gross_cents'] = total
    rv['attainment_bp'] = attainment
    rv['status'] = status
    touch(rv)
    return ok(pub(rv))


@bp.route('/concessions/acdbe-reviews/<rid>/cure', methods=['POST'])
def cure_review(rid):
    require_roles('Tenant')
    rv = get_review_or_404(rid)
    lease = db.leases[rv['lease_id']]
    require_lease_owner(lease)
    body = body_json()
    additional = req_int(body, 'cure_additional_certified_cents')
    if additional < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       'cure_additional_certified_cents must be >= 0')
    # Cure is valid only from DEFICIENT.
    if rv['status'] != 'DEFICIENT':
        raise ApiError(ERR_REVIEW_STATE_FORBIDS, 409,
                       'Cure is valid only from DEFICIENT')
    total = rv['total_gross_cents']
    numerator = rv['certified_revenue_cents'] + additional
    attainment = acdbe_attainment_bp(numerator, total)
    if attainment < lease['acdbe_goal_bp']:
        raise ApiError(ERR_CURE_INSUFFICIENT, 422,
                       'Cure evidence does not bring attainment to the goal')
    rv['cure_additional_certified_cents'] = additional
    rv['attainment_bp'] = attainment
    rv['status'] = 'CURED'
    # Curing a review does not clear a declared lease default.
    touch(rv)
    return ok(pub(rv))
