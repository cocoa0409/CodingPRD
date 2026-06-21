"""MaturityEvent endpoints (§3.9)."""
import re

from flask import Blueprint, request

import db
import errors
from middleware import get_user_context, require_role
from response import success
from serializers import public, public_list
from services import common

bp = Blueprint("maturity", __name__)

EVENT_TYPES = {"BORROWER_DEATH", "PERMANENT_VACANCY", "SALE_OF_PROPERTY", "TAX_INSURANCE_DEFAULT"}
READ_ROLES = {"ServicerOps", "ComplianceOfficer", "HudAuditor"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@bp.route("/maturity-events", methods=["POST"])
def create_event():
    _, role = get_user_context()
    require_role(role, {"ComplianceOfficer", "ServicerOps"})
    body = common.get_json_body()
    common.require_fields(body, ["loan_id", "event_type", "event_date"])
    loan = db.loans.get(body["loan_id"])
    if loan is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Loan not found")
    common.require_enum(body, "event_type", EVENT_TYPES)
    ed = body["event_date"]
    if not isinstance(ed, str) or not _DATE_RE.match(ed):
        raise errors.err(errors.ERR_INVALID_REQUEST, "event_date must be YYYY-MM-DD")

    rec = {
        "loan_id": loan["id"],
        "event_type": body["event_type"],
        "event_date": ed,
        "status": "RECORDED",
    }
    db.stamp_create(rec)
    db.maturity_events[rec["id"]] = rec

    # cascade only when the loan is ACTIVE on the disposition axis
    if loan["disposition_status"] == "ACTIVE":
        loan["disposition_status"] = "DUE_AND_PAYABLE"
        # void every disbursement not yet DISBURSED
        for d in db.disbursements.values():
            if d["loan_id"] != loan["id"]:
                continue
            if d["status"] in ("REQUESTED", "APPROVED"):
                d["status"] = "VOIDED"
                d["approved_amount_cents"] = 0
                db.touch(d)
        # freeze the line
        loan["available_line_of_credit_cents"] = 0
        # conditional: TAX_INSURANCE_DEFAULT + exhausted LESA -> property-charge delinquency
        if body["event_type"] == "TAX_INSURANCE_DEFAULT":
            lesa = _find_lesa(loan["id"])
            if lesa is not None and lesa["remaining_cents"] == 0:
                loan["servicing_status"] = "DELINQUENT_PROPERTY_CHARGE"
        db.touch(loan)

    return success(public(rec), status=201)


def _find_lesa(loan_id):
    for l in db.lesa_set_asides.values():
        if l["loan_id"] == loan_id:
            return l
    return None


@bp.route("/maturity-events/<event_id>", methods=["GET"])
def get_event(event_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    rec = db.maturity_events.get(event_id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "MaturityEvent not found")
    return success(public(rec))


@bp.route("/maturity-events", methods=["GET"])
def list_events():
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    limit, offset = common.parse_pagination()
    rows = list(db.maturity_events.values())
    loan_id = request.args.get("loan_id")
    if loan_id is not None:
        rows = [r for r in rows if r["loan_id"] == loan_id]
    page, meta = common.paginate(rows, limit, offset)
    return success(public_list(page), list_meta=meta)


@bp.route("/maturity-events/<event_id>/acknowledge", methods=["POST"])
def acknowledge(event_id):
    _, role = get_user_context()
    require_role(role, {"ComplianceOfficer"})
    rec = db.maturity_events.get(event_id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "MaturityEvent not found")
    loan = db.loans.get(rec["loan_id"])
    if loan is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Loan not found")
    if rec["status"] != "RECORDED":
        raise errors.err(errors.ERR_INVALID_STATE, "Event not in RECORDED state")
    if loan["disposition_status"] not in ("DUE_AND_PAYABLE", "DEFERRED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Loan not due-and-payable or deferred")
    rec["status"] = "ACKNOWLEDGED"
    db.touch(rec)
    return success(public(rec))
