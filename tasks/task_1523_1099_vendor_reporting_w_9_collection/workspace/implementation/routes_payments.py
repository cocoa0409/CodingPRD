from flask import request

from errors import ApiError
from middleware import guard
from response import success_envelope
from utils import json_body, reject_unknown, req_str, req_int, req_enum, parse_dt, list_page
from db import store, make_record, make_entry, touch, get_or_404, fmt_ts
from serializers import payment as ser
from services import (SOURCE_SYSTEMS, PAYMENT_TYPES, classify, withholding_cents,
                      quarter_of, find_covering_tax_year, backup_flag,
                      recompute_draft_remittances, invalidate_open_returns,
                      payment_in_accepted_return, reverse_entry, DEFAULT_RATE_BPS)


def register(app):
    @app.post("/tax1099/payments")
    @guard({"APClerk"})
    def create_payment():
        b = json_body()
        reject_unknown(b, {"vendor_id", "source_system", "payment_type",
                           "amount_cents", "payment_date"})
        vendor_id = req_str(b, "vendor_id")
        source = req_enum(b, "source_system", SOURCE_SYSTEMS)
        ptype = req_enum(b, "payment_type", PAYMENT_TYPES)
        amount = req_int(b, "amount_cents")
        if "payment_date" not in b:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field 'payment_date'")
        pay_date = parse_dt(b["payment_date"], "payment_date")
        vendor = store["vendors"].get(vendor_id)
        if vendor is None:
            raise ApiError("ERR_NOT_FOUND", 404, "Vendor not found: %s" % vendor_id)
        # Ladder: W-9 compliance (6) -> temporal (8) -> referential (9) -> fiscal (11).
        if vendor["tin_match_status"] not in ("MATCHED", "MISMATCHED"):
            raise ApiError("ERR_W9_NOT_ON_FILE", 409,
                           "Payment requires tin_match_status MATCHED or MISMATCHED")
        year_row = find_covering_tax_year(pay_date)
        if year_row is None:
            raise ApiError("ERR_NO_TAX_YEAR", 422,
                           "No TaxYear period covers payment_date")
        if year_row["status"] != "OPEN":
            raise ApiError("ERR_TAX_YEAR_CLOSED", 409, "Covering TaxYear is CLOSED")
        if vendor["status"] != "ACTIVE":
            raise ApiError("ERR_VENDOR_NOT_ACTIVE", 409, "Vendor must be ACTIVE")
        if amount <= 0:
            raise ApiError("ERR_INVALID_AMOUNT", 422, "amount_cents must be > 0")

        tax_year = pay_date.year
        quarter = quarter_of(pay_date)
        is_reportable, box = classify(ptype, vendor["entity_classification"])
        rate = year_row["backup_withholding_rate_bps"]
        withheld = withholding_cents(amount, rate) if backup_flag(vendor) else 0
        rec = make_record("payments", {
            "vendor_id": vendor["id"],
            "source_system": source,
            "payment_type": ptype,
            "amount_cents": amount,
            "payment_date": fmt_ts(pay_date),
            "tax_year": tax_year,
            "is_reportable": is_reportable,
            "reportable_box": box,
            "withheld_cents": withheld,
            "status": "POSTED",
            "_date": pay_date,
        })
        if withheld > 0:
            make_entry({
                "vendor_id": vendor["id"],
                "payment_id": rec["id"],
                "reverses_entry_id": None,
                "remittance_id": None,
                "tax_year": tax_year,
                "quarter": quarter,
                "entry_type": "DEBIT_WITHHELD",
                "amount_cents": withheld,
                "status": "UNREMITTED",
            })
            recompute_draft_remittances(tax_year, quarter)
        return success_envelope(ser(rec), status=201)

    @app.get("/tax1099/payments/<paymentId>")
    @guard({"APClerk", "TaxAdmin", "TaxSpecialist"})
    def get_payment(paymentId):
        return success_envelope(ser(get_or_404("payments", paymentId)))

    @app.get("/tax1099/payments")
    @guard({"APClerk", "TaxAdmin", "TaxSpecialist"})
    def list_payments():
        items = sorted(store["payments"].values(), key=lambda r: r["_seq"])
        for f in ("vendor_id", "tax_year", "payment_type", "source_system", "status"):
            v = request.args.get(f)
            if v is not None:
                items = [r for r in items if str(r.get(f)) == v]
        page, pagination = list_page(items)
        return success_envelope([ser(r) for r in page], response_type="array",
                                pagination=pagination)

    @app.post("/tax1099/payments/<paymentId>/void")
    @guard({"APClerk", "TaxAdmin"})
    def void_payment(paymentId):
        rec = get_or_404("payments", paymentId)
        if rec["status"] != "POSTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                           "Only a POSTED payment can be voided")
        year_row = find_covering_tax_year(rec["_date"])
        if year_row is not None and year_row["status"] != "OPEN":
            raise ApiError("ERR_PAYMENT_NOT_VOIDABLE", 409,
                           "Covering TaxYear is CLOSED")
        if payment_in_accepted_return(rec):
            raise ApiError("ERR_PAYMENT_NOT_VOIDABLE", 409,
                           "Payment is included in an ACCEPTED return")
        debit = None
        for e in store["withholding_entries"].values():
            if e["payment_id"] == rec["id"] and e["entry_type"] == "DEBIT_WITHHELD":
                debit = e
                break
        if debit is not None and debit["status"] == "REMITTED":
            raise ApiError("ERR_PAYMENT_NOT_VOIDABLE", 409,
                           "Payment's withholding entry is already REMITTED")
        rec["status"] = "VOIDED"
        touch(rec)
        if debit is not None and debit["status"] == "UNREMITTED":
            reverse_entry(debit)
        else:
            recompute_draft_remittances(rec["tax_year"], quarter_of(rec["_date"]))
            invalidate_open_returns(rec["vendor_id"], tax_year=rec["tax_year"])
        return success_envelope(ser(rec))
