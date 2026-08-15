from errors import ApiError
from middleware import guard, caller_id
from response import success_envelope
from utils import json_body, reject_unknown, req_int, req_str
from db import store, make_record, touch, get_or_404
from serializers import remittance as ser
from services import (find_tax_year_by_value, withholding_cents, quarter_of,
                      DEFAULT_RATE_BPS)


def _unremitted_sum(tax_year, quarter):
    return sum(e["amount_cents"] for e in store["withholding_entries"].values()
               if e["status"] == "UNREMITTED" and e["tax_year"] == tax_year
               and e["quarter"] == quarter)


def register(app):
    @app.post("/tax1099/remittances")
    @guard({"TaxSpecialist"})
    def create_remittance():
        b = json_body()
        reject_unknown(b, {"tax_year", "quarter"})
        tax_year = req_int(b, "tax_year")
        quarter = req_int(b, "quarter")
        if quarter < 1 or quarter > 4:
            raise ApiError("ERR_INVALID_REQUEST", 400, "quarter must be in 1..4")
        amount = _unremitted_sum(tax_year, quarter)
        if amount <= 0:
            raise ApiError("ERR_NOTHING_TO_REMIT", 409,
                           "No positive UNREMITTED entry set for this year-quarter")
        rec = make_record("remittances", {
            "tax_year": tax_year,
            "quarter": quarter,
            "amount_cents": amount,
            "statutory_expected_cents": None,
            "created_by_user_id": caller_id(),
            "submitted_by_user_id": None,
            "status": "DRAFT",
        })
        return success_envelope(ser(rec), status=201)

    @app.get("/tax1099/remittances/<remittanceId>")
    @guard({"TaxSpecialist", "TaxAdmin", "TaxTransmitter"})
    def get_remittance(remittanceId):
        return success_envelope(ser(get_or_404("remittances", remittanceId)))

    @app.post("/tax1099/remittances/<remittanceId>/submit")
    @guard({"TaxTransmitter"})
    def submit_remittance(remittanceId):
        rec = get_or_404("remittances", remittanceId)
        if rec["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                           "Only a DRAFT remittance can be submitted")
        uid = caller_id()
        if uid == rec["created_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                           "Submitter must differ from the draft creator")
        amount = _unremitted_sum(rec["tax_year"], rec["quarter"])
        if amount <= 0:
            raise ApiError("ERR_NOTHING_TO_REMIT", 409,
                           "UNREMITTED entry set is empty or non-positive")
        year_row = find_tax_year_by_value(rec["tax_year"])
        rate = year_row["backup_withholding_rate_bps"] if year_row else DEFAULT_RATE_BPS
        gross = sum(p["amount_cents"] for p in store["payments"].values()
                    if p["status"] == "POSTED" and p["tax_year"] == rec["tax_year"]
                    and quarter_of(p["_date"]) == rec["quarter"] and p["withheld_cents"] > 0)
        swept_vendors = set()
        for e in store["withholding_entries"].values():
            if (e["status"] == "UNREMITTED" and e["tax_year"] == rec["tax_year"]
                    and e["quarter"] == rec["quarter"]):
                e["status"] = "REMITTED"
                e["remittance_id"] = rec["id"]
                swept_vendors.add(e["vendor_id"])
        rec["amount_cents"] = amount
        rec["statutory_expected_cents"] = withholding_cents(gross, rate) if gross > 0 else 0
        rec["submitted_by_user_id"] = uid
        rec["status"] = "SUBMITTED"
        touch(rec)
        return success_envelope(ser(rec))

    @app.post("/tax1099/remittances/<remittanceId>/record-outcome")
    @guard({"IRSSystem"})
    def remittance_outcome(remittanceId):
        rec = get_or_404("remittances", remittanceId)
        b = json_body()
        reject_unknown(b, {"outcome"})
        outcome = req_str(b, "outcome")
        if outcome not in ("ACKNOWLEDGED", "REJECTED"):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "outcome must be ACKNOWLEDGED or REJECTED")
        if rec["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                           "Outcome can only be recorded for a SUBMITTED remittance")
        if outcome == "ACKNOWLEDGED":
            rec["status"] = "ACKNOWLEDGED"
        else:
            for e in store["withholding_entries"].values():
                if e["remittance_id"] == rec["id"]:
                    e["status"] = "UNREMITTED"
                    e["remittance_id"] = None
            rec["status"] = "REJECTED"
        touch(rec)
        return success_envelope(ser(rec))

    @app.post("/tax1099/remittances/<remittanceId>/reopen")
    @guard({"TaxSpecialist"})
    def reopen_remittance(remittanceId):
        rec = get_or_404("remittances", remittanceId)
        if rec["status"] != "REJECTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                           "Only a REJECTED remittance can be reopened")
        rec["status"] = "DRAFT"
        rec["amount_cents"] = _unremitted_sum(rec["tax_year"], rec["quarter"])
        touch(rec)
        return success_envelope(ser(rec))
