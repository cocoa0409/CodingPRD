"""Ballot routes: cast, list, get."""
from flask import Blueprint, request

from db import STORE, new_id, now_iso, CLOCK
from errors import raise_err
from middleware import require_roles
from response import success_object, success_list
from util import body, get_field, get_pagination, paginate, parse_dt
from services import domain, calculations
from services.serializers import ballot_json

bp = Blueprint('ballots', __name__)


@bp.route('/ballots', methods=['POST'])
def cast_ballot():
    user_id, role = require_roles('Participant')
    data = body()
    event_id = get_field(data, 'event_id', type_=str)
    registration_id = get_field(data, 'registration_id', type_=str)

    # Existence left to right
    ev = STORE.events.get(event_id)
    if ev is None:
        raise_err(('ERR_NOT_FOUND', 404), 'Event not found')
    reg = STORE.registrations.get(registration_id)
    if reg is None or reg['event_id'] != event_id:
        raise_err(('ERR_NOT_FOUND', 404), 'Registration not found')
    voter = STORE.registrants.get(user_id)
    if voter is None:
        raise_err(('ERR_NOT_FOUND', 404), 'Voter registrant not found')

    # Ballot window + event state (both surface as ERR_BALLOT_WINDOW_CLOSED per
    # the error catalog)
    if ev['lifecycle_status'] != 'JUDGING':
        raise_err(('ERR_BALLOT_WINDOW_CLOSED', 422),
                  'Ballots are accepted only while the event is JUDGING')
    now = parse_dt(CLOCK.now())
    if not (parse_dt(ev['gates_open_at']) <= now < parse_dt(ev['ballot_close_at'])):
        raise_err(('ERR_BALLOT_WINDOW_CLOSED', 422),
                  'Outside the ballot window [gates_open_at, ballot_close_at)')

    for b in STORE.ballots.values():
        if b['event_id'] == event_id and b['voter_registrant_id'] == user_id:
            raise_err(('ERR_DUPLICATE_BALLOT', 409),
                      'Voter already cast a ballot for this event')
    cls = STORE.classes.get(reg['class_id'])
    if cls is None or cls['judging_mode'] not in ('PEOPLES_CHOICE', 'BOTH'):
        raise_err(('ERR_VOTE_INELIGIBLE_CLASS', 422),
                  'Target class is not a people\'s-choice class')

    weight = calculations.MEMBER_BALLOT_WEIGHT if voter.get('club_member') else 1
    now_iso_str = now_iso()
    ballot = {
        'id': new_id(),
        'event_id': event_id,
        'registration_id': registration_id,
        'voter_registrant_id': user_id,
        'weight': weight,
        'status': 'VALID',
        'created_at': now_iso_str,
        'updated_at': now_iso_str,
        'version': 1,
        '_seq': STORE.next_seq(),
    }
    STORE.ballots[ballot['id']] = ballot
    return success_object(ballot_json(ballot), status=201)


@bp.route('/ballots', methods=['GET'])
def list_ballots():
    require_roles('Organizer', 'RegistrationDesk')
    limit, offset = get_pagination()
    items = domain.sorted_created(list(STORE.ballots.values()))
    for param in ('event_id', 'registration_id', 'voter_registrant_id', 'status'):
        val = request.args.get(param)
        if val:
            items = [b for b in items if str(b.get(param)) == val]
    page, total = paginate(items, limit, offset)
    return success_list([ballot_json(b) for b in page], limit, offset, total)


@bp.route('/ballots/<ballot_id>', methods=['GET'])
def get_ballot(ballot_id):
    require_roles('Organizer', 'RegistrationDesk')
    ballot = STORE.ballots.get(ballot_id)
    if ballot is None:
        raise_err(('ERR_NOT_FOUND', 404), 'Ballot not found')
    return success_object(ballot_json(ballot))
