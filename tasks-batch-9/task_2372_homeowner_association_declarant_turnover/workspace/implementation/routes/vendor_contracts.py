"""Vendor contracts: registration, reads and the assignment/cancellation fork."""
from datetime import timedelta

from flask import Blueprint

import auth
import calc
import cascades
import clock
import constants
import response
import util
import validation as v
from db import db, new_record, ordered, serialize, serialize_list, touch
from errors import ApiError
from routes import common

bp = Blueprint("vendor_contracts", __name__)


@bp.get("/hoa/vendor-contracts/<contract_id>")
def read_contract(contract_id):
    auth.require_roles(*constants.ALL_ROLES)
    contract = common.vendor_contract_or_404(contract_id, scoped=True)
    return response.object_response(serialize(contract))


@bp.get("/hoa/vendor-contracts")
def list_contracts():
    auth.require_roles(*constants.ALL_ROLES)
    records = ordered(list(db.vendor_contracts.values()))
    for field in ("association_id", "component_id", "status"):
        value = v.query_filter(field)
        if value is not None:
            records = [r for r in records if r[field] == value]
    affiliated = v.query_bool("developer_affiliated")
    if affiliated is not None:
        records = [r for r in records if r["developer_affiliated"] is affiliated]
    window, pagination = response.paginate(records)
    return response.array_response(serialize_list(window), pagination)


@bp.post("/hoa/vendor-contracts")
def create_contract():
    auth.require_roles(constants.ROLE_DECLARANT)
    body = v.body()

    association = common.body_association_or_404(v.get_fk(body, "association_id"))
    if association is None:
        raise ApiError("ERR_INVALID_REQUEST", "association_id is required.")
    component = common.body_component_or_404(
        v.get_fk(body, "component_id"), association["id"]
    )
    if component is None:
        raise ApiError("ERR_INVALID_REQUEST", "component_id is required.")

    vendor_name = v.get_str(body, "vendor_name", min_len=1, max_len=80)
    developer_affiliated = v.get_bool(body, "developer_affiliated")
    annual_cost = v.get_int(body, "annual_cost_cents", minimum=0)
    window_start, start_dt = v.get_datetime(body, "service_window_start")
    window_end, end_dt = v.get_datetime(body, "service_window_end")
    if end_dt <= start_dt:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "service_window_end must be strictly after service_window_start.",
        )

    cascades.require_not_settled_locked(association["id"])

    # half-open overlap on the same component, existing end inflated by the blackout
    buffer_days = timedelta(days=constants.TRANSITION_BLACKOUT_DAYS)
    for existing in calc.contracts_of(association["id"]):
        if existing["component_id"] != component["id"]:
            continue
        if existing["status"] not in ("ACTIVE", "CANCELLABLE"):
            continue
        other_start = util.parse_dt(existing["service_window_start"])
        other_end = util.parse_dt(existing["service_window_end"]) + buffer_days
        if start_dt < other_end and other_start < end_dt:
            raise ApiError("ERR_SERVICE_WINDOW_CONFLICT")

    contract = new_record({
        "association_id": association["id"],
        "component_id": component["id"],
        "vendor_name": vendor_name,
        "developer_affiliated": developer_affiliated,
        "annual_cost_cents": annual_cost,
        "service_window_start": window_start,
        "service_window_end": window_end,
        "assignment_status": "NOT_REQUESTED",
        "status": "ACTIVE",
        "cancellation_window_end": None,
    })
    db.vendor_contracts[contract["id"]] = contract
    return response.object_response(serialize(contract), 201)


@bp.post("/hoa/vendor-contracts/<contract_id>/actions")
def contract_action(contract_id):
    auth.require_roles(constants.ROLE_DECLARANT, constants.ROLE_TRANSITION_COMMITTEE)
    body = v.body()
    auth.require_discriminator_role(body.get("action"), constants.VENDOR_ACTION_ROLES)

    contract = common.vendor_contract_or_404(contract_id, scoped=True)
    action = v.get_enum(body, "action", constants.VENDOR_ACTIONS)

    cascades.require_not_settled_locked(contract["association_id"])

    association = db.associations[contract["association_id"]]

    if action == "REQUEST_ASSIGNMENT":
        if contract["assignment_status"] != "NOT_REQUESTED":
            raise ApiError("ERR_CONTRACT_STATE_INVALID")
        if contract["status"] not in ("ACTIVE", "CANCELLABLE"):
            raise ApiError("ERR_CONTRACT_STATE_INVALID")
        contract["assignment_status"] = "ASSIGNMENT_REQUESTED"
        touch(contract)

    elif action == "CONSENT":
        if contract["assignment_status"] != "ASSIGNMENT_REQUESTED":
            raise ApiError("ERR_CONTRACT_STATE_INVALID")
        contract["assignment_status"] = "CONSENTED"
        touch(contract)
        case = calc.case_for_association(association["id"])
        if case is not None:
            for item in calc.records_items_of(case["id"]):
                if item["category"] != "VENDOR_CONTRACTS" or item["status"] != "DELIVERED":
                    continue
                item["status"] = "ACCEPTED"
                touch(item)
            cascades.recompute_records_completeness(case)

    elif action == "REFUSE_CONSENT":
        if contract["assignment_status"] != "ASSIGNMENT_REQUESTED":
            raise ApiError("ERR_CONTRACT_STATE_INVALID")
        contract["assignment_status"] = "CONSENT_REFUSED"
        contract["status"] = "TERMINATED_FOR_REFUSAL"
        touch(contract)
        cascades.mark_forecast_stale(association)

    else:  # CANCEL
        if contract["status"] != "CANCELLABLE":
            raise ApiError("ERR_CONTRACT_STATE_INVALID")
        deadline = util.parse_dt(contract["cancellation_window_end"])
        if deadline is None or clock.now() > deadline:
            raise ApiError("ERR_CANCELLATION_WINDOW_CLOSED")
        contract["status"] = "CANCELLED"
        touch(contract)
        cascades.mark_forecast_stale(association)

    return response.object_response(serialize(contract))
