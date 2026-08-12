"""Invoices: finalize (final bed-night variant + incidentals) and payment
(PRD 3.9)."""
from flask import Blueprint, request

from authz import ADMIN, FINANCE, require_roles
from calc import final_bed_night_subtotal
from db import store
from errors import ApiError, invalid_state
from respond import success
from serialize import ser_invoice
from store_ops import get_or_404, json_body, paginate, req_int, sorted_by_creation, touch

bp = Blueprint("invoices", __name__)

READ_ROLES = [ADMIN, FINANCE]


@bp.route("/invoices", methods=["GET"])
def list_invoices():
    require_roles(READ_ROLES)
    group_id = request.args.get("group_id")
    status = request.args.get("status")
    items = [v for v in store.invoices.values()
             if (group_id is None or v["group_id"] == group_id)
             and (status is None or v["status"] == status)]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_invoice(v) for v in page], response_type="array", pagination=pagination)


@bp.route("/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    require_roles(READ_ROLES)
    return success(ser_invoice(get_or_404(store.invoices, iid)))


@bp.route("/invoices/<iid>/finalize", methods=["POST"])
def finalize_invoice(iid):
    require_roles([FINANCE, ADMIN])
    v = get_or_404(store.invoices, iid)
    g = store.groups[v["group_id"]]
    if v["status"] != "PROVISIONAL" or g["status"] != "DEPARTED":
        raise ApiError("ERR_INVOICE_NOT_FINALIZABLE", 409,
                       "Invoice must be PROVISIONAL and the group DEPARTED to finalize")
    final_subtotal = final_bed_night_subtotal(g)
    linen_charge = sum(i["loss_charge_cents"] for i in store.linen_issues.values()
                       if i["group_id"] == g["id"])
    key_charge = sum(
        (k["late_fee_cents"] or 0) + (k["lost_fee_cents"] or 0)
        for k in store.key_credentials.values() if k["group_id"] == g["id"]
    )
    damage_charge = sum(
        d["assessed_total_cents"] for d in store.damage_assessments.values()
        if d["group_id"] == g["id"] and d["status"] == "BILLED"
    )
    total = final_subtotal + linen_charge + key_charge + damage_charge
    v["final_bed_night_subtotal_cents"] = final_subtotal
    v["linen_charge_cents"] = linen_charge
    v["key_charge_cents"] = key_charge
    v["damage_charge_cents"] = damage_charge
    v["total_cents"] = total
    v["balance_due_cents"] = total - g["deposit_paid_cents"]
    v["finalized_at"] = store.clock
    v["status"] = "FINALIZED"
    touch(v)
    return success(ser_invoice(v))


@bp.route("/invoices/<iid>/record-payment", methods=["POST"])
def record_payment(iid):
    require_roles([FINANCE, ADMIN])
    v = get_or_404(store.invoices, iid)
    data = json_body()
    amount = req_int(data, "amount_cents")
    if v["status"] in ("PAID", "VOID"):
        raise ApiError("ERR_INVOICE_ALREADY_PAID", 409,
                       "Invoice is already PAID or VOID")
    if v["status"] != "FINALIZED":
        raise invalid_state("Invoice must be FINALIZED to record payment")
    if amount != v["balance_due_cents"]:
        raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH", 422,
                       "amount_cents must equal balance_due_cents exactly")
    v["status"] = "PAID"
    v["paid_at"] = store.clock
    touch(v)
    g = store.groups[v["group_id"]]
    if g["status"] == "DEPARTED":
        g["status"] = "CLOSED"
        touch(g)
    return success(ser_invoice(v))
