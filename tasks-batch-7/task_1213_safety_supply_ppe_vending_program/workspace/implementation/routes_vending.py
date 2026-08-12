"""Vend routes: issuance creation (badge swipe), listing, reversal."""
from datetime import timedelta

from flask import Blueprint, g

import db
from auth import require_roles
from envelope import ok, ok_list
from errors import err
from helpers import (body, covering_override, find_policy, get_or_404,
                     latest_fit_test, month_cumulative, opt_str, paged,
                     pagination_params, par_trigger, qparam, req_int,
                     req_str, resolve_price, rolling_usage)
from util import clock_date, new_record, touch

bp = Blueprint("vending", __name__)


@bp.post("/issuances")
def create_issuance():
    require_roles("Employee")
    emp = g.employee  # entity-backed identity, resolved by auth
    b = body()
    machine_id = req_str(b, "machine_id")
    slot_id = req_str(b, "slot_id")
    qty = req_int(b, "qty", minimum=1)
    key = req_str(b, "idempotency_key")
    unit_id = opt_str(b, "serialized_unit_id")
    mo_id = opt_str(b, "manager_override_id")

    # existence: path/body FKs in canonical order
    machine = get_or_404(db.machines, machine_id, "ERR_MACHINE_NOT_FOUND")
    slot = get_or_404(db.slots, slot_id, "ERR_SLOT_NOT_FOUND")
    unit = None
    if unit_id is not None:
        unit = get_or_404(db.units, unit_id, "ERR_SERIALIZED_UNIT_NOT_FOUND")
    named_override = None
    if mo_id is not None:
        named_override = get_or_404(db.overrides, mo_id, "ERR_MANAGER_OVERRIDE_NOT_FOUND")

    # idempotency replay (before every business gate)
    for t in db.issuances.values():
        if t["idempotency_key"] == key:
            same = (t["machine_id"] == machine_id and t["slot_id"] == slot_id
                    and t["qty"] == qty
                    and t.get("serialized_unit_id") == unit_id
                    and t.get("manager_override_id") == mo_id)
            if same:
                return ok(t, 201)  # replay of the original transaction
            err("ERR_IDEMPOTENCY_CONFLICT",
                "idempotency_key reused with a different payload")

    # state gates
    if emp["status"] != "ACTIVE":
        err("ERR_EMPLOYEE_NOT_ACTIVE", "vend requires an ACTIVE employee")
    if machine["status"] != "ACTIVE":
        err("ERR_MACHINE_NOT_ACTIVE", "vend requires machine ACTIVE")
    item = db.items.get(slot["item_id"])
    if item is None:
        err("ERR_ITEM_NOT_FOUND", "slot item missing")
    if item["status"] != "ACTIVE":
        err("ERR_ITEM_DISCONTINUED", "item is DISCONTINUED")

    # target-state: a named override must be the unique covering ACTIVE override
    covering = covering_override(emp["id"], item["id"])
    if mo_id is not None and (covering is None or covering["id"] != mo_id):
        err("ERR_OVERRIDE_NOT_ACTIVE",
            "override not ACTIVE, window does not cover today, or id mismatch")

    # safety: respirator fit-test linkage
    if item["requires_fit_test"]:
        latest = latest_fit_test(emp, item["id"])
        if (latest is None or latest["result"] != "PASS"
                or latest["status"] == "EXPIRED"):
            err("ERR_FIT_TEST_REQUIRED",
                "no current PASS fit test for this respirator item")

    # safety: fall-protection linkage
    if item["serialized_tracking"]:
        if unit is not None and unit["status"] != "IN_STOCK":
            err("ERR_SERIALIZED_UNIT_NOT_ISSUABLE", "unit is not IN_STOCK")
        for u in db.units.values():
            if (u["item_id"] == item["id"]
                    and u.get("issued_to_employee_id") == emp["id"]
                    and u["status"] in ("INSPECTION_DUE", "QUARANTINED")):
                err("ERR_REGULATED_ITEM_INSPECTION_DUE",
                    "employee holds a lapsed unit of this item")

    # structural integrity (pinned sub-order)
    if slot["machine_id"] != machine_id:
        err("ERR_SLOT_ITEM_MISMATCH", "slot does not belong to machine")
    if item["serialized_tracking"] and unit_id is None:
        err("ERR_SERIALIZED_UNIT_REQUIRED",
            "FALL_PROTECTION vend requires serialized_unit_id")
    if not item["serialized_tracking"] and unit_id is not None:
        err("ERR_SERIALIZED_UNIT_REQUIRED",
            "serialized_unit_id forbidden for a non-serialized item")
    if item["serialized_tracking"] and qty != 1:
        err("ERR_SERIALIZED_QTY_INVALID", "FALL_PROTECTION vend requires qty == 1")
    if unit is not None and (unit["slot_id"] != slot_id
                             or unit["item_id"] != item["id"]):
        err("ERR_SLOT_ITEM_MISMATCH", "unit slot/item mismatch")

    # entitlement
    policy = find_policy(emp["job_role_id"], item["id"])
    if policy is None:
        err("ERR_ITEM_NOT_ENTITLED", "no issuance policy for this role and item")

    # issuance limit and override draw split (pinned evaluation order)
    usage = rolling_usage(emp["id"], item["id"], policy["period_window_days"])
    base = policy["period_limit_qty"]
    drawn = 0
    if usage + qty <= base:
        drawn = 0
    elif covering is not None:
        needed = (usage + qty) - max(base, usage)
        remaining = covering["approved_qty"] - covering["consumed_qty"]
        if needed > remaining:
            err("ERR_OVERRIDE_QTY_EXCEEDED", "override draw exceeds remaining_qty")
        drawn = needed
    else:
        err("ERR_ISSUANCE_LIMIT_EXCEEDED", "usage + qty exceeds policy limit")

    # pricing at vend time
    vend_dt = db.clock
    vend_date = clock_date()
    cum_before = month_cumulative(emp["home_cost_center_id"], item["id"], vend_date)
    unit_price = resolve_price(item, vend_date, cum_before)
    line_total = unit_price * qty

    if mo_id is not None:
        stored_mo = mo_id
    elif drawn > 0 and covering is not None:
        stored_mo = covering["id"]
    else:
        stored_mo = None

    rec = new_record({
        "employee_id": emp["id"],
        "machine_id": machine_id,
        "slot_id": slot_id,
        "item_id": item["id"],
        "serialized_unit_id": unit_id,
        "qty": qty,
        "unit_price_cents": unit_price,
        "line_total_cents": line_total,
        "cost_center_id": emp["home_cost_center_id"],
        "manager_override_id": stored_mo,
        "override_drawn_qty": drawn,
        "idempotency_key": key,
        "vended_at": vend_dt,
        "chargeback_batch_id": None,
        "status": "POSTED",
    })
    db.issuances[rec["id"]] = rec

    # physical + fiscal side effects, same breath
    slot["on_hand_qty"] -= qty
    touch(slot)
    if drawn > 0 and covering is not None:
        covering["consumed_qty"] += drawn
        if covering["consumed_qty"] == covering["approved_qty"]:
            covering["status"] = "CONSUMED"
        touch(covering)
    if unit is not None:
        unit["status"] = "ISSUED"
        unit["issued_to_employee_id"] = emp["id"]
        due = vend_date + timedelta(days=item["inspection_interval_days"])
        unit["next_inspection_due_on"] = due.isoformat()
        touch(unit)
    par_trigger(slot)
    return ok(rec, 201)


@bp.get("/issuances")
def list_issuances():
    require_roles("Any")
    limit, offset = pagination_params()
    rows = list(db.issuances.values())
    for param in ("employee_id", "machine_id", "slot_id", "item_id",
                  "cost_center_id", "manager_override_id", "serialized_unit_id",
                  "chargeback_batch_id", "status"):
        v = qparam(param)
        if v is not None:
            rows = [t for t in rows if t.get(param) == v]
    page, total = paged(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/issuances/<issuanceId>")
def get_issuance(issuanceId):
    require_roles("Any")
    return ok(get_or_404(db.issuances, issuanceId, "ERR_ISSUANCE_NOT_FOUND"))


@bp.post("/issuances/<issuanceId>/reverse")
def reverse_issuance(issuanceId):
    require_roles("Manager")
    body()
    t = get_or_404(db.issuances, issuanceId, "ERR_ISSUANCE_NOT_FOUND")
    if t["status"] != "POSTED":
        err("ERR_ISSUANCE_ALREADY_REVERSED", "issuance is not POSTED")
    if g.user_id == t["employee_id"]:
        err("ERR_SELF_REVERSAL_FORBIDDEN", "manager cannot reverse their own vend")
    open_batch = None
    if t.get("chargeback_batch_id"):
        billed = db.batches.get(t["chargeback_batch_id"])
        if billed is not None and billed["status"] != "OPEN":
            for bt in db.batches.values():
                if (bt["cost_center_id"] == t["cost_center_id"]
                        and bt["status"] == "OPEN"):
                    if open_batch is None or bt["_seq"] < open_batch["_seq"]:
                        open_batch = bt
            if open_batch is None:
                err("ERR_NO_OPEN_CHARGEBACK_BATCH",
                    "reversal of a billed line requires an OPEN batch")

    t["status"] = "REVERSED"
    touch(t)

    slot = db.slots.get(t["slot_id"])
    if slot is not None:
        slot["on_hand_qty"] += t["qty"]
        touch(slot)
        # restock auto-cancel cascade: restored stock strictly above par
        if slot["on_hand_qty"] > slot["par_level"]:
            for o in db.restock_orders.values():
                if o["slot_id"] == slot["id"] and o["status"] == "SUGGESTED":
                    o["status"] = "CANCELLED"
                    touch(o)

    if t.get("serialized_unit_id"):
        unit = db.units.get(t["serialized_unit_id"])
        if unit is not None and unit["status"] in ("ISSUED", "INSPECTION_DUE"):
            unit["status"] = "IN_STOCK"
            unit["issued_to_employee_id"] = None
            unit["next_inspection_due_on"] = None
            touch(unit)

    # ManagerOverride.consumed_qty is NEVER restored (consumption is final).
    if open_batch is not None:
        open_batch["adjustment_cents"] -= t["line_total_cents"]
        touch(open_batch)
    return ok(t)
