from flask import Blueprint, request, g
from middleware.auth import require_auth
from models.database import db, Return, Order
from services.return_service import (
    open_return, approve_return, reject_return,
    escalate_return, reopen_return,
)
from utils.response import success_response, err

bp = Blueprint('returns', __name__)


@bp.route('/api/orders/<order_id>/returns', methods=['POST'])
@require_auth({'Customer'})
def create_return(order_id):
    order = Order.query.get(order_id)
    if not order:
        return err('ERR_NOT_FOUND', 'Order not found.')
    if g.user_id != order.customer_id:
        return err('ERR_FORBIDDEN', 'Not your order.')
    if order.status != 'DELIVERED':
        return err('ERR_INVALID_STATE', 'Order must be DELIVERED.')
    data = request.get_json(silent=True) or {}
    ret, error_id = open_return(order, data)
    if error_id:
        return err(error_id, f'Return creation failed: {error_id}')
    db.session.commit()
    return success_response(ret.to_dict(), 201)


@bp.route('/api/returns/<id>', methods=['GET'])
@require_auth({'PlatformAdmin', 'Customer', 'Restaurant', 'CustomerService'})
def get_return(id):
    ret = Return.query.get(id)
    if not ret:
        return err('ERR_NOT_FOUND', 'Return not found.')
    if g.user_role == 'Customer':
        order = Order.query.get(ret.order_id)
        if g.user_id != order.customer_id:
            return err('ERR_FORBIDDEN', 'Not your return.')
    if g.user_role == 'Restaurant':
        order = Order.query.get(ret.order_id)
        if g.user_id != order.restaurant_id:
            return err('ERR_FORBIDDEN', 'Not your return.')
    return success_response(ret.to_dict())


@bp.route('/api/returns/<id>/approve', methods=['POST'])
@require_auth({'CustomerService'})
def approve(id):
    ret = Return.query.get(id)
    if not ret:
        return err('ERR_NOT_FOUND', 'Return not found.')
    if ret.status not in ('REQUESTED', 'ESCALATED'):
        return err('ERR_INVALID_STATE', 'Return must be REQUESTED or ESCALATED.')
    data = request.get_json(silent=True) or {}
    error_id = approve_return(ret, data, g.user_id)
    if error_id:
        return err(error_id, f'Approval failed: {error_id}')
    db.session.commit()
    return success_response(ret.to_dict())


@bp.route('/api/returns/<id>/reject', methods=['POST'])
@require_auth({'CustomerService'})
def reject(id):
    ret = Return.query.get(id)
    if not ret:
        return err('ERR_NOT_FOUND', 'Return not found.')
    if ret.status not in ('REQUESTED', 'ESCALATED'):
        return err('ERR_INVALID_STATE', 'Return must be REQUESTED or ESCALATED.')
    reject_return(ret, g.user_id)
    db.session.commit()
    return success_response(ret.to_dict())


@bp.route('/api/returns/<id>/escalate', methods=['POST'])
@require_auth({'CustomerService'})
def escalate(id):
    ret = Return.query.get(id)
    if not ret:
        return err('ERR_NOT_FOUND', 'Return not found.')
    if ret.status != 'REQUESTED':
        return err('ERR_INVALID_STATE', 'Return must be REQUESTED.')
    wo = escalate_return(ret)
    db.session.commit()
    return success_response(ret.to_dict())


@bp.route('/api/returns/<id>/reopen', methods=['POST'])
@require_auth({'CustomerService'})
def reopen(id):
    ret = Return.query.get(id)
    if not ret:
        return err('ERR_NOT_FOUND', 'Return not found.')
    if ret.status != 'ESCALATED':
        return err('ERR_INVALID_STATE', 'Return must be ESCALATED.')
    reopen_return(ret)
    db.session.commit()
    return success_response(ret.to_dict())
