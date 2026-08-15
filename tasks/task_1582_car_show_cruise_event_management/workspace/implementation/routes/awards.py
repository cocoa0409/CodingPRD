"""Award routes: list/get, override-winner (OCC + segregation of duties), present."""
from flask import Blueprint, request

from db import STORE
from errors import raise_err
from middleware import require_roles
from response import success_object, success_list
from util import body, get_field, get_pagination, paginate
from services import domain
from services.serializers import award_json

bp = Blueprint('awards', __name__)


def _get_award_or_404(award_id):
    award = STORE.awards.get(award_id)
    if award is None:
        raise_err(('ERR_NOT_FOUND', 404), 'Award not found')
    return award


@bp.route('/awards', methods=['GET'])
def list_awards():
    require_roles('Organizer', 'RegistrationDesk', 'Participant', 'Judge', 'Vendor')
    limit, offset = get_pagination()
    items = domain.sorted_created(list(STORE.awards.values()))
    for param in ('event_id', 'class_id', 'winner_registration_id', 'status'):
        val = request.args.get(param)
        if val:
            items = [a for a in items if str(a.get(param)) == val]
    page, total = paginate(items, limit, offset)
    return success_list([award_json(a) for a in page], limit, offset, total)


@bp.route('/awards/<award_id>', methods=['GET'])
def get_award(award_id):
    require_roles('Organizer', 'RegistrationDesk', 'Participant', 'Judge', 'Vendor')
    award = _get_award_or_404(award_id)
    return success_object(award_json(award))


@bp.route('/awards/<award_id>/override-winner', methods=['POST'])
def override_winner(award_id):
    user_id, role = require_roles('Organizer')
    award = _get_award_or_404(award_id)
    data = body()
    winner_registration_id = get_field(data, 'winner_registration_id', type_=str)
    expected_award_version = get_field(data, 'expected_award_version', type_=int)
    get_field(data, 'reason', required=False, default=None)

    # State precondition (own state, then OCC)
    if award['status'] not in ('COMPUTED', 'FINALIZED'):
        raise_err(('ERR_INVALID_AWARD_STATE', 409),
                  'Only a COMPUTED or FINALIZED award may be overridden')
    if expected_award_version != award['version']:
        raise_err(('ERR_STALE_VERSION', 412),
                  'expected_award_version does not match the award version')
    ev = STORE.events[award['event_id']]
    if user_id == ev.get('finalized_by_user_id', ''):
        raise_err(('ERR_SEGREGATION_OF_DUTIES', 422),
                  'The finalizing organizer may not override winners')

    # Winner must reference a CHECKED_IN registration in the award's class
    # (BEST_OF_SHOW: any judged class)
    reg = STORE.registrations.get(winner_registration_id)
    valid = False
    if reg is not None and reg['event_id'] == award['event_id'] \
            and reg['status'] == 'CHECKED_IN':
        if award['award_kind'] == 'BEST_OF_SHOW':
            cls = STORE.classes.get(reg['class_id'])
            valid = cls is not None and cls['judging_mode'] in ('JUDGED', 'BOTH')
        else:
            valid = reg['class_id'] == award['class_id']
    if not valid:
        raise_err(('ERR_VALIDATION', 400),
                  'winner_registration_id must reference a CHECKED_IN registration in the award\'s class')

    award['winner_registration_id'] = winner_registration_id
    award['winner_score'] = None
    award['overridden'] = True
    award['tie_break_log'] = 'MANUAL_OVERRIDE'
    award['status'] = 'FINALIZED'
    domain.touch_entity(award)
    return success_object(award_json(award))


@bp.route('/awards/<award_id>/present', methods=['POST'])
def present_award(award_id):
    require_roles('Organizer')
    award = _get_award_or_404(award_id)
    if award['status'] != 'FINALIZED':
        raise_err(('ERR_INVALID_AWARD_STATE', 409),
                  'Only a FINALIZED award may be presented')
    award['status'] = 'PRESENTED'
    domain.touch_entity(award)
    return success_object(award_json(award))
