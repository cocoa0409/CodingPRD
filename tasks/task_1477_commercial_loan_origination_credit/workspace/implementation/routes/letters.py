"""Commitment letters: issue (expiry + rate lock) and accept."""
from datetime import datetime, time as dtime, timedelta, timezone

from flask import Blueprint, request

import serialize
from db import STORE, touch, now_dt
from errors import raise_err, ERR_VALIDATION, ERR_INVALID_STATE, ERR_COMMITMENT_EXPIRED
from middleware import require_roles, ALL_ROLES
from response import success_object
from routes.common import get_or_404, render_list
from validation import get_body, req_date, req_datetime

bp = Blueprint("letters", __name__)


@bp.get("/credit/commitment-letters")
def list_letters():
    require_roles(*ALL_ROLES)
    items = list(STORE.commitment_letters.values())
    app_id = request.args.get("loan_application_id")
    if app_id is not None:
        items = [l for l in items if l['loan_application_id'] == app_id]
    return render_list(items, serialize.commitment_letter)


@bp.get("/credit/commitment-letters/<lid>")
def get_letter(lid):
    require_roles(*ALL_ROLES)
    letter = get_or_404(STORE.commitment_letters, lid, "CommitmentLetter")
    return success_object(serialize.commitment_letter(letter))


@bp.post("/credit/commitment-letters/<lid>/issue")
def issue_letter(lid):
    require_roles("CreditAdministrator")
    letter = get_or_404(STORE.commitment_letters, lid, "CommitmentLetter")
    body = get_body()
    expiry_date = req_date(body, "expiry_date")
    rate_lock = req_datetime(body, "rate_lock_expires_at")
    # Stage 4 schema includes the cross-field rule: rate lock no later than
    # end-of-day on the expiry date.
    end_of_day = datetime.combine(expiry_date, dtime(23, 59, 59), tzinfo=timezone.utc) + timedelta(milliseconds=999)
    if rate_lock > end_of_day:
        raise_err(ERR_VALIDATION,
                  "rate_lock_expires_at must be no later than the end of the day on expiry_date.")
    if letter['status'] != 'DRAFT':
        raise_err(ERR_INVALID_STATE, "Letter status is %s; issue requires DRAFT." % letter['status'])
    letter['expiry_date'] = expiry_date.isoformat()
    letter['_expiry_date_d'] = expiry_date
    letter['rate_lock_expires_at'] = body['rate_lock_expires_at']
    letter['_rate_lock_dt'] = rate_lock
    letter['status'] = 'ISSUED'
    touch(letter)
    return success_object(serialize.commitment_letter(letter))


@bp.post("/credit/commitment-letters/<lid>/accept")
def accept_letter(lid):
    require_roles("CreditAdministrator")
    letter = get_or_404(STORE.commitment_letters, lid, "CommitmentLetter")
    get_body(required=False)
    if letter['status'] != 'ISSUED':
        raise_err(ERR_INVALID_STATE, "Letter status is %s; accept requires ISSUED." % letter['status'])
    # Acceptance requires the clock's current date strictly before expiry_date.
    if not (now_dt().date() < letter['_expiry_date_d']):
        raise_err(ERR_COMMITMENT_EXPIRED, "The commitment letter is at/past its expiry_date.")
    letter['status'] = 'ACCEPTED'
    touch(letter)
    app = get_or_404(STORE.loan_applications, letter['loan_application_id'], "LoanApplication")
    if app['status'] == 'COMMITMENT':
        app['status'] = 'DOCUMENTATION'
        touch(app)
    return success_object(serialize.commitment_letter(letter))
