"""Routes: FeeInvoice (PRD 3.8)."""
from flask import Blueprint, request

from auth import require_roles, ALL_ROLES, uid, check_issuer_owns
from envelope import ok, list_response, get_body, public
from errors import (raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE,
                    ERR_ALREADY_TERMINAL, ERR_SEGREGATION_OF_DUTIES,
                    ERR_NO_EXTRAORDINARY_BASIS, ERR_INVALID_REQUEST)
from store import DB, LOCK, new_entity, mutate
from validate import req_str, req_enum, req_date, opt_num, opt_str, is_num
from calc import extraordinary_fee_amount

bp = Blueprint("fees", __name__)

INVOICE_TERMINAL = ("PAID", "VOID")


def _compute_amount(ind, invoice_type, hours):
    if invoice_type == "EXTRAORDINARY_SERVICE":
        return extraordinary_fee_amount(ind, hours)
    return ind["annual_admin_fee_cents"]


@bp.route("/fee-invoices", methods=["POST"])
@require_roles("TrustOfficer")
def create_invoice():
    body = get_body()
    with LOCK:
        indenture_id = body.get("indenture_id")
        ind = DB["indentures"].get(indenture_id) if isinstance(indenture_id, str) else None
        if ind is None:
            raise_err(ERR_NOT_FOUND, "Indenture not found")
        itype = body.get("invoice_type")
        period_end = body.get("service_period_end")
        # Rule 8: extraordinary-service basis.
        if itype == "EXTRAORDINARY_SERVICE":
            from validate import parse_date_strict, parse_datetime
            end_d = parse_date_strict(period_end)
            if end_d is not None:
                has_basis = False
                for c in DB["default_cases"].values():
                    if (c["indenture_id"] == ind["id"]
                            and c["status"] in ("CONFIRMED", "CURED", "WAIVED",
                                                "ACCELERATED")):
                        declared = parse_datetime(c.get("declared_at"))
                        if declared is not None and declared.date() <= end_d:
                            has_basis = True
                            break
                if not has_basis:
                    raise_err(ERR_NO_EXTRAORDINARY_BASIS,
                              "No qualifying default case for extraordinary billing")
        # Rule 26: shape.
        req_str(body, "indenture_id")
        itype = req_enum(body, "invoice_type",
                         ["ANNUAL_ADMIN", "EXTRAORDINARY_SERVICE"])
        start = req_date(body, "service_period_start")
        period_end = req_date(body, "service_period_end")
        desc = req_str(body, "description")
        hours = opt_num(body, "extraordinary_hours")
        if itype == "EXTRAORDINARY_SERVICE" and hours is None:
            raise_err(ERR_INVALID_REQUEST,
                      "extraordinary_hours is required for EXTRAORDINARY_SERVICE")
        e = new_entity("fee_invoices")
        e.update({
            "indenture_id": indenture_id,
            "invoice_type": itype,
            "service_period_start": start,
            "service_period_end": period_end,
            "extraordinary_hours": hours,
            "description": desc,
            "amount_cents": _compute_amount(ind, itype, hours),
            "status": "DRAFT",
            "drafted_by_user_id": uid(),
            "issued_by_user_id": None,
        })
    return ok(public(e), 201)


@bp.route("/fee-invoices", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_invoices():
    return list_response(DB["fee_invoices"].values(), {
        "indenture_id": request.args.get("indenture_id"),
        "status": request.args.get("status"),
        "invoice_type": request.args.get("invoice_type"),
    })


@bp.route("/fee-invoices/<fid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_invoice(fid):
    e = DB["fee_invoices"].get(fid)
    if e is None:
        raise_err(ERR_NOT_FOUND, "FeeInvoice not found")
    return ok(public(e))


@bp.route("/fee-invoices/<fid>/issue", methods=["POST"])
@require_roles("TrustManager")
def issue_invoice(fid):
    with LOCK:
        inv = DB["fee_invoices"].get(fid)
        if inv is None:
            raise_err(ERR_NOT_FOUND, "FeeInvoice not found")
        if inv["status"] in INVOICE_TERMINAL:
            raise_err(ERR_ALREADY_TERMINAL,
                      "Invoice is terminal (%s)" % inv["status"])
        if inv["status"] not in ("DRAFT", "AMENDED"):
            raise_err(ERR_INVALID_STATE,
                      "Only a DRAFT or AMENDED invoice can be issued")
        # Rule 6: segregation of duties (issuer != drafter).
        if uid() == inv["drafted_by_user_id"]:
            raise_err(ERR_SEGREGATION_OF_DUTIES,
                      "Issuer must differ from the drafting officer")
        mutate(inv, status="ISSUED", issued_by_user_id=uid())
    return ok(public(inv))


@bp.route("/fee-invoices/<fid>/pay", methods=["POST"])
@require_roles("Issuer")
def pay_invoice(fid):
    with LOCK:
        inv = DB["fee_invoices"].get(fid)
        if inv is None:
            raise_err(ERR_NOT_FOUND, "FeeInvoice not found")
        ind = DB["indentures"].get(inv["indenture_id"])
        check_issuer_owns(ind)
        if inv["status"] in INVOICE_TERMINAL:
            raise_err(ERR_ALREADY_TERMINAL,
                      "Invoice is terminal (%s)" % inv["status"])
        if inv["status"] != "ISSUED":
            raise_err(ERR_INVALID_STATE, "Only an ISSUED invoice can be paid")
        mutate(inv, status="PAID")
    return ok(public(inv))


@bp.route("/fee-invoices/<fid>/dispute", methods=["POST"])
@require_roles("Issuer")
def dispute_invoice(fid):
    with LOCK:
        inv = DB["fee_invoices"].get(fid)
        if inv is None:
            raise_err(ERR_NOT_FOUND, "FeeInvoice not found")
        ind = DB["indentures"].get(inv["indenture_id"])
        check_issuer_owns(ind)
        if inv["status"] in INVOICE_TERMINAL:
            raise_err(ERR_ALREADY_TERMINAL,
                      "Invoice is terminal (%s)" % inv["status"])
        if inv["status"] != "ISSUED":
            raise_err(ERR_INVALID_STATE,
                      "Only an ISSUED invoice can be disputed")
        mutate(inv, status="DISPUTED")
    return ok(public(inv))


@bp.route("/fee-invoices/<fid>/amend", methods=["POST"])
@require_roles("TrustOfficer")
def amend_invoice(fid):
    body = get_body()
    with LOCK:
        inv = DB["fee_invoices"].get(fid)
        if inv is None:
            raise_err(ERR_NOT_FOUND, "FeeInvoice not found")
        if inv["status"] in INVOICE_TERMINAL:
            raise_err(ERR_ALREADY_TERMINAL,
                      "Invoice is terminal (%s)" % inv["status"])
        if inv["status"] != "DISPUTED":
            raise_err(ERR_INVALID_STATE,
                      "Only a DISPUTED invoice can be amended")
        hours = opt_num(body, "extraordinary_hours")
        desc = opt_str(body, "description")
        fields = {}
        if hours is not None:
            fields["extraordinary_hours"] = hours
        if desc is not None:
            fields["description"] = desc
        ind = DB["indentures"].get(inv["indenture_id"])
        new_hours = fields.get("extraordinary_hours", inv["extraordinary_hours"])
        fields["amount_cents"] = _compute_amount(ind, inv["invoice_type"], new_hours)
        fields["status"] = "AMENDED"
        mutate(inv, **fields)
    return ok(public(inv))
