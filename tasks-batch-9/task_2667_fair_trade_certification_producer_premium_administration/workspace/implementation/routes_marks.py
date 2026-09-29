"""On-pack mark usage requests and the officer's decision."""
from flask import Blueprint

import common as C
import domain as D
import store as S
import validators as V
from common import new_id, now_iso
from errors import ApiError
from response import created, listing, ok
from store import ordered, touch_once

bp = Blueprint("marks", __name__)


@bp.post("/mark-usage-requests")
def file_mark_request():
    from auth import authorize
    user_id, role = authorize("BrandLicensee")
    data = V.body()
    brand_holder_id = V.req_id(data, "brand_holder_id")
    sku_code = V.req_str(data, "sku_code", 40)
    artwork_ref = V.req_str(data, "artwork_ref", 80)
    claim_type = V.req_enum(data, "claim_type", C.CLAIM_TYPES)
    requested_volume_kg = V.req_number(data, "requested_volume_kg", 3,
                                       exclusive_min=0)

    holder = S.holder_or_404(brand_holder_id)
    if user_id != brand_holder_id:
        raise ApiError("ERR_HOLDER_OWNERSHIP_MISMATCH",
                       "X-User-ID is not this brand holder")
    if holder["label_license_status"] != "ACTIVE":
        raise ApiError("ERR_LABEL_LICENSE_INACTIVE",
                       "label_license_status is %s" % holder["label_license_status"])

    mark = {
        "id": new_id(),
        "brand_holder_id": brand_holder_id,
        "sku_code": sku_code,
        "artwork_ref": artwork_ref,
        "claim_type": claim_type,
        "requested_volume_kg": requested_volume_kg,
        "status": "SUBMITTED",
        "decided_by_user_id": None,
        "decision_reason": None,
        "decided_at": None,
    }
    S.stamp_new(mark)
    S.marks[mark["id"]] = mark
    return created(mark)


@bp.post("/mark-usage-requests/<mark_id>/decide")
def decide_mark_request(mark_id):
    from auth import authorize
    user_id, role = authorize("CertificationOfficer")
    data = V.body()
    decision = V.req_enum(data, "decision", ("APPROVE", "REJECT"))
    reason = V.opt_str(data, "reason", 1000)
    mark = S.mark_or_404(mark_id)
    if mark["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "mark usage request status is %s" % mark["status"])
    holder = S.holders[mark["brand_holder_id"]]

    if decision == "APPROVE":
        if holder["label_license_status"] != "ACTIVE":
            raise ApiError("ERR_LABEL_LICENSE_INACTIVE",
                           "label_license_status is %s"
                           % holder["label_license_status"])
        if mark["claim_type"] == "FT_CERTIFIED_100":
            summary = D.traceability_summary(holder)
            if summary["chain_mode"] != "ALL_PHYSICAL":
                raise ApiError("ERR_TRACEABILITY_MODE_MISMATCH",
                               "chain_mode is %s" % summary["chain_mode"])
        if not holder["license_fee_settled"]:
            raise ApiError("ERR_LICENSE_FEE_UNPAID",
                           "the label licence fee is not settled")
        mark["status"] = "APPROVED"
    else:
        mark["status"] = "REJECTED"

    mark["decided_by_user_id"] = user_id
    mark["decision_reason"] = reason
    mark["decided_at"] = now_iso()
    touch_once(mark)
    return ok(mark)


@bp.get("/mark-usage-requests/<mark_id>")
def read_mark_request(mark_id):
    from auth import authorize
    authorize("CertificationOfficer", "Auditor", "BrandLicensee")
    return ok(S.mark_or_404(mark_id))


@bp.get("/certificate-holders/<holder_id>/mark-usage-requests")
def list_mark_requests(holder_id):
    from auth import authorize
    authorize("CertificationOfficer", "Auditor", "BrandLicensee")
    status = V.enum_filter("status", C.MARK_STATUSES)
    claim_type = V.enum_filter("claim_type", C.CLAIM_TYPES)
    S.holder_or_404(holder_id)
    rows = [m for m in ordered(list(S.marks.values()))
            if m["brand_holder_id"] == holder_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if claim_type:
        rows = [r for r in rows if r["claim_type"] == claim_type]
    page, limit, offset, total = V.paginate(rows)
    return listing(page, limit, offset, total)
