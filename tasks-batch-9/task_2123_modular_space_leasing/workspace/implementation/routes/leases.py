"""Quoting, reservation, activation, voiding and extension of leases."""
from datetime import timedelta

from flask import Blueprint

import calc
import serializers as S
import services
from db import store, new_record, touch, ordered, clock_date
from errors import ApiError
from guard import (auth, lookup, get_body, resolve_fk, v_string, v_int, v_date,
                   require_customer_owner)
from response import success, created, paginate

bp = Blueprint("leases", __name__)


def _price_lease(lease, unit, jurisdiction, config):
    spec = store.building_specs[unit["building_spec_id"]]
    lease["monthly_base_rate_cents"] = calc.lease_monthly_rate(
        spec["base_monthly_rate_cents"],
        config["config_surcharge_cents"],
        jurisdiction["wind_zone"],
        lease["pinned_credit_tier"],
        lease["term_months"],
    )


def _reproject(lease):
    lease["quoted_total_cents"] = calc.quoted_projection(
        lease["mobilization_fee_cents"],
        lease["monthly_base_rate_cents"],
        lease["monthly_accessory_rate_cents"],
        lease["term_months"],
    )


# ---------------------------------------------------------------- create

@bp.post("/leases")
def create_lease():
    auth("LeasingAgent")
    body = get_body()

    # rank 4 -- body foreign keys resolved in the declared field order
    customer = resolve_fk(body, "customer_id", store.customers, "ERR_CUSTOMER_NOT_FOUND")
    unit = resolve_fk(body, "unit_id", store.units, "ERR_UNIT_NOT_FOUND")
    jurisdiction = resolve_fk(body, "jurisdiction_id", store.jurisdictions, "ERR_JURISDICTION_NOT_FOUND")
    config = resolve_fk(body, "floorplan_configuration_id", store.configs, "ERR_CONFIG_NOT_FOUND")

    # rank 5 -- body shape
    customer_id = v_string(body, "customer_id")
    unit_id = v_string(body, "unit_id")
    jurisdiction_id = v_string(body, "jurisdiction_id")
    config_id = v_string(body, "floorplan_configuration_id")
    site_address = v_string(body, "site_address")
    start_date = v_date(body, "start_date")
    term_months = v_int(body, "term_months", minimum=1)

    # rank 7 -- source state: only a unit in the shop is refused here
    if unit["status"] == "REFURBISHING":
        raise ApiError("ERR_UNIT_NOT_AVAILABLE", "The unit is in the refurbishment shop.")

    # rank 13 -- cross-entity link agreement
    if config["building_spec_id"] != unit["building_spec_id"]:
        raise ApiError("ERR_ENTITY_LINK_MISMATCH",
                       "The configuration was not cut against this unit's model.")

    # rank 14 -- configuration published
    if config["status"] != "PUBLISHED":
        raise ApiError("ERR_CONFIG_NOT_PUBLISHED", "The floorplan configuration is not PUBLISHED.")

    # rank 20 -- unit occupancy calendar
    end_date = calc.lease_end_date(start_date, term_months)
    if services.occupancy_conflict(unit_id, start_date, end_date):
        raise ApiError("ERR_UNIT_OCCUPANCY_CONFLICT",
                       "The requested interval collides with an existing tenancy on this unit.")

    # rank 25 -- customer not on credit hold
    if customer["credit_hold"]:
        raise ApiError("ERR_CUSTOMER_ON_CREDIT_HOLD", "The lessee is on credit hold.")

    spec = store.building_specs[unit["building_spec_id"]]
    lease = new_record(
        customer_id=customer_id,
        unit_id=unit_id,
        jurisdiction_id=jurisdiction_id,
        floorplan_configuration_id=config_id,
        extends_lease_id=None,
        site_address=site_address,
        start_date=calc.format_date(start_date),
        term_months=term_months,
        end_date=calc.format_date(end_date),
        occupancy_status="PENDING",
        billing_status="UNBILLED",
        pinned_credit_tier=customer["credit_tier"],
        monthly_base_rate_cents=0,
        monthly_accessory_rate_cents=0,
        mobilization_fee_cents=0,
        quoted_total_cents=0,
        final_settlement_cents=None,
        relocation_surcharge_cents=0,
        billed_to_date_cents=0,
        credited_cents=0,
        actual_vacated_date=None,
        assessment_round=0,
    )
    _price_lease(lease, unit, jurisdiction, config)
    lease["mobilization_fee_cents"] = calc.lease_mobilization_fee(
        spec["delivery_base_cents"], spec["install_base_cents"], jurisdiction["anchoring_standard"])
    _reproject(lease)
    store.leases[lease["id"]] = lease

    # reserve the unit
    branch = store.branches.get(unit["current_branch_id"])
    if unit["status"] == "IN_FLEET" and branch is not None and branch["status"] == "OPERATIONAL":
        unit["status"] = "RESERVED"
    touch(unit)
    services.recompute_branch(branch)

    return created(S.lease(lease))


# ---------------------------------------------------------------- reads

@bp.get("/leases/<lease_id>")
def read_lease(lease_id):
    user_id, role = auth("LeasingAgent", "FleetAdmin", "Customer", "BranchOps")
    lease = lookup(store.leases, lease_id, "ERR_LEASE_NOT_FOUND")
    require_customer_owner(user_id, role, lease["customer_id"])
    return success(S.lease(lease))


@bp.get("/leases")
def list_leases():
    auth("LeasingAgent", "FleetAdmin")
    records = ordered(store.leases.values())
    records = services.apply_filters(records, {
        "customer_id": "customer_id",
        "unit_id": "unit_id",
        "jurisdiction_id": "jurisdiction_id",
        "floorplan_configuration_id": "floorplan_configuration_id",
        "extends_lease_id": "extends_lease_id",
        "occupancy_status": "occupancy_status",
        "billing_status": "billing_status",
    })
    return paginate(records, S.lease)


# ---------------------------------------------------------------- activate

@bp.post("/leases/<lease_id>/activate")
def activate_lease(lease_id):
    auth("LeasingAgent")
    lease = lookup(store.leases, lease_id, "ERR_LEASE_NOT_FOUND")

    # rank 7 -- source state
    if lease["billing_status"] != "UNBILLED":
        raise ApiError("ERR_LEASE_ALREADY_ACTIVATED", "The lease has already been activated.")
    if lease["occupancy_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "The lease occupancy axis has left PENDING.")

    config = store.configs.get(lease["floorplan_configuration_id"])
    if config is None or config["status"] != "PUBLISHED":
        raise ApiError("ERR_CONFIG_NOT_PUBLISHED", "The floorplan configuration is not PUBLISHED.")

    customer = store.customers[lease["customer_id"]]
    first_charge = (lease["mobilization_fee_cents"] + lease["monthly_base_rate_cents"]
                    + lease["monthly_accessory_rate_cents"])

    # rank 26 -- credit headroom
    if customer["outstanding_balance_cents"] + first_charge > customer["credit_limit_cents"]:
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED",
                       "Activation would push the lessee past its credit limit.")

    lease["billing_status"] = "ACCRUING"
    lease["billed_to_date_cents"] = first_charge
    touch(lease)
    services.recompute_customer(customer)
    return success(S.lease(lease))


# ---------------------------------------------------------------- void

@bp.post("/leases/<lease_id>/void")
def void_lease(lease_id):
    auth("LeasingAgent")
    lease = lookup(store.leases, lease_id, "ERR_LEASE_NOT_FOUND")
    body = get_body()
    v_string(body, "void_reason", required=False, allow_blank=True)

    # rank 7 -- source state
    if lease["occupancy_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Only a PENDING lease may be voided.")
    for job in services.jobs_of_lease(lease["id"]):
        if job["status"] in ("DISPATCHED", "COMPLETED"):
            raise ApiError("ERR_INVALID_STATE",
                           "A crew is already on the road for this lease.")

    lease["occupancy_status"] = "CANCELLED"
    lease["billing_status"] = "VOIDED"
    lease["credited_cents"] = lease["billed_to_date_cents"]
    touch(lease)

    customer = store.customers[lease["customer_id"]]
    services.recompute_customer(customer)

    unit = store.units.get(lease["unit_id"])
    if unit is not None and unit["status"] == "RESERVED":
        others_pending = any(
            other["id"] != lease["id"] and other["occupancy_status"] == "PENDING"
            for other in services.leases_of_unit(unit["id"])
        )
        if not others_pending:
            unit["status"] = "IN_FLEET"
            touch(unit)
            services.recompute_branch_of_unit(unit)

    return success(S.lease(lease))


# ---------------------------------------------------------------- extension

@bp.post("/leases/<lease_id>/extensions")
def extend_lease(lease_id):
    auth("LeasingAgent")
    parent = lookup(store.leases, lease_id, "ERR_LEASE_NOT_FOUND")
    body = get_body()
    term_months = v_int(body, "term_months", minimum=1)

    unit = store.units[parent["unit_id"]]
    customer = store.customers[parent["customer_id"]]
    jurisdiction = store.jurisdictions[parent["jurisdiction_id"]]
    config = store.configs[parent["floorplan_configuration_id"]]

    # rank 7 -- source state
    if unit["status"] == "REFURBISHING":
        raise ApiError("ERR_UNIT_NOT_AVAILABLE", "The unit is in the refurbishment shop.")

    # rank 18 -- one live successor per lease
    for other in ordered(store.leases.values()):
        if other["extends_lease_id"] == parent["id"] and other["occupancy_status"] != "CANCELLED":
            raise ApiError("ERR_LEASE_ALREADY_EXTENDED", "This lease already has a live successor.")

    parent_end = calc.parse_iso_date(parent["end_date"])
    start_date = parent_end + timedelta(days=1)
    end_date = calc.lease_end_date(start_date, term_months)

    # rank 20 -- unit occupancy calendar (exempt against its own parent)
    if services.occupancy_conflict(unit["id"], start_date, end_date, extends_lease_id=parent["id"]):
        raise ApiError("ERR_UNIT_OCCUPANCY_CONFLICT",
                       "The successor interval collides with an existing tenancy on this unit.")

    # rank 23 -- extension contiguity against the clock
    if start_date < clock_date():
        raise ApiError("ERR_EXTENSION_NOT_CONTIGUOUS",
                       "The successor may not start before the current logical date.")

    # rank 25 -- customer not on credit hold
    if customer["credit_hold"]:
        raise ApiError("ERR_CUSTOMER_ON_CREDIT_HOLD", "The lessee is on credit hold.")

    successor = new_record(
        customer_id=parent["customer_id"],
        unit_id=parent["unit_id"],
        jurisdiction_id=parent["jurisdiction_id"],
        floorplan_configuration_id=parent["floorplan_configuration_id"],
        extends_lease_id=parent["id"],
        site_address=parent["site_address"],
        start_date=calc.format_date(start_date),
        term_months=term_months,
        end_date=calc.format_date(end_date),
        occupancy_status="INSTALLED",
        billing_status="UNBILLED",
        pinned_credit_tier=parent["pinned_credit_tier"],
        monthly_base_rate_cents=0,
        monthly_accessory_rate_cents=0,
        mobilization_fee_cents=0,
        quoted_total_cents=0,
        final_settlement_cents=None,
        relocation_surcharge_cents=0,
        billed_to_date_cents=0,
        credited_cents=0,
        actual_vacated_date=None,
        assessment_round=0,
    )
    _price_lease(successor, unit, jurisdiction, config)
    _reproject(successor)
    store.leases[successor["id"]] = successor

    touch(parent)
    touch(unit)

    return created(S.lease(successor))
