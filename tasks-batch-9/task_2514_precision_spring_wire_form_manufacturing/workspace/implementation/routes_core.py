"""Customer programs, material specifications and the logical clock."""

from flask import Blueprint, request

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

bp = Blueprint("core", __name__)

PLANT_READERS = (PROGRAM_MANAGER, DESIGN_ENGINEER, ENGINEERING_MANAGER,
                 PROCESS_TECHNICIAN, QUALITY_INSPECTOR, PLANT_ADMIN)


# ---------------------------------------------------------------------------
# CustomerProgram
# ---------------------------------------------------------------------------
@bp.post("/customer-programs")
def create_program():
    auth.guard(PROGRAM_MANAGER)
    body = validate.body()
    program_code = validate.req_string(body, "program_code", min_len=3, max_len=40)
    customer_name = validate.req_string(body, "customer_name")
    application_class = validate.req_enum(body, "application_class",
                                          calc.APPLICATION_CLASSES)
    ppap_level = validate.req_int(body, "ppap_level", minimum=1, maximum=5)
    committed_pieces = validate.req_int(body, "committed_pieces", gt=0)
    minimum_order_quantity = validate.req_int(body, "minimum_order_quantity", gt=0)
    salt_spray = validate.opt_int(body, "required_salt_spray_hours", default=0,
                                 minimum=0)
    biocompatibility_required = validate.opt_bool(body, "biocompatibility_required",
                                                  False)
    min_fatigue_margin = validate.opt_number(body, "min_fatigue_margin", default=1.000)
    required_ppk = validate.opt_number(body, "required_ppk", default=1.000)
    amortization_method = validate.req_enum(body, "amortization_method",
                                            calc.AMORTIZATION_METHODS)

    find.unique_code(store.programs, "program_code", program_code)

    row = store.base_row()
    row.update({
        "program_code": program_code,
        "customer_name": customer_name,
        "application_class": application_class,
        "ppap_level": ppap_level,
        "committed_pieces": committed_pieces,
        "minimum_order_quantity": minimum_order_quantity,
        "required_salt_spray_hours": salt_spray,
        "biocompatibility_required": biocompatibility_required,
        "min_fatigue_margin": min_fatigue_margin,
        "required_ppk": required_ppk,
        "amortization_method": amortization_method,
        "open_commitment_pieces": committed_pieces,
        "allocated_pieces": 0,
        "shipped_pieces": 0,
        "quarantined_lot_count": 0,
        "delivery_posture": "BLOCKED",
        "quoted_qty": None,
        "quoted_pre_discount_subtotal_cents": None,
        "quoted_volume_discount_pct": None,
        "quoted_tooling_amort_per_piece_cents": None,
        "quoted_unit_price_cents": None,
        "quoted_total_cents": None,
        "quote_frozen": False,
        "_quoted_design_id": None,
    })
    row["delivery_posture"] = cascades.derive_posture(row)
    store.programs[row["id"]] = row
    return envelope.created(store.public(row))


@bp.get("/customer-programs/<program_id>")
def read_program(program_id):
    actor = auth.guard(*(PLANT_READERS + (CUSTOMER_REPRESENTATIVE,)))
    auth.own_program(actor, program_id)
    return envelope.ok(store.public(find.program(program_id)))


@bp.get("/customer-programs")
def list_programs():
    auth.guard(*PLANT_READERS)
    application_class = validate.query_enum("application_class",
                                            calc.APPLICATION_CLASSES)
    posture = validate.query_enum("delivery_posture", calc.DELIVERY_POSTURES)
    limit, offset = envelope.pagination()
    rows = store.by_seq(store.programs.values())
    if application_class is not None:
        rows = [r for r in rows if r["application_class"] == application_class]
    if posture is not None:
        rows = [r for r in rows if r["delivery_posture"] == posture]
    return envelope.listed(rows, limit, offset)


@bp.post("/customer-programs/<program_id>/quote")
def quote_program(program_id):
    auth.guard(PROGRAM_MANAGER)
    body = validate.body()
    design_id = validate.req_id(body, "design_id")
    quoted_qty = validate.req_int(body, "quoted_qty", gt=0)
    expected_version = validate.req_int(body, "expected_program_version")

    program = find.program(program_id)
    design = find.design(design_id)
    if expected_version != program["version"]:
        raise ApiError("ERR_STALE_PROGRAM_VERSION",
                       "expected_program_version does not match the program.")
    if program["quote_frozen"]:
        raise ApiError("ERR_QUOTE_FROZEN", "The program's quote is frozen.")
    if design["program_id"] != program["id"]:
        raise ApiError("ERR_PROGRAM_DESIGN_MISMATCH",
                       "The design belongs to a different program.")

    spec = store.material_specs.get(design["material_spec_id"])
    tooling = cascades.newest_tooling(design["id"])
    program.update(calc.quote(design, spec, tooling, quoted_qty))
    program["_quoted_design_id"] = design["id"]
    store.touch(program)
    return envelope.ok(store.public(program))


@bp.get("/customer-programs/<program_id>/tooling-amortization")
def program_tooling_amortization(program_id):
    actor = auth.guard(PROGRAM_MANAGER, ENGINEERING_MANAGER, PLANT_ADMIN,
                       CUSTOMER_REPRESENTATIVE)
    auth.own_program(actor, program_id)
    piece_count = _piece_count_input()
    program = find.program(program_id)

    design_id = program.get("_quoted_design_id")
    tooling = cascades.newest_tooling(design_id) if design_id else None
    open_pieces = program["open_commitment_pieces"]
    if tooling is None:
        data = {
            "amortization_method": program["amortization_method"],
            "tooling_asset_id": None,
            "original_cost_cents": None,
            "recovered_cents": None,
            "unamortized_cents": None,
            "open_commitment_pieces": open_pieces,
            "forecast_basis_recovery_cents": 0,
            "actual_basis_recovery_cents": 0,
        }
        return envelope.ok(data)

    per_piece = tooling.get("amort_per_piece_cents")
    if per_piece is None:
        per_piece = calc.amort_per_piece(tooling["original_cost_cents"],
                                        program["committed_pieces"])
    forecast = calc.forecast_recovery(piece_count, per_piece,
                                      tooling["unamortized_cents"])
    actual = calc.actual_recovery(piece_count, tooling["unamortized_cents"],
                                  open_pieces)
    return envelope.ok({
        "amortization_method": program["amortization_method"],
        "tooling_asset_id": tooling["id"],
        "original_cost_cents": tooling["original_cost_cents"],
        "recovered_cents": tooling["recovered_cents"],
        "unamortized_cents": tooling["unamortized_cents"],
        "open_commitment_pieces": open_pieces,
        "forecast_basis_recovery_cents": forecast,
        "actual_basis_recovery_cents": actual,
    })


def _piece_count_input():
    raw = request.args.get("piece_count")
    if raw is not None:
        text = raw.strip()
        if not text.isdigit() or int(text) <= 0:
            validate.bad("piece_count must be an integer greater than zero.")
        return int(text)
    body = validate.body()
    return validate.req_int(body, "piece_count", gt=0)


# ---------------------------------------------------------------------------
# MaterialSpec
# ---------------------------------------------------------------------------
SPEC_READERS = (DESIGN_ENGINEER, ENGINEERING_MANAGER, PROCESS_TECHNICIAN,
                QUALITY_INSPECTOR, PROGRAM_MANAGER, PLANT_ADMIN)


@bp.post("/material-specs")
def create_material_spec():
    auth.guard(DESIGN_ENGINEER)
    body = validate.body()
    spec_code = validate.req_string(body, "spec_code")
    wire_material = validate.req_enum(body, "wire_material", calc.WIRE_MATERIALS)
    tensile = validate.req_number(body, "tensile_grade_mpa", gt=0)
    shear = validate.req_number(body, "shear_modulus_gpa", gt=0)
    elastic = validate.req_number(body, "elastic_modulus_gpa", gt=0)
    density = validate.req_number(body, "density_kg_per_m3", gt=0)
    coating = validate.req_enum(body, "coating", calc.COATINGS)
    salt_spray = validate.req_int(body, "salt_spray_hours", minimum=0)
    biocompatible = validate.opt_bool(body, "biocompatible", False)
    cost = validate.req_int(body, "cost_per_kg_cents", gt=0)

    find.unique_code(store.material_specs, "spec_code", spec_code)

    row = store.base_row(with_common=False)
    row.update({
        "spec_code": spec_code,
        "wire_material": wire_material,
        "tensile_grade_mpa": tensile,
        "shear_modulus_gpa": shear,
        "elastic_modulus_gpa": elastic,
        "density_kg_per_m3": density,
        "coating": coating,
        "salt_spray_hours": salt_spray,
        "biocompatible": biocompatible,
        "cost_per_kg_cents": cost,
    })
    store.material_specs[row["id"]] = row
    return envelope.created(store.public(row))


@bp.get("/material-specs/<spec_id>")
def read_material_spec(spec_id):
    auth.guard(*SPEC_READERS)
    return envelope.ok(store.public(find.material_spec(spec_id)))


@bp.get("/material-specs")
def list_material_specs():
    auth.guard(*SPEC_READERS)
    wire_material = validate.query_enum("wire_material", calc.WIRE_MATERIALS)
    limit, offset = envelope.pagination()
    rows = store.by_seq(store.material_specs.values())
    if wire_material is not None:
        rows = [r for r in rows if r["wire_material"] == wire_material]
    return envelope.listed(rows, limit, offset)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    auth.guard(PLANT_ADMIN)
    body = validate.body()
    parsed, _raw = validate.req_datetime(body, "to_iso8601")
    if parsed < store.clock_now():
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC",
                       "The logical clock may only move forward.")
    store.clock_set(parsed)
    return envelope.ok({})
