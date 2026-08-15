"""Logical clock: admin-only set + atomic expiry/adjournment sweeps (PRD 2.6)."""
from flask import Blueprint

from db import STORE, touch
from middleware import require_roles
from response import success_object
from validation import get_body, req_datetime

bp = Blueprint("clock", __name__)


@bp.post("/credit/_clock/set_current_utc")
def set_current_utc():
    require_roles("BankAdmin")
    body = get_body()
    new_now = req_datetime(body, "to_iso8601")
    STORE.clock = new_now

    # Sweep 1: ISSUED commitment letters whose expiry_date falls on or before
    # the clock's current date -> EXPIRED, with the three-hop cascade.
    clock_date = new_now.date()
    for letter in list(STORE.commitment_letters.values()):
        if letter['status'] != 'ISSUED':
            continue
        if letter['_expiry_date_d'] is None or letter['_expiry_date_d'] > clock_date:
            continue
        letter['status'] = 'EXPIRED'
        touch(letter)
        app = STORE.loan_applications.get(letter['loan_application_id'])
        if app is not None and app['status'] == 'COMMITMENT':
            app['status'] = 'EXPIRED'
            touch(app)
        app_id = letter['loan_application_id']
        for item in STORE.document_checklist_items.values():
            if item['loan_application_id'] == app_id and item['status'] in ('PENDING', 'RECEIVED', 'REJECTED'):
                item['status'] = 'CANCELLED'
                touch(item)
        for participation in STORE.participations.values():
            if participation['loan_application_id'] == app_id and participation['status'] in ('PROPOSED', 'COMMITTED'):
                participation['status'] = 'RELEASED'
                participation['fee_share_cents'] = None
                touch(participation)

    # Sweep 2: ISSUED term sheets whose expires_at is strictly before now.
    for sheet in list(STORE.term_sheets.values()):
        if sheet['status'] == 'ISSUED' and sheet['_expires_at_dt'] < new_now:
            sheet['status'] = 'EXPIRED'
            touch(sheet)

    # Sweep 3: SCHEDULED committee sessions whose ends_at is at or before now.
    for session in list(STORE.committee_sessions.values()):
        if session['status'] == 'SCHEDULED' and session['_ends_at_dt'] <= new_now:
            session['status'] = 'ADJOURNED'
            touch(session)

    return success_object({}, status=200)
