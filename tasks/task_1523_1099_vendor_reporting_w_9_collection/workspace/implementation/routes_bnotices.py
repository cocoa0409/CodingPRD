from flask import request

from errors import ApiError
from middleware import guard, caller_id, caller_role
from response import success_envelope
from utils import json_body, reject_unknown, req_str, req_int, opt_str, list_page
from db import store, make_record, touch, get_or_404
from serializers import b_notice as ser
from services import STAGE_RANK, mismatch_count_3yr


def _recompute_vendor_stage(vendor):
    best = "NONE"
    for n in store["b_notices"].values():
        if n["vendor_id"] == vendor["id"] and n["status"] == "OPEN":
            if STAGE_RANK[n["stage"]] > STAGE_RANK[best]:
                best = n["stage"]
    if vendor["b_notice_stage"] != best:
        vendor["b_notice_stage"] = best
        touch(vendor)


def register(app):
    @app.post("/tax1099/b-notices")
    @guard({"IRSSystem"})
    def create_b_notice():
        b = json_body()
        reject_unknown(b, {"vendor_id", "notice_year"})
        vendor_id = req_str(b, "vendor_id")
        year = req_int(b, "notice_year")
        vendor = store["vendors"].get(vendor_id)
        if vendor is None:
            raise ApiError("ERR_NOT_FOUND", 404, "Vendor not found: %s" % vendor_id)
        rec_seq_marker = None  # new record will have the highest seq
        prior = any(n["vendor_id"] == vendor["id"]
                    and year - 2 <= n["notice_year"] <= year
                    for n in store["b_notices"].values())
        stage = "SECOND" if (prior or mismatch_count_3yr(vendor["id"]) >= 2) else "FIRST"
        rec = make_record("b_notices", {
            "vendor_id": vendor["id"],
            "notice_year": year,
            "stage": stage,
            "status": "OPEN",
            "resolved_by_user_id": None,
        })
        if STAGE_RANK[stage] > STAGE_RANK[vendor["b_notice_stage"]]:
            vendor["b_notice_stage"] = stage
            touch(vendor)
        return success_envelope(ser(rec), status=201)

    @app.get("/tax1099/b-notices/<noticeId>")
    @guard({"TaxSpecialist", "TaxAdmin", "IRSSystem"})
    def get_b_notice(noticeId):
        return success_envelope(ser(get_or_404("b_notices", noticeId)))

    @app.get("/tax1099/b-notices")
    @guard({"TaxSpecialist", "TaxAdmin", "IRSSystem"})
    def list_b_notices():
        items = sorted(store["b_notices"].values(), key=lambda r: r["_seq"])
        for f in ("vendor_id", "status"):
            v = request.args.get(f)
            if v is not None:
                items = [r for r in items if str(r.get(f)) == v]
        page, pagination = list_page(items)
        return success_envelope([ser(r) for r in page], response_type="array",
                                pagination=pagination)

    @app.post("/tax1099/b-notices/<noticeId>/resolve")
    @guard({"TaxSpecialist", "TaxAdmin"})
    def resolve_b_notice(noticeId):
        rec = get_or_404("b_notices", noticeId)
        b = json_body()
        reject_unknown(b, {"resolution_code"})
        resolution_code = opt_str(b, "resolution_code")
        if rec["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                           "Only an OPEN notice can be resolved")
        vendor = store["vendors"].get(rec["vendor_id"])
        if rec["stage"] == "FIRST":
            fresh_match = any(
                s["vendor_id"] == rec["vendor_id"] and s["match_result"] == "MATCHED"
                and s["_seq"] > rec["_seq"]
                for s in store["w9_submissions"].values())
            if vendor is None or vendor["tin_match_status"] != "MATCHED" or not fresh_match:
                raise ApiError("ERR_B_NOTICE_NOT_RESOLVABLE", 409,
                               "FIRST notice requires a fresh MATCHED W-9")
        else:  # SECOND — TaxAdmin override only, with the IRS/SSA validation code
            if caller_role() != "TaxAdmin" or resolution_code != "IRS_SSA_VALIDATION":
                raise ApiError("ERR_B_NOTICE_NOT_RESOLVABLE", 409,
                               "SECOND notice requires TaxAdmin with IRS_SSA_VALIDATION")
        rec["status"] = "RESOLVED"
        rec["resolved_by_user_id"] = caller_id()
        touch(rec)
        if vendor is not None:
            _recompute_vendor_stage(vendor)
        return success_envelope(ser(rec))
