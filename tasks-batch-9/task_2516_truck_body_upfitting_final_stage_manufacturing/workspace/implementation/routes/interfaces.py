"""Electrical interfaces and the chassis warranty posture (PRD section 3.5)."""

from flask import Blueprint

import db
import middleware
import response
import validation as v
from errors import ApiError
from services import calc, lookup

interfaces_bp = Blueprint("interfaces", __name__, url_prefix="/upfit")

PROPOSAL_ORDER_STATES = (
    "DRAFT",
    "ENGINEERING_REVIEW",
    "REWORK",
    "RELEASED",
    "SCHEDULED",
    "IN_BUILD",
)


def interface_state_error(iface, expected):
    return ApiError(
        "ERR_INTERFACE_INVALID_STATE",
        "The interface is %s; this operation requires %s." % (iface.get("status"), expected),
    )


@interfaces_bp.route("/electrical-interfaces", methods=["POST"])
def create_interface():
    caller = middleware.require(middleware.ROLE_UPFIT_ENGINEER)
    payload = v.body()
    upfit_order_id = v.req_str(payload, "upfit_order_id")
    interface_method = v.req_enum(payload, "interface_method", v.INTERFACE_METHOD)
    circuit_amp_draw = v.req_int(payload, "circuit_amp_draw", minimum=0)
    signal_source = v.req_enum(payload, "signal_source", v.SIGNAL_SOURCE)
    waiver = v.opt_bool(payload, "customer_warranty_waiver_ack", default=False)

    order = lookup.upfit_order(upfit_order_id)
    if order["build_status"] not in PROPOSAL_ORDER_STATES:
        raise ApiError(
            "ERR_ORDER_INVALID_STATE",
            "Interfaces cannot be proposed on an order at %s." % order["build_status"],
        )

    model = lookup.governing_chassis_model(order)
    warranty_impact = calc.electrical_warranty_impact(
        interface_method, (model or {}).get("electrical_bus")
    )

    # 72. auxiliary electrical ceiling, candidate counted in
    projected_amps = calc.committed_aux_amp_draw(order, extra_amps=circuit_amp_draw)
    if model is not None and projected_amps > int(model.get("max_aux_amp_draw") or 0):
        raise ApiError(
            "ERR_AUX_ELECTRICAL_LOAD_EXCEEDED",
            "Auxiliary load %s A would exceed the model's ceiling of %s A."
            % (projected_amps, model.get("max_aux_amp_draw")),
        )

    # 77. a warranty-voiding tap needs a signed waiver
    if warranty_impact == "VOIDS" and not waiver:
        raise ApiError(
            "ERR_CHASSIS_WARRANTY_VOIDING_INTERFACE",
            "This interface method voids the chassis warranty and requires "
            "customer_warranty_waiver_ack.",
        )

    row = db.insert(
        db.electrical_interfaces,
        {
            "upfit_order_id": order["id"],
            "interface_method": interface_method,
            "circuit_amp_draw": circuit_amp_draw,
            "signal_source": signal_source,
            "customer_warranty_waiver_ack": waiver,
            "warranty_impact": warranty_impact,
            "status": "PROPOSED",
            "proposed_by_user_id": caller.user_id,
            "approved_by_user_id": None,
        },
    )
    return response.object_response(db.serialize(row), 201)


@interfaces_bp.route("/electrical-interfaces/<electrical_interface_id>/approve", methods=["POST"])
def approve_interface(electrical_interface_id):
    caller = middleware.require(middleware.ROLE_COMPLIANCE_OFFICER)
    iface = lookup.electrical_interface(electrical_interface_id)

    # 4. segregation of duties, above every state and business check
    middleware.enforce_segregation(
        caller,
        iface.get("proposed_by_user_id"),
        "The approver may not be the engineer who proposed the interface.",
    )

    if iface["status"] != "PROPOSED":
        raise interface_state_error(iface, "PROPOSED")
    order = db.upfit_orders.get(iface["upfit_order_id"])
    if (order or {}).get("build_status") not in PROPOSAL_ORDER_STATES:
        raise ApiError(
            "ERR_ORDER_INVALID_STATE",
            "Interfaces cannot be approved on an order at %s."
            % (order or {}).get("build_status"),
        )

    model = lookup.governing_chassis_model(order)
    # the row is still PROPOSED, so count it in explicitly
    projected_amps = calc.committed_aux_amp_draw(
        order, extra_amps=iface.get("circuit_amp_draw") or 0
    )
    if model is not None and projected_amps > int(model.get("max_aux_amp_draw") or 0):
        raise ApiError(
            "ERR_AUX_ELECTRICAL_LOAD_EXCEEDED",
            "Auxiliary load %s A would exceed the model's ceiling of %s A."
            % (projected_amps, model.get("max_aux_amp_draw")),
        )

    iface["status"] = "APPROVED"
    iface["approved_by_user_id"] = caller.user_id
    db.touch(iface)

    # one signal source can only be read one way
    for other in lookup.interfaces_of(order["id"]):
        if other["id"] == iface["id"]:
            continue
        if other["status"] != "APPROVED":
            continue
        if other["signal_source"] != iface["signal_source"]:
            continue
        other["status"] = "SUPERSEDED"
        db.touch(other)

    calc.refresh_committed_aux(order)
    calc.derive_chassis_warranty_status(order)
    db.touch(order)
    return response.object_response(db.serialize(iface), 200)


@interfaces_bp.route("/electrical-interfaces/<electrical_interface_id>/reject", methods=["POST"])
def reject_interface(electrical_interface_id):
    middleware.require(middleware.ROLE_COMPLIANCE_OFFICER)
    payload = v.body()
    v.req_str(payload, "reason")
    iface = lookup.electrical_interface(electrical_interface_id)
    if iface["status"] != "PROPOSED":
        raise interface_state_error(iface, "PROPOSED")
    iface["status"] = "REJECTED"
    db.touch(iface)
    return response.object_response(db.serialize(iface), 200)


@interfaces_bp.route("/electrical-interfaces/<electrical_interface_id>", methods=["GET"])
def get_interface(electrical_interface_id):
    caller = middleware.require(*middleware.ALL_ROLES)
    iface = lookup.electrical_interface(electrical_interface_id)
    middleware.enforce_order_scope(caller, db.upfit_orders.get(iface["upfit_order_id"]))
    return response.object_response(db.serialize(iface), 200)


@interfaces_bp.route("/electrical-interfaces", methods=["GET"])
def list_interfaces():
    caller = middleware.require(*middleware.ALL_ROLES)
    upfit_order_id = v.filter_str("upfit_order_id")
    status = v.filter_enum("status", v.INTERFACE_STATUS)
    warranty_impact = v.filter_enum("warranty_impact", v.WARRANTY_IMPACT)
    interface_method = v.filter_enum("interface_method", v.INTERFACE_METHOD)

    rows = middleware.scope_filter_by_order(caller, list(db.electrical_interfaces.values()))
    if upfit_order_id is not None:
        rows = [r for r in rows if r["upfit_order_id"] == upfit_order_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if warranty_impact is not None:
        rows = [r for r in rows if r["warranty_impact"] == warranty_impact]
    if interface_method is not None:
        rows = [r for r in rows if r["interface_method"] == interface_method]
    return response.paginate(rows)
