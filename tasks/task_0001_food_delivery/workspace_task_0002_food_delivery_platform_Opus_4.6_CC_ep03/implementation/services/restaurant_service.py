from models.database import db, Restaurant, MenuItem, Order


def create_restaurant(data):
    r = Restaurant(
        name=data['name'],
        address=data['address'],
        lat=data['lat'],
        lng=data['lng'],
        commission_rate_override=data.get('commission_rate_override'),
    )
    db.session.add(r)
    db.session.flush()
    return r


def approve_restaurant(restaurant):
    restaurant.status = 'ACTIVE'
    restaurant.touch()


def suspend_restaurant(restaurant):
    restaurant.status = 'SUSPENDED'
    restaurant.touch()
    placed_orders = Order.query.filter_by(
        restaurant_id=restaurant.id, status='PLACED'
    ).all()
    for order in placed_orders:
        order.status = 'CANCELLED'
        if order.payment_status in ('UNPAID', 'AUTHORIZED'):
            order.payment_status = 'VOIDED'
        order.touch()


def reinstate_restaurant(restaurant):
    restaurant.status = 'ACTIVE'
    restaurant.touch()


def settle_restaurant(restaurant):
    restaurant.pending_settlement_cents = 0
    restaurant.touch()


def create_menu_item(restaurant_id, data):
    mi = MenuItem(
        restaurant_id=restaurant_id,
        name=data['name'],
        price_cents=data['price_cents'],
        is_listed=data.get('is_listed', True),
    )
    db.session.add(mi)
    db.session.flush()
    return mi
