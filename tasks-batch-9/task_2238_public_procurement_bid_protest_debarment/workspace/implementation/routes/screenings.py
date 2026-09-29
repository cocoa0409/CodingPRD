"""Subcontractor screening against the debarred-vendor list (PRD §3.9)."""

from flask import Blueprint, g

import serializers
import services
import store
import validation as v
from errors import ApiError

bp = Blueprint("screenings", __name__)

SUPPORTED_TIERS = (1, 2, 3)


@bp.post("/procurement/subcontractor-screenings")
@v.endpoint(["ProcurementOfficer", "Vendor"])
def screen_subcontractor():
    data = v.body()
    solicitation_id = v.req_str(data, "solicitation_id")
    prime_vendor_id = v.req_str(data, "prime_vendor_id")
    sub_vendor_id = v.req_str(data, "sub_vendor_id")
    tier = v.req_int(data, "tier")

    solicitation = services.must("solicitations", solicitation_id)
    prime = services.must("vendors", prime_vendor_id)
    sub = services.must("vendors", sub_vendor_id)

    if g.user_role == "Vendor" and g.user_id != prime["id"]:
        raise ApiError("ERR_VENDOR_IDENTITY_MISMATCH")

    if tier not in SUPPORTED_TIERS:
        raise ApiError("ERR_SUBCONTRACT_TIER_UNSUPPORTED")
    if prime["id"] == sub["id"]:
        raise ApiError("ERR_SELF_SUBCONTRACT")

    if sub["eligibility_status"] == "ELIGIBLE":
        result = "CLEARED"
        blocked_reason_code = None
    elif sub["eligibility_status"] == "SUSPENDED":
        result = "BLOCKED_SUSPENDED"
        blocked_reason_code = sub["suspension_reason_code"]
    else:
        result = "BLOCKED_DEBARRED"
        blocked_reason_code = sub["suspension_reason_code"]

    screening = store.insert("screenings", store.row("screenings", {
        "solicitation_id": solicitation["id"],
        "prime_vendor_id": prime["id"],
        "sub_vendor_id": sub["id"],
        "tier": tier,
        "result": result,
        "blocked_reason_code": blocked_reason_code,
        "screened_at_utc": store.now(),
        "rescreened_count": 0,
    }))
    return ("obj", screening, serializers.screening, 201)


@bp.get("/procurement/subcontractor-screenings/<screening_id>")
@v.endpoint(v.ALL_ROLES)
def read_screening(screening_id):
    return ("obj", services.must("screenings", screening_id), serializers.screening, 200)


@bp.get("/procurement/subcontractor-screenings")
@v.endpoint(v.ALL_ROLES)
def list_screenings():
    limit, offset = v.pagination()
    filters = {
        "solicitation_id": v.query("solicitation_id"),
        "prime_vendor_id": v.query("prime_vendor_id"),
        "sub_vendor_id": v.query("sub_vendor_id"),
        "result": v.query("result"),
    }
    rows = [r for r in store.ordered(store.values("screenings")) if v.match_filters(r, filters)]
    page, total = v.paginate(rows, limit, offset)
    return ("list", page, serializers.screening, limit, offset, total)
