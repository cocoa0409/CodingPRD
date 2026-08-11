from flask import Blueprint

import calc
import core
import gates
import ops
import serialize
from core import fail, get, now, parse_iso, touch
from gates import check_state

bp = Blueprint("workorders", __name__)

WO_READ_ROLES = ["Dispatcher", "StormCoordinator", "AccountManager", "PlatformAdmin", "Owner",
                 "Vendor", "Auditor"]
WO_FILTERS = ["finding_id", "property_id", "storm_event_id", "key_asset_id", "status", "pipeline"]

CREATE_SPEC = [
    ("work_type", "string", True),
    ("estimated_labour_hours", "number", True),
    ("estimated_parts_cents", "integer", True),
    ("expected_finding_version", "integer", True),
    ("storm_event_id", "string", False),
    ("key_asset_id", "string", False),
]


def _wo_owner_id(wo):
    prop = get("properties", wo.get("property_id"))
    return (prop or {}).get("owner_id")


def _accepted_assignment(wo):
    for a in calc.children("vendor_assignments", "work_order_id", wo["id"]):
        if a["status"] in ("ACCEPTED", "WORKING", "FINISHED"):
            return a
    return None


@bp.post("/property-care/findings/<fid>/work-orders")
def create_work_order(fid):
    role, user_id = gates.begin(["Dispatcher", "StormCoordinator"])
    finding = gates.fetch_path("findings", fid)
    body = gates.body_json()
    # ---- G3 rung 14, in request-body field order ----
    if isinstance(body.get("storm_event_id"), str):
        if get("storm_events", body["storm_event_id"]) is None:
            fail("ERR_LINKED_RESOURCE_NOT_FOUND", "The storm event does not exist.")
    gates.resolve_optional_fks(body, ["key_asset_id"])
    # ---- G4 rung 15 ----
    expected = body.get("expected_finding_version")
    if isinstance(expected, int) and not isinstance(expected, bool):
        if expected != finding["version"]:
            fail("ERR_STALE_FINDING_VERSION", "The finding has been modified.")
    # ---- G5 ----
    check_state("finding", finding, ["TRIAGED"])
    # ---- G10 ----
    gates.validate_payload(body, CREATE_SPEC)

    for prior in calc.children("work_orders", "finding_id", finding["id"]):
        if prior["status"] == "DRAFT":
            prior["status"] = "VOID"
            touch(prior)
    wo = ops.create_work_order(
        finding, body["work_type"], body["estimated_labour_hours"], body["estimated_parts_cents"],
        user_id, storm_event_id=body.get("storm_event_id"), key_asset_id=body.get("key_asset_id"))
    finding["status"] = "WORK_ORDERED"
    touch(finding)
    ops.submit_work_order(wo)
    return core.ok(serialize.work_order(wo), 201)


@bp.get("/property-care/work-orders")
def list_work_orders():
    gates.begin(WO_READ_ROLES)
    return gates.list_response("work_orders", WO_FILTERS, serialize.work_order)


@bp.get("/property-care/work-orders/<wid>")
def read_work_order(wid):
    role, user_id = gates.begin(WO_READ_ROLES)
    wo = gates.fetch_path("work_orders", wid)
    gates.owner_scope(role, user_id, _wo_owner_id(wo))
    return core.ok(serialize.work_order(wo))


@bp.post("/property-care/work-orders/<wid>/submit")
def submit(wid):
    gates.begin(["Dispatcher", "StormCoordinator"])
    wo = gates.fetch_path("work_orders", wid)
    check_state("work_order", wo, ["DRAFT", "REJECTED"])
    body = gates.body_json()
    source = wo["status"]
    if source == "DRAFT":
        finding = get("findings", wo["finding_id"])
        if finding is None or finding["status"] != "WORK_ORDERED":
            fail("ERR_INVALID_STATE_TRANSITION", "The parent finding is not WORK_ORDERED.")
    else:
        new_hours = body.get("estimated_labour_hours", wo["estimated_labour_hours"])
        new_parts = body.get("estimated_parts_cents", wo["estimated_parts_cents"])
        if new_hours == wo["estimated_labour_hours"] and new_parts == wo["estimated_parts_cents"]:
            fail("ERR_INVALID_STATE_TRANSITION",
                 "A re-submission must revise the estimated labour hours or parts cost.")
    gates.validate_payload(body, [
        ("estimated_labour_hours", "number", False),
        ("estimated_parts_cents", "integer", False),
    ])
    if body.get("estimated_labour_hours") is not None:
        wo["estimated_labour_hours"] = body["estimated_labour_hours"]
    if body.get("estimated_parts_cents") is not None:
        wo["estimated_parts_cents"] = body["estimated_parts_cents"]

    if source == "REJECTED":
        wo["status"] = "DRAFT"
        wo["rejection_reason"] = None
        calc.run_cost_chain(wo)
        touch(wo)
    else:
        ops.submit_work_order(wo)
    return core.ok(serialize.work_order(wo))


@bp.post("/property-care/work-orders/<wid>/approve")
def approve(wid):
    role, user_id = gates.begin(["Owner", "StormCoordinator", "PlatformAdmin"])
    wo = gates.fetch_path("work_orders", wid)
    gates.owner_scope(role, user_id, _wo_owner_id(wo))
    pipeline = calc.pipeline_of(wo)
    if role == "Owner" and pipeline == "STORM":
        fail("ERR_WORK_ORDER_PIPELINE_MISMATCH", "An owner may not approve a storm work order.")
    if role == "StormCoordinator" and pipeline == "ROUTINE":
        fail("ERR_WORK_ORDER_PIPELINE_MISMATCH",
             "A storm coordinator may not approve a routine work order.")
    check_state("work_order", wo, ["PENDING_APPROVAL"])
    if pipeline == "STORM" and wo["total_cents"] > core.STORM_EMERGENCY_APPROVAL_CEILING_CENTS:
        fail("ERR_STORM_CEILING_EXCEEDED", "The total exceeds the emergency approval ceiling.")
    wo["status"] = "APPROVED"
    wo["approved_by_user_id"] = user_id
    touch(wo)
    return core.ok(serialize.work_order(wo))


@bp.post("/property-care/work-orders/<wid>/reject")
def reject(wid):
    role, user_id = gates.begin(["Owner", "StormCoordinator", "PlatformAdmin"])
    wo = gates.fetch_path("work_orders", wid)
    gates.owner_scope(role, user_id, _wo_owner_id(wo))
    check_state("work_order", wo, ["PENDING_APPROVAL"])
    body = gates.body_json()
    gates.validate_payload(body, [("rejection_reason", "string", True)])
    wo["status"] = "REJECTED"
    wo["rejection_reason"] = body["rejection_reason"]
    touch(wo)
    finding = get("findings", wo["finding_id"])
    if finding is not None and finding["status"] == "WORK_ORDERED":
        finding["status"] = "TRIAGED"
        touch(finding)
    return core.ok(serialize.work_order(wo))


@bp.post("/property-care/work-orders/<wid>/dispatch")
def dispatch(wid):
    gates.begin(["Dispatcher", "StormCoordinator"])
    wo = gates.fetch_path("work_orders", wid)
    # ---- G5 ----
    if wo["status"] in core.TERMINAL_STATES["work_order"]:
        fail("ERR_ALREADY_TERMINAL", "The work order is already terminal.")
    if wo["status"] == "PENDING_APPROVAL":
        fail("ERR_APPROVAL_REQUIRED", "The work order still awaits approval.")
    if wo["status"] != "APPROVED":
        fail("ERR_INVALID_STATE_TRANSITION", "Only an APPROVED work order may be dispatched.")
    if wo["dispatch_attempt_count"] >= core.WO_MAX_DISPATCH_ATTEMPTS:
        fail("ERR_DISPATCH_ATTEMPTS_EXHAUSTED", "The dispatch attempt cap has been reached.")
    body = gates.body_json()
    # ---- G8: vendor selection (G8a) then key custody (G8b) ----
    finding = get("findings", wo.get("finding_id"))
    pool = calc.vendor_selection(wo, finding)
    if not pool:
        fail("ERR_NO_ELIGIBLE_VENDOR", "No eligible vendor matches this work order.")
    # ---- G10 ----
    gates.validate_payload(body, [
        ("window_start_at", "datetime", True),
        ("window_end_at", "datetime", True),
    ])
    gates.check_interval(body, "window_start_at", "window_end_at")
    ops.perform_dispatch(wo, parse_iso(body["window_start_at"]), parse_iso(body["window_end_at"]))
    return core.ok(serialize.work_order(wo))


@bp.post("/property-care/work-orders/<wid>/complete")
def complete_work_order(wid):
    role, user_id = gates.begin(["Vendor", "Dispatcher"])
    wo = gates.fetch_path("work_orders", wid)
    assignment = _accepted_assignment(wo)
    gates.vendor_scope(role, user_id, (assignment or {}).get("vendor_id"))
    check_state("work_order", wo, ["IN_PROGRESS"])
    if assignment is None or assignment["status"] != "FINISHED":
        fail("ERR_INVALID_STATE_TRANSITION", "The accepted assignment is not FINISHED.")
    body = gates.body_json()
    gates.validate_payload(body, [
        ("actual_labour_hours", "number", True),
        ("actual_parts_cents", "integer", True),
    ])
    wo["actual_labour_hours"] = body["actual_labour_hours"]
    wo["actual_parts_cents"] = body["actual_parts_cents"]
    wo["status"] = "COMPLETED"
    calc.run_cost_chain(wo)
    touch(wo)
    if wo["work_type"] == "REKEY":
        key = get("key_assets", wo.get("key_asset_id"))
        if key is not None and key["rekey_pending_flag"]:
            key["rekey_pending_flag"] = False
            touch(key)
    return core.ok(serialize.work_order(wo))


@bp.post("/property-care/work-orders/<wid>/invoice")
def invoice_work_order(wid):
    gates.begin(["AccountManager", "PlatformAdmin"])
    wo = gates.fetch_path("work_orders", wid)
    body = gates.body_json()
    invoice = None
    if isinstance(body.get("invoice_id"), str):
        invoice = gates.fetch_body_fk("invoices", body["invoice_id"], "ERR_INVOICE_NOT_FOUND")
    check_state("work_order", wo, ["COMPLETED"])
    if invoice is not None and invoice["status"] != "DRAFT":
        fail("ERR_INVOICE_NOT_DRAFT", "The target invoice is not a draft.")
    gates.validate_payload(body, [("invoice_id", "string", True)])
    invoice = gates.fetch_body_fk("invoices", body["invoice_id"], "ERR_INVOICE_NOT_FOUND")

    calc.append_invoice_line(invoice, "WORK_ORDER",
                             "Work order %s" % wo["id"], wo["total_cents"],
                             taxable=True, work_order_id=wo["id"])
    wo["status"] = "INVOICED"
    touch(wo)
    return core.ok(serialize.work_order(wo))


# ---------------------------------------------------------------------------
# Vendor assignments
# ---------------------------------------------------------------------------
ASSIGNMENT_READ_ROLES = ["Dispatcher", "StormCoordinator", "Vendor", "PlatformAdmin", "Auditor",
                         "AccountManager"]


@bp.get("/property-care/vendor-assignments")
def list_assignments():
    gates.begin(ASSIGNMENT_READ_ROLES)
    return gates.list_response("vendor_assignments", ["work_order_id", "vendor_id", "status"],
                               serialize.vendor_assignment)


@bp.get("/property-care/vendor-assignments/<aid>")
def read_assignment(aid):
    gates.begin(ASSIGNMENT_READ_ROLES)
    assignment = gates.fetch_path("vendor_assignments", aid)
    return core.ok(serialize.vendor_assignment(assignment))


@bp.post("/property-care/vendor-assignments/<aid>/accept")
def accept(aid):
    role, user_id = gates.begin(["Vendor"])
    assignment = gates.fetch_path("vendor_assignments", aid)
    gates.vendor_scope(role, user_id, assignment["vendor_id"])
    check_state("vendor_assignment", assignment, ["OFFERED"])
    vendor = get("vendors", assignment["vendor_id"])
    # ---- G8a ----
    if vendor["status"] != "ELIGIBLE":
        fail("ERR_VENDOR_NOT_ELIGIBLE", "The vendor is not eligible.")
    if not vendor["coi_expires_at"] > now():
        fail("ERR_VENDOR_COI_EXPIRED", "The certificate of insurance has expired.")
    if not vendor["license_expires_at"] > now():
        fail("ERR_VENDOR_LICENSE_EXPIRED", "The trade licence has expired.")
    if calc.assignment_window_conflict(assignment):
        fail("ERR_VENDOR_WINDOW_CONFLICT", "The window overlaps another accepted assignment.")
    # ---- G8b ----
    for issuance in calc.children("key_issuances", "vendor_id", vendor["id"]):
        if issuance["status"] in ("OVERDUE", "LOST"):
            fail("ERR_VENDOR_KEY_OVERDUE", "The vendor holds an overdue or lost key.")
    assignment["status"] = "ACCEPTED"
    assignment["accepted_at"] = now()
    touch(assignment)
    return core.ok(serialize.vendor_assignment(assignment))


@bp.post("/property-care/vendor-assignments/<aid>/decline")
def decline(aid):
    role, user_id = gates.begin(["Vendor"])
    assignment = gates.fetch_path("vendor_assignments", aid)
    gates.vendor_scope(role, user_id, assignment["vendor_id"])
    check_state("vendor_assignment", assignment, ["OFFERED"])
    body = gates.body_json()
    gates.validate_payload(body, [("decline_reason", "string", False)])
    assignment["status"] = "DECLINED"
    assignment["decline_reason"] = body.get("decline_reason")
    touch(assignment)
    wo = get("work_orders", assignment["work_order_id"])
    if wo is not None and wo["status"] == "DISPATCHED":
        wo["status"] = "APPROVED"
        touch(wo)
    for issuance in calc.children("key_issuances", "vendor_assignment_id", assignment["id"]):
        if issuance["status"] == "ISSUED":
            issuance["status"] = "RETURNED"
            issuance["returned_at"] = now()
            touch(issuance)
            for grant in calc.children("access_grants", "key_issuance_id", issuance["id"]):
                if grant["status"] in ("PENDING", "ACTIVE"):
                    grant["status"] = "INVALIDATED"
                    grant["invalidated_reason"] = "ASSIGNMENT_WITHDRAWN"
                    touch(grant)
    return core.ok(serialize.vendor_assignment(assignment))


@bp.post("/property-care/vendor-assignments/<aid>/start-work")
def start_work(aid):
    role, user_id = gates.begin(["Vendor"])
    assignment = gates.fetch_path("vendor_assignments", aid)
    gates.vendor_scope(role, user_id, assignment["vendor_id"])
    check_state("vendor_assignment", assignment, ["ACCEPTED"])
    wo = get("work_orders", assignment["work_order_id"])
    prop = get("properties", (wo or {}).get("property_id"))
    # ---- G8b rung 52 ----
    keys = {k["id"] for k in calc.children("key_assets", "property_id", (prop or {}).get("id"))}
    candidates = [gr for gr in core.rows("access_grants")
                  if gr["vendor_id"] == assignment["vendor_id"]
                  and gr["key_asset_id"] in keys
                  and gr["status"] in ("PENDING", "ACTIVE")]
    if not candidates:
        fail("ERR_ACCESS_GRANT_INVALID", "No pending or active access grant exists for this vendor.")
    usable = [gr for gr in candidates
              if gr["window_start_at"] <= now() <= gr["window_end_at"]]
    if not usable:
        fail("ERR_GRANT_WINDOW_NOT_OPEN", "The logical clock lies outside every grant window.")
    grant = usable[0]
    assignment["status"] = "WORKING"
    touch(assignment)
    if grant["status"] == "PENDING":
        grant["status"] = "ACTIVE"
        touch(grant)
    if wo is not None and wo["status"] == "DISPATCHED":
        wo["status"] = "IN_PROGRESS"
        touch(wo)
    ops.occupancy_to_contractor(prop)
    return core.ok(serialize.vendor_assignment(assignment))


@bp.post("/property-care/vendor-assignments/<aid>/finish-work")
def finish_work(aid):
    role, user_id = gates.begin(["Vendor"])
    assignment = gates.fetch_path("vendor_assignments", aid)
    gates.vendor_scope(role, user_id, assignment["vendor_id"])
    check_state("vendor_assignment", assignment, ["WORKING"])
    assignment["status"] = "FINISHED"
    assignment["finished_at"] = now()
    touch(assignment)
    wo = get("work_orders", assignment["work_order_id"])
    prop = get("properties", (wo or {}).get("property_id"))
    ops.occupancy_from_contractor(prop, assignment)
    return core.ok(serialize.vendor_assignment(assignment))


@bp.post("/property-care/vendor-assignments/<aid>/withdraw")
def withdraw(aid):
    gates.begin(["Dispatcher", "PlatformAdmin"])
    assignment = gates.fetch_path("vendor_assignments", aid)
    check_state("vendor_assignment", assignment, ["ACCEPTED"])
    assignment["status"] = "WITHDRAWN"
    touch(assignment)
    for issuance in calc.children("key_issuances", "vendor_assignment_id", assignment["id"]):
        for grant in calc.children("access_grants", "key_issuance_id", issuance["id"]):
            if grant["status"] in ("PENDING", "ACTIVE"):
                grant["status"] = "INVALIDATED"
                grant["invalidated_reason"] = "ASSIGNMENT_WITHDRAWN"
                touch(grant)
    wo = get("work_orders", assignment["work_order_id"])
    if wo is not None and wo["status"] == "DISPATCHED":
        wo["status"] = "APPROVED"
        touch(wo)
    return core.ok(serialize.vendor_assignment(assignment))
