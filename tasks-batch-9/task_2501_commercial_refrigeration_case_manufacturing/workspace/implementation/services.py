"""Shared row helpers, counter recomputation and the cascade chains."""

from flask import g

from calculations import warranty_accrual_cents, warranty_incurred_cents
from db import db, now_iso, rows
from errors import (
    ERR_CASE_MODEL_NOT_FOUND,
    ERR_COMPLIANCE_LABEL_NOT_FOUND,
    ERR_ENERGY_STANDARD_NOT_FOUND,
    ERR_ENERGY_TEST_NOT_FOUND,
    ERR_INSTALL_BOOKING_NOT_FOUND,
    ERR_INSTALL_CREW_NOT_FOUND,
    ERR_PART_INVENTORY_NOT_FOUND,
    ERR_REFRIGERANT_NOT_FOUND,
    ERR_SHIPMENT_NOT_FOUND,
    ERR_STORE_PLAN_LINE_NOT_FOUND,
    ERR_STORE_PLAN_NOT_FOUND,
    ERR_TEST_CHAMBER_NOT_FOUND,
    ERR_WARRANTY_CLAIM_NOT_FOUND,
    ERR_WORK_ORDER_NOT_FOUND,
    fail,
)


# --------------------------------------------------------------------------
# mutation bookkeeping
# --------------------------------------------------------------------------
def touch(row):
    """Refresh updated_at and increment version once per request per row."""
    if "version" not in row:
        return
    touched = getattr(g, "touched_rows", None)
    if touched is None:
        touched = set()
        g.touched_rows = touched
    if row["id"] in touched:
        return
    touched.add(row["id"])
    row["updated_at"] = now_iso()
    row["version"] = row["version"] + 1


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------
def _get(collection, row_id, err):
    if not isinstance(row_id, str):
        fail(err)
    row = collection.get(row_id)
    if row is None:
        fail(err, "No such resource: %s" % row_id)
    return row


def get_refrigerant(rid):
    return _get(db.refrigerants, rid, ERR_REFRIGERANT_NOT_FOUND)


def get_energy_standard(rid):
    return _get(db.energy_standards, rid, ERR_ENERGY_STANDARD_NOT_FOUND)


def get_test_chamber(rid):
    return _get(db.test_chambers, rid, ERR_TEST_CHAMBER_NOT_FOUND)


def get_case_model(rid):
    return _get(db.case_models, rid, ERR_CASE_MODEL_NOT_FOUND)


def get_energy_test(rid):
    return _get(db.energy_tests, rid, ERR_ENERGY_TEST_NOT_FOUND)


def get_compliance_label(rid):
    return _get(db.compliance_labels, rid, ERR_COMPLIANCE_LABEL_NOT_FOUND)


def get_store_plan(rid):
    return _get(db.store_plans, rid, ERR_STORE_PLAN_NOT_FOUND)


def get_store_plan_line(rid):
    return _get(db.store_plan_lines, rid, ERR_STORE_PLAN_LINE_NOT_FOUND)


def get_work_order(rid):
    return _get(db.work_orders, rid, ERR_WORK_ORDER_NOT_FOUND)


def get_shipment(rid):
    return _get(db.shipments, rid, ERR_SHIPMENT_NOT_FOUND)


def get_install_crew(rid):
    return _get(db.install_crews, rid, ERR_INSTALL_CREW_NOT_FOUND)


def get_install_booking(rid):
    return _get(db.install_bookings, rid, ERR_INSTALL_BOOKING_NOT_FOUND)


def get_part_inventory(rid):
    return _get(db.part_inventories, rid, ERR_PART_INVENTORY_NOT_FOUND)


def get_warranty_claim(rid):
    return _get(db.warranty_claims, rid, ERR_WARRANTY_CLAIM_NOT_FOUND)


# --------------------------------------------------------------------------
# collection scans (always created_at ascending)
# --------------------------------------------------------------------------
def plan_lines(plan_id):
    return [r for r in rows(db.store_plan_lines) if r["store_plan_id"] == plan_id]


def plan_work_orders(plan_id):
    return [r for r in rows(db.work_orders) if r["store_plan_id"] == plan_id]


def model_lines(case_model_id):
    return [r for r in rows(db.store_plan_lines) if r["case_model_id"] == case_model_id]


def model_labels(case_model_id):
    return [r for r in rows(db.compliance_labels) if r["case_model_id"] == case_model_id]


def model_tests(case_model_id):
    return [r for r in rows(db.energy_tests) if r["case_model_id"] == case_model_id]


def shipment_bookings(shipment_id):
    return [r for r in rows(db.install_bookings) if r["shipment_id"] == shipment_id]


def shipment_work_orders(shipment_id):
    return [r for r in rows(db.work_orders) if r["shipment_id"] == shipment_id]


def crew_bookings(crew_id):
    return [r for r in rows(db.install_bookings) if r["install_crew_id"] == crew_id]


def plan_claims(plan_id):
    out = []
    for claim in rows(db.warranty_claims):
        wo = db.work_orders.get(claim["work_order_id"])
        if wo is not None and wo["store_plan_id"] == plan_id:
            out.append(claim)
    return out


# --------------------------------------------------------------------------
# counter recomputation
# --------------------------------------------------------------------------
def recompute_line_counters(plan):
    lines = plan_lines(plan["id"])
    plan["line_count"] = len(lines)
    plan["unit_count"] = sum(line["quantity"] for line in lines)


def recompute_held_line_count(plan):
    lines = plan_lines(plan["id"])
    plan["held_line_count"] = sum(1 for line in lines if line["compliance_hold"])


def recompute_unit_counters(plan):
    work_orders = plan_work_orders(plan["id"])
    plan["units_completed_count"] = sum(
        1 for wo in work_orders if wo["status"] in ("COMPLETE", "SHIPPED")
    )
    plan["units_shipped_count"] = sum(1 for wo in work_orders if wo["status"] == "SHIPPED")


def recompute_part_availability(part):
    part["available_qty"] = part["on_hand_qty"] - part["reserved_qty"]
    part["below_min"] = part["available_qty"] < part["min_stock_qty"]


def recompute_warranty_accrual(plan):
    plan["warranty_reserve_accrual_cents"] = warranty_accrual_cents(
        plan_work_orders(plan["id"])
    )


def recompute_warranty_incurred(plan):
    plan["warranty_reserve_incurred_cents"] = warranty_incurred_cents(
        plan_claims(plan["id"])
    )


def crew_committed_case_days(crew_id):
    total = 0
    for booking in crew_bookings(crew_id):
        if booking["status"] == "BOOKED":
            total += booking["cases_committed"] * booking["day_count"]
    return total


def recompute_crew_commitment(crew):
    crew["committed_case_days"] = crew_committed_case_days(crew["id"])


# --------------------------------------------------------------------------
# hold cascades (PRD 2.8 / 3.4 / 3.5)
# --------------------------------------------------------------------------
def apply_compliance_hold_cascade(case_model):
    """Hops 3-5: hold lines, hold plans, freeze queued work orders."""
    touched_plans = []
    for line in model_lines(case_model["id"]):
        plan = db.store_plans.get(line["store_plan_id"])
        if plan is None or plan["production_status"] == "COMPLETE":
            continue
        if not line["compliance_hold"]:
            line["compliance_hold"] = True
            touch(line)
            if plan["id"] not in [p["id"] for p in touched_plans]:
                touched_plans.append(plan)

    for plan in touched_plans:
        recompute_held_line_count(plan)
        touch(plan)
        # hop 4
        if plan["commercial_status"] == "APPROVED" and plan["held_line_count"] > 0:
            plan["commercial_status"] = "HOLD_PENDING_RECERT"
            # hop 5 -- fires because the plan entered HOLD_PENDING_RECERT
            for wo in plan_work_orders(plan["id"]):
                if wo["status"] == "QUEUED":
                    wo["status"] = "HELD"
                    touch(wo)


def clear_compliance_hold_cascade(case_model):
    """Issuing a label unwinds the holds it once created (PRD 3.4)."""
    touched_plans = []
    for line in model_lines(case_model["id"]):
        plan = db.store_plans.get(line["store_plan_id"])
        if plan is None:
            continue
        if line["compliance_hold"]:
            line["compliance_hold"] = False
            touch(line)
            if plan["id"] not in [p["id"] for p in touched_plans]:
                touched_plans.append(plan)

    for plan in touched_plans:
        recompute_held_line_count(plan)
        touch(plan)
        if plan["commercial_status"] == "HOLD_PENDING_RECERT" and plan["held_line_count"] == 0:
            plan["commercial_status"] = "APPROVED"
            for wo in plan_work_orders(plan["id"]):
                if wo["status"] == "HELD":
                    wo["status"] = "QUEUED"
                    touch(wo)
