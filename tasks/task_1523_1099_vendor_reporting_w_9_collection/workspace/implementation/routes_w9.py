from flask import request

from errors import ApiError
from middleware import guard
from response import success_envelope
from utils import json_body, reject_unknown, req_str, opt_str, req_enum, list_page
from db import store, make_record, touch, get_or_404
from serializers import w9_submission as ser
from services import TIN_TYPES


def register(app):
    @app.post("/tax1099/vendors/<vendorId>/w9-submissions")
    @guard({"APClerk", "VendorPortal"}, portal_vendor_param="vendorId")
    def create_w9(vendorId):
        vendor = get_or_404("vendors", vendorId)
        b = json_body()
        reject_unknown(b, {"submitted_legal_name", "submitted_tin",
                           "submitted_tin_type", "signature_name"})
        name = req_str(b, "submitted_legal_name")
        tin = req_str(b, "submitted_tin")
        tin_type = req_enum(b, "submitted_tin_type", TIN_TYPES)
        sig = req_str(b, "signature_name")
        # Referential usability (rung 9) precedes structural TIN shape (rung 10).
        if vendor["status"] != "ACTIVE":
            raise ApiError("ERR_VENDOR_NOT_ACTIVE", 409,
                           "W-9 submissions require an ACTIVE vendor")
        if len(tin) != 9 or not tin.isascii() or not tin.isdigit():
            raise ApiError("ERR_INVALID_TIN_FORMAT", 422,
                           "submitted_tin must be exactly 9 ASCII digits")
        rec = make_record("w9_submissions", {
            "vendor_id": vendor["id"],
            "submitted_legal_name": name,
            "submitted_tin": tin,
            "submitted_tin_type": tin_type,
            "signature_name": sig,
            "match_result": "PENDING",
            "mismatch_reason_code": None,
        })
        # Creation moves the vendor to PENDING_MATCH from any prior match state.
        if vendor["tin_match_status"] != "PENDING_MATCH":
            vendor["tin_match_status"] = "PENDING_MATCH"
            touch(vendor)
        return success_envelope(ser(rec), status=201)

    @app.get("/tax1099/w9-submissions/<submissionId>")
    @guard({"APClerk", "TaxAdmin", "TaxSpecialist"})
    def get_w9(submissionId):
        return success_envelope(ser(get_or_404("w9_submissions", submissionId)))

    @app.get("/tax1099/w9-submissions")
    @guard({"APClerk", "TaxAdmin", "TaxSpecialist"})
    def list_w9():
        items = sorted(store["w9_submissions"].values(), key=lambda r: r["_seq"])
        for f in ("vendor_id", "match_result"):
            v = request.args.get(f)
            if v is not None:
                items = [r for r in items if str(r.get(f)) == v]
        page, pagination = list_page(items)
        return success_envelope([ser(r) for r in page], response_type="array",
                                pagination=pagination)

    @app.post("/tax1099/w9-submissions/<submissionId>/record-match-result")
    @guard({"IRSSystem"})
    def record_match_result(submissionId):
        sub = get_or_404("w9_submissions", submissionId)
        b = json_body()
        reject_unknown(b, {"match_result", "mismatch_reason_code"})
        result = req_enum(b, "match_result", {"MATCHED", "MISMATCHED"})
        reason = opt_str(b, "mismatch_reason_code")
        if result == "MISMATCHED" and (reason is None or not reason.strip()):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "mismatch_reason_code is required for a MISMATCHED result")
        if sub["match_result"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                           "Submission is no longer PENDING")
        vendor = store["vendors"].get(sub["vendor_id"])
        if vendor is None or vendor["status"] != "ACTIVE":
            raise ApiError("ERR_VENDOR_NOT_ACTIVE", 409,
                           "Vendor must be ACTIVE to record a match result")
        if result == "MATCHED":
            vendor["tin"] = sub["submitted_tin"]
            vendor["tin_type"] = sub["submitted_tin_type"]
            vendor["legal_name"] = sub["submitted_legal_name"]
            vendor["tin_match_status"] = "MATCHED"
        else:
            vendor["tin_match_status"] = "MISMATCHED"
            sub["mismatch_reason_code"] = reason
        sub["match_result"] = result
        touch(sub)
        touch(vendor)
        return success_envelope(ser(sub))
