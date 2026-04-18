from flask import Blueprint, request, g
from middleware.auth import require_auth
from models.database import db, WorkOrder, Order, Return
from utils.response import success_response, err

bp = Blueprint('work_orders', __name__)

ALL_ROLES = {'PlatformAdmin', 'CustomerService', 'Customer', 'Rider', 'Restaurant'}
VALID_CATEGORIES = {
    'DELIVERY_LATE', 'FOOD_QUALITY', 'MISSING_ITEM', 'RIDER_BEHAVIOR',
    'RESTAURANT_BEHAVIOR', 'PAYMENT_ISSUE', 'OTHER',
}
VALID_OPENER_ROLES = {'CUSTOMER', 'RIDER', 'RESTAURANT', 'CUSTOMER_SERVICE'}

ROLE_TO_OPENER = {
    'Customer': 'CUSTOMER',
    'Rider': 'RIDER',
    'Restaurant': 'RESTAURANT',
    'CustomerService': 'CUSTOMER_SERVICE',
    'PlatformAdmin': 'CUSTOMER_SERVICE',
}


@bp.route('/api/work-orders', methods=['POST'])
@require_auth(ALL_ROLES)
def create_work_order():
    data = request.get_json(silent=True) or {}
    opened_by_role = data.get('opened_by_role')
    if opened_by_role not in VALID_OPENER_ROLES:
        return err('ERR_VALIDATION', 'Invalid opened_by_role.')
    opened_by_id = data.get('opened_by_id')
    if not opened_by_id:
        return err('ERR_VALIDATION', 'opened_by_id is required.')
    category = data.get('category')
    if category not in VALID_CATEGORIES:
        return err('ERR_VALIDATION', 'Invalid category.')
    related_order_id = data.get('related_order_id')
    related_return_id = data.get('related_return_id')
    if related_order_id:
        order = Order.query.get(related_order_id)
        if not order:
            return err('ERR_NOT_FOUND', 'Related order not found.')
    if related_return_id:
        ret = Return.query.get(related_return_id)
        if not ret:
            return err('ERR_NOT_FOUND', 'Related return not found.')
    wo = WorkOrder(
        opened_by_role=opened_by_role,
        opened_by_id=opened_by_id,
        category=category,
        related_order_id=related_order_id,
        related_return_id=related_return_id,
    )
    db.session.add(wo)
    db.session.commit()
    return success_response(wo.to_dict(), 201)


@bp.route('/api/work-orders/<id>', methods=['GET'])
@require_auth(ALL_ROLES)
def get_work_order(id):
    wo = WorkOrder.query.get(id)
    if not wo:
        return err('ERR_NOT_FOUND', 'Work order not found.')
    return success_response(wo.to_dict())


@bp.route('/api/work-orders/<id>/assign', methods=['POST'])
@require_auth({'CustomerService', 'PlatformAdmin'})
def assign_work_order(id):
    wo = WorkOrder.query.get(id)
    if not wo:
        return err('ERR_NOT_FOUND', 'Work order not found.')
    if wo.status != 'OPEN':
        return err('ERR_INVALID_STATE', 'Work order must be OPEN.')
    wo.assigned_cs_user_id = g.user_id
    wo.status = 'UNDER_REVIEW'
    wo.touch()
    db.session.commit()
    return success_response(wo.to_dict())


@bp.route('/api/work-orders/<id>/request-info', methods=['POST'])
@require_auth({'CustomerService', 'PlatformAdmin'})
def request_info(id):
    wo = WorkOrder.query.get(id)
    if not wo:
        return err('ERR_NOT_FOUND', 'Work order not found.')
    if wo.status != 'UNDER_REVIEW':
        return err('ERR_INVALID_STATE', 'Work order must be UNDER_REVIEW.')
    wo.status = 'AWAITING_INFO'
    wo.touch()
    db.session.commit()
    return success_response(wo.to_dict())


@bp.route('/api/work-orders/<id>/submit-info', methods=['POST'])
@require_auth({'Customer', 'Rider', 'Restaurant'})
def submit_info(id):
    wo = WorkOrder.query.get(id)
    if not wo:
        return err('ERR_NOT_FOUND', 'Work order not found.')
    if wo.status != 'AWAITING_INFO':
        return err('ERR_INVALID_STATE', 'Work order must be AWAITING_INFO.')
    if g.user_id != wo.opened_by_id:
        return err('ERR_FORBIDDEN', 'Only the opener can submit info.')
    wo.status = 'UNDER_REVIEW'
    wo.touch()
    db.session.commit()
    return success_response(wo.to_dict())


@bp.route('/api/work-orders/<id>/resolve', methods=['POST'])
@require_auth({'CustomerService', 'PlatformAdmin'})
def resolve_work_order(id):
    wo = WorkOrder.query.get(id)
    if not wo:
        return err('ERR_NOT_FOUND', 'Work order not found.')
    if wo.status not in ('UNDER_REVIEW', 'ESCALATED'):
        return err('ERR_INVALID_STATE', 'Work order must be UNDER_REVIEW or ESCALATED.')
    if not wo.assigned_cs_user_id:
        return err('ERR_INVALID_STATE', 'Work order must have an assigned CS user.')
    if wo.related_return_id:
        ret = Return.query.get(wo.related_return_id)
        if ret and ret.status in ('REQUESTED', 'ESCALATED'):
            return err('ERR_RELATED_RETURN_UNRESOLVED', 'Linked return must be resolved first.')
    data = request.get_json(silent=True) or {}
    wo.resolution_notes = data.get('resolution_notes', '')
    wo.status = 'RESOLVED'
    wo.touch()
    db.session.commit()
    return success_response(wo.to_dict())


@bp.route('/api/work-orders/<id>/escalate', methods=['POST'])
@require_auth({'CustomerService', 'PlatformAdmin'})
def escalate_work_order(id):
    wo = WorkOrder.query.get(id)
    if not wo:
        return err('ERR_NOT_FOUND', 'Work order not found.')
    if wo.status != 'UNDER_REVIEW':
        return err('ERR_INVALID_STATE', 'Work order must be UNDER_REVIEW.')
    wo.status = 'ESCALATED'
    wo.touch()
    db.session.commit()
    return success_response(wo.to_dict())


@bp.route('/api/work-orders/<id>/close', methods=['POST'])
@require_auth({'CustomerService', 'PlatformAdmin'})
def close_work_order(id):
    wo = WorkOrder.query.get(id)
    if not wo:
        return err('ERR_NOT_FOUND', 'Work order not found.')
    if wo.status != 'RESOLVED':
        return err('ERR_INVALID_STATE', 'Work order must be RESOLVED.')
    wo.status = 'CLOSED'
    wo.touch()
    db.session.commit()
    return success_response(wo.to_dict())
