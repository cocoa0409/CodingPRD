"""Merchandising sessions, offer reads, acceptance and decline."""
from flask import Blueprint

import envelope as env
import ser
import svc
import validate as v
from errors import fail
from store import by_created, db, now, touch

bp = Blueprint('offers', __name__)

TOUCHPOINTS = ('BOOKING', 'CHECKIN', 'INFLIGHT')
OFFER_STATUS = ('PRESENTED', 'ACCEPTED', 'DECLINED', 'EXPIRED', 'SUPERSEDED')
TOUCHPOINT_PHASE = {'BOOKING': 'PRESALE', 'CHECKIN': 'CHECKIN_OPEN',
                    'INFLIGHT': 'BOARDING'}


def scope(booking, uid, role):
    if role == 'ChannelPartner' and booking['distribution_channel_id'] != uid:
        fail('ERR_CHANNEL_SCOPE_VIOLATION')


@bp.post('/bookings/<id>/offer-sessions')
def run_session(id):
    uid, role = v.ctx(('ChannelPartner',))
    data = v.fields(v.body(), [
        ('touchpoint', True, lambda x: v.v_enum(x, TOUCHPOINTS)),
        ('requested_product_ids', False, lambda x: v.v_id_array(x)),
    ])
    booking = svc.booking_or_404(id)
    requested = data.get('requested_product_ids')
    if requested is not None:
        for product_id in requested:
            svc.product_or_404(product_id)
    scope(booking, uid, role)
    if booking['booking_status'] not in ('HELD', 'TICKETED'):
        fail('ERR_BOOKING_STATE_INVALID')
    flight = db.flights[booking['flight_id']]
    family = db.families[booking['fare_family_id']]
    channel = db.channels[booking['distribution_channel_id']]
    if flight['sales_phase'] != TOUCHPOINT_PHASE[data['touchpoint']]:
        fail('ERR_TOUCHPOINT_PHASE_MISMATCH')
    if requested is not None:
        for product_id in requested:
            if db.products[product_id]['category'] not in channel['supported_categories']:
                fail('ERR_CHANNEL_CATEGORY_UNSUPPORTED')
        # an explicitly named product inside its cool-off is an error, while an
        # unnamed one is merely filtered out of the pool
        for product_id in requested:
            if svc.declined_cooloff_active(booking['id'], product_id):
                fail('ERR_OFFER_COOLOFF_CONFLICT')
    result = svc.run_offer_session(booking, family, flight, channel,
                                   data['touchpoint'], requested)
    return env.created(result)


@bp.get('/ancillary-offers/<id>')
def read_offer(id):
    uid, role = v.ctx(v.ALL_ROLES)
    offer = svc.offer_or_404(id)
    scope(db.bookings[offer['booking_id']], uid, role)
    return env.obj(ser.offer(offer))


@bp.get('/ancillary-offers')
def list_offers():
    uid, role = v.ctx(v.ALL_ROLES)
    limit, offset = v.pagination()
    booking_id = v.q_str('booking_id')
    product_id = v.q_str('ancillary_product_id')
    touchpoint = v.q_enum('touchpoint', TOUCHPOINTS)
    status = v.q_enum('offer_status', OFFER_STATUS)
    rows = [o for o in db.offers.values()
            if (booking_id is None or o['booking_id'] == booking_id)
            and (product_id is None or o['ancillary_product_id'] == product_id)
            and (touchpoint is None or o['touchpoint'] == touchpoint)
            and (status is None or o['offer_status'] == status)]
    if role == 'ChannelPartner':
        rows = [o for o in rows
                if db.bookings[o['booking_id']]['distribution_channel_id'] == uid]
    return env.page(by_created(rows), ser.offer, limit, offset)


@bp.post('/ancillary-offers/<id>/accept')
def accept_offer(id):
    uid, role = v.ctx(('ChannelPartner',))
    data = v.fields(v.body(), [
        ('expected_booking_version', True, v.v_int),
    ])
    offer = svc.offer_or_404(id)
    booking = db.bookings[offer['booking_id']]
    scope(booking, uid, role)
    if booking['booking_status'] not in ('HELD', 'TICKETED'):
        fail('ERR_BOOKING_STATE_INVALID')
    if offer['offer_status'] != 'PRESENTED':
        fail('ERR_OFFER_STATE_INVALID')
    if not (offer['valid_from'] <= now() < offer['valid_until']):
        fail('ERR_OFFER_WINDOW_CLOSED')
    if data['expected_booking_version'] != booking['version']:
        fail('ERR_STALE_BOOKING_VERSION')
    channel = db.channels[booking['distribution_channel_id']]
    if channel['content_parity_status'] != 'COMPLIANT':
        fail('ERR_CHANNEL_CONTENT_PARITY_BREACH')
    product = db.products[offer['ancillary_product_id']]
    if product['category'] not in channel['supported_categories']:
        fail('ERR_CHANNEL_CATEGORY_UNSUPPORTED')
    # the channel ceiling is enforced here, never at pricing time
    if offer['offered_price_cents'] > channel['max_ancillary_price_cents']:
        fail('ERR_OFFER_PRICE_CAP_EXCEEDED')
    offer['offer_status'] = 'ACCEPTED'
    offer['accepted_price_cents'] = offer['offered_price_cents']
    touch(offer)
    svc.post_entry(booking, product['category'], 'SALE',
                   offer['accepted_price_cents'], product['tax_treatment'],
                   product['revenue_class'], product['revenue_account_code'],
                   product['sku'], 'offer:' + offer['id'])
    for sibling in svc.offers_of_booking(booking['id']):
        if (sibling['id'] != offer['id']
                and sibling['ancillary_product_id'] == product['id']
                and sibling['offer_status'] == 'PRESENTED'):
            svc.supersede_offer(sibling)
    svc.recompute_booking_money(booking)
    touch(booking)
    return env.obj(ser.offer(offer))


@bp.post('/ancillary-offers/<id>/decline')
def decline_offer(id):
    uid, role = v.ctx(('ChannelPartner',))
    v.fields(v.body(), [])
    offer = svc.offer_or_404(id)
    booking = db.bookings[offer['booking_id']]
    scope(booking, uid, role)
    if offer['offer_status'] != 'PRESENTED':
        fail('ERR_OFFER_STATE_INVALID')
    if not (offer['valid_from'] <= now() < offer['valid_until']):
        fail('ERR_OFFER_WINDOW_CLOSED')
    offer['offer_status'] = 'DECLINED'
    # updated_at anchors the cool-off window for this (booking, product) pair
    touch(offer)
    return env.obj(ser.offer(offer))
