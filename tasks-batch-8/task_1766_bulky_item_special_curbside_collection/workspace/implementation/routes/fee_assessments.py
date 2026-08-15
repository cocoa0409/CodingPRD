"""FeeAssessment endpoints (PRD 3.5)."""
from flask import Blueprint, request as freq

import db
import response
import serializers
from errors import (ApiError, ERR_ASSESSMENT_NOT_SETTLABLE, ERR_INVALID_STATE,
                    ERR_NOT_FOUND)
from middleware import require_own_household, require_roles
from services import calc

bp = Blueprint('fee_assessments', __name__)


def _get_assessment(aid):
    a = db.assessments.get(aid)
    if a is None:
        raise ApiError(ERR_NOT_FOUND, f'FeeAssessment {aid} not found', 404)
    return a


@bp.route('/curbside/fee-assessments/<aid>', methods=['GET'])
def get_assessment(aid):
    uid, role = require_roles('Dispatcher', 'Inspector', 'Resident')
    a = _get_assessment(aid)
    if role == 'Resident':
        require_own_household(uid, a['household_id'])
    return response.ok(serializers.fee_assessment(a))


@bp.route('/curbside/fee-assessments', methods=['GET'])
def list_assessments():
    require_roles('Dispatcher', 'Inspector')
    kind = freq.args.get('kind')
    status = freq.args.get('status')
    rows = list(db.assessments.values())
    if kind is not None:
        rows = [a for a in rows if a['kind'] == kind]
    if status is not None:
        rows = [a for a in rows if a['status'] == status]
    rows.sort(key=lambda a: a['created_at'])
    page, total, limit, offset = response.paginate(rows)
    return response.ok_list([serializers.fee_assessment(a) for a in page], total, limit, offset)


@bp.route('/curbside/fee-assessments/<aid>/settle', methods=['POST'])
def settle_assessment(aid):
    uid, role = require_roles('Resident')
    a = _get_assessment(aid)
    # PRD 3.5 / validations priority 13: non-PENDING or non-owning Resident both
    # surface ERR_ASSESSMENT_NOT_SETTLABLE (409) on this endpoint specifically.
    if a['status'] != 'PENDING' or uid != a['household_id']:
        raise ApiError(ERR_ASSESSMENT_NOT_SETTLABLE,
                       'Settle requires a PENDING assessment owned by the acting Resident', 409)
    a['status'] = 'SETTLED'
    a['settled_at'] = db.get_clock()
    calc.touch(a)
    return response.ok(serializers.fee_assessment(a))


@bp.route('/curbside/fee-assessments/<aid>/waive', methods=['POST'])
def waive_assessment(aid):
    require_roles('Dispatcher')
    a = _get_assessment(aid)
    if a['status'] != 'PENDING':
        raise ApiError(ERR_INVALID_STATE, 'Only a PENDING assessment may be waived', 409)
    a['status'] = 'WAIVED'
    a['settled_at'] = db.get_clock()
    calc.touch(a)
    return response.ok(serializers.fee_assessment(a))
