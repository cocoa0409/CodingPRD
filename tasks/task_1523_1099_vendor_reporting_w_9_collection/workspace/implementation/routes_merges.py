from flask import request

from errors import ApiError
from middleware import guard, caller_id
from response import success_envelope
from utils import json_body, reject_unknown, req_str, list_page
from db import store, make_record, touch, get_or_404
from serializers import merge_request as ser
from services import invalidate_open_returns, STAGE_RANK

NON_TERMINAL = ("DRAFT", "VALIDATED", "TRANSMITTED", "ACCEPTED")


def _target_has_open_return(target_id, tax_year, form_type):
    return any(r["vendor_id"] == target_id and r["tax_year"] == tax_year
               and r["form_type"] == form_type and r["federal_status"] in NON_TERMINAL
               for r in store["returns"].values())


def _execute_merge(source, target):
    src, tgt = source["id"], target["id"]
    for p in store["payments"].values():
        if p["vendor_id"] == src:
            p["vendor_id"] = tgt
    for e in store["withholding_entries"].values():
        if e["vendor_id"] == src:
            e["vendor_id"] = tgt
    for n in store["b_notices"].values():
        if n["vendor_id"] == src:
            n["vendor_id"] = tgt
    for s in store["w9_submissions"].values():
        if s["vendor_id"] == src and s["match_result"] != "PENDING":
            s["vendor_id"] = tgt
    for r in sorted(store["returns"].values(), key=lambda x: x["_seq"]):
        if r["vendor_id"] != src:
            continue
        if (r["federal_status"] in ("DRAFT", "VALIDATED")
                and _target_has_open_return(tgt, r["tax_year"], r["form_type"])):
            r["federal_status"] = "VOIDED"  # key collision: voided, not re-parented
            touch(r)
            continue
        r["vendor_id"] = tgt
        touch(r)
    for ob in store["state_obligations"].values():
        if ob["vendor_id"] == src:
            ob["vendor_id"] = tgt
    source["status"] = "MERGED"
    source["merged_into_vendor_id"] = tgt
    touch(source)
    # Target B-notice posture = highest OPEN stage among its (now combined) notices.
    best = "NONE"
    for n in store["b_notices"].values():
        if n["vendor_id"] == tgt and n["status"] == "OPEN":
            if STAGE_RANK[n["stage"]] > STAGE_RANK[best]:
                best = n["stage"]
    if target["b_notice_stage"] != best:
        target["b_notice_stage"] = best
    # Surviving DRAFT/VALIDATED returns of the combined vendor are invalidated.
    invalidate_open_returns(tgt)
    touch(target)


def register(app):
    @app.post("/tax1099/vendor-merge-requests")
    @guard({"APClerk"})
    def create_merge_request():
        b = json_body()
        reject_unknown(b, {"source_vendor_id", "target_vendor_id", "reason"})
        source_id = req_str(b, "source_vendor_id")
        target_id = req_str(b, "target_vendor_id")
        reason = req_str(b, "reason", allow_empty=True)
        if store["vendors"].get(source_id) is None:
            raise ApiError("ERR_NOT_FOUND", 404, "Vendor not found: %s" % source_id)
        if store["vendors"].get(target_id) is None:
            raise ApiError("ERR_NOT_FOUND", 404, "Vendor not found: %s" % target_id)
        if source_id == target_id:
            raise ApiError("ERR_SELF_MERGE", 422, "Source and target must differ")
        rec = make_record("merge_requests", {
            "source_vendor_id": source_id,
            "target_vendor_id": target_id,
            "reason": reason,
            "requested_by_user_id": caller_id(),
            "reviewed_by_user_id": None,
            "status": "PENDING",
        })
        return success_envelope(ser(rec), status=201)

    @app.post("/tax1099/vendor-merge-requests/<requestId>/approve")
    @guard({"TaxAdmin"})
    def approve_merge(requestId):
        rec = get_or_404("merge_requests", requestId)
        if rec["status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                           "Only a PENDING merge request can be approved")
        uid = caller_id()
        if uid == rec["requested_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                           "Approver must differ from the requester")
        if rec["source_vendor_id"] == rec["target_vendor_id"]:
            raise ApiError("ERR_SELF_MERGE", 422, "Source and target must differ")
        source = store["vendors"].get(rec["source_vendor_id"])
        target = store["vendors"].get(rec["target_vendor_id"])
        if (source is None or target is None or source["status"] != "ACTIVE"
                or target["status"] != "ACTIVE"):
            raise ApiError("ERR_VENDOR_NOT_ACTIVE", 409,
                           "Both vendors must be ACTIVE to merge")
        if source["tin"] is None or target["tin"] is None or source["tin"] != target["tin"]:
            raise ApiError("ERR_TIN_MISMATCH_ON_MERGE", 409,
                           "Merge requires equal, non-null TINs")
        if any(s["vendor_id"] == source["id"] and s["match_result"] == "PENDING"
               for s in store["w9_submissions"].values()):
            raise ApiError("ERR_VENDOR_HAS_OPEN_OBLIGATIONS", 409,
                           "Source vendor has a W-9 awaiting match")
        _execute_merge(source, target)
        rec["reviewed_by_user_id"] = uid
        rec["status"] = "EXECUTED"
        touch(rec)
        return success_envelope(ser(rec))

    @app.post("/tax1099/vendor-merge-requests/<requestId>/reject")
    @guard({"TaxAdmin"})
    def reject_merge(requestId):
        rec = get_or_404("merge_requests", requestId)
        if rec["status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                           "Only a PENDING merge request can be rejected")
        rec["reviewed_by_user_id"] = caller_id()
        rec["status"] = "REJECTED"
        touch(rec)
        return success_envelope(ser(rec))

    @app.get("/tax1099/vendor-merge-requests/<requestId>")
    @guard({"APClerk", "TaxAdmin"})
    def get_merge_request(requestId):
        return success_envelope(ser(get_or_404("merge_requests", requestId)))

    @app.get("/tax1099/vendor-merge-requests")
    @guard({"APClerk", "TaxAdmin"})
    def list_merge_requests():
        items = sorted(store["merge_requests"].values(), key=lambda r: r["_seq"])
        for f in ("source_vendor_id", "target_vendor_id", "status"):
            v = request.args.get(f)
            if v is not None:
                items = [r for r in items if str(r.get(f)) == v]
        page, pagination = list_page(items)
        return success_envelope([ser(r) for r in page], response_type="array",
                                pagination=pagination)
