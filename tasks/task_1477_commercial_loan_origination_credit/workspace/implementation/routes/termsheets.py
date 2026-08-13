"""Term sheets: OCC-guarded issuance (supersede + tiered fee) and response."""
from flask import Blueprint

import serialize
from db import STORE, new_entity, touch
from errors import raise_err, ERR_VALIDATION, ERR_STALE_VERSION, ERR_INVALID_STATE
from middleware import require_roles, ALL_ROLES
from response import success_object
from routes.common import get_or_404, render_list, body_fk_exists
from services import exposure
from services.fees import origination_fee_cents
from validation import get_body, req_str, req_int, req_enum, req_datetime

bp = Blueprint("termsheets", __name__)


@bp.post("/credit/term-sheets")
def create_term_sheet():
    require_roles("RelationshipManager")
    body = get_body()
    app_id = req_str(body, "loan_application_id")
    amount = req_int(body, "amount_cents")
    if amount <= 0:
        raise_err(ERR_VALIDATION, "Field 'amount_cents' must be strictly greater than zero.")
    rate_bps = req_int(body, "rate_bps")
    if rate_bps < 1 or rate_bps > 3000:
        raise_err(ERR_VALIDATION, "Field 'rate_bps' must be between 1 and 3000 inclusive.")
    term_months = req_int(body, "term_months")
    if term_months < 12 or term_months > 360:
        raise_err(ERR_VALIDATION, "Field 'term_months' must be between 12 and 360 inclusive.")
    expires_at = req_datetime(body, "expires_at")
    expected_version = req_int(body, "expected_loan_application_version")
    body_fk_exists(STORE.loan_applications, app_id, "LoanApplication")

    app = STORE.loan_applications[app_id]
    # Stage 5: OCC, before remaining state and business checks.
    if expected_version != app['version']:
        raise_err(ERR_STALE_VERSION,
                  "expected_loan_application_version %s does not match current application version %s."
                  % (expected_version, app['version']))
    if app['status'] != 'TERM_SHEET_NEGOTIATION':
        raise_err(ERR_INVALID_STATE,
                  "Application status is %s; issuing a term sheet requires TERM_SHEET_NEGOTIATION." % app['status'])
    # Business check (PRD 3.6, after the state gate): the offered amount must
    # equal the sized proposal exactly. It carries ERR_VALIDATION but is not a
    # stage-4 body-schema check — it depends on the persisted application, so it
    # runs after OCC per PRD 2.8 stage 5.
    if app['proposed_amount_cents'] is None or amount != app['proposed_amount_cents']:
        raise_err(ERR_VALIDATION,
                  "Offered amount_cents must equal the application's proposed_amount_cents (%s)."
                  % app['proposed_amount_cents'])

    # Supersede the application's currently ISSUED sheet, if any.
    for sheet in exposure.term_sheets_of_app(app_id):
        if sheet['status'] == 'ISSUED':
            sheet['status'] = 'SUPERSEDED'
            touch(sheet)

    sheet = new_entity()
    sheet.update({
        'loan_application_id': app_id,
        'amount_cents': amount,
        'rate_bps': rate_bps,
        'term_months': term_months,
        'expires_at': body['expires_at'],
        '_expires_at_dt': expires_at,
        'origination_fee_cents': origination_fee_cents(amount),
        'status': 'ISSUED',
    })
    STORE.term_sheets[sheet['id']] = sheet
    touch(app)
    return success_object(serialize.term_sheet(sheet), status=201)


@bp.get("/credit/loan-applications/<aid>/term-sheets")
def application_term_sheets(aid):
    require_roles(*ALL_ROLES)
    get_or_404(STORE.loan_applications, aid, "LoanApplication")
    return render_list(exposure.term_sheets_of_app(aid), serialize.term_sheet)


@bp.post("/credit/term-sheets/<tid>/respond")
def respond_term_sheet(tid):
    require_roles("RelationshipManager")
    sheet = get_or_404(STORE.term_sheets, tid, "TermSheet")
    body = get_body()
    outcome = req_enum(body, "outcome", {"ACCEPTED", "DECLINED"})

    app = get_or_404(STORE.loan_applications, sheet['loan_application_id'], "LoanApplication")
    if sheet['status'] != 'ISSUED':
        raise_err(ERR_INVALID_STATE, "Term sheet status is %s; respond requires ISSUED." % sheet['status'])
    if outcome == 'ACCEPTED':
        if app['status'] != 'TERM_SHEET_NEGOTIATION':
            raise_err(ERR_INVALID_STATE,
                      "Application status is %s; accepting a term sheet requires TERM_SHEET_NEGOTIATION." % app['status'])
        sheet['status'] = 'ACCEPTED'
        touch(sheet)
        # Create the DRAFT commitment letter mirroring the sheet's economics.
        letter = new_entity()
        letter.update({
            'loan_application_id': app['id'],
            'committed_amount_cents': sheet['amount_cents'],
            'rate_bps': sheet['rate_bps'],
            'term_months': sheet['term_months'],
            'origination_fee_cents': sheet['origination_fee_cents'],
            'expiry_date': None,
            'rate_lock_expires_at': None,
            '_expiry_date_d': None,
            '_rate_lock_dt': None,
            'status': 'DRAFT',
        })
        STORE.commitment_letters[letter['id']] = letter
        app['status'] = 'COMMITMENT'
        touch(app)
    else:
        sheet['status'] = 'DECLINED'
        touch(sheet)
    return success_object(serialize.term_sheet(sheet))
