"""Cutting-test metrics, market-value cost allocation and the approval cascade.

PRD §3.2, §3.3, §2.6.
"""

from calc import ZERO, rhu, rhu_int
from db import db, mark
from services import pricing

CANDIDATE_DISPOSITIONS = ("SALABLE_CUT", "GRIND_TRIM")


def lines_of_test(test_id):
    rows = [line for line in db.cutting_test_lines.values()
            if line["cutting_test_id"] == test_id]
    return sorted(rows, key=lambda line: line["line_seq"])


def tests_of_purchase(purchase_id):
    rows = [test for test in db.cutting_tests.values()
            if test["primal_purchase_id"] == purchase_id]
    return sorted(rows, key=lambda test: (test["created_at"], test["_seq"]))


# --------------------------------------------------------------------------
# yield metrics (PRD §3.2)
# --------------------------------------------------------------------------

def recompute_metrics(test):
    lines = lines_of_test(test["id"])
    bench = test["test_weight_lb"]
    total = ZERO
    by_disposition = {"SALABLE_CUT": ZERO, "GRIND_TRIM": ZERO, "FAT_BONE_LOSS": ZERO}
    for line in lines:
        total += line["yield_weight_lb"]
        by_disposition[line["disposition"]] += line["yield_weight_lb"]

    test["total_yield_weight_lb"] = rhu(total, 2)
    test["unaccounted_lb"] = rhu(bench - total, 2)
    if bench > 0:
        test["salable_yield_pct"] = rhu(by_disposition["SALABLE_CUT"] / bench, 4)
        test["trim_yield_pct"] = rhu(by_disposition["GRIND_TRIM"] / bench, 4)
        test["loss_pct"] = rhu(by_disposition["FAT_BONE_LOSS"] / bench, 4)
    else:
        test["salable_yield_pct"] = rhu(0, 4)
        test["trim_yield_pct"] = rhu(0, 4)
        test["loss_pct"] = rhu(0, 4)
    mark(test)


def market_value_base(test):
    """Sum of market_value_per_lb_cents * yield_weight_lb over candidate lines."""
    base = ZERO
    for line in lines_of_test(test["id"]):
        if line["disposition"] in CANDIDATE_DISPOSITIONS:
            base += line["market_value_per_lb_cents"] * line["yield_weight_lb"]
    return base


def has_zero_valued_candidate(test):
    for line in lines_of_test(test["id"]):
        if (line["disposition"] in CANDIDATE_DISPOSITIONS
                and line["market_value_per_lb_cents"] <= 0):
            return True
    return False


# --------------------------------------------------------------------------
# allocation (PRD §3.3)
# --------------------------------------------------------------------------

def allocate(test, purchase):
    landed_total = purchase["landed_cost_total_cents"]
    candidates = [line for line in lines_of_test(test["id"])
                  if line["disposition"] in CANDIDATE_DISPOSITIONS]

    weights = {}
    base = ZERO
    for line in candidates:
        weight = line["market_value_per_lb_cents"] * line["yield_weight_lb"]
        weights[line["id"]] = weight
        base += weight

    allocated_sum = 0
    for line in candidates:                       # ascending line_seq order
        cents = rhu_int(landed_total * weights[line["id"]] / base)
        line["allocated_cost_cents"] = cents
        allocated_sum += cents

    remainder = landed_total - allocated_sum
    if remainder != 0 and candidates:
        # greatest yield_weight_lb wins; ties break to the lower line_seq.
        target = candidates[0]
        for line in candidates[1:]:
            if line["yield_weight_lb"] > target["yield_weight_lb"]:
                target = line
        target["allocated_cost_cents"] = target["allocated_cost_cents"] + remainder

    for line in candidates:
        if line["yield_weight_lb"] == 0:
            line["allocated_cost_per_lb_cents"] = rhu(0, 4)
        else:
            line["allocated_cost_per_lb_cents"] = rhu(
                line["allocated_cost_cents"] / line["yield_weight_lb"], 4)
        mark(line)


def approval_cascade(test, purchase):
    """The four hops of PRD §3.3."""
    lines = lines_of_test(test["id"])

    # hop 1 — the purchase ledger
    allocated = sum(line["allocated_cost_cents"] for line in lines)
    purchase["allocated_cost_cents"] = allocated
    purchase["unallocated_cost_cents"] = purchase["landed_cost_total_cents"] - allocated
    purchase["status"] = "CUT_TESTED"
    mark(purchase)

    department = db.departments.get(purchase["department_id"])

    for line in lines:
        if line["disposition"] != "SALABLE_CUT":
            continue
        item = db.retail_items.get(line.get("retail_item_id"))
        if item is None:
            continue
        # hop 2 — the measured cost basis
        item["yield_adjusted_cost_per_lb_cents"] = line["allocated_cost_per_lb_cents"]
        mark(item)
        # hops 3 and 4
        item_department = db.departments.get(item["department_id"]) or department
        if item_department is not None:
            pricing.recompute_final_after_cost_change(item, item_department)


def rewind_purchase_ledger(purchase):
    """PRD §2.6 — superseding an approved test rewinds with no drift."""
    purchase["allocated_cost_cents"] = 0
    purchase["unallocated_cost_cents"] = purchase["landed_cost_total_cents"]
    purchase["status"] = "RECEIVED"
    mark(purchase)


def supersede_existing_tests(purchase):
    """Returns True when at least one test was driven to SUPERSEDED."""
    superseded_any = False
    rewind_needed = False
    for test in tests_of_purchase(purchase["id"]):
        if test["status"] not in ("SUBMITTED", "APPROVED"):
            continue
        was_approved = test["status"] == "APPROVED"
        test["status"] = "SUPERSEDED"
        mark(test)
        superseded_any = True
        if was_approved:
            rewind_needed = True
            for line in lines_of_test(test["id"]):
                line["allocated_cost_cents"] = 0
                line["allocated_cost_per_lb_cents"] = rhu(0, 4)
                mark(line)
    if rewind_needed:
        rewind_purchase_ledger(purchase)
    return superseded_any
