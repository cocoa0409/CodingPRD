"""Receipt commitments and weekly actuals posts."""
from flask import Blueprint, request

from common import (F, ROLE_ADMIN, ROLE_BUYER, ROLE_VENDOR, ANY_ROLE,
                    auth, fail, page_of, pagination, parse_input, public,
                    public_list, respond)
import calc
import store
import svc
from store import db, make_row, touch

bp = Blueprint("commit", __name__)


def _filter(rows, name, field=None):
    value = request.args.get(name)
    if value is None:
        return rows
    return [r for r in rows if r.get(field or name) == value]


COMMITMENT_FIELDS = [
    F("plan_month_id", "str", min_len=1),
    F("assortment_item_id", "str", min_len=1),
    F("vendor_id", "str", min_len=1),
    F("units", "int", minimum=1),
    F("unit_cost_cents", "int", minimum=1),
    F("ship_window_start", "datetime"),
    F("ship_window_end", "datetime"),
    F("expected_plan_month_version", "int", minimum=0),
]


def _posture_gates(plan, item):
    if plan["otb_posture"] == "FROZEN":
        fail("ERR_OTB_POSTURE_FROZEN", "the governing category plan is frozen")
    if plan["otb_posture"] == "RESTRICTED" and item["lifecycle_stage"] == "NEW":
        fail("ERR_POSTURE_RESTRICTED_NEW_ITEM",
             "a restricted plan may not open NEW options")


@bp.post("/otb/receipt-commitments")
def create_commitment():
    auth([ROLE_BUYER])
    data = parse_input(COMMITMENT_FIELDS)
    month = store.get_month(data["plan_month_id"])
    item = store.get_item(data["assortment_item_id"])
    vendor = store.get_vendor(data["vendor_id"])
    if month["status"] not in ("LOCKED_PLAN", "IN_SEASON"):
        fail("ERR_PLAN_MONTH_NOT_OPEN", "the plan month is %s" % month["status"])
    if data["expected_plan_month_version"] != month["version"]:
        fail("ERR_STALE_PLAN_MONTH_VERSION",
             "expected_plan_month_version does not match the stored version")
    plan = store.month_plan(month)
    _posture_gates(plan, item)
    authorization = calc.active_authorization(vendor["id"], plan["category_id"])
    if authorization is None:
        fail("ERR_VENDOR_NOT_AUTHORIZED_FOR_CATEGORY",
             "no ACTIVE authorization links this vendor to the plan's category")
    cell = db.optionplans.get(item["option_plan_id"])
    if cell is None or cell["category_plan_id"] != month["category_plan_id"] \
            or data["vendor_id"] != item["vendor_id"]:
        fail("ERR_PLAN_SCOPE_MISMATCH",
             "the item, the month and the vendor do not agree on scope")
    if data["units"] < vendor["min_order_units"]:
        fail("ERR_BELOW_VENDOR_MINIMUM",
             "units is below the vendor's min_order_units")
    start = store.dt(data["ship_window_start"])
    end = store.dt(data["ship_window_end"])
    calc.check_vendor_capacity(vendor, authorization, data["units"], start, end,
                               plan["category_id"])
    if not end > start:
        fail("ERR_SHIP_WINDOW_INVERTED",
             "ship_window_end must be strictly after ship_window_start")
    if start < store.clock() + calc.days(vendor["lead_time_days"]):
        fail("ERR_LEAD_TIME_INFEASIBLE",
             "ship_window_start is inside the vendor's lead time")
    cost = data["units"] * data["unit_cost_cents"]
    if cost > month["otb_open_cents"]:
        fail("ERR_OTB_EXCEEDED", "the commitment cost exceeds the month's open balance")
    row = make_row(
        plan_month_id=data["plan_month_id"],
        assortment_item_id=data["assortment_item_id"],
        vendor_id=data["vendor_id"],
        units=data["units"],
        unit_cost_cents=data["unit_cost_cents"],
        ship_window_start=data["ship_window_start"],
        ship_window_end=data["ship_window_end"],
        origin="BUYER",
        commit_status="PROPOSED",
        fulfillment_status="AWAITING_SHIP",
        received_units=0,
        cancelled_units=0,
        cost_cents=cost,
        open_cost_cents=data["units"] * data["unit_cost_cents"],
        received_cost_cents=0,
    )
    db.commitments[row["id"]] = row
    touch(month)
    return respond(public(row), 201)


@bp.get("/otb/receipt-commitments/<rid>")
def read_commitment(rid):
    auth(ANY_ROLE)
    return respond(public(store.get_commitment(rid)))


@bp.get("/otb/receipt-commitments")
def list_commitments():
    auth(ANY_ROLE)
    limit, offset = pagination()
    rows = store.by_seq(list(db.commitments.values()))
    rows = _filter(rows, "plan_month_id")
    rows = _filter(rows, "assortment_item_id")
    rows = _filter(rows, "vendor_id")
    rows = _filter(rows, "commit_status")
    rows = _filter(rows, "fulfillment_status")
    window, meta = page_of(rows, limit, offset)
    return respond(public_list(window), 200, meta)


def _recompute_open_cost(rc):
    rc["open_cost_cents"] = ((rc["units"] - rc["received_units"] - rc["cancelled_units"])
                             * rc["unit_cost_cents"])
    rc["received_cost_cents"] = rc["received_units"] * rc["unit_cost_cents"]


@bp.post("/otb/receipt-commitments/<rid>/commit")
def commit_commitment(rid):
    auth([ROLE_BUYER])
    parse_input([])
    rc = store.get_commitment(rid)
    if rc["commit_status"] != "PROPOSED":
        fail("ERR_INVALID_STATE", "a %s commitment cannot be committed" % rc["commit_status"])
    month = db.months.get(rc["plan_month_id"])
    if month["status"] not in ("LOCKED_PLAN", "IN_SEASON"):
        fail("ERR_PLAN_MONTH_NOT_OPEN", "the plan month is %s" % month["status"])
    vendor = db.vendors.get(rc["vendor_id"])
    if vendor["status"] != "AUTHORIZED":
        fail("ERR_VENDOR_NOT_AUTHORIZED", "the vendor is %s" % vendor["status"])
    plan = store.month_plan(month)
    item = db.items.get(rc["assortment_item_id"])
    _posture_gates(plan, item)
    authorization = calc.active_authorization(vendor["id"], plan["category_id"])
    if authorization is None:
        fail("ERR_VENDOR_NOT_AUTHORIZED_FOR_CATEGORY",
             "no ACTIVE authorization links this vendor to the plan's category")
    calc.check_vendor_capacity(vendor, authorization, rc["units"],
                               store.dt(rc["ship_window_start"]),
                               store.dt(rc["ship_window_end"]),
                               plan["category_id"], rc["id"])
    if rc["cost_cents"] > month["otb_open_cents"]:
        fail("ERR_OTB_EXCEEDED", "the commitment cost exceeds the month's open balance")
    rc["commit_status"] = "COMMITTED"
    _recompute_open_cost(rc)
    touch(rc)
    svc.recompute_month_buckets(month, plan)
    svc.recompute_plan_posture(plan)
    svc.apply_freeze_deferrals(plan)
    return respond(public(rc))


@bp.post("/otb/receipt-commitments/<rid>/cancel")
def cancel_commitment(rid):
    auth([ROLE_BUYER])
    parse_input([F("cancel_reason", "str", required=False, max_len=1000)])
    rc = store.get_commitment(rid)
    if rc["commit_status"] not in ("PROPOSED", "COMMITTED"):
        fail("ERR_INVALID_STATE", "a %s commitment cannot be cancelled" % rc["commit_status"])
    vendor = db.vendors.get(rc["vendor_id"])
    if rc["commit_status"] == "COMMITTED":
        start = store.dt(rc["ship_window_start"])
        if store.clock() > start - calc.days(vendor["cancel_cutoff_days"]):
            fail("ERR_CANCEL_CUTOFF_PASSED",
                 "the cancellation cutoff for this commitment has passed")
    if rc["commit_status"] == "PROPOSED":
        # Withdrawal touches no month and no plan field whatsoever.
        rc["commit_status"] = "WITHDRAWN"
        rc["fulfillment_status"] = "VOID"
        rc["cancelled_units"] = rc["units"]
        rc["open_cost_cents"] = 0
        touch(rc)
        return respond(public(rc))
    # Cascade A.
    rc["commit_status"] = "CANCELLED"
    rc["cancelled_units"] = rc["units"] - rc["received_units"]
    rc["open_cost_cents"] = 0
    if rc["received_units"] == 0:
        rc["fulfillment_status"] = "VOID"
    touch(rc)
    month = db.months.get(rc["plan_month_id"])
    plan = store.month_plan(month)
    svc.recompute_month_buckets(month, plan)
    svc.recompute_plan_posture(plan)
    svc.apply_conditional_restore(plan)
    return respond(public(rc))


@bp.post("/otb/receipt-commitments/<rid>/ship")
def ship_commitment(rid):
    user_id, _ = auth([ROLE_VENDOR])
    parse_input([])
    rc = store.get_commitment(rid)
    if rc["vendor_id"] != user_id:
        fail("ERR_NOT_COMMITMENT_VENDOR", "this commitment belongs to another vendor")
    if rc["commit_status"] != "COMMITTED":
        fail("ERR_INVALID_STATE", "a %s commitment cannot ship" % rc["commit_status"])
    if rc["fulfillment_status"] != "AWAITING_SHIP":
        fail("ERR_INVALID_STATE",
             "a %s commitment cannot be marked shipped" % rc["fulfillment_status"])
    rc["fulfillment_status"] = "SHIPPED"
    touch(rc)
    return respond(public(rc))


@bp.post("/otb/receipt-commitments/<rid>/receipts")
def post_receipts(rid):
    user_id, _ = auth([ROLE_VENDOR])
    data = parse_input([F("received_units_delta", "int")])
    rc = store.get_commitment(rid)
    if rc["vendor_id"] != user_id:
        fail("ERR_NOT_COMMITMENT_VENDOR", "this commitment belongs to another vendor")
    if rc["fulfillment_status"] not in ("SHIPPED", "PARTIALLY_RECEIVED"):
        fail("ERR_INVALID_STATE",
             "receipts cannot be posted against a %s commitment" % rc["fulfillment_status"])
    delta = data["received_units_delta"]
    if delta < 1 or rc["received_units"] + delta > rc["units"]:
        fail("ERR_RECEIPT_OVER_COMMITMENT",
             "received_units_delta must be at least 1 and within the ordered quantity")
    month = db.months.get(rc["plan_month_id"])
    plan = store.month_plan(month)
    if rc["received_units"] + delta < rc["units"]:
        rc["received_units"] = rc["received_units"] + delta
        rc["fulfillment_status"] = "PARTIALLY_RECEIVED"
        _recompute_open_cost(rc)
    else:
        rc["received_units"] = rc["units"]
        rc["fulfillment_status"] = "RECEIVED"
        rc["commit_status"] = "CLOSED"
        rc["open_cost_cents"] = 0
        rc["received_cost_cents"] = rc["received_units"] * rc["unit_cost_cents"]
    touch(rc)
    svc.recompute_month_buckets(month, plan)
    return respond(public(rc))


# ---------------------------------------------------------------------------
# Weekly actuals
# ---------------------------------------------------------------------------
ACTUALS_FIELDS = [
    F("plan_month_id", "str", min_len=1),
    F("week_index", "int", minimum=1, maximum=4),
    F("actual_sales_cents", "int", minimum=0),
    F("actual_receipts_cents", "int", minimum=0),
    F("actual_units_received", "int", minimum=0),
]


@bp.post("/otb/actuals-posts")
def create_actuals():
    auth([ROLE_ADMIN])
    data = parse_input(ACTUALS_FIELDS)
    month = store.get_month(data["plan_month_id"])
    if month["status"] != "IN_SEASON":
        fail("ERR_PLAN_MONTH_NOT_OPEN", "the plan month is %s" % month["status"])
    for row in store.month_actuals(month["id"]):
        if row["week_index"] == data["week_index"]:
            fail("ERR_DUPLICATE_ACTUALS_WEEK",
                 "week_index must be unique within the plan month")
    row = make_row(governed=False, **data)
    db.actuals[row["id"]] = row
    plan = store.month_plan(month)
    month["active_basis"] = "PROJECTED_BASIS"
    svc.reserve_event(month, plan, calc.PROJECTED_BASIS)
    verdict = svc.recompute_variance(plan, bump=False)
    svc.recompute_plan_posture(plan, bump=False)
    touch(plan)
    if verdict == "BREACH" and plan["status"] == "APPROVED" \
            and plan["reforecast_round"] < calc.REFORECAST_ROUND_CAP:
        svc.open_cycle(plan, "VARIANCE_BREACH")
    return respond(public(row), 201)
