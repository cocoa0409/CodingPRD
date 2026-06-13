"""ServiceAccount endpoints + billing clock / credit / storage invoice (PRD §3.1, §3.8)."""
from flask import Blueprint, request

from db import db, stamp_create, touch
from errors import err
from middleware import get_auth, require_role
from response import object_response, array_response
from common import (
    body, serialize, paginate, sort_by_created,
    require_present, require_enum, as_int, as_str,
    get_account_or_404, active_rate_card,
)

bp = Blueprint("accounts", __name__)

COMPLIANCE_REGIMES = {"STANDARD", "FACTA", "HIPAA"}


@bp.post("/accounts")
def create_account():
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    data = body()
    require_present(data, "business_name", "compliance_regime", "billing_email")
    business_name = as_str(data["business_name"], "business_name")
    require_enum(data["compliance_regime"], COMPLIANCE_REGIMES, "compliance_regime")
    billing_email = as_str(data["billing_email"], "billing_email")

    acct = {
        "business_name": business_name,
        "compliance_regime": data["compliance_regime"],
        "billing_email": billing_email,
        "current_period_index": 0,
        "storage_credit_cents": 0,
        "status": "ACTIVE",
    }
    stamp_create(acct)
    db.accounts[acct["id"]] = acct
    return object_response(serialize(acct), 201)


@bp.get("/accounts/<account_id>")
def get_account(account_id):
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer", "AccountManager"})
    acct = get_account_or_404(account_id)
    return object_response(serialize(acct), 200)


@bp.get("/accounts")
def list_accounts():
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    items = list(db.accounts.values())
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return array_response([serialize(a) for a in page], limit, offset, total, 200)


@bp.post("/accounts/<account_id>/credit")
def add_credit(account_id):
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    acct = get_account_or_404(account_id)
    data = body()
    require_present(data, "amount_cents")
    amount = as_int(data["amount_cents"], "amount_cents")
    if amount < 0:
        raise err("ERR_INVALID_FIELD_VALUE", "amount_cents must be >= 0")
    acct["storage_credit_cents"] += amount
    touch(acct)
    return object_response(serialize(acct), 200)


@bp.post("/accounts/<account_id>/advance-period")
def advance_period(account_id):
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    acct = get_account_or_404(account_id)

    # Closing a period is a pricing operation -> requires an ACTIVE rate card.
    rate = active_rate_card(account_id)
    if rate is None:
        raise err("ERR_NO_ACTIVE_RATE_CARD", "No ACTIVE rate card on the account")

    P = acct["current_period_index"]  # the period being closed (before increment)

    # billable boxes: status in {STORED, OUT_FOR_RETRIEVAL} AND P >= stored_at_period + free_periods
    billable = [
        b for b in db.retention_boxes.values()
        if b["account_id"] == account_id
        and b["status"] in ("STORED", "OUT_FOR_RETRIEVAL")
        and P >= (b["stored_at_period"] + b["free_periods"])
    ]
    storage_line = rate["storage_rate_cents_per_box_per_period"] * len(billable)

    retrieval_line = sum(
        r["retrieval_charge_cents"]
        for r in db.retrieval_requests.values()
        if r["account_id"] == account_id and r["delivered_period"] == P
    )

    gross = storage_line + retrieval_line
    credit_applied = min(acct["storage_credit_cents"], gross)
    amount_due = gross - credit_applied  # never negative

    inv = {
        "account_id": account_id,
        "period_index": P,
        "storage_line_cents": storage_line,
        "retrieval_line_cents": retrieval_line,
        "credit_applied_cents": credit_applied,
        "amount_due_cents": amount_due,
        "status": "ISSUED",
    }
    stamp_create(inv)
    db.storage_invoices[inv["id"]] = inv

    # Consume credit and advance the clock.
    acct["storage_credit_cents"] -= credit_applied
    acct["current_period_index"] += 1
    touch(acct)

    return object_response(serialize(inv), 201)


@bp.post("/accounts/<account_id>/suspend")
def suspend_account(account_id):
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    acct = get_account_or_404(account_id)
    if acct["status"] != "ACTIVE":
        raise err("ERR_ACCOUNT_NOT_ACTIVE", "Account is not ACTIVE")
    acct["status"] = "SUSPENDED"
    touch(acct)
    return object_response(serialize(acct), 200)


@bp.post("/accounts/<account_id>/reactivate")
def reactivate_account(account_id):
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    acct = get_account_or_404(account_id)
    if acct["status"] != "SUSPENDED":
        raise err("ERR_ACCOUNT_NOT_SUSPENDED", "Account is not SUSPENDED")
    acct["status"] = "ACTIVE"
    touch(acct)
    return object_response(serialize(acct), 200)


@bp.post("/accounts/<account_id>/close")
def close_account(account_id):
    _, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    acct = get_account_or_404(account_id)
    if acct["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_ACCOUNT_NOT_CLOSABLE", "Account is not ACTIVE or SUSPENDED")
    # No retention box in INGESTED/STORED/OUT_FOR_RETRIEVAL.
    for b in db.retention_boxes.values():
        if b["account_id"] == account_id and b["status"] in (
            "INGESTED", "STORED", "OUT_FOR_RETRIEVAL"
        ):
            raise err("ERR_OUTSTANDING_BOXES", "Account has outstanding retention boxes")
    # No service order in a non-terminal state.
    terminal_orders = {"ON_SITE_SHREDDED", "DESTROYED", "CANCELLED"}
    for o in db.service_orders.values():
        if o["account_id"] == account_id and o["status"] not in terminal_orders:
            raise err("ERR_OUTSTANDING_ORDERS", "Account has outstanding service orders")
    acct["status"] = "CLOSED"
    touch(acct)
    return object_response(serialize(acct), 200)
