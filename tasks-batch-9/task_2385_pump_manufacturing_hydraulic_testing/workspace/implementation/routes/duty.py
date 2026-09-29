"""Customer enquiries and hydraulic sizing."""

from flask import Blueprint, g

from db import by_seq, db, new_record
from errors import ApiError
from helpers import (
    apply_filters,
    ensure_unique,
    paginate,
    path_lookup,
    patterns_of_model,
    ref_lookup,
    touch,
)
from middleware import ALL_ROLES, authorize
from response import list_response, object_response
from serializers import dump, dump_all
from services import calc
from validation import (
    SERVICE_CLASSES,
    TEST_GRADES,
    check_keys,
    get_body,
    pagination,
    query_value,
    req_bool,
    req_enum,
    req_int,
    req_number,
    req_string,
)

bp = Blueprint("duty", __name__)


def _no_body_allowed():
    check_keys(get_body(), ())


def _collection(records, limit, offset):
    window, total = paginate(records, limit, offset)
    return list_response(dump_all(window), limit, offset, total)


# ----------------------------------------------------------- duty applications


@bp.post("/duty-applications")
def create_duty_application():
    authorize("ApplicationEngineer")
    body = get_body()
    check_keys(
        body,
        (
            "application_code",
            "customer_name",
            "duty_flow_m3h",
            "duty_head_m",
            "npsha_available_m",
            "specific_gravity",
            "viscosity_cst",
            "solids_pct",
            "chloride_ppm",
            "process_temp_c",
            "min_efficiency_pct",
            "test_grade",
            "witness_required",
            "service_class_required",
        ),
    )
    application_code = req_string(body, "application_code")
    customer_name = req_string(body, "customer_name")
    duty_flow = req_number(body, "duty_flow_m3h", exclusive_min=0)
    duty_head = req_number(body, "duty_head_m", exclusive_min=0)
    npsha = req_number(body, "npsha_available_m", exclusive_min=0)
    specific_gravity = req_number(body, "specific_gravity", exclusive_min=0)
    viscosity = req_number(body, "viscosity_cst", exclusive_min=0)
    solids = req_number(body, "solids_pct", minimum=0)
    chloride = req_number(body, "chloride_ppm", minimum=0)
    process_temp = req_number(body, "process_temp_c", exclusive_min=0)
    min_efficiency = req_number(body, "min_efficiency_pct", exclusive_min=0, maximum=100)
    test_grade = req_enum(body, "test_grade", TEST_GRADES)
    witness_required = req_bool(body, "witness_required")
    service_class_required = req_enum(body, "service_class_required", SERVICE_CLASSES)

    ensure_unique(db.duty_applications, "application_code", application_code)

    record = new_record(
        "DutyApplication",
        application_code=application_code,
        customer_name=customer_name,
        duty_flow_m3h=duty_flow,
        duty_head_m=duty_head,
        npsha_available_m=npsha,
        specific_gravity=specific_gravity,
        viscosity_cst=viscosity,
        solids_pct=solids,
        chloride_ppm=chloride,
        process_temp_c=process_temp,
        min_efficiency_pct=min_efficiency,
        test_grade=test_grade,
        witness_required=witness_required,
        service_class_required=service_class_required,
        status="OPEN",
    )
    db.duty_applications[record["id"]] = record
    return object_response(dump(record), 201)


@bp.get("/duty-applications")
def list_duty_applications():
    authorize(*ALL_ROLES)
    limit, offset = pagination()
    records = apply_filters(
        by_seq(db.duty_applications.values()), [(query_value("status"), "status")]
    )
    return _collection(records, limit, offset)


@bp.get("/duty-applications/<resource_id>")
def read_duty_application(resource_id):
    authorize(*ALL_ROLES)
    return object_response(dump(path_lookup(db.duty_applications, resource_id)))


# ------------------------------------------------------------------ selections


@bp.post("/selections")
def create_selection():
    authorize("ApplicationEngineer")
    body = get_body()
    check_keys(
        body,
        (
            "duty_application_id",
            "pump_model_id",
            "material_seal_config_id",
            "expected_duty_application_version",
        ),
    )
    duty_application_id = req_string(body, "duty_application_id")
    pump_model_id = req_string(body, "pump_model_id")
    material_seal_config_id = req_string(body, "material_seal_config_id")
    expected_version = req_int(body, "expected_duty_application_version")

    # Rung 5, in the order the fields are declared in the endpoint's input list.
    duty = ref_lookup(db.duty_applications, duty_application_id)
    model = ref_lookup(db.pump_models, pump_model_id)
    config = ref_lookup(db.material_seal_configs, material_seal_config_id)

    if expected_version != duty["version"]:
        raise ApiError("ERR_STALE_DUTY_APPLICATION_VERSION")
    if duty["status"] != "OPEN":
        raise ApiError("ERR_DUTY_APPLICATION_NOT_OPEN")
    if model["status"] != "ORDERABLE":
        raise ApiError("ERR_MODEL_NOT_ORDERABLE")
    if config["pump_model_id"] != pump_model_id:
        raise ApiError("ERR_CONFIG_MODEL_MISMATCH")

    # The three calculations all run before the gates that read their outputs.
    trim = calc.impeller_trim(model, duty)
    efficiency = None
    npsh = None
    if trim["trimmed_impeller_diameter_mm"] > 0:
        efficiency = calc.efficiency_and_power(model, duty, config, trim)
        npsh = calc.npsh_chain(model, duty, efficiency["flow_ratio"])

    if calc.D(duty["process_temp_c"]) > calc.D(config["max_temp_c"]):
        raise ApiError("ERR_TEMPERATURE_LIMIT_EXCEEDED")
    if calc.D(duty["chloride_ppm"]) > calc.D(config["max_chloride_ppm"]):
        raise ApiError("ERR_CHLORIDE_LIMIT_EXCEEDED")
    if calc.D(duty["solids_pct"]) > calc.D(config["max_solids_pct"]):
        raise ApiError("ERR_SOLIDS_LIMIT_EXCEEDED")
    if calc.D(duty["viscosity_cst"]) > calc.D(config["max_viscosity_cst"]):
        raise ApiError("ERR_VISCOSITY_LIMIT_EXCEEDED")
    if config["service_class"] != duty["service_class_required"]:
        raise ApiError("ERR_SERVICE_CLASS_MISMATCH")
    if calc.D(duty["duty_flow_m3h"]) > calc.D(model["max_flow_m3h"]):
        raise ApiError("ERR_DUTY_FLOW_ABOVE_MAX")
    if trim["trimmed_impeller_diameter_mm"] < calc.D(model["min_impeller_diameter_mm"]):
        raise ApiError("ERR_TRIM_BELOW_MINIMUM")
    if trim["trimmed_impeller_diameter_mm"] > calc.D(model["max_impeller_diameter_mm"]):
        raise ApiError("ERR_DUTY_POINT_ABOVE_ENVELOPE")
    if efficiency["predicted_efficiency_pct"] < calc.D(duty["min_efficiency_pct"]):
        raise ApiError("ERR_EFFICIENCY_TARGET_NOT_MET")

    record = new_record(
        "Selection",
        duty_application_id=duty_application_id,
        pump_model_id=pump_model_id,
        material_seal_config_id=material_seal_config_id,
        trimmed_impeller_diameter_mm=trim["trimmed_impeller_diameter_mm"],
        diameter_ratio=trim["diameter_ratio"],
        predicted_head_m=trim["predicted_head_m"],
        predicted_efficiency_pct=efficiency["predicted_efficiency_pct"],
        predicted_shaft_power_kw=efficiency["predicted_shaft_power_kw"],
        npshr_catalog_m=npsh["npshr_catalog_m"],
        npsh_provisional_margin_m=npsh["npsh_provisional_margin_m"],
        npsh_safety_factor=npsh["npsh_safety_factor_applied"],
        npshr_certified_m=npsh["npshr_certified_m"],
        npsh_margin_m=npsh["npsh_margin_m"],
        min_motor_kw=efficiency["min_motor_kw"],
        proposed_by_user_id=None,
        approved_by_user_id=None,
        status="DRAFT",
    )
    db.selections[record["id"]] = record
    # The enquiry's observable state has moved on even though its status has not.
    touch(duty)
    return object_response(dump(record), 201)


@bp.get("/selections")
def list_selections():
    authorize(*ALL_ROLES)
    limit, offset = pagination()
    records = apply_filters(
        by_seq(db.selections.values()),
        [
            (query_value("duty_application_id"), "duty_application_id"),
            (query_value("pump_model_id"), "pump_model_id"),
            (query_value("material_seal_config_id"), "material_seal_config_id"),
            (query_value("status"), "status"),
        ],
    )
    return _collection(records, limit, offset)


@bp.get("/selections/<resource_id>")
def read_selection(resource_id):
    authorize(*ALL_ROLES)
    return object_response(dump(path_lookup(db.selections, resource_id)))


@bp.post("/selections/<resource_id>/propose")
def propose_selection(resource_id):
    authorize("ApplicationEngineer")
    _no_body_allowed()
    selection = path_lookup(db.selections, resource_id)
    if selection["status"] not in ("DRAFT", "UNDER_REVIEW"):
        raise ApiError("ERR_SELECTION_INVALID_STATE")
    selection["status"] = "PROPOSED"
    selection["proposed_by_user_id"] = g.user_id
    touch(selection)
    return object_response(dump(selection))


@bp.post("/selections/<resource_id>/revise")
def revise_selection(resource_id):
    authorize("ApplicationEngineer")
    _no_body_allowed()
    selection = path_lookup(db.selections, resource_id)
    if selection["status"] != "PROPOSED":
        raise ApiError("ERR_SELECTION_INVALID_STATE")
    selection["status"] = "DRAFT"
    selection["proposed_by_user_id"] = None
    touch(selection)
    return object_response(dump(selection))


@bp.post("/selections/<resource_id>/approve")
def approve_selection(resource_id):
    authorize("HydraulicApprover")
    _no_body_allowed()
    selection = path_lookup(db.selections, resource_id)

    # Rung 7 sits above the state check at rung 17 on purpose.
    if selection["proposed_by_user_id"] is not None and selection["proposed_by_user_id"] == g.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if selection["status"] != "PROPOSED":
        raise ApiError("ERR_SELECTION_INVALID_STATE")
    qualified = [
        p for p in patterns_of_model(selection["pump_model_id"]) if p["status"] == "QUALIFIED"
    ]
    if not qualified:
        raise ApiError("ERR_PATTERN_NOT_QUALIFIED")
    if calc.D(selection["npsh_margin_m"]) < calc.MIN_NPSH_MARGIN_M:
        raise ApiError("ERR_NPSH_MARGIN_INSUFFICIENT")

    selection["status"] = "APPROVED"
    selection["approved_by_user_id"] = g.user_id
    touch(selection)
    duty = db.duty_applications.get(selection["duty_application_id"])
    if duty is not None and duty["status"] == "OPEN":
        duty["status"] = "SELECTION_LOCKED"
        touch(duty)
    return object_response(dump(selection))


@bp.post("/selections/<resource_id>/supersede")
def supersede_selection(resource_id):
    authorize("ApplicationEngineer")
    _no_body_allowed()
    selection = path_lookup(db.selections, resource_id)
    open_orders = [
        b
        for b in db.build_orders.values()
        if b["selection_id"] == selection["id"] and b["status"] != "CLOSED"
    ]
    if selection["status"] != "APPROVED" or open_orders:
        raise ApiError("ERR_SELECTION_INVALID_STATE")
    selection["status"] = "SUPERSEDED"
    touch(selection)
    duty = db.duty_applications.get(selection["duty_application_id"])
    if duty is not None and duty["status"] == "SELECTION_LOCKED":
        duty["status"] = "OPEN"
        touch(duty)
    return object_response(dump(selection))
