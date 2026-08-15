from flask import request

from errors import ApiError
from middleware import guard
from response import success_envelope
from utils import list_page
from db import store, get_or_404
from serializers import withholding_entry as ser
from services import reverse_entry


def register(app):
    @app.get("/tax1099/withholding-entries/<entryId>")
    @guard({"APClerk", "TaxAdmin", "TaxSpecialist"})
    def get_entry(entryId):
        return success_envelope(ser(get_or_404("withholding_entries", entryId)))

    @app.get("/tax1099/withholding-entries")
    @guard({"APClerk", "TaxAdmin", "TaxSpecialist"})
    def list_entries():
        items = sorted(store["withholding_entries"].values(), key=lambda r: r["_seq"])
        for f in ("vendor_id", "payment_id", "remittance_id", "reverses_entry_id",
                  "entry_type", "status", "tax_year"):
            v = request.args.get(f)
            if v is not None:
                items = [r for r in items if str(r.get(f)) == v]
        page, pagination = list_page(items)
        return success_envelope([ser(r) for r in page], response_type="array",
                                pagination=pagination)

    @app.post("/tax1099/withholding-entries/<entryId>/reverse")
    @guard({"TaxAdmin"})
    def reverse(entryId):
        rec = get_or_404("withholding_entries", entryId)
        if rec["entry_type"] != "DEBIT_WITHHELD":
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                           "REVERSAL entries cannot be reversed")
        if rec["status"] == "REMITTED":
            raise ApiError("ERR_ENTRY_ALREADY_REMITTED", 409,
                           "Entry has already been remitted")
        if rec["status"] != "UNREMITTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                           "Only an UNREMITTED entry can be reversed")
        reverse_entry(rec)
        return success_envelope(ser(rec))
