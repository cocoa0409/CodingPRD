"""Warranty claims, depot reservations and the reserve ledger (PRD 3.9)."""

from flask import Blueprint

import serialize
from calculations import WARRANTY_TERM_MONTHS
from db import add_months, db, new_row, rows
from errors import (
    ERR_CLAIM_OUT_OF_WARRANTY,
    ERR_INVALID_STATE_TRANSITION,
    ERR_PART_MODEL_MISMATCH,
    ERR_PART_REGION_MISMATCH,
    ERR_PARTS_UNAVAILABLE,
    fail,
)
from middleware import ALL_ROLES, roles_required
from response import created, ok, ok_list
from services import (
    get_install_crew,
    get_part_inventory,
    get_warranty_claim,
    get_work_order,
    recompute_part_availability,
    recompute_warranty_incurred,
    touch,
)
from validation import (
    filter_enum,
    filter_value,
    get_body,
    paginate,
    pagination,
    req_datetime,
    req_enum,
    req_int,
    req_string,
)

bp = Blueprint("service_network", __name__)

CLAIM_TYPES = ["COMPRESSOR_FAILURE", "DOOR_GASKET", "CONTROLLER", "GLASS_FOG"]
CLAIM_STATUSES = ["OPEN", "PARTS_RESERVED", "RESOLVED", "DENIED"]


def _plan_of_claim(claim):
    wo = db.work_orders.get(claim["work_order_id"])
    if wo is None:
        return None
    return db.store_plans.get(wo["store_plan_id"])


def _refresh_ledger(plan):
    if plan is None:
        return
    before = plan["warranty_reserve_incurred_cents"]
    recompute_warranty_incurred(plan)
    if plan["warranty_reserve_incurred_cents"] != before:
        touch(plan)


# --------------------------------------------------------------------------
@bp.post("/warranty-claims")
@roles_required("ServiceManager")
def create_warranty_claim():
    body = get_body()
    work_order_id = req_string(body, "work_order_id")
    part_inventory_id = req_string(body, "part_inventory_id")
    install_crew_id = req_string(body, "install_crew_id")
    claim_type = req_enum(body, "claim_type", CLAIM_TYPES)
    reported_raw, reported_date = req_datetime(body, "reported_date")
    requested_qty = req_int(body, "requested_qty", minimum=1)
    estimated_cost_cents = req_int(body, "estimated_cost_cents", minimum=0)

    work_order = get_work_order(work_order_id)      # rank 6, declaration order
    part = get_part_inventory(part_inventory_id)
    get_install_crew(install_crew_id)

    if part["case_model_id"] != work_order["case_model_id"]:  # rank 35
        fail(ERR_PART_MODEL_MISMATCH,
             "Part %s is not stocked for the claimed unit's model" % part["part_number"])

    plan = db.store_plans.get(work_order["store_plan_id"])
    plan_region = plan["region_code"] if plan is not None else None
    if part["region_code"] != plan_region:                    # rank 36
        fail(ERR_PART_REGION_MISMATCH,
             "Part %s sits in region %s, not %s"
             % (part["part_number"], part["region_code"], plan_region))

    term_months = WARRANTY_TERM_MONTHS[claim_type]
    start = work_order.get("_warranty_start_date")
    if start is None:
        in_warranty = False
    else:
        coverage_end = add_months(start, term_months)
        in_warranty = bool(start <= reported_date <= coverage_end)

    row = new_row()
    row.update({
        "work_order_id": work_order_id,
        "part_inventory_id": part_inventory_id,
        "install_crew_id": install_crew_id,
        "claim_type": claim_type,
        "reported_date": reported_raw,
        "_reported_date": reported_date,
        "requested_qty": requested_qty,
        "estimated_cost_cents": estimated_cost_cents,
        "warranty_term_months": term_months,
        "in_warranty": in_warranty,
        "parts_cost_cents": None,
        "labor_cost_cents": None,
        "total_cost_cents": None,
        "denial_reason": None,
        "status": "OPEN",
    })
    db.warranty_claims[row["id"]] = row

    _refresh_ledger(plan)
    return created(serialize.dump("WarrantyClaim", row))


@bp.post("/warranty-claims/<claim_id>/reserve-parts")
@roles_required("ServiceManager")
def reserve_parts(claim_id):
    get_body()
    claim = get_warranty_claim(claim_id)

    if claim["status"] != "OPEN":  # rank 7
        fail(ERR_INVALID_STATE_TRANSITION, "Only an OPEN claim may reserve parts")

    if not claim["in_warranty"]:   # rank 37
        fail(ERR_CLAIM_OUT_OF_WARRANTY, "The claimed unit is out of warranty")

    part = db.part_inventories.get(claim["part_inventory_id"])
    if part["available_qty"] < claim["requested_qty"]:  # rank 38
        fail(ERR_PARTS_UNAVAILABLE,
             "Depot has %d available, %d requested"
             % (part["available_qty"], claim["requested_qty"]))

    claim["parts_cost_cents"] = part["unit_cost_cents"] * claim["requested_qty"]
    claim["status"] = "PARTS_RESERVED"
    touch(claim)

    part["reserved_qty"] = part["reserved_qty"] + claim["requested_qty"]
    recompute_part_availability(part)
    touch(part)

    return ok(serialize.dump("WarrantyClaim", claim))


@bp.post("/warranty-claims/<claim_id>/resolve")
@roles_required("ServiceManager")
def resolve_claim(claim_id):
    body = get_body()
    labor_cost_cents = req_int(body, "labor_cost_cents", minimum=0)

    claim = get_warranty_claim(claim_id)
    if claim["status"] != "PARTS_RESERVED":  # rank 7
        fail(ERR_INVALID_STATE_TRANSITION,
             "Only a PARTS_RESERVED claim may be resolved")

    claim["labor_cost_cents"] = labor_cost_cents
    claim["total_cost_cents"] = (claim["parts_cost_cents"] or 0) + labor_cost_cents
    claim["status"] = "RESOLVED"
    touch(claim)

    part = db.part_inventories.get(claim["part_inventory_id"])
    if part is not None:
        part["on_hand_qty"] = part["on_hand_qty"] - claim["requested_qty"]
        part["reserved_qty"] = part["reserved_qty"] - claim["requested_qty"]
        recompute_part_availability(part)
        touch(part)

    _refresh_ledger(_plan_of_claim(claim))
    return ok(serialize.dump("WarrantyClaim", claim))


@bp.post("/warranty-claims/<claim_id>/deny")
@roles_required("ServiceManager")
def deny_claim(claim_id):
    body = get_body()
    denial_reason = req_string(body, "denial_reason")

    claim = get_warranty_claim(claim_id)
    if claim["status"] not in ("OPEN", "PARTS_RESERVED"):  # rank 7
        fail(ERR_INVALID_STATE_TRANSITION,
             "A %s claim may not be denied" % claim["status"])

    had_reservation = claim["status"] == "PARTS_RESERVED"
    claim["denial_reason"] = denial_reason
    claim["status"] = "DENIED"
    if had_reservation:
        claim["parts_cost_cents"] = None
    touch(claim)

    if had_reservation:
        part = db.part_inventories.get(claim["part_inventory_id"])
        if part is not None:
            part["reserved_qty"] = part["reserved_qty"] - claim["requested_qty"]
            recompute_part_availability(part)
            touch(part)

    _refresh_ledger(_plan_of_claim(claim))
    return ok(serialize.dump("WarrantyClaim", claim))


@bp.get("/warranty-claims/<claim_id>")
@roles_required(*ALL_ROLES)
def read_warranty_claim(claim_id):
    return ok(serialize.dump("WarrantyClaim", get_warranty_claim(claim_id)))


@bp.get("/warranty-claims")
@roles_required(*ALL_ROLES)
def list_warranty_claims():
    limit, offset = pagination()
    work_order_id = filter_value("work_order_id")
    part_inventory_id = filter_value("part_inventory_id")
    install_crew_id = filter_value("install_crew_id")
    status = filter_enum("status", CLAIM_STATUSES)

    items = rows(db.warranty_claims)
    if work_order_id is not None:
        items = [r for r in items if r["work_order_id"] == work_order_id]
    if part_inventory_id is not None:
        items = [r for r in items if r["part_inventory_id"] == part_inventory_id]
    if install_crew_id is not None:
        items = [r for r in items if r["install_crew_id"] == install_crew_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]

    page, total = paginate(items, limit, offset)
    return ok_list(serialize.dump_many("WarrantyClaim", page), limit, offset, total)
