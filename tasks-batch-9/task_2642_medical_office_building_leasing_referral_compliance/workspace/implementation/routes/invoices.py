"""Occupancy billing, payment and write-off (PRD Section 3.7)."""

from decimal import Decimal

from flask import Blueprint

import enums
import serializers as ser
import validators as v
from db import clock_date, db, stamp_new, touch
from errors import ApiError, bad_request
from lookups import get_lease, get_resource, paged
from middleware import acting_user_id, endpoint, require_tenant_scope
from response import object_response
from services import calc

bp = Blueprint("invoices", __name__)

ZERO = Decimal("0.00")


@bp.post("/leases/<lease_id>/rent-invoices")
@endpoint("PropertyManager")
def issue_invoice(lease_id):
    body = v.json_body()
    period_start = v.get_date(body, "period_start")
    period_end = v.get_date(body, "period_end")
    if period_end < period_start:
        raise bad_request("Field 'period_end' must be on or after 'period_start'.")
    due_date = v.get_date(body, "due_date")

    lease = get_lease(lease_id)
    if lease["status"] in calc.CLOSED_LEASE_STATUSES:
        raise ApiError(
            "ERR_INVALID_LEASE_STATE",
            "Lease '%s' has reached %s." % (lease["id"], lease["status"]),
        )

    # Rung 35 — closed-interval overlap against every invoice not written off.
    for other in calc.invoices_of_lease(lease["id"]):
        if other["status"] == "WRITTEN_OFF":
            continue
        if period_start <= other["period_end"] and other["period_start"] <= period_end:
            raise ApiError(
                "ERR_INVOICE_PERIOD_OVERLAP",
                "The requested period overlaps invoice '%s'." % other["id"],
            )
    if lease["status"] != "HOLDOVER" and (
        period_start < lease["term_start"] or period_end > lease["term_end"]
    ):
        raise ApiError(
            "ERR_INVOICE_PERIOD_OVERLAP",
            "The requested period lies outside the lease term %s..%s."
            % (lease["term_start"].isoformat(), lease["term_end"].isoformat()),
        )

    charges = calc.build_invoice_charges(lease)
    row = {
        "lease_id": lease["id"],
        "period_start": period_start,
        "period_end": period_end,
        "due_date": due_date,
        "status": "ISSUED",
        "base_rent_amount": charges["base_rent_amount"],
        "cam_amount": charges["cam_amount"],
        "parking_fee_gross": charges["parking_fee_gross"],
        "pre_waiver_total": charges["pre_waiver_total"],
        "parking_waiver_tier_pct": charges["parking_waiver_pct"],
        "parking_waiver_amount": charges["parking_waiver_amount"],
        "total_amount": charges["total_amount"],
        "amount_paid": ZERO,
        "paid_on": None,
        "days_past_due": 0,
        "days_past_due_at_flag": None,
        "delinquency_tier_weight": 0,
        "write_off_justification": None,
        "written_off_by_user_id": None,
    }
    stamp_new(row)
    db.rent_invoices[row["id"]] = row
    return object_response(ser.rent_invoice_out(row), 201)


@bp.get("/leases/<lease_id>/rent-invoices")
@endpoint()
def list_invoices(lease_id):
    limit, offset = v.pagination()
    status = v.query_enum("status", enums.INVOICE_STATUSES)
    lease = get_lease(lease_id)
    require_tenant_scope(lease["tenant_id"])
    rows = calc.invoices_of_lease(lease["id"])
    if status is not None:
        rows = [i for i in rows if i["status"] == status]
    return paged(rows, ser.rent_invoice_out, limit, offset)


@bp.post("/rent-invoices/<invoice_id>/payments")
@endpoint("PropertyManager")
def record_payment(invoice_id):
    body = v.json_body()
    payment_amount = v.get_money(body, "payment_amount", allow_zero=False)

    invoice = get_resource(db.rent_invoices, invoice_id, "Rent invoice")
    # Rung 3: the payment must settle the balance in one act, so the exactness
    # test outranks the record-state test.
    if calc.q2(invoice["amount_paid"] + payment_amount) != invoice["total_amount"]:
        raise bad_request(
            "Field 'payment_amount' must be exactly the outstanding balance of %s."
            % calc.outstanding_balance(invoice)
        )
    if invoice["status"] not in ("ISSUED", "DELINQUENT"):
        raise ApiError(
            "ERR_INVALID_RECORD_STATE",
            "Invoice '%s' is in status %s; payment requires ISSUED or DELINQUENT."
            % (invoice["id"], invoice["status"]),
        )

    invoice["status"] = "PAID"
    invoice["amount_paid"] = invoice["total_amount"]
    invoice["paid_on"] = clock_date()
    invoice["days_past_due"] = max(0, calc.live_days_past_due(invoice))
    # Curing arrears is emphatically not a compensation: days_past_due_at_flag
    # and delinquency_tier_weight are both retained (PRD Section 3.7).
    touch(invoice)
    return object_response(ser.rent_invoice_out(invoice))


@bp.post("/rent-invoices/<invoice_id>/write-off")
@endpoint("ComplianceOfficer")
def write_off(invoice_id):
    body = v.json_body()
    justification = v.get_string(body, "write_off_justification")

    invoice = get_resource(db.rent_invoices, invoice_id, "Rent invoice")
    if invoice["status"] != "DELINQUENT":
        raise ApiError(
            "ERR_INVALID_RECORD_STATE",
            "Invoice '%s' is in status %s; a write-off requires DELINQUENT."
            % (invoice["id"], invoice["status"]),
        )
    lease = db.leases[invoice["lease_id"]]
    tenant = db.tenants[lease["tenant_id"]]
    actor = acting_user_id()
    for case in calc.cases_of_tenant(tenant["id"]):
        if (
            case["case_type"] == "RENT_DELINQUENCY"
            and case["status"] == "OPEN"
            and case["opened_by_user_id"] == actor
        ):
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                "The officer who raised case '%s' may not forgive the debt." % case["id"],
            )

    invoice["status"] = "WRITTEN_OFF"
    invoice["write_off_justification"] = justification
    invoice["written_off_by_user_id"] = actor
    # The write-off weight replaces the aging tier rather than adding to it.
    invoice["delinquency_tier_weight"] = calc.WRITE_OFF_WEIGHT
    touch(invoice)
    calc.recompute_tenant_risk(tenant, force_bump=True)
    return object_response(ser.rent_invoice_out(invoice))
