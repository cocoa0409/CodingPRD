"""Adjustment endpoints (PRD 3.2) with segregation of duties."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_INVALID_ADJUSTMENT_STATE,
    ERR_INVALID_ENTRY_STATE,
    ERR_ADJUSTMENT_NOT_IN_CASE,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, query_arg
from services.core import new_record, public, recompute_entry_adjusted, touch
from validate import (
    get_body,
    no_unknown_fields,
    req_int,
    req_str,
    require_fk,
    require_path_resource,
)

bp = Blueprint("adjustments", __name__)


@bp.post("/adjustments")
def create_adjustment():
    body = get_body()
    no_unknown_fields(body, {"rate_case_id", "test_year_entry_id", "amount_cents", "reason"})
    rate_case_id = req_str(body, "rate_case_id")
    entry_id = req_str(body, "test_year_entry_id")
    amount = req_int(body, "amount_cents")
    if amount == 0:
        raise_error(ERR_INVALID_REQUEST, "amount_cents must be != 0")
    reason = req_str(body, "reason")
    caller = authorized(["UtilityFiler"])
    case = require_fk("rate_cases", rate_case_id, "rate_case_id")
    entry = require_fk("test_year_entries", entry_id, "test_year_entry_id")
    # state (p6) before referential (p9)
    if entry["status"] not in ("DRAFT", "SUBMITTED"):
        raise_error(ERR_INVALID_ENTRY_STATE,
                    "adjustments may target entries in DRAFT or SUBMITTED only")
    if entry["rate_case_id"] != case["id"]:
        raise_error(ERR_ADJUSTMENT_NOT_IN_CASE, "test_year_entry_id belongs to a different case")
    rec = new_record("adjustments", {
        "rate_case_id": rate_case_id,
        "test_year_entry_id": entry_id,
        "amount_cents": amount,
        "reason": reason,
        "proposed_by_user_id": caller.user_id,
        "verified_by_user_id": None,
        "status": "PROPOSED",
    })
    recompute_entry_adjusted(entry)
    return success_object(public(rec), status=201)


@bp.get("/adjustments")
def list_adjustments():
    filters = {
        "rate_case_id": query_arg("rate_case_id"),
        "test_year_entry_id": query_arg("test_year_entry_id"),
        "status": query_arg("status"),
    }
    return list_response("adjustments", filters)


@bp.get("/adjustments/<adjustment_id>")
def get_adjustment(adjustment_id):
    return get_one("adjustments", adjustment_id)


@bp.post("/adjustments/<adjustment_id>/verify")
def verify_adjustment(adjustment_id):
    body = get_body()
    no_unknown_fields(body, set())
    caller = authorized(["UtilityFiler"])
    adj = require_path_resource("adjustments", adjustment_id)
    # Segregation of duties (p4) before state (p6)
    if caller.user_id == adj["proposed_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES, "verifier must differ from the proposer")
    if adj["status"] not in ("PROPOSED", "DISPUTED"):
        raise_error(ERR_INVALID_ADJUSTMENT_STATE, "verify requires PROPOSED or DISPUTED")
    entry = db["test_year_entries"].get(adj["test_year_entry_id"])
    if entry is not None and entry["status"] == "LOCKED":
        raise_error(ERR_INVALID_ENTRY_STATE, "owning entry is LOCKED")
    adj["verified_by_user_id"] = caller.user_id
    adj["status"] = "VERIFIED"
    touch(adj)
    if entry is not None:
        recompute_entry_adjusted(entry)
    return success_object(public(adj))


@bp.post("/adjustments/<adjustment_id>/withdraw")
def withdraw_adjustment(adjustment_id):
    body = get_body()
    no_unknown_fields(body, set())
    caller = authorized(["UtilityFiler"])
    adj = require_path_resource("adjustments", adjustment_id)
    # Ownership (p3) before state (p6)
    if caller.user_id != adj["proposed_by_user_id"]:
        raise_error(ERR_FORBIDDEN_OWNERSHIP, "only the proposer may withdraw the adjustment")
    if adj["status"] not in ("PROPOSED", "DISPUTED"):
        raise_error(ERR_INVALID_ADJUSTMENT_STATE, "withdraw requires PROPOSED or DISPUTED")
    adj["status"] = "WITHDRAWN"
    touch(adj)
    entry = db["test_year_entries"].get(adj["test_year_entry_id"])
    if entry is not None:
        recompute_entry_adjusted(entry)
    return success_object(public(adj))


@bp.post("/adjustments/<adjustment_id>/dispute")
def dispute_adjustment(adjustment_id):
    body = get_body()
    no_unknown_fields(body, set())
    authorized(["CommissionStaff", "IntervenorRep"])
    adj = require_path_resource("adjustments", adjustment_id)
    if adj["status"] != "VERIFIED":
        raise_error(ERR_INVALID_ADJUSTMENT_STATE, "dispute requires VERIFIED")
    adj["status"] = "DISPUTED"
    touch(adj)
    entry = db["test_year_entries"].get(adj["test_year_entry_id"])
    if entry is not None:
        recompute_entry_adjusted(entry)
    return success_object(public(adj))


@bp.post("/adjustments/<adjustment_id>/reject")
def reject_adjustment(adjustment_id):
    body = get_body()
    no_unknown_fields(body, set())
    authorized(["CommissionStaff"])
    adj = require_path_resource("adjustments", adjustment_id)
    if adj["status"] not in ("VERIFIED", "DISPUTED"):
        raise_error(ERR_INVALID_ADJUSTMENT_STATE, "reject requires VERIFIED or DISPUTED")
    adj["status"] = "REJECTED"
    touch(adj)
    entry = db["test_year_entries"].get(adj["test_year_entry_id"])
    if entry is not None:
        recompute_entry_adjusted(entry)
    return success_object(public(adj))
