"""DumpingReport endpoints (PRD 3.6): filing and Inspector determination cascade."""
from flask import Blueprint, request as freq

import db
import response
import serializers
from errors import (ApiError, ERR_DETERMINATION_INCONSISTENT, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_NOT_FOUND)
from middleware import body_json, require_roles
from services import calc

bp = Blueprint('dumping_reports', __name__)

DETERMINATIONS = {'AUTHORIZED_SETOUT', 'ILLEGAL_DUMPING', 'DISMISSED'}


def _get_report(rid):
    r = db.reports.get(rid)
    if r is None:
        raise ApiError(ERR_NOT_FOUND, f'DumpingReport {rid} not found', 404)
    return r


@bp.route('/curbside/dumping-reports', methods=['POST'])
def create_report():
    require_roles('Inspector', 'Driver')
    body = body_json()
    household_id = body.get('household_id')
    pickup_request_id = body.get('pickup_request_id')
    if not isinstance(household_id, str) or not household_id:
        raise ApiError(ERR_INVALID_REQUEST, 'household_id is required', 400)
    if household_id not in db.households:
        raise ApiError(ERR_NOT_FOUND, f'Household {household_id} not found', 404)
    if pickup_request_id is not None:
        if not isinstance(pickup_request_id, str) or pickup_request_id not in db.pickup_requests:
            raise ApiError(ERR_NOT_FOUND, f'PickupRequest {pickup_request_id} not found', 404)
    now = db.wall_now()
    r = {
        'id': db.new_id(),
        'household_id': household_id,
        'pickup_request_id': pickup_request_id,
        'reported_at': db.get_clock(),
        'status': 'OPEN',
        'determination_notes': None,
        'created_at': now,
        'updated_at': now,
        'version': 1,
    }
    db.reports[r['id']] = r
    return response.ok(serializers.dumping_report(r), status=201)


@bp.route('/curbside/dumping-reports/<rid>', methods=['GET'])
def get_report(rid):
    require_roles('Dispatcher', 'Inspector')
    return response.ok(serializers.dumping_report(_get_report(rid)))


@bp.route('/curbside/dumping-reports', methods=['GET'])
def list_reports():
    require_roles('Dispatcher', 'Inspector')
    household_id = freq.args.get('household_id')
    status = freq.args.get('status')
    rows = list(db.reports.values())
    if household_id is not None:
        rows = [r for r in rows if r['household_id'] == household_id]
    if status is not None:
        rows = [r for r in rows if r['status'] == status]
    rows.sort(key=lambda r: r['created_at'])
    page, total, limit, offset = response.paginate(rows)
    return response.ok_list([serializers.dumping_report(r) for r in page], total, limit, offset)


@bp.route('/curbside/dumping-reports/<rid>/determine', methods=['POST'])
def determine_report(rid):
    require_roles('Inspector')
    r = _get_report(rid)
    if r['status'] != 'OPEN':
        raise ApiError(ERR_INVALID_STATE, 'DumpingReport is not OPEN', 409)
    body = body_json()
    determination = body.get('determination')
    notes = body.get('determination_notes')
    if determination not in DETERMINATIONS:
        raise ApiError(ERR_INVALID_REQUEST,
                       'determination must be AUTHORIZED_SETOUT, ILLEGAL_DUMPING, or DISMISSED', 400)
    qualifying = calc.qualifying_scheduled_link(r)
    if determination == 'AUTHORIZED_SETOUT' and not qualifying:
        raise ApiError(ERR_DETERMINATION_INCONSISTENT,
                       'AUTHORIZED_SETOUT requires a linked SCHEDULED request within +/-1 day', 422)
    if determination == 'ILLEGAL_DUMPING' and qualifying:
        raise ApiError(ERR_DETERMINATION_INCONSISTENT,
                       'ILLEGAL_DUMPING requires the absence of a qualifying scheduled link', 422)
    # ---- side effects ----
    linked = db.pickup_requests.get(r['pickup_request_id']) if r['pickup_request_id'] else None
    if determination == 'AUTHORIZED_SETOUT':
        r['status'] = 'DETERMINED_AUTHORIZED'
        if linked is not None:
            linked['setout_classification'] = 'AUTHORIZED_SETOUT'
            calc.touch(linked)
    elif determination == 'ILLEGAL_DUMPING':
        r['status'] = 'DETERMINED_ILLEGAL'
        amount = calc.illegal_dumping_fine_amount(r)
        calc.create_assessment(r['pickup_request_id'], r['household_id'],
                               'ILLEGAL_DUMPING_FINE', amount)
        household = db.households.get(r['household_id'])
        if household is not None and household['status'] == 'ACTIVE':
            household['status'] = 'SUSPENDED'
            household['suspension_reason'] = 'ILLEGAL_DUMPING'
            calc.touch(household)
        if linked is not None:
            linked['setout_classification'] = 'ILLEGAL_DUMPING'
            calc.touch(linked)
            calc.emit_notification(
                linked['id'], 'ILLEGAL_DUMPING_WARNING', None,
                'Illegal dumping determined for the set-out associated with this pickup request.')
    else:  # DISMISSED
        r['status'] = 'DISMISSED'
    r['determination_notes'] = notes
    calc.touch(r)
    return response.ok(serializers.dumping_report(r))
