"""Work orders: creation, dispatch selection, acceptance, completion and voids."""
from flask import Blueprint

import calc
import cascades
import store
import views
from envelope import created, ok, paginate
from errors import fail
from validation import F, authorize, body_json, must_find, parse_date_value, validate

bp = Blueprint("work_orders", __name__)

WO_READ = ["OperationsManager", "PortfolioAdmin", "RegionalDirector", "VendorManager",
           "Vendor", "ComplianceOfficer"]
RANKING_READ = ["OperationsManager", "PortfolioAdmin", "RegionalDirector", "VendorManager"]

WO_FIELDS = [
    F("home_id", "string"),
    F("scope_template_id", "string"),
    F("work_type", "string", enum=["RENOVATION", "TURN", "RESIDENT_MAINTENANCE"]),
    F("quantity", "count", minimum=1),
    F("crew_size", "count", minimum=1),
    F("scheduled_start_date", "date"),
    F("scheduled_end_date", "date"),
    F("fulfillment_channel", "string", enum=["IN_HOUSE", "VENDOR"]),
    F("quoted_cost_cents", "money", minimum=1),
    F("project_id", "string", required=False, default=""),
]

VOIDABLE_STATUSES = {"PENDING_DISPATCH", "DISPATCHED", "ACCEPTED", "IN_PROGRESS"}
CREW_COMMITTED_STATUSES = {"DISPATCHED", "ACCEPTED"}


def _template_of(work_order):
    return store.get("scope_templates", work_order["scope_template_id"])


@bp.post("/work-orders")
def create_work_order():
    data = validate(body_json(), WO_FIELDS)
    if parse_date_value(data["scheduled_start_date"]) > parse_date_value(
            data["scheduled_end_date"]):
        fail("ERR_INVALID_REQUEST",
             "Field 'scheduled_end_date' may not precede 'scheduled_start_date'.")
    authorize(["OperationsManager"])
    template = must_find("scope_templates", data["scope_template_id"],
                         "ERR_SCOPE_TEMPLATE_NOT_FOUND")
    home = must_find("homes", data["home_id"], "ERR_HOME_NOT_FOUND")
    project = None
    if data["project_id"]:
        project = must_find("renovation_projects", data["project_id"],
                            "ERR_RENOVATION_PROJECT_NOT_FOUND")
        if project["status"] == "RENT_READY":
            fail("ERR_PROJECT_SCOPE_LOCKED")

    market = cascades.market_of(home)
    benchmark = calc.line_benchmark(
        {"benchmark_unit_cost_cents": template["benchmark_unit_cost_cents"],
         "quantity": data["quantity"]},
        market["cost_index_bps"])
    quoted = int(data["quoted_cost_cents"])
    variance = calc.rhu_div((quoted - benchmark) * 10000, benchmark) if benchmark else 0
    if variance > int(market["cost_variance_tolerance_bps"]):
        fail("ERR_COST_VARIANCE_EXCEEDED")
    if project is not None:
        if int(project["committed_cost_cents"]) + quoted > int(project["approved_budget_cents"]):
            fail("ERR_PROJECT_BUDGET_EXCEEDED")

    row = store.base_row()
    row.update({
        "home_id": home["id"],
        "project_id": project["id"] if project is not None else "",
        "vendor_id": "",
        "scope_template_id": template["id"],
        "work_type": data["work_type"],
        "quantity": data["quantity"],
        "crew_size": data["crew_size"],
        "scheduled_start_date": data["scheduled_start_date"],
        "scheduled_end_date": data["scheduled_end_date"],
        "crew_days": calc.crew_days(data["crew_size"], data["scheduled_start_date"],
                                    data["scheduled_end_date"]),
        "fulfillment_channel": data["fulfillment_channel"],
        "quoted_cost_cents": quoted,
        "benchmark_total_cents": benchmark,
        "variance_bps": variance,
        "actual_cost_cents": 0,
        "completed_on": "",
        "void_reason": "",
        "status": "PENDING_DISPATCH",
    })
    store.insert("work_orders", row)
    if project is not None:
        cascades.commit_project_cost(project, quoted)
    return created(views.public(row))


@bp.get("/work-orders/<work_order_id>")
def read_work_order(work_order_id):
    authorize(WO_READ)
    row = must_find("work_orders", work_order_id, "ERR_WORK_ORDER_NOT_FOUND")
    return ok(views.public(row))


@bp.get("/work-orders")
def list_work_orders():
    authorize(WO_READ)
    rows = views.filtered("work_orders", [
        ("home_id", "home_id", "string"),
        ("project_id", "project_id", "string"),
        ("vendor_id", "vendor_id", "string"),
        ("scope_template_id", "scope_template_id", "string"),
        ("status", "status", "string"),
        ("work_type", "work_type", "string"),
        ("fulfillment_channel", "fulfillment_channel", "string"),
    ])
    return paginate(rows, views.public)


@bp.get("/work-orders/<work_order_id>/vendor-ranking")
def vendor_ranking(work_order_id):
    authorize(RANKING_READ)
    work_order = must_find("work_orders", work_order_id, "ERR_WORK_ORDER_NOT_FOUND")
    home = store.get("homes", work_order["home_id"])
    template = _template_of(work_order)
    return ok(calc.vendor_ranking(work_order, home, template["certification_code"]))


@bp.post("/work-orders/<work_order_id>/dispatch")
def dispatch_work_order(work_order_id):
    data = validate(body_json(), [F("vendor_id", "string", required=False, default=None)])
    authorize(["OperationsManager"])
    vendor = None
    if data["vendor_id"]:
        vendor = must_find("vendors", data["vendor_id"], "ERR_VENDOR_NOT_FOUND")
    work_order = must_find("work_orders", work_order_id, "ERR_WORK_ORDER_NOT_FOUND")
    home = store.get("homes", work_order["home_id"])
    if vendor is not None and vendor["market_id"] != home["market_id"]:
        fail("ERR_MARKET_MISMATCH")
    if work_order["status"] != "PENDING_DISPATCH":
        fail("ERR_INVALID_STATE")
    template = _template_of(work_order)

    if work_order["fulfillment_channel"] == "IN_HOUSE":
        if vendor is not None:
            fail("ERR_INVALID_REQUEST",
                 "Field 'vendor_id' is not permitted on an in-house dispatch.")
        if template["safety_critical"]:
            fail("ERR_IN_HOUSE_SAFETY_CRITICAL")
        work_order["status"] = "IN_PROGRESS"
        store.touch(work_order)
        return ok(views.public(work_order))

    certification_code = template["certification_code"]
    if vendor is not None:
        reason = calc.vendor_exclusion_reason(vendor, work_order, certification_code)
        if reason is not None:
            fail(reason)
    else:
        ranking = calc.vendor_ranking(work_order, home, certification_code)
        if not ranking["eligible_vendor_ids"]:
            fail("ERR_NO_ELIGIBLE_VENDOR")
        vendor = store.get("vendors", ranking["winning_vendor_id"])

    work_order["vendor_id"] = vendor["id"]
    work_order["status"] = "DISPATCHED"
    store.touch(work_order)
    vendor["committed_crew_days"] = (int(vendor["committed_crew_days"])
                                     + int(work_order["crew_days"]))
    store.touch(vendor)
    return ok(views.public(work_order))


@bp.post("/work-orders/<work_order_id>/accept")
def accept_work_order(work_order_id):
    role, user_id = authorize(["Vendor"])
    work_order = must_find("work_orders", work_order_id, "ERR_WORK_ORDER_NOT_FOUND")
    if work_order["fulfillment_channel"] == "VENDOR" and not work_order["vendor_id"]:
        fail("ERR_WORK_ORDER_NOT_ASSIGNED")
    if work_order["status"] != "DISPATCHED":
        fail("ERR_INVALID_STATE")
    if user_id != work_order["vendor_id"]:
        fail("ERR_NOT_ASSIGNED_VENDOR")
    work_order["status"] = "ACCEPTED"
    store.touch(work_order)
    return ok(views.public(work_order))


@bp.post("/work-orders/<work_order_id>/complete")
def complete_work_order(work_order_id):
    data = validate(body_json(), [
        F("actual_cost_cents", "money"),
        F("completed_on", "date"),
    ])
    role, user_id = authorize(["Vendor", "OperationsManager"])
    work_order = must_find("work_orders", work_order_id, "ERR_WORK_ORDER_NOT_FOUND")
    vendor_channel = work_order["fulfillment_channel"] == "VENDOR"
    if vendor_channel and not work_order["vendor_id"]:
        fail("ERR_WORK_ORDER_NOT_ASSIGNED")
    origin = "ACCEPTED" if vendor_channel else "IN_PROGRESS"
    if work_order["status"] != origin:
        fail("ERR_INVALID_STATE")
    if role == "Vendor" and user_id != work_order["vendor_id"]:
        fail("ERR_NOT_ASSIGNED_VENDOR")
    if parse_date_value(data["completed_on"]) < parse_date_value(
            work_order["scheduled_start_date"]):
        fail("ERR_COMPLETION_DATE_INVALID")

    # Hop 1 — the work order itself, and the crew-day release on the vendor channel.
    work_order["status"] = "COMPLETED"
    work_order["actual_cost_cents"] = data["actual_cost_cents"]
    work_order["completed_on"] = data["completed_on"]
    store.touch(work_order)
    if vendor_channel:
        vendor = store.get("vendors", work_order["vendor_id"])
        if vendor is not None:
            vendor["committed_crew_days"] = max(
                0, int(vendor["committed_crew_days"]) - int(work_order["crew_days"]))
            store.touch(vendor)

    # Hops 2..5 — only when this completion drains the project's live queue.
    if work_order["project_id"]:
        cascades.maybe_make_ready(store.get("renovation_projects", work_order["project_id"]))
    return ok(views.public(work_order))


@bp.post("/work-orders/<work_order_id>/void")
def void_work_order(work_order_id):
    data = validate(body_json(), [F("void_reason", "string")])
    authorize(["OperationsManager"])
    work_order = must_find("work_orders", work_order_id, "ERR_WORK_ORDER_NOT_FOUND")
    origin = work_order["status"]
    if origin not in VOIDABLE_STATUSES:
        fail("ERR_INVALID_STATE")

    work_order["status"] = "VOIDED"
    work_order["void_reason"] = data["void_reason"]
    store.touch(work_order)

    project = None
    if work_order["project_id"]:
        project = store.get("renovation_projects", work_order["project_id"])
    if project is not None:
        cascades.release_project_cost(project, work_order["quoted_cost_cents"])
    if origin in CREW_COMMITTED_STATUSES and work_order["vendor_id"]:
        vendor = store.get("vendors", work_order["vendor_id"])
        if vendor is not None:
            vendor["committed_crew_days"] = max(
                0, int(vendor["committed_crew_days"]) - int(work_order["crew_days"]))
            store.touch(vendor)
    if project is not None:
        cascades.maybe_make_ready(project)
    return ok(views.public(work_order))
