"""Upfit orders: the order book, the engineering loop, chassis allocation, the
release gate, body install, delivery and cancellation (PRD sections 3.4 - 3.6)."""

from flask import Blueprint

import db
import middleware
import response
import validation as v
from errors import ApiError
from services import calc, cascade, lookup

orders_bp = Blueprint("orders", __name__, url_prefix="/upfit")

EQUIPMENT_PLANNABLE_STATES = (
    "DRAFT",
    "ENGINEERING_REVIEW",
    "REWORK",
    "RELEASED",
    "SCHEDULED",
    "IN_BUILD",
)
ALLOCATABLE_ORDER_STATES = ("DRAFT", "ENGINEERING_REVIEW", "REWORK", "RELEASED", "CHASSIS_HOLD")
CANCELLABLE_ORDER_STATES = (
    "DRAFT",
    "ENGINEERING_REVIEW",
    "REWORK",
    "RELEASED",
    "SCHEDULED",
    "CHASSIS_HOLD",
)
REBINDABLE_INCUMBENT_STATES = ("DRAFT", "ENGINEERING_REVIEW", "REWORK", "RELEASED")
LOCKED_INCUMBENT_STATES = ("SCHEDULED", "IN_BUILD", "BUILD_COMPLETE", "DELIVERED")


def order_state_error(order, expected):
    return ApiError(
        "ERR_ORDER_INVALID_STATE",
        "The order's state is %s; this operation requires %s." % (order.get("build_status"), expected),
    )


# --------------------------------------------------------------------------
# Create
# --------------------------------------------------------------------------
@orders_bp.route("/upfit-orders", methods=["POST"])
def create_upfit_order():
    middleware.require(middleware.ROLE_PRODUCTION_SCHEDULER)
    payload = v.body()
    order_number = v.req_str(payload, "order_number")
    order_type = v.req_enum(payload, "order_type", v.ORDER_TYPE)
    customer_id = v.opt_str(payload, "customer_id")
    build_configuration_id = v.req_str(payload, "build_configuration_id")
    offset = v.req_int(payload, "body_mount_offset_from_front_axle_in", minimum=0)
    required_payload_lb = v.opt_int(payload, "required_payload_lb", default=0, minimum=0)
    requested_in_service_date = v.opt_date(payload, "requested_in_service_date", default=None)
    cap_cents = v.opt_int(
        payload, "warranty_liability_cap_cents", default=5000000, minimum=0
    )

    if order_type == "CUSTOMER_SPECIFIC" and customer_id is None:
        raise v.invalid("customer_id is required when order_type is CUSTOMER_SPECIFIC.")
    if order_type == "POOL_STOCK" and customer_id is not None:
        raise v.invalid("customer_id must be null when order_type is POOL_STOCK.")

    if customer_id is not None:
        lookup.customer(customer_id)
    config = lookup.build_configuration(build_configuration_id)

    for existing in db.upfit_orders.values():
        if existing["order_number"] == order_number:
            raise ApiError(
                "ERR_DUPLICATE_ORDER_NUMBER",
                "Order number '%s' is already in use." % order_number,
            )

    if config["status"] != "PUBLISHED":
        raise ApiError(
            "ERR_CONFIG_NOT_PUBLISHED",
            "Build configuration '%s' is %s, not PUBLISHED."
            % (build_configuration_id, config["status"]),
        )

    body = db.body_specs.get(config["body_spec_id"])
    row = db.insert(
        db.upfit_orders,
        {
            "order_number": order_number,
            "order_type": order_type,
            "customer_id": customer_id,
            "build_configuration_id": build_configuration_id,
            # copied from the configuration and never re-derived afterward
            "body_spec_id": config["body_spec_id"],
            "chassis_id": None,
            "body_mount_offset_from_front_axle_in": offset,
            "body_actual_weight_lb": None,
            "body_install_status": "PLANNED",
            "required_payload_lb": required_payload_lb,
            "requested_in_service_date": requested_in_service_date,
            "warranty_liability_cap_cents": cap_cents,
            "build_status": "DRAFT",
            "compliance_status": "NOT_STARTED",
            "chassis_warranty_status": "INTACT",
            "committed_pto_flow_gpm": 0,
            "committed_aux_amp_draw": int((body or {}).get("aux_amp_draw") or 0),
            "invoice_total_cents": 0,
            "chassis_liability_cents": 0,
            "upfitter_liability_cents": 0,
            "customer_goodwill_cents": 0,
            "engineering_submitted_by_user_id": None,
            "rework_round": 0,
        },
    )
    return response.object_response(db.serialize(row), 201)


# --------------------------------------------------------------------------
# Engineering review loop
# --------------------------------------------------------------------------
@orders_bp.route("/upfit-orders/<upfit_order_id>/submit-engineering", methods=["POST"])
def submit_engineering(upfit_order_id):
    caller = middleware.require(middleware.ROLE_UPFIT_ENGINEER)
    order = lookup.upfit_order(upfit_order_id)
    if order["build_status"] not in ("DRAFT", "REWORK"):
        raise order_state_error(order, "DRAFT or REWORK")
    if order.get("body_mount_offset_from_front_axle_in") is None:
        raise v.invalid("body_mount_offset_from_front_axle_in must be present to submit.")
    order["build_status"] = "ENGINEERING_REVIEW"
    order["engineering_submitted_by_user_id"] = caller.user_id
    db.touch(order)
    return response.object_response(db.serialize(order), 200)


@orders_bp.route("/upfit-orders/<upfit_order_id>/request-rework", methods=["POST"])
def request_rework(upfit_order_id):
    middleware.require(middleware.ROLE_COMPLIANCE_OFFICER)
    payload = v.body()
    v.req_str(payload, "reason")
    order = lookup.upfit_order(upfit_order_id)
    if order["build_status"] != "ENGINEERING_REVIEW":
        raise order_state_error(order, "ENGINEERING_REVIEW")
    order["build_status"] = "REWORK"
    order["rework_round"] = int(order.get("rework_round") or 0) + 1
    db.touch(order)
    return response.object_response(db.serialize(order), 200)


# --------------------------------------------------------------------------
# Chassis allocation
# --------------------------------------------------------------------------
@orders_bp.route("/upfit-orders/<upfit_order_id>/allocate-chassis", methods=["POST"])
def allocate_chassis(upfit_order_id):
    middleware.require(middleware.ROLE_PRODUCTION_SCHEDULER)
    payload = v.body()
    chassis_id = v.req_str(payload, "chassis_id")
    expected_chassis_version = v.req_int(payload, "expected_chassis_version")

    order = lookup.upfit_order(upfit_order_id)
    unit = lookup.chassis(chassis_id)

    # 7. optimistic concurrency, above uniqueness and every state check
    if expected_chassis_version != unit.get("version"):
        raise ApiError(
            "ERR_STALE_CHASSIS_VERSION",
            "Expected chassis version %s but the unit is at version %s."
            % (expected_chassis_version, unit.get("version")),
        )

    # 9. state preconditions: the order's dimension first, then the chassis
    if order["build_status"] not in ALLOCATABLE_ORDER_STATES:
        raise order_state_error(order, "one of " + ", ".join(ALLOCATABLE_ORDER_STATES))
    if unit["status"] not in ("INSPECTED", "ALLOCATED"):
        raise ApiError(
            "ERR_CHASSIS_INVALID_STATE",
            "Allocation accepts a unit at INSPECTED or ALLOCATED; this one is %s." % unit["status"],
        )

    # 12. body builder book: the physical unit must be the configured model
    config = db.build_configurations.get(order["build_configuration_id"])
    if config is not None and unit["chassis_model_id"] != config["chassis_model_id"]:
        raise ApiError(
            "ERR_CHASSIS_MODEL_MISMATCH",
            "The unit's chassis model does not match the order's configuration.",
        )

    # 13. referential: is the incumbent binding still re-plannable?
    incumbent_id = unit.get("allocated_upfit_order_id")
    incumbent = None
    if incumbent_id and incumbent_id != order["id"]:
        incumbent = db.upfit_orders.get(incumbent_id)
        incumbent_state = (incumbent or {}).get("build_status")
        if incumbent_state in LOCKED_INCUMBENT_STATES:
            raise ApiError(
                "ERR_CHASSIS_ALREADY_ALLOCATED",
                "The unit is committed to order %s at %s." % (incumbent_id, incumbent_state),
            )
        if incumbent_state not in REBINDABLE_INCUMBENT_STATES:
            raise ApiError(
                "ERR_CHASSIS_ALREADY_ALLOCATED",
                "The unit is already allocated to order %s." % incumbent_id,
            )

    # the previous holder loses its truck
    if incumbent is not None:
        incumbent["chassis_id"] = None
        incumbent["build_status"] = "CHASSIS_HOLD"
        db.touch(incumbent)

    unit["allocated_upfit_order_id"] = order["id"]
    if unit["status"] == "INSPECTED":
        unit["status"] = "ALLOCATED"
    if order["order_type"] == "CUSTOMER_SPECIFIC":
        unit["ownership"] = "CUSTOMER_ASSIGNED"
    db.touch(unit)

    order["chassis_id"] = unit["id"]
    calc.run_pto_waterfall(order)
    calc.refresh_committed_aux(order)
    if order["build_status"] == "CHASSIS_HOLD":
        order["build_status"] = "RELEASED"
    db.touch(order)
    return response.object_response(db.serialize(order), 200)


# --------------------------------------------------------------------------
# Body mount position
# --------------------------------------------------------------------------
@orders_bp.route("/upfit-orders/<upfit_order_id>/body-mount", methods=["PATCH"])
def patch_body_mount(upfit_order_id):
    middleware.require(middleware.ROLE_UPFIT_ENGINEER)
    payload = v.body()
    offset = v.req_int(payload, "body_mount_offset_from_front_axle_in", minimum=0)
    order = lookup.upfit_order(upfit_order_id)

    order["body_mount_offset_from_front_axle_in"] = offset
    # the whole weight distribution just moved: the design certification is stale
    cascade.void_certifications(order, "BODY_MOUNT_CHANGED", basis="AS_DESIGNED")
    if order["build_status"] in ("RELEASED", "SCHEDULED", "IN_BUILD"):
        calc.refresh_invoice_total(order)
    db.touch(order)
    return response.object_response(db.serialize(order), 200)


# --------------------------------------------------------------------------
# Release: the compliance gate
# --------------------------------------------------------------------------
@orders_bp.route("/upfit-orders/<upfit_order_id>/release", methods=["POST"])
def release_order(upfit_order_id):
    caller = middleware.require(middleware.ROLE_PRODUCTION_SCHEDULER)
    order = lookup.upfit_order(upfit_order_id)

    # 4. segregation of duties, above every state and business check
    middleware.enforce_segregation(
        caller,
        order.get("engineering_submitted_by_user_id"),
        "The releasing user may not be the engineer who submitted the package.",
    )

    # 40. state precondition
    if order["build_status"] != "ENGINEERING_REVIEW":
        raise order_state_error(order, "ENGINEERING_REVIEW")
    chassis_id = order.get("chassis_id")
    if not chassis_id:
        raise ApiError(
            "ERR_ORDER_INVALID_STATE",
            "The order holds no chassis; release requires an allocated unit.",
        )
    unit = db.chassis_units.get(chassis_id)
    if unit is None or unit["status"] != "ALLOCATED":
        raise ApiError(
            "ERR_ORDER_INVALID_STATE",
            "The bound chassis must be at ALLOCATED to release the order.",
        )

    model = lookup.governing_chassis_model(order)
    body = db.body_specs.get(order.get("body_spec_id")) or {}
    config = db.build_configurations.get(order["build_configuration_id"]) or {}
    projection = calc.weight_projection(order, "AS_DESIGNED")

    # 50 / 51 / 52. the three regulatory ceilings, in this exact order
    if projection["gvw_lb"] > model["gvwr_lb"]:
        raise ApiError(
            "ERR_GVWR_EXCEEDED",
            "Projected GVW %s lb exceeds the model's GVWR %s lb."
            % (projection["gvw_lb"], model["gvwr_lb"]),
        )
    if projection["rear_axle_load_lb"] > model["rear_gawr_lb"]:
        raise ApiError(
            "ERR_REAR_GAWR_EXCEEDED",
            "Projected rear axle load %s lb exceeds the rear GAWR %s lb."
            % (projection["rear_axle_load_lb"], model["rear_gawr_lb"]),
        )
    if projection["front_axle_load_lb"] > model["front_gawr_lb"]:
        raise ApiError(
            "ERR_FRONT_GAWR_EXCEEDED",
            "Projected front axle load %s lb exceeds the front GAWR %s lb."
            % (projection["front_axle_load_lb"], model["front_gawr_lb"]),
        )

    # 53. contracted payload
    required_payload = int(order.get("required_payload_lb") or 0)
    if projection["payload_capacity_lb"] < required_payload:
        raise ApiError(
            "ERR_PAYLOAD_SHORTFALL",
            "Projected payload capacity %s lb is below the contracted %s lb."
            % (projection["payload_capacity_lb"], required_payload),
        )

    # 60. in-service feasibility; a null requested date skips the check entirely
    requested = order.get("requested_in_service_date")
    if requested:
        feasible = calc.earliest_feasible_in_service_date(order)
        if v.as_date(requested) < feasible:
            raise ApiError(
                "ERR_IN_SERVICE_DATE_INFEASIBLE",
                "Requested in-service date %s falls before the earliest feasible %s."
                % (requested, feasible.isoformat()),
            )

    # 70 / 71. the book fit rules, re-verified against the bound model
    if model["cab_to_axle_in"] < int(body.get("required_min_ca_in") or 0):
        raise ApiError(
            "ERR_CAB_TO_AXLE_INSUFFICIENT",
            "Bound chassis cab-to-axle %s is below the body's minimum %s."
            % (model["cab_to_axle_in"], body.get("required_min_ca_in")),
        )
    if model["wheelbase_in"] < int(body.get("required_min_wheelbase_in") or 0):
        raise ApiError(
            "ERR_WHEELBASE_INSUFFICIENT",
            "Bound chassis wheelbase %s is below the body's minimum %s."
            % (model["wheelbase_in"], body.get("required_min_wheelbase_in")),
        )

    live_installs = [
        inst
        for inst in lookup.installations_of(order["id"])
        if inst["status"] in calc.WEIGHT_ACTIVE_INSTALL_STATUSES
    ]

    # 76. every hydraulic claimant must have been paid in full
    for inst in live_installs:
        if inst.get("hydraulic_status") == "DEFICIT":
            raise ApiError(
                "ERR_HYDRAULIC_DEFICIT_UNRESOLVED",
                "Installation %s is still short of hydraulic flow." % inst["id"],
            )

    # 78. CAN gateway prerequisite
    gateway_ok = any(
        iface["status"] == "APPROVED"
        and iface["interface_method"] in ("CAN_GATEWAY", "BODY_BUILDER_MODULE")
        for iface in lookup.interfaces_of(order["id"])
    )
    if not gateway_ok:
        for inst in live_installs:
            spec = db.equipment_specs.get(inst["equipment_spec_id"]) or {}
            if spec.get("requires_can_gateway"):
                raise ApiError(
                    "ERR_CAN_GATEWAY_REQUIRED",
                    "Installation %s needs an APPROVED CAN gateway or body builder "
                    "module interface." % inst["id"],
                )

    # 81. pool builds stay standardized
    if order["order_type"] == "POOL_STOCK":
        standard = list(config.get("standard_equipment_spec_ids") or [])
        for inst in live_installs:
            if inst["equipment_spec_id"] not in standard:
                raise ApiError(
                    "ERR_NON_STANDARD_POOL_EQUIPMENT",
                    "Equipment spec %s is not part of the pool configuration."
                    % inst["equipment_spec_id"],
                )

    # 85. a dump body needs a hoist to lift it
    if body.get("requires_hydraulics"):
        powered = False
        for inst in live_installs:
            spec = db.equipment_specs.get(inst["equipment_spec_id"]) or {}
            if spec.get("requires_pto"):
                powered = True
                break
        if not powered:
            raise ApiError(
                "ERR_HYDRAULIC_SOURCE_MISSING",
                "The body requires hydraulics but no PTO-driven equipment is installed.",
            )

    order["build_status"] = "RELEASED"
    calc.refresh_invoice_total(order)
    db.touch(order)
    return response.object_response(db.serialize(order), 200)


# --------------------------------------------------------------------------
# Body install, delivery, cancellation
# --------------------------------------------------------------------------
@orders_bp.route("/upfit-orders/<upfit_order_id>/body-install", methods=["POST"])
def body_install(upfit_order_id):
    middleware.require(middleware.ROLE_INSTALL_TECHNICIAN)
    payload = v.body()
    actual_weight = v.req_int(payload, "body_actual_weight_lb", minimum=1)
    order = lookup.upfit_order(upfit_order_id)

    if order["build_status"] != "IN_BUILD":
        raise order_state_error(order, "IN_BUILD")
    if order["body_install_status"] != "PLANNED":
        raise ApiError(
            "ERR_BODY_ALREADY_INSTALLED",
            "The body of this order is already recorded as INSTALLED.",
        )
    order["body_actual_weight_lb"] = actual_weight
    order["body_install_status"] = "INSTALLED"
    db.touch(order)
    return response.object_response(db.serialize(order), 200)


@orders_bp.route("/upfit-orders/<upfit_order_id>/deliver", methods=["POST"])
def deliver_order(upfit_order_id):
    middleware.require(middleware.ROLE_PRODUCTION_SCHEDULER)
    order = lookup.upfit_order(upfit_order_id)

    if order["build_status"] != "BUILD_COMPLETE":
        raise order_state_error(order, "BUILD_COMPLETE")
    if order["compliance_status"] != "LABELED":
        raise ApiError(
            "ERR_ORDER_INVALID_STATE",
            "Delivery requires compliance_status LABELED; this order is %s."
            % order["compliance_status"],
        )
    unit = db.chassis_units.get(order.get("chassis_id")) if order.get("chassis_id") else None
    if unit is None or unit["status"] != "IN_UPFIT":
        raise ApiError(
            "ERR_ORDER_INVALID_STATE",
            "Delivery requires the bound chassis to still be at IN_UPFIT.",
        )

    order["build_status"] = "DELIVERED"
    db.touch(order)
    unit["status"] = "COMPLETED"
    db.touch(unit)
    return response.object_response(db.serialize(order), 200)


@orders_bp.route("/upfit-orders/<upfit_order_id>/cancel", methods=["POST"])
def cancel_order(upfit_order_id):
    middleware.require(middleware.ROLE_PLANT_ADMIN)
    payload = v.body()
    v.req_str(payload, "reason")
    order = lookup.upfit_order(upfit_order_id)

    if order["build_status"] not in CANCELLABLE_ORDER_STATES:
        raise order_state_error(order, "one of " + ", ".join(CANCELLABLE_ORDER_STATES))
    order["build_status"] = "CANCELLED"
    db.touch(order)
    cascade.order_cancel_cascade(order)
    return response.object_response(db.serialize(order), 200)


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------
@orders_bp.route("/upfit-orders/<upfit_order_id>", methods=["GET"])
def get_upfit_order(upfit_order_id):
    caller = middleware.require(*middleware.ALL_ROLES)
    order = lookup.upfit_order(upfit_order_id)
    middleware.enforce_order_scope(caller, order)
    return response.object_response(db.serialize(order), 200)


@orders_bp.route("/upfit-orders", methods=["GET"])
def list_upfit_orders():
    caller = middleware.require(*middleware.ALL_ROLES)
    customer_id = v.filter_str("customer_id")
    build_configuration_id = v.filter_str("build_configuration_id")
    body_spec_id = v.filter_str("body_spec_id")
    chassis_id = v.filter_str("chassis_id")
    order_type = v.filter_enum("order_type", v.ORDER_TYPE)
    build_status = v.filter_enum("build_status", v.BUILD_STATUS)
    compliance_status = v.filter_enum("compliance_status", v.COMPLIANCE_STATUS)

    rows = middleware.visible_orders(caller)
    if customer_id is not None:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if build_configuration_id is not None:
        rows = [r for r in rows if r["build_configuration_id"] == build_configuration_id]
    if body_spec_id is not None:
        rows = [r for r in rows if r["body_spec_id"] == body_spec_id]
    if chassis_id is not None:
        rows = [r for r in rows if r["chassis_id"] == chassis_id]
    if order_type is not None:
        rows = [r for r in rows if r["order_type"] == order_type]
    if build_status is not None:
        rows = [r for r in rows if r["build_status"] == build_status]
    if compliance_status is not None:
        rows = [r for r in rows if r["compliance_status"] == compliance_status]
    return response.paginate(rows)


@orders_bp.route("/upfit-orders/<upfit_order_id>/weight-projection", methods=["GET"])
def weight_projection(upfit_order_id):
    middleware.require(
        middleware.ROLE_PLANT_ADMIN,
        middleware.ROLE_PRODUCTION_SCHEDULER,
        middleware.ROLE_UPFIT_ENGINEER,
        middleware.ROLE_COMPLIANCE_OFFICER,
    )
    basis = v.filter_enum("basis", v.CERT_BASIS)
    if basis is None:
        raise v.invalid("Query parameter 'basis' is required and must be one of %s." % (v.CERT_BASIS,))
    order = lookup.upfit_order(upfit_order_id)
    return response.object_response(calc.weight_projection(order, basis), 200)
