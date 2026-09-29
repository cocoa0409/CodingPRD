"""Antibiotic prophylaxis: ordering off the formulary and recording administration."""

from flask import Blueprint, g

import constants
import db
import response
import util
import validate
from db import store
from errors import ApiError
from middleware import ALL, authenticate
from services import calc, query, serialize

bp = Blueprint("antibiotics", __name__)


def _order(order_id):
    row = store.get("antibiotic_orders", order_id)
    if row is None:
        raise ApiError("ERR_ANTIBIOTIC_ORDER_NOT_FOUND")
    return row


@bp.route("/antibiotic-orders", methods=["POST"])
@authenticate([constants.ROLE_UROLOGIST])
def order_antibiotic():
    body = validate.get_body()
    case_id = validate.str_field(body, "case_id")
    ordered_by_provider_id = validate.str_field(body, "ordered_by_provider_id")
    requested_agent = validate.enum_field(body, "requested_agent", constants.REQUESTED_AGENTS)

    # Priority 10 — in the order the fields are listed.
    case = store.get("cases", case_id)
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND")
    if store.get("providers", ordered_by_provider_id) is None:
        raise ApiError("ERR_PROVIDER_NOT_FOUND")
    # Priority 14.
    if ordered_by_provider_id != g.user_id:
        raise ApiError("ERR_ACTOR_IDENTITY_MISMATCH")

    ptype = store.get("procedure_types", case["procedure_type_id"])
    patient = store.get("patients", case["patient_id"])
    eligible = calc.eligible_agents(ptype, patient)

    if requested_agent == "AUTO":
        # Priority 46 — an empty pool, including every type that needs no antibiotic.
        if not eligible:
            raise ApiError("ERR_NO_ELIGIBLE_ANTIBIOTIC")
        agent = calc.select_auto_agent(eligible)
    else:
        # Priority 45.
        if requested_agent not in eligible:
            raise ApiError("ERR_ANTIBIOTIC_CONTRAINDICATED")
        agent = requested_agent

    row = db.new_row(
        "antibiotic_orders",
        {
            "case_id": case_id,
            "ordered_by_provider_id": ordered_by_provider_id,
            "requested_agent": requested_agent,
            "agent": agent,
            "dose_mg": calc.dose_for(agent, patient),
            "route": constants.ANTIBIOTIC_CATALOG[agent]["route"],
            "prophylaxis_window_start_at": util.add_minutes(
                case["scheduled_start_at"], -constants.PROPHYLAXIS_WINDOW_MINUTES
            ),
            "administered_at": None,
            "status": "ORDERED",
        },
    )
    return response.created_response(serialize.dump("antibiotic_orders", row))


@bp.route("/antibiotic-orders/<order_id>/administer", methods=["POST"])
@authenticate([constants.ROLE_PROCEDURE_NURSE, constants.ROLE_UROLOGIST])
def administer_antibiotic(order_id):
    body = validate.get_body()
    administered_at = validate.instant_field(body, "administered_at")
    order = _order(order_id)
    case = store.get("cases", order["case_id"])

    # Priority 22 — an already administered or swept order cannot be administered.
    if order["status"] != "ORDERED":
        raise ApiError("ERR_INVALID_CASE_TRANSITION")
    # Priority 47 — a closed interval; both endpoints are accepted.
    window_start = order["prophylaxis_window_start_at"]
    window_end = case["scheduled_start_at"] if case is not None else None
    if window_end is None or administered_at < window_start or administered_at > window_end:
        raise ApiError("ERR_PROPHYLAXIS_WINDOW_MISSED")

    order["status"] = "ADMINISTERED"
    order["administered_at"] = administered_at
    db.touch(order)
    return response.object_response(serialize.dump("antibiotic_orders", order))


@bp.route("/antibiotic-orders/<order_id>", methods=["GET"])
@authenticate(ALL)
def get_order(order_id):
    return response.object_response(serialize.dump("antibiotic_orders", _order(order_id)))


@bp.route("/antibiotic-orders", methods=["GET"])
@authenticate(ALL)
def list_orders():
    return query.collection(
        "antibiotic_orders",
        {
            "case_id": validate.query_str("case_id"),
            "ordered_by_provider_id": validate.query_str("ordered_by_provider_id"),
            "status": validate.query_enum("status", constants.ANTIBIOTIC_STATUSES),
            "agent": validate.query_enum("agent", list(constants.ANTIBIOTIC_CATALOG.keys())),
        },
    )
