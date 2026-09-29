"""Allocation cycles, ordering, review, dock scheduling and distribution."""

from flask import Blueprint, g, request

import calc
import serializers as ser
import services as svc
import validators as val
from db import base_row, db, now, ordered, touch
from errors import fail
from middleware import ANY_ROLE, body, endpoint, paginate, pagination
from response import collection, created, ok

bp = Blueprint("program", __name__)

FORMULA_VARIANTS = ("STANDARD", "HOLD_HARMLESS")
CANCELLABLE_ORDER_STATUSES = ("DRAFT", "SUBMITTED", "APPROVED", "SCHEDULED")
UNSETTLED_ORDER_STATUSES = ("SUBMITTED", "APPROVED", "HELD", "SCHEDULED")


def _page(rows):
    limit, offset = pagination()
    return limit, offset, len(rows), paginate(rows, limit, offset)


def _filter(name):
    value = request.args.get(name)
    if value is None or value.strip() == "":
        return None
    return value.strip()


def _commodity_by_code(code):
    for row in ordered(db.commodities.values()):
        if row["code"] == code:
            return row
    return None


def _require_offered(cycle_row, commodity_row):
    if commodity_row["code"] not in cycle_row["offered_commodity_codes"]:
        fail(
            "ERR_COMMODITY_NOT_OFFERED",
            "Commodity %s is not offered in this cycle" % commodity_row["code"],
        )


# ---------------------------------------------------------------------------
# AllocationCycle (PRD §3.4)
# ---------------------------------------------------------------------------
@bp.post("/efap/allocation-cycles")
@endpoint("StateAdmin")
def create_cycle():
    payload = body()
    cycle_code = val.req_string(payload, "cycle_code", 3, 20, upper=True)
    formula_variant = val.req_enum(payload, "formula_variant", FORMULA_VARIANTS)
    allocatable_cases = val.req_int(payload, "allocatable_cases", minimum=1)
    admin_funds_pool_cents = val.req_int(payload, "admin_funds_pool_cents", minimum=0)
    offered = val.req_string_array(payload, "offered_commodity_codes", 1, 20)
    open_at = val.req_datetime(payload, "order_window_open_at")
    close_at = val.req_datetime(payload, "order_window_close_at")
    if close_at <= open_at:
        fail(
            "ERR_INVALID_REQUEST",
            "order_window_close_at must be after order_window_open_at",
        )
    for existing in db.cycles.values():
        if existing["cycle_code"] == cycle_code:
            fail("ERR_DUPLICATE_CODE", "cycle_code %s already exists" % cycle_code)
    row = base_row()
    row.update(
        {
            "cycle_code": cycle_code,
            "formula_variant": formula_variant,
            "allocatable_cases": allocatable_cases,
            "admin_funds_pool_cents": admin_funds_pool_cents,
            "offered_commodity_codes": offered,
            "order_window_open_at": open_at,
            "order_window_close_at": close_at,
            "status": "DRAFT",
            "draw_posture": "NOT_STARTED",
            "allocation_locked_at": None,
            "total_allocated_cases": 0,
            "eligible_agency_count": 0,
            "admin_funds_allocated_cents": 0,
        }
    )
    db.cycles[row["id"]] = row
    return created(ser.allocation_cycle(row))


@bp.get("/efap/allocation-cycles")
@endpoint(*ANY_ROLE)
def list_cycles():
    status = _filter("status")
    formula_variant = _filter("formula_variant")
    rows = ordered(db.cycles.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if formula_variant is not None:
        rows = [r for r in rows if r["formula_variant"] == formula_variant]
    limit, offset, total, page = _page(rows)
    return collection([ser.allocation_cycle(r) for r in page], limit, offset, total)


@bp.get("/efap/allocation-cycles/<cycle_id>")
@endpoint(*ANY_ROLE)
def read_cycle(cycle_id):
    return ok(ser.allocation_cycle(svc.cycle(cycle_id)))


@bp.post("/efap/allocation-cycles/<cycle_id>/compute-allocations")
@endpoint("StateAdmin")
def compute_allocations(cycle_id):
    row = svc.cycle(cycle_id)
    if row["status"] != "DRAFT":
        fail("ERR_INVALID_CYCLE_STATE", "The cycle is %s" % row["status"])
    included = [
        agency
        for agency in ordered(db.agencies.values())
        if agency["eligibility_posture"] == "ELIGIBLE"
    ]
    if not included:
        fail("ERR_NO_ELIGIBLE_AGENCIES", "No agency currently holds posture ELIGIBLE")
    for code in row["offered_commodity_codes"]:
        if _commodity_by_code(code) is None:
            fail("ERR_COMMODITY_NOT_FOUND", "No commodity has code %s" % code)
    plans = []
    for agency in included:
        area = db.service_areas.get(agency["service_area_id"])
        plans.append(
            {
                "agency": agency,
                "poverty_population": area["poverty_population"] if area else 0,
                "area_eligible_count": area["eligible_agency_count"] if area else 0,
                "prior_pounds": agency["prior_period_pounds_distributed"],
                "prior_cases": agency["prior_period_allocated_cases"],
            }
        )
    failure = calc.compute_allocation(plans, row["allocatable_cases"], row["formula_variant"])
    if failure is not None:
        fail(failure, "The allocation cannot be funded as specified")
    for plan in plans:
        entitlement = base_row()
        entitlement.update(
            {
                "cycle_id": row["id"],
                "agency_id": plan["agency"]["id"],
                "poverty_factor": plan["poverty_factor"],
                "poverty_share": plan["poverty_share"],
                "prior_share": plan["prior_share"],
                "raw_score": plan["raw_score"],
                "floor_cases": plan["floor_cases"],
                "allocated_cases": plan["allocated_cases"],
                "cases_committed": 0,
                "cases_delivered": 0,
                "cases_remaining": plan["allocated_cases"],
                "distributed_pounds": calc.ZERO_2,
                "distribution_record_count": 0,
                "record_compliance_pct": calc.ZERO_4,
                "admin_funds_base_cents": 0,
                "admin_funds_withheld_cents": 0,
                "admin_funds_cents": 0,
                "status": "ENTITLED",
            }
        )
        db.allocations[entitlement["id"]] = entitlement
    row["total_allocated_cases"] = sum(plan["allocated_cases"] for plan in plans)
    row["eligible_agency_count"] = len(plans)
    row["allocation_locked_at"] = now()
    row["status"] = "ALLOCATED"
    touch(row)
    return ok(ser.allocation_cycle(row))


@bp.post("/efap/allocation-cycles/<cycle_id>/open-window")
@endpoint("StateAdmin")
def open_window(cycle_id):
    row = svc.cycle(cycle_id)
    if row["status"] != "ALLOCATED":
        fail("ERR_INVALID_CYCLE_STATE", "The cycle is %s" % row["status"])
    if now() >= row["order_window_close_at"]:
        fail("ERR_ORDER_WINDOW_CLOSED", "The order window has already closed")
    row["status"] = "OPEN"
    touch(row)
    return ok(ser.allocation_cycle(row))


@bp.post("/efap/allocation-cycles/<cycle_id>/close-window")
@endpoint("StateAdmin")
def close_window(cycle_id):
    row = svc.cycle(cycle_id)
    if row["status"] != "OPEN":
        fail("ERR_INVALID_CYCLE_STATE", "The cycle is %s" % row["status"])
    for order_row in ordered(db.orders.values()):
        if order_row["cycle_id"] == row["id"] and order_row["status"] == "DRAFT":
            svc.cancel_order(order_row, "WINDOW_CLOSED")
    row["status"] = "CLOSED"
    touch(row)
    return ok(ser.allocation_cycle(row))


@bp.post("/efap/allocation-cycles/<cycle_id>/finalize")
@endpoint("StateAdmin")
def finalize_cycle(cycle_id):
    row = svc.cycle(cycle_id)
    if row["status"] != "CLOSED":
        fail("ERR_INVALID_CYCLE_STATE", "The cycle is %s" % row["status"])
    for order_row in ordered(db.orders.values()):
        if order_row["cycle_id"] != row["id"]:
            continue
        if order_row["status"] in UNSETTLED_ORDER_STATUSES:
            fail(
                "ERR_INVALID_ORDER_STATE",
                "An order of this cycle is still %s" % order_row["status"],
            )
    rows = [r for r in ordered(db.allocations.values()) if r["cycle_id"] == row["id"]]
    if rows:
        calc.compute_admin_funds(
            rows, row["admin_funds_pool_cents"], row["total_allocated_cases"]
        )
    for entitlement in rows:
        entitlement["status"] = "RECONCILED"
        touch(entitlement)
    row["admin_funds_allocated_cents"] = sum(r["admin_funds_cents"] for r in rows)
    row["status"] = "RECONCILED"
    touch(row)
    return ok(ser.allocation_cycle(row))


@bp.get("/efap/allocation-cycles/<cycle_id>/allocations")
@endpoint(*ANY_ROLE)
def list_cycle_allocations(cycle_id):
    row = svc.cycle(cycle_id)
    rows = [r for r in ordered(db.allocations.values()) if r["cycle_id"] == row["id"]]
    limit, offset, total, page = _page(rows)
    return collection([ser.agency_allocation(r) for r in page], limit, offset, total)


@bp.get("/efap/allocation-cycles/<cycle_id>/admin-funds-report")
@endpoint(*ANY_ROLE)
def admin_funds_report(cycle_id):
    row = svc.cycle(cycle_id)
    rows = [r for r in ordered(db.allocations.values()) if r["cycle_id"] == row["id"]]
    withheld_total = sum(r["admin_funds_withheld_cents"] for r in rows)
    redistributed_total = sum(
        r["admin_funds_cents"] - r["admin_funds_base_cents"] + r["admin_funds_withheld_cents"]
        for r in rows
    )
    return ok(
        {
            "cycle_code": row["cycle_code"],
            "admin_funds_pool_cents": row["admin_funds_pool_cents"],
            "admin_funds_allocated_cents": row["admin_funds_allocated_cents"],
            "withheld_cents_total": withheld_total,
            "redistributed_cents_total": redistributed_total,
            "allocation_line_count": len(rows),
            "non_compliant_line_count": sum(
                1 for r in rows if r["admin_funds_withheld_cents"] > 0
            ),
        }
    )


# ---------------------------------------------------------------------------
# AgencyAllocation reads (PRD §3.4)
# ---------------------------------------------------------------------------
@bp.get("/efap/agency-allocations")
@endpoint(*ANY_ROLE)
def list_allocations():
    cycle_id = _filter("cycle_id")
    agency_id = _filter("agency_id")
    status = _filter("status")
    rows = ordered(db.allocations.values())
    if cycle_id is not None:
        rows = [r for r in rows if r["cycle_id"] == cycle_id]
    if agency_id is not None:
        rows = [r for r in rows if r["agency_id"] == agency_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    limit, offset, total, page = _page(rows)
    return collection([ser.agency_allocation(r) for r in page], limit, offset, total)


@bp.get("/efap/agency-allocations/<agency_allocation_id>")
@endpoint(*ANY_ROLE)
def read_allocation(agency_allocation_id):
    return ok(ser.agency_allocation(svc.allocation(agency_allocation_id)))


# ---------------------------------------------------------------------------
# CommodityOrder (PRD §3.5)
# ---------------------------------------------------------------------------
@bp.post("/efap/commodity-orders")
@endpoint("AgencyCoordinator")
def create_order():
    payload = body()
    val.req_id(payload, "cycle_id")
    val.req_id(payload, "agency_id")
    val.req_id(payload, "warehouse_id")
    expected = val.req_int(payload, "expected_agency_allocation_version")
    cycle_row = svc.cycle(payload["cycle_id"])
    agency_row = svc.agency(payload["agency_id"])
    house = svc.warehouse(payload["warehouse_id"])
    if g.user_id != agency_row["id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "An order may only be placed by its own agency")
    entitlement = svc.allocation_for(cycle_row["id"], agency_row["id"])
    if entitlement is not None and entitlement["version"] != expected:
        fail(
            "ERR_STALE_VERSION",
            "expected_agency_allocation_version %s does not match %s"
            % (expected, entitlement["version"]),
        )
    if cycle_row["status"] not in ("ALLOCATED", "OPEN"):
        fail("ERR_INVALID_CYCLE_STATE", "The cycle is %s" % cycle_row["status"])
    if entitlement is None:
        fail("ERR_ALLOCATION_NOT_FOUND", "The agency holds no entitlement in this cycle")
    for existing in ordered(db.orders.values()):
        if (
            existing["cycle_id"] == cycle_row["id"]
            and existing["agency_id"] == agency_row["id"]
            and existing["status"] == "DRAFT"
        ):
            svc.cancel_order(existing, "SUPERSEDED")
    row = base_row()
    row.update(
        {
            "cycle_id": cycle_row["id"],
            "agency_id": agency_row["id"],
            "warehouse_id": house["id"],
            "status": "DRAFT",
            "line_count": 0,
            "total_cases_requested": 0,
            "total_cases_approved": 0,
            "total_pounds": calc.ZERO_2,
            "total_pallets": 0,
            "revision_count": 0,
            "last_returned_by_user_id": None,
            "approved_by_user_id": None,
            "submitted_at": None,
            "approved_at": None,
            "cancel_reason": None,
        }
    )
    db.orders[row["id"]] = row
    touch(entitlement)
    return created(ser.commodity_order(row))


@bp.get("/efap/commodity-orders")
@endpoint(*ANY_ROLE)
def list_orders():
    cycle_id = _filter("cycle_id")
    agency_id = _filter("agency_id")
    warehouse_id = _filter("warehouse_id")
    status = _filter("status")
    rows = ordered(db.orders.values())
    if cycle_id is not None:
        rows = [r for r in rows if r["cycle_id"] == cycle_id]
    if agency_id is not None:
        rows = [r for r in rows if r["agency_id"] == agency_id]
    if warehouse_id is not None:
        rows = [r for r in rows if r["warehouse_id"] == warehouse_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    limit, offset, total, page = _page(rows)
    return collection([ser.commodity_order(r) for r in page], limit, offset, total)


@bp.get("/efap/commodity-orders/<order_id>")
@endpoint(*ANY_ROLE)
def read_order(order_id):
    return ok(ser.commodity_order(svc.order(order_id)))


@bp.post("/efap/commodity-orders/<order_id>/lines")
@endpoint("AgencyCoordinator")
def add_line(order_id):
    row = svc.order(order_id)
    payload = body()
    val.req_id(payload, "commodity_id")
    cases_requested = val.req_int(payload, "cases_requested", minimum=1)
    item = svc.commodity(payload["commodity_id"])
    if g.user_id != row["agency_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "Only the ordering agency may add lines")
    if row["status"] != "DRAFT":
        fail("ERR_INVALID_ORDER_STATE", "The order is %s" % row["status"])
    cycle_row = svc.cycle(row["cycle_id"])
    if cycle_row["status"] not in ("ALLOCATED", "OPEN"):
        fail("ERR_INVALID_CYCLE_STATE", "The cycle is %s" % cycle_row["status"])
    house = svc.warehouse(row["warehouse_id"])
    storage_class = item["storage_class"]
    pools = {
        "DRY": house["dry_pallet_capacity"],
        "COLD": house["cold_pallet_capacity"],
        "FROZEN": house["frozen_pallet_capacity"],
    }
    if pools[storage_class] <= 0:
        fail(
            "ERR_STORAGE_CLASS_UNSUPPORTED",
            "The warehouse has no %s capacity" % storage_class,
        )
    if storage_class == "FROZEN":
        agency_row = svc.agency(row["agency_id"])
        if agency_row["cold_storage_pallet_capacity"] <= 0:
            fail(
                "ERR_STORAGE_CLASS_UNSUPPORTED",
                "The agency has no cold storage capacity",
            )
    _require_offered(cycle_row, item)
    line = base_row()
    line.update(
        {
            "order_id": row["id"],
            "commodity_id": item["id"],
            "cases_requested": cases_requested,
            "cases_approved": 0,
            "line_pounds": calc.ZERO_2,
            "line_pallets": 0,
            "storage_class": storage_class,
            "lot_assignments": [],
        }
    )
    db.order_lines[line["id"]] = line
    svc.refresh_order_request_totals(row)
    touch(row)
    return created(ser.order_line(line))


@bp.get("/efap/commodity-orders/<order_id>/lines")
@endpoint(*ANY_ROLE)
def list_order_lines_of(order_id):
    row = svc.order(order_id)
    rows = svc.lines_of(row["id"])
    limit, offset, total, page = _page(rows)
    return collection([ser.order_line(r) for r in page], limit, offset, total)


@bp.post("/efap/commodity-orders/<order_id>/submit")
@endpoint("AgencyCoordinator")
def submit_order(order_id):
    row = svc.order(order_id)
    if g.user_id != row["agency_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "Only the ordering agency may submit")
    if row["status"] != "DRAFT":
        fail("ERR_INVALID_ORDER_STATE", "The order is %s" % row["status"])
    agency_row = svc.agency(row["agency_id"])
    svc.require_posture(agency_row, ("ELIGIBLE",))
    cycle_row = svc.cycle(row["cycle_id"])
    lines = svc.lines_of(row["id"])
    for line in lines:
        item = db.commodities.get(line["commodity_id"])
        if item is not None:
            _require_offered(cycle_row, item)
    stamp = now()
    if cycle_row["status"] != "OPEN" or stamp < cycle_row["order_window_open_at"]:
        fail("ERR_ORDER_WINDOW_NOT_OPEN", "The order window is not open")
    if stamp >= cycle_row["order_window_close_at"]:
        fail("ERR_ORDER_WINDOW_CLOSED", "The order window has closed")
    if not lines:
        fail("ERR_EMPTY_ORDER", "The order carries no lines")
    entitlement = svc.allocation_for(cycle_row["id"], row["agency_id"])
    if entitlement is None:
        fail("ERR_ALLOCATION_NOT_FOUND", "The agency holds no entitlement in this cycle")
    if row["total_cases_requested"] > entitlement["cases_remaining"]:
        fail(
            "ERR_ALLOCATION_EXCEEDED",
            "Only %d cases remain on the entitlement" % entitlement["cases_remaining"],
        )
    row["status"] = "SUBMITTED"
    row["submitted_at"] = stamp
    touch(row)
    return ok(ser.commodity_order(row))


@bp.post("/efap/commodity-orders/<order_id>/return-for-revision")
@endpoint("ComplianceReviewer")
def return_order(order_id):
    row = svc.order(order_id)
    if row["status"] != "SUBMITTED":
        fail("ERR_INVALID_ORDER_STATE", "The order is %s" % row["status"])
    row["status"] = "DRAFT"
    row["revision_count"] = row["revision_count"] + 1
    row["last_returned_by_user_id"] = g.user_id
    touch(row)
    return ok(ser.commodity_order(row))


@bp.post("/efap/commodity-orders/<order_id>/approve")
@endpoint("ComplianceReviewer")
def approve_order(order_id):
    row = svc.order(order_id)
    payload = body()
    lines = svc.lines_of(row["id"])
    by_id = {line["id"]: line for line in lines}
    adjustments = {}
    if val.present(payload, "line_adjustments"):
        for entry in val.req_object_array(payload, "line_adjustments", 200):
            line_id = val.req_id(entry, "order_line_id")
            line = by_id.get(line_id)
            if line is None:
                fail(
                    "ERR_INVALID_REQUEST",
                    "line_adjustments names a line outside this order",
                )
            cases = val.req_int(
                entry, "cases_approved", minimum=1, maximum=line["cases_requested"]
            )
            adjustments[line_id] = cases
    if row["status"] != "SUBMITTED":
        fail("ERR_INVALID_ORDER_STATE", "The order is %s" % row["status"])
    cycle_row = svc.cycle(row["cycle_id"])
    if cycle_row["status"] not in ("OPEN", "CLOSED"):
        fail("ERR_INVALID_CYCLE_STATE", "The cycle is %s" % cycle_row["status"])
    agency_row = svc.agency(row["agency_id"])
    svc.require_posture(agency_row, ("ELIGIBLE",))
    if row["revision_count"] > 0 and g.user_id == row["last_returned_by_user_id"]:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The reviewer who returned this order may not approve it",
        )
    approvals = {
        line["id"]: adjustments.get(line["id"], line["cases_requested"]) for line in lines
    }
    plan = svc.fefo_plan(row, approvals)
    if plan is None:
        fail("ERR_INSUFFICIENT_INVENTORY", "FEFO lots cannot cover every approved line")
    total_approved = sum(approvals.values())
    entitlement = svc.allocation_for(row["cycle_id"], row["agency_id"])
    if entitlement is None:
        fail("ERR_ALLOCATION_NOT_FOUND", "The agency holds no entitlement in this cycle")
    if total_approved > entitlement["cases_remaining"]:
        fail(
            "ERR_ALLOCATION_EXCEEDED",
            "Only %d cases remain on the entitlement" % entitlement["cases_remaining"],
        )

    # commit — per-line rounding precedes summation (PRD §3.6)
    total_pounds = calc.ZERO_2
    total_pallets = 0
    reserved = {}
    for line, assignments in plan:
        item = svc.commodity(line["commodity_id"])
        cases = approvals[line["id"]]
        line["cases_approved"] = cases
        line["line_pounds"] = calc.rhu(
            calc.dec(cases) * calc.dec(item["net_weight_lbs_per_case"]), 2
        )
        line["line_pallets"] = calc.ceil_int(
            calc.dec(cases) / calc.dec(item["cases_per_pallet"])
        )
        line["lot_assignments"] = [
            {"lot_id": entry["lot_id"], "cases": entry["cases"]} for entry in assignments
        ]
        total_pounds = total_pounds + line["line_pounds"]
        total_pallets = total_pallets + line["line_pallets"]
        for entry in assignments:
            reserved[entry["lot_id"]] = reserved.get(entry["lot_id"], 0) + entry["cases"]
        touch(line)
    for lot_id, cases in reserved.items():
        target = db.lots[lot_id]
        target["cases_committed"] = target["cases_committed"] + cases
        touch(target)
    row["total_cases_approved"] = total_approved
    row["total_pounds"] = calc.rhu(total_pounds, 2)
    row["total_pallets"] = total_pallets
    row["approved_at"] = now()
    row["approved_by_user_id"] = g.user_id
    row["status"] = "APPROVED"
    touch(row)
    entitlement["cases_committed"] = entitlement["cases_committed"] + total_approved
    svc.refresh_allocation(entitlement)
    return ok(ser.commodity_order(row))


@bp.post("/efap/commodity-orders/<order_id>/cancel")
@endpoint("AgencyCoordinator", "StateAdmin")
def cancel_order_endpoint(order_id):
    row = svc.order(order_id)
    payload = body()
    cancel_reason = val.req_string(payload, "cancel_reason", 1, 400)
    if g.role == "AgencyCoordinator" and g.user_id != row["agency_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "Only the ordering agency may cancel")
    if row["status"] not in CANCELLABLE_ORDER_STATUSES:
        fail("ERR_INVALID_ORDER_STATE", "The order is %s" % row["status"])
    svc.cancel_order(row, cancel_reason)
    return ok(ser.commodity_order(row))


# ---------------------------------------------------------------------------
# OrderLine reads (PRD §3.5)
# ---------------------------------------------------------------------------
@bp.get("/efap/order-lines")
@endpoint(*ANY_ROLE)
def list_order_lines():
    order_id = _filter("order_id")
    commodity_id = _filter("commodity_id")
    rows = ordered(db.order_lines.values())
    if order_id is not None:
        rows = [r for r in rows if r["order_id"] == order_id]
    if commodity_id is not None:
        rows = [r for r in rows if r["commodity_id"] == commodity_id]
    limit, offset, total, page = _page(rows)
    return collection([ser.order_line(r) for r in page], limit, offset, total)


@bp.get("/efap/order-lines/<order_line_id>")
@endpoint(*ANY_ROLE)
def read_order_line(order_line_id):
    return ok(ser.order_line(svc.order_line(order_line_id)))


# ---------------------------------------------------------------------------
# DeliveryAppointment (PRD §3.7)
# ---------------------------------------------------------------------------
@bp.post("/efap/delivery-appointments")
@endpoint("StateWarehouseOperator", "StateAdmin")
def create_appointment():
    payload = body()
    val.req_id(payload, "order_id")
    dock_number = val.req_int(payload, "dock_number", minimum=1)
    window_start = val.req_datetime(payload, "window_start")
    window_end = val.req_datetime(payload, "window_end")
    if window_end <= window_start:
        fail("ERR_INVALID_REQUEST", "window_end must be after window_start")
    order_row = svc.order(payload["order_id"])
    house = svc.warehouse(order_row["warehouse_id"])
    if dock_number > house["dock_count"]:
        fail(
            "ERR_INVALID_REQUEST",
            "dock_number must be at most the warehouse dock_count (%d)"
            % house["dock_count"],
        )
    if order_row["status"] == "HELD":
        fail("ERR_RECALL_HOLD_ACTIVE", "A recall holds inventory reserved by this order")
    # An order only reaches SCHEDULED or DELIVERED by owning a live appointment,
    # so the sharper of the two codes is reported for those states (PRD §3.7).
    if svc.live_appointment(order_row["id"]) is not None:
        fail("ERR_APPOINTMENT_ALREADY_EXISTS", "The order already has a live appointment")
    if order_row["status"] != "APPROVED":
        fail("ERR_INVALID_ORDER_STATE", "The order is %s" % order_row["status"])
    if window_start < now():
        fail("ERR_APPOINTMENT_WINDOW_INVALID", "window_start must not be in the past")
    if svc.dock_conflict(
        house["id"], dock_number, window_start, window_end, order_row["id"]
    ):
        fail("ERR_DOCK_WINDOW_CONFLICT", "The dock is occupied inside the turnaround buffer")
    pallets = {"DRY": 0, "COLD": 0, "FROZEN": 0}
    for line in svc.lines_of(order_row["id"]):
        pallets[line["storage_class"]] += line["line_pallets"]
    peers_b = svc.staging_peers(house["id"], window_start, window_end, order_row["id"])
    capacities = {
        "DRY": house["dry_pallet_capacity"],
        "COLD": house["cold_pallet_capacity"],
        "FROZEN": house["frozen_pallet_capacity"],
    }
    keys = {"DRY": "dry_pallets", "COLD": "cold_pallets", "FROZEN": "frozen_pallets"}
    for storage_class in ("DRY", "COLD", "FROZEN"):
        used = sum(peer[keys[storage_class]] for peer in peers_b)
        if pallets[storage_class] + used > capacities[storage_class]:
            fail(
                "ERR_WAREHOUSE_COLD_CAPACITY_EXCEEDED",
                "%s staging capacity would be exceeded" % storage_class,
            )
    agency_row = svc.agency(order_row["agency_id"])
    peers_c = svc.agency_peers(agency_row["id"], window_start, window_end, order_row["id"])
    frozen_used = sum(peer["frozen_pallets"] for peer in peers_c)
    if pallets["FROZEN"] + frozen_used > agency_row["cold_storage_pallet_capacity"]:
        fail(
            "ERR_AGENCY_COLD_STORAGE_EXCEEDED",
            "The agency cold storage ceiling would be exceeded",
        )
    row = base_row()
    row.update(
        {
            "order_id": order_row["id"],
            "warehouse_id": house["id"],
            "agency_id": agency_row["id"],
            "dock_number": dock_number,
            "window_start": window_start,
            "window_end": window_end,
            "dry_pallets": pallets["DRY"],
            "cold_pallets": pallets["COLD"],
            "frozen_pallets": pallets["FROZEN"],
            "delivered_pounds": calc.ZERO_2,
            "status": "SCHEDULED",
            "confirmed_by_user_id": None,
            "cancel_reason": None,
        }
    )
    db.appointments[row["id"]] = row
    order_row["status"] = "SCHEDULED"
    touch(order_row)
    return created(ser.delivery_appointment(row))


@bp.get("/efap/delivery-appointments")
@endpoint(*ANY_ROLE)
def list_appointments():
    order_id = _filter("order_id")
    warehouse_id = _filter("warehouse_id")
    agency_id = _filter("agency_id")
    status = _filter("status")
    rows = ordered(db.appointments.values())
    if order_id is not None:
        rows = [r for r in rows if r["order_id"] == order_id]
    if warehouse_id is not None:
        rows = [r for r in rows if r["warehouse_id"] == warehouse_id]
    if agency_id is not None:
        rows = [r for r in rows if r["agency_id"] == agency_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    limit, offset, total, page = _page(rows)
    return collection([ser.delivery_appointment(r) for r in page], limit, offset, total)


@bp.get("/efap/delivery-appointments/<appointment_id>")
@endpoint(*ANY_ROLE)
def read_appointment(appointment_id):
    return ok(ser.delivery_appointment(svc.appointment(appointment_id)))


@bp.post("/efap/delivery-appointments/<appointment_id>/confirm-delivery")
@endpoint("StateWarehouseOperator")
def confirm_delivery(appointment_id):
    row = svc.appointment(appointment_id)
    if g.user_id != row["warehouse_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "Only the receiving warehouse may confirm")
    if row["status"] != "SCHEDULED":
        fail("ERR_INVALID_APPOINTMENT_STATE", "The appointment is %s" % row["status"])
    order_row = svc.order(row["order_id"])
    lines = svc.lines_of(order_row["id"])
    for line in lines:
        for entry in line["lot_assignments"]:
            target = db.lots.get(entry["lot_id"])
            if target is None or target["status"] not in svc.LIVE_LOT_STATUSES:
                fail("ERR_RECALL_HOLD_ACTIVE", "A reserved lot is not available")
    agency_row = svc.agency(row["agency_id"])
    svc.require_posture(agency_row, ("ELIGIBLE", "PROBATION"))
    stamp = now()
    if stamp < row["window_start"]:
        fail("ERR_APPOINTMENT_WINDOW_INVALID", "The delivery window has not started")

    debits = {}
    for line in lines:
        for entry in line["lot_assignments"]:
            debits[entry["lot_id"]] = debits.get(entry["lot_id"], 0) + entry["cases"]
    for lot_id, cases in debits.items():
        target = db.lots[lot_id]
        target["cases_on_hand"] = target["cases_on_hand"] - cases
        target["cases_committed"] = target["cases_committed"] - cases
        target["cases_shipped_to_date"] = target["cases_shipped_to_date"] + cases
        svc.deplete_if_empty(target)
        touch(target)
    row["delivered_pounds"] = calc.rhu(order_row["total_pounds"], 2)
    row["confirmed_by_user_id"] = g.user_id
    row["status"] = "DELIVERED"
    touch(row)
    approved = order_row["total_cases_approved"]
    order_row["status"] = "DELIVERED"
    touch(order_row)
    entitlement = svc.allocation_for(order_row["cycle_id"], order_row["agency_id"])
    if entitlement is not None:
        entitlement["cases_committed"] = entitlement["cases_committed"] - approved
        entitlement["cases_delivered"] = entitlement["cases_delivered"] + approved
        svc.refresh_allocation(entitlement)
    agency_row["agency_cases_on_hand"] = agency_row["agency_cases_on_hand"] + approved
    agency_row["delivered_cases_ytd"] = agency_row["delivered_cases_ytd"] + approved
    touch(agency_row)
    return ok(ser.delivery_appointment(row))


@bp.post("/efap/delivery-appointments/<appointment_id>/cancel")
@endpoint("StateAdmin")
def cancel_appointment(appointment_id):
    row = svc.appointment(appointment_id)
    payload = body()
    cancel_reason = val.req_string(payload, "cancel_reason", 1, 400)
    if row["status"] not in ("SCHEDULED", "BLOCKED"):
        fail("ERR_INVALID_APPOINTMENT_STATE", "The appointment is %s" % row["status"])
    was_scheduled = row["status"] == "SCHEDULED"
    row["status"] = "CANCELLED"
    row["cancel_reason"] = cancel_reason
    touch(row)
    order_row = db.orders.get(row["order_id"])
    if order_row is not None and was_scheduled and order_row["status"] == "SCHEDULED":
        # commitments are retained; only the dock slot is released
        order_row["status"] = "APPROVED"
        touch(order_row)
    return ok(ser.delivery_appointment(row))


# ---------------------------------------------------------------------------
# HouseholdDistribution (PRD §3.9)
# ---------------------------------------------------------------------------
@bp.post("/efap/household-distributions")
@endpoint("AgencyCoordinator")
def record_distribution():
    payload = body()
    val.req_id(payload, "agency_id")
    val.req_id(payload, "cycle_id")
    val.req_id(payload, "commodity_id")
    household_size = val.req_int(payload, "household_size", minimum=1, maximum=20)
    income_cents = val.req_int(payload, "declared_monthly_income_cents", minimum=0)
    participates = val.opt_bool(payload, "participates_in_snap", False)
    signed = val.req_bool(payload, "self_declaration_signed")
    cases_distributed = val.req_int(payload, "cases_distributed", minimum=1)
    distribution_date = val.req_date(payload, "distribution_date")
    agency_row = svc.agency(payload["agency_id"])
    cycle_row = svc.cycle(payload["cycle_id"])
    item = svc.commodity(payload["commodity_id"])
    if g.user_id != agency_row["id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "Only the distributing agency may record")
    if cycle_row["status"] == "RECONCILED":
        fail("ERR_INVALID_CYCLE_STATE", "The cycle is RECONCILED")
    svc.require_posture(agency_row, ("ELIGIBLE", "PROBATION"))
    limit_cents = calc.income_limit_cents(household_size)
    if income_cents <= limit_cents:
        determination = "ELIGIBLE"
    elif participates:
        determination = "CATEGORICALLY_ELIGIBLE"
    else:
        fail(
            "ERR_HOUSEHOLD_INELIGIBLE",
            "Declared income exceeds the %d cent limit" % limit_cents,
        )
    _require_offered(cycle_row, item)
    entitlement = svc.allocation_for(cycle_row["id"], agency_row["id"])
    if entitlement is None:
        fail("ERR_ALLOCATION_NOT_FOUND", "The agency holds no entitlement in this cycle")
    if cases_distributed > agency_row["agency_cases_on_hand"]:
        fail(
            "ERR_AGENCY_INVENTORY_INSUFFICIENT",
            "The agency holds only %d cases" % agency_row["agency_cases_on_hand"],
        )
    row = base_row()
    row.update(
        {
            "agency_id": agency_row["id"],
            "cycle_id": cycle_row["id"],
            "commodity_id": item["id"],
            "household_size": household_size,
            "declared_monthly_income_cents": income_cents,
            "participates_in_snap": participates,
            "self_declaration_signed": signed,
            "cases_distributed": cases_distributed,
            "distribution_date": distribution_date,
            "pounds_distributed": calc.rhu(
                calc.dec(cases_distributed) * calc.dec(item["net_weight_lbs_per_case"]), 2
            ),
            "income_limit_cents": limit_cents,
            "eligibility_determination": determination,
            "status": "RECORDED",
            "void_reason": None,
        }
    )
    db.distributions[row["id"]] = row
    agency_row["agency_cases_on_hand"] = (
        agency_row["agency_cases_on_hand"] - cases_distributed
    )
    touch(agency_row)
    svc.recompute_rollup(cycle_row["id"], agency_row["id"])
    return created(ser.household_distribution(row))


@bp.get("/efap/household-distributions")
@endpoint(*ANY_ROLE)
def list_distributions():
    agency_id = _filter("agency_id")
    cycle_id = _filter("cycle_id")
    commodity_id = _filter("commodity_id")
    status = _filter("status")
    rows = ordered(db.distributions.values())
    if agency_id is not None:
        rows = [r for r in rows if r["agency_id"] == agency_id]
    if cycle_id is not None:
        rows = [r for r in rows if r["cycle_id"] == cycle_id]
    if commodity_id is not None:
        rows = [r for r in rows if r["commodity_id"] == commodity_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    limit, offset, total, page = _page(rows)
    return collection([ser.household_distribution(r) for r in page], limit, offset, total)


@bp.get("/efap/household-distributions/<distribution_id>")
@endpoint(*ANY_ROLE)
def read_distribution(distribution_id):
    return ok(ser.household_distribution(svc.distribution(distribution_id)))


@bp.post("/efap/household-distributions/<distribution_id>/void")
@endpoint("AgencyCoordinator")
def void_distribution(distribution_id):
    row = svc.distribution(distribution_id)
    payload = body()
    void_reason = val.req_string(payload, "void_reason", 1, 400)
    if g.user_id != row["agency_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "Only the distributing agency may void")
    if row["status"] != "RECORDED":
        fail("ERR_INVALID_DISTRIBUTION_STATE", "The record is %s" % row["status"])
    cycle_row = svc.cycle(row["cycle_id"])
    if cycle_row["status"] == "RECONCILED":
        fail("ERR_INVALID_CYCLE_STATE", "The cycle is RECONCILED")
    row["status"] = "VOIDED"
    row["void_reason"] = void_reason
    touch(row)
    agency_row = svc.agency(row["agency_id"])
    agency_row["agency_cases_on_hand"] = (
        agency_row["agency_cases_on_hand"] + row["cases_distributed"]
    )
    touch(agency_row)
    svc.recompute_rollup(row["cycle_id"], row["agency_id"])
    return ok(ser.household_distribution(row))
