"""Loan applications: creation, amendment, and the pipeline state machine."""
from decimal import Decimal

from flask import Blueprint, g, request

import serialize
from db import STORE, new_entity, touch
from errors import (
    raise_err, ERR_VALIDATION, ERR_INVALID_STATE, ERR_AMEND_NOT_PERMITTED,
    ERR_BORROWER_NOT_ACTIVE, ERR_SINGLE_BORROWER_LIMIT, ERR_STATEMENTS_NOT_FINAL,
    ERR_OPEN_POLICY_EXCEPTIONS, ERR_NO_ACCEPTED_APPRAISAL, ERR_APPRAISALS_NOT_SETTLED,
    ERR_SOD_SPREAD_FINALIZE_BY_ORIGINATOR, ERR_CHECKLIST_INCOMPLETE,
    ERR_NO_COVENANTS_CONFIGURED,
)
from middleware import require_roles, ALL_ROLES
from response import success_object
from routes.common import get_or_404, render_list, body_fk_exists
from services import exposure, policy, underwriting
from services.underwriting import (
    PRODUCT_TYPES, SINGLE_BORROWER_CAP_CENTS, MAX_LTV,
    compute_dscr, compute_risk_rating, compute_maximum_sizing, latest_final_statement,
)
from validation import get_body, req_str, req_int, req_enum, opt_str, opt_int

bp = Blueprint("applications", __name__)

APP_STATUSES = {
    "INTAKE", "SPREADING", "EXCEPTION_REVIEW", "APPRAISAL_REVIEW", "COMMITTEE_REVIEW",
    "TERM_SHEET_NEGOTIATION", "COMMITMENT", "DOCUMENTATION", "CLOSING", "FUNDED",
    "DECLINED", "WITHDRAWN", "EXPIRED",
}
TERMINAL_STATUSES = {"FUNDED", "DECLINED", "WITHDRAWN", "EXPIRED"}
MUTABLE_STATEMENT_STAGES = {"INTAKE", "SPREADING", "EXCEPTION_REVIEW"}


def _underwriting_conditions(app, borrower, dscr_standard, dscr_stress):
    """The four finalize-spreads auto-exception conditions."""
    total_exposure = exposure.borrower_total_exposure_cents(borrower['id'])
    requested = app['requested_amount_cents']
    return [
        ("dscr_minimum", "DSCR_MINIMUM", dscr_standard < Decimal("1.2500"),
         "dscr_standard=%s is below the 1.2500 minimum." % dscr_standard),
        ("stress_dscr_minimum", "STRESS_DSCR_MINIMUM", dscr_stress < Decimal("1.0000"),
         "dscr_stress=%s is below the 1.0000 minimum." % dscr_stress),
        ("single_borrower_limit", "SINGLE_BORROWER_LIMIT",
         total_exposure + requested > SINGLE_BORROWER_CAP_CENTS,
         "total_exposure_cents=%d plus requested_amount_cents=%d exceeds the 5000000000 single-borrower cap."
         % (total_exposure, requested)),
        ("reg_o_insider", "REG_O_INSIDER", bool(borrower['is_reg_o_insider']),
         "Borrower is a Regulation O insider."),
    ]


def rerun_underwriting_in_exception_review(app):
    """Recompute dual-variant DSCR and refresh the four auto exceptions."""
    stmt = latest_final_statement(app['id'])
    if stmt is None:
        return
    borrower = get_or_404(STORE.borrowers, app['borrower_id'], "Borrower")
    dscr_standard, dscr_stress, _ = compute_dscr(app, stmt)
    app['dscr_standard'] = dscr_standard
    app['dscr_stress'] = dscr_stress
    policy.refresh_auto_exceptions(
        app['id'], _underwriting_conditions(app, borrower, dscr_standard, dscr_stress))


@bp.post("/credit/loan-applications")
def create_application():
    require_roles("RelationshipManager")
    body = get_body()
    borrower_id = req_str(body, "borrower_id")
    product_type = req_enum(body, "product_type", PRODUCT_TYPES)
    requested = req_int(body, "requested_amount_cents")
    if requested <= 0:
        raise_err(ERR_VALIDATION, "Field 'requested_amount_cents' must be strictly greater than zero.")
    term_months = req_int(body, "term_months")
    if term_months < 12 or term_months > 360:
        raise_err(ERR_VALIDATION, "Field 'term_months' must be between 12 and 360 inclusive.")
    purpose = opt_str(body, "purpose")
    body_fk_exists(STORE.borrowers, borrower_id, "Borrower")

    borrower = STORE.borrowers[borrower_id]
    # Priority 13: borrower standing.
    if borrower['status'] != 'ACTIVE':
        raise_err(ERR_BORROWER_NOT_ACTIVE, "Borrower status is %s; only ACTIVE borrowers may originate." % borrower['status'])
    # Priority 32: single-borrower limit.
    total_exposure = exposure.borrower_total_exposure_cents(borrower_id)
    if total_exposure + requested > SINGLE_BORROWER_CAP_CENTS:
        raise_err(ERR_SINGLE_BORROWER_LIMIT,
                  "Borrower total exposure %d plus requested %d exceeds the 5000000000 single-borrower cap."
                  % (total_exposure, requested))

    app = new_entity()
    app.update({
        'borrower_id': borrower_id,
        'originating_officer_id': g.user_id,
        'product_type': product_type,
        'requested_amount_cents': requested,
        'term_months': term_months,
        'purpose': purpose,
        'status': 'INTAKE',
        'dscr_standard': None,
        'dscr_stress': None,
        'risk_rating': None,
        'rating_basis': None,
        'proposed_amount_cents': None,
        'committee_level_required': None,
    })
    STORE.loan_applications[app['id']] = app
    return success_object(serialize.loan_application(app), status=201)


@bp.get("/credit/loan-applications")
def list_applications():
    require_roles(*ALL_ROLES)
    items = list(STORE.loan_applications.values())
    borrower_id = request.args.get("borrower_id")
    status = request.args.get("status")
    officer_id = request.args.get("originating_officer_id")
    if borrower_id is not None:
        items = [a for a in items if a['borrower_id'] == borrower_id]
    if status is not None:
        items = [a for a in items if a['status'] == status]
    if officer_id is not None:
        items = [a for a in items if a['originating_officer_id'] == officer_id]
    return render_list(items, serialize.loan_application)


@bp.get("/credit/loan-applications/<aid>")
def get_application(aid):
    require_roles(*ALL_ROLES)
    app = get_or_404(STORE.loan_applications, aid, "LoanApplication")
    return success_object(serialize.loan_application(app))


@bp.patch("/credit/loan-applications/<aid>")
def amend_application(aid):
    require_roles("RelationshipManager")
    app = get_or_404(STORE.loan_applications, aid, "LoanApplication")
    body = get_body()

    requested = opt_int(body, "requested_amount_cents")
    if requested is not None and requested <= 0:
        raise_err(ERR_VALIDATION, "Field 'requested_amount_cents' must be strictly greater than zero.")
    term_months = opt_int(body, "term_months")
    if term_months is not None and (term_months < 12 or term_months > 360):
        raise_err(ERR_VALIDATION, "Field 'term_months' must be between 12 and 360 inclusive.")
    purpose = opt_str(body, "purpose")

    # Priority 7: amendment window.
    if app['status'] not in MUTABLE_STATEMENT_STAGES:
        raise_err(ERR_AMEND_NOT_PERMITTED,
                  "Application status %s is outside the amendment window (INTAKE, SPREADING, EXCEPTION_REVIEW)."
                  % app['status'])

    if requested is not None:
        app['requested_amount_cents'] = requested
    if term_months is not None:
        app['term_months'] = term_months
    if 'purpose' in body:
        app['purpose'] = purpose
    touch(app)

    if app['status'] == 'EXCEPTION_REVIEW':
        rerun_underwriting_in_exception_review(app)

    return success_object(serialize.loan_application(app))


@bp.post("/credit/loan-applications/<aid>/submit")
def submit_application(aid):
    require_roles("RelationshipManager")
    app = get_or_404(STORE.loan_applications, aid, "LoanApplication")
    get_body(required=False)
    if app['status'] != 'INTAKE':
        raise_err(ERR_INVALID_STATE, "Application status is %s; submit requires INTAKE." % app['status'])
    if not exposure.statements_of_app(aid):
        raise_err(ERR_STATEMENTS_NOT_FINAL, "At least one financial statement is required before submit.")
    app['status'] = 'SPREADING'
    touch(app)
    return success_object(serialize.loan_application(app))


@bp.post("/credit/loan-applications/<aid>/finalize-spreads")
def finalize_spreads(aid):
    require_roles("CreditAnalyst")
    app = get_or_404(STORE.loan_applications, aid, "LoanApplication")
    get_body(required=False)
    # State legality first, then segregation of duties, then statement completeness.
    if app['status'] != 'SPREADING':
        raise_err(ERR_INVALID_STATE, "Application status is %s; finalize-spreads requires SPREADING." % app['status'])
    if g.user_id == app['originating_officer_id']:
        raise_err(ERR_SOD_SPREAD_FINALIZE_BY_ORIGINATOR,
                  "The originating officer may not finalize the application's spreads.")
    statements = exposure.statements_of_app(aid)
    if (not statements
            or not all(s['status'] in ('FINAL', 'SUPERSEDED') for s in statements)
            or not any(s['status'] == 'FINAL' for s in statements)):
        raise_err(ERR_STATEMENTS_NOT_FINAL,
                  "Every statement must be FINAL or SUPERSEDED with at least one FINAL.")

    stmt = latest_final_statement(aid)
    borrower = get_or_404(STORE.borrowers, app['borrower_id'], "Borrower")
    dscr_standard, dscr_stress, _ = compute_dscr(app, stmt)
    app['dscr_standard'] = dscr_standard
    app['dscr_stress'] = dscr_stress
    app['risk_rating'] = compute_risk_rating(app, stmt, borrower, 'PROVISIONAL')
    app['rating_basis'] = 'PROVISIONAL'

    policy.refresh_auto_exceptions(
        aid, _underwriting_conditions(app, borrower, dscr_standard, dscr_stress))

    app['status'] = 'EXCEPTION_REVIEW' if policy.any_open_exception(aid) else 'APPRAISAL_REVIEW'
    touch(app)
    return success_object(serialize.loan_application(app))


@bp.post("/credit/loan-applications/<aid>/clear-exceptions")
def clear_exceptions(aid):
    require_roles("CreditPolicyOfficer")
    app = get_or_404(STORE.loan_applications, aid, "LoanApplication")
    get_body(required=False)
    if app['status'] != 'EXCEPTION_REVIEW':
        raise_err(ERR_INVALID_STATE, "Application status is %s; clear-exceptions requires EXCEPTION_REVIEW." % app['status'])
    if policy.any_open_exception(aid):
        raise_err(ERR_OPEN_POLICY_EXCEPTIONS, "Open policy exceptions remain for this application.")
    app['status'] = 'APPRAISAL_REVIEW'
    touch(app)
    return success_object(serialize.loan_application(app))


@bp.post("/credit/loan-applications/<aid>/submit-to-committee")
def submit_to_committee(aid):
    require_roles("CreditAnalyst")
    app = get_or_404(STORE.loan_applications, aid, "LoanApplication")
    get_body(required=False)
    if app['status'] != 'APPRAISAL_REVIEW':
        raise_err(ERR_INVALID_STATE, "Application status is %s; submit-to-committee requires APPRAISAL_REVIEW." % app['status'])
    appraisals = exposure.appraisals_of_app(aid)
    if not any(a['status'] == 'ACCEPTED' for a in appraisals):
        raise_err(ERR_NO_ACCEPTED_APPRAISAL, "At least one ACCEPTED appraisal is required.")
    if any(a['status'] in ('ENGAGED', 'REPORT_RECEIVED') for a in appraisals):
        raise_err(ERR_APPRAISALS_NOT_SETTLED, "Appraisals still ENGAGED or REPORT_RECEIVED must be settled.")

    borrower = get_or_404(STORE.borrowers, app['borrower_id'], "Borrower")
    stmt = latest_final_statement(aid)
    # Sizing (raises ERR_NO_SIZEABLE_AMOUNT on non-positive results).
    proposed = compute_maximum_sizing(app, stmt, borrower)
    app['proposed_amount_cents'] = proposed

    # Policy re-test against the deal as asked (the requested amount).
    total_appraised, total_eligible, total_liquidation = exposure.collateral_aggregates(aid)
    requested = app['requested_amount_cents']
    max_ltv = MAX_LTV[app['product_type']]
    ltv_holds = Decimal(requested) > Decimal(total_appraised) * max_ltv
    coverage_holds = total_eligible < requested
    liquidation_holds = bool(borrower['is_reg_o_insider']) and (
        Decimal(requested) > Decimal(total_liquidation) * max_ltv)
    policy.refresh_auto_exceptions(aid, [
        ("ltv_maximum", "LTV_MAXIMUM", ltv_holds,
         "requested_amount_cents=%d exceeds max_ltv %s of total_appraised_value_cents=%d."
         % (requested, max_ltv, total_appraised)),
        ("collateral_coverage_min", "COLLATERAL_COVERAGE_MIN", coverage_holds,
         "total_eligible_collateral_cents=%d is below requested_amount_cents=%d."
         % (total_eligible, requested)),
        ("collateral_coverage_min_liquidation", "COLLATERAL_COVERAGE_MIN", liquidation_holds,
         "liquidation basis: requested_amount_cents=%d exceeds max_ltv %s of total_liquidation_collateral_cents=%d."
         % (requested, max_ltv, total_liquidation)),
    ])

    app['risk_rating'] = compute_risk_rating(app, stmt, borrower, 'FULL')
    app['rating_basis'] = 'FULL'
    app['status'] = 'COMMITTEE_REVIEW'
    touch(app)
    return success_object(serialize.loan_application(app))


@bp.post("/credit/loan-applications/<aid>/submit-for-closing")
def submit_for_closing(aid):
    require_roles("CreditAdministrator")
    app = get_or_404(STORE.loan_applications, aid, "LoanApplication")
    get_body(required=False)
    if app['status'] != 'DOCUMENTATION':
        raise_err(ERR_INVALID_STATE, "Application status is %s; submit-for-closing requires DOCUMENTATION." % app['status'])
    items = exposure.checklist_items_of_app(aid)
    incomplete = any(
        i['category'] == 'DOCUMENT' and i['is_required'] and i['status'] not in ('APPROVED', 'WAIVED')
        for i in items)
    if incomplete:
        raise_err(ERR_CHECKLIST_INCOMPLETE, "Required DOCUMENT checklist items are not all APPROVED or WAIVED.")
    if not exposure.covenants_of_app(aid):
        raise_err(ERR_NO_COVENANTS_CONFIGURED, "At least one covenant must be configured before closing.")
    app['status'] = 'CLOSING'
    touch(app)
    return success_object(serialize.loan_application(app))


@bp.post("/credit/loan-applications/<aid>/withdraw")
def withdraw_application(aid):
    require_roles("RelationshipManager")
    app = get_or_404(STORE.loan_applications, aid, "LoanApplication")
    get_body(required=False)
    if app['status'] in TERMINAL_STATUSES:
        raise_err(ERR_INVALID_STATE, "Application status %s is terminal; withdraw is not permitted." % app['status'])

    # Compensation set appropriate to the stage reached.
    letter = exposure.letter_for_app(aid)
    if letter is not None and letter['status'] == 'ACCEPTED':
        letter['status'] = 'TERMINATED'
        touch(letter)
    for appraisal in exposure.appraisals_of_app(aid):
        if appraisal['status'] in ('ENGAGED', 'REPORT_RECEIVED'):
            appraisal['status'] = 'CANCELLED'
            touch(appraisal)
    for participation in exposure.participations_of_app(aid):
        if participation['status'] in ('PROPOSED', 'COMMITTED'):
            participation['status'] = 'RELEASED'
            participation['fee_share_cents'] = None
            touch(participation)
    for sheet in exposure.term_sheets_of_app(aid):
        if sheet['status'] == 'ISSUED':
            sheet['status'] = 'SUPERSEDED'
            touch(sheet)
    for funding in exposure.fundings_of_app(aid):
        if funding['status'] in ('REQUESTED', 'AUTHORIZED'):
            funding['status'] = 'CANCELLED'
            touch(funding)
    # An OPEN committee decision is deliberately left OPEN (not remanded).

    app['status'] = 'WITHDRAWN'
    touch(app)
    return success_object(serialize.loan_application(app))
