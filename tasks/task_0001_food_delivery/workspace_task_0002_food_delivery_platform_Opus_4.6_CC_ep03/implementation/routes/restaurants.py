from flask import Blueprint, request, g
from middleware.auth import require_auth
from models.database import db, Restaurant, MenuItem
from services.restaurant_service import (
    create_restaurant, approve_restaurant, suspend_restaurant,
    reinstate_restaurant, settle_restaurant, create_menu_item,
)
from utils.response import success_response, err

bp = Blueprint('restaurants', __name__)

ALL_ROLES = {'PlatformAdmin', 'Customer', 'Restaurant', 'Rider', 'CustomerService'}


def _check_version(resource, data):
    if 'version' in data and data['version'] is not None:
        if data['version'] != resource.version:
            return err('ERR_VERSION_CONFLICT', 'Version mismatch.')
    return None


@bp.route('/api/restaurants', methods=['POST'])
@require_auth({'PlatformAdmin'})
def register_restaurant():
    data = request.get_json(silent=True) or {}
    name = data.get('name')
    if not name or not isinstance(name, str) or len(name.strip()) == 0 or len(name) > 120:
        return err('ERR_VALIDATION', 'Invalid name.')
    if 'address' not in data:
        return err('ERR_VALIDATION', 'Address is required.')
    if 'lat' not in data or 'lng' not in data:
        return err('ERR_VALIDATION', 'Coordinates are required.')
    try:
        lat = float(data['lat'])
        lng = float(data['lng'])
    except (TypeError, ValueError):
        return err('ERR_VALIDATION', 'Invalid coordinates.')
    override = data.get('commission_rate_override')
    if override is not None:
        try:
            override = float(override)
        except (TypeError, ValueError):
            return err('ERR_VALIDATION', 'Invalid commission rate.')
        if override < 0.05 or override > 0.35:
            return err('ERR_VALIDATION', 'Commission rate must be between 0.05 and 0.35.')
    existing = Restaurant.query.filter_by(name=name).filter(
        Restaurant.status.in_(['PENDING_APPROVAL', 'ACTIVE', 'SUSPENDED'])
    ).first()
    if existing:
        return err('ERR_VALIDATION', 'Restaurant name must be unique among active restaurants.')
    r = create_restaurant({
        'name': name,
        'address': data['address'],
        'lat': lat,
        'lng': lng,
        'commission_rate_override': override,
    })
    db.session.commit()
    return success_response(r.to_dict(), 201)


@bp.route('/api/restaurants', methods=['GET'])
@require_auth(ALL_ROLES)
def list_restaurants():
    query = Restaurant.query
    status_filter = request.args.get('status')
    if status_filter:
        query = query.filter_by(status=status_filter)
    query = query.order_by(Restaurant.created_at.asc())
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
        [r.to_dict() for r in items],
        response_type='array',
        pagination={
            'limit': limit,
            'offset': offset,
            'total_count': total,
            'has_more': offset + limit < total,
        },
    )


@bp.route('/api/restaurants/<id>', methods=['GET'])
@require_auth(ALL_ROLES)
def get_restaurant(id):
    r = Restaurant.query.get(id)
    if not r:
        return err('ERR_NOT_FOUND', 'Restaurant not found.')
    return success_response(r.to_dict())


@bp.route('/api/restaurants/<id>', methods=['PATCH'])
@require_auth({'PlatformAdmin', 'Restaurant'})
def update_restaurant(id):
    r = Restaurant.query.get(id)
    if not r:
        return err('ERR_NOT_FOUND', 'Restaurant not found.')
    if g.user_role == 'Restaurant' and g.user_id != r.id:
        return err('ERR_FORBIDDEN', 'Not your restaurant.')
    data = request.get_json(silent=True) or {}
    updates = {}
    if 'address' in data:
        updates['address'] = data['address']
    if 'lat' in data:
        try:
            updates['lat'] = float(data['lat'])
        except (TypeError, ValueError):
            return err('ERR_VALIDATION', 'Invalid lat.')
    if 'lng' in data:
        try:
            updates['lng'] = float(data['lng'])
        except (TypeError, ValueError):
            return err('ERR_VALIDATION', 'Invalid lng.')
    if 'commission_rate_override' in data:
        val = data['commission_rate_override']
        if val is not None:
            try:
                val = float(val)
            except (TypeError, ValueError):
                return err('ERR_VALIDATION', 'Invalid commission rate.')
            if val < 0.05 or val > 0.35:
                return err('ERR_VALIDATION', 'Commission rate must be between 0.05 and 0.35.')
        updates['commission_rate_override'] = val
    ver_err = _check_version(r, data)
    if ver_err:
        return ver_err
    for k, v in updates.items():
        setattr(r, k, v)
    r.touch()
    db.session.commit()
    return success_response(r.to_dict())


@bp.route('/api/restaurants/<id>/approve', methods=['POST'])
@require_auth({'PlatformAdmin'})
def approve(id):
    r = Restaurant.query.get(id)
    if not r:
        return err('ERR_NOT_FOUND', 'Restaurant not found.')
    if r.status != 'PENDING_APPROVAL':
        return err('ERR_INVALID_STATE', 'Restaurant is not pending approval.')
    approve_restaurant(r)
    db.session.commit()
    return success_response(r.to_dict())


@bp.route('/api/restaurants/<id>/suspend', methods=['POST'])
@require_auth({'PlatformAdmin'})
def suspend(id):
    r = Restaurant.query.get(id)
    if not r:
        return err('ERR_NOT_FOUND', 'Restaurant not found.')
    if r.status != 'ACTIVE':
        return err('ERR_INVALID_STATE', 'Restaurant is not active.')
    suspend_restaurant(r)
    db.session.commit()
    return success_response(r.to_dict())


@bp.route('/api/restaurants/<id>/reinstate', methods=['POST'])
@require_auth({'PlatformAdmin'})
def reinstate(id):
    r = Restaurant.query.get(id)
    if not r:
        return err('ERR_NOT_FOUND', 'Restaurant not found.')
    if r.status != 'SUSPENDED':
        return err('ERR_INVALID_STATE', 'Restaurant is not suspended.')
    reinstate_restaurant(r)
    db.session.commit()
    return success_response(r.to_dict())


@bp.route('/api/restaurants/<id>/settle', methods=['POST'])
@require_auth({'PlatformAdmin'})
def settle(id):
    r = Restaurant.query.get(id)
    if not r:
        return err('ERR_NOT_FOUND', 'Restaurant not found.')
    settle_restaurant(r)
    db.session.commit()
    return success_response(r.to_dict())


@bp.route('/api/restaurants/<restaurant_id>/menu-items', methods=['POST'])
@require_auth({'Restaurant', 'PlatformAdmin'})
def create_menu_item_route(restaurant_id):
    r = Restaurant.query.get(restaurant_id)
    if not r:
        return err('ERR_NOT_FOUND', 'Restaurant not found.')
    if g.user_role == 'Restaurant' and g.user_id != r.id:
        return err('ERR_FORBIDDEN', 'Not your restaurant.')
    data = request.get_json(silent=True) or {}
    if 'name' not in data or not data['name']:
        return err('ERR_VALIDATION', 'Name is required.')
    if 'price_cents' not in data:
        return err('ERR_VALIDATION', 'Price is required.')
    try:
        price = int(data['price_cents'])
    except (TypeError, ValueError):
        return err('ERR_VALIDATION', 'Invalid price.')
    if price < 1 or price > 1000000:
        return err('ERR_VALIDATION', 'Price must be between 1 and 1000000.')
    mi = create_menu_item(restaurant_id, {
        'name': data['name'],
        'price_cents': price,
        'is_listed': data.get('is_listed', True),
    })
    db.session.commit()
    return success_response(mi.to_dict(), 201)


@bp.route('/api/restaurants/<restaurant_id>/menu-items', methods=['GET'])
@require_auth(ALL_ROLES)
def list_menu_items(restaurant_id):
    r = Restaurant.query.get(restaurant_id)
    if not r:
        return err('ERR_NOT_FOUND', 'Restaurant not found.')
    query = MenuItem.query.filter_by(restaurant_id=restaurant_id)
    is_listed = request.args.get('is_listed')
    if is_listed is not None:
        val = is_listed.lower() == 'true'
        query = query.filter_by(is_listed=val)
    query = query.order_by(MenuItem.created_at.asc())
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
        [mi.to_dict() for mi in items],
        response_type='array',
        pagination={
            'limit': limit,
            'offset': offset,
            'total_count': total,
            'has_more': offset + limit < total,
        },
    )


@bp.route('/api/menu-items/<id>', methods=['PATCH'])
@require_auth({'Restaurant', 'PlatformAdmin'})
def update_menu_item(id):
    mi = MenuItem.query.get(id)
    if not mi:
        return err('ERR_NOT_FOUND', 'Menu item not found.')
    if g.user_role == 'Restaurant' and g.user_id != mi.restaurant_id:
        return err('ERR_FORBIDDEN', 'Not your menu item.')
    data = request.get_json(silent=True) or {}
    updates = {}
    if 'price_cents' in data:
        try:
            price = int(data['price_cents'])
        except (TypeError, ValueError):
            return err('ERR_VALIDATION', 'Invalid price.')
        if price < 1 or price > 1000000:
            return err('ERR_VALIDATION', 'Price must be between 1 and 1000000.')
        updates['price_cents'] = price
    if 'is_listed' in data:
        updates['is_listed'] = bool(data['is_listed'])
    ver_err = _check_version(mi, data)
    if ver_err:
        return ver_err
    for k, v in updates.items():
        setattr(mi, k, v)
    mi.touch()
    db.session.commit()
    return success_response(mi.to_dict())
