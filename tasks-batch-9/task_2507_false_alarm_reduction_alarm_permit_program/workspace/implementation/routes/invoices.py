"""Penalty invoices: adjustment, collections referral and the two-dimension reads."""

from flask import Blueprint

import engine
import rt
from core import F, authenticate, check_owner, listing, ok, q, validate
from errors import ApiError
from store import now, store, touch

bp = Blueprint("invoices", __name__)

ADMIN = ["ProgramAdministrator"]
REFER_ROLES = ["BillingClerk", "ProgramAdministrator"]
READ_ROLES = ["ProgramAdministrator", "BillingClerk", "PermitClerk",
              "FalseAlarmReviewOfficer", "HearingOfficer", "AlarmUser"]

KINDS = ("WAIVE", "REDUCE", "WRITE_OFF")

ADJUST_FIELDS = [
    F("adjustment_kind", "enum", values=KINDS),
    F("reason", "string"),
    F("expected_penalty_invoice_version", "int"),
    F("amount_cents", "int", required=False),
]

REFER_FIELDS = [F("referral_agency", "string")]


@bp.post("/penalty-invoices/<invoice_id>/adjustments")
def adjust_invoice(invoice_id):
    ctx = authenticate(ADMIN)
    data = validate(ctx.body, ADJUST_FIELDS)
    invoice = rt.resolve("PenaltyInvoice", invoice_id)
    kind = data["adjustment_kind"]
    for allocation in engine.allocations_for_invoice(invoice["id"]):
        payment = store.payment_records.get(allocation.get("payment_record_id"))
        if payment is not None \
                and payment.get("recorded_by_user_id") == ctx.user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "The clerk who posted a payment to this invoice may "
                           "not adjust it.")
    if data["expected_penalty_invoice_version"] != invoice.get("version"):
        raise ApiError("ERR_STALE_PENALTY_INVOICE_VERSION",
                       "The invoice has been modified since it was read.")
    if invoice.get("payment_status") == "VOIDED":
        raise ApiError("ERR_INVALID_STATE", "A VOIDED invoice may not be "
                                            "adjusted.")
    if invoice.get("collections_stage") == "WRITTEN_OFF":
        raise ApiError("ERR_INVOICE_WRITTEN_OFF",
                       "A written-off invoice may not be adjusted again.")
    if kind == "WRITE_OFF" and invoice.get("collections_stage") != "REFERRED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a REFERRED invoice may be written off.")
    if kind in ("WAIVE", "REDUCE") and "amount_cents" not in data:
        raise ApiError("ERR_MISSING_REQUIRED_FIELD",
                       "amount_cents is required for a %s adjustment." % kind)

    engine.recompute_outstanding(invoice)
    outstanding = invoice["outstanding_cents"]
    if kind == "WRITE_OFF":
        amount = outstanding
    else:
        amount = data["amount_cents"]
        if amount > outstanding:
            raise ApiError("ERR_ADJUSTMENT_EXCEEDS_OUTSTANDING",
                           "The adjustment exceeds the outstanding amount.")

    invoice["adjusted_cents"] = (invoice.get("adjusted_cents") or 0) + amount
    if kind == "WRITE_OFF":
        invoice["collections_stage"] = "WRITTEN_OFF"
        engine.recompute_outstanding(invoice)
    else:
        engine.settle_check(invoice)
    touch(invoice)
    site = store.alarm_sites.get(invoice.get("alarm_site_id"))
    if site is not None:
        engine.rollup_site(site)
    return ok(invoice)


@bp.post("/penalty-invoices/<invoice_id>/collections-referral")
def refer_invoice(invoice_id):
    ctx = authenticate(REFER_ROLES)
    data = validate(ctx.body, REFER_FIELDS)
    invoice = rt.resolve("PenaltyInvoice", invoice_id)
    if invoice.get("payment_status") == "VOIDED":
        raise ApiError("ERR_INVALID_STATE", "A VOIDED invoice may not be "
                                            "referred.")
    if invoice.get("collections_stage") == "WRITTEN_OFF":
        raise ApiError("ERR_INVOICE_WRITTEN_OFF",
                       "A written-off invoice may not be referred.")
    if engine.invoice_frozen_by_appeal(invoice):
        raise ApiError("ERR_INVOICE_UNDER_APPEAL",
                       "The linked incident is under appeal.")
    site = store.alarm_sites.get(invoice.get("alarm_site_id"))
    sched = engine.governing_schedule(site) if site else None
    if sched is None:
        raise ApiError("ERR_NO_ACTIVE_FEE_SCHEDULE",
                       "The premises is not pinned to a governing schedule.")
    engine.recompute_outstanding(invoice)
    engine.refresh_days_delinquent(invoice)
    threshold = int(sched.get("collections_referral_threshold_cents") or 0)
    delinquency_days = int(sched.get("delinquency_days") or 0)
    if invoice.get("collections_stage") != "FINAL_NOTICE" \
            or invoice["days_delinquent"] < delinquency_days \
            or invoice["outstanding_cents"] < threshold:
        raise ApiError("ERR_REFERRAL_CRITERIA_NOT_MET",
                       "The invoice does not meet every referral criterion.")
    invoice["collections_stage"] = "REFERRED"
    invoice["referred_on"] = now()
    invoice["referral_total_cents"] = engine.compute_referral_total(invoice)
    invoice["referral_agency"] = data["referral_agency"]
    touch(invoice)
    return ok(invoice)


@bp.get("/penalty-invoices/<invoice_id>")
def get_invoice(invoice_id):
    ctx = authenticate(READ_ROLES)
    invoice = rt.resolve("PenaltyInvoice", invoice_id)
    check_owner(ctx, site_id=invoice.get("alarm_site_id"))
    engine.refresh_days_delinquent(invoice)
    return ok(invoice)


@bp.get("/penalty-invoices")
def list_invoices():
    ctx = authenticate(READ_ROLES)
    rows = rt.scope_reads(ctx, rt.all_rows("PenaltyInvoice"), company_field=None)
    for field in ("alarm_site_id", "false_alarm_incident_id", "alarm_permit_id",
                  "suspension_order_id", "kind", "payment_status",
                  "collections_stage"):
        value = q(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    for row in rows:
        engine.refresh_days_delinquent(row)
    return listing(rows, rt.fields("PenaltyInvoice"))
