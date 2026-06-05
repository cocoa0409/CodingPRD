"""Invoice endpoints (PRD §3.6, §3.7)."""
from flask import request, Blueprint

from db import db, base_record, touch
from errors import err
from middleware import authenticate, require_owner, require_roles
from response import success
from services import billing
from services import serializers as ser
from services.common import get_json_body, paginate, parse_pagination, require_fields

bp = Blueprint("invoices", __name__)


def _new_invoice_record(account_id, period_start, period_end):
    rec = base_record()
    rec.update(
        {
            "account_id": account_id,
            "period_start": period_start,
            "period_end": period_end,
            "status": "DRAFT",
            "base_fee_cents": 0,
            "weight_charge_cents": 0,
            "contamination_surcharge_cents": 0,
            "credit_cents": 0,
            "total_cents": 0,
            "diversion_penalty_cents": 0,
            "balance_cents": 0,
        }
    )
    return rec


@bp.route("/accounts/<account_id>/invoices", methods=["POST"])
def create_invoice(account_id):
    _, role = authenticate()
    require_roles(role, {"Billing"})
    account = db.accounts.get(account_id)
    if account is None:
        raise err("ERR_NOT_FOUND", "Account not found.")
    body = get_json_body()
    require_fields(body, ["period_start", "period_end", "expected_account_version"])
    # Request shape (period sanity) — ERR_INVALID_PERIOD is a business_temporal
    # check (priority 14), after request shape but it concerns the period itself.
    if not (body["period_start"] < body["period_end"]):
        raise err("ERR_INVALID_PERIOD", "period_start must be strictly before period_end.")
    # OCC on the account version.
    if body["expected_account_version"] != account["version"]:
        raise err("ERR_STALE_VERSION", "Account version is stale.")

    rec = _new_invoice_record(account_id, body["period_start"], body["period_end"])
    db.invoices[rec["id"]] = rec
    # Creating a draft invoice advances the account's version.
    touch(account)
    return success(ser.invoice(rec), status=201)


@bp.route("/invoices/<invoice_id>", methods=["GET"])
def get_invoice(invoice_id):
    user_id, role = authenticate()
    require_roles(role, {"Billing", "ResidentAccount"})
    rec = db.invoices.get(invoice_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Invoice not found.")
    require_owner(role, user_id, rec["account_id"])
    return success(ser.invoice(rec), status=200)


@bp.route("/invoices", methods=["GET"])
def list_invoices():
    user_id, role = authenticate()
    require_roles(role, {"Billing", "ResidentAccount"})
    parse_pagination()
    items = list(db.invoices.values())
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    if role == "ResidentAccount":
        # Residents only see their own invoices.
        items = [i for i in items if i["account_id"] == user_id]
    if account_id is not None:
        items = [i for i in items if i["account_id"] == account_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    page, pagination = paginate(items)
    return success([ser.invoice(i) for i in page], status=200, pagination=pagination)


@bp.route("/invoices/<invoice_id>/issue", methods=["POST"])
def issue_invoice(invoice_id):
    _, role = authenticate()
    require_roles(role, {"Billing"})
    rec = db.invoices.get(invoice_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Invoice not found.")
    if rec["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT invoice can be issued.")
    account = db.accounts.get(rec["account_id"])
    if account is None or account["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "Invoice account must be ACTIVE or SUSPENDED to issue.")
    # Absorb eligible PENDING credits first so credit_cents reflects them.
    billing.absorb_pending_credits(rec)
    billing.compute_charges(rec)
    rec["status"] = "ISSUED"
    touch(rec)
    billing.recompute_account_balance(rec["account_id"])
    return success(ser.invoice(rec), status=200)


@bp.route("/invoices/<invoice_id>/dispute", methods=["POST"])
def dispute_invoice(invoice_id):
    user_id, role = authenticate()
    require_roles(role, {"ResidentAccount"})
    rec = db.invoices.get(invoice_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Invoice not found.")
    require_owner(role, user_id, rec["account_id"])
    if rec["status"] != "ISSUED":
        raise err("ERR_INVALID_STATE", "Only an ISSUED invoice can be disputed.")
    rec["status"] = "DISPUTED"
    touch(rec)
    return success(ser.invoice(rec), status=200)


@bp.route("/invoices/<invoice_id>/resolve", methods=["POST"])
def resolve_invoice(invoice_id):
    _, role = authenticate()
    require_roles(role, {"Billing"})
    rec = db.invoices.get(invoice_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Invoice not found.")
    if rec["status"] != "DISPUTED":
        raise err("ERR_INVALID_STATE", "Only a DISPUTED invoice can be resolved.")
    billing.compute_charges(rec)
    rec["status"] = "ISSUED"
    touch(rec)
    return success(ser.invoice(rec), status=200)


@bp.route("/invoices/<invoice_id>/pay", methods=["POST"])
def pay_invoice(invoice_id):
    _, role = authenticate()
    require_roles(role, {"Billing"})
    rec = db.invoices.get(invoice_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Invoice not found.")
    if rec["status"] != "ISSUED":
        raise err("ERR_INVALID_STATE", "Only an ISSUED invoice can be paid.")
    rec["status"] = "PAID"
    rec["balance_cents"] = 0
    touch(rec)
    billing.recompute_account_balance(rec["account_id"])
    return success(ser.invoice(rec), status=200)


@bp.route("/invoices/<invoice_id>/void", methods=["POST"])
def void_invoice(invoice_id):
    _, role = authenticate()
    require_roles(role, {"Billing"})
    rec = db.invoices.get(invoice_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Invoice not found.")
    if rec["status"] not in ("DRAFT", "ISSUED", "DISPUTED"):
        raise err("ERR_INVALID_STATE", "Invoice cannot be voided from its current state.")
    rec["status"] = "VOID"
    rec["balance_cents"] = 0
    touch(rec)
    # Release applied credits back to PENDING.
    billing.release_applied_credits(rec)
    billing.recompute_account_balance(rec["account_id"])
    return success(ser.invoice(rec), status=200)
