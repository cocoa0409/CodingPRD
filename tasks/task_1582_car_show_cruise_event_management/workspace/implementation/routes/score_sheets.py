"""Score sheet routes: create (DRAFT), submit, reopen, list/get."""
from flask import Blueprint, request

from db import STORE, new_id, now_iso, CLOCK
from errors import raise_err
from middleware import require_roles, check_judge_owns
from response import success_object, success_list
from util import body, get_field, get_pagination, paginate, parse_dt
from services import domain, calculations
from services.serializers import score_sheet_json

bp = Blueprint('score_sheets', __name__)

CRITERIA_SET = set(calculations.CRITERIA)


def _validate_criteria_scores(data):
    scores = get_field(data, 'criteria_scores', type_=list)
    if len(scores) != 5:
        raise_err(('ERR_VALIDATION', 400),
                  'criteria_scores must contain exactly five items')
    seen = set()
    for item in scores:
        if not isinstance(item, dict):
            raise_err(('ERR_VALIDATION', 400), 'Each criteria_scores item must be an object')
        criterion = item.get('criterion')
        points = item.get('points')
        if criterion not in CRITERIA_SET:
            raise_err(('ERR_VALIDATION', 400),
                      'criterion must be one of EXTERIOR, INTERIOR, ENGINE, AUTHENTICITY, CONDITION')
        if criterion in seen:
            raise_err(('ERR_VALIDATION', 400), 'Duplicate criterion in criteria_scores')
        seen.add(criterion)
        if not isinstance(points, int) or isinstance(points, bool) \
                or not (0 <= points <= 10):
            raise_err(('ERR_VALIDATION', 400),
                      'points must be an integer from 0 to 10')
    if seen != CRITERIA_SET:
        raise_err(('ERR_VALIDATION', 400),
                  'criteria_scores must cover all five criteria')
    return [{'criterion': i['criterion'], 'points': i['points']} for i in scores]


def _in_judging_window(ev):
    now = parse_dt(CLOCK.now())
    return parse_dt(ev['judging_start_at']) <= now < parse_dt(ev['judging_end_at'])


def _event_for_sheet(sheet):
    reg = STORE.registrations.get(sheet['registration_id'])
    if reg is None:
        return None
    return STORE.events.get(reg['event_id'])


@bp.route('/score-sheets', methods=['POST'])
def create_score_sheet():
    user_id, role = require_roles('Judge')
    data = body()
    registration_id = get_field(data, 'registration_id', type_=str)
    criteria_scores = _validate_criteria_scores(data)

    reg = STORE.registrations.get(registration_id)
    if reg is None:
        raise_err(('ERR_NOT_FOUND', 404), 'Registration not found')
    ev = STORE.events[reg['event_id']]

    # The acting judge (X-User-ID is the Judge entity id)
    judge = STORE.judges.get(user_id)
    if judge is None or judge['event_id'] != ev['id']:
        raise_err(('ERR_NOT_FOUND', 404), 'Judge not found for this event')
    if reg['status'] != 'CHECKED_IN':
        raise_err(('ERR_INVALID_REGISTRATION_STATE', 409),
                  'Score sheets may be created only for CHECKED_IN registrations')
    if ev['lifecycle_status'] != 'JUDGING':
        raise_err(('ERR_INVALID_EVENT_STATE', 409),
                  'Score sheets may be created only while the event is JUDGING')
    # Temporal before constraint (PRD 2.9: level 8 above level 9)
    if not _in_judging_window(ev):
        raise_err(('ERR_JUDGING_WINDOW_CLOSED', 422),
                  'Outside the judging window')
    if reg['class_id'] not in (judge.get('assigned_class_ids') or []):
        raise_err(('ERR_JUDGE_NOT_ASSIGNED', 422),
                  'Judge is not assigned to this class')
    for s in STORE.score_sheets.values():
        if s['judge_id'] == judge['id'] and s['registration_id'] == registration_id:
            raise_err(('ERR_DUPLICATE_SCORE_SHEET', 409),
                      'Judge already has a score sheet for this registration')
    # Conflict of interest: judge email matches a registrant with a non-terminal
    # registration in the same class
    for other in STORE.registrations.values():
        if other['class_id'] == reg['class_id'] and \
                other['status'] in domain.NON_TERMINAL_REG_STATUSES:
            otr = STORE.registrants.get(other['registrant_id'])
            if otr is not None and otr['email'] == judge['email']:
                raise_err(('ERR_JUDGE_CONFLICT_OF_INTEREST', 422),
                          'Judge competes in this class')

    sheet_total = calculations.compute_sheet_total(criteria_scores)
    now = now_iso()
    sheet = {
        'id': new_id(),
        'judge_id': judge['id'],
        'registration_id': registration_id,
        'criteria_scores': criteria_scores,
        'sheet_total': sheet_total,
        'status': 'DRAFT',
        'submitted_at': None,
        'created_at': now,
        'updated_at': now,
        'version': 1,
        '_seq': STORE.next_seq(),
    }
    STORE.score_sheets[sheet['id']] = sheet
    return success_object(score_sheet_json(sheet), status=201)


@bp.route('/score-sheets', methods=['GET'])
def list_score_sheets():
    user_id, role = require_roles('Judge', 'Organizer')
    limit, offset = get_pagination()
    items = domain.sorted_created(list(STORE.score_sheets.values()))
    if role == 'Judge':
        items = [s for s in items if s['judge_id'] == user_id]
    for param in ('judge_id', 'registration_id', 'status'):
        val = request.args.get(param)
        if val:
            items = [s for s in items if str(s.get(param)) == val]
    page, total = paginate(items, limit, offset)
    return success_list([score_sheet_json(s) for s in page], limit, offset, total)


@bp.route('/score-sheets/<sheet_id>', methods=['GET'])
def get_score_sheet(sheet_id):
    user_id, role = require_roles('Judge', 'Organizer')
    sheet = STORE.score_sheets.get(sheet_id)
    if sheet is None:
        raise_err(('ERR_NOT_FOUND', 404), 'Score sheet not found')
    check_judge_owns(user_id, role, sheet['judge_id'])
    return success_object(score_sheet_json(sheet))


@bp.route('/score-sheets/<sheet_id>/submit', methods=['POST'])
def submit_score_sheet(sheet_id):
    user_id, role = require_roles('Judge')
    sheet = STORE.score_sheets.get(sheet_id)
    if sheet is None:
        raise_err(('ERR_NOT_FOUND', 404), 'Score sheet not found')
    check_judge_owns(user_id, role, sheet['judge_id'])
    # Own-state before cross-entity state (PRD 2.9 level 6)
    if sheet['status'] != 'DRAFT':
        raise_err(('ERR_INVALID_SCORE_SHEET_STATE', 409),
                  'Only a DRAFT sheet can be submitted')
    ev = _event_for_sheet(sheet)
    if ev is None or ev['lifecycle_status'] != 'JUDGING':
        raise_err(('ERR_INVALID_EVENT_STATE', 409), 'Event is not in JUDGING')
    # Temporal before assignment constraint (PRD 3.5)
    if not _in_judging_window(ev):
        raise_err(('ERR_JUDGING_WINDOW_CLOSED', 422),
                  'Outside the judging window')
    reg = STORE.registrations[sheet['registration_id']]
    judge = STORE.judges.get(sheet['judge_id'])
    if judge is None or reg['class_id'] not in (judge.get('assigned_class_ids') or []):
        raise_err(('ERR_JUDGE_NOT_ASSIGNED', 422),
                  'Judge is not assigned to this class')

    sheet['status'] = 'SUBMITTED'
    if sheet['submitted_at'] is None:
        sheet['submitted_at'] = CLOCK.now()
    domain.touch_entity(sheet)
    # Class completion bubble-up: may auto-advance event and lock sheets
    domain.maybe_auto_advance_to_tabulating(ev)
    # Re-read sheet in case the lock cascade flipped it
    sheet = STORE.score_sheets[sheet_id]
    return success_object(score_sheet_json(sheet))


@bp.route('/score-sheets/<sheet_id>/reopen', methods=['POST'])
def reopen_score_sheet(sheet_id):
    require_roles('Organizer')
    sheet = STORE.score_sheets.get(sheet_id)
    if sheet is None:
        raise_err(('ERR_NOT_FOUND', 404), 'Score sheet not found')
    body()  # optional reason
    # Own-state before cross-entity state
    if sheet['status'] != 'SUBMITTED':
        raise_err(('ERR_INVALID_SCORE_SHEET_STATE', 409),
                  'Only a SUBMITTED sheet can be reopened')
    ev = _event_for_sheet(sheet)
    if ev is None or ev['lifecycle_status'] != 'JUDGING':
        raise_err(('ERR_INVALID_EVENT_STATE', 409),
                  'Sheets may be reopened only while the event is JUDGING')
    sheet['status'] = 'DRAFT'
    domain.touch_entity(sheet)
    return success_object(score_sheet_json(sheet))
