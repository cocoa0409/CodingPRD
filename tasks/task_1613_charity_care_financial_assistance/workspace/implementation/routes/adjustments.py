"""Account adjustments: fetch and filtered list (PRD 3.10)."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_NOT_FOUND
from middleware import authorized, check_ownership
from response import success_object
from routes.helpers import list_envelope
from services.core import public

bp = Blueprint("adjustments", __name__)

ADJ_READ = ["Patient", "FinancialCounselor", "AssistanceReviewer",
            "BillingAdministrator", "ComplianceOfficer"]


def _adj_patient_id(adj):
    acct = db["accounts"].get(adj["account_id"])
    return acct["patient_id"] if acct else None


@bp.get("/charity-care/adjustments/<aid>")
def get_adjustment(aid):
    caller = authorized(ADJ_READ)
    adj = db["adjustments"].get(aid)
    if adj is None:
        raise_error(ERR_NOT_FOUND, "adjustment id does not exist")
    check_ownership(caller, _adj_patient_id(adj))
    return success_object(public(adj))


@bp.get("/charity-care/adjustments")
def list_adjustments():
    caller = authorized(ADJ_READ)
    items = list(db["adjustments"].values())
    if caller.role == "Patient":
        items = [a for a in items if _adj_patient_id(a) == caller.user_id]
    account_id = request.args.get("account_id")
    determination_id = request.args.get("determination_id")
    payment_id = request.args.get("payment_id")
    adjustment_type = request.args.get("adjustment_type")
    if account_id is not None:
        items = [a for a in items if a["account_id"] == account_id]
    if determination_id is not None:
        items = [a for a in items if a["determination_id"] == determination_id]
    if payment_id is not None:
        items = [a for a in items if a.get("payment_id") == payment_id]
    if adjustment_type is not None:
        items = [a for a in items if a["adjustment_type"] == adjustment_type]
    return list_envelope(items, view=public)
