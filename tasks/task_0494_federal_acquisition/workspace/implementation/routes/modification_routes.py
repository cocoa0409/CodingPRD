from flask import Blueprint, request

from clock import clock
from db import db, stamp_create, touch
from errors import err
from middleware import auth
from response import object_response, list_response
from services.query import get_or_404, paginate
from services import calc
from validate import (
    get_body, req_enum, opt_int, opt_datetime, pagination_params,
)

bp = Blueprint("modifications", __name__)

MOD_TYPES = {"FUNDING", "OPTION_EXERCISE", "ADMINISTRATIVE"}


@bp.route("/contracts/<contract_id>/modifications", methods=["POST"])
def propose_modification(contract_id):
    auth(["ContractingOfficer"])
    contract = get_or_404(db.contracts, contract_id)
    body = get_body()
    mod_type = req_enum(body, "mod_type", MOD_TYPES)
    delta = opt_int(body, "delta_cents", default=0)
    option_value = opt_int(body, "option_value_cents", default=0)
    option_window = opt_datetime(body, "option_window_close_at")

    mod = {
        "contract_id": contract_id,
        "mod_type": mod_type,
        "delta_cents": delta,
        "option_value_cents": option_value,
        "option_window_close_at": body.get("option_window_close_at"),
        "_option_window_dt": option_window,
        "status": "PROPOSED",
    }
    stamp_create(mod)
    db.modifications[mod["id"]] = mod
    return object_response(mod, status=201)


@bp.route("/contracts/<contract_id>/modifications", methods=["GET"])
def list_modifications(contract_id):
    auth(["Vendor", "ContractingOfficer", "Auditor"])
    get_or_404(db.contracts, contract_id)
    limit, offset = pagination_params()
    items = [m for m in db.modifications.values() if m["contract_id"] == contract_id]
    page, total = paginate(items, limit, offset)
    return list_response(page, limit, offset, total)


@bp.route("/modifications/<mod_id>", methods=["GET"])
def get_modification(mod_id):
    auth(["Vendor", "ContractingOfficer", "Auditor"])
    return object_response(get_or_404(db.modifications, mod_id))


@bp.route("/modifications/<mod_id>/approve", methods=["POST"])
def approve_modification(mod_id):
    auth(["ContractingOfficer"])
    mod = get_or_404(db.modifications, mod_id)
    if mod["status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE", "Only a PROPOSED modification can be approved.")

    contract = db.contracts.get(mod["contract_id"])
    if contract is None:
        raise err("ERR_NOT_FOUND", "Parent contract does not exist.")
    if contract["lifecycle_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Parent contract is not ACTIVE.")
    award = db.awards.get(contract["award_id"])
    if award is None or award["status"] != "AWARDED":
        raise err("ERR_INVALID_STATE", "Parent award is not AWARDED.")

    if mod["mod_type"] == "OPTION_EXERCISE":
        # Option window must not be closed (priority 10, checked before the
        # ceiling/funding-posture rule at priority 17).
        win = mod.get("_option_window_dt")
        if win is None or not (clock.now() <= win):
            raise err("ERR_OPTION_WINDOW_CLOSED", "Option exercise window has closed.")
        # Funding posture must allow option exercise (priority 17).
        if contract["funding_posture"] == "CEILING_REACHED":
            raise err("ERR_CEILING_REACHED_NO_OPTION",
                      "Option exercise blocked: contract has reached its ceiling.")

    mod["status"] = "APPROVED"
    touch(mod)
    contract["obligated_amount_cents"] = calc.compute_obligated_amount(contract)
    # Raising the ceiling unblocks options (PRD §2.10): the funding posture is
    # CEILING_REACHED only while cumulative invoiced == obligated amount.
    if contract["cumulative_invoiced_cents"] < contract["obligated_amount_cents"]:
        contract["funding_posture"] = "WITHIN_CEILING"
    elif contract["cumulative_invoiced_cents"] == contract["obligated_amount_cents"]:
        contract["funding_posture"] = "CEILING_REACHED"
    touch(contract)
    return object_response(mod)


@bp.route("/modifications/<mod_id>/reject", methods=["POST"])
def reject_modification(mod_id):
    auth(["ContractingOfficer"])
    mod = get_or_404(db.modifications, mod_id)
    if mod["status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE", "Only a PROPOSED modification can be rejected.")
    mod["status"] = "REJECTED"
    touch(mod)
    return object_response(mod)
