from flask import request

from errors import ApiError
from middleware import guard
from response import success_envelope
from utils import (json_body, reject_unknown, req_str, opt_str, opt_bool, opt_enum,
                   req_int, req_enum, list_page)
from db import store, make_record, touch, get_or_404
from serializers import vendor as ser
from services import (ENTITY_CLASSIFICATIONS, TIN_TYPES, vendor_balance,
                      invalidate_open_returns)


def _check_tin(tin):
    if tin is not None and (len(tin) != 9 or not tin.isascii() or not tin.isdigit()):
        raise ApiError("ERR_INVALID_TIN_FORMAT", 422, "TIN must be exactly 9 ASCII digits")


def register(app):
    @app.post("/tax1099/vendors")
    @guard({"APClerk", "TaxAdmin"})
    def create_vendor():
        b = json_body()
        reject_unknown(b, {"legal_name", "entity_classification", "address_line1",
                           "address_city", "address_state", "address_postal",
                           "tin", "tin_type", "e_delivery_consent"})
        legal_name = req_str(b, "legal_name")
        classification = req_enum(b, "entity_classification", ENTITY_CLASSIFICATIONS)
        line1 = req_str(b, "address_line1")
        city = req_str(b, "address_city")
        state = req_str(b, "address_state")
        postal = req_str(b, "address_postal")
        tin = opt_str(b, "tin")
        tin_type = opt_enum(b, "tin_type", TIN_TYPES)
        consent = opt_bool(b, "e_delivery_consent", False)
        _check_tin(tin)
        rec = make_record("vendors", {
            "legal_name": legal_name,
            "tin": tin,
            "tin_type": tin_type,
            "entity_classification": classification,
            "address_line1": line1,
            "address_city": city,
            "address_state": state,
            "address_postal": postal,
            "e_delivery_consent": consent,
            "tin_match_status": "NOT_SUBMITTED",
            "b_notice_stage": "NONE",
            "merged_into_vendor_id": None,
            "status": "ACTIVE",
        })
        return success_envelope(ser(rec), status=201)

    @app.get("/tax1099/vendors/<vendorId>")
    @guard({"APClerk", "TaxAdmin", "TaxSpecialist", "VendorPortal"},
           portal_vendor_param="vendorId")
    def get_vendor(vendorId):
        rec = get_or_404("vendors", vendorId)
        return success_envelope(ser(rec))

    @app.get("/tax1099/vendors")
    @guard({"APClerk", "TaxAdmin", "TaxSpecialist"})
    def list_vendors():
        items = sorted(store["vendors"].values(), key=lambda r: r["_seq"])
        for f in ("status", "tin_match_status", "b_notice_stage", "merged_into_vendor_id"):
            v = request.args.get(f)
            if v is not None:
                items = [r for r in items if str(r.get(f)) == v]
        page, pagination = list_page(items)
        return success_envelope([ser(r) for r in page], response_type="array",
                                pagination=pagination)

    @app.patch("/tax1099/vendors/<vendorId>")
    @guard({"APClerk", "TaxAdmin"})
    def patch_vendor(vendorId):
        rec = get_or_404("vendors", vendorId)
        b = json_body()
        reject_unknown(b, {"legal_name", "address_line1", "address_city", "address_state",
                           "address_postal", "e_delivery_consent", "entity_classification",
                           "expected_vendor_version"})
        expected = req_int(b, "expected_vendor_version")
        upd = {}
        for f in ("legal_name", "address_line1", "address_city", "address_state", "address_postal"):
            if f in b:
                upd[f] = req_str(b, f)
        if "e_delivery_consent" in b:
            upd["e_delivery_consent"] = opt_bool(b, "e_delivery_consent")
        if "entity_classification" in b:
            upd["entity_classification"] = opt_enum(b, "entity_classification",
                                                    ENTITY_CLASSIFICATIONS)
        # OCC (rung 5) precedes the referential ACTIVE check (rung 9).
        if expected != rec["version"]:
            raise ApiError("ERR_STALE_VERSION", 412,
                           "expected_vendor_version does not match the current version")
        if rec["status"] != "ACTIVE":
            raise ApiError("ERR_VENDOR_NOT_ACTIVE", 409,
                           "Vendor must be ACTIVE to update")
        classification_changed = ("entity_classification" in upd
                                  and upd["entity_classification"] != rec["entity_classification"])
        rec.update(upd)
        touch(rec)
        if classification_changed:
            # Open years only; posted payments are never reclassified.
            invalidate_open_returns(rec["id"], open_years_only=True)
        return success_envelope(ser(rec))

    @app.post("/tax1099/vendors/<vendorId>/deactivate")
    @guard({"TaxAdmin"})
    def deactivate_vendor(vendorId):
        rec = get_or_404("vendors", vendorId)
        if rec["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                           "Only an ACTIVE vendor can be deactivated")
        if vendor_balance(rec["id"]) != 0:
            raise ApiError("ERR_VENDOR_HAS_OPEN_OBLIGATIONS", 409,
                           "Vendor has a nonzero withholding balance")
        for ret in store["returns"].values():
            if (ret["vendor_id"] == rec["id"]
                    and ret["federal_status"] in ("DRAFT", "VALIDATED")):
                raise ApiError("ERR_VENDOR_HAS_OPEN_OBLIGATIONS", 409,
                               "Vendor has open DRAFT/VALIDATED returns")
        rec["status"] = "DEACTIVATED"
        touch(rec)
        return success_envelope(ser(rec))
