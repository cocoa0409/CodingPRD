from errors import ApiError
from middleware import guard, caller_id
from response import success_envelope
from utils import json_body, reject_unknown, req_int, req_enum, req_str
from db import store, make_record, touch, get_or_404
from serializers import transmittal as ser
from services import (FORM_TYPES, find_tax_year_by_value, recompute_return_final,
                      qualifying_return_count, has_open_second_b_notice)


def _members(tid):
    return sorted((r for r in store["returns"].values() if r["transmittal_id"] == tid),
                  key=lambda r: r["_seq"])


def register(app):
    @app.post("/tax1099/transmittals")
    @guard({"TaxSpecialist"})
    def create_transmittal():
        b = json_body()
        reject_unknown(b, {"tax_year", "form_type"})
        year = req_int(b, "tax_year")
        form = req_enum(b, "form_type", FORM_TYPES)
        if find_tax_year_by_value(year) is None:
            raise ApiError("ERR_NO_TAX_YEAR", 422, "No TaxYear row exists for tax_year")
        rec = make_record("transmittals", {
            "tax_year": year,
            "form_type": form,
            "filing_channel": None,
            "return_count": 0,
            "sealed_by_user_id": None,
            "submitted_by_user_id": None,
            "status": "OPEN",
        })
        return success_envelope(ser(rec), status=201)

    @app.get("/tax1099/transmittals/<transmittalId>")
    @guard({"TaxSpecialist", "TaxAdmin", "TaxTransmitter"})
    def get_transmittal(transmittalId):
        return success_envelope(ser(get_or_404("transmittals", transmittalId)))

    @app.post("/tax1099/transmittals/<transmittalId>/seal")
    @guard({"TaxSpecialist"})
    def seal_transmittal(transmittalId):
        rec = get_or_404("transmittals", transmittalId)
        if rec["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                           "Only an OPEN transmittal can be sealed")
        eligible = sorted(
            (r for r in store["returns"].values()
             if r["federal_status"] == "VALIDATED" and r["tax_year"] == rec["tax_year"]
             and r["form_type"] == rec["form_type"] and r["transmittal_id"] is None),
            key=lambda r: r["_seq"])
        if not eligible:
            raise ApiError("ERR_TRANSMITTAL_EMPTY", 409,
                           "No eligible VALIDATED returns to seal")
        # Pinned order: members transition FIRST, then the channel count is taken.
        for r in eligible:
            r["federal_status"] = "TRANSMITTED"
            r["transmittal_id"] = rec["id"]
            recompute_return_final(r)
            touch(r)
        rec["return_count"] = len(eligible)
        rec["sealed_by_user_id"] = caller_id()
        ty = find_tax_year_by_value(rec["tax_year"])
        threshold = ty["efiling_threshold_count"] if ty else 10
        rec["filing_channel"] = ("EFILE" if qualifying_return_count(rec["tax_year"]) >= threshold
                                 else "PAPER")
        rec["status"] = "SEALED"
        touch(rec)
        return success_envelope(ser(rec))

    @app.post("/tax1099/transmittals/<transmittalId>/submit")
    @guard({"TaxTransmitter"})
    def submit_transmittal(transmittalId):
        rec = get_or_404("transmittals", transmittalId)
        b = json_body()
        reject_unknown(b, {"channel"})
        channel = req_str(b, "channel")
        if channel not in ("EFILE", "PAPER"):
            raise ApiError("ERR_INVALID_REQUEST", 400, "channel must be EFILE or PAPER")
        if rec["status"] != "SEALED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                           "Only a SEALED transmittal can be submitted")
        members = _members(rec["id"])
        for r in members:
            if has_open_second_b_notice(r["vendor_id"]):
                raise ApiError("ERR_UNRESOLVED_SECOND_B_NOTICE", 409,
                               "A member return's vendor has an OPEN SECOND B-notice")
        uid = caller_id()
        if uid == rec["sealed_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                           "Submitter must differ from the sealer")
        if channel == "PAPER":
            ty = find_tax_year_by_value(rec["tax_year"])
            threshold = ty["efiling_threshold_count"] if ty else 10
            if qualifying_return_count(rec["tax_year"]) >= threshold:
                raise ApiError("ERR_EFILE_REQUIRED", 409,
                               "E-filing is required at or above the threshold")
        rec["submitted_by_user_id"] = uid
        rec["status"] = "SUBMITTED"
        touch(rec)
        return success_envelope(ser(rec))

    @app.post("/tax1099/transmittals/<transmittalId>/record-outcome")
    @guard({"IRSSystem"})
    def transmittal_outcome(transmittalId):
        rec = get_or_404("transmittals", transmittalId)
        b = json_body()
        reject_unknown(b, {"outcome"})
        outcome = req_str(b, "outcome")
        if outcome not in ("ACCEPTED", "REJECTED"):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "outcome must be ACCEPTED or REJECTED")
        if rec["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                           "Outcome can only be recorded for a SUBMITTED transmittal")
        members = _members(rec["id"])
        if outcome == "ACCEPTED":
            for r in members:
                r["federal_status"] = "ACCEPTED"
                touch(r)
                if r["is_correction"] and r["corrects_return_id"]:
                    original = store["returns"].get(r["corrects_return_id"])
                    if original is not None and original["federal_status"] == "ACCEPTED":
                        original["federal_status"] = "SUPERSEDED"
                        touch(original)
            for ob in store["state_obligations"].values():
                if (ob["tax_year"] == rec["tax_year"]
                        and ob["required_channel"] == "CFSF_FORWARD"
                        and ob["status"] == "PENDING"):
                    ob["status"] = "FILED_VIA_CFSF"
                    touch(ob)
            rec["status"] = "ACCEPTED"
        else:
            for r in members:
                r["federal_status"] = "VALIDATED"
                r["transmittal_id"] = None
                touch(r)
            rec["status"] = "REJECTED"
        touch(rec)
        return success_envelope(ser(rec))

    @app.post("/tax1099/transmittals/<transmittalId>/reopen")
    @guard({"TaxSpecialist"})
    def reopen_transmittal(transmittalId):
        rec = get_or_404("transmittals", transmittalId)
        if rec["status"] != "REJECTED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                           "Only a REJECTED transmittal can be reopened")
        rec["status"] = "OPEN"
        rec["filing_channel"] = None
        rec["return_count"] = 0
        rec["sealed_by_user_id"] = None
        touch(rec)
        return success_envelope(ser(rec))
