"""Reference catalog: chassis models, body specs, equipment specs, work bays
and fleet customers (PRD section 3.1)."""

from flask import Blueprint

import db
import middleware
import response
import validation as v
from services import lookup

catalog_bp = Blueprint("catalog", __name__, url_prefix="/upfit")

STAFF = middleware.STAFF_ROLES


# --------------------------------------------------------------------------
# Chassis models
# --------------------------------------------------------------------------
@catalog_bp.route("/chassis-models", methods=["POST"])
def create_chassis_model():
    middleware.require(middleware.ROLE_PLANT_ADMIN)
    payload = v.body()
    fields = {
        "code": v.req_str(payload, "code", min_len=1, max_len=40),
        "make": v.req_str(payload, "make"),
        "gvwr_lb": v.req_int(payload, "gvwr_lb", minimum=1),
        "front_gawr_lb": v.req_int(payload, "front_gawr_lb", minimum=1),
        "rear_gawr_lb": v.req_int(payload, "rear_gawr_lb", minimum=1),
        "wheelbase_in": v.req_int(payload, "wheelbase_in", minimum=1),
        "cab_to_axle_in": v.req_int(payload, "cab_to_axle_in", minimum=1),
        "curb_front_axle_lb": v.req_int(payload, "curb_front_axle_lb", minimum=0),
        "curb_rear_axle_lb": v.req_int(payload, "curb_rear_axle_lb", minimum=0),
        "max_aux_amp_draw": v.req_int(payload, "max_aux_amp_draw", minimum=0),
        "electrical_bus": v.req_enum(payload, "electrical_bus", v.ELECTRICAL_BUS),
        "pto_provision": v.req_enum(payload, "pto_provision", v.PTO_PROVISION),
        "pto_max_flow_gpm": v.opt_int(payload, "pto_max_flow_gpm", default=0, minimum=0),
        "body_builder_book_rev": v.req_str(payload, "body_builder_book_rev"),
        "incomplete_vehicle_document_rev": v.opt_str(
            payload, "incomplete_vehicle_document_rev", default="IVD-2026.1"
        ),
    }
    if fields["pto_provision"] == "NONE" and fields["pto_max_flow_gpm"] != 0:
        raise v.invalid(
            "pto_max_flow_gpm must be exactly 0 when pto_provision is NONE."
        )
    row = db.insert(db.chassis_models, fields)
    return response.object_response(db.serialize(row), 201)


@catalog_bp.route("/chassis-models/<chassis_model_id>", methods=["GET"])
def get_chassis_model(chassis_model_id):
    middleware.require(*STAFF)
    return response.object_response(db.serialize(lookup.chassis_model(chassis_model_id)), 200)


@catalog_bp.route("/chassis-models", methods=["GET"])
def list_chassis_models():
    middleware.require(*STAFF)
    make = v.filter_str("make")
    pto_provision = v.filter_enum("pto_provision", v.PTO_PROVISION)
    rows = list(db.chassis_models.values())
    if make is not None:
        rows = [r for r in rows if r["make"] == make]
    if pto_provision is not None:
        rows = [r for r in rows if r["pto_provision"] == pto_provision]
    return response.paginate(rows)


# --------------------------------------------------------------------------
# Body specifications
# --------------------------------------------------------------------------
@catalog_bp.route("/body-specs", methods=["POST"])
def create_body_spec():
    middleware.require(middleware.ROLE_PLANT_ADMIN)
    payload = v.body()
    fields = {
        "code": v.req_str(payload, "code"),
        "body_type": v.req_enum(payload, "body_type", v.BODY_TYPE),
        "weight_lb": v.req_int(payload, "weight_lb", minimum=1),
        "cg_from_body_front_in": v.req_int(payload, "cg_from_body_front_in", minimum=0),
        "cargo_cg_from_body_front_in": v.req_int(
            payload, "cargo_cg_from_body_front_in", minimum=0
        ),
        "length_in": v.req_int(payload, "length_in", minimum=1),
        "required_min_ca_in": v.req_int(payload, "required_min_ca_in", minimum=0),
        "required_min_wheelbase_in": v.req_int(payload, "required_min_wheelbase_in", minimum=0),
        "aux_amp_draw": v.req_int(payload, "aux_amp_draw", minimum=0),
        "requires_hydraulics": v.opt_bool(payload, "requires_hydraulics", default=False),
        "list_price_cents": v.req_int(payload, "list_price_cents", minimum=0),
    }
    row = db.insert(db.body_specs, fields)
    return response.object_response(db.serialize(row), 201)


@catalog_bp.route("/body-specs/<body_spec_id>", methods=["GET"])
def get_body_spec(body_spec_id):
    middleware.require(*STAFF)
    return response.object_response(db.serialize(lookup.body_spec(body_spec_id)), 200)


@catalog_bp.route("/body-specs", methods=["GET"])
def list_body_specs():
    middleware.require(*STAFF)
    body_type = v.filter_enum("body_type", v.BODY_TYPE)
    rows = list(db.body_specs.values())
    if body_type is not None:
        rows = [r for r in rows if r["body_type"] == body_type]
    return response.paginate(rows)


# --------------------------------------------------------------------------
# Equipment specifications
# --------------------------------------------------------------------------
@catalog_bp.route("/equipment-specs", methods=["POST"])
def create_equipment_spec():
    middleware.require(middleware.ROLE_PLANT_ADMIN)
    payload = v.body()
    fields = {
        "code": v.req_str(payload, "code"),
        "equipment_class": v.req_enum(payload, "equipment_class", v.EQUIPMENT_CLASS),
        "weight_lb": v.req_int(payload, "weight_lb", minimum=1),
        "requires_pto": v.opt_bool(payload, "requires_pto", default=False),
        "required_flow_gpm": v.opt_int(payload, "required_flow_gpm", default=0, minimum=0),
        "aux_amp_draw": v.req_int(payload, "aux_amp_draw", minimum=0),
        "duty_priority": v.req_int(payload, "duty_priority", minimum=1),
        "mount_zone": v.req_enum(payload, "mount_zone", v.MOUNT_ZONE),
        "requires_can_gateway": v.opt_bool(payload, "requires_can_gateway", default=False),
        "list_price_cents": v.req_int(payload, "list_price_cents", minimum=0),
    }
    if not fields["requires_pto"] and fields["required_flow_gpm"] != 0:
        raise v.invalid("required_flow_gpm must be exactly 0 when requires_pto is false.")
    row = db.insert(db.equipment_specs, fields)
    return response.object_response(db.serialize(row), 201)


@catalog_bp.route("/equipment-specs/<equipment_spec_id>", methods=["GET"])
def get_equipment_spec(equipment_spec_id):
    middleware.require(*STAFF)
    return response.object_response(db.serialize(lookup.equipment_spec(equipment_spec_id)), 200)


@catalog_bp.route("/equipment-specs", methods=["GET"])
def list_equipment_specs():
    middleware.require(*STAFF)
    equipment_class = v.filter_enum("equipment_class", v.EQUIPMENT_CLASS)
    requires_pto = v.filter_bool("requires_pto")
    rows = list(db.equipment_specs.values())
    if equipment_class is not None:
        rows = [r for r in rows if r["equipment_class"] == equipment_class]
    if requires_pto is not None:
        rows = [r for r in rows if bool(r["requires_pto"]) == requires_pto]
    return response.paginate(rows)


# --------------------------------------------------------------------------
# Work bays
# --------------------------------------------------------------------------
@catalog_bp.route("/work-bays", methods=["POST"])
def create_work_bay():
    middleware.require(middleware.ROLE_PLANT_ADMIN)
    payload = v.body()
    fields = {
        "code": v.req_str(payload, "code"),
        "concurrent_capacity": v.req_int(payload, "concurrent_capacity", minimum=1),
        "supported_body_types": v.req_enum_list(payload, "supported_body_types", v.BODY_TYPE),
        "status": "ACTIVE",
    }
    row = db.insert(db.work_bays, fields)
    return response.object_response(db.serialize(row), 201)


@catalog_bp.route("/work-bays/<work_bay_id>/set-status", methods=["POST"])
def set_work_bay_status(work_bay_id):
    middleware.require(middleware.ROLE_PLANT_ADMIN)
    payload = v.body()
    status = v.req_enum(payload, "status", v.WORK_BAY_STATUS)
    bay = lookup.work_bay(work_bay_id)
    bay["status"] = status
    db.touch(bay)
    return response.object_response(db.serialize(bay), 200)


@catalog_bp.route("/work-bays/<work_bay_id>", methods=["GET"])
def get_work_bay(work_bay_id):
    middleware.require(*STAFF)
    return response.object_response(db.serialize(lookup.work_bay(work_bay_id)), 200)


@catalog_bp.route("/work-bays", methods=["GET"])
def list_work_bays():
    middleware.require(*STAFF)
    status = v.filter_enum("status", v.WORK_BAY_STATUS)
    rows = list(db.work_bays.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return response.paginate(rows)


# --------------------------------------------------------------------------
# Customers
# --------------------------------------------------------------------------
@catalog_bp.route("/customers", methods=["POST"])
def create_customer():
    middleware.require(middleware.ROLE_PLANT_ADMIN)
    payload = v.body()
    fields = {
        "name": v.req_str(payload, "name"),
        "account_code": v.req_str(payload, "account_code"),
        "fleet_contact_email": v.req_str(payload, "fleet_contact_email"),
    }
    row = db.insert(db.customers, fields)
    return response.object_response(db.serialize(row), 201)


@catalog_bp.route("/customers/<customer_id>", methods=["GET"])
def get_customer(customer_id):
    caller = middleware.require(
        middleware.ROLE_PLANT_ADMIN,
        middleware.ROLE_PRODUCTION_SCHEDULER,
        middleware.ROLE_WARRANTY_ADMINISTRATOR,
        middleware.ROLE_CUSTOMER,
    )
    row = lookup.find("customer", customer_id)
    if row is not None:
        middleware.enforce_customer_scope(caller, customer_id)
    row = lookup.customer(customer_id)
    return response.object_response(db.serialize(row), 200)


@catalog_bp.route("/customers", methods=["GET"])
def list_customers():
    middleware.require(
        middleware.ROLE_PLANT_ADMIN,
        middleware.ROLE_PRODUCTION_SCHEDULER,
        middleware.ROLE_WARRANTY_ADMINISTRATOR,
    )
    account_code = v.filter_str("account_code")
    rows = list(db.customers.values())
    if account_code is not None:
        rows = [r for r in rows if r["account_code"] == account_code]
    return response.paginate(rows)
