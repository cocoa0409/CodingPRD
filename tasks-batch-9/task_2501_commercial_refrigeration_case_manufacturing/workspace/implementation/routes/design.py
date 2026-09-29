"""Case design, the airflow model and the engineering-change cascade (PRD 3.2 / 3.5)."""

from flask import Blueprint

import serialize
from calculations import (
    airflow_load_model,
    installed_charge_of,
    refrigerant_charge_basis,
)
from db import db, new_row, rows
from errors import (
    ERR_DOOR_CONFIG_INVALID,
    ERR_DUPLICATE_CODE,
    ERR_INVALID_STATE_TRANSITION,
    ERR_LINE_SET_NOT_PERMITTED,
    ERR_REFRIGERANT_CHARGE_LIMIT_EXCEEDED,
    ERR_REFRIGERANT_SYSTEM_TYPE_INCOMPATIBLE,
    fail,
)
from middleware import ALL_ROLES, roles_required, user_id
from response import created, ok, ok_list
from services import (
    apply_compliance_hold_cascade,
    get_case_model,
    get_refrigerant,
    model_labels,
    model_tests,
    touch,
)
from validation import (
    filter_enum,
    filter_value,
    get_body,
    opt_int,
    opt_string,
    paginate,
    pagination,
    req_enum,
    req_int,
    req_number,
    req_string,
)

bp = Blueprint("design", __name__)

TEMPERATURE_CLASSES = ["HT", "MT", "LT"]
SYSTEM_TYPES = ["REMOTE", "SELF_CONTAINED"]
DOOR_TYPES = ["OPEN", "GLASS_DOOR"]
LENGTHS = [4, 6, 8, 12]
MODEL_STATUSES = [
    "DRAFT", "MODELED", "SUBMITTED_FOR_TEST", "TESTED_PASS", "TESTED_FAIL",
    "CERTIFIED", "DECERTIFIED",
]

COMPUTED_FIELDS = [
    "curtain_factor", "velocity_factor", "infiltration_load_w", "lighting_load_w",
    "fan_load_w", "defrost_load_w", "anti_sweat_load_w", "total_design_load_w",
    "installed_charge_grams", "nameplate_co2e_kg", "installed_co2e_kg",
]

ENGINEERING_CHANGE_SOURCES = [
    "MODELED", "SUBMITTED_FOR_TEST", "TESTED_PASS", "TESTED_FAIL", "CERTIFIED",
    "DECERTIFIED",
]


# --------------------------------------------------------------------------
# shared domain rules
# --------------------------------------------------------------------------
def check_door_config(door_type, glass_door_count):
    """Rank 17."""
    if door_type == "OPEN" and glass_door_count != 0:
        fail(ERR_DOOR_CONFIG_INVALID, "An OPEN case must carry exactly zero glass doors")
    if door_type == "GLASS_DOOR" and glass_door_count < 1:
        fail(ERR_DOOR_CONFIG_INVALID, "A GLASS_DOOR case must carry at least one glass door")


def check_line_set(system_type, line_set_length_ft):
    """Rank 18."""
    if system_type == "SELF_CONTAINED" and line_set_length_ft != 0:
        fail(ERR_LINE_SET_NOT_PERMITTED,
             "A SELF_CONTAINED case must declare exactly 0 feet of line set")
    if system_type == "REMOTE" and line_set_length_ft < 1:
        fail(ERR_LINE_SET_NOT_PERMITTED,
             "A REMOTE case must declare at least 1 foot of line set")


def check_system_type_compatible(model, refrigerant):
    """Rank 10."""
    if model["system_type"] not in refrigerant["allowed_system_types"]:
        fail(ERR_REFRIGERANT_SYSTEM_TYPE_INCOMPATIBLE,
             "Refrigerant %s does not permit %s circuits"
             % (refrigerant["refrigerant_code"], model["system_type"]))


def check_charge_limit(model, refrigerant):
    """Rank 11 -- computed on the fly from the nameplate and line-set basis."""
    if installed_charge_of(model) > refrigerant["max_charge_grams"]:
        fail(ERR_REFRIGERANT_CHARGE_LIMIT_EXCEEDED,
             "Installed charge exceeds the blend ceiling of %d grams"
             % refrigerant["max_charge_grams"])


# --------------------------------------------------------------------------
@bp.post("/case-models")
@roles_required("DesignEngineer")
def create_case_model():
    body = get_body()
    model_code = req_string(body, "model_code", 1, 32)
    application = req_string(body, "application")
    temperature_class = req_enum(body, "temperature_class", TEMPERATURE_CLASSES)
    system_type = req_enum(body, "system_type", SYSTEM_TYPES)
    refrigerant_id = req_string(body, "refrigerant_id")
    predecessor_model_id = opt_string(body, "predecessor_model_id")
    nominal_length_ft = req_int(body, "nominal_length_ft", choices=LENGTHS)
    tda_sqft = req_number(body, "tda_sqft", exclusive_minimum=0)
    charge_grams = req_int(body, "charge_grams", minimum=1)
    line_set_length_ft = req_int(body, "line_set_length_ft", minimum=0)
    door_type = req_enum(body, "door_type", DOOR_TYPES)
    glass_door_count = opt_int(body, "glass_door_count", default=0, minimum=0)
    curtain_layers = req_int(body, "curtain_layers", minimum=1)
    discharge_velocity_mps = req_number(body, "discharge_velocity_mps", exclusive_minimum=0)
    case_air_temp_c = req_number(body, "case_air_temp_c")
    ambient_dew_point_c = req_number(body, "ambient_dew_point_c")
    lighting_w_per_ft = req_number(body, "lighting_w_per_ft", minimum=0)
    fan_w_per_ft = req_number(body, "fan_w_per_ft", minimum=0)
    defrost_cycles_per_day = req_int(body, "defrost_cycles_per_day", minimum=0)

    # rank 6, in declaration order
    get_refrigerant(refrigerant_id)
    if predecessor_model_id is not None:
        get_case_model(predecessor_model_id)

    check_door_config(door_type, glass_door_count)   # rank 17
    check_line_set(system_type, line_set_length_ft)  # rank 18

    for existing in db.case_models.values():         # rank 21
        if existing["model_code"] == model_code:
            fail(ERR_DUPLICATE_CODE, "model_code '%s' already exists" % model_code)

    row = new_row()
    row.update({
        "model_code": model_code,
        "application": application,
        "temperature_class": temperature_class,
        "system_type": system_type,
        "refrigerant_id": refrigerant_id,
        "predecessor_model_id": predecessor_model_id,
        "nominal_length_ft": nominal_length_ft,
        "tda_sqft": tda_sqft,
        "charge_grams": charge_grams,
        "line_set_length_ft": line_set_length_ft,
        "door_type": door_type,
        "glass_door_count": glass_door_count,
        "curtain_layers": curtain_layers,
        "discharge_velocity_mps": discharge_velocity_mps,
        "case_air_temp_c": case_air_temp_c,
        "ambient_dew_point_c": ambient_dew_point_c,
        "lighting_w_per_ft": lighting_w_per_ft,
        "fan_w_per_ft": fan_w_per_ft,
        "defrost_cycles_per_day": defrost_cycles_per_day,
        "design_revision": 1,
        "submitted_by_user_id": None,
        "status": "DRAFT",
    })
    for field in COMPUTED_FIELDS:
        row[field] = None
    db.case_models[row["id"]] = row
    return created(serialize.dump("CaseModel", row))


@bp.post("/case-models/<model_id>/airflow-model")
@roles_required("DesignEngineer")
def run_airflow_model(model_id):
    get_body()
    model = get_case_model(model_id)

    if model["status"] != "DRAFT":                                    # rank 7
        fail(ERR_INVALID_STATE_TRANSITION,
             "The airflow model may only be run on a DRAFT case model")

    refrigerant = db.refrigerants.get(model["refrigerant_id"])
    check_system_type_compatible(model, refrigerant)                  # rank 10
    check_door_config(model["door_type"], model["glass_door_count"])  # rank 17

    airflow_load_model(model)
    refrigerant_charge_basis(model, refrigerant)
    model["status"] = "MODELED"
    touch(model)
    return ok(serialize.dump("CaseModel", model))


@bp.post("/case-models/<model_id>/submit-for-test")
@roles_required("DesignEngineer")
def submit_for_test(model_id):
    get_body()
    model = get_case_model(model_id)

    if model["status"] != "MODELED" or model.get("total_design_load_w") is None:
        fail(ERR_INVALID_STATE_TRANSITION,
             "Only a MODELED case model with a computed design load may be submitted")

    refrigerant = db.refrigerants.get(model["refrigerant_id"])
    check_charge_limit(model, refrigerant)  # rank 11

    model["status"] = "SUBMITTED_FOR_TEST"
    model["submitted_by_user_id"] = user_id()
    touch(model)
    return ok(serialize.dump("CaseModel", model))


@bp.post("/case-models/<model_id>/engineering-change")
@roles_required("DesignEngineer")
def engineering_change(model_id):
    body = get_body()
    refrigerant_id = req_string(body, "refrigerant_id")
    charge_grams = req_int(body, "charge_grams", minimum=1)
    line_set_length_ft = req_int(body, "line_set_length_ft", minimum=0)
    change_note = req_string(body, "change_note")

    model = get_case_model(model_id)                 # rank 5
    refrigerant = get_refrigerant(refrigerant_id)    # rank 6

    if model["status"] not in ENGINEERING_CHANGE_SOURCES:   # rank 7
        fail(ERR_INVALID_STATE_TRANSITION,
             "An engineering change is not admissible from %s" % model["status"])

    check_system_type_compatible(model, refrigerant)        # rank 10
    check_line_set(model["system_type"], line_set_length_ft)  # rank 18

    # ---- hop 1: the design itself -----------------------------------------
    model["refrigerant_id"] = refrigerant_id
    model["charge_grams"] = charge_grams
    model["line_set_length_ft"] = line_set_length_ft
    model["change_note"] = change_note
    model["design_revision"] = model["design_revision"] + 1
    model["submitted_by_user_id"] = None
    model["status"] = "DRAFT"
    for field in COMPUTED_FIELDS:
        model[field] = None
    touch(model)

    # ---- hop 2: labels and running tests ----------------------------------
    for label in model_labels(model["id"]):
        if label["label_status"] == "ISSUED":
            label["label_status"] = "SUPERSEDED"
            touch(label)
    for test in model_tests(model["id"]):
        if test["status"] == "RUNNING":
            test["status"] = "INVALIDATED"
            touch(test)

    # ---- hops 3, 4 and 5 --------------------------------------------------
    apply_compliance_hold_cascade(model)

    return ok(serialize.dump("CaseModel", model))


@bp.get("/case-models/<model_id>")
@roles_required(*ALL_ROLES)
def read_case_model(model_id):
    return ok(serialize.dump("CaseModel", get_case_model(model_id)))


@bp.get("/case-models")
@roles_required(*ALL_ROLES)
def list_case_models():
    limit, offset = pagination()
    refrigerant_id = filter_value("refrigerant_id")
    predecessor_model_id = filter_value("predecessor_model_id")
    status = filter_enum("status", MODEL_STATUSES)

    items = rows(db.case_models)
    if refrigerant_id is not None:
        items = [r for r in items if r["refrigerant_id"] == refrigerant_id]
    if predecessor_model_id is not None:
        items = [r for r in items if r["predecessor_model_id"] == predecessor_model_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]

    page, total = paginate(items, limit, offset)
    return ok_list(serialize.dump_many("CaseModel", page), limit, offset, total)
