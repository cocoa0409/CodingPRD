"""Registrant, vehicle, and waiver routes."""
from flask import Blueprint, request

from db import STORE, new_id, now_iso, CLOCK
from errors import raise_err
from middleware import require_roles, check_participant_owns
from response import success_object, success_list
from util import body, get_field, get_int, get_pagination, paginate
from services import domain
from services.serializers import registrant_json, vehicle_json, waiver_json

bp = Blueprint('registrants', __name__)


def _get_registrant_or_404(registrant_id):
    reg = STORE.registrants.get(registrant_id)
    if reg is None:
        raise_err(('ERR_NOT_FOUND', 404), 'Registrant not found')
    return reg


@bp.route('/registrants', methods=['POST'])
def create_registrant():
    require_roles('Participant', 'RegistrationDesk', 'Organizer')
    data = body()
    full_name = get_field(data, 'full_name', type_=str)
    email = get_field(data, 'email', type_=str)
    club_member = get_field(data, 'club_member', required=False, default=False, type_=bool)
    is_minor = get_field(data, 'is_minor', required=False, default=False, type_=bool)
    now = now_iso()
    reg = {
        'id': new_id(),
        'full_name': full_name,
        'email': email,
        'club_member': club_member,
        'is_minor': is_minor,
        'created_at': now,
        'updated_at': now,
        'version': 1,
        '_seq': STORE.next_seq(),
    }
    STORE.registrants[reg['id']] = reg
    return success_object(registrant_json(reg), status=201)


@bp.route('/registrants/<registrant_id>', methods=['GET'])
def get_registrant(registrant_id):
    user_id, role = require_roles('Participant', 'RegistrationDesk', 'Organizer')
    reg = _get_registrant_or_404(registrant_id)
    check_participant_owns(user_id, role, reg['id'])
    return success_object(registrant_json(reg))


@bp.route('/registrants/<registrant_id>/vehicles', methods=['POST'])
def create_vehicle(registrant_id):
    user_id, role = require_roles('Participant', 'RegistrationDesk', 'Organizer')
    reg = _get_registrant_or_404(registrant_id)
    check_participant_owns(user_id, role, reg['id'])
    data = body()
    year = get_int(data, 'year')
    make = get_field(data, 'make', type_=str)
    model = get_field(data, 'model', type_=str)
    now = now_iso()
    veh = {
        'id': new_id(),
        'registrant_id': registrant_id,
        'year': year,
        'make': make,
        'model': model,
        'created_at': now,
        'updated_at': now,
        'version': 1,
        '_seq': STORE.next_seq(),
    }
    STORE.vehicles[veh['id']] = veh
    return success_object(vehicle_json(veh), status=201)


@bp.route('/registrants/<registrant_id>/vehicles', methods=['GET'])
def list_vehicles(registrant_id):
    user_id, role = require_roles('Participant', 'RegistrationDesk', 'Organizer')
    reg = _get_registrant_or_404(registrant_id)
    check_participant_owns(user_id, role, reg['id'])
    limit, offset = get_pagination()
    items = domain.sorted_created([v for v in STORE.vehicles.values()
                                   if v['registrant_id'] == registrant_id])
    page, total = paginate(items, limit, offset)
    return success_list([vehicle_json(v) for v in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Waivers
# ---------------------------------------------------------------------------

@bp.route('/waivers', methods=['POST'])
def create_waiver():
    user_id, role = require_roles('Participant', 'RegistrationDesk')
    data = body()
    event_id = get_field(data, 'event_id', type_=str)
    registrant_id = get_field(data, 'registrant_id', type_=str)
    signature_name = get_field(data, 'signature_name', type_=str)
    guardian_name = get_field(data, 'guardian_name', required=False, default=None)
    if guardian_name is not None and not isinstance(guardian_name, str):
        raise_err(('ERR_VALIDATION', 400), 'guardian_name must be a string')
    check_participant_owns(user_id, role, registrant_id)
    # Existence: body FK targets left-to-right
    if event_id not in STORE.events:
        raise_err(('ERR_NOT_FOUND', 404), 'Event not found')
    registrant = _get_registrant_or_404(registrant_id)
    # One waiver per (registrant_id, event_id)
    for w in STORE.waivers.values():
        if w['event_id'] == event_id and w['registrant_id'] == registrant_id:
            raise_err(('ERR_VALIDATION', 400),
                      'A waiver already exists for this registrant and event')
    # (uniqueness violation is a shape-level rule for this immutable resource)
    if registrant.get('is_minor') and not guardian_name:
        raise_err(('ERR_GUARDIAN_SIGNATURE_REQUIRED', 422),
                  'Waiver for a minor registrant requires guardian_name')
    waiver = {
        'id': new_id(),
        'event_id': event_id,
        'registrant_id': registrant_id,
        'signature_name': signature_name,
        'guardian_name': guardian_name,
        'signed_at': CLOCK.now(),
        'created_at': now_iso(),
        '_seq': STORE.next_seq(),
    }
    STORE.waivers[waiver['id']] = waiver
    return success_object(waiver_json(waiver), status=201)


@bp.route('/waivers', methods=['GET'])
def list_waivers():
    user_id, role = require_roles('Organizer', 'RegistrationDesk', 'Participant')
    limit, offset = get_pagination()
    event_id = request.args.get('event_id')
    registrant_id = request.args.get('registrant_id')
    items = domain.sorted_created(list(STORE.waivers.values()))
    if role == 'Participant':
        items = [w for w in items if w['registrant_id'] == user_id]
    if event_id:
        items = [w for w in items if w['event_id'] == event_id]
    if registrant_id:
        items = [w for w in items if w['registrant_id'] == registrant_id]
    page, total = paginate(items, limit, offset)
    return success_list([waiver_json(w) for w in page], limit, offset, total)


@bp.route('/waivers/<waiver_id>', methods=['GET'])
def get_waiver(waiver_id):
    user_id, role = require_roles('Organizer', 'RegistrationDesk', 'Participant')
    w = STORE.waivers.get(waiver_id)
    if w is None:
        raise_err(('ERR_NOT_FOUND', 404), 'Waiver not found')
    check_participant_owns(user_id, role, w['registrant_id'])
    return success_object(waiver_json(w))
