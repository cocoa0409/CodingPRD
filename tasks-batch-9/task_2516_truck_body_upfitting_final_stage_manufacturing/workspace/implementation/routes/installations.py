"""Equipment installations and the hydraulic flow waterfall (PRD section 3.4)."""

from flask import Blueprint

import db
import middleware
import response
import validation as v
from errors import ApiError
from services import calc, cascade, lookup

installations_bp = Blueprint("installations", __name__, url_prefix="/upfit")

PLANNABLE_ORDER_STATES = (
    "DRAFT",
    "ENGINEERING_REVIEW",
    "REWORK",
    "RELEASED",
    "SCHEDULED",
    "IN_BUILD",
)


def installation_state_error(inst, expected):
    return ApiError(
        "ERR_INSTALLATION_INVALID_STATE",
        "The installation is %s; this operation requires %s." % (inst.get("status"), expected),
    )


@installations_bp.route("/equipment-installations", methods=["POST"])
def create_installation():
    middleware.require(middleware.ROLE_INSTALL_TECHNICIAN, middleware.ROLE_UPFIT_ENGINEER)
    payload = v.body()
    upfit_order_id = v.req_str(payload, "upfit_order_id")
    equipment_spec_id = v.req_str(payload, "equipment_spec_id")
    mount_cg = v.req_int(payload, "mount_cg_from_front_axle_in", minimum=0)
    circuit = v.opt_enum(payload, "hydraulic_circuit", v.HYDRAULIC_CIRCUIT, default="NONE")

    order = lookup.upfit_order(upfit_order_id)
    spec = lookup.equipment_spec(equipment_spec_id)

    # 40. the planning window
    if order["build_status"] not in PLANNABLE_ORDER_STATES:
        raise ApiError(
            "ERR_ORDER_INVALID_STATE",
            "Equipment cannot be planned on an order at %s." % order["build_status"],
        )

    model = lookup.governing_chassis_model(order)

    # 72. auxiliary electrical ceiling, candidate counted in
    projected_amps = calc.committed_aux_amp_draw(order, extra_amps=spec.get("aux_amp_draw") or 0)
    if model is not None and projected_amps > int(model.get("max_aux_amp_draw") or 0):
        raise ApiError(
            "ERR_AUX_ELECTRICAL_LOAD_EXCEEDED",
            "Auxiliary load %s A would exceed the model's ceiling of %s A."
            % (projected_amps, model.get("max_aux_amp_draw")),
        )

    # 73. hydraulic flow ceiling, deferred entirely while no unit is bound
    if order.get("chassis_id") and spec.get("requires_pto"):
        projected_flow = calc.committed_pto_flow(order) + int(spec.get("required_flow_gpm") or 0)
        pool = int((model or {}).get("pto_max_flow_gpm") or 0)
        if projected_flow > pool:
            raise ApiError(
                "ERR_PTO_FLOW_CAPACITY_EXCEEDED",
                "Committed flow %s GPM would exceed the bound model's %s GPM."
                % (projected_flow, pool),
            )

    # 74. provisioning is a pure book property and is never deferred
    if spec.get("requires_pto") and (model or {}).get("pto_provision") == "NONE":
        raise ApiError(
            "ERR_PTO_NOT_PROVISIONED",
            "The governing chassis model has no power-take-off provision.",
        )

    # 75. circuit coherence, both directions
    if spec.get("requires_pto"):
        if circuit not in ("PRIMARY", "SECONDARY"):
            raise ApiError(
                "ERR_HYDRAULIC_CIRCUIT_REQUIRED",
                "A PTO-driven item must be plumbed onto PRIMARY or SECONDARY.",
            )
    else:
        if circuit != "NONE":
            raise ApiError(
                "ERR_HYDRAULIC_CIRCUIT_REQUIRED",
                "A non-hydraulic item must use hydraulic_circuit NONE.",
            )

    # 78. network gateway prerequisite
    if spec.get("requires_can_gateway"):
        gateway_ok = any(
            iface["status"] == "APPROVED"
            and iface["interface_method"] in ("CAN_GATEWAY", "BODY_BUILDER_MODULE")
            for iface in lookup.interfaces_of(order["id"])
        )
        if not gateway_ok:
            raise ApiError(
                "ERR_CAN_GATEWAY_REQUIRED",
                "This item must be read through an APPROVED CAN gateway or body "
                "builder module interface.",
            )

    # 81. pool standardization
    if order["order_type"] == "POOL_STOCK":
        config = db.build_configurations.get(order["build_configuration_id"]) or {}
        if equipment_spec_id not in list(config.get("standard_equipment_spec_ids") or []):
            raise ApiError(
                "ERR_NON_STANDARD_POOL_EQUIPMENT",
                "A POOL_STOCK order may only carry the configuration's standard equipment.",
            )

    # 84. mount-zone exclusivity over the non-REMOVED set
    for inst in lookup.installations_of(order["id"]):
        if inst["status"] == "REMOVED":
            continue
        other = db.equipment_specs.get(inst["equipment_spec_id"]) or {}
        if other.get("mount_zone") == spec.get("mount_zone"):
            raise ApiError(
                "ERR_MOUNT_ZONE_CONFLICT",
                "Mount zone %s on this order is already occupied." % spec.get("mount_zone"),
            )

    row = db.insert(
        db.equipment_installations,
        {
            "upfit_order_id": order["id"],
            "equipment_spec_id": equipment_spec_id,
            "mount_cg_from_front_axle_in": mount_cg,
            "hydraulic_circuit": circuit,
            "actual_weight_lb": None,
            "allocated_flow_gpm": 0,
            "hydraulic_status": "NOT_APPLICABLE",
            "status": "PLANNED",
        },
    )
    calc.run_pto_waterfall(order)
    calc.refresh_committed_aux(order)
    db.touch(order)
    return response.object_response(db.serialize(row), 201)


@installations_bp.route("/equipment-installations/<equipment_installation_id>/install", methods=["POST"])
def install_installation(equipment_installation_id):
    middleware.require(middleware.ROLE_INSTALL_TECHNICIAN)
    payload = v.body()
    actual_weight = v.req_int(payload, "actual_weight_lb", minimum=1)
    inst = lookup.equipment_installation(equipment_installation_id)
    order = db.upfit_orders.get(inst["upfit_order_id"])

    if inst["status"] != "PLANNED":
        raise installation_state_error(inst, "PLANNED")
    if (order or {}).get("build_status") != "IN_BUILD":
        raise ApiError(
            "ERR_ORDER_INVALID_STATE",
            "The parent order must be at IN_BUILD to record a physical install.",
        )
    if inst.get("hydraulic_status") == "DEFICIT":
        raise ApiError(
            "ERR_HYDRAULIC_DEFICIT_UNRESOLVED",
            "This item is still short of hydraulic flow and cannot be installed.",
        )

    inst["actual_weight_lb"] = actual_weight
    inst["status"] = "INSTALLED"
    db.touch(inst)
    # the installed component set changed: the measured certification is stale
    cascade.component_set_changed(order)
    db.touch(order)
    return response.object_response(db.serialize(inst), 200)


@installations_bp.route(
    "/equipment-installations/<equipment_installation_id>/commission", methods=["POST"]
)
def commission_installation(equipment_installation_id):
    middleware.require(middleware.ROLE_INSTALL_TECHNICIAN)
    inst = lookup.equipment_installation(equipment_installation_id)
    if inst["status"] != "INSTALLED":
        raise installation_state_error(inst, "INSTALLED")
    if inst.get("hydraulic_status") not in ("NOT_APPLICABLE", "OK"):
        raise ApiError(
            "ERR_HYDRAULIC_DEFICIT_UNRESOLVED",
            "A DEFICIT item cannot be commissioned.",
        )
    inst["status"] = "COMMISSIONED"
    db.touch(inst)
    return response.object_response(db.serialize(inst), 200)


@installations_bp.route(
    "/equipment-installations/<equipment_installation_id>/decommission", methods=["POST"]
)
def decommission_installation(equipment_installation_id):
    middleware.require(middleware.ROLE_INSTALL_TECHNICIAN)
    payload = v.body()
    v.req_str(payload, "reason")
    inst = lookup.equipment_installation(equipment_installation_id)
    order = db.upfit_orders.get(inst["upfit_order_id"])

    if inst["status"] != "COMMISSIONED":
        raise installation_state_error(inst, "COMMISSIONED")
    if (order or {}).get("build_status") not in ("IN_BUILD", "BUILD_COMPLETE"):
        raise ApiError(
            "ERR_ORDER_INVALID_STATE",
            "Decommissioning requires the order to be at IN_BUILD or BUILD_COMPLETE.",
        )
    inst["status"] = "INSTALLED"
    db.touch(inst)
    return response.object_response(db.serialize(inst), 200)


@installations_bp.route("/equipment-installations/<equipment_installation_id>/remove", methods=["POST"])
def remove_installation(equipment_installation_id):
    middleware.require(middleware.ROLE_INSTALL_TECHNICIAN)
    payload = v.body()
    v.req_str(payload, "reason")
    inst = lookup.equipment_installation(equipment_installation_id)
    order = db.upfit_orders.get(inst["upfit_order_id"])

    if inst["status"] not in ("PLANNED", "INSTALLED", "COMMISSIONED"):
        raise installation_state_error(inst, "PLANNED, INSTALLED or COMMISSIONED")

    was_physical = inst["status"] in calc.PHYSICAL_INSTALL_STATUSES
    inst["status"] = "REMOVED"
    inst["allocated_flow_gpm"] = 0
    inst["hydraulic_status"] = "NOT_APPLICABLE"
    db.touch(inst)

    # hop one runs on every edge
    calc.run_pto_waterfall(order)
    calc.refresh_committed_aux(order)
    # hops two through four only when something was physically on the truck
    if was_physical:
        cascade.component_set_changed(order)
    db.touch(order)
    return response.object_response(db.serialize(inst), 200)


@installations_bp.route("/equipment-installations/<equipment_installation_id>", methods=["GET"])
def get_installation(equipment_installation_id):
    caller = middleware.require(*middleware.ALL_ROLES)
    inst = lookup.equipment_installation(equipment_installation_id)
    middleware.enforce_order_scope(caller, db.upfit_orders.get(inst["upfit_order_id"]))
    return response.object_response(db.serialize(inst), 200)


@installations_bp.route("/equipment-installations", methods=["GET"])
def list_installations():
    caller = middleware.require(*middleware.ALL_ROLES)
    upfit_order_id = v.filter_str("upfit_order_id")
    equipment_spec_id = v.filter_str("equipment_spec_id")
    status = v.filter_enum("status", v.INSTALLATION_STATUS)
    hydraulic_status = v.filter_enum("hydraulic_status", v.HYDRAULIC_STATUS)

    rows = middleware.scope_filter_by_order(caller, list(db.equipment_installations.values()))
    if upfit_order_id is not None:
        rows = [r for r in rows if r["upfit_order_id"] == upfit_order_id]
    if equipment_spec_id is not None:
        rows = [r for r in rows if r["equipment_spec_id"] == equipment_spec_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if hydraulic_status is not None:
        rows = [r for r in rows if r["hydraulic_status"] == hydraulic_status]
    return response.paginate(rows)
