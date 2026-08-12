"""Disposition orders, health inspections and drug-free affidavits."""
from flask import Blueprint, request

import errors
import services
from db import store, new_record, touch
from middleware import require_roles, authenticate
from response import success_object, success_list
from util import (
    body, require, require_str, require_enum, optional_dt,
    pagination_params, sorted_created, apply_filters,
    DISPOSITION_TYPES, INSPECTION_RESULTS,
)
from views import disposition_view, health_inspection_view, affidavit_view

bp = Blueprint('compliance', __name__)

DISQUALIFIABLE = ('VERIFIED', 'WEIGHED', 'CLASSIFIED', 'SHOWN', 'NOT_SOLD')


def get_disposition_or_404(order_id):
    d = store.dispositions.get(order_id)
    if d is None:
        raise errors.not_found('DispositionOrder not found')
    return d


def check_type_compatible(disposition_type, entry_status):
    """ERR_DISPOSITION_NOT_ALLOWED when incompatible with the CURRENT status."""
    if disposition_type == 'HARVEST':
        allowed = entry_status in ('SOLD', 'NOT_SOLD')
    else:  # RETURN
        allowed = entry_status in ('SHOWN', 'NOT_SOLD', 'DISQUALIFIED')
    if not allowed:
        raise errors.err('ERR_DISPOSITION_NOT_ALLOWED', 409,
                         'Disposition type is incompatible with the entry status')


# ------------------------------------------------------------- Dispositions

@bp.post('/v1/dispositions')
def create_disposition():
    user_id, role = require_roles('FairBoardAdmin', 'Exhibitor')
    b = body()
    entry_id = require(b, 'entry_id')
    entry = store.entries.get(entry_id)
    if entry is None:
        raise errors.not_found('AnimalEntry not found')
    if role == 'Exhibitor' and entry['exhibitor_id'] != user_id:
        raise errors.forbidden('Exhibitors may request dispositions only for own entries')
    disposition_type = require_enum(b, 'disposition_type', DISPOSITION_TYPES)
    destination = b.get('destination')
    if destination is not None and not isinstance(destination, str):
        raise errors.invalid_request('destination must be a string')
    scheduled_date = optional_dt(b, 'scheduled_date')
    # Type compatibility is enforced at request time against current status.
    check_type_compatible(disposition_type, entry['status'])

    order = new_record({
        'entry_id': entry_id,
        'disposition_type': disposition_type,
        'destination': destination,
        'scheduled_date': scheduled_date,
        'status': 'REQUESTED',
        'created_by_user_id': user_id,
        'approved_by_user_id': None,
        'reject_reason': None,
    })
    store.dispositions[order['id']] = order
    return success_object(disposition_view(order), status=201)


@bp.get('/v1/dispositions/<orderId>')
def get_disposition(orderId):
    authenticate()
    return success_object(disposition_view(get_disposition_or_404(orderId)))


@bp.get('/v1/dispositions')
def list_dispositions():
    authenticate()
    limit, offset = pagination_params()
    recs = apply_filters(store.dispositions.values(), {
        'entry_id': request.args.get('entry_id'),
        'status': request.args.get('status'),
    })
    return success_list([disposition_view(d) for d in sorted_created(recs)], limit, offset)


@bp.post('/v1/dispositions/<orderId>/approve')
def approve_disposition(orderId):
    user_id, _ = require_roles('FairBoardAdmin')
    order = get_disposition_or_404(orderId)
    if order['status'] != 'REQUESTED':
        raise errors.invalid_state('Only a REQUESTED order can be approved')
    entry = store.entries[order['entry_id']]
    # Checker ladder: affidavit, then segregation of duties, then type.
    if services.signed_affidavit(entry['id']) is None:
        raise errors.err('ERR_AFFIDAVIT_MISSING', 409,
                         'Entry has no SIGNED affidavit')
    if order['created_by_user_id'] != 'SYSTEM' and user_id == order['created_by_user_id']:
        raise errors.segregation('Approver must differ from the order creator')
    check_type_compatible(order['disposition_type'], entry['status'])
    order['status'] = 'APPROVED'
    order['approved_by_user_id'] = user_id
    touch(order)
    return success_object(disposition_view(order))


@bp.post('/v1/dispositions/<orderId>/reject')
def reject_disposition(orderId):
    require_roles('FairBoardAdmin')
    order = get_disposition_or_404(orderId)
    if order['status'] != 'REQUESTED':
        raise errors.invalid_state('Only a REQUESTED order can be rejected')
    b = body()
    reason = require_str(b, 'reason')
    order['status'] = 'REJECTED'
    order['reject_reason'] = reason
    touch(order)
    return success_object(disposition_view(order))


@bp.post('/v1/dispositions/<orderId>/complete')
def complete_disposition(orderId):
    require_roles('FairBoardAdmin')
    order = get_disposition_or_404(orderId)
    if order['status'] != 'APPROVED':
        raise errors.invalid_state('Only an APPROVED order can be completed')
    entry = store.entries[order['entry_id']]
    now = store.logical_now

    # Gate 1: latest health inspection exists and is PASS.
    latest = services.latest_inspection(entry['id'])
    if latest is None or latest['result'] != 'PASS':
        raise errors.err('ERR_HEALTH_HOLD', 409,
                         'Disposition completion requires a latest inspection of PASS')
    # Gate 2 (HARVEST only): withdrawal clearance against the logical clock.
    if order['disposition_type'] == 'HARVEST':
        affidavit = services.affidavit_of_entry(entry['id'])
        wed = affidavit.get('withdrawal_end_date') if affidavit else None
        if wed is not None and now < wed:
            raise errors.err('ERR_WITHDRAWAL_NOT_CLEARED', 409,
                             'Drug withdrawal period has not ended')
    # Gate 3: scheduled movement date against the logical clock.
    if order['scheduled_date'] is not None and now < order['scheduled_date']:
        raise errors.err('ERR_DISPOSITION_TOO_EARLY', 409,
                         'Disposition cannot complete before its scheduled_date')
    # Gate 4: type still compatible with the entry's CURRENT status.
    check_type_compatible(order['disposition_type'], entry['status'])

    order['status'] = 'COMPLETED'
    touch(order)
    if entry['status'] in ('SOLD', 'NOT_SOLD'):
        entry['status'] = 'CLEARED'
        touch(entry)
    return success_object(disposition_view(order))


# --------------------------------------------------------- Health inspections

@bp.post('/v1/health-inspections')
def create_health_inspection():
    require_roles('HealthInspector')
    b = body()
    entry_id = require(b, 'entry_id')
    entry = store.entries.get(entry_id)
    if entry is None:
        raise errors.not_found('AnimalEntry not found')
    result = require_enum(b, 'result', INSPECTION_RESULTS)
    notes = b.get('notes')
    if notes is not None and not isinstance(notes, str):
        raise errors.invalid_request('notes must be a string')
    insp = new_record({
        'entry_id': entry_id,
        'result': result,
        'notes': notes,
    }, common=False)  # immutable record: no updated_at, no version
    store.health_inspections[insp['id']] = insp
    if result == 'FAIL' and entry['status'] in DISQUALIFIABLE:
        services.cascade_disqualify_entry(entry, 'HEALTH_INSPECTION_FAIL')
    return success_object(health_inspection_view(insp), status=201)


@bp.get('/v1/health-inspections/<inspectionId>')
def get_health_inspection(inspectionId):
    authenticate()
    h = store.health_inspections.get(inspectionId)
    if h is None:
        raise errors.not_found('HealthInspection not found')
    return success_object(health_inspection_view(h))


@bp.get('/v1/health-inspections')
def list_health_inspections():
    authenticate()
    limit, offset = pagination_params()
    recs = apply_filters(store.health_inspections.values(), {
        'entry_id': request.args.get('entry_id'),
        'result': request.args.get('result'),
    })
    return success_list([health_inspection_view(h) for h in sorted_created(recs)], limit, offset)


# ------------------------------------------------------------------ Affidavits

@bp.post('/v1/affidavits')
def create_affidavit():
    user_id, role = require_roles('Exhibitor', 'FairBoardAdmin')
    b = body()
    entry_id = require(b, 'entry_id')
    entry = store.entries.get(entry_id)
    if entry is None:
        raise errors.not_found('AnimalEntry not found')
    if role == 'Exhibitor' and entry['exhibitor_id'] != user_id:
        raise errors.forbidden('Exhibitors may sign affidavits only for own entries')
    withdrawal_end = optional_dt(b, 'withdrawal_end_date')
    if services.affidavit_of_entry(entry_id) is not None:
        raise errors.err('ERR_AFFIDAVIT_EXISTS', 409, 'Entry already has an affidavit')

    aff = new_record({
        'entry_id': entry_id,
        'exhibitor_id': entry['exhibitor_id'],
        'signed_at': store.logical_now,  # logical clock, not wall clock
        'withdrawal_end_date': withdrawal_end,
        'status': 'SIGNED',
        'revoked_reason': None,
    })
    store.affidavits[aff['id']] = aff
    return success_object(affidavit_view(aff), status=201)


@bp.get('/v1/affidavits/<affidavitId>')
def get_affidavit(affidavitId):
    authenticate()
    a = store.affidavits.get(affidavitId)
    if a is None:
        raise errors.not_found('Affidavit not found')
    return success_object(affidavit_view(a))


@bp.get('/v1/affidavits')
def list_affidavits():
    authenticate()
    limit, offset = pagination_params()
    recs = apply_filters(store.affidavits.values(), {
        'entry_id': request.args.get('entry_id'),
        'exhibitor_id': request.args.get('exhibitor_id'),
        'status': request.args.get('status'),
    })
    return success_list([affidavit_view(a) for a in sorted_created(recs)], limit, offset)


@bp.post('/v1/affidavits/<affidavitId>/revoke')
def revoke_affidavit(affidavitId):
    require_roles('HealthInspector')
    a = store.affidavits.get(affidavitId)
    if a is None:
        raise errors.not_found('Affidavit not found')
    if a['status'] != 'SIGNED':
        raise errors.invalid_state('Only a SIGNED affidavit can be revoked')
    entry = store.entries[a['entry_id']]
    if entry['status'] in ('SOLD', 'CLEARED', 'REJECTED', 'DISQUALIFIED'):
        raise errors.invalid_state('Affidavit cannot be revoked for this entry state')
    b = body()
    reason = require_str(b, 'reason')
    a['status'] = 'REVOKED'
    a['revoked_reason'] = reason
    touch(a)
    if entry['status'] in DISQUALIFIABLE:
        services.cascade_disqualify_entry(entry, 'AFFIDAVIT_REVOKED')
    return success_object(affidavit_view(a))
