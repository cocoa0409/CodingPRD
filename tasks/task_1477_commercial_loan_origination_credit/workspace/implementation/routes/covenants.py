"""Covenants: setup, compliance review (breach cascade), breach waiver."""
from decimal import Decimal

from flask import Blueprint, g

import serialize
from db import STORE, new_entity, touch
from errors import raise_err, ERR_VALIDATION, ERR_INVALID_STATE
from middleware import require_roles, ALL_ROLES
from response import success_object
from routes.common import get_or_404, render_list, body_fk_exists
from services import exposure, policy
from validation import get_body, req_str, req_enum, req_number, req_date

bp = Blueprint("covenants", __name__)

COVENANT_TYPES = {"DSCR_MIN", "LEVERAGE_MAX", "CAPEX_LIMIT", "DISTRIBUTION_BLOCK"}
FREQUENCIES = {"ANNUAL", "QUARTERLY"}
COVENANT_CREATABLE_APP_STAGES = {"DOCUMENTATION", "CLOSING", "FUNDED"}


def _breach_condition_key(covenant_id):
    return "covenant_breach:%s" % covenant_id


def _borrower_has_other_breach(borrower_id, except_covenant_id):
    for app in exposure.applications_of_borrower(borrower_id):
        for cov in exposure.covenants_of_app(app['id']):
            if cov['id'] != except_covenant_id and cov['status'] == 'BREACH_PENDING':
                return True
    return False


def _restore_borrower_if_clear(borrower, except_covenant_id):
    if borrower['status'] == 'SUSPENDED' and not _borrower_has_other_breach(borrower['id'], except_covenant_id):
        borrower['status'] = 'ACTIVE'
        touch(borrower)


def _fire_breach_cascade(covenant, measured_value):
    app = get_or_404(STORE.loan_applications, covenant['loan_application_id'], "LoanApplication")
    borrower = get_or_404(STORE.borrowers, app['borrower_id'], "Borrower")
    policy.create_exception(
        app['id'], "COVENANT_BREACH",
        "Covenant %s (%s) breached: measured_value=%s vs threshold_value=%s."
        % (covenant['id'], covenant['covenant_type'], measured_value, covenant['threshold_value']),
        _breach_condition_key(covenant['id']))
    if borrower['status'] != 'SUSPENDED':
        borrower['status'] = 'SUSPENDED'
        touch(borrower)


@bp.post("/credit/covenants")
def create_covenant():
    require_roles("CreditAdministrator")
    body = get_body()
    app_id = req_str(body, "loan_application_id")
    covenant_type = req_enum(body, "covenant_type", COVENANT_TYPES)
    threshold = req_number(body, "threshold_value")
    frequency = req_enum(body, "frequency", FREQUENCIES)
    body_fk_exists(STORE.loan_applications, app_id, "LoanApplication")

    app = STORE.loan_applications[app_id]
    if app['status'] not in COVENANT_CREATABLE_APP_STAGES:
        raise_err(ERR_INVALID_STATE,
                  "Application status %s does not permit covenant setup." % app['status'])

    covenant = new_entity()
    raw_threshold = body.get('threshold_value')
    covenant.update({
        'loan_application_id': app_id,
        'covenant_type': covenant_type,
        'threshold_value': raw_threshold,
        '_threshold_dec': threshold,
        'frequency': frequency,
        'status': 'MONITORING',
        'last_reviewed_period': None,
    })
    STORE.covenants[covenant['id']] = covenant
    return success_object(serialize.covenant(covenant), status=201)


@bp.get("/credit/loan-applications/<aid>/covenants")
def application_covenants(aid):
    require_roles(*ALL_ROLES)
    get_or_404(STORE.loan_applications, aid, "LoanApplication")
    return render_list(exposure.covenants_of_app(aid), serialize.covenant)


@bp.post("/credit/covenants/<cid>/review")
def review_covenant(cid):
    require_roles("CreditAnalyst")
    covenant = get_or_404(STORE.covenants, cid, "Covenant")
    body = get_body()
    measured = req_number(body, "measured_value")
    period_end_date = req_date(body, "period_end_date")

    app = get_or_404(STORE.loan_applications, covenant['loan_application_id'], "LoanApplication")
    if app['status'] != 'FUNDED':
        raise_err(ERR_INVALID_STATE, "Application status is %s; covenant review requires FUNDED." % app['status'])
    if covenant['status'] == 'WAIVED':
        raise_err(ERR_INVALID_STATE, "Covenant status is WAIVED (terminal); review is not permitted.")

    # Pass rule: DSCR_MIN passes on >= threshold; the others pass on <= threshold.
    if covenant['covenant_type'] == 'DSCR_MIN':
        passed = measured >= covenant['_threshold_dec']
    else:
        passed = measured <= covenant['_threshold_dec']

    covenant['last_reviewed_period'] = period_end_date
    if passed:
        if covenant['status'] == 'BREACH_PENDING':
            covenant['status'] = 'CURED'
            policy.resolve_open_exception_by_key(app['id'], _breach_condition_key(covenant['id']))
            borrower = get_or_404(STORE.borrowers, app['borrower_id'], "Borrower")
            _restore_borrower_if_clear(borrower, covenant['id'])
        else:
            covenant['status'] = 'COMPLIANT'
    else:
        covenant['status'] = 'BREACH_PENDING'
        _fire_breach_cascade(covenant, measured)
    touch(covenant)
    return success_object(serialize.covenant(covenant))


@bp.post("/credit/covenants/<cid>/waive-breach")
def waive_breach(cid):
    require_roles("CreditPolicyOfficer")
    covenant = get_or_404(STORE.covenants, cid, "Covenant")
    body = get_body()
    # Stage 4 (rationale length) before stage 6 (state).
    rationale = req_str(body, "waiver_rationale")
    if len(rationale) < 20:
        raise_err(ERR_VALIDATION, "Field 'waiver_rationale' must be at least 20 characters.")
    if covenant['status'] != 'BREACH_PENDING':
        raise_err(ERR_INVALID_STATE, "Covenant status is %s; waive-breach requires BREACH_PENDING." % covenant['status'])

    covenant['status'] = 'WAIVED'
    touch(covenant)
    app = get_or_404(STORE.loan_applications, covenant['loan_application_id'], "LoanApplication")
    policy.waive_open_exception_by_key(app['id'], _breach_condition_key(covenant['id']), g.user_id, rationale)
    borrower = get_or_404(STORE.borrowers, app['borrower_id'], "Borrower")
    _restore_borrower_if_clear(borrower, covenant['id'])
    return success_object(serialize.covenant(covenant))
