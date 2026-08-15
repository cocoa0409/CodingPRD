"""Financial statements: attach (optionally restating), spread, finalize."""
from flask import Blueprint, g, request

import serialize
from db import STORE, new_entity, touch
from errors import (
    raise_err, ERR_INVALID_STATE, ERR_AMEND_NOT_PERMITTED, ERR_RESTATEMENT_TARGET_INVALID,
)
from middleware import require_roles, ALL_ROLES
from response import success_object
from routes.common import get_or_404, render_list, body_fk_exists
from routes.applications import rerun_underwriting_in_exception_review
from validation import get_body, req_str, req_int, req_date

bp = Blueprint("statements", __name__)

SPREAD_PARENT_STAGES = {"INTAKE", "SPREADING", "EXCEPTION_REVIEW"}
FINALIZE_PARENT_STAGES = {"SPREADING", "EXCEPTION_REVIEW"}

_STATEMENT_INT_FIELDS = [
    'revenue_cents', 'ebitda_cents', 'addbacks_cents', 'distributions_cents',
    'maintenance_capex_cents', 'existing_annual_debt_service_cents',
    'total_assets_cents', 'total_liabilities_cents',
]


@bp.post("/credit/financial-statements")
def create_statement():
    require_roles("CreditAnalyst")
    body = get_body()
    app_id = req_str(body, "loan_application_id")
    period_end_date = req_date(body, "period_end_date")
    figures = {f: req_int(body, f) for f in _STATEMENT_INT_FIELDS}
    restatement_of_id = body.get('restatement_of_id')
    if restatement_of_id is not None and not isinstance(restatement_of_id, str):
        raise_err(ERR_RESTATEMENT_TARGET_INVALID, "Field 'restatement_of_id' must reference a statement.")
    body_fk_exists(STORE.loan_applications, app_id, "LoanApplication")

    app = STORE.loan_applications[app_id]
    # Priority 7: amendment window.
    if app['status'] not in SPREAD_PARENT_STAGES:
        raise_err(ERR_AMEND_NOT_PERMITTED,
                  "Application status %s does not permit attaching statements." % app['status'])

    # Priority 31: restatement target validity.
    if restatement_of_id is not None:
        target = STORE.financial_statements.get(restatement_of_id)
        if (target is None
                or target['loan_application_id'] != app_id
                or target['status'] != 'FINAL'
                or target['period_end_date'] != period_end_date):
            raise_err(ERR_RESTATEMENT_TARGET_INVALID,
                      "restatement_of_id must reference an existing FINAL statement of the same application with an identical period_end_date.")

    stmt = new_entity()
    stmt.update({
        'loan_application_id': app_id,
        'restatement_of_id': restatement_of_id,
        'period_end_date': period_end_date,
        'status': 'SUBMITTED',
        'spread_by_officer_id': None,
        'finalized_by_officer_id': None,
    })
    stmt.update(figures)
    STORE.financial_statements[stmt['id']] = stmt
    return success_object(serialize.financial_statement(stmt), status=201)


@bp.get("/credit/financial-statements")
def list_statements():
    require_roles(*ALL_ROLES)
    items = list(STORE.financial_statements.values())
    app_id = request.args.get("loan_application_id")
    restatement_of_id = request.args.get("restatement_of_id")
    spread_by = request.args.get("spread_by_officer_id")
    finalized_by = request.args.get("finalized_by_officer_id")
    if app_id is not None:
        items = [s for s in items if s['loan_application_id'] == app_id]
    if restatement_of_id is not None:
        items = [s for s in items if s['restatement_of_id'] == restatement_of_id]
    if spread_by is not None:
        items = [s for s in items if s['spread_by_officer_id'] == spread_by]
    if finalized_by is not None:
        items = [s for s in items if s['finalized_by_officer_id'] == finalized_by]
    return render_list(items, serialize.financial_statement)


@bp.get("/credit/financial-statements/<sid>")
def get_statement(sid):
    require_roles(*ALL_ROLES)
    stmt = get_or_404(STORE.financial_statements, sid, "FinancialStatement")
    return success_object(serialize.financial_statement(stmt))


@bp.post("/credit/financial-statements/<sid>/spread")
def spread_statement(sid):
    require_roles("CreditAnalyst")
    stmt = get_or_404(STORE.financial_statements, sid, "FinancialStatement")
    get_body(required=False)
    if stmt['status'] != 'SUBMITTED':
        raise_err(ERR_INVALID_STATE, "Statement status is %s; spread requires SUBMITTED." % stmt['status'])
    app = get_or_404(STORE.loan_applications, stmt['loan_application_id'], "LoanApplication")
    if app['status'] not in SPREAD_PARENT_STAGES:
        raise_err(ERR_AMEND_NOT_PERMITTED,
                  "Application status %s does not permit spreading statements." % app['status'])
    stmt['status'] = 'SPREAD'
    stmt['spread_by_officer_id'] = g.user_id
    touch(stmt)
    return success_object(serialize.financial_statement(stmt))


@bp.post("/credit/financial-statements/<sid>/finalize")
def finalize_statement(sid):
    require_roles("CreditAnalyst")
    stmt = get_or_404(STORE.financial_statements, sid, "FinancialStatement")
    get_body(required=False)
    if stmt['status'] != 'SPREAD':
        raise_err(ERR_INVALID_STATE, "Statement status is %s; finalize requires SPREAD." % stmt['status'])
    app = get_or_404(STORE.loan_applications, stmt['loan_application_id'], "LoanApplication")
    if app['status'] not in FINALIZE_PARENT_STAGES:
        raise_err(ERR_AMEND_NOT_PERMITTED,
                  "Application status %s does not permit finalizing statements." % app['status'])

    stmt['status'] = 'FINAL'
    stmt['finalized_by_officer_id'] = g.user_id
    touch(stmt)

    # Restatement cycle: the referenced statement is superseded.
    if stmt['restatement_of_id'] is not None:
        target = STORE.financial_statements.get(stmt['restatement_of_id'])
        if target is not None and target['status'] == 'FINAL':
            target['status'] = 'SUPERSEDED'
            touch(target)

    # Underwriting re-run while the application sits in EXCEPTION_REVIEW.
    if app['status'] == 'EXCEPTION_REVIEW':
        rerun_underwriting_in_exception_review(app)
        touch(app)

    return success_object(serialize.financial_statement(stmt))
