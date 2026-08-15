"""Funding authorizations: request, authorize (SoD), release (gated pipeline)."""
from flask import Blueprint, g

import serialize
from db import STORE, new_entity, touch, now_dt
from errors import (
    raise_err, ERR_VALIDATION, ERR_INVALID_STATE, ERR_SOD_FUNDING_SELF_AUTHORIZE,
    ERR_UNRESOLVED_POLICY_EXCEPTION, ERR_CHECKLIST_INCOMPLETE, ERR_RATE_LOCK_EXPIRED,
    ERR_COMMITMENT_NOT_ACCEPTED, ERR_FUNDING_OVER_COMMITMENT,
)
from middleware import require_roles, ALL_ROLES
from response import success_object
from routes.common import get_or_404, render_list, body_fk_exists
from services import exposure, policy
from validation import get_body, req_str, req_int, req_date

bp = Blueprint("funding", __name__)


@bp.post("/credit/funding-authorizations")
def request_funding():
    require_roles("CreditAdministrator")
    body = get_body()
    app_id = req_str(body, "loan_application_id")
    amount = req_int(body, "amount_cents")
    if amount <= 0:
        raise_err(ERR_VALIDATION, "Field 'amount_cents' must be strictly greater than zero.")
    disbursement_date = req_date(body, "disbursement_date")
    body_fk_exists(STORE.loan_applications, app_id, "LoanApplication")

    app = STORE.loan_applications[app_id]
    if app['status'] not in ('CLOSING', 'FUNDED'):
        raise_err(ERR_INVALID_STATE,
                  "Application status is %s; funding requests require CLOSING or FUNDED." % app['status'])

    funding = new_entity()
    funding.update({
        'loan_application_id': app_id,
        'amount_cents': amount,
        'disbursement_date': disbursement_date,
        'requested_by_officer_id': g.user_id,
        'authorized_by_officer_id': None,
        'status': 'REQUESTED',
    })
    STORE.funding_authorizations[funding['id']] = funding
    return success_object(serialize.funding_authorization(funding), status=201)


@bp.get("/credit/loan-applications/<aid>/funding-authorizations")
def application_fundings(aid):
    require_roles(*ALL_ROLES)
    get_or_404(STORE.loan_applications, aid, "LoanApplication")
    return render_list(exposure.fundings_of_app(aid), serialize.funding_authorization)


@bp.post("/credit/funding-authorizations/<fid>/authorize")
def authorize_funding(fid):
    require_roles("CreditPolicyOfficer")
    funding = get_or_404(STORE.funding_authorizations, fid, "FundingAuthorization")
    get_body(required=False)
    if funding['status'] != 'REQUESTED':
        raise_err(ERR_INVALID_STATE, "Funding status is %s; authorize requires REQUESTED." % funding['status'])
    if g.user_id == funding['requested_by_officer_id']:
        raise_err(ERR_SOD_FUNDING_SELF_AUTHORIZE,
                  "The funding authorizer must differ from the requesting officer.")
    funding['status'] = 'AUTHORIZED'
    funding['authorized_by_officer_id'] = g.user_id
    touch(funding)
    return success_object(serialize.funding_authorization(funding))


@bp.post("/credit/funding-authorizations/<fid>/release")
def release_funding(fid):
    require_roles("CreditAdministrator")
    funding = get_or_404(STORE.funding_authorizations, fid, "FundingAuthorization")
    get_body(required=False)
    app = get_or_404(STORE.loan_applications, funding['loan_application_id'], "LoanApplication")

    # Gate order (PRD section 3.7): state -> open HIGH exceptions -> closing
    # conditions -> rate lock -> letter state -> cumulative funding cap.
    if funding['status'] != 'AUTHORIZED':
        raise_err(ERR_INVALID_STATE, "Funding status is %s; release requires AUTHORIZED." % funding['status'])
    if app['status'] not in ('CLOSING', 'FUNDED'):
        raise_err(ERR_INVALID_STATE,
                  "Application status is %s; release requires CLOSING or FUNDED." % app['status'])
    if policy.any_open_high_exception(app['id']):
        raise_err(ERR_UNRESOLVED_POLICY_EXCEPTION,
                  "An OPEN HIGH-severity policy exception exists for this application.")
    incomplete = any(
        i['category'] == 'CLOSING_CONDITION' and i['is_required'] and i['status'] not in ('APPROVED', 'WAIVED')
        for i in exposure.checklist_items_of_app(app['id']))
    if incomplete:
        raise_err(ERR_CHECKLIST_INCOMPLETE,
                  "Required CLOSING_CONDITION checklist items are not all APPROVED or WAIVED.")
    letter = exposure.letter_for_app(app['id'])
    if letter is None or letter['_rate_lock_dt'] is None or now_dt() > letter['_rate_lock_dt']:
        raise_err(ERR_RATE_LOCK_EXPIRED, "The logical clock has passed the letter's rate_lock_expires_at.")
    if letter['status'] not in ('ACCEPTED', 'FUNDED'):
        raise_err(ERR_COMMITMENT_NOT_ACCEPTED,
                  "Commitment letter status is %s; release requires ACCEPTED or FUNDED." % letter['status'])
    funded_so_far = exposure.app_funded_amount_cents(app['id'])
    if funded_so_far + funding['amount_cents'] > letter['committed_amount_cents']:
        raise_err(ERR_FUNDING_OVER_COMMITMENT,
                  "Cumulative funding would exceed the letter's committed_amount_cents.")

    first_release = (letter['status'] == 'ACCEPTED')
    funding['status'] = 'RELEASED'
    touch(funding)
    if first_release:
        letter['status'] = 'FUNDED'
        touch(letter)
        if app['status'] == 'CLOSING':
            app['status'] = 'FUNDED'
        touch(app)
        for participation in exposure.participations_of_app(app['id']):
            if participation['status'] == 'COMMITTED':
                participation['status'] = 'FUNDED'
                touch(participation)
    else:
        # Subsequent tranche: funded totals are derived, but the application's
        # funded_amount_cents mutation still advances its version.
        touch(app)
    return success_object(serialize.funding_authorization(funding))
