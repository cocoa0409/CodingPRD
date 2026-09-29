"""Steps / ramp accessory packages and their ADA compliance scoring."""
from flask import Blueprint

import calc
import serializers as S
import services
from db import store, new_record, touch, ordered
from errors import ApiError
from guard import auth, lookup, get_body, resolve_fk, v_string, v_int, v_number, v_enum
from response import success, created, paginate

bp = Blueprint("accessories", __name__)

PACKAGE_TYPES = ("STEPS", "RAMP_ADA", "COMBO")


@bp.post("/accessory-packages")
def create_package():
    auth("LeasingAgent")
    body = get_body()

    # rank 4
    lease = resolve_fk(body, "lease_id", store.leases, "ERR_LEASE_NOT_FOUND")

    # rank 5
    lease_id = v_string(body, "lease_id")
    package_type = v_enum(body, "package_type", PACKAGE_TYPES)
    ramp_run_ft = v_number(body, "ramp_run_ft", required=False, default=0, minimum=0)
    landing_count = v_int(body, "landing_count", required=False, default=0, minimum=0)
    step_count = v_int(body, "step_count", required=False, default=0, minimum=0)

    # rank 17 -- one accessory package per lease
    if services.packages_of_lease(lease_id):
        raise ApiError("ERR_ACCESSORY_ALREADY_ATTACHED", "This lease already carries a package.")

    unit = store.units[lease["unit_id"]]
    spec = store.building_specs[unit["building_spec_id"]]
    jurisdiction = store.jurisdictions[lease["jurisdiction_id"]]

    rate = calc.accessory_package_rate(package_type, ramp_run_ft, landing_count)
    compliance = calc.ada_ramp_compliance(
        package_type, ramp_run_ft, landing_count,
        spec["floor_height_in"], jurisdiction["min_ramp_run_ratio"])

    record = new_record(
        lease_id=lease_id,
        package_type=package_type,
        ramp_run_ft=ramp_run_ft,
        landing_count=landing_count,
        step_count=step_count,
        monthly_accessory_rate_cents=rate,
        compliance_status=compliance,
    )
    store.accessory_packages[record["id"]] = record

    lease["monthly_accessory_rate_cents"] = rate
    lease["quoted_total_cents"] = calc.quoted_projection(
        lease["mobilization_fee_cents"], lease["monthly_base_rate_cents"],
        lease["monthly_accessory_rate_cents"], lease["term_months"])
    touch(lease)

    return created(S.accessory_package(record))


@bp.get("/accessory-packages/<package_id>")
def read_package(package_id):
    auth("LeasingAgent", "FleetAdmin")
    record = lookup(store.accessory_packages, package_id, "ERR_ACCESSORY_PACKAGE_NOT_FOUND")
    return success(S.accessory_package(record))


@bp.get("/accessory-packages")
def list_packages():
    auth("LeasingAgent", "FleetAdmin")
    records = ordered(store.accessory_packages.values())
    records = services.apply_filters(records, {"lease_id": "lease_id"})
    return paginate(records, S.accessory_package)
