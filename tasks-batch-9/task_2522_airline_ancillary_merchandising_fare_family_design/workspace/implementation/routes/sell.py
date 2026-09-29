"""Bookings, the fee disclosure, ticketing, changes, cancellation and seats."""
from flask import Blueprint

import calc
import envelope as env
import ser
import svc
import validate as v
from errors import fail
from store import by_created, common_fields, db, now, touch

bp = Blueprint('sell', __name__)

BOOKING_STATUS = ('HELD', 'TICKETED', 'CHANGE_PENDING', 'CANCELLED', 'FLOWN')
DISCLOSURE_STATE = ('NOT_ISSUED', 'PENDING_ACK', 'ACKNOWLEDGED', 'STALE')
ASSIGNMENT_STATE = ('HELD', 'CONFIRMED', 'RELEASED')


def scope(booking, uid, role):
    """PRD 2.1: a ChannelPartner may only act on its own channel's bookings."""
    if role == 'ChannelPartner' and booking['distribution_channel_id'] != uid:
        fail('ERR_CHANNEL_SCOPE_VIOLATION')


@bp.post('/bookings')
def create_booking():
    uid, role = v.ctx(('ChannelPartner',))
    data = v.fields(v.body(), [
        ('record_locator', True, lambda x: v.v_str(x, v.RE_LOCATOR)),
        ('flight_id', True, v.v_id),
        ('fare_family_id', True, v.v_id),
        ('distribution_channel_id', True, v.v_id),
        ('passenger_name', True, lambda x: v.v_str(x)),
    ])
    flight = svc.flight_or_404(data['flight_id'])
    family = svc.family_or_404(data['fare_family_id'])
    channel = svc.channel_or_404(data['distribution_channel_id'])
    if channel['id'] != uid:
        fail('ERR_CHANNEL_SCOPE_VIOLATION')
    if flight['sales_phase'] == 'DEPARTED':
        fail('ERR_FLIGHT_ALREADY_DEPARTED')
    if any(b['record_locator'] == data['record_locator']
           for b in db.bookings.values()):
        fail('ERR_DUPLICATE_RECORD_LOCATOR')
    record = common_fields()
    record.update({
        'record_locator': data['record_locator'], 'flight_id': flight['id'],
        'fare_family_id': family['id'], 'distribution_channel_id': channel['id'],
        'passenger_name': data['passenger_name'],
        'booking_status': 'HELD', 'disclosure_state': 'NOT_ISSUED',
        'disclosed_fee_fingerprint': None, 'disclosed_total_fee_cents': None,
        'disclosed_unbundled_list_cents': None, 'disclosure_issued_at': None,
        'disclosure_acked_at': None, 'fare_component_cents': None,
        'ancillary_gross_cents': 0, 'recognized_ancillary_net_cents': 0,
        'commission_cents': 0, 'incentive_credit_cents': 0,
        'channel_settlement_total_cents': 0, 'change_fee_waived_cents': 0,
        'waiver_applied': False, 'pending_change_fee_cents': None,
        'change_count': 0,
    })
    db.bookings[record['id']] = record
    return env.created(ser.booking(record))


@bp.get('/bookings/<id>')
def read_booking(id):
    uid, role = v.ctx(v.ALL_ROLES)
    booking = svc.booking_or_404(id)
    scope(booking, uid, role)
    return env.obj(ser.booking(booking))


@bp.get('/bookings')
def list_bookings():
    uid, role = v.ctx(v.ALL_ROLES)
    limit, offset = v.pagination()
    flight_id = v.q_str('flight_id')
    family_id = v.q_str('fare_family_id')
    channel_id = v.q_str('distribution_channel_id')
    status = v.q_enum('booking_status', BOOKING_STATUS)
    disclosure = v.q_enum('disclosure_state', DISCLOSURE_STATE)
    rows = [b for b in db.bookings.values()
            if (flight_id is None or b['flight_id'] == flight_id)
            and (family_id is None or b['fare_family_id'] == family_id)
            and (channel_id is None or b['distribution_channel_id'] == channel_id)
            and (status is None or b['booking_status'] == status)
            and (disclosure is None or b['disclosure_state'] == disclosure)]
    if role == 'ChannelPartner':
        # list reads filter silently instead of raising (PRD 2.1)
        rows = [b for b in rows if b['distribution_channel_id'] == uid]
    return env.page(by_created(rows), ser.booking, limit, offset)


def chargeable_attributes(family_id):
    return [a for a in svc.attributes_of(family_id)
            if a['attribute_state'] == 'ACTIVE' and a['inclusion'] == 'CHARGEABLE']


@bp.post('/bookings/<id>/disclosure')
def issue_disclosure(id):
    uid, role = v.ctx(('ChannelPartner',))
    v.fields(v.body(), [])
    booking = svc.booking_or_404(id)
    scope(booking, uid, role)
    if booking['booking_status'] != 'HELD':
        fail('ERR_BOOKING_STATE_INVALID')
    family = db.families[booking['fare_family_id']]
    channel = db.channels[booking['distribution_channel_id']]
    chargeable = chargeable_attributes(family['id'])
    if booking['disclosure_state'] == 'NOT_ISSUED':
        # PRD 2.7 orders the undisclosed-fee check (28) ahead of the
        # unsupported-category check (31).
        for attr in chargeable:
            if not db.products[attr['ancillary_product_id']]['disclosable_fee']:
                fail('ERR_UNDISCLOSED_FEE_CATEGORY')
        for attr in chargeable:
            product = db.products[attr['ancillary_product_id']]
            if product['category'] not in channel['supported_categories']:
                fail('ERR_CHANNEL_CATEGORY_UNSUPPORTED')
    booking['disclosed_fee_fingerprint'] = family['fee_fingerprint']
    booking['disclosed_unbundled_list_cents'] = calc.bundle_valuation(
        family, 'list_basis')[0]
    booking['disclosed_total_fee_cents'] = (
        sum(a['effective_unit_cents'] for a in chargeable)
        + family['change_fee_cents'])
    booking['disclosure_issued_at'] = now()
    booking['disclosure_acked_at'] = None
    booking['disclosure_state'] = 'PENDING_ACK'
    touch(booking)
    return env.obj(ser.booking(booking))


@bp.post('/bookings/<id>/disclosure-ack')
def ack_disclosure(id):
    uid, role = v.ctx(('ChannelPartner',))
    data = v.fields(v.body(), [
        ('acknowledged_fee_fingerprint', True, lambda x: v.v_str(x)),
    ])
    booking = svc.booking_or_404(id)
    scope(booking, uid, role)
    if booking['booking_status'] != 'HELD':
        fail('ERR_BOOKING_STATE_INVALID')
    if booking['disclosure_state'] != 'PENDING_ACK':
        fail('ERR_DISCLOSURE_STATE_INVALID')
    # compared against the snapshot, never against the family's live value
    if data['acknowledged_fee_fingerprint'] != booking['disclosed_fee_fingerprint']:
        fail('ERR_DISCLOSURE_FINGERPRINT_MISMATCH')
    booking['disclosure_state'] = 'ACKNOWLEDGED'
    booking['disclosure_acked_at'] = now()
    touch(booking)
    return env.obj(ser.booking(booking))


@bp.post('/bookings/<id>/ticket')
def ticket(id):
    uid, role = v.ctx(('ChannelPartner',))
    v.fields(v.body(), [])
    booking = svc.booking_or_404(id)
    scope(booking, uid, role)
    if booking['booking_status'] != 'HELD':
        fail('ERR_BOOKING_STATE_INVALID')
    flight = db.flights[booking['flight_id']]
    family = db.families[booking['fare_family_id']]
    channel = db.channels[booking['distribution_channel_id']]
    if flight['sales_phase'] not in ('PRESALE', 'CHECKIN_OPEN'):
        fail('ERR_FLIGHT_SALES_PHASE_CLOSED')
    if family['status'] != 'PUBLISHED':
        fail('ERR_FAMILY_NOT_PUBLISHED')
    if flight['irops_state'] == 'IRREGULAR':
        fail('ERR_IROPS_SALES_BLOCKED')
    if booking['disclosure_state'] in ('NOT_ISSUED', 'PENDING_ACK'):
        fail('ERR_FEE_DISCLOSURE_NOT_ACKNOWLEDGED')
    if (booking['disclosure_state'] == 'STALE'
            or booking['disclosed_fee_fingerprint'] != family['fee_fingerprint']):
        fail('ERR_FEE_DISCLOSURE_STALE')
    published = [p for p in svc.publications_of_family(family['id'])
                 if p['distribution_channel_id'] == channel['id']
                 and p['parity_state'] == 'IN_PARITY']
    if not published:
        fail('ERR_FAMILY_NOT_PUBLISHED_TO_CHANNEL')
    if channel['content_parity_status'] != 'COMPLIANT':
        fail('ERR_CHANNEL_CONTENT_PARITY_BREACH')
    svc.ticket_booking(booking, family, flight)
    return env.obj(ser.booking(booking))


@bp.post('/bookings/<id>/change-open')
def change_open(id):
    uid, role = v.ctx(('ChannelPartner',))
    v.fields(v.body(), [])
    booking = svc.booking_or_404(id)
    scope(booking, uid, role)
    if booking['booking_status'] != 'TICKETED':
        fail('ERR_BOOKING_STATE_INVALID')
    flight = db.flights[booking['flight_id']]
    if flight['sales_phase'] == 'DEPARTED':
        fail('ERR_FLIGHT_ALREADY_DEPARTED')
    family = db.families[booking['fare_family_id']]
    quote = family['change_fee_cents'] - booking['change_fee_waived_cents']
    booking['pending_change_fee_cents'] = quote if quote > 0 else 0
    booking['booking_status'] = 'CHANGE_PENDING'
    touch(booking)
    return env.obj(ser.booking(booking))


@bp.post('/bookings/<id>/change-settle')
def change_settle(id):
    uid, role = v.ctx(('ChannelPartner',))
    data = v.fields(v.body(), [
        ('resolution', True, lambda x: v.v_enum(x, ('CONFIRM', 'ABANDON'))),
    ])
    booking = svc.booking_or_404(id)
    scope(booking, uid, role)
    if booking['booking_status'] != 'CHANGE_PENDING':
        fail('ERR_BOOKING_STATE_INVALID')
    quoted = booking['pending_change_fee_cents'] or 0
    booking['booking_status'] = 'TICKETED'
    if data['resolution'] == 'CONFIRM':
        if quoted > 0:
            svc.post_entry(booking, 'CHANGE', 'SALE', quoted, 'TAXABLE_SERVICE',
                           'NON_AIR', '4300', 'CHANGE_SETTLEMENT',
                           'change:' + booking['id'])
        booking['change_count'] = booking['change_count'] + 1
        booking['pending_change_fee_cents'] = None
        svc.recompute_booking_money(booking)
    else:
        booking['pending_change_fee_cents'] = None
    touch(booking)
    return env.obj(ser.booking(booking))


@bp.post('/bookings/<id>/cancel')
def cancel(id):
    uid, role = v.ctx(('ChannelPartner',))
    v.fields(v.body(), [('cancel_reason', True, lambda x: v.v_str(x))])
    booking = svc.booking_or_404(id)
    scope(booking, uid, role)
    if booking['booking_status'] not in ('HELD', 'TICKETED', 'CHANGE_PENDING'):
        fail('ERR_BOOKING_STATE_INVALID')
    family = db.families[booking['fare_family_id']]
    flight = db.flights[booking['flight_id']]
    svc.cancel_booking(booking, family, flight)
    return env.obj(ser.booking(booking))


# --------------------------------------------------------------------------
# seat assignments
# --------------------------------------------------------------------------
@bp.post('/bookings/<id>/seat-assignments')
def assign_seat(id):
    uid, role = v.ctx(('ChannelPartner',))
    data = v.fields(v.body(), [
        ('seat_inventory_segment_id', True, v.v_id),
        ('row', True, v.v_int),
        ('seat_letter', True, lambda x: v.v_enum(x, v.SEAT_LETTERS)),
    ])
    booking = svc.booking_or_404(id)
    segment = svc.segment_or_404(data['seat_inventory_segment_id'])
    scope(booking, uid, role)
    if booking['booking_status'] not in ('HELD', 'TICKETED', 'CHANGE_PENDING'):
        fail('ERR_BOOKING_STATE_INVALID')
    if segment['segment_state'] != 'OPEN':
        fail('ERR_SEGMENT_CLOSED')
    if (data['row'] < segment['row_start'] or data['row'] > segment['row_end']
            or data['seat_letter'] not in segment['seat_letters']):
        fail('ERR_SEAT_ROW_OUT_OF_SEGMENT')
    # the aggregate capacity check deliberately precedes point occupancy
    if segment['available_seats'] < 1:
        fail('ERR_SEAT_INVENTORY_EXHAUSTED')
    for other in svc.assignments_of_segment(segment['id']):
        if (other['assignment_state'] in ('HELD', 'CONFIRMED')
                and other['row'] == data['row']
                and other['seat_letter'] == data['seat_letter']):
            fail('ERR_SEAT_ALREADY_OCCUPIED')
    prepaid = any(o['offer_status'] == 'ACCEPTED'
                  and o['ancillary_product_id'] == segment['ancillary_product_id']
                  for o in svc.offers_of_booking(booking['id']))
    record = common_fields()
    record.update({
        'booking_id': booking['id'],
        'seat_inventory_segment_id': segment['id'],
        'row': data['row'], 'seat_letter': data['seat_letter'],
        'price_charged_cents': 0 if prepaid else segment['effective_price_cents'],
        'assignment_state': 'HELD', 'released_reason': None,
    })
    db.assignments[record['id']] = record
    if booking['booking_status'] == 'HELD':
        segment['held_seats'] = segment['held_seats'] + 1
    else:
        # auto-confirm: the row is never counted as held on this path
        record['assignment_state'] = 'CONFIRMED'
        segment['sold_seats'] = segment['sold_seats'] + 1
    svc.recompute_segment_inventory(segment)
    touch(segment)
    if record['assignment_state'] == 'CONFIRMED':
        svc.post_seat_sale(record, segment, booking)
        svc.recompute_booking_money(booking)
        touch(booking)
    return env.created(ser.assignment(record))


@bp.get('/seat-assignments/<id>')
def read_assignment(id):
    uid, role = v.ctx(v.ALL_ROLES)
    assignment = svc.assignment_or_404(id)
    scope(db.bookings[assignment['booking_id']], uid, role)
    return env.obj(ser.assignment(assignment))


@bp.get('/seat-assignments')
def list_assignments():
    uid, role = v.ctx(v.ALL_ROLES)
    limit, offset = v.pagination()
    booking_id = v.q_str('booking_id')
    segment_id = v.q_str('seat_inventory_segment_id')
    state = v.q_enum('assignment_state', ASSIGNMENT_STATE)
    rows = [a for a in db.assignments.values()
            if (booking_id is None or a['booking_id'] == booking_id)
            and (segment_id is None or a['seat_inventory_segment_id'] == segment_id)
            and (state is None or a['assignment_state'] == state)]
    if role == 'ChannelPartner':
        rows = [a for a in rows
                if db.bookings[a['booking_id']]['distribution_channel_id'] == uid]
    return env.page(by_created(rows), ser.assignment, limit, offset)


@bp.post('/seat-assignments/<id>/release')
def release_seat(id):
    uid, role = v.ctx(('ChannelPartner',))
    v.fields(v.body(), [('release_reason', True, lambda x: v.v_str(x))])
    assignment = svc.assignment_or_404(id)
    booking = db.bookings[assignment['booking_id']]
    scope(booking, uid, role)
    if assignment['assignment_state'] not in ('HELD', 'CONFIRMED'):
        fail('ERR_SEAT_ASSIGNMENT_STATE_INVALID')
    if assignment['assignment_state'] == 'CONFIRMED':
        flight = db.flights[booking['flight_id']]
        if flight['sales_phase'] == 'DEPARTED':
            fail('ERR_FLIGHT_ALREADY_DEPARTED')
    if svc.release_assignment(assignment, 'PASSENGER_RELEASE'):
        svc.recompute_booking_money(booking)
        touch(booking)
    return env.obj(ser.assignment(assignment))
