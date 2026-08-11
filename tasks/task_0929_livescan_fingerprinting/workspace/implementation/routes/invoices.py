from flask import Blueprint, request

import billing
import serializers
import validation as V
from envelope import object_response, paginate
from errors import ApiError
from lookups import body_row, check_parent_version, path_row, require_record_state
from store import db
from timeutil import add_date_days, date_of, is_period_key

bp = Blueprint("invoices", __name__)


@bp.post("/livescan/invoices")
def open_invoice():
    data = V.body()
    agency = body_row("agencies", data["agency_id"]) if data.get("agency_id") else None
    period_key = V.req_string(data, "period_key")
    expected_agency_version = V.req_int(data, "expected_agency_version")
    if agency is None:
        V.bad_request("agency_id is required")
    if not is_period_key(period_key):
        V.bad_request("period_key must be a YYYY-MM string")

    for other in db.invoices.values():
        if (
            other["agency_id"] == agency["id"]
            and other["period_key"] == period_key
            and other["status"] != "WRITTEN_OFF"
        ):
            V.bad_request("period_key must be unique per agency")

    check_parent_version(agency, expected_agency_version)

    row = db.create(
        "invoices",
        {
            "agency_id": agency["id"],
            "period_key": period_key,
            "issued_on": None,
            "due_on": None,
            "subtotal_cents": 0,
            "late_fee_cents": 0,
            "total_cents": 0,
            "paid_cents": 0,
            "aging_days": 0,
            "status": "DRAFT",
        },
    )
    db.touch(agency)
    return object_response(serializers.invoice(row), 201)


@bp.get("/livescan/invoices/<id>")
def read_invoice(id):
    return object_response(serializers.invoice(path_row("invoices", id)))


@bp.get("/livescan/invoices")
def list_invoices():
    rows = list(db.invoices.values())
    for field in ("agency_id", "status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return paginate(rows, serializers.invoice)


@bp.post("/livescan/invoices/<id>/issue")
def issue_invoice(id):
    invoice = path_row("invoices", id)
    require_record_state(invoice["status"] == "DRAFT", "invoice is %s" % invoice["status"])

    # Friction point 6: only AGENCY_BILLED assessments are attached; a
    # FEE_WAIVED row is reached by neither the counter path nor the invoice path
    # and remains at ASSESSED.
    attachable = [
        a
        for a in db.assessments.values()
        if a["agency_id"] == invoice["agency_id"]
        and a["status"] == "ASSESSED"
        and a["payer_regime"] == "AGENCY_BILLED"
    ]
    require_record_state(bool(attachable), "no open agency-billed assessment exists")
    attachable.sort(key=lambda a: (a["created_at"], a["id"]))

    agency = db.agencies[invoice["agency_id"]]
    for assessment in attachable:
        assessment["invoice_id"] = invoice["id"]
        assessment["status"] = "INVOICED"
        db.touch(assessment)

    issued_on = date_of(db.now())
    invoice["status"] = "ISSUED"
    invoice["issued_on"] = issued_on
    invoice["due_on"] = add_date_days(issued_on, agency["invoice_terms_days"])
    billing.recompute_invoice_totals(invoice)
    db.touch(invoice)

    billing.recompute_agency_posture(agency)
    return object_response(serializers.invoice(invoice))


@bp.post("/livescan/invoices/<id>/payments")
def pay_invoice(id):
    invoice = path_row("invoices", id)
    data = V.body()
    amount_cents = V.req_int(data, "amount_cents", minimum=1)

    require_record_state(
        invoice["status"] in ("ISSUED", "PAST_DUE"), "invoice is %s" % invoice["status"]
    )
    if amount_cents != invoice["total_cents"] - invoice["paid_cents"]:
        raise ApiError("ERR_INVALID_REQUEST", "the payment must equal the outstanding balance")

    was_past_due = invoice["status"] == "PAST_DUE"
    invoice["paid_cents"] = invoice["total_cents"]
    invoice["status"] = "PAID"
    if was_past_due:
        invoice["aging_days"] = 0
    db.touch(invoice)

    for assessment in db.assessments.values():
        if assessment["invoice_id"] != invoice["id"] or assessment["status"] != "INVOICED":
            continue
        assessment["status"] = "PAID"
        assessment["paid_cents"] = assessment["total_cents"]
        db.touch(assessment)

    billing.recompute_agency_posture(db.agencies[invoice["agency_id"]])
    return object_response(serializers.invoice(invoice))
