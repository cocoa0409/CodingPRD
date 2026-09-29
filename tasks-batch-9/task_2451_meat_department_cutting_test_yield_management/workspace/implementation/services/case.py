"""Case-plan execution, cold-chain posture and the halt cascade.

PRD §2.7, §2.9, §3.6, §3.7.
"""

from datetime import timedelta

from calc import ZERO, rhu
from db import db, mark, sort_rows, today


# --------------------------------------------------------------------------
# collections
# --------------------------------------------------------------------------

def lines_of_plan(plan_id):
    rows = [line for line in db.case_plan_lines.values()
            if line["case_plan_id"] == plan_id]
    return sorted(rows, key=lambda line: line["line_seq"])


def plans_of_department(department_id):
    return sort_rows([plan for plan in db.case_plans.values()
                      if plan["department_id"] == department_id])


def staged_pre_orders_on(line_id, statuses):
    return sort_rows([order for order in db.pre_orders.values()
                      if order.get("staged_case_plan_line_id") == line_id
                      and order["status"] in statuses])


# --------------------------------------------------------------------------
# derived plan fields (PRD §2.9)
# --------------------------------------------------------------------------

def derive_fill_status(total_actual, total_required):
    if total_actual <= 0:
        return "UNFILLED"
    if total_actual < total_required:
        return "PARTIAL"
    return "FILLED"


def recompute_plan_totals(plan):
    lines = lines_of_plan(plan["id"])
    expected = ZERO
    required = ZERO
    actual = ZERO
    for line in lines:
        expected += line["expected_movement_lb"]
        required += line["required_fill_lb"]
        actual += line["actual_fill_lb"]
    fresh = {
        "total_expected_movement_lb": rhu(expected, 2),
        "total_required_fill_lb": rhu(required, 2),
        "total_actual_fill_lb": rhu(actual, 2),
    }
    fresh["fill_status"] = derive_fill_status(fresh["total_actual_fill_lb"],
                                             fresh["total_required_fill_lb"])
    changed = any(plan[key] != value for key, value in fresh.items())
    plan.update(fresh)
    if changed:
        mark(plan)


def apply_fill(line, pounds):
    """Add pounds to a case line, dating it on the first fill (PRD §3.6)."""
    first_fill = line["pack_date"] is None
    line["actual_fill_lb"] = rhu(line["actual_fill_lb"] + pounds, 2)
    if first_fill:
        item = db.retail_items[line["retail_item_id"]]
        pack_date = today()
        line["pack_date"] = pack_date.isoformat()
        line["sell_by_date"] = (
            pack_date + timedelta(days=int(item["shelf_life_days"]))).isoformat()
    if line["line_status"] == "PLANNED":
        line["line_status"] = "FILLED"
    mark(line)
    plan = db.case_plans.get(line["case_plan_id"])
    if plan is not None:
        recompute_plan_totals(plan)


def release_pounds_from_fill(line, pounds):
    """Pickup removes pounds from both staged_lb and actual_fill_lb."""
    line["staged_lb"] = rhu(line["staged_lb"] - pounds, 2)
    line["actual_fill_lb"] = rhu(line["actual_fill_lb"] - pounds, 2)
    mark(line)
    plan = db.case_plans.get(line["case_plan_id"])
    if plan is not None:
        recompute_plan_totals(plan)


def release_staged_pounds(line, pounds):
    """Cancellation / forfeiture releases the staging reservation only."""
    line["staged_lb"] = rhu(line["staged_lb"] - pounds, 2)
    mark(line)


# --------------------------------------------------------------------------
# suspension / resumption hops (PRD §3.7)
# --------------------------------------------------------------------------

def suspend_plan(plan, failure=None):
    plan["plan_status"] = "SUSPENDED"
    mark(plan)
    for line in lines_of_plan(plan["id"]):
        if line["line_status"] not in ("FILLED", "MARKED_DOWN"):
            continue
        line["held_from_status"] = line["line_status"]
        line["line_status"] = "HELD"
        mark(line)
        if failure is not None:
            failure["affected_line_count"] = failure["affected_line_count"] + 1
            mark(failure)
        for order in staged_pre_orders_on(line["id"], ("STAGED",)):
            order["status"] = "HELD"
            mark(order)


def resume_plan(plan):
    plan["plan_status"] = "PUBLISHED"
    mark(plan)
    for line in lines_of_plan(plan["id"]):
        if line["line_status"] != "HELD":
            continue
        line["line_status"] = line["held_from_status"] or "FILLED"
        line["held_from_status"] = None
        mark(line)
        for order in staged_pre_orders_on(line["id"], ("HELD",)):
            order["status"] = "STAGED"
            mark(order)


def halt_cascade(department, failure=None):
    """Hops 2-4 of the cold-chain halt (PRD §3.7)."""
    current = today().isoformat()
    for plan in plans_of_department(department["id"]):
        if plan["plan_status"] != "PUBLISHED":
            continue
        if plan["service_date"] < current:
            continue
        suspend_plan(plan, failure)


# --------------------------------------------------------------------------
# posture (PRD §3.7)
# --------------------------------------------------------------------------

def recompute_posture(department):
    if department["open_case_failure_count"] >= 1:
        posture = "SALES_HALTED"
    elif (department["contained_case_failure_count"] >= 1
          or department["consecutive_out_of_spec_readings"] >= 1):
        posture = "SALES_RESTRICTED"
    else:
        posture = "SALES_OPEN"
    if department["case_posture"] != posture:
        department["case_posture"] = posture
        mark(department)
    return posture
