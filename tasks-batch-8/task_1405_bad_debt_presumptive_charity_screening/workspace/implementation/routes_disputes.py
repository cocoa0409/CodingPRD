"""PatientDispute endpoints: file, get, list-by-account, resolve (PRD 3.6)."""

from datetime import timedelta

from flask import Blueprint

from db import db
from errors import (
    ApiError,
    ERR_DISPUTE_AMOUNT_INVALID,
    invalid_state,
    not_found,
)
from middleware import (
    ROLE_COLLECTOR,
    ROLE_COUNSELOR,
    ROLE_OFFICER,
    authenticate,
)
from response import ok_list, ok_object
from services import (
    DISPUTE_INVESTIGATION_DAYS,
    active_agency_placement,
    serialize_dispute,
)
from util import (
    base_record,
    get_body,
    now_iso,
    paginate,
    req_enum,
    req_int,
    req_str,
    today,
    touch,
)

bp = Blueprint("disputes", __name__)

_READ_ROLES = [ROLE_COLLECTOR, ROLE_COUNSELOR, ROLE_OFFICER]


def get_dispute_or_404(dispute_id):
    d = db.disputes.get(dispute_id)
    if d is None:
        raise not_found("dispute not found")
    return d


@bp.post("/self-pay/patient-disputes")
def file_dispute():
    authenticate([ROLE_COLLECTOR, ROLE_COUNSELOR])
    b = get_body()
    account_id = req_str(b, "account_id")
    from routes_accounts import get_account_or_404
    account = get_account_or_404(account_id)
    dispute_reason = req_str(b, "dispute_reason")
    dispute_amount_cents = req_int(b, "dispute_amount_cents")
    if (dispute_amount_cents <= 0
            or dispute_amount_cents > account["current_balance_cents"]):
        raise ApiError(
            ERR_DISPUTE_AMOUNT_INVALID,
            "dispute_amount_cents must be > 0 and no more than the account's "
            "current_balance_cents",
            422,
        )

    rec = base_record()
    rec.update({
        "account_id": account_id,
        "dispute_reason": dispute_reason,
        "dispute_amount_cents": dispute_amount_cents,
        "filed_at": now_iso(),
        "investigation_due_at": (
            today() + timedelta(days=DISPUTE_INVESTIGATION_DAYS)).isoformat(),
        "resolved_at": None,
        "resolution_outcome": None,
        "status": "OPEN",
    })
    db.disputes[rec["id"]] = rec

    # credit-reporting freeze fires only when the debt was actually furnished
    # to a bureau (PRD 3.6)
    placement = active_agency_placement(account_id)
    if placement is not None and placement["credit_reported_at"] is not None:
        placement["status"] = "CLOSED_DISPUTE"
        touch(placement)
        account["credit_reporting_status"] = "FROZEN_BY_DISPUTE"
        touch(account)
    return ok_object(serialize_dispute(rec), 201)


@bp.get("/self-pay/patient-disputes/<dispute_id>")
def get_dispute(dispute_id):
    authenticate(_READ_ROLES)
    return ok_object(serialize_dispute(get_dispute_or_404(dispute_id)))


@bp.get("/self-pay/accounts/<account_id>/patient-disputes")
def list_disputes_for_account(account_id):
    authenticate(_READ_ROLES)
    from routes_accounts import get_account_or_404
    get_account_or_404(account_id)
    items = [d for d in db.disputes.values() if d["account_id"] == account_id]
    page, meta = paginate(items)
    return ok_list([serialize_dispute(d) for d in page], meta)


@bp.post("/self-pay/patient-disputes/<dispute_id>/resolve")
def resolve_dispute(dispute_id):
    authenticate([ROLE_OFFICER])
    d = get_dispute_or_404(dispute_id)
    b = get_body()
    outcome = req_enum(b, "resolution_outcome", ("UPHELD_PATIENT", "UPHELD_PROVIDER"))
    if d["status"] != "OPEN":
        raise invalid_state("only an OPEN dispute can be resolved")
    d["status"] = "RESOLVED"
    d["resolution_outcome"] = outcome
    d["resolved_at"] = now_iso()
    touch(d)

    account = db.accounts.get(d["account_id"])
    if account is not None:
        if outcome == "UPHELD_PATIENT":
            account["current_balance_cents"] = max(
                0, account["current_balance_cents"] - d["dispute_amount_cents"])
            if account["credit_reporting_status"] == "FROZEN_BY_DISPUTE":
                account["credit_reporting_status"] = "REPORTED"
            touch(account)
        else:  # UPHELD_PROVIDER: balance stands; credit reverts pre-dispute
            if account["credit_reporting_status"] == "FROZEN_BY_DISPUTE":
                # the freeze only fires once furnished to a bureau, so the
                # pre-dispute value is REPORTED
                account["credit_reporting_status"] = "REPORTED"
            touch(account)
    return ok_object(serialize_dispute(d))
