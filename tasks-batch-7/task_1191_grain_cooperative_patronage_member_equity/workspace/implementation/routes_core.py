"""Routes: clock, members, delegate districts, delegates, fiscal years, deliveries."""
from datetime import timedelta

from flask import Blueprint

from common import (db, base_fields, touch, public, success, paginate, authn, body,
                    require, as_int, as_number, as_str, as_bool, as_dt, err, now, iso,
                    parse_dt, require_own_member)
from services import (MEMBER_CLASSES, COMMODITIES, delivery_net_bushels,
                      delivery_retain_cents, recompute_member_equity,
                      freeze_member_certificates, unfreeze_member_certificates,
                      is_executor_of, run_provisional_close, run_finalize_close,
                      run_reopen, check_resolution_ref, has_passed_resolution,
                      OPEN_REQUEST_STATUSES, delegate_is_seated)

bp = Blueprint('core', __name__)

OPEN_CLAIM_STATUSES = ('FILED', 'PROBATED', 'APPROVED')


# ---------------------------------------------------------------- clock
@bp.post('/coop/_clock/set_current_utc')
def set_current_utc():
    authn(['CoopAdmin'])
    data = body()
    require(data, 'to_iso8601')
    dt = as_dt(data, 'to_iso8601')
    from common import set_clock
    set_clock(dt)
    return success({'now_iso8601': iso(now())})


# ---------------------------------------------------------------- members
@bp.post('/coop/members')
def create_member():
    authn(['CoopRegistrar'])
    data = body()
    require(data, 'patron_ref', 'legal_name', 'member_class', 'joined_at',
            'delegate_district_id', 'is_producer_member')
    patron_ref = as_str(data, 'patron_ref')
    legal_name = as_str(data, 'legal_name')
    member_class = as_str(data, 'member_class')
    if member_class not in MEMBER_CLASSES:
        err('ERR_INVALID_REQUEST', 'member_class must be one of {0}'.format(MEMBER_CLASSES))
    joined = as_dt(data, 'joined_at')
    district_id = as_str(data, 'delegate_district_id')
    is_producer = as_bool(data, 'is_producer_member')
    if district_id not in db.districts:
        err('ERR_REFERENTIAL', 'delegate_district_id does not reference an existing district')
    if any(m['patron_ref'] == patron_ref for m in db.members.values()):
        err('ERR_CONSTRAINT_VIOLATION', 'patron_ref must be unique per cooperative')
    m = base_fields()
    m.update({
        'patron_ref': patron_ref,
        'legal_name': legal_name,
        'member_class': member_class,
        'status': 'ACTIVE',
        'joined_at': iso(joined),
        'delegate_district_id': district_id,
        'is_producer_member': is_producer,
        'capital_share_balance_cents': 0,
        'qualified_equity_cents': 0,
        'nonqualified_equity_cents': 0,
        'per_unit_retains_cents': 0,
        'total_patronage_volume_bu': 0,
    })
    db.members[m['id']] = m
    return success(public(m), 201)


def _get_member_or_404(member_id):
    m = db.members.get(member_id)
    if m is None:
        err('ERR_NOT_FOUND', 'Member not found')
    return m


@bp.get('/coop/members/<member_id>')
def get_member(member_id):
    role, uid = authn(['CoopRegistrar', 'CoopAccountant', 'CoopTreasurer', 'BoardSecretary', 'Member'])
    m = _get_member_or_404(member_id)
    require_own_member(role, uid, member_id)
    return success(public(m))


@bp.get('/coop/members')
def list_members():
    authn(['CoopRegistrar', 'CoopAccountant', 'CoopTreasurer', 'BoardSecretary'])
    items = list(db.members.values())
    from flask import request
    status = request.args.get('status')
    district = request.args.get('delegate_district_id')
    if status is not None:
        items = [m for m in items if m['status'] == status]
    if district is not None:
        items = [m for m in items if m['delegate_district_id'] == district]
    page_items, page = paginate(items)
    return success(page_items, 200, page)


def _open_request_exists(member_id):
    return any(r['member_id'] == member_id and r['status'] in OPEN_REQUEST_STATUSES
               for r in db.redemption_requests.values())


def _open_claim_exists(member_id):
    return any((c['deceased_member_id'] == member_id or c['executor_member_id'] == member_id)
               and c['status'] in OPEN_CLAIM_STATUSES
               for c in db.estate_claims.values())


@bp.post('/coop/members/<member_id>/deactivate')
def deactivate_member(member_id):
    authn(['CoopRegistrar'])
    m = _get_member_or_404(member_id)
    if m['status'] != 'ACTIVE':
        err('ERR_INVALID_STATE', 'Member must be ACTIVE to deactivate')
    if _open_request_exists(member_id):
        err('ERR_INVALID_STATE', 'Member has an open redemption request')
    m['status'] = 'INACTIVE'
    touch(m)
    return success(public(m))


@bp.post('/coop/members/<member_id>/reactivate')
def reactivate_member(member_id):
    authn(['CoopRegistrar'])
    m = _get_member_or_404(member_id)
    if m['status'] != 'INACTIVE':
        err('ERR_INVALID_STATE', 'Member must be INACTIVE to reactivate')
    m['status'] = 'ACTIVE'
    touch(m)
    unfreeze_member_certificates(member_id)
    recompute_member_equity(member_id)
    return success(public(m))


@bp.post('/coop/members/<member_id>/record_death')
def record_death(member_id):
    authn(['CoopRegistrar'])
    m = _get_member_or_404(member_id)
    data = body()
    require(data, 'date_of_death', 'executor_member_id')
    dod = as_dt(data, 'date_of_death')
    executor_id = as_str(data, 'executor_member_id')
    if m['status'] != 'ACTIVE':
        err('ERR_INVALID_STATE', 'Member must be ACTIVE to record death')
    if dod > now():
        err('ERR_TEMPORAL_WINDOW', 'date_of_death must not lie in the future')
    executor = db.members.get(executor_id)
    if executor is None:
        err('ERR_REFERENTIAL', 'executor_member_id does not reference an existing member')
    if executor['status'] != 'ACTIVE' or executor['member_class'] != 'ESTATE':
        err('ERR_REFERENTIAL', 'Executor must be an ACTIVE member of class ESTATE')
    m['status'] = 'DECEASED'
    touch(m)
    # Spawn the estate claim in FILED.
    claim = base_fields()
    claim_amount = sum(c['outstanding_cents'] for c in db.certificates.values()
                       if c['member_id'] == member_id
                       and c['status'] in ('ISSUED', 'ACTIVE', 'PARTIALLY_REDEEMED', 'FROZEN'))
    claim.update({
        'deceased_member_id': member_id,
        'executor_member_id': executor_id,
        'filed_at': iso(now()),
        'probate_completed_at': None,
        'claim_window_days': 90,
        'status': 'FILED',
        'claim_amount_cents': claim_amount,
    })
    db.estate_claims[claim['id']] = claim
    freeze_member_certificates(member_id, ('ACTIVE',))
    recompute_member_equity(member_id)
    for r in db.redemption_requests.values():
        if r['member_id'] == member_id and r['status'] in OPEN_REQUEST_STATUSES:
            r['status'] = 'CANCELLED'
            r['cancel_reason'] = 'ESTATE_TRANSITION'
            touch(r)
    return success(public(m))


@bp.post('/coop/members/<member_id>/withdraw')
def withdraw_member(member_id):
    role, uid = authn(['Member', 'CoopRegistrar'])
    m = _get_member_or_404(member_id)
    require_own_member(role, uid, member_id)
    data = body()
    require(data, 'expected_member_version')
    expected = as_int(data, 'expected_member_version')
    if expected != m['version']:
        err('ERR_STALE_MEMBER_VERSION', 'Member version has advanced; re-read and retry')
    if m['status'] != 'ACTIVE':
        err('ERR_INVALID_STATE', 'Member must be ACTIVE to withdraw')
    if _open_request_exists(member_id):
        err('ERR_INVALID_STATE', 'Member has an open redemption request')
    if _open_claim_exists(member_id):
        err('ERR_INVALID_STATE', 'Member has an open estate claim referencing them')
    m['status'] = 'WITHDRAWN'
    touch(m)
    freeze_member_certificates(member_id, ('ISSUED', 'ACTIVE'))
    recompute_member_equity(member_id)
    return success(public(m))


@bp.post('/coop/members/<member_id>/expel')
def expel_member(member_id):
    authn(['BoardSecretary'])
    m = _get_member_or_404(member_id)
    if m['status'] != 'ACTIVE':
        err('ERR_INVALID_STATE', 'Member must be ACTIVE to expel')
    if not has_passed_resolution('APPROVE_SPECIAL_REDEMPTION', member_id):
        err('ERR_INVALID_STATE',
            'A PASSED APPROVE_SPECIAL_REDEMPTION resolution referencing this member is required')
    m['status'] = 'EXPELLED'
    touch(m)
    # All certificates become immediately redeemable at face value.
    for c in db.certificates.values():
        if c['member_id'] == member_id and c['status'] in ('ISSUED', 'ACTIVE', 'PARTIALLY_REDEEMED', 'FROZEN'):
            c['redeemable_at'] = iso(now())
            touch(c)
    return success(public(m))


# ---------------------------------------------------------------- delegate districts
@bp.post('/coop/delegate_districts')
def create_district():
    authn(['CoopAdmin'])
    data = body()
    require(data, 'code', 'name', 'max_delegates')
    code = as_str(data, 'code')
    name = as_str(data, 'name')
    max_delegates = as_int(data, 'max_delegates')
    if any(d['code'] == code for d in db.districts.values()):
        err('ERR_CONSTRAINT_VIOLATION', 'District code must be unique')
    d = base_fields()
    d.update({'code': code, 'name': name, 'max_delegates': max_delegates, 'status': 'ACTIVE'})
    db.districts[d['id']] = d
    return success(public(d), 201)


def _get_district_or_404(district_id):
    d = db.districts.get(district_id)
    if d is None:
        err('ERR_NOT_FOUND', 'Delegate district not found')
    return d


@bp.get('/coop/delegate_districts/<district_id>')
def get_district(district_id):
    authn(['CoopAdmin', 'CoopRegistrar', 'BoardSecretary'])
    return success(public(_get_district_or_404(district_id)))


@bp.post('/coop/delegate_districts/<district_id>/delegates')
def seat_delegate(district_id):
    authn(['CoopRegistrar'])
    district = _get_district_or_404(district_id)
    data = body()
    require(data, 'member_id', 'term_start', 'term_end')
    member_id = as_str(data, 'member_id')
    term_start = as_dt(data, 'term_start')
    term_end = as_dt(data, 'term_end')
    member = db.members.get(member_id)
    if member is None:
        err('ERR_REFERENTIAL', 'member_id does not reference an existing member')
    if member['status'] != 'ACTIVE' or not member['is_producer_member']:
        err('ERR_INVALID_STATE', 'Delegate must be an ACTIVE producer-member')
    seated = [d for d in db.delegates.values()
              if d['district_id'] == district_id and delegate_is_seated(d)]
    if len(seated) >= district['max_delegates']:
        err('ERR_DELEGATE_CAP_REACHED', 'District already seats max_delegates active delegates')
    d = base_fields()
    d.update({
        'district_id': district_id,
        'member_id': member_id,
        'term_start': iso(term_start),
        'term_end': iso(term_end),
        'is_seated': delegate_is_seated({'member_id': member_id,
                                         'term_start': iso(term_start),
                                         'term_end': iso(term_end)}),
    })
    db.delegates[d['id']] = d
    return success(public(d), 201)


@bp.get('/coop/delegate_districts/<district_id>/delegates')
def list_district_delegates(district_id):
    authn(['CoopRegistrar', 'BoardSecretary', 'CoopAdmin'])
    _get_district_or_404(district_id)
    items = [d for d in db.delegates.values() if d['district_id'] == district_id]
    for d in items:
        d['is_seated'] = delegate_is_seated(d)
    page_items, page = paginate(items)
    return success(page_items, 200, page)


@bp.get('/coop/delegates/<delegate_id>')
def get_delegate(delegate_id):
    authn(['CoopRegistrar', 'BoardSecretary', 'CoopAdmin'])
    d = db.delegates.get(delegate_id)
    if d is None:
        err('ERR_NOT_FOUND', 'Delegate not found')
    d['is_seated'] = delegate_is_seated(d)
    return success(public(d))


@bp.get('/coop/delegates')
def list_delegates():
    authn(['CoopRegistrar', 'BoardSecretary', 'CoopAdmin'])
    from flask import request
    items = list(db.delegates.values())
    district_id = request.args.get('district_id')
    member_id = request.args.get('member_id')
    if district_id is not None:
        items = [d for d in items if d['district_id'] == district_id]
    if member_id is not None:
        items = [d for d in items if d['member_id'] == member_id]
    for d in items:
        d['is_seated'] = delegate_is_seated(d)
    page_items, page = paginate(items)
    return success(page_items, 200, page)


# ---------------------------------------------------------------- fiscal years
@bp.post('/coop/fiscal_years')
def create_fiscal_year():
    authn(['CoopAccountant'])
    data = body()
    require(data, 'year_code', 'start_date', 'end_date', 'net_margin_cents',
            'retained_reserve_pct', 'qualified_payout_pct')
    year_code = as_str(data, 'year_code')
    start = as_dt(data, 'start_date')
    end = as_dt(data, 'end_date')
    net_margin = as_int(data, 'net_margin_cents')
    reserve = as_number(data, 'retained_reserve_pct')
    payout = as_number(data, 'qualified_payout_pct')
    from decimal import Decimal as _D0
    if not (_D0(0) <= _D0(str(reserve)) <= _D0('0.5')):
        err('ERR_FISCAL_BOUNDARY', 'retained_reserve_pct must lie in [0.0, 0.5]')
    if not (_D0(0) <= _D0(str(payout)) <= _D0(1)):
        err('ERR_FISCAL_BOUNDARY', 'qualified_payout_pct must lie in [0, 1]')
    from common import cents_half_up, D as _D
    fy = base_fields()
    fy.update({
        'year_code': year_code,
        'start_date': iso(start),
        'end_date': iso(end),
        'status': 'OPEN',
        'net_margin_cents': net_margin,
        'patronage_pool_cents': cents_half_up(_D(net_margin) * (1 - _D(reserve))),
        'retained_reserve_pct': reserve,
        'qualified_payout_pct': payout,
        'closed_at': None,
        'final_audit_locked': False,
    })
    db.fiscal_years[fy['id']] = fy
    return success(public(fy), 201)


def _get_fy_or_404(fy_id):
    fy = db.fiscal_years.get(fy_id)
    if fy is None:
        err('ERR_NOT_FOUND', 'Fiscal year not found')
    return fy


@bp.get('/coop/fiscal_years/<fy_id>')
def get_fiscal_year(fy_id):
    authn(['CoopAccountant', 'CoopTreasurer', 'BoardSecretary', 'CoopRegistrar', 'ExternalAuditor'])
    return success(public(_get_fy_or_404(fy_id)))


@bp.post('/coop/fiscal_years/<fy_id>/close_provisional')
def close_provisional(fy_id):
    authn(['CoopAccountant'])
    fy = _get_fy_or_404(fy_id)
    if fy['status'] != 'OPEN':
        err('ERR_INVALID_STATE', 'Fiscal year must be OPEN for provisional close')
    if any(d['fiscal_year_id'] == fy_id and d['status'] == 'BOOKED'
           for d in db.deliveries.values()):
        err('ERR_INVALID_STATE', 'All deliveries in the year must be SETTLED or CANCELLED')
    if now() < parse_dt(fy['end_date']):
        err('ERR_TEMPORAL_WINDOW', 'Fiscal year end_date has not been reached')
    run_provisional_close(fy)
    return success(public(fy))


@bp.post('/coop/fiscal_years/<fy_id>/begin_audit')
def begin_audit(fy_id):
    authn(['ExternalAuditor'])
    fy = _get_fy_or_404(fy_id)
    if fy['status'] != 'CLOSED_PROVISIONAL':
        err('ERR_INVALID_STATE', 'Fiscal year must be CLOSED_PROVISIONAL to begin audit')
    fy['status'] = 'UNDER_AUDIT'
    touch(fy)
    return success(public(fy))


@bp.post('/coop/fiscal_years/<fy_id>/finalize_close')
def finalize_close(fy_id):
    authn(['CoopAccountant'])
    fy = _get_fy_or_404(fy_id)
    data = body()
    require(data, 'expected_fiscal_year_version')
    expected = as_int(data, 'expected_fiscal_year_version')
    if expected != fy['version']:
        err('ERR_STALE_FISCAL_YEAR_VERSION', 'Fiscal year version has advanced; re-read and retry')
    if fy['status'] not in ('UNDER_AUDIT', 'REOPENED'):
        err('ERR_INVALID_STATE', 'Fiscal year must be UNDER_AUDIT or REOPENED to finalize')
    run_finalize_close(fy)
    return success(public(fy))


@bp.post('/coop/fiscal_years/<fy_id>/reopen')
def reopen_fiscal_year(fy_id):
    authn(['BoardSecretary'])
    fy = _get_fy_or_404(fy_id)
    data = body()
    require(data, 'resolution_id')
    resolution_id = as_str(data, 'resolution_id')
    if fy['status'] != 'CLOSED_FINAL':
        err('ERR_INVALID_STATE', 'Fiscal year must be CLOSED_FINAL to reopen')
    check_resolution_ref(resolution_id, 'AMEND_ALLOCATION', fy_id)
    run_reopen(fy)
    return success(public(fy))


# ---------------------------------------------------------------- deliveries
@bp.post('/coop/deliveries')
def create_delivery():
    authn(['ElevatorOperator'])
    data = body()
    require(data, 'member_id', 'fiscal_year_id', 'commodity', 'gross_bushels',
            'dockage_pct', 'is_patron_sourced')
    member_id = as_str(data, 'member_id')
    fy_id = as_str(data, 'fiscal_year_id')
    commodity = as_str(data, 'commodity')
    if commodity not in COMMODITIES:
        err('ERR_INVALID_REQUEST', 'commodity must be one of {0}'.format(COMMODITIES))
    gross = as_int(data, 'gross_bushels')
    dockage = as_number(data, 'dockage_pct')
    is_patron = as_bool(data, 'is_patron_sourced')
    member = db.members.get(member_id)
    if member is None:
        err('ERR_REFERENTIAL', 'member_id does not reference an existing member')
    fy = db.fiscal_years.get(fy_id)
    if fy is None:
        err('ERR_REFERENTIAL', 'fiscal_year_id does not reference an existing fiscal year')
    if member['status'] != 'ACTIVE':
        err('ERR_COMPLIANCE_GATE', 'Deliveries may only be booked for ACTIVE members')
    if fy['status'] != 'OPEN':
        err('ERR_TEMPORAL_WINDOW', 'Fiscal year must be OPEN at booking')
    from decimal import Decimal as _D0
    if gross <= 0:
        err('ERR_FISCAL_BOUNDARY', 'gross_bushels must be greater than zero')
    if not (_D0(0) <= _D0(str(dockage)) <= _D0('0.30')):
        err('ERR_FISCAL_BOUNDARY', 'dockage_pct must lie in [0.00, 0.30]')
    d = base_fields()
    d.update({
        'member_id': member_id,
        'fiscal_year_id': fy_id,
        'commodity': commodity,
        'gross_bushels': gross,
        'dockage_pct': dockage,
        'net_bushels': delivery_net_bushels(gross, dockage),
        'is_patron_sourced': is_patron,
        'booked_at': iso(now()),
        'status': 'BOOKED',
        'per_unit_retain_cents': 0,
    })
    db.deliveries[d['id']] = d
    return success(public(d), 201)


def _get_delivery_or_404(delivery_id):
    d = db.deliveries.get(delivery_id)
    if d is None:
        err('ERR_NOT_FOUND', 'Delivery not found')
    return d


@bp.get('/coop/deliveries/<delivery_id>')
def get_delivery(delivery_id):
    authn(['ElevatorOperator', 'CoopAccountant', 'CoopTreasurer'])
    return success(public(_get_delivery_or_404(delivery_id)))


@bp.get('/coop/members/<member_id>/deliveries')
def list_member_deliveries(member_id):
    role, uid = authn(['ElevatorOperator', 'CoopAccountant', 'CoopTreasurer',
                       'CoopRegistrar', 'Member'])
    _get_member_or_404(member_id)
    require_own_member(role, uid, member_id)
    from flask import request
    items = [d for d in db.deliveries.values() if d['member_id'] == member_id]
    fy_id = request.args.get('fiscal_year_id')
    status = request.args.get('status')
    if fy_id is not None:
        items = [d for d in items if d['fiscal_year_id'] == fy_id]
    if status is not None:
        items = [d for d in items if d['status'] == status]
    page_items, page = paginate(items)
    return success(page_items, 200, page)


@bp.get('/coop/deliveries')
def list_deliveries():
    authn(['ElevatorOperator', 'CoopAccountant', 'CoopTreasurer', 'CoopRegistrar',
           'BoardSecretary'])
    from flask import request
    items = list(db.deliveries.values())
    member_id = request.args.get('member_id')
    fy_id = request.args.get('fiscal_year_id')
    status = request.args.get('status')
    commodity = request.args.get('commodity')
    if member_id is not None:
        items = [d for d in items if d['member_id'] == member_id]
    if fy_id is not None:
        items = [d for d in items if d['fiscal_year_id'] == fy_id]
    if status is not None:
        items = [d for d in items if d['status'] == status]
    if commodity is not None:
        items = [d for d in items if d['commodity'] == commodity]
    page_items, page = paginate(items)
    return success(page_items, 200, page)


@bp.post('/coop/deliveries/<delivery_id>/settle')
def settle_delivery(delivery_id):
    authn(['ElevatorOperator'])
    d = _get_delivery_or_404(delivery_id)
    if d['status'] == 'SETTLED':
        err('ERR_DELIVERY_ALREADY_SETTLED', 'Delivery is already SETTLED')
    if d['status'] != 'BOOKED':
        err('ERR_INVALID_STATE', 'Delivery must be BOOKED to settle')
    fy = db.fiscal_years.get(d['fiscal_year_id'])
    if fy is None or fy['status'] != 'OPEN':
        err('ERR_INVALID_STATE', 'Delivery fiscal year must be OPEN to settle')
    retain = delivery_retain_cents(d['net_bushels'], d['commodity'])
    d['per_unit_retain_cents'] = retain
    d['status'] = 'SETTLED'
    touch(d)
    m = db.members.get(d['member_id'])
    if m is not None:
        m['per_unit_retains_cents'] += retain
        if d['is_patron_sourced']:
            m['total_patronage_volume_bu'] += d['net_bushels']
        touch(m)
    return success(public(d))


@bp.post('/coop/deliveries/<delivery_id>/cancel')
def cancel_delivery(delivery_id):
    authn(['ElevatorOperator'])
    d = _get_delivery_or_404(delivery_id)
    if d['status'] != 'BOOKED':
        err('ERR_INVALID_STATE', 'Delivery must be BOOKED to cancel')
    d['status'] = 'CANCELLED'
    touch(d)
    return success(public(d))
