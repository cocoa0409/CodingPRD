from flask import Blueprint, request, g
from middleware.auth import require_auth
from models.database import db, Fine, Rider, Customer, Restaurant
from utils.response import success_response, err

bp = Blueprint('fines', __name__)

ALL_ROLES = {'PlatformAdmin', 'CustomerService', 'Rider', 'Restaurant', 'Customer'}


@bp.route('/api/fines/<id>', methods=['GET'])
@require_auth(ALL_ROLES)
def get_fine(id):
    f = Fine.query.get(id)
    if not f:
        return err('ERR_NOT_FOUND', 'Fine not found.')
    if g.user_role in ('Rider', 'Restaurant', 'Customer') and g.user_id != f.subject_id:
        return err('ERR_FORBIDDEN', 'Not your fine.')
    return success_response(f.to_dict())


@bp.route('/api/fines', methods=['GET'])
@require_auth(ALL_ROLES)
def list_fines():
    query = Fine.query
    subject_type = request.args.get('subject_type')
    subject_id = request.args.get('subject_id')
    settlement_status = request.args.get('settlement_status')
    if subject_type:
        query = query.filter_by(subject_type=subject_type)
    if subject_id:
        if g.user_role in ('Rider', 'Restaurant', 'Customer') and g.user_id != subject_id:
            return err('ERR_FORBIDDEN', 'Cannot view fines for other subjects.')
        query = query.filter_by(subject_id=subject_id)
    if settlement_status:
        query = query.filter_by(settlement_status=settlement_status)
    if g.user_role in ('Rider', 'Restaurant', 'Customer') and not subject_id:
        query = query.filter_by(subject_id=g.user_id)
    query = query.order_by(Fine.created_at.asc())
    total = query.count()
    try:
        limit = int(request.args.get('limit', 10))
        offset = int(request.args.get('offset', 0))
    except (TypeError, ValueError):
        return err('ERR_VALIDATION', 'Invalid pagination parameters.')
    if limit < 1 or limit > 100 or offset < 0:
        return err('ERR_VALIDATION', 'Invalid pagination parameters.')
    items = query.offset(offset).limit(limit).all()
    return success_response(
        [f.to_dict() for f in items],
        response_type='array',
        pagination={
            'limit': limit,
            'offset': offset,
            'total_count': total,
            'has_more': offset + limit < total,
        },
    )


@bp.route('/api/fines/<id>/waive', methods=['POST'])
@require_auth({'CustomerService', 'PlatformAdmin'})
def waive_fine(id):
    f = Fine.query.get(id)
    if not f:
        return err('ERR_NOT_FOUND', 'Fine not found.')
    if f.settlement_status != 'PENDING':
        return err('ERR_INVALID_STATE', 'Fine must be PENDING to waive.')
    f.settlement_status = 'WAIVED'

    if f.subject_type == 'RIDER':
        rider = Rider.query.get(f.subject_id)
        if rider:
            rider.wallet_balance_cents += f.amount_cents
            rider.touch()
    elif f.subject_type == 'CUSTOMER':
        customer = Customer.query.get(f.subject_id)
        if customer:
            customer.credit_balance_cents += f.amount_cents
            customer.touch()
    elif f.subject_type == 'RESTAURANT':
        restaurant = Restaurant.query.get(f.subject_id)
        if restaurant:
            restaurant.pending_settlement_cents += f.amount_cents
            restaurant.touch()

    db.session.commit()
    return success_response(f.to_dict())
