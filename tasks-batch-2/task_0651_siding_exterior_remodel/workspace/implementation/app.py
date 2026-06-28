"""Siding & Exterior Remodel API — entry point and all routes.

In-memory only. The store starts empty on every boot; nothing is seeded.
Validation priority order (PRD 3.12): auth -> forbidden-role -> segregation ->
existence -> invalid-request -> invalid-state -> business rules.
"""
import os
import logging

from flask import Flask, request

import errors
import middleware
import helpers
import serialize
import services
import calculations as calc
from clock import clock
from db import db, new_id
from response import success, list_success, error_response

app = Flask(__name__)

# ---- enum sets ----
STAFF_ROLE_CODES = {"ESTIMATOR", "PROJECT_MANAGER", "FINANCE_OFFICER"}
SCOPE_KINDS = {"SIDING", "TRIM", "WRAP"}
MILESTONES = {"WRAP_INSTALL", "SIDING_INSTALL", "TRIM_FINISH"}
WARRANTY_KINDS = {"LIFETIME_MATERIAL", "WORKMANSHIP"}
TERM_MONTHS = {60, 120, 180}


# ============================================================================
# Error handling
# ============================================================================
@app.errorhandler(errors.ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message), e.http_status


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Referenced resource does not exist"), 404


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed"), 404


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, errors.ApiError):
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", str(e)), 400


def out(entity, status=200):
    return success(serialize.serialize(entity), status=status)


def list_out(items, limit, offset, total):
    return list_success([serialize.serialize(i) for i in items], limit, offset, total)


def _filtered_list(table, filters):
    """Generic list helper: apply equality filters then paginate."""
    limit, offset = helpers.get_pagination()
    items = list(table.values())
    for field in filters:
        val = request.args.get(field)
        if val is not None:
            items = [i for i in items if i.get(field) == val]
    page, total = helpers.paginate(items, limit, offset)
    return list_out(page, limit, offset, total)


# ============================================================================
# Logical clock
# ============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager", "FinanceOfficer"})
    body = helpers.get_body()
    dt = helpers.require_dt(body, "to_iso8601")
    clock.set(dt)
    return success({}, status=200)


# ============================================================================
# Registration / identity
# ============================================================================
@app.route("/clients/register", methods=["POST"])
def register_client():
    body = helpers.get_body()
    email = helpers.require_str(body, "email")
    full_name = helpers.require_str(body, "full_name")
    annual_income_cents = helpers.require_int(body, "annual_income_cents")
    monthly_debt_cents = helpers.require_int(body, "monthly_debt_cents")

    cid = new_id()
    client = {
        "id": cid,
        "email": email.lower(),
        "full_name": full_name,
        "annual_income_cents": annual_income_cents,
        "monthly_debt_cents": monthly_debt_cents,
    }
    helpers.stamp_common(client, versioned=True)
    db.homeowner_clients[cid] = client
    return out(client, status=201)


@app.route("/clients/<cid>", methods=["GET"])
def get_client(cid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager", "FinanceOfficer", "HomeownerClient"})
    client = helpers.get_or_404(db.homeowner_clients, cid)
    return out(client)


@app.route("/staff/register", methods=["POST"])
def register_staff():
    body = helpers.get_body()
    email = helpers.require_str(body, "email")
    full_name = helpers.require_str(body, "full_name")
    role_code = helpers.require_enum(body, "role_code", STAFF_ROLE_CODES)

    sid = new_id()
    staff = {
        "id": sid,
        "email": email.lower(),
        "full_name": full_name,
        "role_code": role_code,
    }
    helpers.stamp_common(staff, versioned=True)
    db.staff_members[sid] = staff
    return out(staff, status=201)


@app.route("/staff/<sid>", methods=["GET"])
def get_staff(sid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager", "FinanceOfficer", "Estimator"})
    staff = helpers.get_or_404(db.staff_members, sid)
    return out(staff)


# ============================================================================
# Project
# ============================================================================
@app.route("/projects", methods=["POST"])
def create_project():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager"})
    body = helpers.get_body()
    client_id = helpers.require_str(body, "client_id")
    project_manager_id = helpers.require_str(body, "project_manager_id")
    property_address = helpers.require_str(body, "property_address")
    hoa_required = helpers.optional_bool(body, "hoa_required", False)

    # existence of body FKs
    helpers.get_or_404(db.homeowner_clients, client_id)
    pm = helpers.get_or_404(db.staff_members, project_manager_id)
    # project_manager_id must reference a StaffMember whose role_code == PROJECT_MANAGER
    if pm["role_code"] != "PROJECT_MANAGER":
        raise errors.err(errors.ERR_INVALID_REQUEST, "project_manager_id must reference a PROJECT_MANAGER StaffMember")

    pid = new_id()
    project = {
        "id": pid,
        "client_id": client_id,
        "project_manager_id": project_manager_id,
        "property_address": property_address,
        "hoa_required": hoa_required,
        "workflow_status": "DRAFT",
        "compliance_status": "PENDING_CLEARANCE",
        "contract_total_cents": 0,
        "retainage_held_cents": 0,
        "amount_released_cents": 0,
        "cancelled_reason": None,
    }
    helpers.stamp_common(project, versioned=True)
    db.projects[pid] = project
    return out(project, status=201)


@app.route("/projects", methods=["GET"])
def list_projects():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager", "FinanceOfficer"})
    return _filtered_list(db.projects, ["client_id", "project_manager_id"])


@app.route("/projects/<pid>", methods=["GET"])
def get_project(pid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager", "FinanceOfficer", "HomeownerClient"})
    project = helpers.get_or_404(db.projects, pid)
    return out(project)


@app.route("/projects/<pid>/complete", methods=["POST"])
def complete_project(pid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager"})
    project = helpers.get_or_404(db.projects, pid)
    # state: must be IN_PROGRESS
    if project["workflow_status"] != "IN_PROGRESS":
        raise errors.err(errors.ERR_INVALID_STATE, "Project not IN_PROGRESS")
    # open-milestones gate
    for ws in db.work_schedules.values():
        if ws["project_id"] == pid and ws["status"] not in ("COMPLETED", "CANCELLED"):
            raise errors.err(errors.ERR_OPEN_MILESTONES, "Open work schedule present")
    for draw in db.progress_draws.values():
        if draw["project_id"] == pid and draw["status"] not in ("RELEASED", "REJECTED"):
            raise errors.err(errors.ERR_OPEN_MILESTONES, "Open progress draw present")

    project["workflow_status"] = "COMPLETED"
    # release residual retainage
    project["amount_released_cents"] += project["retainage_held_cents"]
    project["retainage_held_cents"] = 0
    helpers.touch(project)
    # activate all PENDING warranties
    for wty in db.warranties.values():
        if wty["project_id"] == pid and wty["status"] == "PENDING":
            wty["status"] = "ACTIVE"
            helpers.touch(wty)
    return out(project)


@app.route("/projects/<pid>/cancel", methods=["POST"])
def cancel_project(pid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager"})
    project = helpers.get_or_404(db.projects, pid)
    body = helpers.get_body()
    cancelled_reason = body.get("cancelled_reason")
    expected_project_version = helpers.require_int(body, "expected_project_version")

    # cancellation guard: non-empty reason AND eligible status (one combined error).
    if not isinstance(cancelled_reason, str) or cancelled_reason == "":
        raise errors.err(errors.ERR_CANCEL_NOT_ALLOWED, "cancelled_reason is required")
    if project["workflow_status"] in ("IN_PROGRESS", "COMPLETED", "CANCELLED"):
        raise errors.err(errors.ERR_CANCEL_NOT_ALLOWED, "Project not in a cancellable status")
    # OCC: cancellation requires expected_project_version to match (reported via
    # the cancellation guard per PRD 2.5).
    if expected_project_version != project["version"]:
        raise errors.err(errors.ERR_CANCEL_NOT_ALLOWED, "expected_project_version mismatch")

    project["cancelled_reason"] = cancelled_reason
    services.cancel_project_cascade(project)
    return out(project)


# ============================================================================
# Measurement
# ============================================================================
@app.route("/projects/<pid>/measurements", methods=["POST"])
def create_measurement(pid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"Estimator"})
    project = helpers.get_or_404(db.projects, pid)
    body = helpers.get_body()
    estimator_id = helpers.require_str(body, "estimator_id")
    gross_wall_sqft = helpers.require_number(body, "gross_wall_sqft")
    opening_sqft = helpers.require_number(body, "opening_sqft")
    linear_trim_ft = helpers.require_number(body, "linear_trim_ft")
    color_code = helpers.require_str(body, "color_code")

    # existence of estimator FK
    estimator = helpers.get_or_404(db.staff_members, estimator_id)
    # estimator must be an ESTIMATOR
    if estimator["role_code"] != "ESTIMATOR":
        raise errors.err(errors.ERR_INVALID_REQUEST, "estimator_id must reference an ESTIMATOR StaffMember")
    # numeric range checks (>= 0)
    if gross_wall_sqft < 0 or opening_sqft < 0 or linear_trim_ft < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "areas/lengths must be >= 0")

    # state: first measurement requires project DRAFT
    if project["workflow_status"] != "DRAFT":
        raise errors.err(errors.ERR_INVALID_STATE, "Project not DRAFT")

    mid = new_id()
    net = calc.net_siding_area(gross_wall_sqft, opening_sqft)
    measurement = {
        "id": mid,
        "project_id": pid,
        "estimator_id": estimator_id,
        "gross_wall_sqft": calc.round_half_up_2dp(gross_wall_sqft),
        "opening_sqft": calc.round_half_up_2dp(opening_sqft),
        "linear_trim_ft": calc.round_half_up_2dp(linear_trim_ft),
        "net_siding_sqft": net,
        "color_code": color_code,
    }
    helpers.stamp_common(measurement, versioned=True)
    db.measurements[mid] = measurement
    # advance DRAFT -> MEASURED
    project["workflow_status"] = "MEASURED"
    helpers.touch(project)
    return out(measurement, status=201)


@app.route("/measurements/<mid>", methods=["GET"])
def get_measurement(mid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager", "FinanceOfficer", "Estimator"})
    m = helpers.get_or_404(db.measurements, mid)
    return out(m)


@app.route("/measurements", methods=["GET"])
def list_measurements():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager", "FinanceOfficer", "Estimator"})
    return _filtered_list(db.measurements, ["project_id", "estimator_id"])


# ============================================================================
# Estimate + line items
# ============================================================================
@app.route("/estimates", methods=["POST"])
def create_estimate():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"Estimator", "ProjectManager"})
    body = helpers.get_body()
    project_id = helpers.require_str(body, "project_id")
    measurement_id = helpers.require_str(body, "measurement_id")
    waste_factor_pct = helpers.optional_number(body, "waste_factor_pct", 0.10)

    # existence left-to-right
    helpers.get_or_404(db.projects, project_id)
    helpers.get_or_404(db.measurements, measurement_id)
    # waste_factor_pct range [0, 0.50] -> ERR_VALIDATION_RANGE
    if waste_factor_pct < 0 or waste_factor_pct > 0.50:
        raise errors.err(errors.ERR_VALIDATION_RANGE, "waste_factor_pct must be in [0, 0.50]")

    eid = new_id()
    estimate = {
        "id": eid,
        "project_id": project_id,
        "measurement_id": measurement_id,
        "status": "DRAFT",
        "waste_factor_pct": waste_factor_pct,
        "line_subtotal_cents": 0,
        "tax_cents": 0,
        "estimate_total_cents": 0,
    }
    helpers.stamp_common(estimate, versioned=True)
    db.estimates[eid] = estimate
    return out(estimate, status=201)


@app.route("/estimates/<eid>", methods=["GET"])
def get_estimate(eid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager", "FinanceOfficer", "Estimator", "HomeownerClient"})
    e = helpers.get_or_404(db.estimates, eid)
    return out(e)


@app.route("/estimates", methods=["GET"])
def list_estimates():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager", "FinanceOfficer", "Estimator"})
    return _filtered_list(db.estimates, ["project_id", "measurement_id"])


@app.route("/estimates/<eid>/line-items", methods=["POST"])
def create_line_item(eid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"Estimator", "ProjectManager"})
    estimate = helpers.get_or_404(db.estimates, eid)
    body = helpers.get_body()
    scope_kind = helpers.require_enum(body, "scope_kind", SCOPE_KINDS)
    quantity = helpers.require_number(body, "quantity")
    unit_price_cents = helpers.require_int(body, "unit_price_cents")

    # numeric ranges: quantity > 0, unit_price_cents >= 0
    if quantity <= 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "quantity must be > 0")
    if unit_price_cents < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "unit_price_cents must be >= 0")

    lid = new_id()
    extended = calc.line_extended_amount(scope_kind, quantity, unit_price_cents,
                                         estimate["waste_factor_pct"])
    li = {
        "id": lid,
        "estimate_id": eid,
        "scope_kind": scope_kind,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
        "extended_cents": extended,
    }
    helpers.stamp_common(li, versioned=True)
    db.line_items[lid] = li
    # recompute estimate subtotal/tax/total
    services.recompute_estimate_totals(estimate)
    return out(li, status=201)


@app.route("/line-items/<lid>", methods=["GET"])
def get_line_item(lid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager", "FinanceOfficer", "Estimator"})
    li = helpers.get_or_404(db.line_items, lid)
    return out(li)


@app.route("/line-items", methods=["GET"])
def list_line_items():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager", "FinanceOfficer", "Estimator", "HomeownerClient"})
    return _filtered_list(db.line_items, ["estimate_id"])


@app.route("/estimates/<eid>/baseline", methods=["POST"])
def baseline_estimate(eid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager"})
    estimate = helpers.get_or_404(db.estimates, eid)
    project = helpers.get_or_404(db.projects, estimate["project_id"])

    # state: estimate must be DRAFT
    if estimate["status"] != "DRAFT":
        raise errors.err(errors.ERR_INVALID_STATE, "Estimate not DRAFT")
    # baseline uniqueness (PRD 3.3): a second baseline attempt is rejected with
    # ERR_BASELINE_EXISTS "rather than superseding the first". This is checked
    # before the project-workflow-state check, because after the first baseline
    # the project has already advanced MEASURED -> ESTIMATED, and PRD 3.3 names
    # ERR_BASELINE_EXISTS as the specific outcome of a second baseline attempt.
    for e in db.estimates.values():
        if e["project_id"] == project["id"] and e["status"] == "BASELINE":
            raise errors.err(errors.ERR_BASELINE_EXISTS, "A BASELINE estimate already exists for this project")
    if project["workflow_status"] != "MEASURED":
        raise errors.err(errors.ERR_INVALID_STATE, "Project not MEASURED")
    # empty-estimate gate (priority 8)
    items = [li for li in db.line_items.values() if li["estimate_id"] == eid]
    if len(items) == 0:
        raise errors.err(errors.ERR_EMPTY_ESTIMATE, "Estimate has no line items")

    estimate["status"] = "BASELINE"
    helpers.touch(estimate)
    project["workflow_status"] = "ESTIMATED"
    project["contract_total_cents"] = estimate["estimate_total_cents"]
    helpers.touch(project)
    # create one PENDING warranty per warranty_kind
    for kind in ("LIFETIME_MATERIAL", "WORKMANSHIP"):
        wid = new_id()
        wty = {
            "id": wid,
            "project_id": project["id"],
            "warranty_kind": kind,
            "status": "PENDING",
            "workmanship_years": 0,
        }
        helpers.stamp_common(wty, versioned=True)
        db.warranties[wid] = wty
    return out(estimate)


# ============================================================================
# Permit
# ============================================================================
@app.route("/permits", methods=["POST"])
def create_permit():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager"})
    body = helpers.get_body()
    project_id = helpers.require_str(body, "project_id")
    jurisdiction = helpers.require_str(body, "jurisdiction")

    project = helpers.get_or_404(db.projects, project_id)
    # state: compliance_status must be PENDING_CLEARANCE
    if project["compliance_status"] != "PENDING_CLEARANCE":
        raise errors.err(errors.ERR_INVALID_STATE, "Project compliance_status not PENDING_CLEARANCE")

    pid = new_id()
    permit = {
        "id": pid,
        "project_id": project_id,
        "jurisdiction": jurisdiction,
        "status": "FILED",
        "permit_number": None,
    }
    helpers.stamp_common(permit, versioned=True)
    db.permits[pid] = permit
    project["compliance_status"] = "PERMIT_FILED"
    helpers.touch(project)
    return out(permit, status=201)


@app.route("/permits/<pid>", methods=["GET"])
def get_permit(pid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager", "FinanceOfficer"})
    permit = helpers.get_or_404(db.permits, pid)
    return out(permit)


@app.route("/permits", methods=["GET"])
def list_permits():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager", "FinanceOfficer"})
    return _filtered_list(db.permits, ["project_id"])


@app.route("/permits/<pid>/issue", methods=["POST"])
def issue_permit(pid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager"})
    permit = helpers.get_or_404(db.permits, pid)
    body = helpers.get_body()
    permit_number = helpers.require_str(body, "permit_number")
    project = helpers.get_or_404(db.projects, permit["project_id"])

    # state: project PERMIT_FILED and permit FILED
    if project["compliance_status"] != "PERMIT_FILED":
        raise errors.err(errors.ERR_INVALID_STATE, "Project compliance_status not PERMIT_FILED")
    if permit["status"] != "FILED":
        raise errors.err(errors.ERR_INVALID_STATE, "Permit not FILED")
    # if hoa_required, an APPROVED HOAApproval must exist
    if project["hoa_required"]:
        has_approved = any(
            h["project_id"] == project["id"] and h["status"] == "APPROVED"
            for h in db.hoa_approvals.values()
        )
        if not has_approved:
            raise errors.err(errors.ERR_INVALID_STATE, "HOA approval required but not APPROVED")

    permit["status"] = "ISSUED"
    permit["permit_number"] = permit_number
    helpers.touch(permit)
    project["compliance_status"] = "CLEARED"
    helpers.touch(project)
    return out(permit)


@app.route("/permits/<pid>/reject", methods=["POST"])
def reject_permit(pid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager"})
    permit = helpers.get_or_404(db.permits, pid)
    project = helpers.get_or_404(db.projects, permit["project_id"])
    # block transition requires compliance in {PENDING_CLEARANCE, PERMIT_FILED}
    if project["compliance_status"] not in ("PENDING_CLEARANCE", "PERMIT_FILED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Project compliance_status not blockable")
    permit["status"] = "REJECTED"
    helpers.touch(permit)
    project["compliance_status"] = "BLOCKED"
    helpers.touch(project)
    return out(permit)


# ============================================================================
# HOA
# ============================================================================
@app.route("/hoa-approvals", methods=["POST"])
def create_hoa():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager", "HomeownerClient"})
    body = helpers.get_body()
    project_id = helpers.require_str(body, "project_id")
    reviewed_color_code = helpers.require_str(body, "reviewed_color_code")

    helpers.get_or_404(db.projects, project_id)

    hid = new_id()
    hoa = {
        "id": hid,
        "project_id": project_id,
        "status": "SUBMITTED",
        "reviewed_color_code": reviewed_color_code,
    }
    helpers.stamp_common(hoa, versioned=True)
    db.hoa_approvals[hid] = hoa
    return out(hoa, status=201)


@app.route("/hoa-approvals/<hid>", methods=["GET"])
def get_hoa(hid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager", "FinanceOfficer", "HomeownerClient"})
    hoa = helpers.get_or_404(db.hoa_approvals, hid)
    return out(hoa)


@app.route("/hoa-approvals", methods=["GET"])
def list_hoa():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager", "FinanceOfficer", "HomeownerClient"})
    return _filtered_list(db.hoa_approvals, ["project_id"])


@app.route("/hoa-approvals/<hid>/approve", methods=["POST"])
def approve_hoa(hid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"HomeownerClient", "ProjectManager"})
    hoa = helpers.get_or_404(db.hoa_approvals, hid)
    if hoa["status"] != "SUBMITTED":
        raise errors.err(errors.ERR_INVALID_STATE, "HOA approval not SUBMITTED")
    hoa["status"] = "APPROVED"
    helpers.touch(hoa)
    return out(hoa)


@app.route("/hoa-approvals/<hid>/deny", methods=["POST"])
def deny_hoa(hid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"HomeownerClient", "ProjectManager"})
    hoa = helpers.get_or_404(db.hoa_approvals, hid)
    project = helpers.get_or_404(db.projects, hoa["project_id"])
    # HOA must be SUBMITTED to deny
    if hoa["status"] != "SUBMITTED":
        raise errors.err(errors.ERR_INVALID_STATE, "HOA approval not SUBMITTED")
    # block transition requires compliance in {PENDING_CLEARANCE, PERMIT_FILED}
    if project["compliance_status"] not in ("PENDING_CLEARANCE", "PERMIT_FILED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Project compliance_status not blockable")
    hoa["status"] = "DENIED"
    helpers.touch(hoa)
    project["compliance_status"] = "BLOCKED"
    helpers.touch(project)
    return out(hoa)


# ============================================================================
# Material order
# ============================================================================
@app.route("/material-orders", methods=["POST"])
def create_material_order():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager"})
    body = helpers.get_body()
    project_id = helpers.require_str(body, "project_id")
    estimate_id = helpers.require_str(body, "estimate_id")

    project = helpers.get_or_404(db.projects, project_id)
    estimate = helpers.get_or_404(db.estimates, estimate_id)
    # state: project ESTIMATED and a BASELINE estimate exists
    if project["workflow_status"] != "ESTIMATED":
        raise errors.err(errors.ERR_INVALID_STATE, "Project not ESTIMATED")
    baseline = services.baseline_estimate(project_id)
    if baseline is None:
        raise errors.err(errors.ERR_INVALID_STATE, "No BASELINE estimate for project")

    # ordered_sqft = ceil(measurement.net_siding_sqft * (1 + waste_factor_pct))
    measurement = db.measurements.get(baseline["measurement_id"])
    net = measurement["net_siding_sqft"] if measurement else 0
    ordered = calc.material_order_qty(net, baseline["waste_factor_pct"])

    mid = new_id()
    mo = {
        "id": mid,
        "project_id": project_id,
        "estimate_id": estimate_id,
        "status": "PLACED",
        "ordered_sqft": ordered,
        "delivery_eta_iso": None,
    }
    helpers.stamp_common(mo, versioned=True)
    db.material_orders[mid] = mo
    project["workflow_status"] = "ORDERED"
    helpers.touch(project)
    return out(mo, status=201)


@app.route("/material-orders/<mid>", methods=["GET"])
def get_material_order(mid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager", "FinanceOfficer"})
    mo = helpers.get_or_404(db.material_orders, mid)
    return out(mo)


@app.route("/material-orders", methods=["GET"])
def list_material_orders():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager", "FinanceOfficer"})
    return _filtered_list(db.material_orders, ["project_id", "estimate_id"])


@app.route("/material-orders/<mid>/confirm", methods=["POST"])
def confirm_material_order(mid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager"})
    mo = helpers.get_or_404(db.material_orders, mid)
    body = helpers.get_body()
    delivery_eta_iso = helpers.require_dt(body, "delivery_eta_iso")
    if mo["status"] != "PLACED":
        raise errors.err(errors.ERR_INVALID_STATE, "Material order not PLACED")
    mo["status"] = "CONFIRMED"
    mo["delivery_eta_iso"] = helpers.iso_ms(delivery_eta_iso)
    helpers.touch(mo)
    return out(mo)


@app.route("/material-orders/<mid>/backorder", methods=["POST"])
def backorder_material_order(mid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager"})
    mo = helpers.get_or_404(db.material_orders, mid)
    body = helpers.get_body()
    delivery_eta_iso = helpers.require_dt(body, "delivery_eta_iso")
    if mo["status"] != "CONFIRMED":
        raise errors.err(errors.ERR_INVALID_STATE, "Material order not CONFIRMED")
    mo["status"] = "BACKORDERED"
    mo["delivery_eta_iso"] = helpers.iso_ms(delivery_eta_iso)
    helpers.touch(mo)
    return out(mo)


@app.route("/material-orders/<mid>/deliver", methods=["POST"])
def deliver_material_order(mid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager"})
    mo = helpers.get_or_404(db.material_orders, mid)
    if mo["status"] not in ("CONFIRMED", "BACKORDERED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Material order not CONFIRMED/BACKORDERED")
    # clock-gated: current clock must be >= delivery_eta_iso
    eta = helpers.parse_dt(mo["delivery_eta_iso"], "delivery_eta_iso")
    if clock.now() < eta:
        raise errors.err(errors.ERR_DELIVERY_TOO_EARLY, "Cannot deliver before delivery_eta_iso")
    mo["status"] = "DELIVERED"
    helpers.touch(mo)
    return out(mo)


@app.route("/material-orders/<mid>/cancel", methods=["POST"])
def cancel_material_order(mid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager"})
    mo = helpers.get_or_404(db.material_orders, mid)
    if mo["status"] not in ("PLACED", "CONFIRMED", "BACKORDERED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Material order not cancellable")
    services.cancel_material_order_cascade(mo)
    return out(mo)


# ============================================================================
# Change order
# ============================================================================
@app.route("/change-orders", methods=["POST"])
def create_change_order():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager", "HomeownerClient"})
    body = helpers.get_body()
    project_id = helpers.require_str(body, "project_id")
    target_line_item_id = helpers.require_str(body, "target_line_item_id")
    delta_cents = helpers.require_int(body, "delta_cents")
    supersedes = body.get("supersedes_change_order_id")

    helpers.get_or_404(db.projects, project_id)
    helpers.get_or_404(db.line_items, target_line_item_id)
    if supersedes is not None:
        if not isinstance(supersedes, str):
            raise errors.err(errors.ERR_INVALID_REQUEST, "supersedes_change_order_id must be a string")
        helpers.get_or_404(db.change_orders, supersedes)

    cid = new_id()
    co = {
        "id": cid,
        "project_id": project_id,
        "target_line_item_id": target_line_item_id,
        "supersedes_change_order_id": supersedes,
        "status": "SUBMITTED",
        "delta_cents": delta_cents,
        "pm_approved": False,
        "client_approved": False,
    }
    helpers.stamp_common(co, versioned=True)
    db.change_orders[cid] = co
    return out(co, status=201)


@app.route("/change-orders/<cid>", methods=["GET"])
def get_change_order(cid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager", "FinanceOfficer", "HomeownerClient"})
    co = helpers.get_or_404(db.change_orders, cid)
    return out(co)


@app.route("/change-orders", methods=["GET"])
def list_change_orders():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager", "FinanceOfficer", "HomeownerClient"})
    return _filtered_list(db.change_orders,
                          ["project_id", "target_line_item_id", "supersedes_change_order_id"])


@app.route("/change-orders/<cid>/sign", methods=["POST"])
def sign_change_order(cid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager", "HomeownerClient"})
    co = helpers.get_or_404(db.change_orders, cid)
    if co["status"] != "SUBMITTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Change order not SUBMITTED")
    if role == "ProjectManager":
        co["pm_approved"] = True
    else:  # HomeownerClient
        co["client_approved"] = True
    helpers.touch(co)
    return out(co)


@app.route("/change-orders/<cid>/negotiate", methods=["POST"])
def negotiate_change_order(cid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"HomeownerClient"})
    co = helpers.get_or_404(db.change_orders, cid)
    project = helpers.get_or_404(db.projects, co["project_id"])
    if co["status"] != "SUBMITTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Change order not SUBMITTED")
    if project["workflow_status"] in ("COMPLETED", "CANCELLED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Project is terminal")
    co["status"] = "NEGOTIATING"
    co["pm_approved"] = False
    co["client_approved"] = False
    helpers.touch(co)
    return out(co)


@app.route("/change-orders/<cid>/revise", methods=["POST"])
def revise_change_order(cid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager"})
    co = helpers.get_or_404(db.change_orders, cid)
    body = helpers.get_body()
    delta_cents = helpers.require_int(body, "delta_cents")
    if co["status"] != "NEGOTIATING":
        raise errors.err(errors.ERR_INVALID_STATE, "Change order not NEGOTIATING")
    co["status"] = "SUBMITTED"
    co["delta_cents"] = delta_cents
    helpers.touch(co)
    return out(co)


@app.route("/change-orders/<cid>/approve", methods=["POST"])
def approve_change_order(cid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager"})
    co = helpers.get_or_404(db.change_orders, cid)
    body = helpers.get_body()
    expected_project_version = helpers.require_int(body, "expected_project_version")
    project = helpers.get_or_404(db.projects, co["project_id"])

    # state: change order must be SUBMITTED
    if co["status"] != "SUBMITTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Change order not SUBMITTED")
    # dual sign-off gate
    if not (co["pm_approved"] and co["client_approved"]):
        raise errors.err(errors.ERR_DUAL_SIGNOFF_INCOMPLETE, "Both pm_approved and client_approved required")
    # parent project not terminal
    if project["workflow_status"] in ("COMPLETED", "CANCELLED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Project is terminal")
    # OCC
    if expected_project_version != project["version"]:
        raise errors.err(errors.ERR_STALE_PROJECT_VERSION, "expected_project_version mismatch")

    co["status"] = "APPROVED"
    helpers.touch(co)
    # adjust target line item extended_cents by delta_cents (cross-aggregate)
    target = db.line_items.get(co["target_line_item_id"])
    if target is not None:
        target["extended_cents"] += co["delta_cents"]
        helpers.touch(target)
    # recompute project contract_total_cents (also bumps project version once)
    services.recompute_contract_total(project)
    return out(co)


@app.route("/change-orders/<cid>/reject", methods=["POST"])
def reject_change_order(cid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager"})
    co = helpers.get_or_404(db.change_orders, cid)
    if co["status"] != "SUBMITTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Change order not SUBMITTED")
    co["status"] = "REJECTED"
    helpers.touch(co)
    return out(co)


@app.route("/change-orders/<cid>/withdraw", methods=["POST"])
def withdraw_change_order(cid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"HomeownerClient"})
    co = helpers.get_or_404(db.change_orders, cid)
    if co["status"] not in ("SUBMITTED", "NEGOTIATING"):
        raise errors.err(errors.ERR_INVALID_STATE, "Change order not SUBMITTED/NEGOTIATING")
    co["status"] = "WITHDRAWN"
    helpers.touch(co)
    return out(co)


# ============================================================================
# Crew + work schedule
# ============================================================================
@app.route("/crews", methods=["POST"])
def create_crew():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager"})
    body = helpers.get_body()
    name = helpers.require_str(body, "name")
    max_wind_mph = helpers.optional_number(body, "max_wind_mph", 25)
    if max_wind_mph <= 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "max_wind_mph must be > 0")

    cid = new_id()
    crew = {
        "id": cid,
        "name": name,
        "max_wind_mph": max_wind_mph,
    }
    helpers.stamp_common(crew, versioned=True)
    db.crews[cid] = crew
    return out(crew, status=201)


@app.route("/crews/<cid>", methods=["GET"])
def get_crew(cid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager", "FinanceOfficer"})
    crew = helpers.get_or_404(db.crews, cid)
    return out(crew)


@app.route("/projects/<pid>/work-schedules", methods=["POST"])
def create_work_schedule(pid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager"})
    project = helpers.get_or_404(db.projects, pid)
    body = helpers.get_body()
    crew_id = helpers.require_str(body, "crew_id")
    milestone = helpers.require_enum(body, "milestone", MILESTONES)
    window_start = helpers.require_dt(body, "window_start_iso")
    window_end = helpers.require_dt(body, "window_end_iso")
    forecast_wind_mph = helpers.require_number(body, "forecast_wind_mph")

    helpers.get_or_404(db.crews, crew_id)
    if forecast_wind_mph < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "forecast_wind_mph must be >= 0")

    wid = new_id()
    ws = {
        "id": wid,
        "project_id": pid,
        "crew_id": crew_id,
        "milestone": milestone,
        "window_start_iso": helpers.iso_ms(window_start),
        "window_end_iso": helpers.iso_ms(window_end),
        "forecast_wind_mph": forecast_wind_mph,
        "status": "PROPOSED",
    }
    helpers.stamp_common(ws, versioned=True)
    db.work_schedules[wid] = ws
    return out(ws, status=201)


@app.route("/work-schedules/<wid>", methods=["GET"])
def get_work_schedule(wid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager", "FinanceOfficer"})
    ws = helpers.get_or_404(db.work_schedules, wid)
    return out(ws)


@app.route("/work-schedules", methods=["GET"])
def list_work_schedules():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager", "FinanceOfficer"})
    return _filtered_list(db.work_schedules, ["project_id", "crew_id"])


def _apply_confirmation_gates(ws, project):
    """Gates 9-13 (PRD 3.6) for a window whose wind is acceptable.
    Order: compliance -> material -> crew overlap -> site sequencing."""
    if project["compliance_status"] != "CLEARED":
        raise errors.err(errors.ERR_COMPLIANCE_NOT_CLEARED, "Project compliance_status not CLEARED")
    if not services.project_material_order_delivered(project["id"]):
        raise errors.err(errors.ERR_MATERIAL_NOT_DELIVERED, "Project MaterialOrder not DELIVERED")
    if services.crew_overlap(ws, ws["crew_id"]):
        raise errors.err(errors.ERR_CREW_OVERLAP, "Crew window overlap")
    if services.site_window_conflict(ws, project["id"]):
        raise errors.err(errors.ERR_SITE_WINDOW_CONFLICT, "Site sequencing conflict")


@app.route("/work-schedules/<wid>/confirm", methods=["POST"])
def confirm_work_schedule(wid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager"})
    ws = helpers.get_or_404(db.work_schedules, wid)
    project = helpers.get_or_404(db.projects, ws["project_id"])
    # state: must be PROPOSED
    if ws["status"] != "PROPOSED":
        raise errors.err(errors.ERR_INVALID_STATE, "Work schedule not PROPOSED")

    crew = db.crews.get(ws["crew_id"])
    # weather branch: wind too high parks on WEATHER_HOLD (not an error)
    if ws["forecast_wind_mph"] > crew["max_wind_mph"]:
        ws["status"] = "WEATHER_HOLD"
        helpers.touch(ws)
        return out(ws)

    _apply_confirmation_gates(ws, project)
    ws["status"] = "CONFIRMED"
    helpers.touch(ws)
    if project["workflow_status"] == "ORDERED":
        project["workflow_status"] = "SCHEDULED"
        helpers.touch(project)
    return out(ws)


@app.route("/work-schedules/<wid>/reweather", methods=["POST"])
def reweather_work_schedule(wid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager"})
    ws = helpers.get_or_404(db.work_schedules, wid)
    body = helpers.get_body()
    forecast_wind_mph = helpers.require_number(body, "forecast_wind_mph")
    project = helpers.get_or_404(db.projects, ws["project_id"])
    if forecast_wind_mph < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "forecast_wind_mph must be >= 0")
    # state: must be WEATHER_HOLD
    if ws["status"] != "WEATHER_HOLD":
        raise errors.err(errors.ERR_INVALID_STATE, "Work schedule not WEATHER_HOLD")

    crew = db.crews.get(ws["crew_id"])
    # weather gate: still-too-high wind is rejected
    if forecast_wind_mph > crew["max_wind_mph"]:
        raise errors.err(errors.ERR_WIND_EXCEEDS_LIMIT, "Revised forecast still exceeds crew max_wind_mph")

    # update forecast then evaluate the remaining four gates against the new value
    ws["forecast_wind_mph"] = forecast_wind_mph
    _apply_confirmation_gates(ws, project)
    ws["status"] = "CONFIRMED"
    helpers.touch(ws)
    if project["workflow_status"] == "ORDERED":
        project["workflow_status"] = "SCHEDULED"
        helpers.touch(project)
    return out(ws)


@app.route("/work-schedules/<wid>/start", methods=["POST"])
def start_work_schedule(wid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager"})
    ws = helpers.get_or_404(db.work_schedules, wid)
    project = helpers.get_or_404(db.projects, ws["project_id"])
    if ws["status"] != "CONFIRMED":
        raise errors.err(errors.ERR_INVALID_STATE, "Work schedule not CONFIRMED")
    if project["workflow_status"] != "SCHEDULED":
        raise errors.err(errors.ERR_INVALID_STATE, "Project not SCHEDULED")
    project["workflow_status"] = "IN_PROGRESS"
    helpers.touch(project)
    return out(ws)


@app.route("/work-schedules/<wid>/complete", methods=["POST"])
def complete_work_schedule(wid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager"})
    ws = helpers.get_or_404(db.work_schedules, wid)
    project = helpers.get_or_404(db.projects, ws["project_id"])
    if ws["status"] != "CONFIRMED":
        raise errors.err(errors.ERR_INVALID_STATE, "Work schedule not CONFIRMED")
    if project["workflow_status"] != "IN_PROGRESS":
        raise errors.err(errors.ERR_INVALID_STATE, "Project not IN_PROGRESS")
    ws["status"] = "COMPLETED"
    helpers.touch(ws)
    return out(ws)


@app.route("/work-schedules/<wid>/cancel", methods=["POST"])
def cancel_work_schedule(wid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager"})
    ws = helpers.get_or_404(db.work_schedules, wid)
    if ws["status"] not in ("PROPOSED", "CONFIRMED", "WEATHER_HOLD"):
        raise errors.err(errors.ERR_INVALID_STATE, "Work schedule not cancellable")
    services.cancel_work_schedule_cascade(ws)
    return out(ws)


# ============================================================================
# Progress draw
# ============================================================================
@app.route("/projects/<pid>/progress-draws", methods=["POST"])
def create_progress_draw(pid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager"})
    project = helpers.get_or_404(db.projects, pid)
    body = helpers.get_body()
    work_schedule_id = helpers.require_str(body, "work_schedule_id")
    milestone_pct = helpers.require_number(body, "milestone_pct")

    helpers.get_or_404(db.work_schedules, work_schedule_id)
    # range: milestone_pct in (0, 1]
    if milestone_pct <= 0 or milestone_pct > 1:
        raise errors.err(errors.ERR_VALIDATION_RANGE, "milestone_pct must be in (0, 1]")

    did = new_id()
    draw = {
        "id": did,
        "project_id": pid,
        "work_schedule_id": work_schedule_id,
        "status": "REQUESTED",
        "approved_by_staff_id": None,
        "milestone_pct": milestone_pct,
        "gross_amount_cents": 0,
        "retainage_cents": 0,
        "net_released_cents": 0,
    }
    helpers.stamp_common(draw, versioned=True)
    db.progress_draws[did] = draw
    return out(draw, status=201)


@app.route("/progress-draws/<did>", methods=["GET"])
def get_progress_draw(did):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager", "FinanceOfficer"})
    draw = helpers.get_or_404(db.progress_draws, did)
    return out(draw)


@app.route("/progress-draws", methods=["GET"])
def list_progress_draws():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager", "FinanceOfficer"})
    return _filtered_list(db.progress_draws, ["project_id", "work_schedule_id"])


@app.route("/progress-draws/<did>/approve", methods=["POST"])
def approve_progress_draw(did):
    user_id, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager"})
    draw = helpers.get_or_404(db.progress_draws, did)
    project = helpers.get_or_404(db.projects, draw["project_id"])
    ws = db.work_schedules.get(draw["work_schedule_id"])

    # state: draw must be REQUESTED
    if draw["status"] != "REQUESTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Progress draw not REQUESTED")
    # milestone completeness gate
    if ws is None or ws["status"] != "COMPLETED":
        raise errors.err(errors.ERR_MILESTONE_INCOMPLETE, "Referenced WorkSchedule not COMPLETED")
    # project must be IN_PROGRESS
    if project["workflow_status"] != "IN_PROGRESS":
        raise errors.err(errors.ERR_INVALID_STATE, "Project not IN_PROGRESS")

    gross, retainage, net = calc.draw_release_amount(
        project["contract_total_cents"], draw["milestone_pct"], project["retainage_held_cents"]
    )
    draw["status"] = "APPROVED"
    draw["approved_by_staff_id"] = user_id
    draw["gross_amount_cents"] = gross
    draw["retainage_cents"] = retainage
    draw["net_released_cents"] = net
    helpers.touch(draw)
    return out(draw)


@app.route("/progress-draws/<did>/release", methods=["POST"])
def release_progress_draw(did):
    user_id, role = middleware.authenticate()
    middleware.require_roles(role, {"FinanceOfficer"})
    draw = helpers.get_or_404(db.progress_draws, did)
    # segregation of duties is priority 3 — checked before existence of further
    # resources, but the draw itself must be resolved to read approved_by_staff_id.
    if user_id == draw.get("approved_by_staff_id"):
        raise errors.err(errors.ERR_SEGREGATION_OF_DUTIES, "Releaser must not be the approving manager")
    project = helpers.get_or_404(db.projects, draw["project_id"])
    body = helpers.get_body()
    expected_project_version = helpers.require_int(body, "expected_project_version")

    if draw["status"] != "APPROVED":
        raise errors.err(errors.ERR_INVALID_STATE, "Progress draw not APPROVED")
    if expected_project_version != project["version"]:
        raise errors.err(errors.ERR_STALE_PROJECT_VERSION, "expected_project_version mismatch")

    draw["status"] = "RELEASED"
    helpers.touch(draw)
    project["amount_released_cents"] += draw["net_released_cents"]
    project["retainage_held_cents"] += draw["retainage_cents"]
    helpers.touch(project)
    return out(draw)


@app.route("/progress-draws/<did>/clawback", methods=["POST"])
def clawback_progress_draw(did):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"FinanceOfficer"})
    draw = helpers.get_or_404(db.progress_draws, did)
    project = helpers.get_or_404(db.projects, draw["project_id"])
    body = helpers.get_body()
    expected_project_version = helpers.require_int(body, "expected_project_version")

    if draw["status"] != "RELEASED":
        raise errors.err(errors.ERR_INVALID_STATE, "Progress draw not RELEASED")
    if expected_project_version != project["version"]:
        raise errors.err(errors.ERR_STALE_PROJECT_VERSION, "expected_project_version mismatch")

    draw["status"] = "CLAWED_BACK"
    helpers.touch(draw)
    project["amount_released_cents"] -= draw["net_released_cents"]
    project["retainage_held_cents"] -= draw["retainage_cents"]
    helpers.touch(project)
    return out(draw)


@app.route("/progress-draws/<did>/reject", methods=["POST"])
def reject_progress_draw(did):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager"})
    draw = helpers.get_or_404(db.progress_draws, did)
    if draw["status"] not in ("REQUESTED", "APPROVED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Progress draw not REQUESTED/APPROVED")
    draw["status"] = "REJECTED"
    helpers.touch(draw)
    return out(draw)


# ============================================================================
# Warranty
# ============================================================================
@app.route("/warranties/<wid>", methods=["GET"])
def get_warranty(wid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager", "FinanceOfficer", "HomeownerClient"})
    wty = helpers.get_or_404(db.warranties, wid)
    return out(wty)


@app.route("/warranties", methods=["GET"])
def list_warranties():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ProjectManager", "FinanceOfficer", "HomeownerClient"})
    return _filtered_list(db.warranties, ["project_id"])


# ============================================================================
# Financing
# ============================================================================
@app.route("/financing-applications", methods=["POST"])
def create_financing():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"HomeownerClient", "ProjectManager"})
    body = helpers.get_body()
    project_id = helpers.require_str(body, "project_id")
    client_id = helpers.require_str(body, "client_id")
    requested_amount_cents = helpers.require_int(body, "requested_amount_cents")
    term_months = helpers.require_int(body, "term_months")

    helpers.get_or_404(db.projects, project_id)
    helpers.get_or_404(db.homeowner_clients, client_id)
    # requested_amount_cents > 0
    if requested_amount_cents <= 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "requested_amount_cents must be > 0")
    # term_months in {60, 120, 180} -> ERR_VALIDATION_RANGE
    if term_months not in TERM_MONTHS:
        raise errors.err(errors.ERR_VALIDATION_RANGE, "term_months must be one of 60, 120, 180")

    fid = new_id()
    app_row = {
        "id": fid,
        "project_id": project_id,
        "client_id": client_id,
        "requested_amount_cents": requested_amount_cents,
        "term_months": term_months,
        "status": "SUBMITTED",
        "monthly_payment_cents": 0,
        "dti_ratio": 0,
    }
    helpers.stamp_common(app_row, versioned=True)
    db.financing_applications[fid] = app_row
    return out(app_row, status=201)


@app.route("/financing-applications/<fid>", methods=["GET"])
def get_financing(fid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"FinanceOfficer", "HomeownerClient", "ProjectManager"})
    app_row = helpers.get_or_404(db.financing_applications, fid)
    return out(app_row)


@app.route("/financing-applications", methods=["GET"])
def list_financing():
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"FinanceOfficer", "HomeownerClient", "ProjectManager"})
    return _filtered_list(db.financing_applications, ["project_id", "client_id"])


@app.route("/financing-applications/<fid>/decide", methods=["POST"])
def decide_financing(fid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"FinanceOfficer"})
    app_row = helpers.get_or_404(db.financing_applications, fid)
    project = helpers.get_or_404(db.projects, app_row["project_id"])
    client = helpers.get_or_404(db.homeowner_clients, app_row["client_id"])

    if app_row["status"] != "SUBMITTED":
        raise errors.err(errors.ERR_INVALID_STATE, "Financing application not SUBMITTED")

    # compute monthly payment then dti, then apply the gates
    monthly_payment = calc.financing_monthly_payment(
        app_row["requested_amount_cents"], app_row["term_months"]
    )
    dti = calc.financing_dti(
        client["annual_income_cents"], client["monthly_debt_cents"], monthly_payment
    )
    app_row["monthly_payment_cents"] = monthly_payment
    app_row["dti_ratio"] = dti if dti is not None else 0

    # DTI gate (priority 17) then principal gate (priority 18)
    if not calc.dti_within_limit(dti):
        app_row["status"] = "DECLINED"
        helpers.touch(app_row)
        raise errors.err(errors.ERR_DTI_EXCEEDED, "dti_ratio exceeds DTI_MAX")
    if app_row["requested_amount_cents"] > project["contract_total_cents"]:
        app_row["status"] = "DECLINED"
        helpers.touch(app_row)
        raise errors.err(errors.ERR_PRINCIPAL_EXCEEDS_CONTRACT, "requested_amount_cents exceeds contract_total_cents")

    app_row["status"] = "APPROVED"
    helpers.touch(app_row)
    return out(app_row)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    # Serve via waitress (a production WSGI server) rather than the werkzeug dev
    # server. Under the per-test-server isolation the server is rebooted before
    # every test and hit immediately; the dev server occasionally accepts the TCP
    # connection before its request thread is ready and resets it ("Connection
    # reset by peer"). waitress drains its accept queue cleanly and removes that
    # boot-time flake.
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8, _quiet=True)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
