"""Spring designs, their critical-characteristic plan and tooling assets."""

from flask import Blueprint

import auth
import calc
import cascades
import envelope
import find
import store
import validate
from auth import (CUSTOMER_REPRESENTATIVE, DESIGN_ENGINEER, ENGINEERING_MANAGER,
                  PLANT_ADMIN, PROCESS_TECHNICIAN, PROGRAM_MANAGER,
                  QUALITY_INSPECTOR)
from errors import ApiError

bp = Blueprint("designs", __name__)

DESIGN_READERS = (DESIGN_ENGINEER, ENGINEERING_MANAGER, PROCESS_TECHNICIAN,
                  QUALITY_INSPECTOR, PROGRAM_MANAGER, PLANT_ADMIN)
TOOLING_READERS = (ENGINEERING_MANAGER, PROGRAM_MANAGER, PROCESS_TECHNICIAN,
                   DESIGN_ENGINEER, QUALITY_INSPECTOR, PLANT_ADMIN)

REVISABLE = ("DRAFT", "ENG_REVIEW", "REJECTED", "PROTOTYPE_RELEASED")
RETIREABLE = ("PROTOTYPE_RELEASED", "REJECTED", "PRODUCTION_RELEASED")
LOCKING_SUBMISSION_STATUSES = ("SUBMITTED", "INTERIM_APPROVED", "APPROVED")


# ---------------------------------------------------------------------------
# Geometry / metallurgy helpers
# ---------------------------------------------------------------------------
def _check_geometry(values):
    if values["outer_diameter_mm"] <= values["wire_diameter_mm"]:
        validate.bad("outer_diameter_mm must be greater than wire_diameter_mm.")
    if values["min_working_load_n"] >= values["max_working_load_n"]:
        validate.bad("min_working_load_n must be strictly less than max_working_load_n.")


def _check_material_gates(program, spec):
    if spec["salt_spray_hours"] < program["required_salt_spray_hours"]:
        raise ApiError("ERR_CORROSION_REQUIREMENT_UNMET",
                       "The material's salt-spray endurance is below the program floor.")
    if program["biocompatibility_required"] and not spec["biocompatible"]:
        raise ApiError("ERR_BIOCOMPATIBILITY_REQUIRED",
                       "The program requires a biocompatible material.")


def _apply_engineering(design):
    spec = store.material_specs[design["material_spec_id"]]
    program = store.programs[design["program_id"]]
    design.update(calc.engineering(design, spec, program))


# ---------------------------------------------------------------------------
# SpringDesign
# ---------------------------------------------------------------------------
@bp.post("/spring-designs")
def create_design():
    actor = auth.guard(DESIGN_ENGINEER)
    body = validate.body()
    program_id = validate.req_id(body, "program_id")
    material_spec_id = validate.req_id(body, "material_spec_id")
    values = {
        "part_number": validate.req_string(body, "part_number"),
        "form_type": validate.req_enum(body, "form_type", calc.FORM_TYPES),
        "end_type": validate.req_enum(body, "end_type", calc.END_TYPES),
        "wire_diameter_mm": validate.req_number(body, "wire_diameter_mm", gt=0),
        "outer_diameter_mm": validate.req_number(body, "outer_diameter_mm", gt=0),
        "free_length_mm": validate.req_number(body, "free_length_mm", gt=0),
        "active_coils": validate.req_number(body, "active_coils", minimum=1),
        "max_working_load_n": validate.req_number(body, "max_working_load_n", gt=0),
        "min_working_load_n": validate.req_number(body, "min_working_load_n",
                                                  minimum=0),
        "cycle_seconds_per_piece": validate.req_number(body,
                                                       "cycle_seconds_per_piece",
                                                       gt=0),
        "shot_peening_required": validate.opt_bool(body, "shot_peening_required",
                                                   False),
    }
    _check_geometry(values)

    program = find.program(program_id)
    spec = find.material_spec(material_spec_id)
    _check_material_gates(program, spec)

    row = store.base_row()
    row["program_id"] = program["id"]
    row["material_spec_id"] = spec["id"]
    row.update(values)
    row.update({
        "created_by_user_id": actor.user_id,
        "reviewed_by_user_id": None,
        "current_revision_no": 1,
        "superseded_revision_no": None,
        "release_status": "DRAFT",
    })
    row.update(calc.engineering(row, spec, program))
    store.designs[row["id"]] = row
    return envelope.created(store.public(row))


@bp.get("/spring-designs/<design_id>")
def read_design(design_id):
    actor = auth.guard(*(DESIGN_READERS + (CUSTOMER_REPRESENTATIVE,)))
    design = find.design(design_id)
    auth.own_program(actor, design["program_id"])
    return envelope.ok(store.public(design))


@bp.get("/spring-designs")
def list_designs():
    auth.guard(*DESIGN_READERS)
    program_id = validate.query_str("program_id")
    material_spec_id = validate.query_str("material_spec_id")
    release_status = validate.query_enum("release_status", calc.RELEASE_STATUSES)
    limit, offset = envelope.pagination()
    rows = store.by_seq(store.designs.values())
    if program_id is not None:
        rows = [r for r in rows if r["program_id"] == program_id]
    if material_spec_id is not None:
        rows = [r for r in rows if r["material_spec_id"] == material_spec_id]
    if release_status is not None:
        rows = [r for r in rows if r["release_status"] == release_status]
    return envelope.listed(rows, limit, offset)


@bp.post("/spring-designs/<design_id>/critical-characteristics")
def create_characteristic(design_id):
    auth.guard(DESIGN_ENGINEER)
    body = validate.body()
    char_code = validate.req_enum(body, "char_code", calc.CHAR_CODES)
    nominal = validate.req_number(body, "nominal_value")
    lsl = validate.req_number(body, "lsl")
    usl = validate.req_number(body, "usl")
    is_safety_critical = validate.opt_bool(body, "is_safety_critical", False)
    cpk_floor = validate.opt_number(body, "cpk_floor", default=1.333)
    if lsl >= nominal:
        validate.bad("lsl must be strictly less than nominal_value.")
    if usl <= nominal:
        validate.bad("usl must be strictly greater than nominal_value.")

    design = find.design(design_id)
    if design["release_status"] != "DRAFT":
        raise ApiError("ERR_DESIGN_INVALID_STATE",
                       "Characteristics may only be added while the design is DRAFT.")
    for existing in cascades.characteristics_of(design["id"]):
        if existing["char_code"] == char_code:
            raise ApiError("ERR_DUPLICATE_CHARACTERISTIC",
                           "char_code %s already exists on this design." % char_code)

    row = store.base_row(with_common=False)
    row.update({
        "design_id": design["id"],
        "char_code": char_code,
        "nominal_value": nominal,
        "lsl": lsl,
        "usl": usl,
        "is_safety_critical": is_safety_critical,
        "cpk_floor": cpk_floor,
    })
    store.characteristics[row["id"]] = row
    return envelope.created(store.public(row))


@bp.get("/spring-designs/<design_id>/critical-characteristics")
def list_characteristics(design_id):
    auth.guard(*DESIGN_READERS)
    limit, offset = envelope.pagination()
    design = find.design(design_id)
    rows = cascades.characteristics_of(design["id"])
    return envelope.listed(rows, limit, offset)


@bp.post("/spring-designs/<design_id>/submit-for-review")
def submit_design(design_id):
    auth.guard(DESIGN_ENGINEER)
    validate.body()
    design = find.design(design_id)
    if design["release_status"] != "DRAFT":
        raise ApiError("ERR_DESIGN_INVALID_STATE",
                       "Only a DRAFT design may be submitted for review.")
    if not cascades.characteristics_of(design["id"]):
        raise ApiError("ERR_CHARACTERISTIC_SET_EMPTY",
                       "The design has no critical characteristics on file.")
    design["release_status"] = "ENG_REVIEW"
    store.touch(design)
    return envelope.ok(store.public(design))


@bp.post("/spring-designs/<design_id>/review")
def review_design(design_id):
    actor = auth.guard(ENGINEERING_MANAGER)
    body = validate.body()
    decision = validate.req_enum(body, "decision", ("APPROVE_PROTOTYPE", "REJECT"))
    design = find.design(design_id)
    if design["release_status"] != "ENG_REVIEW":
        raise ApiError("ERR_DESIGN_INVALID_STATE",
                       "Only an ENG_REVIEW design may be decided.")
    if actor.user_id == design["created_by_user_id"]:
        raise ApiError("ERR_SELF_REVIEW_FORBIDDEN",
                       "The design's author may not review it.")
    program = store.programs[design["program_id"]]
    if decision == "APPROVE_PROTOTYPE":
        if design["fatigue_margin_ratio"] is None or \
                design["fatigue_margin_ratio"] < program["min_fatigue_margin"]:
            raise ApiError("ERR_FATIGUE_MARGIN_BELOW_FLOOR",
                           "The design's fatigue margin is below the program floor.")
        design["release_status"] = "PROTOTYPE_RELEASED"
    else:
        design["release_status"] = "REJECTED"
    design["reviewed_by_user_id"] = actor.user_id
    store.touch(design)
    cascades.refresh_posture(program)
    return envelope.ok(store.public(design))


@bp.post("/spring-designs/<design_id>/revisions")
def revise_design(design_id):
    actor = auth.guard(DESIGN_ENGINEER)
    body = validate.body()
    expected_version = validate.req_int(body, "expected_design_version")
    material_spec_id = validate.opt_id(body, "material_spec_id")
    patch = {}
    for name, kwargs in (("wire_diameter_mm", {"gt": 0}),
                         ("outer_diameter_mm", {"gt": 0}),
                         ("free_length_mm", {"gt": 0}),
                         ("active_coils", {"minimum": 1}),
                         ("max_working_load_n", {"gt": 0}),
                         ("min_working_load_n", {"minimum": 0}),
                         ("cycle_seconds_per_piece", {"gt": 0})):
        value = validate.opt_number(body, name, default=None, **kwargs)
        if value is not None:
            patch[name] = value
    if "shot_peening_required" in body and body["shot_peening_required"] is not None:
        patch["shot_peening_required"] = validate.req_bool(body,
                                                           "shot_peening_required")

    design = find.design(design_id)
    spec = find.material_spec(material_spec_id) if material_spec_id is not None \
        else store.material_specs[design["material_spec_id"]]

    if expected_version != design["version"]:
        raise ApiError("ERR_STALE_DESIGN_VERSION",
                       "expected_design_version does not match the design.")
    if design["release_status"] not in REVISABLE:
        raise ApiError("ERR_DESIGN_INVALID_STATE",
                       "A %s design cannot be revised." % design["release_status"])
    for submission in store.submissions.values():
        if submission["design_id"] == design["id"] and \
                submission["submission_status"] in LOCKING_SUBMISSION_STATUSES:
            raise ApiError("ERR_DESIGN_LOCKED",
                           "An in-flight or granted approval package freezes "
                           "this design.")

    merged = dict(design)
    merged.update(patch)
    _check_geometry(merged)
    program = store.programs[design["program_id"]]
    _check_material_gates(program, spec)

    design.update(patch)
    design["material_spec_id"] = spec["id"]
    design["superseded_revision_no"] = design["current_revision_no"]
    design["current_revision_no"] = design["current_revision_no"] + 1
    design["release_status"] = "DRAFT"
    design["reviewed_by_user_id"] = None
    design["created_by_user_id"] = actor.user_id
    design.update(calc.engineering(design, spec, program))
    store.touch(design)

    cascades.abort_scheduled_setups(design, free_coiler=True)
    cascades.refresh_posture(program)
    return envelope.ok(store.public(design))


@bp.post("/spring-designs/<design_id>/obsolete")
def obsolete_design(design_id):
    auth.guard(ENGINEERING_MANAGER)
    validate.body()
    design = find.design(design_id)
    if design["release_status"] not in RETIREABLE:
        raise ApiError("ERR_DESIGN_INVALID_STATE",
                       "A %s design cannot be retired." % design["release_status"])
    for run in store.runs.values():
        if run["design_id"] == design["id"] and \
                run["process_status"] in ("FAI_PENDING", "RUNNING"):
            raise ApiError("ERR_DESIGN_INVALID_STATE",
                           "A production run of this design is still open.")
    design["release_status"] = "OBSOLETE"
    store.touch(design)
    cascades.write_off_tooling(design)
    cascades.abort_scheduled_setups(design, free_coiler=False)
    cascades.refresh_posture_of_design(design)
    return envelope.ok(store.public(design))


@bp.get("/spring-designs/<design_id>/fatigue-analysis")
def design_fatigue_analysis(design_id):
    auth.guard(DESIGN_ENGINEER, ENGINEERING_MANAGER, QUALITY_INSPECTOR,
               PROGRAM_MANAGER, PLANT_ADMIN)
    design = find.design(design_id)
    return envelope.ok({
        "criterion_in_force": design["fatigue_criterion"],
        "fatigue_margin_goodman": design["_fatigue_margin_goodman"],
        "fatigue_margin_soderberg": design["_fatigue_margin_soderberg"],
        "stress_amplitude_mpa": design["stress_amplitude_mpa"],
        "mean_stress_mpa": design["mean_stress_mpa"],
        "endurance_limit_mpa": design["_endurance_limit_mpa"],
        "predicted_fatigue_life_cycles": design["predicted_fatigue_life_cycles"],
    })


# ---------------------------------------------------------------------------
# ToolingAsset
# ---------------------------------------------------------------------------
@bp.post("/tooling-assets")
def create_tooling():
    auth.guard(ENGINEERING_MANAGER)
    body = validate.body()
    design_id = validate.req_id(body, "design_id")
    tool_code = validate.req_string(body, "tool_code")
    cost = validate.req_int(body, "original_cost_cents", gt=0)

    design = find.design(design_id)
    find.unique_code(store.tooling_assets, "tool_code", tool_code)

    row = store.base_row()
    row.update({
        "design_id": design["id"],
        "tool_code": tool_code,
        "original_cost_cents": cost,
        "amortization_status": "PENDING",
        "amortization_basis_pieces": None,
        "amort_per_piece_cents": None,
        "recovered_cents": 0,
        "unamortized_cents": cost,
    })
    store.tooling_assets[row["id"]] = row
    return envelope.created(store.public(row))


@bp.get("/tooling-assets/<tooling_id>")
def read_tooling(tooling_id):
    auth.guard(*TOOLING_READERS)
    return envelope.ok(store.public(find.tooling(tooling_id)))


@bp.get("/tooling-assets")
def list_tooling():
    auth.guard(*TOOLING_READERS)
    design_id = validate.query_str("design_id")
    status = validate.query_enum("amortization_status", calc.AMORTIZATION_STATUSES)
    limit, offset = envelope.pagination()
    rows = store.by_seq(store.tooling_assets.values())
    if design_id is not None:
        rows = [r for r in rows if r["design_id"] == design_id]
    if status is not None:
        rows = [r for r in rows if r["amortization_status"] == status]
    return envelope.listed(rows, limit, offset)
