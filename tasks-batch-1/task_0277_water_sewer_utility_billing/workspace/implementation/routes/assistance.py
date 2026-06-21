"""AssistanceEnrollment routes (PRD §3.10)."""
from flask import Blueprint

import db
import errors
import middleware
from response import object_response, array_response
from services import lookup, ledger
from services.common import (
    get_json_body, require_str, require_datetime, require_bool,
    public, public_list, parse_pagination, paginate,
)

bp = Blueprint("assistance", __name__)


@bp.post("/accounts/<account_id>/assistance-enrollments")
def enroll(account_id):
    middleware.require_role({"AssistanceCaseworker"})
    account = lookup.account(account_id)
    body = get_json_body()

    program_code = require_str(body, "program_code")
    require_datetime(body, "certified_until")
    grants_protection = require_bool(body, "grants_shutoff_protection", default=True)

    rec = db.make_record({
        "account_id": account_id,
        "program_code": program_code,
        "certified_until": body["certified_until"],
        "grants_shutoff_protection": grants_protection,
        "status": "ACTIVE",
    })
    db.assistance_enrollments[rec["id"]] = rec

    # If grants protection and account currently PAST_DUE -> DELINQUENT_PROTECTED
    # (transition defined out of PAST_DUE) (PRD §3.10).
    if grants_protection and account["billing_status"] == "PAST_DUE":
        account["billing_status"] = "DELINQUENT_PROTECTED"

    # Sets assistance_enrolled true; reconcile refreshes derived flags + version.
    ledger.reconcile(account)
    return object_response(public(rec), 201)


@bp.get("/accounts/<account_id>/assistance-enrollments")
def list_enrollments(account_id):
    middleware.require_role({"AssistanceCaseworker", "BillingClerk", "Customer"})
    lookup.account(account_id)
    middleware.require_owner(account_id)
    limit, offset = parse_pagination()

    records = [e for e in db.assistance_enrollments.values() if e["account_id"] == account_id]
    window, total = paginate(records, limit, offset)
    return array_response(public_list(window), limit, offset, total, 200)


@bp.post("/assistance-enrollments/<rid>/revoke")
def revoke(rid):
    middleware.require_role({"AssistanceCaseworker"})
    enrollment = lookup.assistance_enrollment(rid)

    # Revoke is defined only from ACTIVE.
    if enrollment["status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Only an ACTIVE enrollment may be revoked.")

    enrollment["status"] = "REVOKED"
    db.touch(enrollment)

    account = db.accounts[enrollment["account_id"]]
    # Recompute derived flags first so assistance_enrolled reflects the revoke.
    ledger.reconcile(account)

    # If account was DELINQUENT_PROTECTED and still carries arrears -> PAST_DUE.
    if account["billing_status"] == "DELINQUENT_PROTECTED" and account["past_due_cents"] > 0:
        account["billing_status"] = "PAST_DUE"
        ledger.reconcile(account)

    return object_response(public(enrollment), 200)
