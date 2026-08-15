"""Participant census routes."""
from flask import Blueprint, request

from auth import roles_allowed
from domain import recompute_balance
from envelope import success_list, success_object
from errors import (ERR_DUPLICATE_PARTICIPANT_REF, ERR_INVALID_REQUEST,
                    ERR_NOT_FOUND, raise_err)
from store import base_fields, public, store, touch
from validate import (get_body, opt_enum, paginate, parse_bool_param,
                      parse_pagination, req_bool, req_date, req_int, req_str,
                      sorted_created)

bp = Blueprint('participants', __name__)

PSTATUSES = ('ACTIVE', 'SEPARATED_WITH_BALANCE', 'SEPARATED_NO_BALANCE',
             'RETIRED_WITH_BALANCE', 'DECEASED')


def get_participant_or_404(pid):
    p = store.participants.get(pid)
    if p is None:
        raise_err(ERR_NOT_FOUND, 'Participant %s not found' % pid)
    return p


def _get_engagement(eid):
    eng = store.engagements.get(eid)
    if eng is None:
        raise_err(ERR_NOT_FOUND, 'Engagement %s not found' % eid)
    return eng


def _parse_census_fields(body):
    return {
        'eligibility_date': req_date(body, 'eligibility_date'),
        'entry_date': req_date(body, 'entry_date'),
        'is_eligible': req_bool(body, 'is_eligible'),
        'is_hce': req_bool(body, 'is_hce'),
        'compensation_cy_cents': req_int(body, 'compensation_cy_cents', 0),
        'deferral_amount_cy_cents': req_int(body, 'deferral_amount_cy_cents', 0),
        'opening_balance_cents': req_int(body, 'opening_balance_cents', 0),
    }


def _build_participant(engagement_id, external_ref, vals):
    p = base_fields()
    p.update({
        'engagement_id': engagement_id,
        'external_ref': external_ref,
        'eligibility_date': vals['eligibility_date'].isoformat(),
        'entry_date': vals['entry_date'].isoformat(),
        'status': vals.get('status', 'ACTIVE'),
        'is_eligible': vals['is_eligible'],
        'is_hce': vals['is_hce'],
        'compensation_cy_cents': vals['compensation_cy_cents'],
        'deferral_amount_cy_cents': vals['deferral_amount_cy_cents'],
        'opening_balance_cents': vals['opening_balance_cents'],
    })
    recompute_balance(p)
    return p


@bp.route('/plan-audit/participants', methods=['POST'])
@roles_allowed('SponsorAdmin')
def create_participant():
    body = get_body()
    engagement_id = req_str(body, 'engagement_id')
    external_ref = req_str(body, 'external_ref')
    vals = _parse_census_fields(body)
    vals['status'] = opt_enum(body, 'status', PSTATUSES, 'ACTIVE')
    _get_engagement(engagement_id)
    for p in store.participants.values():
        if p['engagement_id'] == engagement_id and p['external_ref'] == external_ref:
            raise_err(ERR_DUPLICATE_PARTICIPANT_REF,
                      'external_ref %s already exists in this engagement' % external_ref)
    p = _build_participant(engagement_id, external_ref, vals)
    store.participants[p['id']] = p
    return success_object(public(p), status=201)


@bp.route('/plan-audit/participants/bulk-import', methods=['POST'])
@roles_allowed('SponsorAdmin')
def bulk_import():
    body = get_body()
    engagement_id = req_str(body, 'engagement_id')
    count = req_int(body, 'count', 1)
    prefix = req_str(body, 'external_ref_prefix')
    template = body.get('template')
    if not isinstance(template, dict):
        raise_err(ERR_INVALID_REQUEST, 'template must be an object')
    vals = _parse_census_fields(template)
    vals['status'] = opt_enum(template, 'status', PSTATUSES, 'ACTIVE')
    _get_engagement(engagement_id)
    # Atomic: validate every generated ref before persisting any participant.
    refs = ['%s-%03d' % (prefix, i) for i in range(1, count + 1)]
    existing = {p['external_ref'] for p in store.participants.values()
                if p['engagement_id'] == engagement_id}
    for ref in refs:
        if ref in existing:
            raise_err(ERR_DUPLICATE_PARTICIPANT_REF,
                      'external_ref %s already exists in this engagement' % ref)
    created = []
    for ref in refs:
        p = _build_participant(engagement_id, ref, vals)
        store.participants[p['id']] = p
        created.append(p)
    return success_list([public(p) for p in created], len(created),
                        len(created) or 10, 0, status=201)


@bp.route('/plan-audit/participants', methods=['GET'])
@roles_allowed('Any')
def list_participants():
    limit, offset = parse_pagination()
    items = sorted_created(store.participants.values())
    engagement_id = request.args.get('engagement_id')
    status = request.args.get('status')
    is_hce = parse_bool_param('is_hce')
    is_eligible = parse_bool_param('is_eligible')
    if engagement_id is not None:
        items = [p for p in items if p['engagement_id'] == engagement_id]
    if status is not None:
        items = [p for p in items if p['status'] == status]
    if is_hce is not None:
        items = [p for p in items if p['is_hce'] == is_hce]
    if is_eligible is not None:
        items = [p for p in items if p['is_eligible'] == is_eligible]
    page, total = paginate(items, limit, offset)
    return success_list([public(p) for p in page], total, limit, offset)


@bp.route('/plan-audit/participants/<pid>', methods=['GET'])
@roles_allowed('Any')
def get_participant(pid):
    return success_object(public(get_participant_or_404(pid)))


@bp.route('/plan-audit/participants/<pid>', methods=['PATCH'])
@roles_allowed('SponsorAdmin')
def patch_participant(pid):
    p = get_participant_or_404(pid)
    body = get_body()
    if 'status' in body:
        p['status'] = opt_enum(body, 'status', PSTATUSES, p['status'])
    if 'is_eligible' in body:
        p['is_eligible'] = req_bool(body, 'is_eligible')
    if 'is_hce' in body:
        p['is_hce'] = req_bool(body, 'is_hce')
    if 'compensation_cy_cents' in body:
        p['compensation_cy_cents'] = req_int(body, 'compensation_cy_cents', 0)
    if 'deferral_amount_cy_cents' in body:
        p['deferral_amount_cy_cents'] = req_int(body, 'deferral_amount_cy_cents', 0)
    if 'opening_balance_cents' in body:
        p['opening_balance_cents'] = req_int(body, 'opening_balance_cents', 0)
    recompute_balance(p)
    touch(p)
    return success_object(public(p))
