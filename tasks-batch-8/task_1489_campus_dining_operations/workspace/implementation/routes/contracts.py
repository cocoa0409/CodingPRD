"""VendorContract endpoints."""
from flask import Blueprint

from db import DB, new_id, next_seq
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok
from services import get_contract, get_hall, ser, stamp, touch
from util import as_int, as_iso_date, as_str, body, parse_ymd, required
from routes.common import list_endpoint

bp = Blueprint("contracts", __name__)


@bp.post("/vendor-contracts")
def create_contract():
    auth(["DiningAdmin"])
    data = body()
    # Body FK existence in declared input order (tier 3).
    dining_hall_id = required(data, "dining_hall_id")
    if isinstance(dining_hall_id, str):
        get_hall(dining_hall_id)
    vendor_name = as_str(required(data, "vendor_name"), "vendor_name")
    board_rate = as_int(
        required(data, "board_rate_per_cover_cents"), "board_rate_per_cover_cents"
    )
    if board_rate < 0:
        raise ApiError("ERR_VALIDATION", 400, "board_rate_per_cover_cents must be >= 0")
    retail_bps = as_int(required(data, "retail_commission_bps"), "retail_commission_bps")
    if not 0 <= retail_bps <= 10000:
        raise ApiError("ERR_VALIDATION", 400, "retail_commission_bps must be 0..10000")
    catering_bps = as_int(
        required(data, "catering_commission_bps"), "catering_commission_bps"
    )
    if not 0 <= catering_bps <= 10000:
        raise ApiError("ERR_VALIDATION", 400, "catering_commission_bps must be 0..10000")
    guarantee = as_int(
        required(data, "minimum_monthly_guarantee_cents"),
        "minimum_monthly_guarantee_cents",
    )
    if guarantee < 0:
        raise ApiError(
            "ERR_VALIDATION", 400, "minimum_monthly_guarantee_cents must be >= 0"
        )
    start = as_iso_date(required(data, "effective_start_date"), "effective_start_date")
    end = as_iso_date(required(data, "effective_end_date"), "effective_end_date")
    if parse_ymd(end) <= parse_ymd(start):
        raise ApiError(
            "ERR_VALIDATION", 400, "effective_end_date must be after effective_start_date"
        )
    if not isinstance(dining_hall_id, str):
        raise ApiError("ERR_VALIDATION", 400, "dining_hall_id must be a string")
    rec = {
        "id": new_id(),
        "dining_hall_id": dining_hall_id,
        "vendor_name": vendor_name,
        "board_rate_per_cover_cents": board_rate,
        "retail_commission_bps": retail_bps,
        "catering_commission_bps": catering_bps,
        "minimum_monthly_guarantee_cents": guarantee,
        "effective_start_date": start,
        "effective_end_date": end,
        "status": "NEGOTIATION",
        "_seq": next_seq(),
    }
    stamp(rec)
    DB["vendor_contracts"][rec["id"]] = rec
    return ok(ser(rec), status=201)


@bp.get("/vendor-contracts")
def list_contracts():
    return list_endpoint(
        "vendor_contracts", [("dining_hall_id", "dining_hall_id"), ("status", "status")]
    )


@bp.get("/vendor-contracts/<cid>")
def get_one_contract(cid):
    auth(ALL_ROLES)
    return ok(ser(get_contract(cid)))


@bp.post("/vendor-contracts/<cid>/activate")
def activate_contract(cid):
    auth(["ContractManager"])
    contract = get_contract(cid)
    if contract["status"] != "NEGOTIATION":
        raise ApiError("ERR_INVALID_STATE", 409, "Contract is not in NEGOTIATION")
    for other in DB["vendor_contracts"].values():
        if (
            other["id"] != contract["id"]
            and other["dining_hall_id"] == contract["dining_hall_id"]
            and other["status"] == "ACTIVE"
        ):
            raise ApiError(
                "ERR_DUPLICATE_ACTIVE_CONTRACT",
                409,
                "The hall already has an ACTIVE contract",
            )
    contract["status"] = "ACTIVE"
    touch(contract)
    return ok(ser(contract))


@bp.post("/vendor-contracts/<cid>/terminate")
def terminate_contract(cid):
    auth(["ContractManager"])
    contract = get_contract(cid)
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Contract is not ACTIVE")
    contract["status"] = "TERMINATED"
    touch(contract)
    return ok(ser(contract))
