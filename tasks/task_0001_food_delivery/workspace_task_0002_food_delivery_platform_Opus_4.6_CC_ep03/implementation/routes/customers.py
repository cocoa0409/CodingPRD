from flask import Blueprint, request, g
from middleware.auth import require_auth
from models.database import db, Customer
from utils.response import success_response, err

bp = Blueprint('customers', __name__)


@bp.route('/api/customers', methods=['POST'])
@require_auth({'PlatformAdmin', 'CustomerService'})
def register_customer():
    data = request.get_json(silent=True) or {}
    for field in ('name', 'phone', 'address'):
        if field not in data or not data[field]:
            return err('ERR_VALIDATION', f'{field} is required.')
    if 'lat' not in data or 'lng' not in data:
        return err('ERR_VALIDATION', 'Coordinates are required.')
    try:
        lat = float(data['lat'])
        lng = float(data['lng'])
    except (TypeError, ValueError):
        return err('ERR_VALIDATION', 'Invalid coordinates.')
    existing = Customer.query.filter_by(phone=data['phone']).first()
    if existing:
        return err('ERR_VALIDATION', 'Phone must be unique.')
    c = Customer(
        name=data['name'],
        phone=data['phone'],
        address=data['address'],
        lat=lat,
        lng=lng,
    )
    db.session.add(c)
    db.session.commit()
    return success_response(c.to_dict(), 201)


@bp.route('/api/customers/<id>', methods=['GET'])
@require_auth({'PlatformAdmin', 'Customer', 'CustomerService'})
def get_customer(id):
    c = Customer.query.get(id)
    if not c:
        return err('ERR_NOT_FOUND', 'Customer not found.')
    if g.user_role == 'Customer' and g.user_id != c.id:
        return err('ERR_FORBIDDEN', 'Not your account.')
    return success_response(c.to_dict())
