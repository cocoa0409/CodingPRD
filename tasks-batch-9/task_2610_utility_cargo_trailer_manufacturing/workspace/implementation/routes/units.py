"""Build records, dimensional control and regulatory systems stages (PRD 3.2-3.4)."""
from flask import Blueprint

import errors
import lookups
import validators as v
from db import (db, new_id, public, public_list, stamp_immutable, stamp_new,
                touch)
from middleware import ALL_ROLES, actor, endpoint
from response import created, listing, ok
from services import calc, rollups

bp = Blueprint("units", __name__)

BUILD_STATUSES = ("PLANNED", "BUILD_HOLD", "JIG_RESERVED", "FRAME_REWORK", "FRAME_WELDED",
                  "SYSTEMS_INSTALLED", "ROAD_TEST_PENDING", "SYSTEMS_REWORK",
                  "ROAD_TEST_PASSED", "LABELED", "RELEASED_TO_STOCK", "ALLOCATED",
                  "SHIPPED", "SCRAPPED")
SERIAL_MIN = 6
SERIAL_MAX = 20
STAGES = ("LIGHTING", "BRAKE_AND_AXLE")


@bp.route("/trailer-units", methods=["POST"])
@endpoint(["WeldSupervisor"])
def create_unit():
    data = v.body()
    model = lookups.model_or_404(v.req_id(data, "model_id"))
    serial_number = v.req_code(data, "serial_number", SERIAL_MIN, SERIAL_MAX)
    planned_raw, _planned_dt = v.opt_dt(data, "planned_start_date")

    if model["certification_status"] not in ("DRAFT", "IN_ENGINEERING_REVIEW", "CERTIFIED"):
        raise errors.ApiError("ERR_MODEL_NOT_BUILDABLE", 409,
                              "A model in certification_status %s may not receive new build records"
                              % model["certification_status"])
    lookups.unique_or_409(db.units, "serial_number", serial_number)

    row = {
        "id": new_id(),
        "serial_number": serial_number,
        "model_id": model["id"],
        "dealer_order_id": None,
        "planned_start_date": planned_raw,
        "model_version_pinned": None,
        "gvwr_lbs": None,
        "curb_weight_lbs": None,
        "payload_capacity_lbs": None,
        "build_status": "PLANNED",
        "compliance_status": "NOT_VERIFIED",
        "installed_braked_axle_count": None,
        "breakaway_kit_installed": False,
        "clearance_lamp_count": None,
        "frame_fail_count": 0,
        "rework_cycle_count": 0,
        "released_to_stock_at": None,
        "warranty_start_date": None,
        "vin": None,
        "_released_to_stock_dt": None,
        "_warranty_start_dt": None,
    }
    stamp_new(row)
    db.units[row["id"]] = row
    rollups.recompute_model_active_unit_count(model)
    return created(public(row))


@bp.route("/trailer-units/<unit_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_unit(unit_id):
    return ok(public(lookups.unit_or_404(unit_id)))


@bp.route("/trailer-units", methods=["GET"])
@endpoint(["PlantEngineer", "CertificationOfficer", "WeldSupervisor", "QualityInspector",
           "AssemblyTech", "SalesAdmin"])
def list_units():
    build_status = v.query_enum("build_status", BUILD_STATUSES)
    model_id = v.request_arg("model_id")
    dealer_order_id = v.request_arg("dealer_order_id")
    limit, offset = v.pagination()
    rows = list(db.units.values())
    if model_id is not None:
        rows = [r for r in rows if r["model_id"] == model_id]
    if dealer_order_id is not None:
        rows = [r for r in rows if r["dealer_order_id"] == dealer_order_id]
    if build_status is not None:
        rows = [r for r in rows if r["build_status"] == build_status]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    return listing(public_list(rows[offset:offset + limit]), limit, offset, total)


def _active_reservation(unit_id):
    """The unit's live jig window: prefer RESERVED, else the CONSUMED one."""
    rows = sorted(rollups.reservations_of_unit(unit_id), key=lambda r: (r["created_at"], r["_seq"]))
    for row in rows:
        if row["status"] == "RESERVED":
            return row
    for row in reversed(rows):
        if row["status"] == "CONSUMED":
            return row
    return None


@bp.route("/trailer-units/<unit_id>/frame-inspections", methods=["POST"])
@endpoint(["WeldSupervisor"])
def create_frame_inspection(unit_id):
    unit = lookups.unit_or_404(unit_id)
    data = v.body()
    measured_length = v.req_num(data, "measured_length_mm")
    measured_width = v.req_num(data, "measured_width_mm")
    diagonal_a = v.req_num(data, "diagonal_a_mm")
    diagonal_b = v.req_num(data, "diagonal_b_mm")
    critical = v.req_int(data, "critical_weld_defect_count", minimum=0)
    non_critical = v.req_int(data, "non_critical_weld_defect_count", minimum=0)

    if unit["build_status"] not in ("JIG_RESERVED", "FRAME_REWORK"):
        raise errors.ApiError("ERR_UNIT_BUILD_STATE_INVALID", 409,
                              "A trailer in build_status %s may not be inspected"
                              % unit["build_status"])

    model = db.models.get(unit["model_id"])
    verdict = calc.frame_verdict(model, measured_length, measured_width, diagonal_a,
                                 diagonal_b, critical, non_critical)
    row = {
        "id": new_id(),
        "unit_id": unit["id"],
        "inspection_seq": len(rollups.inspections_of_unit(unit["id"])) + 1,
        "measured_length_mm": calc.num(calc.dec(measured_length)),
        "measured_width_mm": calc.num(calc.dec(measured_width)),
        "diagonal_a_mm": calc.num(calc.dec(diagonal_a)),
        "diagonal_b_mm": calc.num(calc.dec(diagonal_b)),
        "length_deviation_mm": verdict["length_deviation_mm"],
        "width_deviation_mm": verdict["width_deviation_mm"],
        "max_deviation_mm": verdict["max_deviation_mm"],
        "squareness_delta_mm": verdict["squareness_delta_mm"],
        "critical_weld_defect_count": critical,
        "non_critical_weld_defect_count": non_critical,
        "result": verdict["result"],
        "failure_reasons": verdict["failure_reasons"],
        "inspector_user_id": actor(),
    }
    stamp_immutable(row)
    db.inspections[row["id"]] = row

    reservation = _active_reservation(unit["id"])
    if verdict["result"] == "PASS":
        unit["build_status"] = "FRAME_WELDED"
        touch(unit)
        # A consumed window keeps occupying the jig: minutes are NOT refunded.
        if reservation is not None and reservation["status"] == "RESERVED":
            reservation["status"] = "CONSUMED"
            touch(reservation)
    else:
        fails = rollups.recompute_frame_fail_count(unit)
        if fails >= calc.FRAME_SCRAP_THRESHOLD:
            unit["build_status"] = "SCRAPPED"
            touch(unit)
            if reservation is not None and reservation["status"] in ("RESERVED", "CONSUMED"):
                reservation["status"] = "RELEASED"
                touch(reservation)
                rollups.recompute_jig_minutes(db.jigs.get(reservation["jig_id"]))
            rollups.recompute_model_active_unit_count(model)
        else:
            unit["build_status"] = "FRAME_REWORK"
            touch(unit)
    return created(public(row))


@bp.route("/trailer-units/<unit_id>/frame-inspections", methods=["GET"])
@endpoint(["WeldSupervisor", "CertificationOfficer", "PlantEngineer", "QualityInspector"])
def list_frame_inspections(unit_id):
    unit = lookups.unit_or_404(unit_id)
    limit, offset = v.pagination()
    rows = sorted(rollups.inspections_of_unit(unit["id"]), key=lambda r: r["inspection_seq"])
    total = len(rows)
    return listing(public_list(rows[offset:offset + limit]), limit, offset, total)


@bp.route("/trailer-units/<unit_id>/systems-install", methods=["POST"])
@endpoint(["AssemblyTech"])
def systems_install(unit_id):
    unit = lookups.unit_or_404(unit_id)
    data = v.body()
    stage = v.req_enum(data, "stage", STAGES)
    if stage == "LIGHTING":
        stop_tail_turn = v.req_int(data, "stop_tail_turn_lamp_count", minimum=0)
        clearance = v.req_int(data, "clearance_lamp_count", minimum=0)
        side_marker = v.req_int(data, "side_marker_lamp_count", minimum=0)
        license_plate = v.req_int(data, "license_plate_lamp_count", minimum=0)
        reflex = v.req_int(data, "reflex_reflector_count", minimum=0)
    else:
        braked_axles = v.req_int(data, "installed_braked_axle_count", minimum=0)
        breakaway = v.req_bool(data, "breakaway_kit_installed")

    if unit["build_status"] not in ("FRAME_WELDED", "SYSTEMS_REWORK"):
        raise errors.ApiError("ERR_UNIT_BUILD_STATE_INVALID", 409,
                              "A trailer in build_status %s may not record a systems stage"
                              % unit["build_status"])

    compliance = unit["compliance_status"]
    if stage == "LIGHTING":
        if compliance not in ("NOT_VERIFIED", "NON_COMPLIANT"):
            raise errors.ApiError("ERR_COMPLIANCE_STAGE_OUT_OF_ORDER", 409,
                                  "Stage LIGHTING requires compliance_status NOT_VERIFIED or "
                                  "NON_COMPLIANT, found %s" % compliance)
    else:
        if compliance != "LIGHTING_VERIFIED":
            raise errors.ApiError("ERR_COMPLIANCE_STAGE_OUT_OF_ORDER", 409,
                                  "Stage BRAKE_AND_AXLE requires compliance_status "
                                  "LIGHTING_VERIFIED, found %s" % compliance)

    model = db.models.get(unit["model_id"])
    if stage == "LIGHTING":
        if not calc.lighting_ok(model, stop_tail_turn, clearance, side_marker,
                                license_plate, reflex):
            raise errors.ApiError("ERR_LIGHTING_NOT_COMPLIANT", 422,
                                  "The installed lamp and reflector set does not satisfy the "
                                  "federal lighting requirement for this trailer")
        unit["clearance_lamp_count"] = clearance
        unit["compliance_status"] = "LIGHTING_VERIFIED"
        touch(unit)
    else:
        if not calc.brake_ok(model, unit.get("gvwr_lbs"), braked_axles, breakaway):
            raise errors.ApiError("ERR_BRAKE_REQUIREMENT_UNMET", 422,
                                  "The installed brake and axle configuration does not satisfy "
                                  "the braking requirement for a %s lb trailer"
                                  % unit.get("gvwr_lbs"))
        unit["installed_braked_axle_count"] = braked_axles
        unit["breakaway_kit_installed"] = breakaway
        unit["compliance_status"] = "FULLY_COMPLIANT"
        unit["build_status"] = "SYSTEMS_INSTALLED"
        touch(unit)
    return ok(public(unit))


@bp.route("/trailer-units/<unit_id>/jig-reservations", methods=["GET"])
@endpoint(["WeldSupervisor", "PlantEngineer"])
def list_unit_reservations(unit_id):
    unit = lookups.unit_or_404(unit_id)
    limit, offset = v.pagination()
    rows = sorted(rollups.reservations_of_unit(unit["id"]),
                  key=lambda r: (r["window_start_at"], r["created_at"], r["_seq"]))
    total = len(rows)
    return listing(public_list(rows[offset:offset + limit]), limit, offset, total)


@bp.route("/trailer-units/<unit_id>/road-tests", methods=["GET"])
@endpoint(["QualityInspector", "AssemblyTech", "CertificationOfficer", "PlantEngineer"])
def list_unit_road_tests(unit_id):
    unit = lookups.unit_or_404(unit_id)
    limit, offset = v.pagination()
    rows = sorted(rollups.road_tests_of_unit(unit["id"]),
                  key=lambda r: (r["window_start_at"], r["created_at"], r["_seq"]))
    total = len(rows)
    return listing(public_list(rows[offset:offset + limit]), limit, offset, total)
