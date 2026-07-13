"""Invoice assembly, issue, void and payment (PRD 3.8)."""
from flask import Blueprint, request

import db
import response
import services
import validate
from auth import endpoint
from errors import ApiError

bp = Blueprint("invoices", __name__)

INVOICE_READ_ROLES = ["AgencyAdmin", "AccountManager", "ClientReviewer"]


@bp.post("/invoices")
@endpoint(["AccountManager"])
def create_invoice():
    b = validate.body()
    client_id = validate.req_str(b, "client_id")
    campaign_id = validate.req_str(b, "campaign_id")
    retainer_id = validate.req_str(b, "retainer_id")
    billing_mode = validate.req_enum(b, "billing_mode", validate.BILLING_MODES)
    period_start = validate.req_datetime(b, "period_start")
    period_end = validate.req_datetime(b, "period_end")
    if period_end <= period_start:
        validate.bad("period_end must be strictly after period_start.")

    # Priority 6: client_id, then campaign_id, then retainer_id.
    services.must("client", client_id)
    campaign = services.must("campaign", campaign_id)
    retainer = services.must("retainer", retainer_id)

    # Priority 14: both must belong to the named advertiser.
    if campaign["client_id"] != client_id:
        validate.bad("The campaign belongs to a different advertiser.")
    if retainer["client_id"] != client_id:
        validate.bad("The retainer belongs to a different advertiser.")

    sow = services.must("sow", campaign["sow_id"])
    money, line_ids = services.assemble_invoice_lines(
        campaign, sow, billing_mode, period_start.date(), period_end.date()
    )

    # Priority 16: an invoice that assembles zero lines is not created at all.
    if money["line_count"] == 0:
        raise ApiError("ERR_INVOICE_NO_LINES")

    obj = db.base_entity()
    obj.update(
        {
            "client_id": client_id,
            "campaign_id": campaign_id,
            "retainer_id": retainer_id,
            "billing_mode": billing_mode,
            "period_start": b["period_start"],
            "period_end": b["period_end"],
            "retainer_applied_cents": 0,
            "cash_due_cents": 0,
            "amount_paid_cents": 0,
            "approval_status": "DRAFT",
            "payment_status": "UNPAID",
            "void_reason": None,
            "_billed_time_entry_ids": [],
            "_billed_vendor_cost_ids": [],
        }
    )
    obj.update(money)
    obj.update(line_ids)
    db.INVOICES[obj["id"]] = obj
    return response.created(db.public(obj))


@bp.get("/invoices/<iid>")
@endpoint(INVOICE_READ_ROLES)
def get_invoice(iid):
    return response.ok(db.public(services.must("invoice", iid)))


@bp.get("/invoices")
@endpoint(INVOICE_READ_ROLES)
def list_invoices():
    limit, offset = validate.pagination()
    client_id = request.args.get("client_id")
    campaign_id = request.args.get("campaign_id")
    retainer_id = request.args.get("retainer_id")
    approval_status = request.args.get("approval_status")
    rows = db.ordered(db.INVOICES)
    if client_id:
        rows = [i for i in rows if i["client_id"] == client_id]
    if campaign_id:
        rows = [i for i in rows if i["campaign_id"] == campaign_id]
    if retainer_id:
        rows = [i for i in rows if i["retainer_id"] == retainer_id]
    if approval_status:
        rows = [i for i in rows if i["approval_status"] == approval_status]
    return response.listing(rows, limit, offset)


@bp.post("/invoices/<iid>/issue")
@endpoint(["AgencyAdmin"])
def issue_invoice(iid):
    b = validate.body()
    expected_version = validate.req_int(b, "expected_retainer_version")

    invoice = services.must("invoice", iid)
    retainer = services.must("retainer", invoice["retainer_id"])

    # Priority 9: the stale-version guard, ahead of the state check.
    if expected_version != retainer["version"]:
        raise ApiError("ERR_STALE_RETAINER_VERSION")

    # Priority 10.
    if invoice["approval_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")

    applied = min(retainer["balance_cents"], invoice["total_cents"])
    cash_due = invoice["total_cents"] - applied

    invoice["retainer_applied_cents"] = applied
    invoice["cash_due_cents"] = cash_due
    invoice["approval_status"] = "ISSUED"
    services.touch(invoice)

    # Hop 1..4: retainer drawdown -> DEPLETED -> client CREDIT_HOLD -> campaigns ON_HOLD.
    retainer["balance_cents"] -= applied
    services.touch(retainer)
    services.retainer_status_recompute(retainer)

    # A FINAL invoice bills its lines; a PROVISIONAL one never does.
    if invoice["billing_mode"] == "FINAL":
        billed_tes = []
        for tid in invoice["_time_entry_ids"]:
            entry = db.TIME_ENTRIES.get(tid)
            if entry is not None and entry["status"] == "APPROVED":
                entry["status"] = "BILLED"
                services.touch(entry)
                billed_tes.append(tid)
        billed_vcs = []
        for vid in invoice["_vendor_cost_ids"]:
            cost = db.VENDOR_COSTS.get(vid)
            if cost is not None and cost["status"] == "APPROVED":
                cost["status"] = "BILLED"
                services.touch(cost)
                billed_vcs.append(vid)
        invoice["_billed_time_entry_ids"] = billed_tes
        invoice["_billed_vendor_cost_ids"] = billed_vcs

    # The retainer covered the whole total: the payment dimension jumps to PAID.
    if cash_due == 0:
        invoice["payment_status"] = "PAID"
        services.close_campaign_if_wrapped(db.CAMPAIGNS.get(invoice["campaign_id"]))

    return response.ok(db.public(invoice))


@bp.post("/invoices/<iid>/void")
@endpoint(["AgencyAdmin"])
def void_invoice(iid):
    b = validate.body()
    reason = validate.req_str(b, "reason")

    invoice = services.must("invoice", iid)
    if invoice["approval_status"] != "ISSUED" or invoice["amount_paid_cents"] != 0:
        raise ApiError("ERR_INVALID_STATE")

    invoice["approval_status"] = "VOID"
    invoice["void_reason"] = reason
    services.touch(invoice)

    # Compensating action: the applied cash goes back, and the invoice leaves the
    # ISSUED filter — retainer_applied_cents itself is deliberately NOT zeroed.
    retainer = db.RETAINERS.get(invoice["retainer_id"])
    if retainer is not None:
        retainer["balance_cents"] += invoice["retainer_applied_cents"]
        services.touch(retainer)
        services.retainer_status_recompute(retainer)

    if invoice["billing_mode"] == "FINAL":
        for tid in invoice["_billed_time_entry_ids"]:
            entry = db.TIME_ENTRIES.get(tid)
            if entry is not None and entry["status"] == "BILLED":
                entry["status"] = "APPROVED"
                services.touch(entry)
        for vid in invoice["_billed_vendor_cost_ids"]:
            cost = db.VENDOR_COSTS.get(vid)
            if cost is not None and cost["status"] == "BILLED":
                cost["status"] = "APPROVED"
                services.touch(cost)

    return response.ok(db.public(invoice))


@bp.post("/invoices/<iid>/payments")
@endpoint(["ClientReviewer"])
def pay_invoice(iid):
    b = validate.body()
    amount = validate.req_int(b, "amount_cents", minimum=1)

    invoice = services.must("invoice", iid)
    services.must_own_client(invoice["client_id"])

    if invoice["approval_status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE")

    if invoice["amount_paid_cents"] + amount > invoice["cash_due_cents"]:
        raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE")

    invoice["amount_paid_cents"] += amount
    paid = invoice["amount_paid_cents"]
    due = invoice["cash_due_cents"]
    if paid == due:
        invoice["payment_status"] = "PAID"
    elif paid > 0:
        invoice["payment_status"] = "PARTIALLY_PAID"
    else:
        invoice["payment_status"] = "UNPAID"
    services.touch(invoice)

    if invoice["payment_status"] == "PAID":
        services.close_campaign_if_wrapped(db.CAMPAIGNS.get(invoice["campaign_id"]))

    return response.ok(db.public(invoice))
