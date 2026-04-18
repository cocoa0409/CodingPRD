from flask import Blueprint, g
from middleware.auth import require_auth
from models.database import db, Assignment, Order, Rider
from services.assignment_service import (
    accept_assignment, reject_assignment, pickup_assignment,
    deliver_assignment, cancel_assignment,
)
from utils.response import success_response, err

bp = Blueprint('assignments', __name__)


@bp.route('/api/assignments/<id>', methods=['GET'])
@require_auth({'PlatformAdmin', 'Rider', 'CustomerService'})
def get_assignment(id):
    a = Assignment.query.get(id)
    if not a:
        return err('ERR_NOT_FOUND', 'Assignment not found.')
    if g.user_role == 'Rider' and g.user_id != a.rider_id:
        return err('ERR_FORBIDDEN', 'Not your assignment.')
    return success_response(a.to_dict())


@bp.route('/api/assignments/<id>/accept', methods=['POST'])
@require_auth({'Rider'})
def accept(id):
    a = Assignment.query.get(id)
    if not a:
        return err('ERR_NOT_FOUND', 'Assignment not found.')
    if g.user_id != a.rider_id:
        return err('ERR_FORBIDDEN', 'Not your assignment.')
    rider = Rider.query.get(a.rider_id)
    if rider.status not in ('AVAILABLE', 'ON_DELIVERY'):
        return err('ERR_INVALID_STATE', 'Rider must be AVAILABLE or ON_DELIVERY.')
    if a.status != 'OFFERED':
        return err('ERR_INVALID_STATE', 'Assignment must be OFFERED.')
    order = Order.query.get(a.order_id)
    if order.status not in ('RESTAURANT_ACCEPTED', 'PREPARING', 'READY_FOR_PICKUP'):
        return err('ERR_INVALID_STATE', 'Order is not in a valid state for acceptance.')
    existing = Assignment.query.filter_by(order_id=a.order_id).filter(
        Assignment.status.in_(['ACCEPTED', 'PICKED_UP'])
    ).first()
    if existing:
        return err('ERR_ORDER_ALREADY_ASSIGNED', 'Order already has an accepted assignment.')
    result, error_id = accept_assignment(a, rider)
    if error_id:
        return err(error_id, 'Assignment could not be accepted.')
    db.session.commit()
    return success_response(result.to_dict())


@bp.route('/api/assignments/<id>/reject', methods=['POST'])
@require_auth({'Rider'})
def reject(id):
    a = Assignment.query.get(id)
    if not a:
        return err('ERR_NOT_FOUND', 'Assignment not found.')
    if g.user_id != a.rider_id:
        return err('ERR_FORBIDDEN', 'Not your assignment.')
    if a.status != 'OFFERED':
        return err('ERR_INVALID_STATE', 'Assignment must be OFFERED.')
    result = reject_assignment(a, Rider.query.get(a.rider_id))
    db.session.commit()
    return success_response(result.to_dict())


@bp.route('/api/assignments/<id>/pickup', methods=['POST'])
@require_auth({'Rider'})
def pickup(id):
    a = Assignment.query.get(id)
    if not a:
        return err('ERR_NOT_FOUND', 'Assignment not found.')
    if g.user_id != a.rider_id:
        return err('ERR_FORBIDDEN', 'Not your assignment.')
    if a.status != 'ACCEPTED':
        return err('ERR_INVALID_STATE', 'Assignment must be ACCEPTED.')
    order = Order.query.get(a.order_id)
    if order.status != 'READY_FOR_PICKUP':
        return err('ERR_INVALID_STATE', 'Order must be READY_FOR_PICKUP.')
    result = pickup_assignment(a)
    db.session.commit()
    return success_response(result.to_dict())


@bp.route('/api/assignments/<id>/deliver', methods=['POST'])
@require_auth({'Rider'})
def deliver(id):
    a = Assignment.query.get(id)
    if not a:
        return err('ERR_NOT_FOUND', 'Assignment not found.')
    if g.user_id != a.rider_id:
        return err('ERR_FORBIDDEN', 'Not your assignment.')
    if a.status != 'PICKED_UP':
        return err('ERR_INVALID_STATE', 'Assignment must be PICKED_UP.')
    order = Order.query.get(a.order_id)
    if order.status != 'PICKED_UP':
        return err('ERR_INVALID_STATE', 'Order must be PICKED_UP.')
    result = deliver_assignment(a)
    db.session.commit()
    return success_response(result.to_dict())


@bp.route('/api/assignments/<id>/cancel', methods=['POST'])
@require_auth({'Rider'})
def cancel(id):
    a = Assignment.query.get(id)
    if not a:
        return err('ERR_NOT_FOUND', 'Assignment not found.')
    if g.user_id != a.rider_id:
        return err('ERR_FORBIDDEN', 'Not your assignment.')
    if a.status != 'ACCEPTED':
        return err('ERR_INVALID_STATE', 'Assignment must be ACCEPTED to cancel.')
    order = Order.query.get(a.order_id)
    if order.status == 'PICKED_UP':
        return err('ERR_INVALID_STATE', 'Cannot cancel after pickup.')
    result = cancel_assignment(a)
    db.session.commit()
    return success_response(result.to_dict())
