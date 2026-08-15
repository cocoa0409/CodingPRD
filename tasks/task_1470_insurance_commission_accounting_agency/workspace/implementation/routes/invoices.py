"""PremiumInvoice endpoints: list per policy, get, payments, reversals."""
from flask import Blueprint

from db import DB
from errors import ApiError
from middleware import auth, ADMIN_ACCT, ALL_ROLES
from response import ok
from services import carrier_id_of_policy, ser_invoice, touch
from util import apply_filters, as_pos_int, get_body, is_int, req, respond_list

bp = Blueprint("invoices", __name__)


def _carrier_for_invoice(inv):
    policy = DB["policies"].get(inv["policy_id"])
    if policy is None:
        return None
    return DB["carriers"].get(carrier_id_of_policy(policy))


@bp.get("/agency/policies/<policyId>/invoices")
def list_invoices(policyId):
    auth(ALL_ROLES)
    policy = DB["policies"].get(policyId)
    if policy is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Policy not found")
    items = [i for i in DB["invoices"].values() if i["policy_id"] == policy["id"]]
    items = apply_filters(items, {"status": "status"})
    return respond_list(items, ser_invoice)


@bp.get("/agency/premium-invoices/<invoiceId>")
def get_invoice(invoiceId):
    auth(ALL_ROLES)
    inv = DB["invoices"].get(invoiceId)
    if inv is None:
        raise ApiError("ERR_NOT_FOUND", 404, "PremiumInvoice not found")
    return ok(ser_invoice(inv))


@bp.post("/agency/premium-invoices/<invoiceId>/payments")
def record_payment(invoiceId):
    auth(ADMIN_ACCT)
    inv = DB["invoices"].get(invoiceId)
    if inv is None:
        raise ApiError("ERR_NOT_FOUND", 404, "PremiumInvoice not found")
    # Priority 4: PAID is terminal.
    if inv["status"] == "PAID":
        raise ApiError("ERR_INVALID_STATE", 409, "Invoice is already PAID")
    data = get_body()
    # Priority 9: payment must not exceed the remaining balance.
    amount = data.get("amount_cents")
    remaining = inv["amount_cents"] - inv["paid_total_cents"]
    if is_int(amount) and amount > 0 and amount > remaining:
        raise ApiError("ERR_OVERPAYMENT", 409, "Payment exceeds the remaining balance")
    # Priority 10: shape.
    amount = as_pos_int(req(data, "amount_cents"), "amount_cents")
    # Effects: invoice paid_total grows; the carrier trust grows by the same.
    inv["paid_total_cents"] += amount
    carrier = _carrier_for_invoice(inv)
    if carrier is not None:
        carrier["trust_balance_cents"] += amount
        touch(carrier)
    if inv["paid_total_cents"] == inv["amount_cents"]:
        inv["status"] = "PAID"
    touch(inv)
    # Grace cure: a payment that flips the invoice to PAID returns the policy
    # to ACTIVE when it has no other DELINQUENT invoices.
    policy = DB["policies"].get(inv["policy_id"])
    if (
        inv["status"] == "PAID"
        and policy is not None
        and policy["status"] == "GRACE"
        and not any(
            i["policy_id"] == policy["id"] and i["status"] == "DELINQUENT"
            for i in DB["invoices"].values()
        )
    ):
        policy["status"] = "ACTIVE"
        touch(policy)
    return ok(ser_invoice(inv))


@bp.post("/agency/premium-invoices/<invoiceId>/reverse-payments")
def reverse_payments(invoiceId):
    auth(ADMIN_ACCT)
    inv = DB["invoices"].get(invoiceId)
    if inv is None:
        raise ApiError("ERR_NOT_FOUND", 404, "PremiumInvoice not found")
    # Priority 4: PAID is terminal.
    if inv["status"] == "PAID":
        raise ApiError("ERR_INVALID_STATE", 409, "Invoice is already PAID")
    # Priority 9: fiscal limits.
    if inv["paid_total_cents"] <= 0:
        raise ApiError("ERR_NOTHING_TO_REVERSE", 409, "Invoice has no payments to reverse")
    carrier = _carrier_for_invoice(inv)
    trust = carrier["trust_balance_cents"] if carrier is not None else 0
    if trust < inv["paid_total_cents"]:
        raise ApiError(
            "ERR_TRUST_INSUFFICIENT",
            409,
            "Reversal would drive the carrier trust balance negative",
        )
    # Effects: trust debited, payments unwound, invoice keeps its current status.
    if carrier is not None:
        carrier["trust_balance_cents"] -= inv["paid_total_cents"]
        touch(carrier)
    inv["paid_total_cents"] = 0
    touch(inv)
    return ok(ser_invoice(inv))
