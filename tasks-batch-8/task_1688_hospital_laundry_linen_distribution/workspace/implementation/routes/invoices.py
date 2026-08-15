"""VendorInvoice endpoints (PRD 3.6)."""
from decimal import Decimal

from flask import Blueprint, request

import services
import store
from auth import authenticate, authorize, ALL_ROLES
from errors import ERR_ALREADY_TERMINAL, ERR_CONTRACT_CAP_EXCEEDED, \
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_MANIFEST_ALREADY_INVOICED, \
    ERR_MANIFEST_NOT_RECONCILED, ERR_NOT_FOUND, ERR_SEGREGATION_OF_DUTIES, \
    raise_err
from serializers import invoice_out
from util import body_json, bump, fk_ref, get_or_404, list_response, new_record, \
    req_dt, req_int, rhu0, rhu2, dec, success_object

bp = Blueprint("invoices", __name__)


@bp.route("/invoices", methods=["POST"])
def create_invoice():
    """provisional_invoice_total calc: per-line round-half-up BEFORE summation."""
    uid, role = authenticate()
    authorize(role, ["LinenManager"])
    body = body_json()

    fac = fk_ref(body, "facility_id", store.facilities, "Facility")

    raw_ids = body.get("manifest_ids")
    if not isinstance(raw_ids, list):
        raise_err(ERR_INVALID_REQUEST, "manifest_ids is required and must be a list")
    mans = []
    for mid in raw_ids:
        m = store.manifests.get(mid) if isinstance(mid, str) else None
        if m is None:
            raise_err(ERR_NOT_FOUND, "SoiledManifest not found: %s" % mid)
        if m["facility_id"] != fac["id"]:
            raise_err(ERR_NOT_FOUND,
                      "SoiledManifest %s is outside facility %s" % (mid, fac["id"]))
        mans.append(m)

    period_start = req_dt(body, "period_start")
    period_end = req_dt(body, "period_end")
    if period_end <= period_start:
        raise_err(ERR_INVALID_REQUEST, "period_end must be after period_start")
    apd = req_int(body, "period_adjusted_patient_days")
    if apd < 1:
        raise_err(ERR_INVALID_REQUEST, "period_adjusted_patient_days must be >= 1")

    # state guard (priority 7): manifests must be RETURNED or RECONCILED
    for m in mans:
        if m["status"] not in ("RETURNED", "RECONCILED"):
            raise_err(ERR_INVALID_STATE,
                      "manifest %s is %s; invoices require RETURNED or RECONCILED"
                      % (m["id"], m["status"]))

    # referential (priority 10)
    for m in mans:
        if m["invoice_id"] is not None:
            raise_err(ERR_MANIFEST_ALREADY_INVOICED,
                      "manifest %s already belongs to invoice %s"
                      % (m["id"], m["invoice_id"]))

    total = 0
    for m in mans:
        for line in m["lines"]:
            line_cents = rhu0(dec(line["weight_lbs"]) * dec(fac["rate_per_lb_cents"]))
            if line["isolation_flag"]:
                line_cents += rhu0(dec(line_cents) * dec(fac["isolation_surcharge_pct"]))
            total += line_cents

    rec = new_record()
    rec.update({
        "facility_id": fac["id"],
        "period_start": period_start,
        "period_end": period_end,
        "period_adjusted_patient_days": apd,
        "status": "PROVISIONAL",
        "provisional_total_cents": total,
        "final_total_cents": None,
        "credit_total_cents": 0,
        "billed_total_cents": None,
        "cost_per_apd_cents": None,
        "created_by_user_id": uid,
        "finalized_by_user_id": None,
    })
    store.invoices[rec["id"]] = rec

    for m in mans:
        m["invoice_id"] = rec["id"]
        bump(m)

    return success_object(invoice_out(rec), 201)


@bp.route("/invoices/<invoice_id>", methods=["GET"])
def get_invoice(invoice_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.invoices, invoice_id, "VendorInvoice")
    return success_object(invoice_out(rec))


@bp.route("/invoices", methods=["GET"])
def list_invoices():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    records = list(store.invoices.values())
    facility_id = request.args.get("facility_id")
    if facility_id is not None:
        records = [r for r in records if r["facility_id"] == facility_id]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records, invoice_out)


@bp.route("/invoices/<invoice_id>/finalize", methods=["POST"])
def finalize_invoice(invoice_id):
    """final_invoice_total calc: per-piece rates first, then the final total,
    then credits, then billed (pinned evaluation order, PRD 3.6)."""
    uid, role = authenticate()
    authorize(role, ["LinenManager"])
    inv = get_or_404(store.invoices, invoice_id, "VendorInvoice")
    body_json()

    # segregation of duties (priority 3)
    if uid == inv["created_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES,
                  "the invoice creator may not finalize the same invoice")

    # state guard (priority 7)
    if inv["status"] == "SETTLED":
        raise_err(ERR_ALREADY_TERMINAL, "invoice is SETTLED (terminal)")
    if inv["status"] not in ("PROVISIONAL", "DISPUTED"):
        raise_err(ERR_INVALID_STATE,
                  "finalize requires status PROVISIONAL or DISPUTED, got %s"
                  % inv["status"])

    mans = services.manifests_of_invoice(inv["id"])
    for m in mans:
        if m["status"] != "RECONCILED":
            raise_err(ERR_MANIFEST_NOT_RECONCILED,
                      "manifest %s is %s; finalize requires RECONCILED"
                      % (m["id"], m["status"]))

    fac = store.facilities.get(inv["facility_id"])

    total = 0
    rate_cache = {}
    for m in mans:
        for rl in m["returned_lines"]:
            stock = store.stocks[rl["stock_id"]]
            if stock["id"] not in rate_cache:
                rate_cache[stock["id"]] = services.per_piece_rate_cents(stock, fac)
            line_cents = rl["pieces"] * rate_cache[stock["id"]]
            line = services.find_manifest_line(m, rl["stock_id"])
            if line is not None and line["isolation_flag"]:
                line_cents += rhu0(dec(line_cents) * dec(fac["isolation_surcharge_pct"]))
            total += line_cents

    # fiscal cap (priority 11)
    cap = fac["monthly_cap_cents"]
    if cap is not None and total > cap:
        raise_err(ERR_CONTRACT_CAP_EXCEEDED,
                  "final_total_cents %s exceeds monthly_cap_cents %s" % (total, cap))

    inv["final_total_cents"] = total
    inv["billed_total_cents"] = total - inv["credit_total_cents"]
    inv["cost_per_apd_cents"] = rhu2(
        Decimal(inv["billed_total_cents"]) / Decimal(inv["period_adjusted_patient_days"]))
    inv["finalized_by_user_id"] = uid
    inv["status"] = "FINALIZED"
    bump(inv)
    return success_object(invoice_out(inv), 200)


@bp.route("/invoices/<invoice_id>/dispute", methods=["POST"])
def dispute_invoice(invoice_id):
    _, role = authenticate()
    authorize(role, ["LaundryVendor"])
    inv = get_or_404(store.invoices, invoice_id, "VendorInvoice")
    body_json()  # optional reason

    if inv["status"] == "SETTLED":
        raise_err(ERR_ALREADY_TERMINAL, "invoice is SETTLED (terminal)")
    if inv["status"] != "FINALIZED":
        raise_err(ERR_INVALID_STATE,
                  "dispute requires status FINALIZED, got %s" % inv["status"])

    inv["status"] = "DISPUTED"
    bump(inv)
    return success_object(invoice_out(inv), 200)


@bp.route("/invoices/<invoice_id>/settle", methods=["POST"])
def settle_invoice(invoice_id):
    _, role = authenticate()
    authorize(role, ["LinenManager"])
    inv = get_or_404(store.invoices, invoice_id, "VendorInvoice")
    body_json()

    if inv["status"] == "SETTLED":
        raise_err(ERR_ALREADY_TERMINAL, "invoice is SETTLED (terminal)")
    if inv["status"] != "FINALIZED":
        raise_err(ERR_INVALID_STATE,
                  "settle requires status FINALIZED, got %s" % inv["status"])

    inv["status"] = "SETTLED"
    bump(inv)
    return success_object(invoice_out(inv), 200)
