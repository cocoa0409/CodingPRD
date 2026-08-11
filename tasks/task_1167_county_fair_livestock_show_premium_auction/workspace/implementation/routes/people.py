"""Exhibitor, Judge and Buyer registration/read endpoints."""
from flask import Blueprint

import errors
from db import store, new_record, touch
from middleware import require_roles, authenticate
from response import success_object, success_list
from util import (
    body, require, require_int, require_str, require_enum,
    pagination_params, sorted_created, apply_filters,
    ORGANIZATIONS, SPECIES,
)
from views import exhibitor_view, judge_view, buyer_view

bp = Blueprint('people', __name__)


def get_fair_or_404(fair_id):
    fair = store.fairs.get(fair_id)
    if fair is None:
        raise errors.not_found('Fair not found')
    return fair


# ---------------------------------------------------------------- Exhibitors

@bp.post('/v1/exhibitors')
def create_exhibitor():
    require_roles('FairBoardAdmin')
    b = body()
    fair_id = require(b, 'fair_id')
    get_fair_or_404(fair_id)
    full_name = require_str(b, 'full_name')
    organization = require_enum(b, 'organization', ORGANIZATIONS)
    ex = new_record({
        'fair_id': fair_id,
        'full_name': full_name,
        'organization': organization,
        'status': 'ACTIVE',
    })
    store.exhibitors[ex['id']] = ex
    return success_object(exhibitor_view(ex), status=201)


def get_exhibitor_or_404(exhibitor_id):
    ex = store.exhibitors.get(exhibitor_id)
    if ex is None:
        raise errors.not_found('Exhibitor not found')
    return ex


@bp.get('/v1/exhibitors/<exhibitorId>')
def get_exhibitor(exhibitorId):
    authenticate()
    return success_object(exhibitor_view(get_exhibitor_or_404(exhibitorId)))


@bp.get('/v1/exhibitors')
def list_exhibitors():
    authenticate()
    limit, offset = pagination_params()
    recs = apply_filters(store.exhibitors.values(), {
        'fair_id': request_arg('fair_id'),
        'status': request_arg('status'),
    })
    return success_list([exhibitor_view(e) for e in sorted_created(recs)], limit, offset)


@bp.post('/v1/exhibitors/<exhibitorId>/suspend')
def suspend_exhibitor(exhibitorId):
    require_roles('FairBoardAdmin')
    ex = get_exhibitor_or_404(exhibitorId)
    if ex['status'] != 'ACTIVE':
        raise errors.invalid_state('Only an ACTIVE exhibitor can be suspended')
    ex['status'] = 'SUSPENDED'
    touch(ex)
    return success_object(exhibitor_view(ex))


# --------------------------------------------------------------------- Judges

@bp.post('/v1/judges')
def create_judge():
    require_roles('FairBoardAdmin')
    b = body()
    fair_id = require(b, 'fair_id')
    get_fair_or_404(fair_id)
    full_name = require_str(b, 'full_name')
    qualified = require(b, 'qualified_species')
    if (not isinstance(qualified, list) or not qualified
            or any(s not in SPECIES for s in qualified)):
        raise errors.invalid_request('qualified_species must be a non-empty list of species enums')
    judge = new_record({
        'fair_id': fair_id,
        'full_name': full_name,
        'qualified_species': list(qualified),
    })
    store.judges[judge['id']] = judge
    return success_object(judge_view(judge), status=201)


def get_judge_or_404(judge_id):
    j = store.judges.get(judge_id)
    if j is None:
        raise errors.not_found('Judge not found')
    return j


@bp.get('/v1/judges/<judgeId>')
def get_judge(judgeId):
    authenticate()
    return success_object(judge_view(get_judge_or_404(judgeId)))


@bp.get('/v1/judges')
def list_judges():
    authenticate()
    limit, offset = pagination_params()
    recs = apply_filters(store.judges.values(), {'fair_id': request_arg('fair_id')})
    return success_list([judge_view(j) for j in sorted_created(recs)], limit, offset)


# --------------------------------------------------------------------- Buyers

@bp.post('/v1/buyers')
def create_buyer():
    require_roles('FairBoardAdmin')
    b = body()
    fair_id = require(b, 'fair_id')
    get_fair_or_404(fair_id)
    business_name = require_str(b, 'business_name')
    credit_limit = require_int(b, 'credit_limit_cents', minimum=0)
    # bidder_number: B-<zero-padded 3-digit sequence> per fair, created_at ASC.
    seq_no = sum(1 for x in store.buyers.values() if x['fair_id'] == fair_id) + 1
    buyer = new_record({
        'fair_id': fair_id,
        'business_name': business_name,
        'bidder_number': f'B-{seq_no:03d}',
        'credit_limit_cents': credit_limit,
    })
    store.buyers[buyer['id']] = buyer
    return success_object(buyer_view(buyer), status=201)


def get_buyer_or_404(buyer_id):
    by = store.buyers.get(buyer_id)
    if by is None:
        raise errors.not_found('Buyer not found')
    return by


@bp.get('/v1/buyers/<buyerId>')
def get_buyer(buyerId):
    authenticate()
    return success_object(buyer_view(get_buyer_or_404(buyerId)))


@bp.get('/v1/buyers')
def list_buyers():
    authenticate()
    limit, offset = pagination_params()
    recs = apply_filters(store.buyers.values(), {'fair_id': request_arg('fair_id')})
    return success_list([buyer_view(x) for x in sorted_created(recs)], limit, offset)


def request_arg(name):
    from flask import request
    return request.args.get(name)
