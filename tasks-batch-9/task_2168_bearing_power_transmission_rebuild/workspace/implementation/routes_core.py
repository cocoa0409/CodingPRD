"""Core units: receipt, reads and the core lifecycle."""

from flask import Blueprint

import bench_ops
import calc
import ledger
import store
import validate as v
import views
from auth import ALL_ROLES, CORE_UNIT_ACTIONS, authenticate, require_action_role, require_roles
from errors import fail
from response import created, listing, ok

bp = Blueprint("core", __name__)

GRADES = {"GRADE_A", "GRADE_B", "GRADE_C", "GRADE_D", "SCRAP"}
CORE_ACTIONS = {"REINSPECT", "SCRAP", "RETURN_AS_IS"}


def path_core(cid):
    rec = store.get("core_units", cid)
    if rec is None:
        fail("ERR_CORE_UNIT_NOT_FOUND", "Core unit %s not found" % cid)
    return rec


def orders_for_core(core_id):
    return store.sorted_rows(
        [o for o in store.all_rows("orders") if o["core_unit_id"] == core_id]
    )


@bp.post("/shop/core-units")
def receive_core():
    _, role = authenticate()
    require_roles(role, ["ShopAdmin"])
    body = v.body()
    customer_id = v.req_fk(body, "customer_id")
    standard_id = v.req_fk(body, "clearance_standard_id")
    serial_no = v.req_str(body, "serial_no")
    rebuild_count = v.opt_int(body, "rebuild_count", 0, minimum=0)
    declared = v.req_enum(body, "declared_condition_grade", GRADES)

    customer = store.get("customers", customer_id)
    if customer is None:
        fail("ERR_CUSTOMER_NOT_FOUND", "Customer %s not found" % customer_id)
    standard = store.get("standards", standard_id)
    if standard is None:
        fail("ERR_STANDARD_NOT_FOUND", "Clearance standard %s not found" % standard_id)

    for row in store.all_rows("core_units"):
        if row["customer_id"] == customer_id and row["serial_no"] == serial_no:
            fail("ERR_DUPLICATE_SERIAL", "serial_no already received for this account")

    provisional = calc.core_credit_valuation(
        standard["base_core_value_cents"], declared, rebuild_count
    )

    rec = store.base_record()
    rec.update({
        "customer_id": customer_id,
        "clearance_standard_id": standard_id,
        "serial_no": serial_no,
        "model_code": standard["model_code"],
        "rebuild_count": rebuild_count,
        "declared_condition_grade": declared,
        "condition_grade": None,
        "status": "RECEIVED",
        "provisional_core_credit_cents": provisional,
        "final_core_credit_cents": None,
        "replacement_core_unit_id": None,
    })
    store.insert("core_units", rec)

    ledger.post_note(
        customer_id, "CORE_EXCHANGE", provisional,
        core_unit_id=rec["id"], memo="provisional exchange-core credit",
    )
    ledger.settle(customer, reprice=False)
    return created(views.render("core_units", rec))


@bp.get("/shop/core-units/<cid>")
def read_core(cid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = path_core(cid)
    views.require_owner(role, uid, "core_units", rec)
    return ok(views.render("core_units", rec))


@bp.get("/shop/core-units")
def list_cores():
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    limit, offset = v.pagination()
    rows = store.all_rows("core_units")
    for key in ("customer_id", "clearance_standard_id", "replacement_core_unit_id", "status"):
        value = v.qparam(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    rows = views.scope_rows(role, uid, "core_units", rows)
    rows = store.sorted_rows(rows)
    page, total = v.paginate(rows, limit, offset)
    return listing(views.render_many("core_units", page), limit, offset, total)


# ---------------------------------------------------------------------------
# advance
# ---------------------------------------------------------------------------
@bp.post("/shop/core-units/<cid>/advance")
def advance_core(cid):
    _, role = authenticate()
    require_roles(role, ["ShopAdmin", "Inspector"])
    raw = v.body()
    require_action_role(role, raw.get("action"), CORE_UNIT_ACTIONS)
    core = path_core(cid)
    action = v.req_enum(raw, "action", CORE_ACTIONS)
    override_reason = v.opt_str(raw, "override_reason", None)
    replacement_id = v.opt_fk(raw, "replacement_core_unit_id")

    replacement = None
    if replacement_id is not None:
        replacement = store.get("core_units", replacement_id)
        if replacement is None:
            fail("ERR_CORE_UNIT_NOT_FOUND", "Replacement core %s not found" % replacement_id)

    if action == "REINSPECT":
        _reinspect(core)
    elif action == "SCRAP":
        _scrap(core, override_reason, replacement)
    else:
        _return_as_is(core)
    return ok(views.render("core_units", core))


def _reinspect(core):
    if core["status"] != "GRADED":
        fail("ERR_CORE_UNIT_INVALID_STATE", "core is not GRADED")
    for order in orders_for_core(core["id"]):
        if order["work_status"] in ("IN_PROGRESS", "COMPLETED", "DELIVERED"):
            fail("ERR_CORE_UNIT_INVALID_STATE", "a rebuild order on this core has started")

    for order in orders_for_core(core["id"]):
        for insp in store.sorted_rows(store.all_rows("inspections")):
            if insp["rebuild_order_id"] == order["id"] and insp["status"] == "ACCEPTED":
                insp["status"] = "RETURNED"
                insp["return_reason"] = "core re-inspection ordered"
                store.touch(insp)

    core["condition_grade"] = None
    core["final_core_credit_cents"] = None
    core["status"] = "INSPECTING"
    store.touch(core)
    ledger.void_core_note_and_settle(core, "core re-inspection ordered", reprice=True)


def _scrap(core, override_reason, replacement):
    if core["status"] != "GRADED":
        fail("ERR_CORE_UNIT_INVALID_STATE", "core is not GRADED")
    if core.get("condition_grade") != "SCRAP":
        if not (override_reason and override_reason.strip()):
            fail("ERR_CORE_UNIT_INVALID_STATE",
                 "override_reason is required to scrap a non-SCRAP core")
    if replacement is not None:
        if (replacement["status"] != "RECEIVED"
                or replacement["customer_id"] != core["customer_id"]
                or replacement["clearance_standard_id"] != core["clearance_standard_id"]):
            fail("ERR_CORE_UNIT_INVALID_STATE", "replacement core is not eligible")

    core["status"] = "SCRAPPED"
    core["replacement_core_unit_id"] = replacement["id"] if replacement is not None else None
    store.touch(core)

    ledger.void_core_note_and_settle(core, "core scrapped", reprice=True)

    for order in orders_for_core(core["id"]):
        if order["work_status"] in ("DRAFT", "QUOTED", "SCHEDULED"):
            order["work_status"] = "CANCELLED"
            order["cancel_reason"] = "core scrapped"
            store.touch(order)
            bench_ops.release_order_reservations(order, statuses=("HELD", "CONFIRMED"))


def _return_as_is(core):
    if core["status"] not in ("RECEIVED", "GRADED"):
        fail("ERR_CORE_UNIT_INVALID_STATE", "core may not be returned as-is from this state")
    was_graded = core["status"] == "GRADED"
    core["status"] = "RETURNED_AS_IS"
    store.touch(core)
    ledger.void_core_note_and_settle(core, "core returned as-is", reprice=was_graded)
