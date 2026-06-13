"""Read-only child resource lists: fee-assessments, interest-postings,
escheat-events — FK reverse-reachability GETs."""
from flask import Blueprint, request

from db import db
from middleware import require_roles
from response import object_response
from models import public
from services.resolve import get_account, get_fee_assessment
from routes.common import paged_list

bp = Blueprint("reads", __name__)


# ---- FeeAssessment ----
@bp.route("/accounts/<account_id>/fee-assessments", methods=["GET"])
@require_roles("Teller", "ComplianceOfficer", "AccountHolder")
def list_account_fees(account_id):
    get_account(account_id)
    assessed_date = request.args.get("assessed_date")
    rows = [f for f in db.fee_assessments.values() if f["account_id"] == account_id]
    if assessed_date is not None:
        rows = [f for f in rows if f["assessed_date"] == assessed_date]
    return paged_list(rows)


@bp.route("/fee-assessments/<fee_id>", methods=["GET"])
@require_roles("Teller", "ComplianceOfficer", "AccountHolder")
def get_fee(fee_id):
    f = get_fee_assessment(fee_id)
    return object_response(public(f))


@bp.route("/fee-assessments", methods=["GET"])
@require_roles("Teller", "ComplianceOfficer")
def list_fees():
    source_transaction_id = request.args.get("source_transaction_id")
    account_id = request.args.get("account_id")
    rows = list(db.fee_assessments.values())
    if source_transaction_id is not None:
        rows = [f for f in rows if f["source_transaction_id"] == source_transaction_id]
    if account_id is not None:
        rows = [f for f in rows if f["account_id"] == account_id]
    return paged_list(rows)


# ---- InterestPosting ----
@bp.route("/accounts/<account_id>/interest-postings", methods=["GET"])
@require_roles("Teller", "ComplianceOfficer", "AccountHolder")
def list_interest_postings(account_id):
    get_account(account_id)
    rows = [p for p in db.interest_postings.values() if p["account_id"] == account_id]
    return paged_list(rows)


# ---- EscheatEvent ----
@bp.route("/accounts/<account_id>/escheat-events", methods=["GET"])
@require_roles("Teller", "ComplianceOfficer")
def list_escheat_events(account_id):
    get_account(account_id)
    rows = [e for e in db.escheat_events.values() if e["account_id"] == account_id]
    return paged_list(rows)
