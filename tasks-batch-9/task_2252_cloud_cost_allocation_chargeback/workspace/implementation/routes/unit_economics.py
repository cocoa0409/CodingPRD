"""Unit economics drivers (PRD 3.9)."""
from flask import Blueprint

from db import base_fields, db, touch
from errors import fail
from middleware import authorize
from routes.common import lookup, optional_ref, serve, serve_list
from services import derived
from services.calc import unit_economics
from validation import body, req_enum, req_int, req_str

bp = Blueprint("unit_economics", __name__)

DRIVER_NAMES = ("ORDERS", "ACTIVE_USERS", "API_CALLS", "SHIPMENTS")
READERS = ("FinOpsAnalyst", "FinOpsController", "PlatformAdmin", "BusinessUnitOwner")


@bp.route("/finops/unit-economics-drivers", methods=["POST"])
@authorize("FinOpsAnalyst", "FinOpsController")
def register_driver():
    data = body()
    bu = optional_ref("business_units", req_str(data, "business_unit_id"))
    run = optional_ref("allocation_runs", req_str(data, "allocation_run_id"))
    driver_name = req_enum(data, "driver_name", DRIVER_NAMES)
    driver_volume = req_int(data, "driver_volume")

    if driver_volume <= 0:
        fail("ERR_DRIVER_VOLUME_INVALID", "driver_volume must be strictly positive.")

    driver = base_fields()
    driver.update(
        {
            "business_unit_id": bu["id"],
            "allocation_run_id": run["id"],
            "driver_name": driver_name,
            "driver_volume": driver_volume,
            "base_allocated_cents": 0,
            "provisional_cost_per_unit_cents": 0.00,
            "efficiency_tier": None,
            "platform_overhead_cents": 0,
            "final_cost_per_unit_cents": 0.00,
        }
    )
    db.unit_economics_drivers[driver["id"]] = driver
    return serve(driver, 201)


@bp.route("/finops/unit-economics-drivers", methods=["GET"])
@authorize(*READERS)
def list_drivers():
    return serve_list(
        db.unit_economics_drivers.values(),
        {
            "business_unit_id": "business_unit_id",
            "allocation_run_id": "allocation_run_id",
            "driver_name": "driver_name",
        },
    )


@bp.route("/finops/unit-economics-drivers/<driver_id>", methods=["GET"])
@authorize(*READERS)
def get_driver(driver_id):
    return serve(lookup("unit_economics_drivers", driver_id))


@bp.route("/finops/unit-economics-drivers/<driver_id>/compute", methods=["POST"])
@authorize("FinOpsAnalyst", "FinOpsController")
def compute_driver(driver_id):
    driver = lookup("unit_economics_drivers", driver_id)
    run = db.allocation_runs.get(driver["allocation_run_id"])
    if run is None or run["status"] not in ("PUBLISHED", "CLOSED"):
        fail(
            "ERR_RUN_STATE_INVALID",
            "Unit economics require a PUBLISHED or CLOSED allocation run.",
        )
    if driver["driver_volume"] <= 0:
        fail("ERR_DRIVER_VOLUME_INVALID", "driver_volume must be strictly positive.")

    base = derived.bu_line_total(run["id"], driver["business_unit_id"])
    driver["base_allocated_cents"] = base
    driver.update(unit_economics(base, driver["driver_volume"]))
    touch(driver)
    return serve(driver)
