"""Event routes: CRUD, lifecycle transitions, weather, tabulation finalize,
summary, classes, zones, judges, sound slots, noise readings, clock."""
from flask import Blueprint

from db import STORE, new_id, now_iso, CLOCK
from errors import ApiError, raise_err
from middleware import require_roles
from response import success_object, success_list
from util import (body, get_field, get_enum, get_int, get_pagination, paginate,
                  parse_dt, parse_hhmm, parse_date)
from services import domain, calculations
from services.serializers import (event_json, class_json, zone_json, judge_json,
                                  sound_slot_json, noise_reading_json)

bp = Blueprint('events', __name__)

TABULATION_METHODS = ('STRAIGHT_AVERAGE', 'DROP_EXTREMES')
ZONE_TYPES = ('SHOW_FIELD', 'OVERFLOW', 'VENDOR_ROW')
JUDGING_MODES = ('JUDGED', 'PEOPLES_CHOICE', 'BOTH')
NOISE_SOURCES = ('STAGE', 'PA_SYSTEM', 'EXHAUST', 'CROWD')


def _get_event_or_404(event_id):
    ev = STORE.events.get(event_id)
    if ev is None:
        raise_err(('ERR_NOT_FOUND', 404), 'Event not found')
    return ev


# ---------------------------------------------------------------------------
# Event CRUD
# ---------------------------------------------------------------------------

@bp.route('/events', methods=['POST'])
def create_event():
    user_id, role = require_roles('Organizer')
    data = body()
    name = get_field(data, 'name', type_=str)
    event_date = get_field(data, 'event_date', type_=str)
    parse_date(event_date, 'event_date')
    gates_open_at = get_field(data, 'gates_open_at', type_=str)
    judging_start_at = get_field(data, 'judging_start_at', type_=str)
    judging_end_at = get_field(data, 'judging_end_at', type_=str)
    ballot_close_at = get_field(data, 'ballot_close_at', type_=str)
    prereg_deadline = get_field(data, 'prereg_deadline', type_=str)
    for f in (gates_open_at, judging_start_at, judging_end_at, ballot_close_at,
              prereg_deadline):
        parse_dt(f)
    curfew_start = get_field(data, 'curfew_start', type_=str)
    curfew_end = get_field(data, 'curfew_end', type_=str)
    parse_hhmm(curfew_start, 'curfew_start')
    parse_hhmm(curfew_end, 'curfew_end')
    liability_policy_number = get_field(data, 'liability_policy_number',
                                        required=False, default='', type_=str)
    tabulation_method = get_enum(data, 'tabulation_method', TABULATION_METHODS,
                                 required=False, default='STRAIGHT_AVERAGE')
    now = now_iso()
    ev = {
        'id': new_id(),
        'name': name,
        'event_date': event_date,
        'gates_open_at': gates_open_at,
        'judging_start_at': judging_start_at,
        'judging_end_at': judging_end_at,
        'ballot_close_at': ballot_close_at,
        'prereg_deadline': prereg_deadline,
        'curfew_start': curfew_start,
        'curfew_end': curfew_end,
        'liability_policy_number': liability_policy_number,
        'tabulation_method': tabulation_method,
        'lifecycle_status': 'DRAFT',
        'weather_posture': 'NORMAL',
        'sound_permit_status': 'ACTIVE',
        'treasury_cents': 0,
        'noise_exceedance_count': 0,
        'finalized_by_user_id': '',
        'created_at': now,
        'updated_at': now,
        'version': 1,
        '_seq': STORE.next_seq(),
    }
    STORE.events[ev['id']] = ev
    return success_object(event_json(ev), status=201)


@bp.route('/events', methods=['GET'])
def list_events():
    require_roles('Organizer', 'RegistrationDesk', 'Participant', 'Judge', 'Vendor')
    limit, offset = get_pagination()
    status_filter = None
    from flask import request
    status_filter = request.args.get('lifecycle_status')
    items = domain.sorted_created(list(STORE.events.values()))
    if status_filter:
        items = [e for e in items if e['lifecycle_status'] == status_filter]
    page, total = paginate(items, limit, offset)
    return success_list([event_json(e) for e in page], limit, offset, total)


@bp.route('/events/<event_id>', methods=['GET'])
def get_event(event_id):
    require_roles('Organizer', 'RegistrationDesk', 'Participant', 'Judge', 'Vendor')
    ev = _get_event_or_404(event_id)
    return success_object(event_json(ev))


@bp.route('/events/<event_id>', methods=['PATCH'])
def update_event(event_id):
    require_roles('Organizer')
    ev = _get_event_or_404(event_id)
    data = body()
    if ev['lifecycle_status'] != 'DRAFT':
        raise_err(('ERR_INVALID_EVENT_STATE', 409),
                  'Event configuration may be updated only in DRAFT')
    updatable = ('name', 'event_date', 'gates_open_at', 'judging_start_at',
                 'judging_end_at', 'ballot_close_at', 'prereg_deadline',
                 'curfew_start', 'curfew_end', 'liability_policy_number',
                 'tabulation_method')
    changed = False
    for field in updatable:
        if field in data:
            val = data[field]
            if field == 'tabulation_method':
                if val not in TABULATION_METHODS:
                    raise_err(('ERR_VALIDATION', 400),
                              'tabulation_method must be STRAIGHT_AVERAGE or DROP_EXTREMES')
            elif field == 'event_date':
                parse_date(val, field)
            elif field in ('gates_open_at', 'judging_start_at', 'judging_end_at',
                           'ballot_close_at', 'prereg_deadline'):
                parse_dt(val, field)
            elif field in ('curfew_start', 'curfew_end'):
                parse_hhmm(val, field)
            elif field in ('name', 'liability_policy_number'):
                if not isinstance(val, str):
                    raise_err(('ERR_VALIDATION', 400), f'{field} must be a string')
            ev[field] = val
            changed = True
    if changed:
        domain.touch_entity(ev)
    return success_object(event_json(ev))


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------

@bp.route('/events/<event_id>/publish', methods=['POST'])
def publish_event(event_id):
    require_roles('Organizer')
    ev = _get_event_or_404(event_id)
    if ev['lifecycle_status'] != 'DRAFT':
        raise_err(('ERR_INVALID_EVENT_STATE', 409), 'Event is not in DRAFT')
    if not ev['liability_policy_number']:
        raise_err(('ERR_INSURANCE_POLICY_MISSING', 422),
                  'liability_policy_number must be non-empty before publish')
    if not domain.classes_of_event(event_id) or not domain.zones_of_event(event_id):
        raise_err(('ERR_VALIDATION', 400),
                  'At least one class and one zone are required before publish')
    if not (parse_dt(ev['prereg_deadline']) < parse_dt(ev['gates_open_at'])
            <= parse_dt(ev['judging_start_at']) < parse_dt(ev['judging_end_at'])):
        raise_err(('ERR_VALIDATION', 400),
                  'Timeline must satisfy prereg_deadline < gates_open_at <= judging_start_at < judging_end_at')
    ev['lifecycle_status'] = 'PUBLISHED'
    domain.bump_event(ev)
    return success_object(event_json(ev))


@bp.route('/events/<event_id>/open-registration', methods=['POST'])
def open_registration(event_id):
    require_roles('Organizer')
    ev = _get_event_or_404(event_id)
    if ev['lifecycle_status'] != 'PUBLISHED':
        raise_err(('ERR_INVALID_EVENT_STATE', 409), 'Event is not PUBLISHED')
    if ev['weather_posture'] not in ('NORMAL', 'WATCH'):
        raise_err(('ERR_INVALID_EVENT_STATE', 409),
                  'Weather posture must be NORMAL or WATCH to open registration')
    ev['lifecycle_status'] = 'REGISTRATION_OPEN'
    domain.bump_event(ev)
    return success_object(event_json(ev))


@bp.route('/events/<event_id>/lock-registration', methods=['POST'])
def lock_registration(event_id):
    require_roles('Organizer')
    ev = _get_event_or_404(event_id)
    if ev['lifecycle_status'] != 'REGISTRATION_OPEN':
        raise_err(('ERR_INVALID_EVENT_STATE', 409), 'Event is not REGISTRATION_OPEN')
    ev['lifecycle_status'] = 'REGISTRATION_LOCKED'
    domain.bump_event(ev)
    return success_object(event_json(ev))


@bp.route('/events/<event_id>/start-judging', methods=['POST'])
def start_judging(event_id):
    require_roles('Organizer')
    ev = _get_event_or_404(event_id)
    if ev['lifecycle_status'] != 'REGISTRATION_LOCKED':
        raise_err(('ERR_INVALID_EVENT_STATE', 409), 'Event is not REGISTRATION_LOCKED')
    if ev['weather_posture'] == 'CANCELLED':
        raise_err(('ERR_INVALID_EVENT_STATE', 409),
                  'Cannot start judging while weather is CANCELLED')

    # Side effect 1: gate no-shows
    for reg in domain.registrations_of_event(event_id):
        if reg['status'] == 'CONFIRMED':
            reg['status'] = 'NO_SHOW'
            domain.touch_entity(reg)

    # Side effect 2: materialize award rows in PENDING
    for cls in domain.sorted_created(domain.classes_of_event(event_id)):
        if cls['judging_mode'] in ('JUDGED', 'BOTH'):
            for place in range(1, cls['award_depth'] + 1):
                _create_award(ev, cls['id'], 'CLASS_PLACE', place)
        if cls['judging_mode'] in ('PEOPLES_CHOICE', 'BOTH'):
            _create_award(ev, cls['id'], 'PEOPLES_CHOICE', None)
    _create_award(ev, None, 'BEST_OF_SHOW', None)

    ev['lifecycle_status'] = 'JUDGING'
    domain.bump_event(ev)

    # Side effect 3: auto-advance when nothing to judge
    domain.maybe_auto_advance_to_tabulating(ev)
    return success_object(event_json(ev))


def _create_award(event, class_id, award_kind, place):
    now = now_iso()
    award = {
        'id': new_id(),
        'event_id': event['id'],
        'class_id': class_id,
        'award_kind': award_kind,
        'place': place,
        'status': 'PENDING',
        'winner_registration_id': None,
        'winner_score': None,
        'tie_break_log': '',
        'overridden': False,
        'created_at': now,
        'updated_at': now,
        'version': 1,
        '_seq': STORE.next_seq(),
    }
    STORE.awards[award['id']] = award
    return award


# ---------------------------------------------------------------------------
# Weather decisions (PRD 3.7)
# ---------------------------------------------------------------------------

@bp.route('/events/<event_id>/weather-decision', methods=['POST'])
def weather_decision(event_id):
    user_id, role = require_roles('Organizer')
    ev = _get_event_or_404(event_id)
    data = body()
    posture = get_enum(data, 'posture', ('NORMAL', 'WATCH', 'POSTPONED', 'CANCELLED'))
    get_field(data, 'reason', required=False, default=None, type_=str)

    current = ev['weather_posture']
    allowed = {
        'NORMAL': {'WATCH', 'POSTPONED', 'CANCELLED'},
        'WATCH': {'NORMAL', 'POSTPONED', 'CANCELLED'},
        'POSTPONED': {'NORMAL', 'CANCELLED'},
        'CANCELLED': set(),
    }
    if posture not in allowed.get(current, set()):
        raise_err(('ERR_INVALID_EVENT_STATE', 409),
                  f'Weather posture cannot move {current} -> {posture}')

    if posture == 'POSTPONED':
        calculations.postponement_refunds(ev, user_id)
    elif posture == 'CANCELLED':
        calculations.cancellation_refunds(ev, user_id)

    ev['weather_posture'] = posture
    # Organizer all-clear: NORMAL also reinstates a SUSPENDED sound permit
    if posture == 'NORMAL' and ev['sound_permit_status'] == 'SUSPENDED':
        ev['sound_permit_status'] = 'ACTIVE'
    domain.bump_event(ev)
    return success_object(event_json(ev))


# ---------------------------------------------------------------------------
# Tabulation finalize (PRD 3.6)
# ---------------------------------------------------------------------------

@bp.route('/events/<event_id>/tabulations/finalize', methods=['POST'])
def finalize_tabulations(event_id):
    user_id, role = require_roles('Organizer')
    ev = _get_event_or_404(event_id)
    data = body()
    expected = get_field(data, 'expected_event_version', type_=int)

    # State precondition
    status = ev['lifecycle_status']
    allowed = status in ('TABULATING', 'FINALIZED')
    if status == 'JUDGING' and not domain.judged_classes(event_id):
        allowed = True
    if not allowed:
        raise_err(('ERR_INVALID_EVENT_STATE', 409),
                  'Event must be TABULATING or FINALIZED to finalize tabulations')
    # OCC
    if expected != ev['version']:
        raise_err(('ERR_STALE_VERSION', 412),
                  'expected_event_version does not match the event version')

    # Recompute every non-overridden award in PENDING or COMPUTED
    awards = [a for a in domain.awards_of_event(event_id)
              if a['status'] in ('PENDING', 'COMPUTED') and not a.get('overridden', False)]
    # Stable ordering: class-place by class then place; PC; BEST_OF_SHOW last
    def award_order(a):
        cls_seq = 0
        if a['class_id']:
            cls = STORE.classes.get(a['class_id'])
            cls_seq = cls.get('_seq', 0) if cls else 0
        kind_rank = {'CLASS_PLACE': 0, 'PEOPLES_CHOICE': 1, 'BEST_OF_SHOW': 2}[a['award_kind']]
        return (cls_seq, kind_rank, a.get('place') or 0, a.get('_seq', 0))
    awards.sort(key=award_order)

    bos_candidates = []
    for award in awards:
        if award['award_kind'] == 'CLASS_PLACE':
            _compute_class_place(ev, award, bos_candidates)
        elif award['award_kind'] == 'PEOPLES_CHOICE':
            _compute_peoples_choice(ev, award)
        elif award['award_kind'] == 'BEST_OF_SHOW':
            _compute_best_of_show(ev, award, awards)
        # PENDING -> COMPUTED -> FINALIZED within the same request
        award['status'] = 'FINALIZED'
        domain.touch_entity(award)

    ev['finalized_by_user_id'] = user_id
    ev['lifecycle_status'] = 'FINALIZED'
    domain.bump_event(ev)
    return success_object(event_json(ev))


def _compute_class_place(ev, award, bos_candidates):
    cls = STORE.classes.get(award['class_id'])
    if cls is None:
        award.update(winner_registration_id=None, winner_score=None,
                     tie_break_log='INSUFFICIENT_ENTRIES')
        return
    ranked = calculations.rank_judged_class(ev, cls)
    idx = (award['place'] or 1) - 1
    if idx < len(ranked):
        reg, score = ranked[idx]
        award['winner_registration_id'] = reg['id']
        award['winner_score'] = score
        award['tie_break_log'] = calculations.tie_break_log_for(ranked, idx)
        if award['place'] == 1:
            bos_candidates.append((reg, score))
    else:
        award['winner_registration_id'] = None
        award['winner_score'] = None
        award['tie_break_log'] = 'INSUFFICIENT_ENTRIES'


def _compute_peoples_choice(ev, award):
    cls = STORE.classes.get(award['class_id'])
    if cls is None:
        award.update(winner_registration_id=None, winner_score=None,
                     tie_break_log='NO_VALID_BALLOTS')
        return
    ranked, total_valid = calculations.tally_peoples_choice(ev, cls)
    if total_valid == 0:
        award['winner_registration_id'] = None
        award['winner_score'] = None
        award['tie_break_log'] = 'NO_VALID_BALLOTS'
        return
    reg, tally, members = ranked[0]
    award['winner_registration_id'] = reg['id']
    award['winner_score'] = tally
    award['tie_break_log'] = calculations.pc_tie_break_log(ranked, 0)


def _compute_best_of_show(ev, award, all_awards):
    """Highest-scoring CLASS_PLACE place-1 winner across judged classes; ties
    resolved by the same 5-level tie-break chain."""
    candidates = []
    for a in all_awards:
        if (a['award_kind'] == 'CLASS_PLACE' and a['place'] == 1
                and a.get('winner_registration_id')):
            reg = STORE.registrations.get(a['winner_registration_id'])
            if reg is not None:
                candidates.append((reg, a['winner_score']))
    if not candidates:
        award['winner_registration_id'] = None
        award['winner_score'] = None
        award['tie_break_log'] = 'INSUFFICIENT_ENTRIES'
        return

    def key(item):
        reg, score = item
        cond = calculations.compute_condition_avg(reg) or 0
        cnt = sum(1 for s in domain.sheets_of_registration(reg['id'])
                  if s['status'] == 'LOCKED')
        vehicle = STORE.vehicles.get(reg['vehicle_id'])
        year = vehicle['year'] if vehicle else 0
        from decimal import Decimal
        return (-Decimal(str(score)), -Decimal(str(cond)), -cnt,
                reg.get('checked_in_at') or '', -year)

    candidates.sort(key=key)
    reg, score = candidates[0]
    award['winner_registration_id'] = reg['id']
    award['winner_score'] = score
    if len(candidates) > 1:
        award['tie_break_log'] = 'CLASS_SCORE'
    else:
        award['tie_break_log'] = 'CLASS_SCORE'


# ---------------------------------------------------------------------------
# Close
# ---------------------------------------------------------------------------

@bp.route('/events/<event_id>/close', methods=['POST'])
def close_event(event_id):
    require_roles('Organizer')
    ev = _get_event_or_404(event_id)
    if not (ev['lifecycle_status'] == 'FINALIZED' or ev['weather_posture'] == 'CANCELLED'):
        raise_err(('ERR_INVALID_EVENT_STATE', 409),
                  'Event must be FINALIZED or weather CANCELLED to close')
    for reg in domain.registrations_of_event(event_id):
        if reg['status'] == 'CHECKED_IN':
            reg['status'] = 'COMPLETED'
            domain.touch_entity(reg)
    ev['lifecycle_status'] = 'CLOSED'
    domain.bump_event(ev)
    return success_object(event_json(ev))


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

@bp.route('/events/<event_id>/summary', methods=['GET'])
def event_summary(event_id):
    require_roles('Organizer', 'RegistrationDesk')
    ev = _get_event_or_404(event_id)
    regs = domain.registrations_of_event(event_id)
    summary = {
        'treasury_cents': domain.compute_treasury(event_id),
        'refunded_cents_total': domain.compute_refunded_cents_total(event_id),
        'registration_count': len(regs),
        'checked_in_count': sum(1 for r in regs if r['status'] == 'CHECKED_IN'),
        'noise_exceedance_count': domain.compute_noise_exceedance_count(event_id),
        'sound_permit_status': ev['sound_permit_status'],
        'lifecycle_status': ev['lifecycle_status'],
        'weather_posture': ev['weather_posture'],
    }
    return success_object(summary)


# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------

@bp.route('/events/<event_id>/classes', methods=['POST'])
def create_class(event_id):
    require_roles('Organizer')
    ev = _get_event_or_404(event_id)
    data = body()
    code = get_field(data, 'code', type_=str)
    name = get_field(data, 'name', type_=str)
    min_year = get_int(data, 'min_year')
    max_year = get_int(data, 'max_year')
    prereg_fee_cents = get_int(data, 'prereg_fee_cents', min_v=0)
    day_of_fee_cents = get_int(data, 'day_of_fee_cents', min_v=0)
    capacity = get_int(data, 'capacity', min_v=1)
    judging_mode = get_enum(data, 'judging_mode', JUDGING_MODES)
    award_depth = get_int(data, 'award_depth', min_v=1, max_v=3)
    if min_year > max_year:
        raise_err(('ERR_VALIDATION', 400), 'min_year must be <= max_year')
    for existing in domain.classes_of_event(event_id):
        if existing['code'] == code:
            raise_err(('ERR_DUPLICATE_CLASS_CODE', 409),
                      'Class code already exists within the event')
    if ev['lifecycle_status'] not in ('DRAFT', 'PUBLISHED'):
        raise_err(('ERR_INVALID_EVENT_STATE', 409),
                  'Classes may be created only while DRAFT or PUBLISHED')
    now = now_iso()
    cls = {
        'id': new_id(),
        'event_id': event_id,
        'code': code,
        'name': name,
        'min_year': min_year,
        'max_year': max_year,
        'prereg_fee_cents': prereg_fee_cents,
        'day_of_fee_cents': day_of_fee_cents,
        'capacity': capacity,
        'judging_mode': judging_mode,
        'award_depth': award_depth,
        'confirmed_count': 0,
        'created_at': now,
        'updated_at': now,
        'version': 1,
        '_seq': STORE.next_seq(),
    }
    STORE.classes[cls['id']] = cls
    return success_object(class_json(cls), status=201)


@bp.route('/events/<event_id>/classes', methods=['GET'])
def list_classes(event_id):
    require_roles('Organizer', 'RegistrationDesk', 'Participant', 'Judge', 'Vendor')
    _get_event_or_404(event_id)
    limit, offset = get_pagination()
    items = domain.sorted_created(domain.classes_of_event(event_id))
    page, total = paginate(items, limit, offset)
    return success_list([class_json(c) for c in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------

@bp.route('/events/<event_id>/zones', methods=['POST'])
def create_zone(event_id):
    require_roles('Organizer')
    ev = _get_event_or_404(event_id)
    data = body()
    name = get_field(data, 'name', type_=str)
    zone_type = get_enum(data, 'zone_type', ZONE_TYPES)
    capacity = get_int(data, 'capacity', min_v=1)
    has_power = get_field(data, 'has_power', required=False, default=False, type_=bool)
    aws = get_field(data, 'arrival_window_start', required=False, default=None)
    awe = get_field(data, 'arrival_window_end', required=False, default=None)
    if aws is not None:
        parse_dt(aws, 'arrival_window_start')
    if awe is not None:
        parse_dt(awe, 'arrival_window_end')
    if ev['lifecycle_status'] not in ('DRAFT', 'PUBLISHED'):
        raise_err(('ERR_INVALID_EVENT_STATE', 409),
                  'Zones may be created only while DRAFT or PUBLISHED')
    now = now_iso()
    zone = {
        'id': new_id(),
        'event_id': event_id,
        'name': name,
        'zone_type': zone_type,
        'capacity': capacity,
        'has_power': has_power,
        'arrival_window_start': aws,
        'arrival_window_end': awe,
        'assigned_count': 0,
        'created_at': now,
        'updated_at': now,
        'version': 1,
        '_seq': STORE.next_seq(),
    }
    STORE.zones[zone['id']] = zone
    return success_object(zone_json(zone), status=201)


@bp.route('/events/<event_id>/zones', methods=['GET'])
def list_zones(event_id):
    require_roles('Organizer', 'RegistrationDesk', 'Participant', 'Judge', 'Vendor')
    _get_event_or_404(event_id)
    limit, offset = get_pagination()
    items = domain.sorted_created(domain.zones_of_event(event_id))
    page, total = paginate(items, limit, offset)
    return success_list([zone_json(z) for z in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Judges
# ---------------------------------------------------------------------------

@bp.route('/events/<event_id>/judges', methods=['POST'])
def create_judge(event_id):
    require_roles('Organizer')
    ev = _get_event_or_404(event_id)
    data = body()
    name = get_field(data, 'name', type_=str)
    email = get_field(data, 'email', type_=str)
    assigned = get_field(data, 'assigned_class_ids', type_=list)
    for cid in assigned:
        if not isinstance(cid, str):
            raise_err(('ERR_VALIDATION', 400), 'assigned_class_ids must be strings')
    if ev['lifecycle_status'] == 'CLOSED':
        raise_err(('ERR_INVALID_EVENT_STATE', 409),
                  'Judges may not be added once the event is CLOSED')
    for cid in assigned:
        cls = STORE.classes.get(cid)
        if cls is None or cls['event_id'] != event_id:
            raise_err(('ERR_NOT_FOUND', 404), f'Class {cid} not found for this event')
    now = now_iso()
    judge = {
        'id': new_id(),
        'event_id': event_id,
        'name': name,
        'email': email,
        'assigned_class_ids': list(assigned),
        'submitted_sheet_count': 0,
        'created_at': now,
        'updated_at': now,
        'version': 1,
        '_seq': STORE.next_seq(),
    }
    STORE.judges[judge['id']] = judge
    return success_object(judge_json(judge), status=201)


@bp.route('/events/<event_id>/judges', methods=['GET'])
def list_judges(event_id):
    require_roles('Organizer', 'RegistrationDesk', 'Participant', 'Judge', 'Vendor')
    _get_event_or_404(event_id)
    limit, offset = get_pagination()
    items = domain.sorted_created(domain.judges_of_event(event_id))
    page, total = paginate(items, limit, offset)
    return success_list([judge_json(j) for j in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Sound slots (PRD 3.8)
# ---------------------------------------------------------------------------

@bp.route('/events/<event_id>/sound-slots', methods=['POST'])
def create_sound_slot(event_id):
    require_roles('Organizer')
    ev = _get_event_or_404(event_id)
    data = body()
    performer_name = get_field(data, 'performer_name', type_=str)
    slot_start = get_field(data, 'slot_start', type_=str)
    slot_end = get_field(data, 'slot_end', type_=str)
    expected_db = get_field(data, 'expected_db', type_=(int, float))
    start_dt = parse_dt(slot_start, 'slot_start')
    end_dt = parse_dt(slot_end, 'slot_end')
    if not start_dt < end_dt:
        raise_err(('ERR_VALIDATION', 400), 'slot_start must be before slot_end')
    if ev['sound_permit_status'] != 'ACTIVE':
        raise_err(('ERR_SOUND_PERMIT_SUSPENDED', 422),
                  'Sound permit is SUSPENDED; new sound slots rejected')
    for slot in domain.sound_slots_of_event(event_id):
        if slot['status'] != 'SCHEDULED':
            continue
        if start_dt < parse_dt(slot['slot_end']) and end_dt > parse_dt(slot['slot_start']):
            raise_err(('ERR_SOUND_SLOT_OVERLAP', 409),
                      'Requested slot intersects an existing SCHEDULED slot')
    now = now_iso()
    slot = {
        'id': new_id(),
        'event_id': event_id,
        'performer_name': performer_name,
        'slot_start': slot_start,
        'slot_end': slot_end,
        'expected_db': expected_db,
        'status': 'SCHEDULED',
        'created_at': now,
        'updated_at': now,
        'version': 1,
        '_seq': STORE.next_seq(),
    }
    STORE.sound_slots[slot['id']] = slot
    return success_object(sound_slot_json(slot), status=201)


@bp.route('/events/<event_id>/sound-slots', methods=['GET'])
def list_sound_slots(event_id):
    require_roles('Organizer', 'RegistrationDesk', 'Participant', 'Judge', 'Vendor')
    _get_event_or_404(event_id)
    limit, offset = get_pagination()
    from flask import request
    status_filter = request.args.get('status')
    items = domain.sorted_created(domain.sound_slots_of_event(event_id))
    if status_filter:
        items = [s for s in items if s['status'] == status_filter]
    page, total = paginate(items, limit, offset)
    return success_list([sound_slot_json(s) for s in page], limit, offset, total)


@bp.route('/sound-slots/<slot_id>/cancel', methods=['POST'])
def cancel_sound_slot(slot_id):
    require_roles('Organizer')
    slot = STORE.sound_slots.get(slot_id)
    if slot is None:
        raise_err(('ERR_NOT_FOUND', 404), 'Sound slot not found')
    if slot['status'] != 'SCHEDULED':
        raise_err(('ERR_INVALID_EVENT_STATE', 409),
                  'Only a SCHEDULED slot can be cancelled')
    slot['status'] = 'CANCELLED'
    domain.touch_entity(slot)
    return success_object(sound_slot_json(slot))


# ---------------------------------------------------------------------------
# Noise readings (PRD 3.8)
# ---------------------------------------------------------------------------

@bp.route('/events/<event_id>/noise-readings', methods=['POST'])
def create_noise_reading(event_id):
    require_roles('Organizer', 'RegistrationDesk')
    ev = _get_event_or_404(event_id)
    data = body()
    reading_db = get_field(data, 'reading_db', type_=(int, float))
    if not reading_db > 0:
        raise_err(('ERR_VALIDATION', 400), 'reading_db must be > 0')
    source = get_enum(data, 'source', NOISE_SOURCES)
    recorded_at = get_field(data, 'recorded_at', required=False, default=None)
    if recorded_at is not None:
        parse_dt(recorded_at, 'recorded_at')
    else:
        recorded_at = CLOCK.now()
    is_curfew, limit_db, is_exceedance = calculations.evaluate_noise_reading(
        ev, reading_db, recorded_at)
    reading = {
        'id': new_id(),
        'event_id': event_id,
        'recorded_at': recorded_at,
        'reading_db': reading_db,
        'source': source,
        'is_curfew': is_curfew,
        'limit_db': limit_db,
        'is_exceedance': is_exceedance,
        'created_at': now_iso(),
        '_seq': STORE.next_seq(),
    }
    STORE.noise_readings[reading['id']] = reading
    if is_exceedance:
        calculations.maybe_suspend_permit(ev)
    return success_object(noise_reading_json(reading), status=201)


@bp.route('/events/<event_id>/noise-readings', methods=['GET'])
def list_noise_readings(event_id):
    require_roles('Organizer', 'RegistrationDesk')
    _get_event_or_404(event_id)
    limit, offset = get_pagination()
    from flask import request
    ex_filter = request.args.get('is_exceedance')
    items = domain.sorted_created([r for r in STORE.noise_readings.values()
                                   if r['event_id'] == event_id])
    if ex_filter is not None and ex_filter != '':
        want = ex_filter.lower() in ('true', '1', 'yes')
        items = [r for r in items if r['is_exceedance'] == want]
    page, total = paginate(items, limit, offset)
    return success_list([noise_reading_json(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Logical clock (test-driving)
# ---------------------------------------------------------------------------

@bp.route('/_clock/set_current_utc', methods=['POST'])
def set_clock():
    require_roles('Organizer')
    data = body()
    to_iso = get_field(data, 'to_iso8601', type_=str)
    parse_dt(to_iso, 'to_iso8601')
    CLOCK.set(to_iso)
    domain.complete_elapsed_sound_slots()
    return success_object({'current_utc': CLOCK.now()})
