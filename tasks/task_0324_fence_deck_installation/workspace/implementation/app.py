"""Fence & Deck Installation API — Flask entry point.

In-memory only. Boots empty on every invocation; no seeding.
"""
import os

from flask import Flask, request

import calculations as calc
import clock
import db
import services as svc
from errors import ApiError, err
from middleware import auth_context, require_role, body
from response import success, list_response, error_response

app = Flask(__name__)

ALL_ROLES = ["ProjectManager", "Estimator", "FieldTech", "PermitClerk", "Customer"]

JOB_TYPES = {"FENCE", "DECK", "FENCE_AND_DECK"}
WORK_TYPES = {"FENCE", "DECK"}
MATERIALS = {"CEDAR", "VINYL", "COMPOSITE", "PT_PINE", "ALUMINUM"}
STYLES = {"PRIVACY", "PICKET", "DECK_STANDARD", "ORNAMENTAL"}
ACCESSORIES = {"NONE", "SINGLE_GATE", "DOUBLE_GATE", "STAIR_SET"}
PERMIT_TYPES = {"FENCE_PERMIT", "DECK_PERMIT", "ZONING_VARIANCE"}


# ===========================================================================
# Error handling
# ===========================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % e, 400)


# ===========================================================================
# Helpers
# ===========================================================================
def paginate(items):
    """Apply limit/offset query params (PRD §2.3). Returns (page, limit, offset, total)."""
    total = len(items)
    limit = _int_param("limit", 10)
    offset = _int_param("offset", 0)
    if limit < 1 or limit > 100:
        raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset < 0:
        raise err("ERR_INVALID_REQUEST", "offset must be >= 0.")
    page = items[offset:offset + limit]
    return page, limit, offset, total


def _int_param(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer." % name)


def sorted_by_created(rows):
    return sorted(rows, key=lambda r: r["_seq"])


def get_project_or_404(project_id):
    p = db.projects.get(project_id)
    if p is None:
        raise err("ERR_NOT_FOUND", "Project not found.")
    return p


def get_child_or_404(collection, child_id, project_id, label):
    child = collection.get(child_id)
    if child is None or child["project_id"] != project_id:
        raise err("ERR_NOT_FOUND", "%s not found." % label)
    return child


def require_fields(data, fields):
    for f in fields:
        if data.get(f) is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def require_enum(value, domain, field):
    if value not in domain:
        raise err("ERR_INVALID_REQUEST", "%s value out of domain: %r" % (field, value))


def positive_number(value, field):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise err("ERR_VALIDATION", "%s must be a positive number." % field)
    if value <= 0:
        raise err("ERR_VALIDATION", "%s must be greater than zero." % field)


def ok(record):
    return success(svc.serialize(record), status=200, response_type="object")


def created(record):
    return success(svc.serialize(record), status=201, response_type="object")


# ===========================================================================
# Customers
# ===========================================================================
@app.route("/customers", methods=["POST"])
def create_customer():
    role, _ = auth_context()
    require_role(role, ["ProjectManager"])
    data = body()
    require_fields(data, ["full_name", "email", "hoa_governed"])
    if not isinstance(data["hoa_governed"], bool):
        raise err("ERR_INVALID_REQUEST", "hoa_governed must be a boolean.")
    with db.LOCK:
        rec = {
            "full_name": data["full_name"],
            "email": data["email"],
            "hoa_governed": data["hoa_governed"],
        }
        db.stamp_create(rec, versioned=False)
        db.customers[rec["id"]] = rec
        return created(rec)


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    role, _ = auth_context()
    require_role(role, ALL_ROLES)
    rec = db.customers.get(cid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Customer not found.")
    return ok(rec)


# ===========================================================================
# Projects
# ===========================================================================
@app.route("/projects", methods=["POST"])
def create_project():
    role, _ = auth_context()
    require_role(role, ["ProjectManager"])
    data = body()
    # referential check (priority 4) for customer_id comes before required-field
    # shape per §2.9 ordering: existence/referential precede ERR_INVALID_REQUEST.
    if data.get("customer_id") is not None and data["customer_id"] not in db.customers:
        raise err("ERR_REFERENCE_NOT_FOUND", "customer_id does not resolve to a Customer.")
    require_fields(data, ["customer_id", "site_address", "job_type"])
    require_enum(data["job_type"], JOB_TYPES, "job_type")
    with db.LOCK:
        rec = {
            "customer_id": data["customer_id"],
            "site_address": data["site_address"],
            "job_type": data["job_type"],
            "status": "DRAFT",
            "active_estimate_id": None,
            "contract_total": calc.r2("0.00"),
            "draws_paid_total": calc.r2("0.00"),
            "balance_due": calc.r2("0.00"),
            "permit_clearance": "PENDING",
        }
        db.stamp_create(rec)
        db.projects[rec["id"]] = rec
        return created(rec)


@app.route("/projects/<pid>", methods=["GET"])
def get_project(pid):
    role, _ = auth_context()
    require_role(role, ALL_ROLES)
    p = get_project_or_404(pid)
    return ok(p)


@app.route("/projects", methods=["GET"])
def list_projects():
    role, _ = auth_context()
    require_role(role, ALL_ROLES)
    rows = sorted_by_created(list(db.projects.values()))
    cust = request.args.get("customer_id")
    if cust is not None:
        rows = [p for p in rows if p["customer_id"] == cust]
    page, limit, offset, total = paginate(rows)
    return list_response([svc.serialize(p) for p in page], limit, offset, total)


@app.route("/projects/<pid>/cancel", methods=["POST"])
def cancel_project(pid):
    role, _ = auth_context()
    require_role(role, ["ProjectManager"])
    p = get_project_or_404(pid)
    with db.LOCK:
        if p["status"] not in ("DRAFT", "ESTIMATED", "APPROVED"):
            raise err("ERR_INVALID_STATE", "Project cannot be cancelled from %s." % p["status"])
        from_state = p["status"]
        p["status"] = "CANCELLED"
        db.touch(p)
        # cascade: non-terminal crew bookings -> CANCELLED
        for cb in svc.project_crew_bookings(pid):
            if cb["status"] in ("HELD", "CONFIRMED"):
                cb["status"] = "CANCELLED"
                db.touch(cb)
        # cascade: SCHEDULED/INVOICED draws -> VOIDED
        for d in svc.project_draws(pid):
            if d["status"] in ("SCHEDULED", "INVOICED"):
                d["status"] = "VOIDED"
                db.touch(d)
        # cancelling from APPROVED also cancels PLACED/CONFIRMED material orders
        if from_state == "APPROVED":
            for mo in svc.project_material_orders(pid):
                if mo["status"] in ("PLACED", "CONFIRMED"):
                    mo["status"] = "CANCELLED"
                    db.touch(mo)
        svc.recompute_project_money(p)
        return ok(p)


# ===========================================================================
# Estimates
# ===========================================================================
@app.route("/projects/<pid>/estimates", methods=["POST"])
def create_estimate(pid):
    role, _ = auth_context()
    require_role(role, ["Estimator"])
    p = get_project_or_404(pid)
    data = body()
    tax_rate = data.get("tax_rate_pct")
    if tax_rate is None:
        tax_rate = 7.25
    with db.LOCK:
        rec = {
            "project_id": pid,
            "status": "DRAFT",
            "tax_rate_pct": tax_rate,
            "material_subtotal": calc.r2("0.00"),
            "labor_subtotal": calc.r2("0.00"),
            "material_tax": calc.r2("0.00"),
            "contract_total": calc.r2("0.00"),
            "reconciled_total": None,
        }
        db.stamp_create(rec)
        db.estimates[rec["id"]] = rec
        return created(rec)


@app.route("/projects/<pid>/estimates", methods=["GET"])
def list_estimates(pid):
    role, _ = auth_context()
    require_role(role, ALL_ROLES)
    get_project_or_404(pid)
    rows = sorted_by_created(svc.project_estimates(pid))
    page, limit, offset, total = paginate(rows)
    return list_response([svc.serialize(e) for e in page], limit, offset, total)


@app.route("/projects/<pid>/estimates/<eid>/price", methods=["POST"])
def price_estimate(pid, eid):
    role, _ = auth_context()
    require_role(role, ["Estimator"])
    p = get_project_or_404(pid)
    est = get_child_or_404(db.estimates, eid, pid, "Estimate")
    with db.LOCK:
        if est["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "Estimate must be DRAFT to be priced.")
        lines = svc.estimate_line_items(eid)
        if len(lines) == 0:
            raise err("ERR_EMPTY_ESTIMATE", "Cannot price an estimate with no line items.")
        svc.price_estimate_lines(est)
        est["status"] = "PRICED"
        db.touch(est)
        return ok(est)


@app.route("/projects/<pid>/estimates/<eid>/accept", methods=["POST"])
def accept_estimate(pid, eid):
    role, user_id = auth_context()
    require_role(role, ["Customer"])
    p = get_project_or_404(pid)
    est = get_child_or_404(db.estimates, eid, pid, "Estimate")
    with db.LOCK:
        # ownership: acting Customer X-User-ID must equal Project.customer_id
        if user_id != p["customer_id"]:
            raise err("ERR_FORBIDDEN", "Customer may only act on their own project.")
        if est["status"] != "PRICED":
            raise err("ERR_ESTIMATE_NOT_PRICED", "Estimate must be PRICED to be accepted.")
        # supersede any other ACCEPTED estimate
        for other in svc.project_estimates(pid):
            if other["id"] != eid and other["status"] == "ACCEPTED":
                other["status"] = "SUPERSEDED"
                db.touch(other)
        est["status"] = "ACCEPTED"
        db.touch(est)
        p["active_estimate_id"] = eid
        p["contract_total"] = calc.D(est["contract_total"])
        p["status"] = "ESTIMATED"
        svc.create_draws(p)
        svc.recompute_project_money(p)
        db.touch(p)
        return ok(est)


# ===========================================================================
# Line items (top-level collection, estimate_id in body)
# ===========================================================================
@app.route("/line-items", methods=["POST"])
def create_line_item():
    role, _ = auth_context()
    require_role(role, ["Estimator"])
    data = body()
    # referential: estimate_id must resolve
    est_id = data.get("estimate_id")
    if est_id is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: estimate_id")
    est = db.estimates.get(est_id)
    if est is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "estimate_id does not resolve to an Estimate.")
    # semantic validity (priority 4b): quantity_units > 0 when present
    if "quantity_units" in data and data["quantity_units"] is not None:
        positive_number(data["quantity_units"], "quantity_units")
    # request shape (priority 5)
    require_fields(data, ["work_type", "material", "style", "quantity_units"])
    require_enum(data["work_type"], WORK_TYPES, "work_type")
    require_enum(data["material"], MATERIALS, "material")
    require_enum(data["style"], STYLES, "style")
    accessory = data.get("accessory", "NONE")
    if accessory is None:
        accessory = "NONE"
    require_enum(accessory, ACCESSORIES, "accessory")
    grade_slope = data.get("grade_slope_pct", 0)
    if grade_slope is None:
        grade_slope = 0
    with db.LOCK:
        if est["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "Line items may only be added while the estimate is DRAFT.")
        rec = {
            "estimate_id": est_id,
            "work_type": data["work_type"],
            "material": data["material"],
            "style": data["style"],
            "quantity_units": data["quantity_units"],
            "accessory": accessory,
            "grade_slope_pct": grade_slope,
            "line_material_cost": None,
        }
        db.stamp_create(rec)
        db.line_items[rec["id"]] = rec
        return created(rec)


@app.route("/line-items/<lid>", methods=["GET"])
def get_line_item(lid):
    role, _ = auth_context()
    require_role(role, ALL_ROLES)
    rec = db.line_items.get(lid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Line item not found.")
    return ok(rec)


@app.route("/line-items", methods=["GET"])
def list_line_items():
    role, _ = auth_context()
    require_role(role, ALL_ROLES)
    rows = sorted_by_created(list(db.line_items.values()))
    est_id = request.args.get("estimate_id")
    if est_id is not None:
        rows = [li for li in rows if li["estimate_id"] == est_id]
    page, limit, offset, total = paginate(rows)
    return list_response([svc.serialize(li) for li in page], limit, offset, total)


# ===========================================================================
# Site measures
# ===========================================================================
@app.route("/projects/<pid>/site-measures", methods=["POST"])
def create_site_measure(pid):
    role, _ = auth_context()
    require_role(role, ["FieldTech"])
    p = get_project_or_404(pid)
    data = body()
    # semantic validity (priority 4b) for measured_quantities
    mq = data.get("measured_quantities")
    accepted = svc.accepted_estimate(pid)
    accepted_line_ids = set()
    if accepted is not None:
        accepted_line_ids = {li["id"] for li in svc.estimate_line_items(accepted["id"])}
    if mq is not None:
        if not isinstance(mq, list):
            raise err("ERR_VALIDATION", "measured_quantities must be a list.")
        for entry in mq:
            if not isinstance(entry, dict):
                raise err("ERR_VALIDATION", "measured_quantities entries must be objects.")
            li_id = entry.get("line_item_id")
            mu = entry.get("measured_units")
            if li_id not in accepted_line_ids:
                raise err("ERR_VALIDATION", "measured_quantities references a line not on the accepted estimate.")
            if mu is None:
                raise err("ERR_VALIDATION", "measured_units is required.")
            positive_number(mu, "measured_units")
    # request shape (priority 5)
    require_fields(data, ["measured_quantities", "property_line_note", "setback_ok"])
    if not isinstance(data["setback_ok"], bool):
        raise err("ERR_INVALID_REQUEST", "setback_ok must be a boolean.")
    with db.LOCK:
        rec = {
            "project_id": pid,
            "status": "RECORDED",
            "measured_quantities": data["measured_quantities"],
            "property_line_note": data["property_line_note"],
            "setback_ok": data["setback_ok"],
        }
        db.stamp_create(rec)
        db.site_measures[rec["id"]] = rec
        return created(rec)


@app.route("/projects/<pid>/site-measures", methods=["GET"])
def list_site_measures(pid):
    role, _ = auth_context()
    require_role(role, ALL_ROLES)
    get_project_or_404(pid)
    rows = sorted_by_created([s for s in db.site_measures.values() if s["project_id"] == pid])
    page, limit, offset, total = paginate(rows)
    return list_response([svc.serialize(s) for s in page], limit, offset, total)


@app.route("/projects/<pid>/site-measures/<smid>/approve", methods=["POST"])
def approve_site_measure(pid, smid):
    role, _ = auth_context()
    require_role(role, ["ProjectManager"])
    p = get_project_or_404(pid)
    sm = get_child_or_404(db.site_measures, smid, pid, "Site measure")
    with db.LOCK:
        # state (priority 7): measure RECORDED and project ESTIMATED
        if sm["status"] != "RECORDED" or p["status"] != "ESTIMATED":
            raise err("ERR_INVALID_STATE", "Site measure cannot be approved in the current state.")
        # business_safety (priority 8): setback gate
        if not sm["setback_ok"]:
            raise err("ERR_SETBACK_VIOLATION", "Site measure approval blocked: setback_ok is false.")
        sm["status"] = "APPROVED"
        db.touch(sm)
        # reconcile estimate
        est = svc.accepted_estimate(pid)
        if est is not None:
            overrides = {e["line_item_id"]: e["measured_units"] for e in sm.get("measured_quantities", [])}
            reconciled = svc.rollup_on_basis(est, overrides)
            est["reconciled_total"] = reconciled
            db.touch(est)
            p["contract_total"] = calc.D(reconciled)
        p["status"] = "MEASURED"
        svc.rebalance_draws(p)
        svc.recompute_project_money(p)
        db.touch(p)
        return ok(sm)


# ===========================================================================
# Permits
# ===========================================================================
@app.route("/projects/<pid>/permits", methods=["POST"])
def create_permit(pid):
    role, _ = auth_context()
    require_role(role, ["PermitClerk"])
    p = get_project_or_404(pid)
    data = body()
    require_fields(data, ["permit_type", "jurisdiction"])
    require_enum(data["permit_type"], PERMIT_TYPES, "permit_type")
    with db.LOCK:
        rec = {
            "project_id": pid,
            "permit_type": data["permit_type"],
            "status": "DRAFT",
            "jurisdiction": data["jurisdiction"],
            "return_reason": None,
        }
        db.stamp_create(rec)
        db.permits[rec["id"]] = rec
        return created(rec)


@app.route("/projects/<pid>/permits", methods=["GET"])
def list_permits(pid):
    role, _ = auth_context()
    require_role(role, ALL_ROLES)
    get_project_or_404(pid)
    rows = sorted_by_created(svc.project_permits(pid))
    page, limit, offset, total = paginate(rows)
    return list_response([svc.serialize(r) for r in page], limit, offset, total)


@app.route("/projects/<pid>/permits/<permit_id>/submit", methods=["POST"])
def submit_permit(pid, permit_id):
    role, _ = auth_context()
    require_role(role, ["PermitClerk"])
    p = get_project_or_404(pid)
    permit = get_child_or_404(db.permits, permit_id, pid, "Permit")
    with db.LOCK:
        if permit["status"] not in ("DRAFT", "RETURNED"):
            raise err("ERR_INVALID_STATE", "Permit must be DRAFT or RETURNED to submit.")
        # too-early gate: project must be MEASURED or APPROVED
        if p["status"] not in ("MEASURED", "APPROVED"):
            raise err("ERR_PERMIT_TOO_EARLY", "Permit cannot be submitted before the project is MEASURED.")
        permit["status"] = "SUBMITTED"
        permit["return_reason"] = None
        db.touch(permit)
        return ok(permit)


@app.route("/projects/<pid>/permits/<permit_id>/decide", methods=["POST"])
def decide_permit(pid, permit_id):
    role, _ = auth_context()
    require_role(role, ["PermitClerk"])
    p = get_project_or_404(pid)
    permit = get_child_or_404(db.permits, permit_id, pid, "Permit")
    data = body()
    require_fields(data, ["decision"])
    require_enum(data["decision"], {"ISSUE", "RETURN", "DENY"}, "decision")
    with db.LOCK:
        if permit["status"] != "SUBMITTED":
            raise err("ERR_INVALID_STATE", "Permit must be SUBMITTED to be decided.")
        decision = data["decision"]
        if decision == "RETURN":
            permit["status"] = "RETURNED"
            permit["return_reason"] = data.get("return_reason")
            db.touch(permit)
        elif decision == "ISSUE":
            permit["status"] = "ISSUED"
            db.touch(permit)
        else:  # DENY
            permit["status"] = "DENIED"
            db.touch(permit)
        _recompute_clearance_and_gate(p)
        return ok(permit)


# ===========================================================================
# HOA approvals
# ===========================================================================
@app.route("/projects/<pid>/hoa-approvals", methods=["POST"])
def create_hoa(pid):
    role, _ = auth_context()
    require_role(role, ["PermitClerk"])
    p = get_project_or_404(pid)
    data = body()
    require_fields(data, ["architectural_packet_ref"])
    with db.LOCK:
        rec = {
            "project_id": pid,
            "status": "SUBMITTED",
            "architectural_packet_ref": data["architectural_packet_ref"],
        }
        db.stamp_create(rec)
        db.hoa_approvals[rec["id"]] = rec
        return created(rec)


@app.route("/projects/<pid>/hoa-approvals", methods=["GET"])
def list_hoa(pid):
    role, _ = auth_context()
    require_role(role, ALL_ROLES)
    get_project_or_404(pid)
    rows = sorted_by_created(svc.project_hoas(pid))
    page, limit, offset, total = paginate(rows)
    return list_response([svc.serialize(r) for r in page], limit, offset, total)


@app.route("/projects/<pid>/hoa-approvals/<hoa_id>/decide", methods=["POST"])
def decide_hoa(pid, hoa_id):
    role, _ = auth_context()
    require_role(role, ["PermitClerk"])
    p = get_project_or_404(pid)
    hoa = get_child_or_404(db.hoa_approvals, hoa_id, pid, "HOA approval")
    data = body()
    require_fields(data, ["decision"])
    require_enum(data["decision"], {"APPROVE", "REJECT"}, "decision")
    with db.LOCK:
        if hoa["status"] != "SUBMITTED":
            raise err("ERR_INVALID_STATE", "HOA approval must be SUBMITTED to be decided.")
        hoa["status"] = "APPROVED" if data["decision"] == "APPROVE" else "REJECTED"
        db.touch(hoa)
        _recompute_clearance_and_gate(p)
        return ok(hoa)


def _recompute_clearance_and_gate(project):
    customer = db.customers.get(project["customer_id"], {})
    before = project["permit_clearance"]
    clearance = svc.recompute_permit_clearance(project, customer)
    changed = before != clearance
    gated = False
    if clearance == "CLEARED" and project["status"] == "MEASURED":
        project["status"] = "APPROVED"
        gated = True
    if changed or gated:
        db.touch(project)


# ===========================================================================
# Material orders
# ===========================================================================
@app.route("/projects/<pid>/material-orders", methods=["POST"])
def create_material_order(pid):
    role, _ = auth_context()
    require_role(role, ["ProjectManager"])
    p = get_project_or_404(pid)
    data = body()
    require_fields(data, ["supplier_name", "dock_id", "delivery_window_start", "delivery_window_end"])
    # validate datetimes parse
    try:
        clock.parse_iso(data["delivery_window_start"])
        clock.parse_iso(data["delivery_window_end"])
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "delivery window must be ISO 8601 datetimes.")
    waste = data.get("waste_factor_pct")
    if waste is None:
        waste = 10
    with db.LOCK:
        rec = {
            "project_id": pid,
            "status": "PLACED",
            "supplier_name": data["supplier_name"],
            "waste_factor_pct": waste,
            "ordered_lines": None,
            "dock_id": data["dock_id"],
            "delivery_window_start": data["delivery_window_start"],
            "delivery_window_end": data["delivery_window_end"],
        }
        db.stamp_create(rec)
        db.material_orders[rec["id"]] = rec
        return created(rec)


@app.route("/projects/<pid>/material-orders", methods=["GET"])
def list_material_orders(pid):
    role, _ = auth_context()
    require_role(role, ALL_ROLES)
    get_project_or_404(pid)
    rows = sorted_by_created(svc.project_material_orders(pid))
    page, limit, offset, total = paginate(rows)
    return list_response([svc.serialize(r) for r in page], limit, offset, total)


@app.route("/projects/<pid>/material-orders/<moid>/confirm", methods=["POST"])
def confirm_material_order(pid, moid):
    role, _ = auth_context()
    require_role(role, ["ProjectManager"])
    p = get_project_or_404(pid)
    mo = get_child_or_404(db.material_orders, moid, pid, "Material order")
    with db.LOCK:
        if mo["status"] != "PLACED":
            raise err("ERR_INVALID_STATE", "Material order must be PLACED to confirm.")
        # requires APPROVED site measure
        sm = svc.approved_site_measure(pid)
        if sm is None:
            raise err("ERR_MEASURE_REQUIRED", "Material order confirm requires an APPROVED site measure.")
        # dock window conflict check (priority 8b)
        _check_dock_conflict(mo)
        mo["status"] = "CONFIRMED"
        # material takeoff from measured units
        ordered = []
        for entry in sm.get("measured_quantities", []):
            ordered.append({
                "line_item_id": entry["line_item_id"],
                "ordered_units": calc.ordered_units(entry["measured_units"], mo["waste_factor_pct"]),
            })
        mo["ordered_lines"] = ordered
        db.touch(mo)
        return ok(mo)


def _check_dock_conflict(candidate):
    cand_start = clock.parse_iso(candidate["delivery_window_start"])
    cand_end = clock.parse_iso(candidate["delivery_window_end"])
    others = [
        m for m in db.material_orders.values()
        if m["id"] != candidate["id"]
        and m["dock_id"] == candidate["dock_id"]
        and m["status"] in ("CONFIRMED", "DELIVERED")
    ]
    others.sort(key=lambda m: m["_seq"])
    for ex in others:
        ex_start = clock.parse_iso(ex["delivery_window_start"])
        ex_end = clock.parse_iso(ex["delivery_window_end"])
        if calc.dock_conflict(cand_start, cand_end, ex_start, ex_end):
            raise err("ERR_DOCK_WINDOW_CONFLICT", "Delivery window conflicts on the same dock_id.")


@app.route("/projects/<pid>/material-orders/<moid>/deliver", methods=["POST"])
def deliver_material_order(pid, moid):
    role, _ = auth_context()
    require_role(role, ["FieldTech"])
    p = get_project_or_404(pid)
    mo = get_child_or_404(db.material_orders, moid, pid, "Material order")
    with db.LOCK:
        if mo["status"] != "CONFIRMED":
            raise err("ERR_INVALID_STATE", "Material order must be CONFIRMED to deliver.")
        mo["status"] = "DELIVERED"
        db.touch(mo)
        # side effect: SCHEDULED DELIVERY draw -> INVOICED
        for d in svc.project_draws(pid):
            if d["milestone"] == "DELIVERY" and d["status"] == "SCHEDULED":
                d["status"] = "INVOICED"
                db.touch(d)
        return ok(mo)


@app.route("/projects/<pid>/material-orders/<moid>/cancel", methods=["POST"])
def cancel_material_order(pid, moid):
    role, _ = auth_context()
    require_role(role, ["ProjectManager"])
    p = get_project_or_404(pid)
    mo = get_child_or_404(db.material_orders, moid, pid, "Material order")
    with db.LOCK:
        if mo["status"] not in ("PLACED", "CONFIRMED"):
            raise err("ERR_INVALID_STATE", "Material order must be PLACED or CONFIRMED to cancel.")
        mo["status"] = "CANCELLED"
        db.touch(mo)
        return ok(mo)


# ===========================================================================
# Crew bookings
# ===========================================================================
@app.route("/projects/<pid>/crew-bookings", methods=["POST"])
def create_crew_booking(pid):
    role, _ = auth_context()
    require_role(role, ["FieldTech"])
    p = get_project_or_404(pid)
    data = body()
    require_fields(data, ["crew_id", "window_start", "window_end"])
    try:
        clock.parse_iso(data["window_start"])
        clock.parse_iso(data["window_end"])
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "crew booking window must be ISO 8601 datetimes.")
    with db.LOCK:
        rec = {
            "project_id": pid,
            "crew_id": data["crew_id"],
            "status": "HELD",
            "window_start": data["window_start"],
            "window_end": data["window_end"],
        }
        db.stamp_create(rec)
        db.crew_bookings[rec["id"]] = rec
        return created(rec)


@app.route("/projects/<pid>/crew-bookings", methods=["GET"])
def list_crew_bookings(pid):
    role, _ = auth_context()
    require_role(role, ALL_ROLES)
    get_project_or_404(pid)
    rows = sorted_by_created(svc.project_crew_bookings(pid))
    page, limit, offset, total = paginate(rows)
    return list_response([svc.serialize(r) for r in page], limit, offset, total)


@app.route("/projects/<pid>/crew-bookings/<cbid>/confirm", methods=["POST"])
def confirm_crew_booking(pid, cbid):
    role, _ = auth_context()
    require_role(role, ["FieldTech"])
    p = get_project_or_404(pid)
    cb = get_child_or_404(db.crew_bookings, cbid, pid, "Crew booking")
    with db.LOCK:
        # state (priority 7): booking HELD and project APPROVED
        if cb["status"] != "HELD" or p["status"] != "APPROVED":
            raise err("ERR_INVALID_STATE", "Crew booking cannot be confirmed in the current state.")
        # crew overlap (priority 9) precedes material-readiness (priority 10)
        _check_crew_overlap(cb)
        # material readiness (priority 10)
        ready = any(
            m["status"] in ("CONFIRMED", "DELIVERED")
            for m in svc.project_material_orders(pid)
        )
        if not ready:
            raise err("ERR_MATERIAL_NOT_READY", "A CONFIRMED or DELIVERED material order is required.")
        cb["status"] = "CONFIRMED"
        db.touch(cb)
        # bubble project APPROVED -> SCHEDULED
        p["status"] = "SCHEDULED"
        db.touch(p)
        return ok(cb)


def _check_crew_overlap(candidate):
    cand_start = clock.parse_iso(candidate["window_start"])
    cand_end = clock.parse_iso(candidate["window_end"])
    others = [
        c for c in db.crew_bookings.values()
        if c["id"] != candidate["id"]
        and c["crew_id"] == candidate["crew_id"]
        and c["status"] == "CONFIRMED"
    ]
    others.sort(key=lambda c: c["_seq"])
    for ex in others:
        ex_start = clock.parse_iso(ex["window_start"])
        ex_end = clock.parse_iso(ex["window_end"])
        if calc.crew_overlap(cand_start, cand_end, ex_start, ex_end):
            raise err("ERR_CREW_DOUBLE_BOOKED", "Crew booking overlaps a CONFIRMED booking on the same crew_id.")


@app.route("/projects/<pid>/crew-bookings/<cbid>/cancel", methods=["POST"])
def cancel_crew_booking(pid, cbid):
    role, _ = auth_context()
    require_role(role, ["FieldTech"])
    p = get_project_or_404(pid)
    cb = get_child_or_404(db.crew_bookings, cbid, pid, "Crew booking")
    with db.LOCK:
        if cb["status"] not in ("HELD", "CONFIRMED"):
            raise err("ERR_INVALID_STATE", "Crew booking must be HELD or CONFIRMED to cancel.")
        cb["status"] = "CANCELLED"
        db.touch(cb)
        return ok(cb)


# ===========================================================================
# Change orders (top-level; project_id + line_item_id in body)
# ===========================================================================
@app.route("/change-orders", methods=["POST"])
def create_change_order():
    role, _ = auth_context()
    require_role(role, ["ProjectManager"])
    data = body()
    # existence/referential: project_id (404 not declared for body project_id;
    # treat unresolved project_id as reference-not-found per FK semantics)
    pid = data.get("project_id")
    if pid is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: project_id")
    p = db.projects.get(pid)
    if p is None:
        raise err("ERR_REFERENCE_NOT_FOUND", "project_id does not resolve to a Project.")
    # referential (priority 4): line_item_id must be on the project's ACCEPTED estimate
    li_id = data.get("line_item_id")
    if li_id is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: line_item_id")
    accepted = svc.accepted_estimate(pid)
    accepted_line_ids = set()
    if accepted is not None:
        accepted_line_ids = {li["id"] for li in svc.estimate_line_items(accepted["id"])}
    if li_id not in accepted_line_ids:
        raise err("ERR_REFERENCE_NOT_FOUND", "line_item_id is not on the project's ACCEPTED estimate.")
    # semantic validity (priority 4b): new_quantity_units > 0 when provided
    if data.get("new_quantity_units") is not None:
        positive_number(data["new_quantity_units"], "new_quantity_units")
    # request shape (priority 5): expected_project_version required
    if data.get("expected_project_version") is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: expected_project_version")
    new_accessory = data.get("new_accessory")
    if new_accessory is not None:
        require_enum(new_accessory, ACCESSORIES, "new_accessory")
    with db.LOCK:
        # OCC (priority 6)
        if int(data["expected_project_version"]) != p["version"]:
            raise err("ERR_STALE_PROJECT_VERSION", "expected_project_version does not match current project version.")
        rec = {
            "project_id": pid,
            "line_item_id": li_id,
            "status": "DRAFT",
            "new_quantity_units": data.get("new_quantity_units"),
            "new_accessory": new_accessory,
            "expected_project_version": int(data["expected_project_version"]),
            "total_delta": None,
        }
        db.stamp_create(rec)
        db.change_orders[rec["id"]] = rec
        # creating the draft claims the pricing baseline: bump project version
        db.touch(p)
        return created(rec)


@app.route("/change-orders/<coid>", methods=["GET"])
def get_change_order(coid):
    role, _ = auth_context()
    require_role(role, ALL_ROLES)
    rec = db.change_orders.get(coid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Change order not found.")
    return ok(rec)


@app.route("/change-orders", methods=["GET"])
def list_change_orders():
    role, _ = auth_context()
    require_role(role, ALL_ROLES)
    rows = sorted_by_created(list(db.change_orders.values()))
    pid = request.args.get("project_id")
    if pid is not None:
        rows = [c for c in rows if c["project_id"] == pid]
    li_id = request.args.get("line_item_id")
    if li_id is not None:
        rows = [c for c in rows if c["line_item_id"] == li_id]
    page, limit, offset, total = paginate(rows)
    return list_response([svc.serialize(c) for c in page], limit, offset, total)


@app.route("/change-orders/<coid>/apply", methods=["POST"])
def apply_change_order(coid):
    role, _ = auth_context()
    require_role(role, ["ProjectManager"])
    co = db.change_orders.get(coid)
    if co is None:
        raise err("ERR_NOT_FOUND", "Change order not found.")
    p = db.projects.get(co["project_id"])
    if p is None:
        raise err("ERR_NOT_FOUND", "Project not found.")
    with db.LOCK:
        if co["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "Change order must be DRAFT to apply.")
        # too-late gate
        if p["status"] not in ("ESTIMATED", "MEASURED", "APPROVED"):
            raise err("ERR_CHANGE_ORDER_TOO_LATE", "Change order cannot be applied at this project stage.")
        # target line must still belong to the project's ACCEPTED estimate
        accepted = svc.accepted_estimate(p["id"])
        if accepted is None:
            raise err("ERR_INVALID_STATE", "No accepted estimate to apply against.")
        li = db.line_items.get(co["line_item_id"])
        if li is None or li["estimate_id"] != accepted["id"]:
            raise err("ERR_INVALID_STATE", "Target line item no longer belongs to the accepted estimate.")
        prior_total = calc.D(p["contract_total"])
        # 1) mutate target line
        if co["new_quantity_units"] is not None:
            li["quantity_units"] = co["new_quantity_units"]
        if co["new_accessory"] is not None:
            li["accessory"] = co["new_accessory"]
        # 2) recompute the target line cost
        li["line_material_cost"] = calc.line_material_cost(
            li["material"], li["style"], li["quantity_units"], li["accessory"], li["grade_slope_pct"],
        )
        db.touch(li)
        # 3) recompute estimate totals + project contract_total on the correct basis
        measured = svc.measured_quantity_map(p["id"])  # empty if no approved measure
        if measured:
            # measured basis: untouched siblings use measured_units; target uses
            # its (now-updated) quantity_units. Build overrides for all lines.
            overrides = {}
            for sib in svc.estimate_line_items(accepted["id"]):
                if sib["id"] == li["id"]:
                    overrides[sib["id"]] = li["quantity_units"]
                elif sib["id"] in measured:
                    overrides[sib["id"]] = measured[sib["id"]]
                # siblings without a measured value keep their estimate quantity
            new_total = svc.rollup_on_basis(accepted, overrides)
            # also refresh estimate computed subtotals to the measured basis
            _set_estimate_totals(accepted, overrides)
            accepted["reconciled_total"] = new_total
        else:
            # estimate basis: roll up on the estimate's stored quantities
            new_total = svc.price_estimate_lines(accepted)
        db.touch(accepted)
        p["contract_total"] = calc.D(new_total)
        # 4) total_delta
        co["total_delta"] = calc.r2(calc.D(new_total) - prior_total)
        co["status"] = "APPLIED"
        db.touch(co)
        # 5) rebalance draws + bump project version
        svc.rebalance_draws(p)
        svc.recompute_project_money(p)
        db.touch(p)
        return ok(co)


def _set_estimate_totals(estimate, overrides):
    """Recompute and store estimate subtotals using override quantities."""
    lines = svc.estimate_line_items(estimate["id"])
    priced = []
    for li in lines:
        qty = overrides.get(li["id"], li["quantity_units"])
        lmc = calc.line_material_cost(
            li["material"], li["style"], qty, li["accessory"], li["grade_slope_pct"],
        )
        priced.append({
            "work_type": li["work_type"],
            "quantity_units": qty,
            "line_material_cost": lmc,
        })
    ms, ls, mt, ct = calc.rollup(priced, estimate["tax_rate_pct"])
    estimate["material_subtotal"] = ms
    estimate["labor_subtotal"] = ls
    estimate["material_tax"] = mt
    estimate["contract_total"] = ct


@app.route("/change-orders/<coid>/decide", methods=["POST"])
def decide_change_order(coid):
    role, _ = auth_context()
    require_role(role, ["ProjectManager"])
    co = db.change_orders.get(coid)
    if co is None:
        raise err("ERR_NOT_FOUND", "Change order not found.")
    data = body()
    require_fields(data, ["decision"])
    require_enum(data["decision"], {"REJECT"}, "decision")
    with db.LOCK:
        if co["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "Change order must be DRAFT to reject.")
        co["status"] = "REJECTED"
        db.touch(co)
        return ok(co)


@app.route("/change-orders/<coid>/withdraw", methods=["POST"])
def withdraw_change_order(coid):
    role, _ = auth_context()
    require_role(role, ["ProjectManager"])
    co = db.change_orders.get(coid)
    if co is None:
        raise err("ERR_NOT_FOUND", "Change order not found.")
    with db.LOCK:
        if co["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "Change order must be DRAFT to withdraw.")
        co["status"] = "WITHDRAWN"
        db.touch(co)
        return ok(co)


# ===========================================================================
# Draws
# ===========================================================================
@app.route("/projects/<pid>/draws", methods=["GET"])
def list_draws(pid):
    role, _ = auth_context()
    require_role(role, ALL_ROLES)
    get_project_or_404(pid)
    rows = svc.project_draws(pid)  # already milestone-ordered
    page, limit, offset, total = paginate(rows)
    return list_response([svc.serialize(d) for d in page], limit, offset, total)


@app.route("/projects/<pid>/draws/<draw_id>/invoice", methods=["POST"])
def invoice_draw(pid, draw_id):
    role, _ = auth_context()
    require_role(role, ["ProjectManager"])
    p = get_project_or_404(pid)
    d = get_child_or_404(db.draws, draw_id, pid, "Draw")
    with db.LOCK:
        if d["status"] != "SCHEDULED":
            raise err("ERR_INVALID_STATE", "Draw must be SCHEDULED to invoice.")
        _check_draw_gate(p, d)
        d["status"] = "INVOICED"
        db.touch(d)
        return ok(d)


def _check_draw_gate(project, draw):
    milestone = draw["milestone"]
    if milestone == "DEPOSIT":
        return  # always
    if milestone == "DELIVERY":
        if not any(m["status"] == "DELIVERED" for m in svc.project_material_orders(project["id"])):
            raise err("ERR_DRAW_GATE_NOT_MET", "DELIVERY draw requires a DELIVERED material order.")
        return
    if milestone == "FRAMING":
        if project["status"] != "IN_PROGRESS":
            raise err("ERR_DRAW_GATE_NOT_MET", "FRAMING draw requires the project to be IN_PROGRESS.")
        return
    if milestone == "FINAL":
        prior = [d for d in svc.project_draws(project["id"]) if d["milestone"] != "FINAL"]
        for d in prior:
            if d["status"] not in ("PAID", "VOIDED"):
                raise err("ERR_DRAW_GATE_NOT_MET", "FINAL draw requires all prior non-VOIDED draws PAID.")
        return


@app.route("/projects/<pid>/draws/<draw_id>/pay", methods=["POST"])
def pay_draw(pid, draw_id):
    role, _ = auth_context()
    require_role(role, ["ProjectManager"])
    p = get_project_or_404(pid)
    d = get_child_or_404(db.draws, draw_id, pid, "Draw")
    with db.LOCK:
        if d["status"] != "INVOICED":
            raise err("ERR_INVALID_STATE", "Draw must be INVOICED to pay.")
        # FINAL sequence gate (priority 12)
        if d["milestone"] == "FINAL":
            for other in svc.project_draws(pid):
                if other["milestone"] != "FINAL" and other["status"] not in ("PAID", "VOIDED"):
                    raise err("ERR_DRAW_SEQUENCE_VIOLATION", "FINAL draw cannot be paid before all prior non-VOIDED draws are PAID.")
        d["status"] = "PAID"
        db.touch(d)
        svc.recompute_project_money(p)
        # gate side effects
        if d["milestone"] == "DEPOSIT" and p["status"] == "SCHEDULED":
            p["status"] = "IN_PROGRESS"
        elif d["milestone"] == "FINAL" and p["status"] == "IN_PROGRESS":
            p["status"] = "COMPLETED"
            _issue_warranty(p)
        db.touch(p)
        return ok(d)


def _issue_warranty(project):
    rec = {
        "project_id": project["id"],
        "status": "ISSUED",
        "coverage_years": 5,
        "workmanship_only": False,
    }
    db.stamp_create(rec)
    db.warranties[rec["id"]] = rec


# ===========================================================================
# Warranties
# ===========================================================================
@app.route("/projects/<pid>/warranties", methods=["GET"])
def list_warranties(pid):
    role, _ = auth_context()
    require_role(role, ALL_ROLES)
    get_project_or_404(pid)
    rows = sorted_by_created(svc.project_warranties(pid))
    with db.LOCK:
        for w in rows:
            svc.apply_warranty_expiry(w)
    page, limit, offset, total = paginate(rows)
    return list_response([svc.serialize(w) for w in page], limit, offset, total)


@app.route("/projects/<pid>/warranties/<wid>", methods=["PATCH"])
def update_warranty(pid, wid):
    role, _ = auth_context()
    require_role(role, ["ProjectManager"])
    p = get_project_or_404(pid)
    w = get_child_or_404(db.warranties, wid, pid, "Warranty")
    data = body()
    with db.LOCK:
        svc.apply_warranty_expiry(w)
        if w["status"] != "ISSUED":
            raise err("ERR_INVALID_STATE", "Warranty terms may only be updated while ISSUED.")
        if "coverage_years" in data and data["coverage_years"] is not None:
            cy = data["coverage_years"]
            if not isinstance(cy, int) or isinstance(cy, bool) or cy <= 0:
                raise err("ERR_INVALID_REQUEST", "coverage_years must be a positive integer.")
            w["coverage_years"] = cy
        if "workmanship_only" in data and data["workmanship_only"] is not None:
            if not isinstance(data["workmanship_only"], bool):
                raise err("ERR_INVALID_REQUEST", "workmanship_only must be a boolean.")
            w["workmanship_only"] = data["workmanship_only"]
        db.touch(w)
        return ok(w)


@app.route("/projects/<pid>/warranties/<wid>/claim", methods=["POST"])
def claim_warranty(pid, wid):
    role, user_id = auth_context()
    require_role(role, ["Customer"])
    p = get_project_or_404(pid)
    w = get_child_or_404(db.warranties, wid, pid, "Warranty")
    with db.LOCK:
        # ownership check
        if user_id != p["customer_id"]:
            raise err("ERR_FORBIDDEN", "Customer may only act on their own project.")
        svc.apply_warranty_expiry(w)
        if p["status"] != "COMPLETED":
            raise err("ERR_INVALID_STATE", "Warranty claim requires the project to be COMPLETED.")
        if w["status"] != "ISSUED":
            raise err("ERR_INVALID_STATE", "Warranty must be ISSUED to claim.")
        w["status"] = "CLAIMED"
        db.touch(w)
        return ok(w)


@app.route("/projects/<pid>/warranties/<wid>/resolve", methods=["POST"])
def resolve_warranty(pid, wid):
    role, _ = auth_context()
    require_role(role, ["ProjectManager"])
    p = get_project_or_404(pid)
    w = get_child_or_404(db.warranties, wid, pid, "Warranty")
    data = body()
    require_fields(data, ["resolution"])
    require_enum(data["resolution"], {"REPAIRED", "DENIED"}, "resolution")
    with db.LOCK:
        if w["status"] != "CLAIMED":
            raise err("ERR_INVALID_STATE", "Warranty must be CLAIMED to resolve.")
        w["status"] = "ISSUED" if data["resolution"] == "REPAIRED" else "VOIDED"
        db.touch(w)
        return ok(w)


# ===========================================================================
# Clock control (test-driving)
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    role, _ = auth_context()
    require_role(role, ["ProjectManager"])
    data = body()
    require_fields(data, ["to_iso8601"])
    try:
        dt = clock.parse_iso(data["to_iso8601"])
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 datetime.")
    clock.set_current_utc(dt)
    return success({}, status=200, response_type="object")


# ===========================================================================
# Main
# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
