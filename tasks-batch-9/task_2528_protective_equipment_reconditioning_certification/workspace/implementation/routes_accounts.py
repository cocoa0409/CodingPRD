"""CustomerAccount endpoints (PRD 3.1)."""
from flask import Blueprint

import calc
import cascades
import db
import helpers
import serialize
import validate
from auth import authorize, check_account_scope
from db import touch

bp = Blueprint("accounts", __name__)


@bp.post("/customer-accounts")
def create_account():
    authorize(("PlantManager",))
    data = validate.body()
    org_name = validate.req_str(data, "org_name", min_len=1, max_len=120)
    org_type = validate.req_enum(data, "org_type", calc.ORG_TYPES)
    sport = validate.req_enum(data, "sport", calc.SPORTS)
    contact_email = validate.req_str(data, "contact_email", max_len=200)

    record = db.base_record()
    record.update({
        "org_name": org_name,
        "org_type": org_type,
        "sport": sport,
        "contact_email": contact_email,
        "status": "ACTIVE",
        "billing_hold_reason": None,
        "liability_waiver_version": None,
        "liability_waiver_signed_at": None,
        "liability_waiver_signer": None,
        "liability_waiver_status": "MISSING",
        "open_shipment_count": 0,
        "loaner_recall_due_at": None,
    })
    db.db.customer_accounts[record["id"]] = record
    return helpers.single(record, serialize.customer_account, 201)


@bp.get("/customer-accounts/<row_id>")
def get_account(row_id):
    caller = authorize(("PlantManager", "IntakeClerk", "ComplianceOfficer",
                        "CustomerContact"))
    # PRD 2.1: scope (rung 3) precedes existence (rung 5); the path id IS the
    # account being read, so a CustomerContact reaching for another program is
    # rejected before the lookup.
    check_account_scope(caller, row_id)
    return helpers.single(helpers.account(row_id), serialize.customer_account)


@bp.post("/customer-accounts/<row_id>/liability-acknowledgment")
def acknowledge_liability(row_id):
    authorize(("PlantManager", "IntakeClerk"))
    data = validate.body()
    waiver_version = validate.req_str(data, "waiver_version", max_len=40)
    signer_name = validate.req_str(data, "signer_name", max_len=200)
    record = helpers.account(row_id)

    record["liability_waiver_version"] = waiver_version
    record["liability_waiver_signer"] = signer_name
    record["liability_waiver_signed_at"] = db.now()
    cascades.refresh_waiver_status(record)
    touch(record)
    return helpers.single(record, serialize.customer_account)


@bp.post("/customer-accounts/<row_id>/billing-hold")
def set_billing_hold(row_id):
    authorize(("PlantManager",))
    data = validate.body()
    hold = validate.req_bool(data, "hold")
    reason = validate.opt_str(data, "reason", max_len=500)
    record = helpers.account(row_id)

    if hold:
        record["status"] = "BILLING_HOLD"
        record["billing_hold_reason"] = reason
    else:
        record["status"] = "ACTIVE"
        record["billing_hold_reason"] = None
    touch(record)
    return helpers.single(record, serialize.customer_account)
