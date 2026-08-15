from flask import request

from errors import ApiError
from middleware import guard
from response import success_envelope
from utils import json_body, reject_unknown, req_int, req_enum, list_page
from db import store, make_record, touch, get_or_404, logical_now, fmt_ts
from serializers import tax_return as ser
from services import (find_tax_year_by_value, aggregate_year, boxes_for_form,
                      recompute_return_final)

NON_TERMINAL = ("DRAFT", "VALIDATED", "TRANSMITTED", "ACCEPTED")


def _box_sums(vendor_id, tax_year):
    return aggregate_year(vendor_id, tax_year)


def register(app):
    @app.post("/tax1099/returns/generate")
    @guard({"TaxSpecialist"})
    def generate_returns():
        b = json_body()
        reject_unknown(b, {"tax_year"})
        year = req_int(b, "tax_year")
        ty = find_tax_year_by_value(year)
        if ty is None:
            raise ApiError("ERR_NO_TAX_YEAR", 422, "No TaxYear row exists for tax_year")
        vendor_ids = []
        seen = set()
        for p in sorted(store["payments"].values(), key=lambda r: r["_seq"]):
            if p["status"] == "POSTED" and p["tax_year"] == year and p["vendor_id"] not in seen:
                seen.add(p["vendor_id"])
                vendor_ids.append(p["vendor_id"])
        generated_ids = []
        skipped = 0
        for vid in vendor_ids:
            sums, box4 = _box_sums(vid, year)
            forms = []
            if sums["NEC_1"] >= ty["nec_reportable_threshold_cents"]:
                forms.append("NEC")
            if (sums["MISC_1"] + sums["MISC_2"] + sums["MISC_3"] + sums["MISC_6"]
                    >= ty["misc_reportable_threshold_cents"]):
                forms.append("MISC")
            for form in forms:
                dup = any(r["vendor_id"] == vid and r["tax_year"] == year
                          and r["form_type"] == form and r["federal_status"] in NON_TERMINAL
                          for r in store["returns"].values())
                if dup:
                    skipped += 1
                    continue
                boxes = boxes_for_form(form, sums, box4)
                rec = make_record("returns", {
                    "vendor_id": vid,
                    "tax_year": year,
                    "form_type": form,
                    "box_amounts": dict(boxes),
                    "provisional_box_amounts": dict(boxes),
                    "amount_basis": "PROVISIONAL",
                    "is_correction": False,
                    "corrects_return_id": None,
                    "transmittal_id": None,
                    "federal_status": "DRAFT",
                    "recipient_copy_status": "PENDING",
                    "copy_delivered_at": None,
                })
                generated_ids.append(rec["id"])
        return success_envelope({"generated_count": len(generated_ids),
                                 "generated_return_ids": generated_ids,
                                 "skipped_count": skipped}, status=201)

    @app.get("/tax1099/returns/<returnId>")
    @guard({"TaxSpecialist", "TaxAdmin"})
    def get_return(returnId):
        return success_envelope(ser(get_or_404("returns", returnId)))

    @app.get("/tax1099/returns")
    @guard({"TaxSpecialist", "TaxAdmin"})
    def list_returns():
        items = sorted(store["returns"].values(), key=lambda r: r["_seq"])
        for f in ("vendor_id", "tax_year", "form_type", "federal_status",
                  "transmittal_id", "corrects_return_id"):
            v = request.args.get(f)
            if v is not None:
                items = [r for r in items if str(r.get(f)) == v]
        page, pagination = list_page(items)
        return success_envelope([ser(r) for r in page], response_type="array",
                                pagination=pagination)

    @app.post("/tax1099/returns/<returnId>/validate")
    @guard({"TaxSpecialist"})
    def validate_return(returnId):
        rec = get_or_404("returns", returnId)
        if rec["federal_status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                           "Only a DRAFT return can be validated")
        vendor = store["vendors"].get(rec["vendor_id"])
        if (vendor is None or vendor["tin_match_status"] not in ("MATCHED", "MISMATCHED")
                or vendor["tin"] is None):
            raise ApiError("ERR_W9_NOT_ON_FILE", 409,
                           "Validation requires a resolved W-9 with a TIN on file")
        if vendor["status"] != "ACTIVE":
            raise ApiError("ERR_VENDOR_NOT_ACTIVE", 409, "Vendor must be ACTIVE")
        rec["federal_status"] = "VALIDATED"
        touch(rec)
        return success_envelope(ser(rec))

    @app.post("/tax1099/returns/<returnId>/void")
    @guard({"TaxSpecialist"})
    def void_return(returnId):
        rec = get_or_404("returns", returnId)
        if rec["federal_status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                           "Only a DRAFT return can be voided")
        rec["federal_status"] = "VOIDED"
        touch(rec)
        return success_envelope(ser(rec))

    @app.post("/tax1099/returns/<returnId>/correct")
    @guard({"TaxSpecialist"})
    def correct_return(returnId):
        original = get_or_404("returns", returnId)
        b = json_body()
        reject_unknown(b, {"expected_return_version"})
        expected = req_int(b, "expected_return_version")
        # OCC (rung 5) precedes the structural correctability rule (rung 10).
        if expected != original["version"]:
            raise ApiError("ERR_STALE_VERSION", 412,
                           "expected_return_version does not match the current version")
        if original["federal_status"] != "ACCEPTED":
            raise ApiError("ERR_RETURN_NOT_CORRECTABLE", 409,
                           "Only an ACCEPTED return can be corrected")
        for r in store["returns"].values():
            if (r["corrects_return_id"] == original["id"]
                    and r["federal_status"] in ("DRAFT", "VALIDATED", "TRANSMITTED")):
                raise ApiError("ERR_RETURN_NOT_CORRECTABLE", 409,
                               "Another non-terminal correction already exists")
        touch(original)  # successful OCC-guarded write increments the original's version
        sums, box4 = _box_sums(original["vendor_id"], original["tax_year"])
        boxes = boxes_for_form(original["form_type"], sums, box4)
        rec = make_record("returns", {
            "vendor_id": original["vendor_id"],
            "tax_year": original["tax_year"],
            "form_type": original["form_type"],
            "box_amounts": dict(boxes),
            "provisional_box_amounts": dict(boxes),
            "amount_basis": "FINAL",
            "is_correction": True,
            "corrects_return_id": original["id"],
            "transmittal_id": None,
            "federal_status": "DRAFT",
            "recipient_copy_status": "PENDING",
            "copy_delivered_at": None,
        })
        return success_envelope(ser(rec), status=201)

    @app.post("/tax1099/returns/<returnId>/deliver-copy")
    @guard({"TaxSpecialist"})
    def deliver_copy(returnId):
        rec = get_or_404("returns", returnId)
        b = json_body()
        reject_unknown(b, {"channel"})
        channel = req_enum(b, "channel", {"POSTAL", "ELECTRONIC"})
        if (rec["federal_status"] not in ("VALIDATED", "TRANSMITTED", "ACCEPTED")
                or rec["recipient_copy_status"] not in ("PENDING", "UNDELIVERABLE")):
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                           "Copy delivery is not allowed from the current state")
        ty = find_tax_year_by_value(rec["tax_year"])
        if ty is not None and logical_now() > ty["_deadline"]:
            raise ApiError("ERR_COPY_DEADLINE_PASSED", 409,
                           "Recipient copy deadline has passed")
        if channel == "ELECTRONIC":
            vendor = store["vendors"].get(rec["vendor_id"])
            if vendor is None or not vendor["e_delivery_consent"]:
                raise ApiError("ERR_ELECTRONIC_CONSENT_REQUIRED", 409,
                               "Electronic delivery requires vendor consent")
        rec["recipient_copy_status"] = "POSTAL_SENT" if channel == "POSTAL" else "E_DELIVERED"
        rec["copy_delivered_at"] = fmt_ts(logical_now())
        touch(rec)
        return success_envelope(ser(rec))

    @app.post("/tax1099/returns/<returnId>/record-copy-bounce")
    @guard({"IRSSystem"})
    def copy_bounce(returnId):
        rec = get_or_404("returns", returnId)
        if rec["recipient_copy_status"] != "POSTAL_SENT":
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                           "Only a POSTAL_SENT copy can bounce")
        rec["recipient_copy_status"] = "UNDELIVERABLE"
        touch(rec)
        return success_envelope(ser(rec))
