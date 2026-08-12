from flask import Blueprint

import calc
import db
from errors import ApiError, invalid
from middleware import auth
from response import ok
from util import body, require, optional, as_str, as_int, as_num, as_enum, find, serialize, parse_dt

bp = Blueprint('events', __name__)

DT_FIELDS = ('start_at', 'end_at')
ROOMS = ('MAIN_SHOWROOM', 'RECITAL_HALL')


def ser(event):
    return serialize(event, DT_FIELDS)


def _not_settlable(message='event is not in the required state'):
    return ApiError('ERR_EVENT_NOT_SETTLABLE', 409, message)


@bp.post('/piano-dealer/showroom-events')
def create_event():
    auth('StoreManager')
    d = body()
    room = as_enum(require(d, 'room'), 'room', ROOMS)
    title = as_str(require(d, 'title'), 'title')
    start = parse_dt(require(d, 'start_at'), 'start_at')
    end = parse_dt(require(d, 'end_at'), 'end_at')
    if end <= start:
        raise invalid('end_at must be strictly after start_at')
    capacity = as_int(require(d, 'capacity'), 'capacity')
    guarantee = as_int(require(d, 'artist_guarantee_cents'), 'artist_guarantee_cents')
    split_pct = as_num(require(d, 'split_pct'), 'split_pct')
    # Half-open room overlap vs non-CANCELLED events; back-to-back is allowed.
    for ev in db.stores['events'].values():
        if ev['room'] != room or ev['status'] == 'CANCELLED':
            continue
        if start < ev['end_at'] and ev['start_at'] < end:
            raise ApiError('ERR_ROOM_WINDOW_CONFLICT', 409,
                           'event window conflicts with another event in this room')
    rec = db.base_fields()
    rec.update({
        'room': room,
        'title': title,
        'start_at': start,
        'end_at': end,
        'capacity': capacity,
        'artist_guarantee_cents': guarantee,
        'split_pct': split_pct,
        'rsvp_count': 0,
        'gross_cents': None,
        'payout_cents': None,
        'status': 'PLANNED',
    })
    db.stores['events'][rec['id']] = rec
    return ok(ser(rec), 201)


@bp.get('/piano-dealer/showroom-events/<rid>')
def get_event(rid):
    auth('StoreManager', 'SalesAssociate')
    return ok(ser(find(db.stores['events'], rid, 'event')))


@bp.post('/piano-dealer/showroom-events/<rid>/open-rsvp')
def open_rsvp(rid):
    auth('StoreManager')
    ev = find(db.stores['events'], rid, 'event')
    if ev['status'] != 'PLANNED':
        raise _not_settlable('only PLANNED events can open RSVPs')
    ev['status'] = 'RSVP_OPEN'
    db.touch(ev)
    return ok(ser(ev))


@bp.post('/piano-dealer/showroom-events/<rid>/rsvps')
def add_rsvp(rid):
    auth('SalesAssociate')
    ev = find(db.stores['events'], rid, 'event')
    d = body()
    party_size = as_int(optional(d, 'party_size', 1), 'party_size')
    if party_size < 1:
        raise invalid('party_size must be at least 1')
    if ev['status'] != 'RSVP_OPEN':
        raise _not_settlable('RSVPs require an RSVP_OPEN event')
    if ev['rsvp_count'] + party_size > ev['capacity']:
        raise ApiError('ERR_EVENT_CAPACITY_EXCEEDED', 409,
                       'rsvp_count + party_size would exceed capacity')
    ev['rsvp_count'] += party_size
    db.touch(ev)
    return ok(ser(ev), 201)


@bp.post('/piano-dealer/showroom-events/<rid>/settle')
def settle_event(rid):
    auth('StoreManager')
    ev = find(db.stores['events'], rid, 'event')
    d = body()
    gross = as_int(require(d, 'gross_cents'), 'gross_cents')
    if ev['status'] != 'RSVP_OPEN':
        raise _not_settlable('only RSVP_OPEN events can be settled')
    if db.now() < ev['end_at']:
        raise _not_settlable('event cannot be settled before its end')
    ev['gross_cents'] = gross
    ev['payout_cents'] = calc.artist_payout(ev['artist_guarantee_cents'], ev['split_pct'], gross)
    ev['status'] = 'SETTLED'
    db.touch(ev)
    return ok(ser(ev))


@bp.post('/piano-dealer/showroom-events/<rid>/cancel')
def cancel_event(rid):
    auth('StoreManager')
    ev = find(db.stores['events'], rid, 'event')
    if ev['status'] not in ('PLANNED', 'RSVP_OPEN'):
        raise _not_settlable('only PLANNED or RSVP_OPEN events can be cancelled')
    ev['status'] = 'CANCELLED'
    db.touch(ev)
    return ok(ser(ev))
