"""RemanOrder lifecycle, teardown findings, component decisions (PRD 3.2-3.5)."""
from flask import Blueprint, g

from db import store, new_id, new_common, new_append_only, touch, clock_iso
from errors import ApiError
from middleware import (get_context, require_roles, check_customer_scope,
                        owning_customer_id_of_order, ALL_ROLES)
from response import ok, created, paginate
from services import pricing, workflow
from validation import (parse_body, no_body, require_path_entity, schema_field,
                        severity_ok)

bp = Blueprint("orders", __name__)

CONDITIONS = ["REUSABLE", "REGRINDABLE", "CUT_ONLY", "BEYOND_REPAIR"]
ACTIONS = ["REGRIND", "CUT_NEW", "REPLACE_OEM", "REUSE_AS_IS"]


def _load_order(order_id):
    return require_path_entity(store.orders, order_id)


def _require_state(order, allowed):
    if order["status"] not in allowed:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Order status %s does not admit this action" % order["status"])


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

@bp.get("/reman/orders/<order_id>")
def get_order(order_id):
    uid, role, _ = get_context()
    require_roles(ALL_ROLES)
    order = _load_order(order_id)
    check_customer_scope(uid, role, owning_customer_id_of_order(order))
    return ok(order)


# ---------------------------------------------------------------------------
# Teardown
# ---------------------------------------------------------------------------

@bp.post("/reman/orders/<order_id>/start-teardown")
def start_teardown(order_id):
    uid, role, _ = get_context()
    require_roles(["RemanEngineer"])
    order = _load_order(order_id)
    no_body()
    _require_state(order, ["INTAKE"])
    unit = workflow.order_unit(order)
    if unit["physical_status"] != "AT_SHOP":
        raise ApiError("ERR_UNIT_NOT_AT_SHOP", 409,
                       "GearUnit.physical_status must be AT_SHOP to start teardown")
    if workflow.has_nonterminal_order(unit["id"], exclude_order_id=order["id"]):
        raise ApiError("ERR_UNIT_BUSY", 409,
                       "Unit already has another RemanOrder in a non-terminal state")
    order["status"] = "TEARDOWN"
    touch(order)
    return ok(order)


@bp.post("/reman/orders/<order_id>/findings")
def add_finding(order_id):
    uid, role, _ = get_context()
    require_roles(["RemanEngineer"])
    order = _load_order(order_id)
    body = parse_body({
        "component_code": schema_field("string"),
        "condition": schema_field("enum", enum=CONDITIONS),
        "severity": schema_field("integer", extra=severity_ok),
        "notes": schema_field("string"),
    }, allow_empty=False)
    _require_state(order, ["TEARDOWN"])
    finding = {
        "id": new_id(),
        "reman_order_id": order["id"],
        "component_code": body["component_code"],
        "condition": body["condition"],
        "severity": body["severity"],
        "notes": body["notes"],
    }
    new_append_only(finding)
    store.findings[finding["id"]] = finding
    return created(finding)


@bp.get("/reman/orders/<order_id>/findings")
def list_findings(order_id):
    uid, role, _ = get_context()
    require_roles(ALL_ROLES)
    order = _load_order(order_id)
    check_customer_scope(uid, role, owning_customer_id_of_order(order))
    return ok(paginate(workflow.findings_of_order(order_id)),
              rtype="array", pagination=paginate)


# ---------------------------------------------------------------------------
# Component decisions
# ---------------------------------------------------------------------------

@bp.post("/reman/orders/<order_id>/decisions")
def add_decision(order_id):
    uid, role, _ = get_context()
    require_roles(["RemanEngineer"])
    order = _load_order(order_id)
    body = parse_body({
        "component_code": schema_field("string"),
        "action": schema_field("enum", enum=ACTIONS),
        "labor_hours": schema_field("number"),
        "material_cents": schema_field("integer"),
    }, allow_empty=False)
    _require_state(order, ["TEARDOWN", "SCOPE_APPROVAL"])
    # Per-component replacement: a new PENDING decision supersedes the older one.
    for prior in workflow.pending_decisions(order["id"]):
        if prior["component_code"] == body["component_code"]:
            prior["approval_status"] = "SUPERSEDED"
            touch(prior)
    decision = {
        "id": new_id(),
        "reman_order_id": order["id"],
        "component_code": body["component_code"],
        "action": body["action"],
        "labor_hours": body["labor_hours"],
        "material_cents": body["material_cents"],
        "line_total_cents": pricing.component_line_total_cents(
            body["action"], body["labor_hours"], body["material_cents"],
            order["rush"]),
        "approval_status": "PENDING",
    }
    new_common(decision)
    store.decisions[decision["id"]] = decision
    return created(decision)


@bp.get("/reman/orders/<order_id>/decisions")
def list_decisions(order_id):
    uid, role, _ = get_context()
    require_roles(ALL_ROLES)
    order = _load_order(order_id)
    check_customer_scope(uid, role, owning_customer_id_of_order(order))
    return ok(paginate(workflow.decisions_of_order(order_id)),
              rtype="array", pagination=paginate)


# ---------------------------------------------------------------------------
# Scope submission / revision / approval (PRD 3.3)
# ---------------------------------------------------------------------------

def _check_scope_completeness(order):
    findings = workflow.findings_of_order(order["id"])
    if not findings:
        raise ApiError("ERR_NO_FINDINGS", 422,
                       "submit-scope requires at least one TeardownFinding")
    pending_codes = {d["component_code"]
                     for d in workflow.pending_decisions(order["id"])}
    for finding in findings:
        if finding["component_code"] not in pending_codes:
            raise ApiError("ERR_DECISIONS_INCOMPLETE", 422,
                           "Every finding's component_code needs a PENDING decision")


@bp.post("/reman/orders/<order_id>/submit-scope")
def submit_scope(order_id):
    uid, role, _ = get_context()
    require_roles(["RemanEngineer"])
    order = _load_order(order_id)
    no_body()
    _require_state(order, ["TEARDOWN"])
    _check_scope_completeness(order)
    workflow.recompute_line_totals(order)
    order["approved_scope_cents"] = workflow.compute_approved_scope(order["id"])
    if order["approved_scope_cents"] > order["quoted_estimate_cents"]:
        order["status"] = "SCOPE_APPROVAL"
        touch(order)
    else:
        # Scope within estimate: system auto-approval with the full fiscal
        # footprint of an explicit customer approval (PRD 3.3).
        order["status"] = "APPROVED"
        touch(order)
        for d in workflow.pending_decisions(order["id"]):
            d["approval_status"] = "APPROVED"
            touch(d)
        workflow.refresh_customer_credit(workflow.order_customer(order))
    return ok(order)


@bp.post("/reman/orders/<order_id>/revise-scope")
def revise_scope(order_id):
    uid, role, _ = get_context()
    require_roles(["RemanEngineer"])
    order = _load_order(order_id)
    body = parse_body({
        "expected_order_version": schema_field("version"),
    }, allow_empty=False)
    _require_state(order, ["SCOPE_APPROVAL"])
    if int(body["expected_order_version"]) != order["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_order_version does not match the order's version")
    # Every logged finding must still carry a PENDING decision.
    pending_codes = {d["component_code"]
                     for d in workflow.pending_decisions(order["id"])}
    for finding in workflow.findings_of_order(order["id"]):
        if finding["component_code"] not in pending_codes:
            raise ApiError("ERR_DECISIONS_INCOMPLETE", 422,
                           "Every finding's component_code needs a PENDING decision")
    workflow.recompute_line_totals(order)
    order["approved_scope_cents"] = workflow.compute_approved_scope(order["id"])
    touch(order)  # each revision pass advances version by exactly one
    return ok(order)


@bp.post("/reman/orders/<order_id>/approve-scope")
def approve_scope(order_id):
    uid, role, _ = get_context()
    require_roles(["Customer"])
    order = _load_order(order_id)
    check_customer_scope(uid, role, owning_customer_id_of_order(order))
    no_body()
    _require_state(order, ["SCOPE_APPROVAL"])
    customer = workflow.order_customer(order)
    projected = customer["outstanding_approved_cents"] + order["approved_scope_cents"]
    if customer["credit_hold"] or projected > customer["credit_limit_cents"]:
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED", 422,
                       "Scope approval would exceed the customer's credit limit")
    order["status"] = "APPROVED"
    touch(order)
    for d in workflow.pending_decisions(order["id"]):
        d["approval_status"] = "APPROVED"
        touch(d)
    workflow.refresh_customer_credit(customer)
    return ok(order)


# ---------------------------------------------------------------------------
# Build / assembly transitions (PRD 3.4)
# ---------------------------------------------------------------------------

@bp.post("/reman/orders/<order_id>/start-build")
def start_build(order_id):
    uid, role, _ = get_context()
    require_roles(["RemanEngineer"])
    order = _load_order(order_id)
    no_body()
    _require_state(order, ["APPROVED"])
    if workflow.pending_decisions(order["id"]):
        raise ApiError("ERR_DECISIONS_INCOMPLETE", 422,
                       "All component decisions must be APPROVED to start the build")
    order["status"] = "IN_BUILD"
    touch(order)
    return ok(order)


@bp.post("/reman/orders/<order_id>/start-assembly")
def start_assembly(order_id):
    uid, role, _ = get_context()
    require_roles(["RemanEngineer"])
    order = _load_order(order_id)
    no_body()
    _require_state(order, ["IN_BUILD"])
    order["status"] = "ASSEMBLY"
    touch(order)
    return ok(order)


# ---------------------------------------------------------------------------
# Ship / complete (PRD 3.5)
# ---------------------------------------------------------------------------

@bp.post("/reman/orders/<order_id>/ship")
def ship(order_id):
    uid, role, _ = get_context()
    require_roles(["ServiceManager"])
    order = _load_order(order_id)
    no_body()
    _require_state(order, ["READY_TO_SHIP"])
    booked_outbound = [s for s in workflow.shipments_of_order(order["id"])
                       if s["direction"] == "OUTBOUND" and s["status"] == "BOOKED"]
    if not booked_outbound:
        raise ApiError("ERR_FREIGHT_NOT_READY", 409,
                       "An OUTBOUND shipment in status BOOKED is required to ship")
    for assignment in workflow.assignments_of_order(order["id"]):
        if assignment["status"] == "CHECKED_OUT":
            raise ApiError("ERR_LOANER_OUTSTANDING", 409,
                           "A CHECKED_OUT loaner assignment for the order is unreturned")
    order["status"] = "SHIPPED"
    touch(order)
    for shipment in booked_outbound:
        shipment["status"] = "IN_TRANSIT"
        touch(shipment)
    return ok(order)


@bp.post("/reman/orders/<order_id>/complete")
def complete(order_id):
    uid, role, _ = get_context()
    require_roles(["ServiceManager"])
    order = _load_order(order_id)
    no_body()
    _require_state(order, ["SHIPPED"])
    delivered = any(s["direction"] == "OUTBOUND" and s["status"] == "DELIVERED"
                    for s in workflow.shipments_of_order(order["id"]))
    if not delivered:
        raise ApiError("ERR_FREIGHT_NOT_READY", 409,
                       "The OUTBOUND shipment must be DELIVERED before completion")
    unit = workflow.order_unit(order)
    order["completed_at_hours"] = unit["cumulative_service_hours"]
    order["completed_at_utc"] = clock_iso()
    order["status"] = "COMPLETED"
    touch(order)
    unit["physical_status"] = "IN_SERVICE"
    unit["commercial_status"] = "STANDARD"
    touch(unit)
    workflow.refresh_customer_credit(workflow.order_customer(order))
    # Claims filed in flight resolve their dual-basis verdict at completion.
    for claim in workflow.claims_of_order(order["id"]):
        if claim["status"] == "OPEN" and claim["eligibility"] is None:
            workflow.resolve_claim_eligibility(claim, order)
            touch(claim)
    return ok(order)


# ---------------------------------------------------------------------------
# Cancellation (PRD 3.3)
# ---------------------------------------------------------------------------

@bp.post("/reman/orders/<order_id>/cancel")
def cancel(order_id):
    uid, role, _ = get_context()
    require_roles(["IntakeCoordinator", "Customer"])
    order = _load_order(order_id)
    if role == "Customer":
        check_customer_scope(uid, role, owning_customer_id_of_order(order))
    no_body()
    if role == "IntakeCoordinator" and order["status"] == "INTAKE":
        order["status"] = "CANCELLED"
        touch(order)
        return ok(order)
    if role == "Customer" and order["status"] == "SCOPE_APPROVAL":
        order["status"] = "CANCELLED"
        touch(order)
        for d in workflow.pending_decisions(order["id"]):
            d["approval_status"] = "SUPERSEDED"
            touch(d)
        for assignment in workflow.assignments_of_order(order["id"]):
            if assignment["status"] == "RESERVED":
                assignment["status"] = "CANCELLED"
                touch(assignment)
        # A scope awaiting approval never entered the exposure sum: no debit.
        workflow.refresh_customer_credit(workflow.order_customer(order))
        return ok(order)
    raise ApiError("ERR_INVALID_STATE", 409,
                   "Cancel exists only from INTAKE (IntakeCoordinator) or "
                   "SCOPE_APPROVAL (owning Customer)")
