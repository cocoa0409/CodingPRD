"""PRD 3.6 -- engineering designs, component detailing, submit, review and revise."""

from flask import Blueprint, request

import constants as C
import serializers as S
import validation as V
from errors import ApiError, invalid
from middleware import ANY, actor, roles_required
from response import object_response, paginated
from services import calc, domain
from store import db, new_row, ordered, touch

bp = Blueprint("designs", __name__)

WEIGHT_FIELDS = ("quantity", "length_ft", "weight_per_ft")
CONNECTION_FIELDS = ("connection_type", "capacity_moment_kip_ft")


@bp.route("/engineering-designs", methods=["POST"])
@roles_required("Engineer")
def create_design():
    data = V.body()
    configuration_id = V.get_string(data, "configuration_id")
    design_variant = V.get_enum(data, "design_variant", C.DESIGN_VARIANTS)
    expected_version = V.get_int(data, "expected_configuration_version")

    config = domain.get_configuration(configuration_id)

    # Band 6 precedes band 10.
    if expected_version != config["version"]:
        raise ApiError("ERR_STALE_CONFIGURATION_VERSION")
    if config["status"] != "LOCKED":
        raise ApiError("ERR_CONFIGURATION_NOT_LOCKED")

    computed = calc.design_load_combination_and_required_moment(config, design_variant)

    # Opening a design supersedes every earlier non-terminal design of the
    # configuration -- from APPROVED just as much as from DRAFT.
    for earlier in domain.designs_of_configuration(config["id"]):
        if earlier["status"] in C.DESIGN_NON_TERMINAL:
            earlier["status"] = "SUPERSEDED"
            touch(earlier)

    fields = {
        "configuration_id": config["id"],
        "design_variant": design_variant,
        "frame_weight_lbs": 0,
        "shippable_weight_lbs": 0,
        "component_count": 0,
        "revision_count": 0,
        "submitted_by_user_id": None,
        "reviewed_by_user_id": None,
        "status": "DRAFT",
    }
    fields.update(computed)
    row = new_row(fields)
    db.designs[row["id"]] = row

    # The configuration now has a different current design.
    touch(config)
    return object_response(S.design_out(row), 201)


@bp.route("/engineering-designs/<design_id>", methods=["GET"])
@roles_required(ANY)
def read_design(design_id):
    return object_response(S.design_out(domain.get_design(design_id)))


@bp.route("/engineering-designs", methods=["GET"])
@roles_required(ANY)
def list_designs():
    configuration_id = request.args.get("configuration_id")
    status = request.args.get("status")

    def predicate(row):
        if configuration_id is not None and row["configuration_id"] != configuration_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return paginated(ordered(db.designs, predicate), S.design_out)


@bp.route("/engineering-designs/<design_id>/components", methods=["POST"])
@roles_required("Engineer")
def append_component(design_id):
    data = V.body()
    component_class = V.get_enum(data, "component_class", C.COMPONENT_CLASSES)
    mark = V.get_string(data, "mark", min_len=1, max_len=12)
    member_type = V.get_enum(data, "member_type", C.MEMBER_TYPES)
    erection_stage = V.get_enum(data, "erection_stage", C.ERECTION_STAGES)

    # Band 3: the class/field split is strict, not advisory.
    if component_class == "CONNECTION_DETAIL":
        for forbidden in WEIGHT_FIELDS:
            if V.present(data, forbidden):
                raise invalid("%s must not be supplied for a CONNECTION_DETAIL" % forbidden)
        connection_type = V.get_enum(data, "connection_type", C.CONNECTION_TYPES)
        capacity_moment = V.get_number(data, "capacity_moment_kip_ft", minimum=0)
        quantity = None
        length_ft = None
        weight_per_ft = None
    else:
        for forbidden in CONNECTION_FIELDS:
            if V.present(data, forbidden):
                raise invalid("%s must not be supplied for component class %s" % (forbidden, component_class))
        connection_type = None
        capacity_moment = None
        quantity = V.get_int(data, "quantity", minimum=1)
        length_ft = V.get_number(data, "length_ft", exclusive_minimum=0)
        weight_per_ft = V.get_number(data, "weight_per_ft", exclusive_minimum=0)

    design = domain.get_design(design_id)

    if design["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    existing = domain.components_of_design(design["id"])
    for component in existing:
        if component["mark"] == mark:
            raise ApiError("ERR_DUPLICATE_COMPONENT_MARK")

    unit_weight, line_weight = calc.component_weights(
        component_class, length_ft, weight_per_ft, quantity
    )
    row = new_row(
        {
            "design_id": design["id"],
            "component_class": component_class,
            "mark": mark,
            "member_type": member_type,
            "erection_stage": erection_stage,
            "quantity": quantity,
            "length_ft": length_ft,
            "weight_per_ft": weight_per_ft,
            "connection_type": connection_type,
            "capacity_moment_kip_ft": capacity_moment,
            "unit_weight_lbs": unit_weight,
            "line_weight_lbs": line_weight,
        },
        versioned=False,
    )
    db.components[row["id"]] = row

    design.update(calc.design_weight_rollup(domain.components_of_design(design["id"])))
    touch(design)
    return object_response(S.component_out(row), 201)


@bp.route("/engineering-designs/<design_id>/components", methods=["GET"])
@roles_required(ANY)
def list_components(design_id):
    design = domain.get_design(design_id)
    component_class = request.args.get("component_class")

    def predicate(row):
        if row["design_id"] != design["id"]:
            return False
        if component_class is not None and row["component_class"] != component_class:
            return False
        return True

    return paginated(ordered(db.components, predicate), S.component_out)


@bp.route("/engineering-designs/<design_id>/submit", methods=["POST"])
@roles_required("Engineer")
def submit_design(design_id):
    design = domain.get_design(design_id)

    if design["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    config = db.configurations.get(design["configuration_id"])
    if config is None or config["status"] != "LOCKED":
        raise ApiError("ERR_CONFIGURATION_NOT_LOCKED")

    components = domain.components_of_design(design["id"])
    if not any(c["component_class"] == "PRIMARY_FRAME_MEMBER" for c in components):
        raise ApiError("ERR_PRIMARY_FRAME_MEMBERS_MISSING")

    design["submitted_by_user_id"] = actor()
    design["status"] = "SUBMITTED"
    touch(design)
    return object_response(S.design_out(design))


@bp.route("/engineering-designs/<design_id>/review", methods=["POST"])
@roles_required("EngineeringManager")
def review_design(design_id):
    data = V.body()
    decision = V.get_enum(data, "decision", C.REVIEW_DECISIONS)

    design = domain.get_design(design_id)

    # Band 7 precedes band 9.
    if design["submitted_by_user_id"] is not None and design["submitted_by_user_id"] == actor():
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if design["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    design["reviewed_by_user_id"] = actor()

    if decision == "APPROVE":
        design["status"] = "APPROVED"
        # Approval reaches orders through the CONFIGURATION, not a pre-existing link.
        for order in ordered(
            db.orders, lambda o: o["configuration_id"] == design["configuration_id"]
        ):
            if order["production_status"] == "PROD_COMPLETE":
                continue
            if order["engineering_status"] not in ("ENG_PENDING", "ENG_REWORK"):
                continue
            order["engineering_design_id"] = design["id"]
            order["engineering_status"] = "ENG_APPROVED"
            touch(order)
    else:
        design["status"] = "REVISION_REQUIRED"
        # Revision reaches orders through the EXISTING design link only.
        for order in ordered(
            db.orders, lambda o: o["engineering_design_id"] == design["id"]
        ):
            order["engineering_status"] = "ENG_REWORK"
            touch(order)

    touch(design)
    return object_response(S.design_out(design))


@bp.route("/engineering-designs/<design_id>/revise", methods=["POST"])
@roles_required("Engineer")
def revise_design(design_id):
    design = domain.get_design(design_id)

    if design["status"] != "REVISION_REQUIRED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if design["revision_count"] >= C.MAX_DESIGN_REVISIONS:
        raise ApiError("ERR_REVISION_LIMIT_REACHED")

    design["revision_count"] = design["revision_count"] + 1
    design["submitted_by_user_id"] = None
    design["reviewed_by_user_id"] = None
    design["status"] = "DRAFT"
    touch(design)
    return object_response(S.design_out(design))
