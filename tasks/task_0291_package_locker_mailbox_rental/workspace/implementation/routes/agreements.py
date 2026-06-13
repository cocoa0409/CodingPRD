"""RentalAgreement endpoints."""
from flask import Blueprint, request, g

from db import db, new_id, now_iso
from errors import err
from response import success, list_response
from middleware import require_roles
from common import (get_json, require_fields, require_str, require_int, optional_bool,
                    fk_or_404, get_or_404, touch, parse_pagination, paginate,
                    require_customer_owns)
import constants as C
import calculations as calc
import clock
import serializers as S
from services import billing
from services import packages as pkg_svc
from services import agreements as agr_svc

bp = Blueprint("agreements", __name__)


@bp.post("/rental-agreements")
def create_agreement():
    require_roles("FacilityOperator", "Customer")
    body = get_json()
    require_fields(body, ["facility_id", "customer_id", "mailbox_unit_id",
                          "form_1583_id", "term_months"])
    facility_id = require_str(body, "facility_id")
    customer_id = require_str(body, "customer_id")
    mailbox_unit_id = require_str(body, "mailbox_unit_id")
    form_1583_id = require_str(body, "form_1583_id")
    term_months = require_int(body, "term_months", minimum=1)
    autopay = optional_bool(body, "autopay_enabled", default=False)
    fk_or_404(db.facilities, facility_id)
    customer = fk_or_404(db.customers, customer_id)
    mailbox = fk_or_404(db.mailbox_units, mailbox_unit_id)
    fk_or_404(db.forms_1583, form_1583_id)
    require_customer_owns(customer["id"])
    aid = new_id()
    agreement = {
        "id": aid,
        "facility_id": facility_id,
        "customer_id": customer_id,
        "mailbox_unit_id": mailbox_unit_id,
        "form_1583_id": form_1583_id,
        "term_months": term_months,
        "monthly_fee_cents": mailbox["monthly_fee_cents"],
        "term_start": None,
        "term_end": None,
        "autopay_enabled": autopay,
        "status": "PENDING_AUTH",
        "renewal_count": 0,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.rental_agreements[aid] = agreement
    return success(S.agreement_out(agreement), status=201)


@bp.get("/rental-agreements/<aid>")
def get_agreement(aid):
    require_roles("FacilityOperator", "ComplianceOfficer", "Customer")
    agreement = get_or_404(db.rental_agreements, aid)
    require_customer_owns(agreement["customer_id"])
    return success(S.agreement_out(agreement))


@bp.get("/rental-agreements")
def list_agreements():
    require_roles("FacilityOperator", "ComplianceOfficer", "Customer")
    limit, offset = parse_pagination()
    items = list(db.rental_agreements.values())
    if g.role == "Customer":
        items = [x for x in items if x["customer_id"] == g.user_id]
    for key in ("facility_id", "customer_id", "mailbox_unit_id", "form_1583_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [x for x in items if x[key] == val]
    page, total = paginate(items, limit, offset)
    return list_response([S.agreement_out(x) for x in page], limit, offset, total)


@bp.get("/rental-agreements/<aid>/refund-quote")
def refund_quote(aid):
    require_roles("FacilityOperator", "Customer")
    agreement = get_or_404(db.rental_agreements, aid)
    require_customer_owns(agreement["customer_id"])
    facility = db.facilities[agreement["facility_id"]]
    if agreement.get("term_start"):
        term_start = clock.parse_iso(agreement["term_start"])
        now = clock.parse_iso(facility["current_utc"])
        chrono = calc.prorated_refund_chronological(
            agreement["monthly_fee_cents"], agreement["term_months"],
            term_start, now, facility["time_zone"])
        fwd = calc.prorated_refund_forward_looking(
            agreement["monthly_fee_cents"], agreement["term_months"],
            term_start, now, facility["time_zone"])
    else:
        chrono = 0
        fwd = 0
    return success({"chronological_refund_cents": chrono,
                    "forward_looking_refund_cents": fwd})


@bp.post("/rental-agreements/<aid>/activate")
def activate(aid):
    require_roles("FacilityOperator")
    agreement = get_or_404(db.rental_agreements, aid)
    if agreement["status"] != "PENDING_AUTH":
        raise err("ERR_INVALID_STATE", "Agreement must be PENDING_AUTH to activate")
    form = db.forms_1583.get(agreement["form_1583_id"])
    customer = db.customers.get(agreement["customer_id"])
    mailbox = db.mailbox_units.get(agreement["mailbox_unit_id"])
    if form is None or form["status"] != "VERIFIED":
        raise err("ERR_AUTH_NOT_VERIFIED", "Form 1583 must be VERIFIED to activate")
    if customer is None or customer["status"] != "ACTIVE":
        raise err("ERR_AUTH_NOT_VERIFIED", "Customer must be ACTIVE to activate")
    if mailbox is None or mailbox["status"] != "VACANT":
        raise err("ERR_MAILBOX_OCCUPIED", "Mailbox is not VACANT")
    facility = db.facilities[agreement["facility_id"]]
    now = clock.parse_iso(facility["current_utc"])
    term_end = clock.add_days(now, agreement["term_months"] * C.DAYS_PER_MONTH)
    agreement["status"] = "ACTIVE"
    agreement["term_start"] = facility["current_utc"]
    agreement["term_end"] = clock.to_iso_z(term_end)
    mailbox["status"] = "RENTED"
    touch(mailbox)
    # Open the single invoice and post the first RENTAL charge.
    inv_id = new_id()
    invoice = {
        "id": inv_id,
        "facility_id": facility["id"],
        "rental_agreement_id": aid,
        "status": "OPEN",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.invoices[inv_id] = invoice
    amount = agreement["monthly_fee_cents"] * agreement["term_months"]
    billing.post_ledger_entry(invoice, "CHARGE", "RENTAL", amount, aid)
    billing.capture_autopay(agreement, invoice)
    touch(agreement)
    return success(S.agreement_out(agreement))


@bp.post("/rental-agreements/<aid>/renew")
def renew(aid):
    require_roles("Customer", "FacilityOperator")
    agreement = get_or_404(db.rental_agreements, aid)
    require_customer_owns(agreement["customer_id"])
    body = get_json()
    require_fields(body, ["expected_rental_agreement_version"])
    expected = body.get("expected_rental_agreement_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "expected_rental_agreement_version must be an integer")
    if agreement["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Agreement must be ACTIVE to renew")
    if expected != agreement["version"]:
        raise err("ERR_STALE_VERSION", "Agreement version is stale")
    facility = db.facilities[agreement["facility_id"]]
    term_end = clock.parse_iso(agreement["term_end"])
    new_end = clock.add_days(term_end, agreement["term_months"] * C.DAYS_PER_MONTH)
    agreement["term_end"] = clock.to_iso_z(new_end)
    agreement["renewal_count"] += 1
    invoice = pkg_svc.invoice_for_agreement(aid)
    amount = agreement["monthly_fee_cents"] * agreement["term_months"]
    billing.post_ledger_entry(invoice, "CHARGE", "RENTAL", amount, aid)
    billing.capture_autopay(agreement, invoice)
    touch(agreement)
    return success(S.agreement_out(agreement))


@bp.post("/rental-agreements/<aid>/suspend")
def suspend(aid):
    require_roles("FacilityOperator")
    agreement = get_or_404(db.rental_agreements, aid)
    if agreement["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Agreement must be ACTIVE to suspend")
    agreement["status"] = "SUSPENDED"
    agr_svc.cascade_suspend(agreement)
    touch(agreement)
    return success(S.agreement_out(agreement))


@bp.post("/rental-agreements/<aid>/reactivate")
def reactivate(aid):
    require_roles("FacilityOperator")
    agreement = get_or_404(db.rental_agreements, aid)
    if agreement["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Agreement must be SUSPENDED to reactivate")
    invoice = pkg_svc.invoice_for_agreement(aid)
    balance = billing.invoice_balance(invoice) if invoice else 0
    if balance > C.SUSPEND_BALANCE_THRESHOLD_CENTS:
        raise err("ERR_AGREEMENT_NOT_ACTIVE", "Balance exceeds threshold")
    agreement["status"] = "ACTIVE"
    agr_svc.cascade_reactivate(agreement)
    touch(agreement)
    return success(S.agreement_out(agreement))


@bp.post("/rental-agreements/<aid>/close")
def close(aid):
    require_roles("Customer", "FacilityOperator")
    agreement = get_or_404(db.rental_agreements, aid)
    require_customer_owns(agreement["customer_id"])
    if agreement["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "Agreement must be ACTIVE or SUSPENDED to close")
    for p in db.packages.values():
        if p["rental_agreement_id"] == aid and p["status"] in ("RECEIVED", "NOTIFIED"):
            raise err("ERR_UNRESOLVED_PACKAGES", "Unresolved packages on agreement")
    facility = db.facilities[agreement["facility_id"]]
    agr_svc.close_agreement(agreement, facility)
    return success(S.agreement_out(agreement))
