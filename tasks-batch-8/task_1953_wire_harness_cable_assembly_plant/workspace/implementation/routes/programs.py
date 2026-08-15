"""Cut/strip/crimp machine programs (PRD 3.2)."""
from flask import Blueprint, request

from db import db
from errors import (raise_error, ERR_INVALID_REQUEST, ERR_DRAWING_NOT_RELEASED,
                    ERR_PROGRAM_NOT_DRAFT, ERR_STALE_PROGRAM_VERSION)
from middleware import authenticate, ALL_ROLES
from response import success_object
from services import (TERMINAL_TYPES, common_fields, touch,
                      compute_min_pull_force_n, ser_program, paginated)
from validate import (get_body, req_str, opt_str, req_int, opt_int, req_num,
                      opt_num, req_enum, opt_enum, require_path, require_fk)

bp = Blueprint("machine_programs", __name__)

PROCESS_ENGINEER = {"ProcessEngineer"}


def _validate_recipe_fields(body, partial=False):
    """Tier 1 for create (all required) and PATCH (only present fields)."""
    get = (lambda f, **kw: opt_int(body, f, **kw)) if partial else \
          (lambda f, **kw: req_int(body, f, **kw))
    gets = (lambda f: opt_str(body, f)) if partial else (lambda f: req_str(body, f))
    getn = (lambda f, **kw: opt_num(body, f, **kw)) if partial else \
           (lambda f, **kw: req_num(body, f, **kw))
    gete = (lambda f, a: opt_enum(body, f, a)) if partial else \
           (lambda f, a: req_enum(body, f, a))
    values = {
        "wire_gauge_awg": get("wire_gauge_awg", minimum=12, maximum=26),
        "wire_type": gets("wire_type"),
        "cut_length_mm": getn("cut_length_mm", exclusive_min=0),
        "strip_length_mm": getn("strip_length_mm", exclusive_min=0),
        "terminal_mpn": gets("terminal_mpn"),
        "terminal_type": gete("terminal_type", TERMINAL_TYPES),
    }
    return values


@bp.route("/plant/machine-programs", methods=["POST"])
def create_program():
    body = get_body()
    # Tier 1
    program_code = req_str(body, "program_code")
    drawing_id = req_str(body, "drawing_id")
    applicator_id = req_str(body, "applicator_id")
    recipe = _validate_recipe_fields(body, partial=False)
    # Tiers 2-3
    authenticate(PROCESS_ENGINEER)
    # Tier 4, left-to-right
    drawing = require_fk("drawings", drawing_id, "drawing_id")
    require_fk("applicators", applicator_id, "applicator_id")
    # Tier 6
    if drawing["status"] != "RELEASED":
        raise_error(ERR_DRAWING_NOT_RELEASED,
                    "machine programs require a RELEASED drawing")
    for p in db["machine_programs"].values():
        if p["program_code"] == program_code:
            raise_error(ERR_INVALID_REQUEST, f"duplicate program_code: {program_code}")

    program = common_fields()
    program.update({
        "program_code": program_code,
        "drawing_id": drawing["id"],
        "applicator_id": applicator_id,
        "wire_gauge_awg": recipe["wire_gauge_awg"],
        "wire_type": recipe["wire_type"],
        "cut_length_mm": recipe["cut_length_mm"],
        "strip_length_mm": recipe["strip_length_mm"],
        "terminal_mpn": recipe["terminal_mpn"],
        "terminal_type": recipe["terminal_type"],
        "min_pull_force_n": compute_min_pull_force_n(
            recipe["wire_gauge_awg"], recipe["terminal_type"],
            drawing["workmanship_class"]),
        "status": "DRAFT",
    })
    db["machine_programs"][program["id"]] = program
    return success_object(ser_program(program), 201)


@bp.route("/plant/machine-programs/<pid>", methods=["GET"])
def get_program(pid):
    authenticate(ALL_ROLES)
    program = require_path("machine_programs", pid)
    return success_object(ser_program(program), 200)


@bp.route("/plant/machine-programs", methods=["GET"])
def list_programs():
    authenticate(ALL_ROLES)
    items = list(db["machine_programs"].values())
    drawing_id = request.args.get("drawing_id")
    if drawing_id is not None:
        items = [p for p in items if p["drawing_id"] == drawing_id]
    applicator_id = request.args.get("applicator_id")
    if applicator_id is not None:
        items = [p for p in items if p["applicator_id"] == applicator_id]
    return paginated(items, ser_program)


@bp.route("/plant/machine-programs/<pid>", methods=["PATCH"])
def patch_program(pid):
    body = get_body()
    # Tier 1: OCC field is a non-optional input (PRD 2.7); recipe fields optional.
    expected_version = req_int(body, "expected_machine_program_version")
    recipe = _validate_recipe_fields(body, partial=True)
    new_applicator_id = opt_str(body, "applicator_id")
    # Tiers 2-3
    authenticate(PROCESS_ENGINEER)
    # Tier 4
    program = require_path("machine_programs", pid)
    if new_applicator_id is not None:
        require_fk("applicators", new_applicator_id, "applicator_id")
    # Tier 5: OCC precedes the state check (PRD 2.6 example).
    if expected_version != program["version"]:
        raise_error(ERR_STALE_PROGRAM_VERSION,
                    "expected_machine_program_version does not match current version")
    # Tier 6
    if program["status"] != "DRAFT":
        raise_error(ERR_PROGRAM_NOT_DRAFT, "only a DRAFT program may be edited")

    for field, value in recipe.items():
        if value is not None:
            program[field] = value
    if new_applicator_id is not None:
        program["applicator_id"] = new_applicator_id
    drawing = db["drawings"][program["drawing_id"]]
    program["min_pull_force_n"] = compute_min_pull_force_n(
        program["wire_gauge_awg"], program["terminal_type"],
        drawing["workmanship_class"])
    touch(program)
    return success_object(ser_program(program), 200)
