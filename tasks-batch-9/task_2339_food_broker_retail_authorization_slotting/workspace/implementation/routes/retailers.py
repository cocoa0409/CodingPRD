"""Retail chain registration and reads (PRD section 3.1)."""

from flask import Blueprint

import db
import response
import validators as v
from errors import ApiError
from middleware import ALL_ROLES, authorize

bp = Blueprint("retailers", __name__)


def serialize(rec):
    return {
        "id": rec["id"],
        "name": rec["name"],
        "chain_code": rec["chain_code"],
        "total_store_count": rec["total_store_count"],
        "void_rate_basis_default": rec["void_rate_basis_default"],
        "at_risk_void_rate_bps": rec["at_risk_void_rate_bps"],
        "deduction_dispute_window_days": rec["deduction_dispute_window_days"],
        "demo_changeover_buffer_minutes": rec["demo_changeover_buffer_minutes"],
        "max_concurrent_demos": rec["max_concurrent_demos"],
        "review_blackout_days": rec["review_blackout_days"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


@bp.post("/retailers")
def create_retailer():
    authorize("BrokerAdmin")
    data = v.body()

    name = v.req_string(data, "name")
    chain_code = v.req_chain_code(data)
    total_store_count = v.req_int(data, "total_store_count", 1)
    void_rate_basis_default = v.opt_enum(data, "void_rate_basis_default", v.VOID_RATE_BASES, "STORE_COUNT_BASIS")
    at_risk_void_rate_bps = v.opt_bps(data, "at_risk_void_rate_bps", 1500)
    deduction_dispute_window_days = v.opt_int(data, "deduction_dispute_window_days", 90, 0)
    demo_changeover_buffer_minutes = v.opt_int(data, "demo_changeover_buffer_minutes", 30, 0)
    max_concurrent_demos = v.opt_int(data, "max_concurrent_demos", 2, 1)
    review_blackout_days = v.opt_int(data, "review_blackout_days", 14, 0)

    for existing in db.ordered("retailers"):
        if existing["chain_code"] == chain_code:
            raise ApiError("ERR_CHAIN_CODE_DUPLICATE")

    rec = db.base_record()
    rec.update({
        "name": name,
        "chain_code": chain_code,
        "total_store_count": total_store_count,
        "void_rate_basis_default": void_rate_basis_default,
        "at_risk_void_rate_bps": at_risk_void_rate_bps,
        "deduction_dispute_window_days": deduction_dispute_window_days,
        "demo_changeover_buffer_minutes": demo_changeover_buffer_minutes,
        "max_concurrent_demos": max_concurrent_demos,
        "review_blackout_days": review_blackout_days,
    })
    db.insert("retailers", rec)
    return response.created(serialize(rec))


@bp.get("/retailers/<retailer_id>")
def read_retailer(retailer_id):
    authorize(*ALL_ROLES)
    return response.ok(serialize(db.get("retailers", retailer_id)))


@bp.get("/retailers")
def list_retailers():
    authorize(*ALL_ROLES)
    limit, offset = v.pagination()
    chain_code = v.filter_value("chain_code")
    rows = [r for r in db.ordered("retailers") if chain_code is None or r["chain_code"] == chain_code]
    return response.listing([serialize(r) for r in rows], limit, offset)
