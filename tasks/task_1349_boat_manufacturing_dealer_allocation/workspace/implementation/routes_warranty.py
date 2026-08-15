"""Warranty: retail registration (36-month coverage, order -> RETAILED) and
claim submission/adjudication with the STANDARD vs RECALL_GOODWILL variants."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from store import (DB, CLOCK, fmt_dt, new_rec, serialize, touch, rhu,
                   add_months, recount_allocation)
from services import remedy_notice
from util import (ApiError, respond, list_response, auth_context, require_roles,
                  json_body, present, need, as_str, as_int, as_num, as_date,
                  invalid, get_or_404)

bp = Blueprint('warranty', __name__)

BASE_LABOR_RATE = Decimal('9000')
TIER1_HOURS = Decimal('2.0')
TIER2_FACTOR = Decimal('0.85')
PARTS_FACTOR = Decimal('0.85')


# ---------------------------------------------------------------- registration
@bp.post('/warranty-registrations')
def create_registration():
    uid, role = auth_context()
    require_roles(role, 'DealerPrincipal')
    data = json_body()
    # family 2: DealerPrincipal registers own dealership's sale
    if present(data, 'dealer_id') and data['dealer_id'] != uid:
        raise ApiError(403, 'ERR_INSUFFICIENT_PERMISSIONS',
                       'dealer_id must equal X-User-ID')
    hull_id = as_str(need(data, 'hull_id'), 'hull_id')
    dealer_id = as_str(need(data, 'dealer_id'), 'dealer_id')
    sale_date = as_date(need(data, 'retail_sale_date'), 'retail_sale_date')
    # family 5: body FK existence
    hull = get_or_404(DB['hulls'], hull_id, 'ERR_HULL_NOT_FOUND', 'Hull')
    get_or_404(DB['dealers'], dealer_id, 'ERR_DEALER_NOT_FOUND', 'Dealer')
    # family 7: only a delivered hull can be retailed
    if hull['delivery_status'] != 'DELIVERED':
        raise ApiError(409, 'ERR_INVALID_HULL_STATE',
                       'Registration requires a delivered hull')
    # family 9: sale not in the future, and no more than 45 days before the
    # clock date (exactly 45 days old still qualifies)
    clock_date = CLOCK.now().date()
    if sale_date > clock_date or sale_date < clock_date - timedelta(days=45):
        raise ApiError(422, 'ERR_REGISTRATION_WINDOW_EXPIRED',
                       'retail_sale_date outside the 45-day window')
    # family 10: one registration per hull; selling dealer must match the
    # delivered order's dealer
    if any(r['hull_id'] == hull_id for r in DB['registrations'].values()):
        raise ApiError(409, 'ERR_DUPLICATE_REGISTRATION',
                       'Hull already has a warranty registration')
    order = DB['orders'][hull['order_id']]
    if dealer_id != order['dealer_id']:
        raise ApiError(422, 'ERR_SELLING_DEALER_MISMATCH',
                       'Registration dealer differs from the order dealer')
    rec = new_rec({
        'hull_id': hull_id,
        'dealer_id': dealer_id,
        'retail_sale_date': sale_date.isoformat(),
        'registered_at': fmt_dt(CLOCK.now()),
        'coverage_end_date': add_months(sale_date, 36).isoformat(),
        'status': 'ACTIVE',
    })
    DB['registrations'][rec['id']] = rec
    # order DELIVERED -> RETAILED; RETAILED exits the allocation pipeline
    order['status'] = 'RETAILED'
    touch(order)
    dealer = DB['dealers'][dealer_id]
    dealer['allocation_used'] = recount_allocation(dealer_id)
    touch(dealer)
    return respond(serialize(rec), 201)


@bp.get('/warranty-registrations')
def list_registrations():
    auth_context()
    items = list(DB['registrations'].values())
    for param in ('hull_id', 'dealer_id'):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r[param] == v]
    return list_response(items, serialize)


@bp.get('/warranty-registrations/<rid>')
def get_registration(rid):
    auth_context()
    rec = get_or_404(DB['registrations'], rid, 'ERR_REGISTRATION_NOT_FOUND',
                     'WarrantyRegistration')
    return respond(serialize(rec), 200)


# ---------------------------------------------------------------- claims
@bp.post('/warranty-claims')
def create_claim():
    uid, role = auth_context()
    require_roles(role, 'DealerPrincipal')
    data = json_body()
    registration_id = as_str(need(data, 'registration_id'), 'registration_id')
    defect = as_str(need(data, 'defect_description'), 'defect_description')
    labor = as_num(need(data, 'labor_hours'), 'labor_hours')
    if labor <= 0:
        invalid('labor_hours must be > 0')
    parts = as_int(need(data, 'parts_cents'), 'parts_cents')
    if parts < 0:
        invalid('parts_cents must be >= 0')
    notice_id = None
    if present(data, 'recall_notice_id'):
        notice_id = as_str(data['recall_notice_id'], 'recall_notice_id')
    # family 5: body FK existence
    reg = get_or_404(DB['registrations'], registration_id,
                     'ERR_REGISTRATION_NOT_FOUND', 'WarrantyRegistration')
    notice = None
    if notice_id is not None:
        notice = get_or_404(DB['notices'], notice_id, 'ERR_NOTICE_NOT_FOUND',
                            'RecallNotice')
    # family 2: the registration's owning dealer files the claim
    if reg['dealer_id'] != uid:
        raise ApiError(403, 'ERR_INSUFFICIENT_PERMISSIONS',
                       'DealerPrincipal may only file claims for own registrations')
    # family 7: linked notice must still be NOTIFIED
    if notice is not None and notice['status'] != 'NOTIFIED':
        raise ApiError(409, 'ERR_INVALID_NOTICE_STATE',
                       'Linked recall notice is not NOTIFIED')
    # family 9: coverage enforced temporally; recall-linked claims bypass it
    # (submission on the coverage end date itself is still inside coverage)
    if notice is None:
        from store import parse_date
        coverage_end = parse_date(reg['coverage_end_date'])
        if CLOCK.now().date() > coverage_end:
            raise ApiError(422, 'ERR_COVERAGE_EXPIRED',
                           'Claim submitted after coverage end date')
    # family 10: the linked notice must belong to the registration's hull
    if notice is not None and notice['hull_id'] != reg['hull_id']:
        raise ApiError(422, 'ERR_RECALL_NOTICE_MISMATCH',
                       'Recall notice belongs to a different hull')
    rec = new_rec({
        'registration_id': registration_id,
        'recall_notice_id': notice_id,
        'defect_description': defect,
        'labor_hours': labor,
        'parts_cents': parts,
        'variant_applied': 'RECALL_GOODWILL' if notice is not None else 'STANDARD',
        'labor_charge_cents': None,
        'parts_credit_cents': None,
        'reimbursement_cents': None,
        'status': 'SUBMITTED',
    })
    DB['claims'][rec['id']] = rec
    return respond(serialize(rec), 201)


@bp.get('/warranty-claims')
def list_claims():
    auth_context()
    items = list(DB['claims'].values())
    for param in ('registration_id', 'recall_notice_id', 'status'):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c[param] == v]
    return list_response(items, serialize)


@bp.get('/warranty-claims/<cid>')
def get_claim(cid):
    auth_context()
    rec = get_or_404(DB['claims'], cid, 'ERR_CLAIM_NOT_FOUND',
                     'WarrantyClaim')
    return respond(serialize(rec), 200)


@bp.post('/warranty-claims/<cid>/approve')
def approve_claim(cid):
    uid, role = auth_context()
    require_roles(role, 'WarrantyAdministrator')
    claim = get_or_404(DB['claims'], cid, 'ERR_CLAIM_NOT_FOUND',
                       'WarrantyClaim')
    if claim['status'] != 'SUBMITTED':
        raise ApiError(409, 'ERR_CLAIM_NOT_SUBMITTED',
                       'Approve requires a SUBMITTED claim')
    hours = Decimal(str(claim['labor_hours']))
    if claim['variant_applied'] == 'RECALL_GOODWILL':
        # labor flat at 100%, parts at 100%
        labor_charge = rhu(hours * BASE_LABOR_RATE)
        parts_credit = claim['parts_cents']
    else:
        # STANDARD: first 2.0h at full rate, beyond at 85%; parts at 85%;
        # per-component rounding pinned (labor, then parts, then sum)
        labor_charge = (rhu(min(hours, TIER1_HOURS) * BASE_LABOR_RATE)
                        + rhu(max(Decimal('0'), hours - TIER1_HOURS)
                              * BASE_LABOR_RATE * TIER2_FACTOR))
        parts_credit = rhu(Decimal(claim['parts_cents']) * PARTS_FACTOR)
    claim['labor_charge_cents'] = labor_charge
    claim['parts_credit_cents'] = parts_credit
    claim['reimbursement_cents'] = labor_charge + parts_credit
    claim['status'] = 'APPROVED'
    touch(claim)
    # retail remedy path: linked notice remedies on approval
    if claim['recall_notice_id'] is not None:
        notice = DB['notices'].get(claim['recall_notice_id'])
        if notice is not None and notice['status'] == 'NOTIFIED':
            remedy_notice(notice, 'WARRANTY_CLAIM')
    return respond(serialize(claim), 200)


@bp.post('/warranty-claims/<cid>/reject')
def reject_claim(cid):
    uid, role = auth_context()
    require_roles(role, 'WarrantyAdministrator')
    claim = get_or_404(DB['claims'], cid, 'ERR_CLAIM_NOT_FOUND',
                       'WarrantyClaim')
    if claim['status'] != 'SUBMITTED':
        raise ApiError(409, 'ERR_CLAIM_NOT_SUBMITTED',
                       'Reject requires a SUBMITTED claim')
    claim['status'] = 'REJECTED'
    touch(claim)
    return respond(serialize(claim), 200)
