from flask import Blueprint, request, g
from middleware.auth import require_auth
from models.database import db, Order, Customer, Restaurant, Assignment
from services.order_service import place_order
from services.dispatch_service import dispatch_order, get_rejected_rider_ids
from utils.response import success_response, err

bp = Blueprint('orders', __name__)

ALL_ROLES = {'PlatformAdmin', 'Customer', 'Restaurant', 'Rider', 'CustomerService'}


@bp.route('/api/orders', methods=['POST'])
@require_auth({'Customer'})
def create_order():
    data = request.get_json(silent=True) or {}
    customer_id = data.get('customer_id')
    restaurant_id = data.get('restaurant_id')
    if not customer_id:
        return err('ERR_VALIDATION', 'customer_id is required.')
    if not restaurant_id:
        return err('ERR_VALIDATION', 'restaurant_id is required.')
    customer = Customer.query.get(customer_id)
    if not customer:
        return err('ERR_NOT_FOUND', 'Customer not found.')
    restaurant = Restaurant.query.get(restaurant_id)
    if not restaurant:
        return err('ERR_NOT_FOUND', 'Restaurant not found.')
    if g.user_id != customer_id:
        return err('ERR_FORBIDDEN', 'Cannot place an order for another customer.')
    if restaurant.status != 'ACTIVE':
        return err('ERR_RESTAURANT_UNAVAILABLE', 'Restaurant is not active.')
    order, error_id, message = place_order(data, customer, restaurant)
    if error_id:
        return err(error_id, message)
    db.session.commit()
    return success_response(order.to_dict(), 201)


@bp.route('/api/orders/<id>', methods=['GET'])
@require_auth(ALL_ROLES)
def get_order(id):
    order = Order.query.get(id)
    if not order:
        return err('ERR_NOT_FOUND', 'Order not found.')
    if g.user_role == 'Customer' and g.user_id != order.customer_id:
        return err('ERR_FORBIDDEN', 'Not your order.')
    if g.user_role == 'Restaurant' and g.user_id != order.restaurant_id:
        return err('ERR_FORBIDDEN', 'Not your order.')
    if g.user_role == 'Rider':
        assignment = Assignment.query.filter_by(
            order_id=order.id, rider_id=g.user_id
        ).first()
        if not assignment:
            return err('ERR_FORBIDDEN', 'Not your order.')
    return success_response(order.to_dict())


@bp.route('/api/orders', methods=['GET'])
@require_auth(ALL_ROLES)
def list_orders():
    query = Order.query
    customer_id = request.args.get('customer_id')
    restaurant_id = request.args.get('restaurant_id')
    rider_id = request.args.get('rider_id')
    status_filter = request.args.get('status')
    if customer_id:
        if g.user_role == 'Customer' and g.user_id != customer_id:
            return err('ERR_FORBIDDEN', 'Cannot view other customer orders.')
        query = query.filter_by(customer_id=customer_id)
    if restaurant_id:
        if g.user_role == 'Restaurant' and g.user_id != restaurant_id:
            return err('ERR_FORBIDDEN', 'Cannot view other restaurant orders.')
        query = query.filter_by(restaurant_id=restaurant_id)
    if rider_id:
        if g.user_role == 'Rider' and g.user_id != rider_id:
            return err('ERR_FORBIDDEN', 'Cannot view other rider orders.')
        order_ids = [a.order_id for a in Assignment.query.filter_by(rider_id=rider_id).all()]
        query = query.filter(Order.id.in_(order_ids)) if order_ids else query.filter(Order.id == None)
    if status_filter:
        query = query.filter_by(status=status_filter)
    if g.user_role == 'Customer' and not customer_id:
        query = query.filter_by(customer_id=g.user_id)
    if g.user_role == 'Restaurant' and not restaurant_id:
        query = query.filter_by(restaurant_id=g.user_id)
    if g.user_role == 'Rider' and not rider_id:
        order_ids = [a.order_id for a in Assignment.query.filter_by(rider_id=g.user_id).all()]
        query = query.filter(Order.id.in_(order_ids)) if order_ids else query.filter(Order.id == None)
    query = query.order_by(Order.created_at.asc())
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
        [o.to_dict() for o in items],
        response_type='array',
        pagination={
            'limit': limit,
            'offset': offset,
            'total_count': total,
            'has_more': offset + limit < total,
        },
    )


@bp.route('/api/orders/<id>/accept', methods=['POST'])
@require_auth({'Restaurant'})
def accept_order(id):
    order = Order.query.get(id)
    if not order:
        return err('ERR_NOT_FOUND', 'Order not found.')
    if g.user_id != order.restaurant_id:
        return err('ERR_FORBIDDEN', 'Not your order.')
    restaurant = Restaurant.query.get(order.restaurant_id)
    if restaurant.status != 'ACTIVE':
        return err('ERR_INVALID_STATE', 'Restaurant is not active.')
    if order.status != 'PLACED':
        return err('ERR_INVALID_STATE', 'Order must be in PLACED state.')
    order.status = 'RESTAURANT_ACCEPTED'
    order.touch()
    db.session.commit()
    return success_response(order.to_dict())


@bp.route('/api/orders/<id>/cancel', methods=['POST'])
@require_auth({'Customer', 'Restaurant', 'CustomerService'})
def cancel_order(id):
    order = Order.query.get(id)
    if not order:
        return err('ERR_NOT_FOUND', 'Order not found.')
    if g.user_role == 'Customer' and g.user_id != order.customer_id:
        return err('ERR_FORBIDDEN', 'Not your order.')
    if g.user_role == 'Restaurant' and g.user_id != order.restaurant_id:
        return err('ERR_FORBIDDEN', 'Not your order.')
    if order.status != 'PLACED':
        return err('ERR_INVALID_STATE', 'Order can only be cancelled from PLACED.')
    order.status = 'CANCELLED'
    if order.payment_status in ('UNPAID', 'AUTHORIZED'):
        order.payment_status = 'VOIDED'
    order.touch()
    db.session.commit()
    return success_response(order.to_dict())


@bp.route('/api/orders/<id>/start-preparing', methods=['POST'])
@require_auth({'Restaurant'})
def start_preparing(id):
    order = Order.query.get(id)
    if not order:
        return err('ERR_NOT_FOUND', 'Order not found.')
    if g.user_id != order.restaurant_id:
        return err('ERR_FORBIDDEN', 'Not your order.')
    if order.status != 'RESTAURANT_ACCEPTED':
        return err('ERR_INVALID_STATE', 'Order must be RESTAURANT_ACCEPTED.')
    order.status = 'PREPARING'
    order.touch()
    exclude_ids = get_rejected_rider_ids(order.id)
    assignment = dispatch_order(order, exclude_rider_ids=exclude_ids)
    db.session.commit()
    return success_response(order.to_dict())


@bp.route('/api/orders/<id>/ready', methods=['POST'])
@require_auth({'Restaurant'})
def mark_ready(id):
    order = Order.query.get(id)
    if not order:
        return err('ERR_NOT_FOUND', 'Order not found.')
    if g.user_id != order.restaurant_id:
        return err('ERR_FORBIDDEN', 'Not your order.')
    if order.status != 'PREPARING':
        return err('ERR_INVALID_STATE', 'Order must be PREPARING.')
    active_assignment = Assignment.query.filter_by(order_id=order.id).filter(
        Assignment.status.in_(['ACCEPTED', 'PICKED_UP'])
    ).first()
    if not active_assignment:
        return err('ERR_INVALID_STATE', 'No rider has accepted the order yet.')
    order.status = 'READY_FOR_PICKUP'
    order.touch()
    db.session.commit()
    return success_response(order.to_dict())


@bp.route('/api/orders/<id>/dispatch', methods=['POST'])
@require_auth({'PlatformAdmin', 'CustomerService'})
def manual_dispatch(id):
    order = Order.query.get(id)
    if not order:
        return err('ERR_NOT_FOUND', 'Order not found.')
    active_assignment = Assignment.query.filter_by(order_id=order.id).filter(
        Assignment.status.in_(['OFFERED', 'ACCEPTED', 'PICKED_UP'])
    ).first()
    if active_assignment:
        return err('ERR_ORDER_ALREADY_ASSIGNED', 'Order already has an active assignment.')
    exclude_ids = get_rejected_rider_ids(order.id)
    assignment = dispatch_order(order, exclude_rider_ids=exclude_ids)
    if not assignment:
        return err('ERR_VALIDATION', 'No available rider for dispatch.')
    db.session.commit()
    return success_response(assignment.to_dict(), 201)
