"""Period shrink/markdown reconciliation figures (PRD §3.9)."""

from calc import ZERO, rhu, rhu_int
from db import db, mark

IN_SCOPE_PLAN_STATUSES = ("PUBLISHED", "CLOSED")


def plans_in_period(department_id, start_date, end_date, statuses=None):
    rows = []
    for plan in db.case_plans.values():
        if plan["department_id"] != department_id:
            continue
        if not (start_date <= plan["service_date"] <= end_date):
            continue
        if statuses is not None and plan["plan_status"] not in statuses:
            continue
        rows.append(plan)
    return rows


def scope_lines(department_id, start_date, end_date):
    """Scope lines in ascending plan service_date then ascending line_seq."""
    ordered = []
    plans = plans_in_period(department_id, start_date, end_date,
                            IN_SCOPE_PLAN_STATUSES)
    for plan in sorted(plans, key=lambda p: (p["service_date"], p["_seq"])):
        lines = [line for line in db.case_plan_lines.values()
                 if line["case_plan_id"] == plan["id"]]
        for line in sorted(lines, key=lambda l: l["line_seq"]):
            ordered.append(line)
    return ordered


def compute_figures(row, department):
    lines = scope_lines(row["department_id"], row["period_start_date"],
                        row["period_end_date"])

    expected = ZERO
    physical = ZERO
    markdown_dollars = 0
    shrink_dollars = 0

    for line in lines:
        if row["basis"] == "YIELD_MODEL":
            expected += line["required_fill_lb"]
            physical += line["actual_fill_lb"]
        else:                                      # PHYSICAL_COUNT
            expected += line["actual_fill_lb"]
            physical += (line["actual_fill_lb"] - line["markdown_lb"]
                         - line["shrink_lb"])
        markdown_dollars += line["markdown_dollars_cents"]
        item = db.retail_items.get(line["retail_item_id"])
        active_price = item["active_price_per_lb_cents"] if item is not None else 0
        shrink_dollars += rhu_int(line["shrink_lb"] * active_price)

    row["expected_salable_lb"] = rhu(expected, 2)
    row["physical_salable_lb"] = rhu(physical, 2)
    row["variance_lb"] = rhu(row["physical_salable_lb"]
                             - row["expected_salable_lb"], 2)
    if row["expected_salable_lb"] == 0:
        row["variance_pct"] = rhu(0, 4)
    else:
        row["variance_pct"] = rhu(row["variance_lb"] / row["expected_salable_lb"], 4)
    row["within_tolerance"] = abs(row["variance_pct"]) <= department["shrink_tolerance_pct"]
    row["markdown_dollars_cents"] = markdown_dollars
    row["shrink_dollars_cents"] = shrink_dollars


def close_reconciled_purchases(row):
    """Posting closes the department's cut-tested purchases inside the period."""
    for purchase in db.primal_purchases.values():
        if purchase["department_id"] != row["department_id"]:
            continue
        if purchase["status"] != "CUT_TESTED":
            continue
        received_date = purchase["_received_at"].date().isoformat()
        if not (row["period_start_date"] <= received_date <= row["period_end_date"]):
            continue
        purchase["status"] = "RECONCILED"
        mark(purchase)
