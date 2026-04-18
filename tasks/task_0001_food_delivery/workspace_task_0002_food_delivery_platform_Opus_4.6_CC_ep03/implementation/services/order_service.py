from datetime import timedelta
from models.database import db, Order, Customer, Restaurant, MenuItem
from utils.clock import clock
from utils.calculations import (
    haversine_km, compute_delivery_fee, compute_tiered_commission,
    is_peak_time,
)


def place_order(data, customer, restaurant):
    items = data.get('items', [])
    if not items:
        return None, 'ERR_ORDER_INVALID', 'Items cannot be empty.'
    processed_items = []
    for item in items:
        mid = item.get('menu_item_id')
        if not mid:
            return None, 'ERR_ORDER_INVALID', 'Each item must have a menu_item_id.'
        mi = MenuItem.query.get(mid)
        if not mi:
            return None, 'ERR_NOT_FOUND', f'Menu item {mid} not found.'
        if mi.restaurant_id != restaurant.id:
            return None, 'ERR_RESTAURANT_UNAVAILABLE', 'Menu item does not belong to this restaurant.'
        if not mi.is_listed:
            return None, 'ERR_RESTAURANT_UNAVAILABLE', 'Menu item is not listed.'
        qty = item.get('quantity', 1)
        if not isinstance(qty, int) or qty < 1:
            return None, 'ERR_ORDER_INVALID', 'Quantity must be at least 1.'
        processed_items.append({
            'menu_item_id': mi.id,
            'name': mi.name,
            'unit_price_cents': mi.price_cents,
            'quantity': qty,
        })

    subtotal = sum(i['unit_price_cents'] * i['quantity'] for i in processed_items)
    if subtotal < 100:
        return None, 'ERR_ORDER_INVALID', 'Subtotal must be at least 100 cents.'

    now = clock.now()
    peak = is_peak_time(now)
    dist = haversine_km(restaurant.lat, restaurant.lng, customer.lat, customer.lng)
    prov_fee = compute_delivery_fee(dist, peak)
    prov_commission = compute_tiered_commission(subtotal)
    promised = now + timedelta(minutes=45)

    order = Order(
        customer_id=customer.id,
        restaurant_id=restaurant.id,
        status='PLACED',
        payment_status='AUTHORIZED',
        items=processed_items,
        subtotal_cents=subtotal,
        distance_km=dist,
        is_peak=peak,
        promised_delivery_time=clock.format(promised),
        provisional_delivery_fee_cents=prov_fee,
        provisional_commission_cents=prov_commission,
    )
    db.session.add(order)
    db.session.flush()
    return order, None, None
