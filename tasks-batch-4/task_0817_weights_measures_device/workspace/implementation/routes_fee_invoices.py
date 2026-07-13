from flask import request

from core import (store, authorize, get_body, respond_object, respond_list,
                  touch, serialize, serialize_many, sort_by_created, paginate,
                  ApiError)
from lookups import get_fee_invoice
from services import apply_est_side_effect


def register(app):

    @app.route("/fee-invoices/<fid>", methods=["GET"])
    def get_fee_invoice_route(fid):
        authorize(["ProgramAdmin", "Establishment"])
        inv = get_fee_invoice(fid)
        return respond_object(serialize(inv), 200)

    @app.route("/fee-invoices", methods=["GET"])
    def list_fee_invoices():
        authorize(["ProgramAdmin", "Establishment"])
        establishment_id = request.args.get("establishment_id")
        device_id = request.args.get("device_id")
        status = request.args.get("status")
        items = list(store.fee_invoices.values())
        if establishment_id is not None:
            items = [i for i in items if i["establishment_id"] == establishment_id]
        if device_id is not None:
            items = [i for i in items if i["device_id"] == device_id]
        if status is not None:
            items = [i for i in items if i["status"] == status]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return respond_list(serialize_many(page), limit, offset, total, 200)

    @app.route("/fee-invoices/<fid>/pay", methods=["POST"])
    def pay_fee_invoice(fid):
        role, uid = authorize(["Establishment", "ProgramAdmin"])
        get_body(optional=True)
        inv = get_fee_invoice(fid)
        if role == "Establishment" and uid != inv["establishment_id"]:
            raise ApiError("ERR_OWNERSHIP_VIOLATION",
                           "Establishment may only pay its own invoices")
        if inv["status"] != "DUE":
            raise ApiError("ERR_INVOICE_NOT_PAYABLE", "Invoice is not payable")
        inv["status"] = "PAID"
        touch(inv)
        est = store.establishments.get(inv["establishment_id"])
        if est is not None:
            apply_est_side_effect(est)
        return respond_object(serialize(inv), 200)
