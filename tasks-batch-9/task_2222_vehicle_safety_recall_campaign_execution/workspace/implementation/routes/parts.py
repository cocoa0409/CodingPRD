"""Dealers, remedy parts, labor operations and parts allocations."""
from flask import Blueprint, request

import calc
import helpers as h
import validators as v
from auth import ALL_ROLES, require_roles
from db import base_record, parse_date, sorted_records, store, touch
from errors import ApiError
from response import collection, single

bp = Blueprint("parts", __name__)


# --------------------------------------------------------------------------
# dealers
# --------------------------------------------------------------------------
@bp.post("/dealers")
@require_roles("RecallOperationsManager")
def create_dealer():
    payload = v.body()
    dealer_code = v.req_str(payload, "dealer_code", min_len=1, max_len=16)
    name = v.req_str(payload, "name")
    region_code = v.req_enum(payload, "region_code", v.REGION_CODES)
    labor_rate = v.req_decimal(payload, "labor_rate_per_hour", gt=0)
    capacity = v.req_int(payload, "monthly_repair_capacity", minimum=1)

    dealer = base_record()
    dealer.update({
        "dealer_code": dealer_code,
        "name": name,
        "region_code": region_code,
        "labor_rate_per_hour": calc.q2(labor_rate),
        "monthly_repair_capacity": capacity,
        "status": "ACTIVE",
        "suspension_reason": None,
    })
    store.dealers[dealer["id"]] = dealer
    return single(h.dealer_out(dealer), 201)


@bp.get("/dealers/<dealer_id>")
@require_roles(*ALL_ROLES)
def get_dealer(dealer_id):
    return single(h.dealer_out(h.get_dealer(dealer_id)))


@bp.post("/dealers/<dealer_id>/suspend")
@require_roles("RecallOperationsManager")
def suspend_dealer(dealer_id):
    dealer = h.get_dealer(dealer_id)
    payload = v.body()
    reason = v.req_str(payload, "suspension_reason")
    dealer["status"] = "SUSPENDED"
    dealer["suspension_reason"] = reason
    touch(dealer)
    return single(h.dealer_out(dealer))


# --------------------------------------------------------------------------
# remedy parts
# --------------------------------------------------------------------------
@bp.post("/recall-campaigns/<campaign_id>/remedy-parts")
@require_roles("SafetyEngineer")
def create_part(campaign_id):
    campaign = h.get_campaign(campaign_id)
    payload = v.body()
    part_number = v.req_str(payload, "part_number")
    unit_cost = v.req_decimal(payload, "unit_cost", gt=0)
    total_procured = v.req_int(payload, "total_procured_qty", minimum=0)
    lead_time_days = v.opt_int(payload, "lead_time_days", 30, minimum=0)

    h.assert_campaign_writable(campaign)

    part = base_record()
    part.update({
        "campaign_id": campaign["id"],
        "part_number": part_number,
        "unit_cost": calc.q2(unit_cost),
        "total_procured_qty": total_procured,
        "unallocated_qty": total_procured,
        "consumed_qty": 0,
        "lead_time_days": lead_time_days,
    })
    store.remedy_parts[part["id"]] = part
    return single(h.part_out(part), 201)


@bp.get("/recall-campaigns/<campaign_id>/remedy-parts")
@require_roles(*ALL_ROLES)
def list_parts(campaign_id):
    campaign = h.get_campaign(campaign_id)
    part_number = request.args.get("part_number")
    rows = calc.campaign_parts(campaign["id"])
    if part_number is not None:
        rows = [r for r in rows if r["part_number"] == part_number]
    return collection(rows, h.part_out)


# --------------------------------------------------------------------------
# labor operations
# --------------------------------------------------------------------------
@bp.post("/recall-campaigns/<campaign_id>/labor-operations")
@require_roles("SafetyEngineer")
def create_labor_op(campaign_id):
    campaign = h.get_campaign(campaign_id)
    payload = v.body()
    labor_op_code = v.req_str(payload, "labor_op_code")
    description = v.req_str(payload, "description")
    flat_hours = v.req_decimal(payload, "flat_hours", gt=0)
    rate_type = v.req_enum(payload, "rate_type", v.RATE_TYPES)
    from_raw, from_date = v.req_date_str(payload, "effective_from")
    to_raw, to_date = v.req_date_str(payload, "effective_to")

    h.assert_campaign_writable(campaign)

    if from_date > to_date:
        raise ApiError("ERR_INVALID_DATE_RANGE")

    for other in calc.campaign_labor_ops(campaign["id"]):
        if other["labor_op_code"] != labor_op_code:
            continue
        o_from = parse_date(other["effective_from"])
        o_to = parse_date(other["effective_to"])
        if from_date <= o_to and o_from <= to_date:
            raise ApiError("ERR_LABOR_OP_WINDOW_CONFLICT")

    labor_op = base_record()
    labor_op.update({
        "campaign_id": campaign["id"],
        "labor_op_code": labor_op_code,
        "description": description,
        "flat_hours": calc.q2(flat_hours),
        "rate_type": rate_type,
        "effective_from": from_raw,
        "effective_to": to_raw,
    })
    store.labor_operations[labor_op["id"]] = labor_op
    return single(h.labor_op_out(labor_op), 201)


@bp.get("/recall-campaigns/<campaign_id>/labor-operations")
@require_roles(*ALL_ROLES)
def list_labor_ops(campaign_id):
    campaign = h.get_campaign(campaign_id)
    labor_op_code = request.args.get("labor_op_code")
    effective_on = v.query_date("effective_on")
    rows = calc.campaign_labor_ops(campaign["id"])
    if labor_op_code is not None:
        rows = [r for r in rows if r["labor_op_code"] == labor_op_code]
    if effective_on is not None:
        rows = [r for r in rows
                if parse_date(r["effective_from"]) <= effective_on
                <= parse_date(r["effective_to"])]
    return collection(rows, h.labor_op_out)


# --------------------------------------------------------------------------
# parts allocations
# --------------------------------------------------------------------------
@bp.post("/parts-allocations")
@require_roles("RecallOperationsManager")
def create_allocation():
    payload = v.body()
    remedy_part_id = v.req_str(payload, "remedy_part_id")
    dealer_id = v.req_str(payload, "dealer_id")
    requested_qty = v.req_int(payload, "requested_qty", minimum=1)
    expected_part_version = v.req_int(payload, "expected_part_version")

    dealer = h.get_dealer(dealer_id)
    part = h.get_part(remedy_part_id)
    campaign = store.campaigns.get(part["campaign_id"])

    h.assert_campaign_writable(campaign)

    if expected_part_version != part["version"]:
        raise ApiError("ERR_STALE_PART_VERSION")

    if dealer["status"] != "ACTIVE":
        raise ApiError("ERR_DEALER_SUSPENDED")

    # step 1 - the dealer's prior holding on this part is superseded first
    prior = None
    for alloc in calc.campaign_allocations(part["campaign_id"]):
        if (alloc["remedy_part_id"] == part["id"]
                and alloc["dealer_id"] == dealer["id"]
                and alloc["status"] == "ALLOCATED"):
            prior = alloc
            break
    returned = 0 if prior is None else prior["allocated_qty"] - prior["consumed_qty"]
    pool = part["unallocated_qty"] + returned

    # step 2 - regional demand snapshot, taken after that return has landed
    region_demand = 0
    for av in calc.campaign_avs(part["campaign_id"]):
        if av["remedy_status"] not in ("UNREPAIRED", "SCHEDULED"):
            continue
        vehicle = store.vehicles.get(av["vehicle_id"])
        if vehicle is not None and vehicle["region_code"] == dealer["region_code"]:
            region_demand += 1

    # step 3 - nested caps
    dealer_cap = min(requested_qty, dealer["monthly_repair_capacity"],
                     region_demand * calc.PARTS_PER_REPAIR_MAX)
    granted = min(dealer_cap, pool)
    if granted <= 0:
        raise ApiError("ERR_NO_PARTS_AVAILABLE")

    if prior is not None:
        h.return_units_to_pool(prior, "SUPERSEDED")

    alloc = base_record()
    alloc.update({
        "remedy_part_id": part["id"],
        "dealer_id": dealer["id"],
        "campaign_id": part["campaign_id"],
        "requested_qty": requested_qty,
        "allocated_qty": granted,
        "consumed_qty": 0,
        "status": "ALLOCATED",
        "partially_granted": granted < requested_qty,
        "revoked_reason": None,
    })
    store.allocations[alloc["id"]] = alloc

    part["unallocated_qty"] = part["unallocated_qty"] - granted
    touch(part)
    return single(h.allocation_out(alloc), 201)


@bp.get("/parts-allocations")
@require_roles(*ALL_ROLES)
def list_allocations():
    status = v.query_enum("status", v.ALLOCATION_STATUSES)
    filters = {
        "remedy_part_id": request.args.get("remedy_part_id"),
        "dealer_id": request.args.get("dealer_id"),
        "campaign_id": request.args.get("campaign_id"),
    }
    rows = list(store.allocations.values())
    for field, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return collection(sorted_records(rows), h.allocation_out)


@bp.get("/parts-allocations/<allocation_id>")
@require_roles(*ALL_ROLES)
def get_allocation(allocation_id):
    return single(h.allocation_out(h.get_allocation(allocation_id)))


@bp.post("/parts-allocations/<allocation_id>/revoke")
@require_roles("RecallOperationsManager")
def revoke_allocation(allocation_id):
    alloc = h.get_allocation(allocation_id)
    payload = v.body()
    v.opt_str(payload, "revoke_note")

    if alloc["status"] != "ALLOCATED":
        raise ApiError("ERR_ALLOCATION_INVALID_STATE")

    h.return_units_to_pool(alloc, "MANUAL")
    return single(h.allocation_out(alloc))
