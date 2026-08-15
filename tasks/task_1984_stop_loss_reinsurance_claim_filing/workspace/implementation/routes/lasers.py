"""Lasered member term endpoints (PRD §3.3): OCC-guarded create, rescind, reads."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_CROSS_PLAN_REFERENCE,
    ERR_INVALID_DATE_RANGE, ERR_LASER_CONFLICT, ERR_STALE_VERSION,
)
from middleware import authorized
from response import success_object
from routes.helpers import READ_LASER, get_one, list_response
from services.accumulation import recompute_specific_row
from services.core import new_record, public, touch
from util import norm_dt, parse_dt
from validate import (
    get_body, req_str, req_int, req_datetime, require_path_resource, require_ref,
)

bp = Blueprint("lasers", __name__)


def _intervals_overlap(a_from, a_to, b_from, b_to):
    """Half-open [from, to) intersection."""
    return a_from < b_to and b_from < a_to


@bp.post("/stop-loss/lasered-terms")
def create_laser():
    authorized(["PlanAdministrator"])
    body = get_body()
    contract_id = req_str(body, "contract_id")
    member_id = req_str(body, "member_id")
    lasered_ded = req_int(body, "lasered_specific_deductible_cents", minimum=0)
    effective_from = req_datetime(body, "effective_from")
    effective_to = req_datetime(body, "effective_to")
    expected_version = req_int(body, "expected_contract_version")

    contract = require_ref("contracts", contract_id, "contract_id")
    member = require_ref("members", member_id, "member_id")

    # Fixed check order (PRD §3.3): cross-plan -> date range -> laser rules -> OCC.
    if member["plan_id"] != contract["plan_id"]:
        raise_error(ERR_CROSS_PLAN_REFERENCE,
                    "member_id does not belong to the plan the contract insures")
    if not (parse_dt(effective_from) < parse_dt(effective_to)):
        raise_error(ERR_INVALID_DATE_RANGE,
                    "effective_from must be strictly earlier than effective_to")
    if lasered_ded <= contract["specific_deductible_cents"]:
        raise_error(ERR_LASER_CONFLICT,
                    "lasered_specific_deductible_cents must be strictly greater than "
                    "the contract's specific_deductible_cents")
    for other in db["lasers"].values():
        if (other["contract_id"] == contract_id and other["member_id"] == member_id
                and other["status"] == "ACTIVE"
                and _intervals_overlap(parse_dt(effective_from), parse_dt(effective_to),
                                       parse_dt(other["effective_from"]),
                                       parse_dt(other["effective_to"]))):
            raise_error(ERR_LASER_CONFLICT,
                        "overlapping ACTIVE laser intervals for the same member")
    if expected_version != contract["version"]:
        raise_error(ERR_STALE_VERSION,
                    "expected_contract_version does not match the contract's current version")

    rec = new_record("lasers", {
        "contract_id": contract_id,
        "member_id": member_id,
        "lasered_specific_deductible_cents": lasered_ded,
        "effective_from": norm_dt(effective_from),
        "effective_to": norm_dt(effective_to),
        "status": "ACTIVE",
    })
    # Ledger side effect: the SPECIFIC row reflects the lasered override at once.
    recompute_specific_row(contract, member_id)
    touch(contract)
    return success_object(public(rec), status=201)


@bp.post("/stop-loss/lasered-terms/<rid>/rescind")
def rescind_laser(rid):
    authorized(["PlanAdministrator"])
    get_body()
    laser = require_path_resource("lasers", rid)
    if laser["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE,
                    f"laser in {laser['status']} cannot be rescinded")
    touch(laser)
    laser["status"] = "RESCINDED"
    # The SPECIFIC row falls back to the contract base deductible (or to any
    # remaining ACTIVE laser covering the member).
    contract = db["contracts"].get(laser["contract_id"])
    if contract is not None:
        recompute_specific_row(contract, laser["member_id"])
    return success_object(public(laser))


@bp.get("/stop-loss/lasered-terms/<rid>")
def get_laser(rid):
    return get_one("lasers", rid, READ_LASER)


@bp.get("/stop-loss/lasered-terms")
def list_lasers():
    return list_response("lasers", READ_LASER, {
        "contract_id": request.args.get("contract_id"),
        "member_id": request.args.get("member_id"),
    })
