from datetime import timedelta

from flask import Blueprint

from auth import user_context, require_role, forbidden, check_parent_owns_case
from db import store, base_fields, register, touch, now
from domain import (ser_package, ser_session, ser_message, ser_refund,
                    price_package, has_window_overlap,
                    TIER_WEEKS, TIER_CALLS, TIER_MESSAGES, TIER_SLA_HOURS,
                    FOLLOW_UP_WINDOW_DAYS)
from envelope import ok, paginate
from errors import ApiError
from validators import body, req_enum, opt_date, opt_int
from routes.cases import load_case

bp = Blueprint('packages', __name__)

TIERS = ('BASIC', 'STANDARD', 'PREMIUM')
KINDS = ('INITIAL', 'FOLLOW_UP')


@bp.post('/cases/<caseId>/packages')
def purchase_package(caseId):
    uid, role = user_context()
    require_role(role, 'Parent', 'PracticeAdmin')
    data = body()
    tier = req_enum(data, 'tier', TIERS)
    kind = req_enum(data, 'kind', KINDS)
    starts_on = opt_date(data, 'starts_on', default=None)
    apply_credit = opt_int(data, 'apply_credit_cents', min_v=0, default=0)
    case = load_case(caseId)
    if role == 'Parent':
        check_parent_owns_case(uid, role, case)
    # State (stage 5): FOLLOW_UP re-opens a COMPLETED case; INITIAL purchases
    # carry no case-state requirement.
    if kind == 'FOLLOW_UP' and case['status'] != 'COMPLETED':
        raise ApiError('ERR_CASE_INVALID_STATE', 409,
                       'A FOLLOW_UP package requires the case to be COMPLETED')
    family = store.families.get(case['family_id'])
    if family is None:
        raise ApiError('ERR_FAMILY_NOT_FOUND', 404, 'Family not found')
    # Pricing and the credit-balance/cap check (ERR_INVALID_REQUEST).
    gross, discount, net = price_package(case, family, tier, apply_credit)
    if starts_on is None:
        starts_on = now().date()
    duration_weeks = TIER_WEEKS[tier]
    expires_on = starts_on + timedelta(days=duration_weeks * 7 - 1)
    # Temporal (stage 7): follow-up purchase within completed_at + 180 days.
    if kind == 'FOLLOW_UP':
        completed_at = case['completed_at']
        if now() > completed_at + timedelta(days=FOLLOW_UP_WINDOW_DAYS):
            raise ApiError('ERR_FOLLOW_UP_WINDOW_CLOSED', 422,
                           'Follow-up window (completed_at + 180 days) has closed')
    # Coverage uniqueness (stage 8): INITIAL windows must not overlap an
    # existing ACTIVE package (closed date interval; touching boundaries clash).
    if kind == 'INITIAL' and has_window_overlap(case['id'], starts_on, expires_on):
        raise ApiError('ERR_PACKAGE_WINDOW_OVERLAP', 409,
                       'Coverage window overlaps an existing ACTIVE package')
    # Delivery-mode match (stage 10).
    if case['delivery_mode'] != 'ONE_ON_ONE':
        raise ApiError('ERR_DELIVERY_MODE_MISMATCH', 422,
                       'Package purchase requires delivery_mode ONE_ON_ONE')
    pkg = base_fields()
    pkg.update({
        'case_id': case['id'],
        'tier': tier,
        'kind': kind,
        'purchased_at': now(),
        'starts_on': starts_on,
        'duration_weeks': duration_weeks,
        'expires_on': expires_on,
        'included_calls': TIER_CALLS[tier],
        'included_messages': TIER_MESSAGES[tier],
        'response_sla_hours': TIER_SLA_HOURS[tier],
        'remaining_calls': TIER_CALLS[tier],
        'remaining_messages': TIER_MESSAGES[tier],
        'gross_price_cents': gross,
        'repeat_discount_cents': discount,
        'credit_applied_cents': apply_credit,
        'net_price_cents': net,
        'sla_credit_total_cents': 0,
        'status': 'ACTIVE',
    })
    register(store.packages, pkg)
    if apply_credit:
        family['credit_balance_cents'] -= apply_credit
    if kind == 'FOLLOW_UP':
        # COMPLETED -> ACTIVE_SUPPORT (the follow-up re-opens the engagement).
        case['status'] = 'ACTIVE_SUPPORT'
        touch(case)
    return ok(ser_package(pkg), status=201)


@bp.get('/cases/<caseId>/packages')
def list_case_packages(caseId):
    uid, role = user_context()
    require_role(role, 'PracticeAdmin', 'Consultant', 'Parent')
    case = load_case(caseId)
    check_parent_owns_case(uid, role, case)
    rows = [p for p in store.packages.values() if p['case_id'] == case['id']]
    return paginate(rows, ser_package)


def load_package(package_id):
    pkg = store.packages.get(package_id)
    if pkg is None:
        raise ApiError('ERR_PACKAGE_NOT_FOUND', 404, 'Package not found')
    return pkg


def _authorize_package_read(uid, role, pkg):
    if role == 'Parent':
        case = store.cases.get(pkg['case_id'])
        if case is None or case['family_id'] != uid:
            forbidden('Parent may read only their own cases\' packages')


@bp.get('/packages/<packageId>')
def get_package(packageId):
    uid, role = user_context()
    require_role(role, 'PracticeAdmin', 'Consultant', 'Parent')
    pkg = load_package(packageId)
    _authorize_package_read(uid, role, pkg)
    return ok(ser_package(pkg))


@bp.get('/packages/<packageId>/troubleshooting-sessions')
def list_package_sessions(packageId):
    uid, role = user_context()
    require_role(role, 'PracticeAdmin', 'Consultant', 'Parent')
    pkg = load_package(packageId)
    _authorize_package_read(uid, role, pkg)
    rows = [s for s in store.sessions.values() if s['package_id'] == pkg['id']]
    return paginate(rows, ser_session)


@bp.get('/packages/<packageId>/messages')
def list_package_messages(packageId):
    uid, role = user_context()
    require_role(role, 'PracticeAdmin', 'Consultant', 'Parent')
    pkg = load_package(packageId)
    _authorize_package_read(uid, role, pkg)
    rows = [m for m in store.messages.values() if m['package_id'] == pkg['id']]
    return paginate(rows, ser_message)


@bp.get('/packages/<packageId>/refund-requests')
def list_package_refunds(packageId):
    uid, role = user_context()
    require_role(role, 'PracticeAdmin', 'Consultant', 'Parent')
    pkg = load_package(packageId)
    _authorize_package_read(uid, role, pkg)
    rows = [r for r in store.refunds.values() if r['package_id'] == pkg['id']]
    return paginate(rows, ser_refund)
