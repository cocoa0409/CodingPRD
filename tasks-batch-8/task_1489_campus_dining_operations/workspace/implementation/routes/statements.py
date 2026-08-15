"""CommissionStatement endpoints (C3 settlement)."""
from flask import Blueprint

from db import DB, logical_now_str, new_id, next_seq
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok
from services import c3_settlement, get_contract, get_statement, ser, stamp, touch
from util import as_period_month, body, required
from routes.common import list_endpoint

bp = Blueprint("statements", __name__)


@bp.post("/vendor-contracts/<cid>/commission-statements")
def create_statement(cid):
    auth(["DiningAdmin"])
    contract = get_contract(cid)
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", 409, "Contract is not ACTIVE")
    data = body()
    period_month = required(data, "period_month")
    if not isinstance(period_month, str):
        raise ApiError("ERR_VALIDATION", 400, "period_month must be a string")
    # Tier 7: unique (vendor_contract_id, period_month).
    for s in DB["commission_statements"].values():
        if s["vendor_contract_id"] == cid and s["period_month"] == period_month:
            raise ApiError(
                "ERR_DUPLICATE_STATEMENT",
                409,
                "A statement already exists for this contract and month",
            )
    period_month = as_period_month(period_month)
    figures = c3_settlement(contract, period_month, "PROVISIONAL")
    rec = {
        "id": new_id(),
        "vendor_contract_id": cid,
        "period_month": period_month,
        "status": "PROVISIONAL",
        "board_revenue_cents": figures["board_revenue_cents"],
        "retail_commission_cents": figures["retail_commission_cents"],
        "catering_commission_cents": figures["catering_commission_cents"],
        "guarantee_top_up_cents": figures["guarantee_top_up_cents"],
        "total_due_to_university_cents": figures["total_due_to_university_cents"],
        "provisional_total_due_cents": figures["total_due_to_university_cents"],
        "finalized_at": None,
        "_seq": next_seq(),
    }
    stamp(rec)
    DB["commission_statements"][rec["id"]] = rec
    return ok(ser(rec), status=201)


@bp.get("/commission-statements")
def list_statements():
    return list_endpoint(
        "commission_statements",
        [
            ("vendor_contract_id", "vendor_contract_id"),
            ("period_month", "period_month"),
            ("status", "status"),
        ],
    )


@bp.get("/commission-statements/<sid>")
def get_one_statement(sid):
    auth(ALL_ROLES)
    return ok(ser(get_statement(sid)))


@bp.post("/commission-statements/<sid>/finalize")
def finalize_statement(sid):
    auth(["ContractManager"])
    statement = get_statement(sid)
    if statement["status"] != "PROVISIONAL":
        raise ApiError("ERR_INVALID_STATE", 409, "Statement is not PROVISIONAL")
    contract = get_contract(statement["vendor_contract_id"])
    if contract["status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE", 409, "Contract is not ACTIVE")
    figures = c3_settlement(contract, statement["period_month"], "FINAL")
    statement["board_revenue_cents"] = figures["board_revenue_cents"]
    statement["retail_commission_cents"] = figures["retail_commission_cents"]
    statement["catering_commission_cents"] = figures["catering_commission_cents"]
    statement["guarantee_top_up_cents"] = figures["guarantee_top_up_cents"]
    statement["total_due_to_university_cents"] = figures["total_due_to_university_cents"]
    statement["finalized_at"] = logical_now_str()
    statement["status"] = "FINALIZED"
    touch(statement)
    return ok(ser(statement))


@bp.post("/commission-statements/<sid>/dispute")
def dispute_statement(sid):
    auth(["DiningAdmin"])
    statement = get_statement(sid)
    if statement["status"] != "FINALIZED":
        raise ApiError("ERR_INVALID_STATE", 409, "Statement is not FINALIZED")
    statement["status"] = "DISPUTED"
    touch(statement)
    return ok(ser(statement))


@bp.post("/commission-statements/<sid>/recompute")
def recompute_statement(sid):
    auth(["DiningAdmin"])
    statement = get_statement(sid)
    if statement["status"] != "DISPUTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Statement is not DISPUTED")
    contract = get_contract(statement["vendor_contract_id"])
    figures = c3_settlement(contract, statement["period_month"], "PROVISIONAL")
    statement["board_revenue_cents"] = figures["board_revenue_cents"]
    statement["retail_commission_cents"] = figures["retail_commission_cents"]
    statement["catering_commission_cents"] = figures["catering_commission_cents"]
    statement["guarantee_top_up_cents"] = figures["guarantee_top_up_cents"]
    statement["total_due_to_university_cents"] = figures["total_due_to_university_cents"]
    statement["finalized_at"] = None
    statement["status"] = "PROVISIONAL"
    touch(statement)
    return ok(ser(statement))
