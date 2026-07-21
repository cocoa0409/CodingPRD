"""Tournament Bracket Management API — Flask entry point.

In-memory only. Fresh process => empty store. No seeding at startup.
"""
import os
from flask import Flask, request, jsonify

import core
from core import (
    ApiError, ALL_ROLES, create, touch, touch_nv, serialize, make_request_id,
    wall_now_iso, parse_dt, fmt_dt,
    venues, stations, channels, players, tournaments, registrations,
    matches, stream_assignments, payouts, disputes,
)

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {'api_request_id': make_request_id(), 'api_request_timestamp': wall_now_iso()}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, pagination=None):
    rt = 'array' if isinstance(data, list) else 'object'
    body = {'meta': _meta(pagination), 'response_type': rt, 'data': data}
    return jsonify(body), status


def err(error_id, message, status):
    body = {
        'meta': _meta(),
        'response_type': 'error',
        'data': {'error_id': error_id, 'message': message},
    }
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(e):
    return err(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return err('ERR_NOT_FOUND', 'resource not found', 404)


@app.errorhandler(405)
def handle_405(e):
    return err('ERR_NOT_FOUND', 'method not allowed', 404)


@app.errorhandler(Exception)
def handle_uncaught(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return err('ERR_INVALID_REQUEST', 'internal error: %s' % e, 500)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def require_role(allowed, optional=False):
    role = request.headers.get('X-User-Role')
    uid = request.headers.get('X-User-ID')
    present = bool(role) and bool(uid)
    if not present or role not in ALL_ROLES:
        if optional:
            return (role if role in ALL_ROLES else None), uid
        raise ApiError('ERR_UNAUTHENTICATED', 'missing or invalid auth headers')
    if role == 'Director':
        return role, uid
    if role in allowed:
        return role, uid
    raise ApiError('ERR_UNAUTHORIZED', 'role not permitted for this operation')


# ---------------------------------------------------------------------------
# Body / field helpers
# ---------------------------------------------------------------------------
def body():
    if not request.data:
        return {}
    j = request.get_json(silent=True)
    if j is None:
        return {}
    if not isinstance(j, dict):
        raise ApiError('ERR_INVALID_REQUEST', 'body must be a JSON object')
    return j


def require(b, name):
    if name not in b or b[name] is None:
        raise ApiError('ERR_INVALID_REQUEST', 'missing required field: %s' % name)
    return b[name]


def req_str(b, name):
    v = require(b, name)
    if not isinstance(v, str) or v == '':
        raise ApiError('ERR_INVALID_REQUEST', 'field %s must be a non-empty string' % name)
    return v


def req_int(b, name):
    v = require(b, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError('ERR_INVALID_REQUEST', 'field %s must be an integer' % name)
    return v


def opt_int(b, name, default=None):
    if name not in b or b[name] is None:
        return default
    v = b[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError('ERR_INVALID_REQUEST', 'field %s must be an integer' % name)
    return v


def opt_enum(b, name, choices, default):
    if name not in b or b[name] is None:
        return default
    v = b[name]
    if v not in choices:
        raise ApiError('ERR_INVALID_REQUEST', 'field %s invalid value' % name)
    return v


def req_enum(b, name, choices):
    v = require(b, name)
    if v not in choices:
        raise ApiError('ERR_INVALID_REQUEST', 'field %s invalid value' % name)
    return v


def lookup(coll, id_, label):
    e = coll.get(id_)
    if e is None:
        raise ApiError('ERR_NOT_FOUND', '%s not found' % label)
    return e


def paginate():
    args = request.args
    try:
        limit = int(args.get('limit', 10))
    except (ValueError, TypeError):
        raise ApiError('ERR_INVALID_REQUEST', 'invalid limit')
    try:
        offset = int(args.get('offset', 0))
    except (ValueError, TypeError):
        raise ApiError('ERR_INVALID_REQUEST', 'invalid offset')
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def list_response(items):
    items = sorted(items, key=lambda e: e['_seq'])
    limit, offset = paginate()
    total = len(items)
    page = items[offset:offset + limit]
    pag = {
        'limit': limit,
        'offset': offset,
        'total_count': total,
        'has_more': offset + limit < total,
    }
    return ok([serialize(e) for e in page], 200, pagination=pag)


# ===========================================================================
# Venues & Stations
# ===========================================================================
@app.route('/venues', methods=['POST'])
def create_venue():
    require_role({'Director'})
    b = body()
    name = req_str(b, 'name')
    address = req_str(b, 'address')
    open_minute = req_int(b, 'open_minute')
    close_minute = req_int(b, 'close_minute')
    if not (0 <= open_minute < close_minute <= 1440):
        raise ApiError('ERR_INVALID_REQUEST', 'invalid venue hours')
    v = create('Venue', {
        'name': name, 'address': address,
        'open_minute': open_minute, 'close_minute': close_minute,
    })
    return ok(serialize(v), 201)


@app.route('/venues/<id>', methods=['GET'])
def get_venue(id):
    require_role(ALL_ROLES, optional=True)
    return ok(serialize(lookup(venues, id, 'venue')))


@app.route('/venues/<id>/stations', methods=['POST'])
def create_station(id):
    require_role({'Director'})
    v = lookup(venues, id, 'venue')
    b = body()
    label = req_str(b, 'label')
    s = create('Station', {'venue_id': v['id'], 'label': label})
    return ok(serialize(s), 201)


@app.route('/venues/<id>/stations', methods=['GET'])
def list_venue_stations(id):
    require_role(ALL_ROLES, optional=True)
    v = lookup(venues, id, 'venue')
    items = [s for s in stations.values() if s['venue_id'] == v['id']]
    return list_response(items)


@app.route('/stations/<id>', methods=['GET'])
def get_station(id):
    require_role(ALL_ROLES, optional=True)
    return ok(serialize(lookup(stations, id, 'station')))


# ===========================================================================
# Stream channels
# ===========================================================================
@app.route('/stream-channels', methods=['POST'])
def create_channel():
    require_role({'Director'})
    b = body()
    name = req_str(b, 'name')
    platform = req_enum(b, 'platform', {'TWITCH', 'YOUTUBE', 'FACEBOOK'})
    c = create('StreamChannel', {'name': name, 'platform': platform})
    return ok(serialize(c), 201)


@app.route('/stream-channels/<id>', methods=['GET'])
def get_channel(id):
    require_role(ALL_ROLES, optional=True)
    return ok(serialize(lookup(channels, id, 'stream channel')))


# ===========================================================================
# Players
# ===========================================================================
@app.route('/players', methods=['POST'])
def create_player():
    require_role({'Public', 'Director'}, optional=True)
    b = body()
    display_name = req_str(b, 'display_name')
    email = req_str(b, 'email')
    for p in players.values():
        if p['email'] == email:
            raise ApiError('ERR_INVALID_REQUEST', 'email already in use')
    rating = opt_int(b, 'rating', 1000)
    tax = b.get('tax_id_provided', False)
    if not isinstance(tax, bool):
        raise ApiError('ERR_INVALID_REQUEST', 'tax_id_provided must be boolean')
    p = create('Player', {
        'display_name': display_name, 'email': email,
        'rating': rating, 'tax_id_provided': tax,
    })
    return ok(serialize(p), 201)


@app.route('/players/<id>', methods=['GET'])
def get_player(id):
    require_role(ALL_ROLES, optional=True)
    return ok(serialize(lookup(players, id, 'player')))


# ===========================================================================
# Tournaments
# ===========================================================================
@app.route('/tournaments', methods=['POST'])
def create_tournament():
    require_role({'Director'})
    b = body()
    name = req_str(b, 'name')
    venue_id = req_str(b, 'venue_id')
    fmt = req_enum(b, 'format', {'SINGLE_ELIM', 'DOUBLE_ELIM', 'ROUND_ROBIN', 'SWISS'})
    max_participants = req_int(b, 'max_participants')
    if max_participants < 2:
        raise ApiError('ERR_INVALID_REQUEST', 'max_participants must be >= 2')
    prize_pool_cents = req_int(b, 'prize_pool_cents')
    if prize_pool_cents < 0:
        raise ApiError('ERR_INVALID_REQUEST', 'prize_pool_cents must be >= 0')
    check_in_deadline = req_str(b, 'check_in_deadline')
    parse_dt(check_in_deadline)  # validate format
    seeding_method = opt_enum(b, 'seeding_method', {'RATING', 'RANDOM_STABLE', 'MANUAL'}, 'RATING')
    tiebreak_method = opt_enum(b, 'tiebreak_method', {'SEED', 'GAME_DIFF'}, 'SEED')
    swiss_rounds = opt_int(b, 'swiss_rounds', 0)
    paid_places = opt_int(b, 'paid_places', 2)
    if not (1 <= paid_places <= 4):
        raise ApiError('ERR_INVALID_REQUEST', 'paid_places must be between 1 and 4')
    lookup(venues, venue_id, 'venue')
    reg_open = b.get('registration_open_at')
    reg_close = b.get('registration_close_at')
    if reg_open is not None:
        parse_dt(reg_open)
    if reg_close is not None:
        parse_dt(reg_close)
    t = create('Tournament', {
        'name': name, 'venue_id': venue_id, 'format': fmt, 'status': 'DRAFT',
        'max_participants': max_participants, 'seeding_method': seeding_method,
        'tiebreak_method': tiebreak_method, 'swiss_rounds': swiss_rounds,
        'num_swiss_rounds_played': 0, 'prize_pool_cents': prize_pool_cents,
        'paid_places': paid_places, 'payout_variant': 'NONE',
        'unallocated_prize_cents': prize_pool_cents,
        'registration_open_at': reg_open, 'registration_close_at': reg_close,
        'check_in_deadline': check_in_deadline,
        'registered_count': 0, 'checked_in_count': 0,
        'alive_count': 0, 'eliminated_count': 0,
    })
    return ok(serialize(t), 201)


@app.route('/tournaments', methods=['GET'])
def list_tournaments():
    require_role(ALL_ROLES, optional=True)
    items = list(tournaments.values())
    venue_id = request.args.get('venue_id')
    status = request.args.get('status')
    if venue_id is not None:
        items = [t for t in items if t['venue_id'] == venue_id]
    if status is not None:
        items = [t for t in items if t['status'] == status]
    return list_response(items)


@app.route('/tournaments/<id>', methods=['GET'])
def get_tournament(id):
    require_role(ALL_ROLES, optional=True)
    return ok(serialize(lookup(tournaments, id, 'tournament')))


@app.route('/tournaments/<id>/open-registration', methods=['POST'])
def open_registration(id):
    require_role({'Director'})
    t = lookup(tournaments, id, 'tournament')
    if t['status'] != 'DRAFT':
        raise ApiError('ERR_INVALID_STATE', 'tournament not in DRAFT')
    lookup(venues, t['venue_id'], 'venue')
    b = body()
    if b.get('registration_open_at') is not None:
        parse_dt(b['registration_open_at'])
        t['registration_open_at'] = b['registration_open_at']
    t['status'] = 'REGISTRATION_OPEN'
    touch(t)
    return ok(serialize(t))


@app.route('/tournaments/<id>/close-registration', methods=['POST'])
def close_registration(id):
    require_role({'Director'})
    t = lookup(tournaments, id, 'tournament')
    if t['status'] != 'REGISTRATION_OPEN':
        raise ApiError('ERR_INVALID_STATE', 'tournament not in REGISTRATION_OPEN')
    t['status'] = 'REGISTRATION_CLOSED'
    touch(t)
    return ok(serialize(t))


@app.route('/tournaments/<id>/generate-bracket', methods=['POST'])
def generate_bracket(id):
    require_role({'Director'})
    t = lookup(tournaments, id, 'tournament')
    if t['status'] != 'REGISTRATION_CLOSED':
        raise ApiError('ERR_INVALID_STATE', 'tournament not in REGISTRATION_CLOSED')
    checked_in = t.get('checked_in_count', 0)
    if checked_in < 2:
        raise ApiError('ERR_INSUFFICIENT_PARTICIPANTS', 'need >= 2 checked-in participants')
    if t['format'] == 'SWISS' and (t.get('swiss_rounds') or 0) < 1:
        raise ApiError('ERR_INSUFFICIENT_PARTICIPANTS', 'SWISS requires swiss_rounds >= 1')
    seeded = core.assign_seeds(t)
    core.generate_bracket_matches(t, seeded)
    t['alive_count'] = checked_in
    t['eliminated_count'] = 0
    core.run_provisional_payout(t)
    t['status'] = 'BRACKET_READY'
    touch(t)
    return ok(serialize(t))


@app.route('/tournaments/<id>/start', methods=['POST'])
def start_tournament(id):
    require_role({'Director'})
    t = lookup(tournaments, id, 'tournament')
    if t['status'] != 'BRACKET_READY':
        raise ApiError('ERR_INVALID_STATE', 'tournament not in BRACKET_READY')
    t['status'] = 'IN_PROGRESS'
    touch(t)
    return ok(serialize(t))


@app.route('/tournaments/<id>/complete', methods=['POST'])
def complete_tournament(id):
    require_role({'Director'})
    t = lookup(tournaments, id, 'tournament')
    if t['status'] != 'IN_PROGRESS':
        raise ApiError('ERR_INVALID_STATE', 'tournament not in IN_PROGRESS')
    for m in core.tournament_matches(t):
        if m['status'] not in ('CONFIRMED', 'VOIDED'):
            raise ApiError('ERR_MATCHES_INCOMPLETE', 'some match is not terminal')
    b = body()
    expected = require(b, 'expected_tournament_version')
    if expected != t['version']:
        raise ApiError('ERR_STALE_TOURNAMENT_VERSION', 'stale tournament version')
    core.assign_final_placements(t)
    core.run_final_payout(t)
    t['status'] = 'COMPLETED'
    touch(t)
    return ok(serialize(t))


@app.route('/tournaments/<id>/cancel', methods=['POST'])
def cancel_tournament(id):
    require_role({'Director'})
    t = lookup(tournaments, id, 'tournament')
    if t['status'] not in ('DRAFT', 'REGISTRATION_OPEN', 'REGISTRATION_CLOSED'):
        raise ApiError('ERR_INVALID_STATE', 'tournament cannot be cancelled from this state')
    core.void_provisional_payouts(t)
    t['unallocated_prize_cents'] = t['prize_pool_cents']
    if t['status'] in ('REGISTRATION_OPEN', 'REGISTRATION_CLOSED'):
        for r in registrations.values():
            if r['tournament_id'] == t['id'] and r['status'] in ('REGISTERED', 'CHECKED_IN'):
                was_checked = r['status'] == 'CHECKED_IN'
                r['status'] = 'WITHDRAWN'
                touch(r)
                t['registered_count'] = t.get('registered_count', 0) - 1
                if was_checked:
                    t['checked_in_count'] = t.get('checked_in_count', 0) - 1
    t['status'] = 'CANCELLED'
    touch(t)
    return ok(serialize(t))


@app.route('/tournaments/<id>/standings', methods=['GET'])
def get_standings(id):
    require_role(ALL_ROLES, optional=True)
    t = lookup(tournaments, id, 'tournament')
    return ok({'rows': core.standings_rows(t)})


@app.route('/tournaments/<id>/matches', methods=['GET'])
def list_tournament_matches(id):
    require_role(ALL_ROLES, optional=True)
    t = lookup(tournaments, id, 'tournament')
    items = [m for m in matches.values() if m['tournament_id'] == t['id']]
    rn = request.args.get('round_number')
    bracket = request.args.get('bracket')
    status = request.args.get('status')
    if rn is not None:
        try:
            rn_i = int(rn)
        except ValueError:
            raise ApiError('ERR_INVALID_REQUEST', 'invalid round_number')
        items = [m for m in items if m['round_number'] == rn_i]
    if bracket is not None:
        items = [m for m in items if m['bracket'] == bracket]
    if status is not None:
        items = [m for m in items if m['status'] == status]
    return list_response(items)


@app.route('/tournaments/<id>/registrations', methods=['GET'])
def list_tournament_registrations(id):
    require_role(ALL_ROLES, optional=True)
    t = lookup(tournaments, id, 'tournament')
    items = [r for r in registrations.values() if r['tournament_id'] == t['id']]
    status = request.args.get('status')
    if status is not None:
        items = [r for r in items if r['status'] == status]
    return list_response(items)


# ===========================================================================
# Registrations
# ===========================================================================
@app.route('/registrations', methods=['POST'])
def create_registration():
    require_role({'Player', 'Director'}, optional=True)
    b = body()
    tournament_id = req_str(b, 'tournament_id')
    player_id = req_str(b, 'player_id')
    t = lookup(tournaments, tournament_id, 'tournament')
    lookup(players, player_id, 'player')
    if t['status'] != 'REGISTRATION_OPEN':
        raise ApiError('ERR_INVALID_STATE', 'tournament not open for registration')
    active = [r for r in registrations.values()
              if r['tournament_id'] == t['id'] and r['status'] in ('REGISTERED', 'CHECKED_IN')]
    if len(active) >= t['max_participants']:
        raise ApiError('ERR_TOURNAMENT_FULL', 'tournament is full')
    for r in active:
        if r['player_id'] == player_id:
            raise ApiError('ERR_DUPLICATE_REGISTRATION', 'player already registered')
    seed_input = opt_int(b, 'seed_input', None)
    r = create('Registration', {
        'tournament_id': tournament_id, 'player_id': player_id,
        'status': 'REGISTERED', 'seed': None, 'seed_input': seed_input,
        'checked_in_at': None, 'eliminated': False, 'final_placement': None,
    })
    t['registered_count'] = t.get('registered_count', 0) + 1
    touch_nv(t)
    return ok(serialize(r), 201)


@app.route('/registrations/<id>', methods=['GET'])
def get_registration(id):
    require_role(ALL_ROLES, optional=True)
    return ok(serialize(lookup(registrations, id, 'registration')))


@app.route('/registrations', methods=['GET'])
def list_registrations():
    require_role(ALL_ROLES, optional=True)
    items = list(registrations.values())
    tid = request.args.get('tournament_id')
    pid = request.args.get('player_id')
    status = request.args.get('status')
    if tid is not None:
        items = [r for r in items if r['tournament_id'] == tid]
    if pid is not None:
        items = [r for r in items if r['player_id'] == pid]
    if status is not None:
        items = [r for r in items if r['status'] == status]
    return list_response(items)


@app.route('/registrations/<id>/check-in', methods=['POST'])
def check_in(id):
    require_role({'Player', 'Director'})
    r = lookup(registrations, id, 'registration')
    t = lookup(tournaments, r['tournament_id'], 'tournament')
    if t['status'] != 'REGISTRATION_CLOSED':
        raise ApiError('ERR_TOURNAMENT_NOT_IN_CHECKIN', 'tournament not in check-in window')
    deadline = parse_dt(t['check_in_deadline'])
    if core.get_clock() > deadline:
        raise ApiError('ERR_CHECKIN_CLOSED', 'check-in deadline has passed')
    if r['status'] != 'REGISTERED':
        raise ApiError('ERR_INVALID_STATE', 'registration not in REGISTERED')
    r['status'] = 'CHECKED_IN'
    r['checked_in_at'] = fmt_dt(core.get_clock())
    touch(r)
    t['checked_in_count'] = t.get('checked_in_count', 0) + 1
    touch_nv(t)
    return ok(serialize(r))


@app.route('/registrations/<id>/withdraw', methods=['POST'])
def withdraw(id):
    require_role({'Player', 'Director'})
    r = lookup(registrations, id, 'registration')
    t = lookup(tournaments, r['tournament_id'], 'tournament')
    if r['status'] not in ('REGISTERED', 'CHECKED_IN'):
        raise ApiError('ERR_INVALID_STATE', 'registration cannot be withdrawn')
    if t['status'] == 'IN_PROGRESS':
        raise ApiError('ERR_INVALID_STATE', 'tournament already in progress')
    was_checked = r['status'] == 'CHECKED_IN'
    r['status'] = 'WITHDRAWN'
    touch(r)
    t['registered_count'] = t.get('registered_count', 0) - 1
    if was_checked:
        t['checked_in_count'] = t.get('checked_in_count', 0) - 1
    touch_nv(t)
    return ok(serialize(r))


# ===========================================================================
# Matches
# ===========================================================================
@app.route('/matches/<id>', methods=['GET'])
def get_match(id):
    require_role(ALL_ROLES, optional=True)
    return ok(serialize(lookup(matches, id, 'match')))


@app.route('/matches', methods=['GET'])
def list_matches():
    require_role(ALL_ROLES, optional=True)
    items = list(matches.values())
    filt = {
        'tournament_id': 'tournament_id', 'station_id': 'station_id',
        'home_registration_id': 'home_registration_id',
        'away_registration_id': 'away_registration_id',
        'winner_registration_id': 'winner_registration_id',
        'loser_registration_id': 'loser_registration_id',
        'next_match_id': 'next_match_id',
        'loser_next_match_id': 'loser_next_match_id',
        'status': 'status',
    }
    for arg, field in filt.items():
        val = request.args.get(arg)
        if val is not None:
            items = [m for m in items if m.get(field) == val]
    return list_response(items)


@app.route('/matches/<id>/schedule', methods=['POST'])
def schedule_match(id):
    require_role({'Referee', 'Director'})
    m = lookup(matches, id, 'match')
    b = body()
    station_id = b.get('station_id')
    station = None
    if station_id is not None:
        station = lookup(stations, station_id, 'station')
    t = tournaments[m['tournament_id']]
    if m['status'] != 'PENDING' or t['status'] != 'IN_PROGRESS':
        raise ApiError('ERR_INVALID_STATE', 'match not schedulable in current state')
    if not m['home_registration_id'] or not m['away_registration_id']:
        raise ApiError('ERR_INVALID_STATE', 'both competitor slots must be populated')
    for rid in (m['home_registration_id'], m['away_registration_id']):
        reg = registrations.get(rid)
        if reg is None or reg['status'] != 'CHECKED_IN':
            raise ApiError('ERR_COMPETITOR_NOT_CHECKED_IN', 'competitor not checked in')
    if station is None:
        station_id = req_str(b, 'station_id')  # raise ERR_INVALID_REQUEST
        station = lookup(stations, station_id, 'station')
    if station['venue_id'] != t['venue_id']:
        raise ApiError('ERR_STATION_WRONG_VENUE', 'station belongs to a different venue')
    start_s = req_str(b, 'scheduled_start')
    end_s = req_str(b, 'scheduled_end')
    start = parse_dt(start_s)
    end = parse_dt(end_s)
    venue = venues[t['venue_id']]
    start_min = start.hour * 60 + start.minute
    end_min = end.hour * 60 + end.minute
    if end <= start:
        raise ApiError('ERR_OUTSIDE_VENUE_HOURS', 'end must be after start')
    if start_min < venue['open_minute'] or end_min > venue['close_minute']:
        raise ApiError('ERR_OUTSIDE_VENUE_HOURS', 'window outside venue hours')
    if core.station_conflict(station['id'], start, end, m['id']):
        raise ApiError('ERR_STATION_OVERLAP', 'station is busy during this window')
    m['station_id'] = station['id']
    m['scheduled_start'] = start_s
    m['scheduled_end'] = end_s
    m['status'] = 'SCHEDULED'
    touch(m)
    return ok(serialize(m))


@app.route('/matches/<id>/report', methods=['POST'])
def report_match(id):
    role, uid = require_role({'Player', 'Referee'})
    m = lookup(matches, id, 'match')
    if m['status'] != 'SCHEDULED':
        raise ApiError('ERR_INVALID_STATE', 'match not in SCHEDULED')
    b = body()
    home_score = req_int(b, 'home_score')
    away_score = req_int(b, 'away_score')
    if home_score == away_score:
        raise ApiError('ERR_TIE_NOT_ALLOWED', 'ties are not permitted')
    if role == 'Player':
        competitor_pids = set()
        for rid in (m['home_registration_id'], m['away_registration_id']):
            reg = registrations.get(rid)
            if reg is not None:
                competitor_pids.add(reg['player_id'])
        if uid not in competitor_pids:
            raise ApiError('ERR_NOT_A_COMPETITOR', 'reporter is not a competitor')
    m['home_score'] = home_score
    m['away_score'] = away_score
    m['reported_by_user_id'] = uid
    m['status'] = 'REPORTED'
    touch(m)
    return ok(serialize(m))


@app.route('/matches/<id>/confirm', methods=['POST'])
def confirm_match(id):
    role, uid = require_role({'Referee', 'Director'})
    m = lookup(matches, id, 'match')
    if m['status'] != 'REPORTED':
        raise ApiError('ERR_INVALID_STATE', 'match not in REPORTED')
    if uid is not None and uid == m.get('reported_by_user_id'):
        raise ApiError('ERR_SOD_SELF_CONFIRM', 'confirmer must differ from reporter')
    b = body()
    expected = require(b, 'expected_match_version')
    if expected != m['version']:
        raise ApiError('ERR_STALE_MATCH_VERSION', 'stale match version')
    t = tournaments[m['tournament_id']]
    m['confirmed_by_user_id'] = uid
    m['status'] = 'CONFIRMED'
    touch(m)
    core.confirm_cascade(t, m)
    return ok(serialize(m))


@app.route('/matches/<id>/replay', methods=['POST'])
def replay_match(id):
    require_role({'Referee', 'Director'})
    m = lookup(matches, id, 'match')
    if m['status'] != 'VOIDED':
        raise ApiError('ERR_INVALID_STATE', 'match not in VOIDED')
    if not m['home_registration_id'] or not m['away_registration_id']:
        raise ApiError('ERR_INVALID_STATE', 'both competitor slots must be populated')
    m['status'] = 'PENDING'
    m['station_id'] = None
    m['scheduled_start'] = None
    m['scheduled_end'] = None
    touch(m)
    return ok(serialize(m))


# ===========================================================================
# Stream assignments
# ===========================================================================
@app.route('/stream-assignments', methods=['POST'])
def create_stream_assignment():
    require_role({'Referee', 'Director'})
    b = body()
    match_id = req_str(b, 'match_id')
    channel_id = req_str(b, 'channel_id')
    m = lookup(matches, match_id, 'match')
    c = lookup(channels, channel_id, 'stream channel')
    if m['status'] not in ('SCHEDULED', 'REPORTED', 'CONFIRMED', 'DISPUTED'):
        raise ApiError('ERR_MATCH_NOT_SCHEDULABLE_STREAM', 'match not in a broadcastable state')
    start_s = req_str(b, 'start_at')
    end_s = req_str(b, 'end_at')
    start = parse_dt(start_s)
    end = parse_dt(end_s)
    if end <= start:
        raise ApiError('ERR_INVALID_REQUEST', 'end_at must be after start_at')
    if core.stream_conflict(c['id'], start, end, None):
        raise ApiError('ERR_CHANNEL_OVERLAP', 'channel is busy during this window')
    sa = create('StreamAssignment', {
        'match_id': match_id, 'channel_id': channel_id,
        'start_at': start_s, 'end_at': end_s, 'status': 'SCHEDULED',
    })
    return ok(serialize(sa), 201)


@app.route('/stream-assignments/<id>', methods=['GET'])
def get_stream_assignment(id):
    require_role(ALL_ROLES, optional=True)
    return ok(serialize(lookup(stream_assignments, id, 'stream assignment')))


@app.route('/stream-assignments', methods=['GET'])
def list_stream_assignments():
    require_role(ALL_ROLES, optional=True)
    items = list(stream_assignments.values())
    mid = request.args.get('match_id')
    cid = request.args.get('channel_id')
    status = request.args.get('status')
    if mid is not None:
        items = [s for s in items if s['match_id'] == mid]
    if cid is not None:
        items = [s for s in items if s['channel_id'] == cid]
    if status is not None:
        items = [s for s in items if s['status'] == status]
    return list_response(items)


# ===========================================================================
# Disputes
# ===========================================================================
@app.route('/disputes', methods=['POST'])
def create_dispute():
    require_role({'Player', 'Director'})
    b = body()
    match_id = req_str(b, 'match_id')
    raised_by = req_str(b, 'raised_by_registration_id')
    reason = req_str(b, 'reason')
    m = lookup(matches, match_id, 'match')
    lookup(registrations, raised_by, 'registration')
    if m['status'] not in ('REPORTED', 'CONFIRMED'):
        raise ApiError('ERR_MATCH_NOT_DISPUTABLE', 'match not REPORTED or CONFIRMED')
    for d in disputes.values():
        if d['match_id'] == match_id and d['status'] == 'OPEN':
            raise ApiError('ERR_DISPUTE_ALREADY_OPEN', 'an OPEN dispute already exists')
    d = create('Dispute', {
        'match_id': match_id, 'raised_by_registration_id': raised_by,
        'reason': reason, 'status': 'OPEN', 'resolution_note': None,
        'resolved_by_user_id': None,
    })
    if m['status'] == 'REPORTED':
        m['status'] = 'DISPUTED'
        touch(m)
    return ok(serialize(d), 201)


@app.route('/disputes/<id>', methods=['GET'])
def get_dispute(id):
    require_role(ALL_ROLES, optional=True)
    return ok(serialize(lookup(disputes, id, 'dispute')))


@app.route('/disputes', methods=['GET'])
def list_disputes():
    require_role(ALL_ROLES, optional=True)
    items = list(disputes.values())
    mid = request.args.get('match_id')
    rb = request.args.get('raised_by_registration_id')
    status = request.args.get('status')
    if mid is not None:
        items = [d for d in items if d['match_id'] == mid]
    if rb is not None:
        items = [d for d in items if d['raised_by_registration_id'] == rb]
    if status is not None:
        items = [d for d in items if d['status'] == status]
    return list_response(items)


@app.route('/disputes/<id>/resolve', methods=['POST'])
def resolve_dispute(id):
    role, uid = require_role({'Referee', 'Director'})
    d = lookup(disputes, id, 'dispute')
    m = lookup(matches, d['match_id'], 'match')
    if d['status'] != 'OPEN':
        raise ApiError('ERR_INVALID_STATE', 'dispute not OPEN')
    b = body()
    outcome = req_enum(b, 'outcome', {'UPHELD', 'REJECTED'})
    if uid is not None and m.get('confirmed_by_user_id') is not None and uid == m['confirmed_by_user_id']:
        raise ApiError('ERR_SOD_CONFIRMER_RESOLVE', 'resolver confirmed the match')
    expected = require(b, 'expected_match_version')
    if expected != m['version']:
        raise ApiError('ERR_STALE_MATCH_VERSION', 'stale match version')
    t = tournaments[m['tournament_id']]
    d['resolved_by_user_id'] = uid
    d['resolution_note'] = b.get('resolution_note')
    if outcome == 'UPHELD':
        d['status'] = 'UPHELD'
        was_confirmed = m['status'] == 'CONFIRMED'
        core.void_cascade(t, m, was_confirmed)
    else:
        d['status'] = 'REJECTED'
        if m['status'] == 'DISPUTED':
            m['status'] = 'REPORTED'
        touch(m)
    touch(d)
    return ok(serialize(d))


# ===========================================================================
# Payouts
# ===========================================================================
@app.route('/payouts/<id>', methods=['GET'])
def get_payout(id):
    require_role(ALL_ROLES, optional=True)
    return ok(serialize(lookup(payouts, id, 'payout')))


@app.route('/payouts', methods=['GET'])
def list_payouts():
    require_role(ALL_ROLES, optional=True)
    items = list(payouts.values())
    tid = request.args.get('tournament_id')
    rid = request.args.get('registration_id')
    variant = request.args.get('variant')
    status = request.args.get('status')
    if tid is not None:
        items = [p for p in items if p['tournament_id'] == tid]
    if rid is not None:
        items = [p for p in items if p['registration_id'] == rid]
    if variant is not None:
        items = [p for p in items if p['variant'] == variant]
    if status is not None:
        items = [p for p in items if p['status'] == status]
    return list_response(items)


@app.route('/payouts/<id>/pay', methods=['POST'])
def pay_payout(id):
    require_role({'Director'})
    p = lookup(payouts, id, 'payout')
    t = tournaments.get(p['tournament_id'])
    if p['variant'] != 'FINAL' or t is None or t['status'] != 'COMPLETED':
        raise ApiError('ERR_PAYOUT_NOT_FINAL', 'payout is not a FINAL payout of a completed tournament')
    if p['status'] != 'PENDING':
        raise ApiError('ERR_INVALID_STATE', 'payout not in PENDING')
    p['status'] = 'PAID'
    touch(p)
    return ok(serialize(p))


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route('/_clock/set_current_utc', methods=['POST'])
def set_clock():
    require_role({'Director'})
    b = body()
    to_iso = req_str(b, 'to_iso8601')
    dt = parse_dt(to_iso)
    core.set_clock(dt)
    return ok({'now': fmt_dt(dt)})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '10000'))
    app.run(host='0.0.0.0', port=port, threaded=True)
