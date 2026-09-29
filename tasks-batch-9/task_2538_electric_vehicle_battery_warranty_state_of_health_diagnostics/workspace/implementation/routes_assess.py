"""State-of-health assessments."""
from flask import Blueprint, request

import calc
import cascade
from common import (API_PREFIX, ApiError, D, R_TECH, READ_ROLES, auth, by_created,
                    db, get_body, invalid, must, fk, new_record, now, ok, ok_list,
                    opt_dec, page, pagination, present, pack_modules, req_enum,
                    req_int, req_int_list, req_str, rhu, touch, vehicle_assessments)

bp = Blueprint("assess", __name__, url_prefix=API_PREFIX)

VARIANTS = ("TELEMATICS_FLEET", "BENCH_CAPACITY_TEST")


def _positions(body, name, module_count):
    values = req_int_list(body, name)
    return values


@bp.route("/soh-assessments", methods=["POST"])
def create_assessment():
    auth((R_TECH,))
    body = get_body()
    vehicle_id = req_str(body, "vehicle_id")
    pack_id = req_str(body, "pack_id")
    technician_id = req_str(body, "technician_id")
    variant = req_enum(body, "variant", VARIANTS)
    expected_version = req_int(body, "expected_vehicle_version")
    bench = opt_dec(body, "bench_measured_capacity_kwh", 3, None)
    fault_positions = req_int_list(body, "module_fault_positions")
    degraded_positions = req_int_list(body, "module_degraded_positions")
    # priority 5 -- the conditional bench-capacity rule
    if variant == "BENCH_CAPACITY_TEST" and bench is None:
        raise ApiError("ERR_BENCH_CAPACITY_REQUIRED", 400,
                       "bench_measured_capacity_kwh is required for a bench assessment.")
    if variant == "TELEMATICS_FLEET" and bench is not None:
        raise ApiError("ERR_BENCH_CAPACITY_REQUIRED", 400,
                       "bench_measured_capacity_kwh must be absent for a fleet assessment.")
    # priority 7 -- body foreign keys in field-declaration order
    vehicle = fk("vehicles", vehicle_id)
    pack = fk("packs", pack_id)
    fk("technicians", technician_id)
    # priority 8 -- stale vehicle version
    if expected_version != vehicle["version"]:
        raise ApiError("ERR_STALE_VEHICLE_VERSION", 412,
                       "expected_vehicle_version does not match the vehicle's version.")
    # priority 36 -- the pack must be the one installed in the vehicle
    if vehicle["installed_pack_id"] != pack_id:
        raise ApiError("ERR_PACK_VEHICLE_MISMATCH", 422,
                       "pack_id is not the vehicle's installed pack.")
    # priority 58 -- module position integrity
    _check_positions(fault_positions, degraded_positions, pack["module_count"])

    program = db.programs[vehicle["warranty_program_id"]]
    # The declared module conditions are written through BEFORE any arithmetic.
    modules = pack_modules(pack_id)
    by_position = dict((m["position_index"], m) for m in modules)
    for position in fault_positions:
        module = by_position[position]
        if module["status"] != "FAULTED":
            module["status"] = "FAULTED"
            touch(module)
    for position in degraded_positions:
        module = by_position[position]
        if module["status"] != "DEGRADED":
            module["status"] = "DEGRADED"
            touch(module)
    cascade.refresh_pack_counters(pack)

    all_valid, fresh, window = calc.snapshot_window(vehicle, program)
    window_count = len(window)
    if window:
        assessed_odometer = window[0]["odometer_miles"]
        max_delta = window[0]["max_cell_delta_mv"]
    else:
        assessed_odometer = 0
        max_delta = 0
    faulted_after_write = calc.faulted_module_count(pack_id)
    basis = calc.nominal_basis(variant, pack, faulted_after_write)
    validity = calc.diagnostic_validity(variant, program, all_valid, fresh, window,
                                        basis, bench)
    if validity == "VALID":
        estimated = calc.estimated_capacity(variant, program, window, bench)
        retention = calc.retention_pct(estimated, basis)
    else:
        estimated = None
        retention = None
    months = calc.elapsed_months(vehicle["in_service_date"], now())
    position, applicable = calc.coverage_position(program, months, assessed_odometer)

    record = new_record()
    record.update({
        "vehicle_id": vehicle_id,
        "pack_id": pack_id,
        "technician_id": technician_id,
        "variant": variant,
        "bench_measured_capacity_kwh": bench,
        "module_fault_positions": list(fault_positions),
        "module_degraded_positions": list(degraded_positions),
        "window_snapshot_count": window_count,
        "nominal_basis_kwh": basis,
        "estimated_capacity_kwh": estimated,
        "retention_pct": retention,
        "diagnostic_validity": validity,
        "elapsed_months": months,
        "assessed_odometer_miles": assessed_odometer,
        "coverage_position": position,
        "applicable_min_retention_pct": applicable,
        "max_cell_delta_mv": max_delta,
        "qualifies_for_claim": calc.qualifies(validity, position, retention, applicable),
        "superseded": False,
    })
    for prior in vehicle_assessments(vehicle_id):
        if not prior["superseded"]:
            prior["superseded"] = True
            touch(prior)
    db.assessments[record["id"]] = record
    touch(vehicle)
    return ok(record, 201)


def _check_positions(fault_positions, degraded_positions, module_count):
    error = ApiError("ERR_MODULE_POSITION_INVALID", 422,
                     "Module positions must be distinct integers within 1..%d and the "
                     "faulted and degraded arrays must be disjoint." % module_count)
    for group in (fault_positions, degraded_positions):
        seen = set()
        for value in group:
            if value < 1 or value > module_count:
                raise error
            if value in seen:
                raise error
            seen.add(value)
    if set(fault_positions) & set(degraded_positions):
        raise error


@bp.route("/soh-assessments/<assessment_id>", methods=["GET"])
def get_assessment(assessment_id):
    auth(READ_ROLES)
    return ok(must("assessments", assessment_id))


@bp.route("/soh-assessments", methods=["GET"])
def list_assessments():
    auth(READ_ROLES)
    limit, offset = pagination()
    rows = by_created(list(db.assessments.values()))
    for field in ("vehicle_id", "pack_id", "technician_id", "variant", "diagnostic_validity"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    raw = request.args.get("superseded")
    if raw is not None and raw != "":
        lowered = raw.lower()
        if lowered in ("true", "1"):
            rows = [r for r in rows if r["superseded"]]
        elif lowered in ("false", "0"):
            rows = [r for r in rows if not r["superseded"]]
        else:
            raise invalid("superseded must be a boolean.")
    window, total = page(rows, limit, offset)
    return ok_list(window, limit, offset, total)
