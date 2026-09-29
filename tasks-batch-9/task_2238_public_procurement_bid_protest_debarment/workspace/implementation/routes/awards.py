"""Notice of award, the statutory stay and execution (PRD §3.6)."""

from flask import Blueprint

import calc
import serializers
import services
import store
import validation as v
from errors import ApiError

bp = Blueprint("awards", __name__)

RESOLVED_PROTEST_STATUSES = ("SUSTAINED", "DENIED", "WITHDRAWN")


@bp.post("/procurement/awards")
@v.endpoint(["ProcurementOfficer"])
def create_award():
    data = v.body()
    solicitation_id = v.req_str(data, "solicitation_id")
    winning_bid_id = v.req_str(data, "winning_bid_id")

    solicitation = services.must("solicitations", solicitation_id)
    winning_bid = services.must("bids", winning_bid_id)

    if solicitation["status"] != "AWARD_PENDING":
        raise ApiError("ERR_INVALID_SOLICITATION_STATE")

    if solicitation["apparent_low_bid_id"] is None:
        raise ApiError("ERR_NO_APPARENT_LOW_BIDDER")

    if services.has_active_stay(solicitation):
        raise ApiError("ERR_AWARD_STAYED")

    if winning_bid["solicitation_id"] != solicitation["id"]:
        raise ApiError("ERR_BID_NOT_ON_SOLICITATION")

    if solicitation["apparent_low_bid_id"] != winning_bid["id"]:
        raise ApiError("ERR_NOT_APPARENT_LOW_BIDDER")

    base = winning_bid["evaluated_price_cents"]
    has_resolved = any(
        p["status"] in RESOLVED_PROTEST_STATUSES for p in services.protests_of(solicitation)
    )
    rate, fee, reserve, total = calc.award_amounts(base, has_resolved)

    award = store.insert("awards", store.row("awards", {
        "solicitation_id": solicitation["id"],
        "winning_bid_id": winning_bid["id"],
        "vendor_id": winning_bid["vendor_id"],
        "base_obligation_cents": base,
        "administrative_fee_rate": rate,
        "administrative_fee_cents": fee,
        "protest_risk_reserve_cents": reserve,
        "award_total_obligation_cents": total,
        "status": "PENDING_STAY",
        "executed_at_utc": None,
        "void_reason_code": None,
    }))
    return ("obj", award, serializers.award, 201)


@bp.post("/procurement/awards/<award_id>/execute")
@v.endpoint(["ProcurementOfficer"])
def execute_award(award_id):
    award = services.must("awards", award_id)
    solicitation = services.must("solicitations", award["solicitation_id"])

    if award["status"] != "PENDING_STAY" or solicitation["status"] != "AWARD_PENDING":
        raise ApiError("ERR_INVALID_SOLICITATION_STATE")

    if services.has_active_stay(solicitation):
        raise ApiError("ERR_AWARD_STAYED")

    v.set_field(award, "status", "EXECUTED")
    v.set_field(award, "executed_at_utc", store.now())
    v.set_field(solicitation, "status", "AWARDED")
    return ("obj", award, serializers.award, 200)


@bp.get("/procurement/awards/<award_id>")
@v.endpoint(v.ALL_ROLES)
def read_award(award_id):
    return ("obj", services.must("awards", award_id), serializers.award, 200)


@bp.get("/procurement/awards")
@v.endpoint(v.ALL_ROLES)
def list_awards():
    limit, offset = v.pagination()
    filters = {
        "solicitation_id": v.query("solicitation_id"),
        "winning_bid_id": v.query("winning_bid_id"),
        "vendor_id": v.query("vendor_id"),
        "status": v.query("status"),
    }
    rows = [r for r in store.ordered(store.values("awards")) if v.match_filters(r, filters)]
    page, total = v.paginate(rows, limit, offset)
    return ("list", page, serializers.award, limit, offset, total)
