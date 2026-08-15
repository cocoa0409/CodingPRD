"""Invoice endpoints: draft (final pricing), issue (suspension cascade),
void, write-off."""
from datetime import timedelta

from flask import Blueprint, request

from db import store, new_record, touch
from errors import (ApiError, err_not_found, err_invalid_state)
from middleware import auth, require_fleet_ownership
from response import success
from serializers import serialize, serialize_invoice, fleet_mtd
from services.cascades import (append_event, close_call,
                               suspend_fleet_credit_hold,
                               maybe_reinstate_credit_hold, wall_now)
from services.pricing import invoice_pricing
from routes.service_calls import get_call_or_404, ensure_not_cancelled
from util import Field, validate_body, parse_pagination, paginate

bp = Blueprint("invoices", __name__)

READ_ROLES = ["OpsAdmin", "Dispatcher", "BillingClerk", "FleetManager"]
LIST_ROLES = ["OpsAdmin", "BillingClerk", "FleetManager"]


def _get_invoice(invoice_id):
    inv = store.invoices.get(invoice_id)
    if inv is None:
        raise err_not_found("Invoice not found")
    return inv


def _fleet_check(inv, uid, role):
    if role == "FleetManager":
        require_fleet_ownership(uid, inv.get("fleet_account_id"))


@bp.route("/roadside/service-calls/<serviceCallId>/invoices", methods=["POST"])
def create_invoice(serviceCallId):
    uid, role = auth(["BillingClerk"])
    call = get_call_or_404(serviceCallId)
    validate_body(request.get_json(silent=True), [])
    ensure_not_cancelled(call)
    if call["status"] not in ("REPAIR_COMPLETED", "TOWED"):
        raise err_invalid_state(
            "Invoice draft requires REPAIR_COMPLETED or TOWED")
    for c in store.warranty_claims.values():
        if (c["service_call_id"] == call["id"]
                and c["status"] in ("DRAFT", "SUBMITTED", "APPEALED")):
            raise ApiError("ERR_WARRANTY_CLAIM_UNDECIDED",
                           "A claim of the call is DRAFT/SUBMITTED/APPEALED",
                           409)
    for inv in store.invoices.values():
        if (inv["service_call_id"] == call["id"]
                and inv["issue_status"] != "VOID"):
            raise ApiError("ERR_INVOICE_EXISTS",
                           "A non-VOID invoice already exists for the call", 409)
    pricing = invoice_pricing(call)  # may raise ERR_NO_ACTIVE_RATE_CARD
    number = "INV-" + str(next(store.invoice_seq)).zfill(6)
    rec = new_record()
    now = wall_now()
    rec.update({
        "_created": now, "_updated": now,
        "service_call_id": call["id"],
        "fleet_account_id": call.get("fleet_account_id"),
        "invoice_number": number,
        "issue_status": "DRAFT",
        "payment_status": "UNPAID",
        "amount_paid_cents": 0,
        "outstanding_cents": pricing["total_cents"],
        "issued_at": None,
        "due_at": None,
        "created_by": uid,
        "issued_by": None,
        "void_reason": None,
        "writeoff_reason": None,
    })
    rec.update(pricing)
    store.invoices[rec["id"]] = rec
    append_event(call["id"], "INVOICE_CREATED", role, uid)
    return success(serialize_invoice(rec), status=201)


@bp.route("/roadside/invoices/<invoiceId>", methods=["GET"])
def get_invoice(invoiceId):
    uid, role = auth(READ_ROLES)
    inv = _get_invoice(invoiceId)
    _fleet_check(inv, uid, role)
    return success(serialize_invoice(inv))


@bp.route("/roadside/invoices", methods=["GET"])
def list_invoices():
    uid, role = auth(LIST_ROLES)
    limit, offset = parse_pagination(request.args)
    fleet_f = request.args.get("fleet_account_id")
    call_f = request.args.get("service_call_id")
    issue_f = request.args.get("issue_status")
    pay_f = request.args.get("payment_status")
    items = sorted(store.invoices.values(), key=lambda r: r["_seq"])
    if role == "FleetManager":
        items = [i for i in items if i.get("fleet_account_id") == uid]
    if fleet_f is not None:
        items = [i for i in items if i.get("fleet_account_id") == fleet_f]
    if call_f is not None:
        items = [i for i in items if i["service_call_id"] == call_f]
    if issue_f is not None:
        items = [i for i in items if i["issue_status"] == issue_f]
    if pay_f is not None:
        items = [i for i in items if i["payment_status"] == pay_f]
    page, total, has_more = paginate(items, limit, offset)
    return success([serialize_invoice(i) for i in page],
                   response_type="array",
                   pagination={"limit": limit, "offset": offset,
                               "total_count": total, "has_more": has_more})


@bp.route("/roadside/invoices/<invoiceId>/issue", methods=["POST"])
def issue(invoiceId):
    uid, role = auth(["BillingClerk", "OpsAdmin"])
    inv = _get_invoice(invoiceId)
    validate_body(request.get_json(silent=True), [])
    if inv["issue_status"] != "DRAFT":
        raise err_invalid_state("Issue requires issue_status DRAFT")
    call = store.service_calls.get(inv["service_call_id"])
    fleet = None
    if inv.get("fleet_account_id"):
        fleet = store.fleets.get(inv["fleet_account_id"])
    if fleet is not None:
        if fleet["status"] == "SUSPENDED":
            raise ApiError("ERR_FLEET_SUSPENDED",
                           "Invoice issue attempted for a SUSPENDED fleet", 409)
        if fleet["status"] == "CLOSED":
            raise ApiError("ERR_FLEET_CLOSED",
                           "Invoice issue attempted for a CLOSED fleet", 409)
    inv["issue_status"] = "ISSUED"
    inv["issued_at"] = store.clock
    inv["issued_by"] = uid
    terms = fleet["payment_terms_days"] if fleet is not None else 0
    inv["due_at"] = store.clock + timedelta(days=terms)
    touch(inv, wall_now())
    if call is not None and call["status"] in ("REPAIR_COMPLETED", "TOWED"):
        call["status_before_invoice"] = call["status"]
        call["status"] = "INVOICED"
        touch(call, wall_now())
        append_event(call["id"], "INVOICE_ISSUED", role, uid)
    if fleet is not None:
        touch(fleet, wall_now())  # mtd feed is a fleet mutation
        if fleet_mtd(fleet["id"]) > fleet["monthly_spend_cap_cents"]:
            suspend_fleet_credit_hold(fleet)
    if inv["total_cents"] == 0:
        # zero-total (NO_CHARGE comeback): skip collection lifecycle
        inv["payment_status"] = "PAID"
        touch(inv, wall_now())
        if call is not None:
            close_call(call)
    return success(serialize_invoice(inv))


@bp.route("/roadside/invoices/<invoiceId>/void", methods=["POST"])
def void(invoiceId):
    uid, role = auth(["OpsAdmin"])
    inv = _get_invoice(invoiceId)
    vals = validate_body(request.get_json(silent=True), [
        Field("reason", "string", required=True),
    ])
    if inv["issue_status"] != "ISSUED":
        raise err_invalid_state("Void requires issue_status ISSUED")
    if inv.get("issued_by") == uid:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The issuer may not void the same invoice", 403)
    for p in store.payments.values():
        if p["invoice_id"] == inv["id"] and p["status"] == "POSTED":
            raise ApiError("ERR_INVOICE_HAS_PAYMENTS",
                           "Void attempted on an invoice with POSTED payments",
                           409)
    inv["issue_status"] = "VOID"
    inv["void_reason"] = vals["reason"]
    touch(inv, wall_now())
    fleet = None
    if inv.get("fleet_account_id"):
        fleet = store.fleets.get(inv["fleet_account_id"])
    if fleet is not None:
        touch(fleet, wall_now())  # mtd reversal is a fleet mutation
        maybe_reinstate_credit_hold(fleet)
    call = store.service_calls.get(inv["service_call_id"])
    if call is not None and call["status"] == "INVOICED":
        prior = call.get("status_before_invoice")
        call["status"] = prior if prior else "REPAIR_COMPLETED"
        touch(call, wall_now())
        if call["status"] == "REPAIR_COMPLETED":
            append_event(call["id"], "INVOICE_VOIDED", role, uid)
    return success(serialize_invoice(inv))


@bp.route("/roadside/invoices/<invoiceId>/write-off", methods=["POST"])
def write_off(invoiceId):
    uid, role = auth(["OpsAdmin"])
    inv = _get_invoice(invoiceId)
    vals = validate_body(request.get_json(silent=True), [
        Field("reason", "string", required=True),
    ])
    if inv["issue_status"] != "ISSUED" or inv["outstanding_cents"] <= 0:
        raise err_invalid_state(
            "Write-off requires an ISSUED invoice with outstanding balance")
    inv["payment_status"] = "WRITTEN_OFF"
    inv["writeoff_reason"] = vals["reason"]
    touch(inv, wall_now())
    call = store.service_calls.get(inv["service_call_id"])
    if call is not None:
        close_call(call)  # month-to-date spend is deliberately NOT reduced
    return success(serialize_invoice(inv))
