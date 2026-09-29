"""Master data: foundries, hydraulic models, casting tooling, service configs."""

from flask import Blueprint

from db import by_seq, db, new_record
from errors import ApiError
from helpers import (
    apply_filters,
    ensure_unique,
    lots_of_pattern,
    paginate,
    path_lookup,
    ref_lookup,
    touch,
)
from middleware import ALL_ROLES, authorize
from response import list_response, object_response
from serializers import dump, dump_all
from services.cascades import constrain_model_if_needed, unconstrain_model_if_possible
from validation import (
    ALLOYS,
    BALANCE_GRADES,
    FLUSH_PLANS,
    SEAL_TYPES,
    SERVICE_CLASSES,
    check_keys,
    get_body,
    pagination,
    query_value,
    req_array,
    req_enum,
    req_int,
    req_number,
    req_string,
)

bp = Blueprint("master", __name__)

BUSY_LOT_STATES = ("POURED", "INSPECTED", "REWORK", "QUARANTINED")


def _no_body_allowed():
    check_keys(get_body(), ())


def _collection(records, limit, offset):
    window, total = paginate(records, limit, offset)
    return list_response(dump_all(window), limit, offset, total)


# ------------------------------------------------------------------ foundries


@bp.post("/foundries")
def create_foundry():
    authorize("PlatformAdmin")
    body = get_body()
    check_keys(body, ("foundry_code", "name", "approved_alloys", "concurrent_pour_capacity"))
    foundry_code = req_string(body, "foundry_code", min_len=3, max_len=32)
    name = req_string(body, "name")
    alloys = req_array(body, "approved_alloys")
    if not alloys:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'approved_alloys' must be a non-empty array")
    for member in alloys:
        if not isinstance(member, str) or member not in ALLOYS:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "Field 'approved_alloys' members must be one of %s" % ", ".join(ALLOYS),
            )
    capacity = req_int(body, "concurrent_pour_capacity", minimum=1)

    ensure_unique(db.foundries, "foundry_code", foundry_code)

    record = new_record(
        "Foundry",
        foundry_code=foundry_code,
        name=name,
        approved_alloys=list(alloys),
        concurrent_pour_capacity=capacity,
        status="ACTIVE",
        suspension_reason=None,
    )
    db.foundries[record["id"]] = record
    return object_response(dump(record), 201)


@bp.get("/foundries")
def list_foundries():
    authorize(*ALL_ROLES)
    limit, offset = pagination()
    records = apply_filters(by_seq(db.foundries.values()), [(query_value("status"), "status")])
    return _collection(records, limit, offset)


@bp.get("/foundries/<resource_id>")
def read_foundry(resource_id):
    authorize(*ALL_ROLES)
    return object_response(dump(path_lookup(db.foundries, resource_id)))


@bp.post("/foundries/<resource_id>/suspend")
def suspend_foundry(resource_id):
    authorize("PlatformAdmin")
    body = get_body()
    check_keys(body, ("suspension_reason",))
    reason = req_string(body, "suspension_reason")
    foundry = path_lookup(db.foundries, resource_id)
    if foundry["status"] != "ACTIVE":
        raise ApiError("ERR_FOUNDRY_SUSPENDED")
    foundry["status"] = "SUSPENDED"
    foundry["suspension_reason"] = reason
    touch(foundry)
    return object_response(dump(foundry))


# ---------------------------------------------------------------- pump models


@bp.post("/pump-models")
def create_pump_model():
    authorize("PlatformAdmin")
    body = get_body()
    check_keys(
        body,
        (
            "model_code",
            "generation",
            "interchange_group",
            "max_impeller_diameter_mm",
            "min_impeller_diameter_mm",
            "shutoff_head_m",
            "bep_flow_m3h",
            "bep_head_m",
            "bep_efficiency_pct",
            "npshr_at_bep_m",
            "rated_speed_rpm",
            "max_flow_m3h",
            "rotor_mass_kg",
            "balance_grade",
        ),
    )
    model_code = req_string(body, "model_code")
    generation = req_int(body, "generation", minimum=1)
    interchange_group = req_string(body, "interchange_group")
    max_d = req_number(body, "max_impeller_diameter_mm", exclusive_min=0)
    min_d = req_number(body, "min_impeller_diameter_mm", exclusive_min=0)
    shutoff = req_number(body, "shutoff_head_m", exclusive_min=0)
    bep_flow = req_number(body, "bep_flow_m3h", exclusive_min=0)
    bep_head = req_number(body, "bep_head_m", exclusive_min=0)
    bep_eff = req_number(body, "bep_efficiency_pct", exclusive_min=0, maximum=100)
    npshr = req_number(body, "npshr_at_bep_m", exclusive_min=0)
    rated_speed = req_int(body, "rated_speed_rpm", minimum=300)
    max_flow = req_number(body, "max_flow_m3h", exclusive_min=0)
    rotor_mass = req_number(body, "rotor_mass_kg", exclusive_min=0)
    balance_grade = req_enum(body, "balance_grade", BALANCE_GRADES)

    if not float(min_d) < float(max_d):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'min_impeller_diameter_mm' must be strictly less than 'max_impeller_diameter_mm'",
        )
    if not float(shutoff) > float(bep_head):
        raise ApiError(
            "ERR_INVALID_REQUEST", "Field 'shutoff_head_m' must exceed 'bep_head_m'"
        )
    if not float(max_flow) > float(bep_flow):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'max_flow_m3h' must exceed 'bep_flow_m3h'")

    ensure_unique(db.pump_models, "model_code", model_code)

    record = new_record(
        "PumpModel",
        model_code=model_code,
        generation=generation,
        interchange_group=interchange_group,
        max_impeller_diameter_mm=max_d,
        min_impeller_diameter_mm=min_d,
        shutoff_head_m=shutoff,
        bep_flow_m3h=bep_flow,
        bep_head_m=bep_head,
        bep_efficiency_pct=bep_eff,
        npshr_at_bep_m=npshr,
        rated_speed_rpm=rated_speed,
        max_flow_m3h=max_flow,
        rotor_mass_kg=rotor_mass,
        balance_grade=balance_grade,
        superseded_by_model_id=None,
        status="ORDERABLE",
        warranty_defect_count=0,
        application_error_count=0,
        no_defect_count=0,
    )
    db.pump_models[record["id"]] = record
    return object_response(dump(record), 201)


@bp.get("/pump-models")
def list_pump_models():
    authorize(*ALL_ROLES)
    limit, offset = pagination()
    records = apply_filters(
        by_seq(db.pump_models.values()),
        [
            (query_value("interchange_group"), "interchange_group"),
            (query_value("superseded_by_model_id"), "superseded_by_model_id"),
            (query_value("status"), "status"),
        ],
    )
    return _collection(records, limit, offset)


@bp.get("/pump-models/<resource_id>")
def read_pump_model(resource_id):
    authorize(*ALL_ROLES)
    return object_response(dump(path_lookup(db.pump_models, resource_id)))


@bp.post("/pump-models/<resource_id>/supersede")
def supersede_pump_model(resource_id):
    authorize("PlatformAdmin")
    body = get_body()
    check_keys(body, ("superseded_by_model_id",))
    successor_id = req_string(body, "superseded_by_model_id")
    model = path_lookup(db.pump_models, resource_id)
    ref_lookup(db.pump_models, successor_id)
    if model["status"] not in ("ORDERABLE", "PATTERN_CONSTRAINED"):
        raise ApiError("ERR_MODEL_NOT_ORDERABLE")
    if successor_id == model["id"]:
        raise ApiError("ERR_SUCCESSOR_MODEL_INVALID")
    model["superseded_by_model_id"] = successor_id
    model["status"] = "SUPERSEDED"
    touch(model)
    return object_response(dump(model))


# ------------------------------------------------------------- pattern assets


@bp.post("/pattern-assets")
def create_pattern_asset():
    authorize("PlatformAdmin")
    body = get_body()
    check_keys(body, ("pump_model_id", "foundry_id", "pattern_code", "wear_threshold"))
    pump_model_id = req_string(body, "pump_model_id")
    foundry_id = req_string(body, "foundry_id")
    pattern_code = req_string(body, "pattern_code")
    wear_threshold = req_int(body, "wear_threshold", minimum=1)

    ref_lookup(db.pump_models, pump_model_id)
    ref_lookup(db.foundries, foundry_id)
    ensure_unique(db.pattern_assets, "pattern_code", pattern_code)

    record = new_record(
        "PatternAsset",
        pump_model_id=pump_model_id,
        foundry_id=foundry_id,
        pattern_code=pattern_code,
        wear_threshold=wear_threshold,
        pours_since_refurb=0,
        defect_pours_since_refurb=0,
        wear_index=0,
        refurb_cycles=0,
        status="QUALIFIED",
    )
    db.pattern_assets[record["id"]] = record
    # PATTERN_CONSTRAINED -> ORDERABLE is raised only by refurbishment-complete
    # (PRD section 3.4), so registering fresh tooling does not relieve the model.
    return object_response(dump(record), 201)


@bp.get("/pattern-assets")
def list_pattern_assets():
    authorize(*ALL_ROLES)
    limit, offset = pagination()
    records = apply_filters(
        by_seq(db.pattern_assets.values()),
        [
            (query_value("pump_model_id"), "pump_model_id"),
            (query_value("foundry_id"), "foundry_id"),
            (query_value("status"), "status"),
        ],
    )
    return _collection(records, limit, offset)


@bp.get("/pattern-assets/<resource_id>")
def read_pattern_asset(resource_id):
    authorize(*ALL_ROLES)
    return object_response(dump(path_lookup(db.pattern_assets, resource_id)))


def _pattern_free_of_busy_lots(pattern):
    for lot in lots_of_pattern(pattern["id"]):
        if lot["status"] in BUSY_LOT_STATES:
            return False
    return True


@bp.post("/pattern-assets/<resource_id>/refurbishment-start")
def start_refurbishment(resource_id):
    authorize("PlatformAdmin")
    _no_body_allowed()
    pattern = path_lookup(db.pattern_assets, resource_id)
    if pattern["status"] != "WORN" or not _pattern_free_of_busy_lots(pattern):
        raise ApiError("ERR_PATTERN_INVALID_STATE")
    pattern["status"] = "IN_REFURB"
    touch(pattern)
    return object_response(dump(pattern))


@bp.post("/pattern-assets/<resource_id>/refurbishment-complete")
def complete_refurbishment(resource_id):
    authorize("PlatformAdmin")
    _no_body_allowed()
    pattern = path_lookup(db.pattern_assets, resource_id)
    if pattern["status"] != "IN_REFURB":
        raise ApiError("ERR_PATTERN_INVALID_STATE")
    pattern["status"] = "QUALIFIED"
    pattern["pours_since_refurb"] = 0
    pattern["defect_pours_since_refurb"] = 0
    pattern["wear_index"] = 0
    pattern["refurb_cycles"] += 1
    # The critical-defect counter only counts the first critical defect per lot
    # *since the last completed refurbishment*, so the boundary is recorded here.
    # A creation-sequence mark rather than a timestamp: the logical clock can sit
    # still (or be rewound) between the defect and the refurbishment.
    pattern["_last_refurb_seq"] = db.seq_mark()
    touch(pattern)
    unconstrain_model_if_possible(pattern["pump_model_id"])
    return object_response(dump(pattern))


@bp.post("/pattern-assets/<resource_id>/retire")
def retire_pattern(resource_id):
    authorize("PlatformAdmin")
    _no_body_allowed()
    pattern = path_lookup(db.pattern_assets, resource_id)
    if pattern["status"] not in ("QUALIFIED", "WORN") or not _pattern_free_of_busy_lots(pattern):
        raise ApiError("ERR_PATTERN_INVALID_STATE")
    pattern["status"] = "RETIRED"
    touch(pattern)
    constrain_model_if_needed(pattern["pump_model_id"])
    return object_response(dump(pattern))


# ------------------------------------------------------ material seal configs


@bp.post("/material-seal-configs")
def create_material_seal_config():
    authorize("PlatformAdmin")
    body = get_body()
    check_keys(
        body,
        (
            "pump_model_id",
            "config_code",
            "casing_material",
            "impeller_material",
            "seal_type",
            "flush_plan",
            "service_class",
            "max_solids_pct",
            "max_viscosity_cst",
            "max_chloride_ppm",
            "max_temp_c",
            "min_running_clearance_mm",
        ),
    )
    pump_model_id = req_string(body, "pump_model_id")
    config_code = req_string(body, "config_code")
    casing_material = req_enum(body, "casing_material", ALLOYS)
    impeller_material = req_enum(body, "impeller_material", ALLOYS)
    seal_type = req_enum(body, "seal_type", SEAL_TYPES)
    flush_plan = req_enum(body, "flush_plan", FLUSH_PLANS)
    service_class = req_enum(body, "service_class", SERVICE_CLASSES)
    max_solids = req_number(body, "max_solids_pct", minimum=0)
    max_viscosity = req_number(body, "max_viscosity_cst", exclusive_min=0)
    max_chloride = req_number(body, "max_chloride_ppm", minimum=0)
    max_temp = req_number(body, "max_temp_c", exclusive_min=0)
    min_clearance = req_number(body, "min_running_clearance_mm", exclusive_min=0)

    ref_lookup(db.pump_models, pump_model_id)
    ensure_unique(db.material_seal_configs, "config_code", config_code)

    record = new_record(
        "MaterialSealConfig",
        versioned=False,
        pump_model_id=pump_model_id,
        config_code=config_code,
        casing_material=casing_material,
        impeller_material=impeller_material,
        seal_type=seal_type,
        flush_plan=flush_plan,
        service_class=service_class,
        max_solids_pct=max_solids,
        max_viscosity_cst=max_viscosity,
        max_chloride_ppm=max_chloride,
        max_temp_c=max_temp,
        min_running_clearance_mm=min_clearance,
    )
    db.material_seal_configs[record["id"]] = record
    return object_response(dump(record), 201)


@bp.get("/material-seal-configs")
def list_material_seal_configs():
    authorize(*ALL_ROLES)
    limit, offset = pagination()
    records = apply_filters(
        by_seq(db.material_seal_configs.values()),
        [
            (query_value("pump_model_id"), "pump_model_id"),
            (query_value("service_class"), "service_class"),
        ],
    )
    return _collection(records, limit, offset)


@bp.get("/material-seal-configs/<resource_id>")
def read_material_seal_config(resource_id):
    authorize(*ALL_ROLES)
    return object_response(dump(path_lookup(db.material_seal_configs, resource_id)))
