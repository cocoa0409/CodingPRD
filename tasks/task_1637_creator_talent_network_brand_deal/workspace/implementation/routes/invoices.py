"""Invoice endpoints: list, get, issue (creates ACCRUED payout), record
payment (late fee + cascades), void (compensating entry)."""

import datetime as _dt

from flask import Blueprint, request

import db
import errors as err
import response as resp
from middleware import require_roles, require_owner
from services import calc, helpers as H

bp = Blueprint("invoices", __name__)


@bp.route("/invoices", methods=["GET"])
@require_roles("FinanceAdmin", "BrandManager", "Brand")
def list_invoices(actor):
    items = list(db.invoices.values())
    if actor.role == "Brand":
        items = [i for i in items if i["brand_id"] == actor.user_id]
    deal_id = request.args.get("deal_id")
    brand_id = request.args.get("brand_id")
    status = request.args.get("status")
    if deal_id is not None:
        items = [i for i in items if i["deal_id"] == deal_id]
    if brand_id is not None:
        items = [i for i in items if i["brand_id"] == brand_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    return resp.paginate(items, request.args)


@bp.route("/invoices/<iid>", methods=["GET"])
@require_roles("FinanceAdmin", "BrandManager", "Brand")
def get_invoice(actor, iid):
    invoice = H.get_or_404(db.invoices, iid, "invoice")
    if actor.role == "Brand":
        require_owner(actor, invoice["brand_id"], "invoice")
    return resp.ok(invoice)


@bp.route("/invoices/<iid>/issue", methods=["POST"])
@require_roles("FinanceAdmin")
def issue_invoice(actor, iid):
    invoice = H.get_or_404(db.invoices, iid, "invoice")
    H.body()
    if invoice["status"] in ("PAID", "VOID"):
        raise err.already_terminal(f"Invoice is {invoice['status']}")
    if invoice["status"] != "DRAFT":
        raise err.invalid_state("Only a DRAFT invoice can be issued")

    now = db.get_clock()
    invoice["status"] = "ISSUED"
    invoice["issued_at"] = db.iso_format(now)
    invoice["due_date"] = db.iso_format(
        now + _dt.timedelta(days=H.INVOICE_NET_DAYS))
    invoice["issued_by_user_id"] = actor.user_id
    H.touch(invoice)

    # Ledger sync: brand outstanding += total.
    brand = db.brands.get(invoice["brand_id"])
    if brand is not None:
        brand["outstanding_balance_cents"] = (
            int(brand.get("outstanding_balance_cents", 0))
            + int(invoice["total_cents"]))
        H.touch(brand)

    # Cascade: create the ACCRUED payout with ESTIMATED commission.
    deal = db.deals.get(invoice["deal_id"])
    creator_id = deal["creator_id"] if deal else None
    creator = db.creators.get(creator_id) if creator_id else None
    gross = int(invoice["fee_line_cents"]) + int(invoice["bonus_line_cents"])
    lifetime = int(creator.get("lifetime_billed_cents", 0)) if creator else 0
    rate_bps, commission_cents, net_cents = calc.commission(lifetime, gross)

    payout = H.new_entity()
    payout.update({
        "invoice_id": invoice["id"],
        "deal_id": invoice["deal_id"],
        "creator_id": creator_id,
        "status": "ACCRUED",
        "gross_cents": gross,
        "commission_rate_bps": rate_bps,
        "commission_cents": commission_cents,
        "net_cents": net_cents,
        "payout_due_at": None,
        "released_by_user_id": None,
        "released_at": None,
    })
    db.payouts[payout["id"]] = payout

    return resp.ok(invoice)


@bp.route("/invoices/<iid>/record-payment", methods=["POST"])
@require_roles("FinanceAdmin")
def record_payment(actor, iid):
    invoice = H.get_or_404(db.invoices, iid, "invoice")
    payload = H.body()
    H.req_fields(payload, ["amount_cents"])
    amount = H.require_int(payload, "amount_cents", minimum=0)

    if invoice["status"] in ("PAID", "VOID"):
        raise err.already_terminal(f"Invoice is {invoice['status']}")
    if invoice["status"] not in ("ISSUED", "OVERDUE"):
        raise err.invalid_state(
            "Payment can be recorded only on ISSUED or OVERDUE invoices")

    now = db.get_clock()
    if invoice["status"] == "OVERDUE":
        due = db.parse_iso(invoice["due_date"])
        invoice["late_fee_cents"] = calc.late_fee(now, due,
                                                  int(invoice["total_cents"]))
    expected_amount = int(invoice["total_cents"]) + int(
        invoice.get("late_fee_cents") or 0)
    if amount != expected_amount:
        raise err.ApiError(err.ERR_PAYMENT_AMOUNT_MISMATCH,
                           "amount_cents must equal total_cents + "
                           "late_fee_cents", 422)

    invoice["status"] = "PAID"
    invoice["paid_at"] = db.iso_format(now)
    H.touch(invoice)

    # Ledger sync: brand outstanding -= total.
    brand = db.brands.get(invoice["brand_id"])
    if brand is not None:
        brand["outstanding_balance_cents"] = (
            int(brand.get("outstanding_balance_cents", 0))
            - int(invoice["total_cents"]))
        H.touch(brand)

    # Cascade link 1: payout ACCRUED -> PAYABLE, payout_due_at = paid_at + 7d.
    due_at = now + _dt.timedelta(days=H.PAYOUT_NET_DAYS)
    for po in db.payouts.values():
        if po["invoice_id"] == invoice["id"] and po["status"] == "ACCRUED":
            po["status"] = "PAYABLE"
            po["payout_due_at"] = db.iso_format(due_at)
            H.touch(po)

    # Cascade link 2: creator.lifetime_billed_cents += fee_line_cents.
    deal = db.deals.get(invoice["deal_id"])
    creator = db.creators.get(deal["creator_id"]) if deal else None
    if creator is not None:
        creator["lifetime_billed_cents"] = (
            int(creator.get("lifetime_billed_cents", 0))
            + int(invoice["fee_line_cents"]))
        H.touch(creator)

    return resp.ok(invoice)


@bp.route("/invoices/<iid>/void", methods=["POST"])
@require_roles("FinanceAdmin")
def void_invoice(actor, iid):
    invoice = H.get_or_404(db.invoices, iid, "invoice")
    payload = H.body()
    H.req_fields(payload, ["void_reason"])
    void_reason = H.require_str(payload, "void_reason")

    if invoice["status"] in ("PAID", "VOID"):
        raise err.already_terminal(f"Invoice is {invoice['status']}")
    if invoice["status"] not in ("DRAFT", "ISSUED"):
        raise err.invalid_state("Only DRAFT or ISSUED invoices can be voided")

    was_issued = invoice["status"] == "ISSUED"
    invoice["status"] = "VOID"
    invoice["void_reason"] = void_reason
    H.touch(invoice)

    if was_issued:
        # Compensating entry: brand outstanding -= total.
        brand = db.brands.get(invoice["brand_id"])
        if brand is not None:
            brand["outstanding_balance_cents"] = (
                int(brand.get("outstanding_balance_cents", 0))
                - int(invoice["total_cents"]))
            H.touch(brand)
        # Cascade: payout ACCRUED -> VOIDED.
        for po in db.payouts.values():
            if po["invoice_id"] == invoice["id"] and po["status"] == "ACCRUED":
                po["status"] = "VOIDED"
                H.touch(po)

    return resp.ok(invoice)
