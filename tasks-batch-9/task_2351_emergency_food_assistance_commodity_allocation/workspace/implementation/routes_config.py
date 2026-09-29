"""Program configuration, agency eligibility and the logical clock."""

from datetime import timedelta

from flask import Blueprint, g, request

import calc
import serializers as ser
import services as svc
import validators as val
from db import base_row, db, iso, now, ordered, touch
from errors import fail
from middleware import (
    ANY_ROLE,
    body,
    endpoint,
    open_endpoint,
    paginate,
    pagination,
)
from response import collection, created, ok

bp = Blueprint("config", __name__)

URBAN_RURAL = ("URBAN", "RURAL", "MIXED")
STORAGE_CLASSES = ("DRY", "COLD", "FROZEN")
MONITOR_POLICIES = ("TURNOVER_BASED", "SHELF_LIFE_BASED")


def _page(rows):
    limit, offset = pagination()
    total = len(rows)
    return limit, offset, total, paginate(rows, limit, offset)


def _filter(name):
    value = request.args.get(name)
    if value is None or value.strip() == "":
        return None
    return value.strip()


# ---------------------------------------------------------------------------
# logical clock (PRD §2.4)
# ---------------------------------------------------------------------------
@bp.post("/efap/_clock/set_current_utc")
@endpoint("StateAdmin")
def set_clock():
    payload = body()
    db.clock = val.req_datetime(payload, "current_utc")
    return ok({"current_utc": iso(db.clock)})


@bp.get("/efap/_clock/current")
@open_endpoint
def read_clock():
    return ok({"current_utc": iso(now())})


# ---------------------------------------------------------------------------
# ServiceArea (PRD §3.1)
# ---------------------------------------------------------------------------
@bp.post("/efap/service-areas")
@endpoint("StateAdmin")
def create_service_area():
    payload = body()
    name = val.req_string(payload, "name", 1, 120)
    county_code = val.req_string(payload, "county_code", 2, 8, upper=True)
    poverty_population = val.req_int(payload, "poverty_population", minimum=0)
    urban_rural = val.opt_enum(payload, "urban_rural", URBAN_RURAL, "MIXED")
    for existing in db.service_areas.values():
        if existing["county_code"] == county_code:
            fail("ERR_DUPLICATE_CODE", "county_code %s already exists" % county_code)
    row = base_row()
    row.update(
        {
            "name": name,
            "county_code": county_code,
            "poverty_population": poverty_population,
            "urban_rural": urban_rural,
            "eligible_agency_count": 0,
        }
    )
    db.service_areas[row["id"]] = row
    return created(ser.service_area(row))


@bp.get("/efap/service-areas")
@endpoint(*ANY_ROLE)
def list_service_areas():
    county_code = _filter("county_code")
    urban_rural = _filter("urban_rural")
    rows = ordered(db.service_areas.values())
    if county_code is not None:
        rows = [r for r in rows if r["county_code"] == county_code]
    if urban_rural is not None:
        rows = [r for r in rows if r["urban_rural"] == urban_rural]
    limit, offset, total, page = _page(rows)
    return collection([ser.service_area(r) for r in page], limit, offset, total)


@bp.get("/efap/service-areas/<service_area_id>")
@endpoint(*ANY_ROLE)
def read_service_area(service_area_id):
    return ok(ser.service_area(svc.service_area(service_area_id)))


@bp.patch("/efap/service-areas/<service_area_id>")
@endpoint("StateAdmin")
def patch_service_area(service_area_id):
    row = svc.service_area(service_area_id)
    payload = body()
    poverty_population = val.opt_int(payload, "poverty_population", minimum=0)
    urban_rural = val.opt_enum(payload, "urban_rural", URBAN_RURAL)
    if poverty_population is not None:
        row["poverty_population"] = poverty_population
    if urban_rural is not None:
        row["urban_rural"] = urban_rural
    touch(row)
    return ok(ser.service_area(row))


# ---------------------------------------------------------------------------
# Agency (PRD §3.2)
# ---------------------------------------------------------------------------
@bp.post("/efap/agencies")
@endpoint("StateAdmin")
def create_agency():
    payload = body()
    name = val.req_string(payload, "name", 1, 120)
    val.req_id(payload, "service_area_id")
    cold_capacity = val.req_int(payload, "cold_storage_pallet_capacity", minimum=0)
    prior_pounds = val.opt_decimal(
        payload, "prior_period_pounds_distributed", minimum=0, places=2, default=calc.ZERO_2
    )
    prior_cases = val.opt_int(payload, "prior_period_allocated_cases", minimum=0, default=0)
    area = svc.service_area(payload["service_area_id"])
    row = base_row()
    row.update(
        {
            "name": name,
            "service_area_id": area["id"],
            "cold_storage_pallet_capacity": cold_capacity,
            "prior_period_pounds_distributed": calc.rhu(prior_pounds, 2),
            "prior_period_allocated_cases": prior_cases,
            "agreement_status": "PENDING",
            "agreement_start_date": None,
            "agreement_end_date": None,
            "training_status": "REQUIRED",
            "last_training_completed_at": None,
            "training_expires_at": None,
            "eligibility_posture": "INELIGIBLE",
            "agency_cases_on_hand": 0,
            "delivered_cases_ytd": 0,
            "renewal_count": 0,
        }
    )
    db.agencies[row["id"]] = row
    return created(ser.agency(row))


@bp.get("/efap/agencies")
@endpoint(*ANY_ROLE)
def list_agencies():
    service_area_id = _filter("service_area_id")
    agreement_status = _filter("agreement_status")
    training_status = _filter("training_status")
    posture = _filter("eligibility_posture")
    rows = ordered(db.agencies.values())
    if service_area_id is not None:
        rows = [r for r in rows if r["service_area_id"] == service_area_id]
    if agreement_status is not None:
        rows = [r for r in rows if r["agreement_status"] == agreement_status]
    if training_status is not None:
        rows = [r for r in rows if r["training_status"] == training_status]
    if posture is not None:
        rows = [r for r in rows if r["eligibility_posture"] == posture]
    limit, offset, total, page = _page(rows)
    return collection([ser.agency(r) for r in page], limit, offset, total)


@bp.get("/efap/agencies/<agency_id>")
@endpoint(*ANY_ROLE)
def read_agency(agency_id):
    return ok(ser.agency(svc.agency(agency_id)))


@bp.patch("/efap/agencies/<agency_id>")
@endpoint("StateAdmin")
def patch_agency(agency_id):
    row = svc.agency(agency_id)
    payload = body()
    cold_capacity = val.opt_int(payload, "cold_storage_pallet_capacity", minimum=0)
    prior_pounds = val.opt_decimal(
        payload, "prior_period_pounds_distributed", minimum=0, places=2
    )
    prior_cases = val.opt_int(payload, "prior_period_allocated_cases", minimum=0)
    if cold_capacity is not None:
        row["cold_storage_pallet_capacity"] = cold_capacity
    if prior_pounds is not None:
        row["prior_period_pounds_distributed"] = prior_pounds
    if prior_cases is not None:
        row["prior_period_allocated_cases"] = prior_cases
    touch(row)
    return ok(ser.agency(row))


@bp.post("/efap/agencies/<agency_id>/agreement-renewals")
@endpoint("ComplianceReviewer")
def renew_agreement(agency_id):
    row = svc.agency(agency_id)
    payload = body()
    start_date = val.req_date(payload, "agreement_start_date")
    end_date = val.req_date(payload, "agreement_end_date")
    if end_date <= start_date:
        fail("ERR_INVALID_REQUEST", "agreement_end_date must be after agreement_start_date")
    # position 8 — the terminal state admits no renewal
    if row["agreement_status"] == "TERMINATED":
        fail("ERR_AGREEMENT_NOT_RENEWABLE", "A terminated agreement cannot be renewed")
    # position 13 — training currency
    if row["training_status"] != "CURRENT":
        fail("ERR_TRAINING_NOT_CURRENT", "Civil rights training is not current")
    # the ACTIVE self-loop carries one extra precondition
    if row["agreement_status"] == "ACTIVE":
        if row["agreement_end_date"] is None or start_date <= row["agreement_end_date"]:
            fail(
                "ERR_AGREEMENT_NOT_RENEWABLE",
                "agreement_start_date must be after the current agreement_end_date",
            )
    row["agreement_status"] = "ACTIVE"
    row["agreement_start_date"] = start_date
    row["agreement_end_date"] = end_date
    row["renewal_count"] = row["renewal_count"] + 1
    svc.recompute_posture(row)
    touch(row)
    return created(ser.agency(row))


@bp.post("/efap/agencies/<agency_id>/civil-rights-trainings")
@endpoint("ComplianceReviewer")
def record_training(agency_id):
    row = svc.agency(agency_id)
    payload = body()
    completed_at = val.req_datetime(payload, "completed_at")
    val.req_int(payload, "attendee_count", minimum=1)
    if completed_at > now():
        fail("ERR_INVALID_REQUEST", "completed_at must not be in the future")
    if row["training_status"] == "CURRENT":
        if row["last_training_completed_at"] is not None and completed_at <= row["last_training_completed_at"]:
            fail(
                "ERR_INVALID_REQUEST",
                "completed_at must be after the last recorded training",
            )
    row["training_status"] = "CURRENT"
    row["last_training_completed_at"] = completed_at
    row["training_expires_at"] = completed_at + timedelta(days=calc.TRAINING_VALID_DAYS)
    svc.recompute_posture(row)
    touch(row)
    return created(ser.agency(row))


@bp.get("/efap/agencies/<agency_id>/allocations")
@endpoint(*ANY_ROLE)
def list_agency_allocations(agency_id):
    row = svc.agency(agency_id)
    rows = [r for r in ordered(db.allocations.values()) if r["agency_id"] == row["id"]]
    limit, offset, total, page = _page(rows)
    return collection([ser.agency_allocation(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# compliance sweep (PRD §3.2, ops-run checkpoint)
# ---------------------------------------------------------------------------
@bp.post("/efap/compliance-sweeps")
@endpoint("StateAdmin")
def compliance_sweep():
    stamp = now()
    today = stamp.date()
    touched = []

    def mark(row):
        if row["id"] not in [r["id"] for r in touched]:
            touched.append(row)

    rows = ordered(db.agencies.values())
    # pass 1 — agreements past their end date expire
    for row in rows:
        if row["agreement_status"] == "ACTIVE" and row["agreement_end_date"] is not None:
            if today > row["agreement_end_date"]:
                row["agreement_status"] = "EXPIRED"
                mark(row)
    # pass 2 — training lapses at or after its expiry instant
    for row in rows:
        if row["training_status"] == "CURRENT" and row["training_expires_at"] is not None:
            if stamp >= row["training_expires_at"]:
                row["training_status"] = "LAPSED"
                mark(row)
    # pass 3 — expired agreements terminate after the grace period
    for row in rows:
        if row["agreement_status"] == "EXPIRED" and row["agreement_end_date"] is not None:
            deadline = row["agreement_end_date"] + timedelta(
                days=calc.AGREEMENT_TERMINATION_GRACE_DAYS
            )
            if today >= deadline:
                row["agreement_status"] = "TERMINATED"
                mark(row)
                for order_row in ordered(db.orders.values()):
                    if order_row["agency_id"] != row["id"]:
                        continue
                    if order_row["status"] in ("DRAFT", "SUBMITTED"):
                        svc.cancel_order(order_row, "AGREEMENT_TERMINATED")

    for row in touched:
        row["eligibility_posture"] = svc.posture_of(row)
    areas = []
    for row in touched:
        if row["service_area_id"] not in areas:
            areas.append(row["service_area_id"])
    for area_id in areas:
        svc.recompute_area_count(area_id)
    for row in touched:
        touch(row)
    return collection([ser.agency(r) for r in ordered(touched)])


# ---------------------------------------------------------------------------
# Commodity (PRD §3.1)
# ---------------------------------------------------------------------------
@bp.post("/efap/commodities")
@endpoint("StateAdmin")
def create_commodity():
    payload = body()
    code = val.req_string(payload, "code", 1, 60, upper=True)
    name = val.req_string(payload, "name", 1, 200)
    storage_class = val.req_enum(payload, "storage_class", STORAGE_CLASSES)
    net_weight = val.req_decimal(payload, "net_weight_lbs_per_case", exclusive_min=0, places=3)
    cases_per_pallet = val.req_int(payload, "cases_per_pallet", minimum=1)
    entitlement_value = val.req_int(payload, "entitlement_value_cents_per_case", minimum=1)
    shelf_life_days = val.req_int(payload, "shelf_life_days", minimum=1)
    excess_ceiling = val.req_int(payload, "excess_case_ceiling", minimum=1)
    for existing in db.commodities.values():
        if existing["code"] == code:
            fail("ERR_DUPLICATE_CODE", "code %s already exists" % code)
    row = base_row(versioned=False)
    row.update(
        {
            "code": code,
            "name": name,
            "storage_class": storage_class,
            "net_weight_lbs_per_case": net_weight,
            "cases_per_pallet": cases_per_pallet,
            "entitlement_value_cents_per_case": entitlement_value,
            "shelf_life_days": shelf_life_days,
            "excess_case_ceiling": excess_ceiling,
        }
    )
    db.commodities[row["id"]] = row
    return created(ser.commodity(row))


@bp.get("/efap/commodities")
@endpoint(*ANY_ROLE)
def list_commodities():
    code = _filter("code")
    storage_class = _filter("storage_class")
    rows = ordered(db.commodities.values())
    if code is not None:
        rows = [r for r in rows if r["code"] == code]
    if storage_class is not None:
        rows = [r for r in rows if r["storage_class"] == storage_class]
    limit, offset, total, page = _page(rows)
    return collection([ser.commodity(r) for r in page], limit, offset, total)


@bp.get("/efap/commodities/<commodity_id>")
@endpoint(*ANY_ROLE)
def read_commodity(commodity_id):
    return ok(ser.commodity(svc.commodity(commodity_id)))


# ---------------------------------------------------------------------------
# Warehouse (PRD §3.1)
# ---------------------------------------------------------------------------
@bp.post("/efap/warehouses")
@endpoint("StateAdmin")
def create_warehouse():
    payload = body()
    name = val.req_string(payload, "name", 1, 200)
    dock_count = val.req_int(payload, "dock_count", minimum=1)
    dry = val.req_int(payload, "dry_pallet_capacity", minimum=0)
    cold = val.req_int(payload, "cold_pallet_capacity", minimum=0)
    frozen = val.req_int(payload, "frozen_pallet_capacity", minimum=0)
    policy = val.opt_enum(payload, "monitor_policy", MONITOR_POLICIES, "TURNOVER_BASED")
    for existing in db.warehouses.values():
        if existing["name"] == name:
            fail("ERR_DUPLICATE_CODE", "Warehouse name %s already exists" % name)
    row = base_row()
    row.update(
        {
            "name": name,
            "dock_count": dock_count,
            "dry_pallet_capacity": dry,
            "cold_pallet_capacity": cold,
            "frozen_pallet_capacity": frozen,
            "monitor_policy": policy,
        }
    )
    db.warehouses[row["id"]] = row
    return created(ser.warehouse(row))


@bp.get("/efap/warehouses")
@endpoint(*ANY_ROLE)
def list_warehouses():
    policy = _filter("monitor_policy")
    rows = ordered(db.warehouses.values())
    if policy is not None:
        rows = [r for r in rows if r["monitor_policy"] == policy]
    limit, offset, total, page = _page(rows)
    return collection([ser.warehouse(r) for r in page], limit, offset, total)


@bp.get("/efap/warehouses/<warehouse_id>")
@endpoint(*ANY_ROLE)
def read_warehouse(warehouse_id):
    return ok(ser.warehouse(svc.warehouse(warehouse_id)))


@bp.patch("/efap/warehouses/<warehouse_id>")
@endpoint("StateAdmin")
def patch_warehouse(warehouse_id):
    row = svc.warehouse(warehouse_id)
    payload = body()
    dock_count = val.opt_int(payload, "dock_count", minimum=1)
    dry = val.opt_int(payload, "dry_pallet_capacity", minimum=0)
    cold = val.opt_int(payload, "cold_pallet_capacity", minimum=0)
    frozen = val.opt_int(payload, "frozen_pallet_capacity", minimum=0)
    policy = val.opt_enum(payload, "monitor_policy", MONITOR_POLICIES)
    if dock_count is not None:
        row["dock_count"] = dock_count
    if dry is not None:
        row["dry_pallet_capacity"] = dry
    if cold is not None:
        row["cold_pallet_capacity"] = cold
    if frozen is not None:
        row["frozen_pallet_capacity"] = frozen
    if policy is not None:
        row["monitor_policy"] = policy
    touch(row)
    return ok(ser.warehouse(row))
