"""Custom options and the unit weight budget (PRD 3.5)."""
from flask import Blueprint

import errors
import lookups
import validators as v
from db import db, new_id, public, public_list, stamp_new, touch
from middleware import endpoint
from response import created, listing, ok
from services import calc, rollups

bp = Blueprint("options", __name__)

OPTION_CODES = ("REAR_RAMP_GATE", "SIDE_CABINET_PKG", "SPECIALTY_FLOORING",
                "SPARE_TIRE_CARRIER", "E_TRACK_KIT")
OPTION_BUILD_STATES = ("FRAME_WELDED", "SYSTEMS_INSTALLED", "SYSTEMS_REWORK",
                       "ROAD_TEST_PENDING", "ROAD_TEST_PASSED", "LABELED")
READ_ROLES = ["AssemblyTech", "CertificationOfficer", "SalesAdmin", "PlantEngineer"]


@bp.route("/trailer-units/<unit_id>/option-installs", methods=["POST"])
@endpoint(["AssemblyTech"])
def create_option_install(unit_id):
    unit = lookups.unit_or_404(unit_id)
    data = v.body()
    option_code = v.req_enum(data, "option_code", OPTION_CODES)
    quantity = v.req_int(data, "quantity", minimum=1)
    unit_weight = v.req_int(data, "unit_weight_lbs", minimum=0)
    unit_price = v.req_int(data, "unit_price_cents", minimum=0)
    labor_hours = v.req_num(data, "labor_hours", minimum=0)

    if unit["build_status"] not in OPTION_BUILD_STATES:
        raise errors.ApiError("ERR_UNIT_BUILD_STATE_INVALID", 409,
                              "A trailer in build_status %s may not be charged an option"
                              % unit["build_status"])

    total_weight = quantity * unit_weight
    if unit.get("gvwr_lbs") is not None:
        prospective = unit["payload_capacity_lbs"] - total_weight
        if prospective < calc.MIN_PAYLOAD_CAPACITY_LBS:
            raise errors.ApiError("ERR_PAYLOAD_CAPACITY_EXCEEDED", 422,
                                  "Charging %s lb of options would drive payload_capacity_lbs "
                                  "to %s" % (total_weight, prospective))

    row = {
        "id": new_id(),
        "unit_id": unit["id"],
        "option_code": option_code,
        "quantity": quantity,
        "unit_weight_lbs": unit_weight,
        "unit_price_cents": unit_price,
        "labor_hours": calc.num(calc.dec(labor_hours)),
        "total_weight_lbs": total_weight,
        "total_price_cents": quantity * unit_price,
        "status": "PENDING",
    }
    stamp_new(row)
    db.options[row["id"]] = row
    rollups.recompute_unit_weights(unit)
    return created(public(row))


@bp.route("/option-installs/<option_id>/completion", methods=["POST"])
@endpoint(["AssemblyTech"])
def complete_option_install(option_id):
    line = lookups.option_or_404(option_id)
    data = v.body()
    note = v.opt_str(data, "signoff_note", max_len=500)

    if line["status"] != "PENDING":
        raise errors.ApiError("ERR_OPTION_NOT_REMOVABLE", 409,
                              "An option install in status %s may not be signed off"
                              % line["status"])
    line["status"] = "COMPLETED"
    if note is not None:
        line["signoff_note"] = note
    touch(line)
    rollups.maybe_release_to_stock(db.units.get(line["unit_id"]))
    return ok(public(line))


@bp.route("/option-installs/<option_id>", methods=["DELETE"])
@endpoint(["AssemblyTech"])
def remove_option_install(option_id):
    line = lookups.option_or_404(option_id)
    data = v.body()
    reason = v.opt_str(data, "removal_reason", max_len=500)

    if line["status"] != "PENDING":
        raise errors.ApiError("ERR_OPTION_NOT_REMOVABLE", 409,
                              "An option install in status %s may not be removed"
                              % line["status"])
    line["status"] = "REMOVED"
    if reason is not None:
        line["removal_reason"] = reason
    touch(line)
    rollups.recompute_unit_weights(db.units.get(line["unit_id"]))
    rollups.maybe_release_to_stock(db.units.get(line["unit_id"]))
    return ok(public(line))


@bp.route("/option-installs/<option_id>", methods=["GET"])
@endpoint(READ_ROLES)
def get_option_install(option_id):
    return ok(public(lookups.option_or_404(option_id)))


@bp.route("/trailer-units/<unit_id>/option-installs", methods=["GET"])
@endpoint(READ_ROLES)
def list_option_installs(unit_id):
    unit = lookups.unit_or_404(unit_id)
    include_removed = v.query_flag("include_removed", False)
    limit, offset = v.pagination()
    rows = sorted(rollups.options_of_unit(unit["id"]),
                  key=lambda r: (r["created_at"], r["_seq"]))
    if not include_removed:
        rows = [r for r in rows if r["status"] != "REMOVED"]
    total = len(rows)
    return listing(public_list(rows[offset:offset + limit]), limit, offset, total)
