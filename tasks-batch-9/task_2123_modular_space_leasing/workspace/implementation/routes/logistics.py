"""Logistics jobs: booking, dispatch, completion and abort."""
from flask import Blueprint

import calc
import serializers as S
import services
from db import store, new_record, touch, ordered, clock_date
from errors import ApiError, invalid
from guard import (auth, lookup, get_body, resolve_fk, v_string, v_number, v_date,
                   v_enum, require_branch_owner)
from response import success, created, paginate

bp = Blueprint("logistics", __name__)

JOB_TYPES = ("DELIVERY_INSTALL", "TEARDOWN_RETURN", "RELOCATION")


@bp.post("/logistics-jobs")
def create_job():
    user_id, role = auth("BranchOps")
    body = get_body()

    # rank 4 -- body foreign keys in the declared field order
    lease = resolve_fk(body, "lease_id", store.leases, "ERR_LEASE_NOT_FOUND")
    origin_branch = resolve_fk(body, "origin_branch_id", store.branches, "ERR_BRANCH_NOT_FOUND")
    destination_branch = resolve_fk(body, "destination_branch_id", store.branches, "ERR_BRANCH_NOT_FOUND")

    # rank 5 -- body shape
    lease_id = v_string(body, "lease_id")
    job_type = v_enum(body, "job_type", JOB_TYPES)
    origin_branch_id = v_string(body, "origin_branch_id")
    scheduled_date = v_date(body, "scheduled_date")
    mileage_miles = v_number(body, "mileage_miles", minimum=0)
    crew_hours = v_number(body, "crew_hours", minimum=0)
    destination_branch_id = v_string(body, "destination_branch_id", required=False)
    new_site_address = v_string(body, "new_site_address", required=False)

    if job_type == "TEARDOWN_RETURN":
        if destination_branch_id is None:
            invalid("'destination_branch_id' is required for a TEARDOWN_RETURN job.")
    elif destination_branch_id is not None:
        invalid("'destination_branch_id' must be omitted for a %s job." % job_type)

    if job_type == "RELOCATION":
        if new_site_address is None:
            invalid("'new_site_address' is required for a RELOCATION job.")
    elif new_site_address is not None:
        invalid("'new_site_address' must be omitted for a %s job." % job_type)

    # rank 6 -- resource ownership
    require_branch_owner(user_id, role, origin_branch_id)

    unit = store.units[lease["unit_id"]]
    jurisdiction = store.jurisdictions[lease["jurisdiction_id"]]

    # rank 9 -- ADA package compliance
    if job_type == "DELIVERY_INSTALL" and jurisdiction["ada_ramp_required"]:
        packages = services.packages_of_lease(lease["id"])
        if not packages or packages[0]["compliance_status"] != "COMPLIANT":
            raise ApiError("ERR_ADA_PACKAGE_NON_COMPLIANT",
                           "This jurisdiction requires a COMPLIANT accessible ramp package.")

    # rank 15 -- servicing branch operational
    if origin_branch["status"] != "OPERATIONAL":
        raise ApiError("ERR_BRANCH_SUSPENDED", "The origin branch is SUSPENDED.")

    # rank 21 -- branch dispatch capacity for the scheduled day
    scheduled_iso = calc.format_date(scheduled_date)
    held = len([j for j in store.jobs.values()
                if j["origin_branch_id"] == origin_branch_id
                and j["scheduled_date"] == scheduled_iso
                and j["status"] in ("SCHEDULED", "DISPATCHED")])
    if held >= origin_branch["daily_dispatch_capacity"]:
        raise ApiError("ERR_BRANCH_DISPATCH_CAPACITY_EXCEEDED",
                       "The origin branch has no dispatch slot free on that day.")

    spec = store.building_specs[unit["building_spec_id"]]
    cost = calc.transport_cost(mileage_miles, crew_hours,
                               origin_branch["labor_rate_cents_per_hour"], job_type, spec["sections"])

    record = new_record(
        lease_id=lease_id,
        unit_id=lease["unit_id"],
        origin_branch_id=origin_branch_id,
        destination_branch_id=destination_branch_id,
        job_type=job_type,
        scheduled_date=scheduled_iso,
        mileage_miles=mileage_miles,
        crew_hours=crew_hours,
        new_site_address=new_site_address,
        status="SCHEDULED",
        transport_cost_cents=cost,
        cancellation_reason=None,
    )
    store.jobs[record["id"]] = record
    return created(S.job(record))


@bp.get("/logistics-jobs/<job_id>")
def read_job(job_id):
    auth("BranchOps", "FleetAdmin", "LeasingAgent")
    record = lookup(store.jobs, job_id, "ERR_LOGISTICS_JOB_NOT_FOUND")
    return success(S.job(record))


@bp.get("/logistics-jobs")
def list_jobs():
    auth("BranchOps", "FleetAdmin", "LeasingAgent")
    records = ordered(store.jobs.values())
    records = services.apply_filters(records, {
        "lease_id": "lease_id",
        "unit_id": "unit_id",
        "origin_branch_id": "origin_branch_id",
        "destination_branch_id": "destination_branch_id",
        "status": "status",
        "scheduled_date": "scheduled_date",
    })
    return paginate(records, S.job)


@bp.post("/logistics-jobs/<job_id>/dispatch")
def dispatch_job(job_id):
    user_id, role = auth("BranchOps")
    job = lookup(store.jobs, job_id, "ERR_LOGISTICS_JOB_NOT_FOUND")

    # rank 6
    require_branch_owner(user_id, role, job["origin_branch_id"])

    lease = store.leases[job["lease_id"]]
    unit = store.units[job["unit_id"]]

    # rank 7 -- source state
    if job["status"] != "SCHEDULED":
        raise ApiError("ERR_JOB_NOT_DISPATCHABLE", "Only a SCHEDULED job may be dispatched.")
    if job["job_type"] == "DELIVERY_INSTALL":
        if lease["billing_status"] != "ACCRUING":
            raise ApiError("ERR_LEASE_NOT_ACTIVATED", "The lease has not been activated.")
    else:
        if lease["occupancy_status"] != "INSTALLED":
            raise ApiError("ERR_INVALID_STATE", "The lease is not INSTALLED.")

    # rank 10 -- permit approval
    if job["job_type"] == "DELIVERY_INSTALL":
        jurisdiction = store.jurisdictions[lease["jurisdiction_id"]]
        if jurisdiction["permit_required"]:
            approved = any(p["status"] == "APPROVED" for p in services.permits_of_lease(lease["id"]))
            if not approved:
                raise ApiError("ERR_PERMIT_NOT_APPROVED",
                               "This jurisdiction requires an APPROVED permit before dispatch.")

    job["status"] = "DISPATCHED"
    touch(job)

    if job["job_type"] == "DELIVERY_INSTALL":
        if unit["status"] == "RESERVED":
            unit["status"] = "IN_TRANSIT"
        touch(unit)
        services.recompute_branch_of_unit(unit)
    elif job["job_type"] == "TEARDOWN_RETURN":
        if unit["status"] == "ON_LEASE":
            unit["status"] = "IN_TRANSIT"
        touch(unit)
    # RELOCATION: the unit deliberately stays ON_LEASE and is not written

    return success(S.job(job))


@bp.post("/logistics-jobs/<job_id>/complete")
def complete_job(job_id):
    user_id, role = auth("BranchOps")
    job = lookup(store.jobs, job_id, "ERR_LOGISTICS_JOB_NOT_FOUND")

    # rank 6
    require_branch_owner(user_id, role, job["origin_branch_id"])

    lease = store.leases[job["lease_id"]]
    unit = store.units[job["unit_id"]]

    # rank 7 -- source state
    if job["status"] != "DISPATCHED":
        raise ApiError("ERR_INVALID_STATE", "Only a DISPATCHED job may be completed.")
    if job["job_type"] == "DELIVERY_INSTALL":
        if lease["occupancy_status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", "The lease occupancy axis is not PENDING.")
    else:
        if lease["occupancy_status"] != "INSTALLED":
            raise ApiError("ERR_INVALID_STATE", "The lease is not INSTALLED.")

    # rank 24 -- receiving yard has room
    destination = None
    if job["job_type"] == "TEARDOWN_RETURN":
        destination = store.branches[job["destination_branch_id"]]
        if destination["units_in_yard"] >= destination["yard_capacity_units"]:
            raise ApiError("ERR_YARD_CAPACITY_EXCEEDED", "The receiving yard is full.")

    job["status"] = "COMPLETED"
    touch(job)

    if job["job_type"] == "DELIVERY_INSTALL":
        if unit["status"] == "IN_TRANSIT":
            unit["status"] = "ON_LEASE"
        unit["installed_config_id"] = lease["floorplan_configuration_id"]
        touch(unit)
        lease["occupancy_status"] = "INSTALLED"
        touch(lease)
    elif job["job_type"] == "TEARDOWN_RETURN":
        lease["occupancy_status"] = "VACATED"
        lease["actual_vacated_date"] = calc.format_date(clock_date())
        touch(lease)
        previous_branch_id = unit["current_branch_id"]
        if unit["status"] == "IN_TRANSIT":
            unit["status"] = "RETURNED"
        unit["current_branch_id"] = job["destination_branch_id"]
        touch(unit)
        # PRD 2.10: the three counters are recomputed from scratch after every
        # write that changes a unit's status or its custody branch.  Custody
        # moved, so the yard the unit left is restated as well as the receiving
        # yard -- the departed unit no longer counts in its former total.
        services.recompute_branch(destination)
        if previous_branch_id != job["destination_branch_id"]:
            services.recompute_branch(store.branches.get(previous_branch_id))
    else:  # RELOCATION
        unit["lifetime_relocations"] += 1
        touch(unit)
        lease["site_address"] = job["new_site_address"]
        lease["relocation_surcharge_cents"] += calc.relocation_passthrough(job["transport_cost_cents"])
        touch(lease)

    return success(S.job(job))


@bp.post("/logistics-jobs/<job_id>/cancel")
def cancel_job(job_id):
    user_id, role = auth("BranchOps")
    job = lookup(store.jobs, job_id, "ERR_LOGISTICS_JOB_NOT_FOUND")
    body = get_body()
    cancellation_reason = v_string(body, "cancellation_reason", required=False, allow_blank=True)

    # rank 6
    require_branch_owner(user_id, role, job["origin_branch_id"])

    # rank 7 -- source state
    aborting_delivery = job["status"] == "DISPATCHED" and job["job_type"] == "DELIVERY_INSTALL"
    if job["status"] != "SCHEDULED" and not aborting_delivery:
        raise ApiError("ERR_JOB_NOT_DISPATCHABLE", "This job may not be cancelled from its current state.")

    job["status"] = "CANCELLED"
    job["cancellation_reason"] = cancellation_reason
    touch(job)

    if aborting_delivery:
        unit = store.units[job["unit_id"]]
        if unit["status"] == "IN_TRANSIT":
            unit["status"] = "RESERVED"
        touch(unit)
        services.recompute_branch_of_unit(unit)

    return success(S.job(job))
