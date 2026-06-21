"""PLM / ECO REST API — entry point and all routes (PRD task_0438_plm_eco).

Python + Flask. In-memory store only. No seeding. Reads PORT, binds 0.0.0.0,
runs in the foreground.
"""
import os

from flask import Flask, request

from db import store, CLOCK_DEFAULT
from errors import ApiError, err
from response import success, error
from middleware import extract_identity, require_role
import common
from common import (
    new_entity,
    touch,
    public,
    get_json,
    require_str,
    optional_str,
    require_enum,
    require_int,
    optional_int,
    optional_number,
    parse_pagination,
    paginate,
)
import services

app = Flask(__name__)

ALL_ROLES = [
    "Designer",
    "ChangeAdmin",
    "Approver",
    "QualityEngineer",
    "SupplierManager",
    "Viewer",
]


# =============================================================================
# Error handling
# =============================================================================

@app.errorhandler(ApiError)
def handle_api_error(e):
    return error(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error(e.error_id, e.message, e.http_status)
    return error("ERR_INVALID_REQUEST", "Unexpected error: %s" % e, 422)


# =============================================================================
# Auth + RBAC helper
# =============================================================================

def authorize(allowed_roles):
    """Validate auth headers (priority 1) then role (priority 2)."""
    user_id, role = extract_identity(request.headers)
    require_role(role, allowed_roles)
    return user_id, role


# =============================================================================
# Lookup helpers (existence — priority 3, ERR_NOT_FOUND)
# =============================================================================

def get_or_404(collection, entity_id):
    entity = collection.get(entity_id)
    if entity is None:
        raise err("ERR_NOT_FOUND", "Resource %s not found" % entity_id)
    return entity


# =============================================================================
# Output serializers
# =============================================================================

def out_supplier(s):
    return public(s)


def out_part(p):
    return public(p)


def out_revision(r):
    return public(r)


def out_bom_line(l):
    return public(l)


def out_ecr(e):
    return public(e)


def out_eco(e):
    return public(e)


def out_task(t):
    return public(t)


def out_affected_item(i):
    return public(i)


def out_document(d):
    return public(d)


def out_deviation(d):
    return public(d)


def out_pcn(p):
    return public(p)


def out_unit(u):
    return public(u)


# =============================================================================
# Generic list response builder
# =============================================================================

def list_response(rows, serializer):
    limit, offset = parse_pagination(request.args)
    page, meta = paginate(rows, limit, offset)
    return success([serializer(r) for r in page], 200, is_list=True, pagination=meta)


# =============================================================================
# Logical clock (PRD Section 2.4)
# =============================================================================

@app.route("/plm/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authorize(["ChangeAdmin", "QualityEngineer"])
    body = get_json(request)
    iso = require_str(body, "to_iso8601")
    store.clock = services.parse_iso(iso)
    # 200 with no data -> empty object (PRD 2.2).
    return success({}, 200)


# =============================================================================
# Supplier (PRD Section 3.1)
# =============================================================================

@app.route("/plm/suppliers", methods=["POST"])
def create_supplier():
    authorize(["SupplierManager"])
    body = get_json(request)
    name = require_str(body, "name")
    code = require_str(body, "supplier_code").upper()
    # supplier_code unique across all suppliers (uppercased).
    for s in store.suppliers.values():
        if s["supplier_code"] == code:
            raise err("ERR_INVALID_REQUEST", "supplier_code must be unique")
    supplier = new_entity({
        "name": name,
        "supplier_code": code,
        "status": "ACTIVE",
    })
    store.suppliers[supplier["id"]] = supplier
    return success(out_supplier(supplier), 201)


@app.route("/plm/suppliers/<sid>", methods=["GET"])
def get_supplier(sid):
    authorize(ALL_ROLES)
    return success(out_supplier(get_or_404(store.suppliers, sid)), 200)


@app.route("/plm/suppliers", methods=["GET"])
def list_suppliers():
    authorize(ALL_ROLES)
    rows = list(store.suppliers.values())
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, out_supplier)


# =============================================================================
# Part (PRD Section 3.1)
# =============================================================================

@app.route("/plm/parts", methods=["POST"])
def create_part():
    authorize(["Designer"])
    body = get_json(request)
    part_number = require_str(body, "part_number").upper()
    name = require_str(body, "name")
    part_type = require_enum(body, "part_type", {"MAKE", "BUY", "PHANTOM"})
    base_cost = optional_int(body, "base_cost_cents", 0, minimum=0)
    default_supplier_id = optional_str(body, "default_supplier_id", None)

    # part_number unique across all parts (uppercased).
    for p in store.parts.values():
        if p["part_number"] == part_number:
            raise err("ERR_INVALID_REQUEST", "part_number must be unique")

    # Supplier linkage is type-sensitive (PRD 3.1).
    if part_type == "BUY":
        if not default_supplier_id:
            raise err("ERR_INVALID_REQUEST", "BUY part requires default_supplier_id")
        get_or_404(store.suppliers, default_supplier_id)
    else:
        if default_supplier_id is not None:
            raise err("ERR_INVALID_REQUEST", "MAKE/PHANTOM part must omit default_supplier_id")

    part = new_entity({
        "part_number": part_number,
        "name": name,
        "part_type": part_type,
        "base_cost_cents": base_cost,
        "default_supplier_id": default_supplier_id,
        "released_revision_id": None,
        "revision_count": 0,
    })
    store.parts[part["id"]] = part
    return success(out_part(part), 201)


@app.route("/plm/parts/<pid>", methods=["GET"])
def get_part(pid):
    authorize(ALL_ROLES)
    return success(out_part(get_or_404(store.parts, pid)), 200)


@app.route("/plm/parts", methods=["GET"])
def list_parts():
    authorize(ALL_ROLES)
    rows = list(store.parts.values())
    pt = request.args.get("part_type")
    if pt is not None:
        rows = [r for r in rows if r["part_type"] == pt]
    sup = request.args.get("default_supplier_id")
    if sup is not None:
        rows = [r for r in rows if r.get("default_supplier_id") == sup]
    rel = request.args.get("released_revision_id")
    if rel is not None:
        rows = [r for r in rows if r.get("released_revision_id") == rel]
    return list_response(rows, out_part)


@app.route("/plm/parts/<pid>/where-used", methods=["GET"])
def part_where_used(pid):
    authorize(ALL_ROLES)
    part = get_or_404(store.parts, pid)
    return success(services.where_used(part), 200)


# =============================================================================
# PartRevision (PRD Sections 3.2, 3.3, 2.7)
# =============================================================================

@app.route("/plm/parts/<pid>/revisions", methods=["POST"])
def create_revision(pid):
    authorize(["Designer"])
    part = get_or_404(store.parts, pid)
    body = get_json(request)
    # expected_part_version is required (PRD 2.7).
    expected = require_int(body, "expected_part_version")
    if expected != part["version"]:
        raise err("ERR_STALE_VERSION", "expected_part_version does not match current part version")

    # Assign next rev_label in per-part sequence A, B, C, ...
    existing = services.revisions_of_part(pid)
    next_label = chr(ord("A") + len(existing))
    supersedes = part.get("released_revision_id")  # null for first revision

    rev = new_entity({
        "part_id": pid,
        "rev_label": next_label,
        "supersedes_revision_id": supersedes,
        "governing_change_order_id": None,
        "lifecycle_state": "WORKING",
        "planned_cost_cents": 0,
        "effective_cost_cents": 0,
    })
    store.part_revisions[rev["id"]] = rev

    # Increment part.revision_count and part.version.
    part["revision_count"] = len(services.revisions_of_part(pid))
    touch(part)  # bumps version by 1 and updated_at

    services.recompute_and_store_costs(rev)
    return success(out_revision(rev), 201)


@app.route("/plm/parts/<pid>/revisions", methods=["GET"])
def list_part_revisions(pid):
    authorize(ALL_ROLES)
    get_or_404(store.parts, pid)
    rows = services.revisions_of_part(pid)
    ls = request.args.get("lifecycle_state")
    if ls is not None:
        rows = [r for r in rows if r["lifecycle_state"] == ls]
    return list_response(rows, out_revision)


@app.route("/plm/part-revisions/<rid>", methods=["GET"])
def get_revision(rid):
    authorize(ALL_ROLES)
    return success(out_revision(get_or_404(store.part_revisions, rid)), 200)


@app.route("/plm/part-revisions", methods=["GET"])
def list_revisions():
    authorize(ALL_ROLES)
    rows = list(store.part_revisions.values())
    for field in ("part_id", "supersedes_revision_id", "governing_change_order_id", "lifecycle_state"):
        val = request.args.get(field)
        if val is not None:
            rows = [r for r in rows if r.get(field) == val]
    return list_response(rows, out_revision)


@app.route("/plm/part-revisions/<rid>/cost", methods=["GET"])
def revision_cost(rid):
    authorize(ALL_ROLES)
    rev = get_or_404(store.part_revisions, rid)
    planned, effective = services.recompute_and_store_costs(rev)
    return success({
        "part_revision_id": rid,
        "planned_cost_cents": planned,
        "effective_cost_cents": effective,
    }, 200)


@app.route("/plm/part-revisions/<rid>/submit-review", methods=["POST"])
def submit_review_revision(rid):
    authorize(["Designer"])
    rev = get_or_404(store.part_revisions, rid)
    if rev["lifecycle_state"] != "WORKING":
        raise err("ERR_INVALID_STATE", "Revision is not WORKING")
    part = store.parts[rev["part_id"]]
    # MAKE/PHANTOM must have at least one BOM line (BUY exempt).
    if part["part_type"] in ("MAKE", "PHANTOM"):
        if not services.bom_lines_of_revision(rid):
            raise err("ERR_EMPTY_BOM", "MAKE/PHANTOM revision needs at least one BOM line")
    rev["lifecycle_state"] = "IN_REVIEW"
    services.recompute_and_store_costs(rev)
    touch(rev)
    return success(out_revision(rev), 200)


@app.route("/plm/part-revisions/<rid>/return-to-work", methods=["POST"])
def return_to_work_revision(rid):
    authorize(["Designer"])
    rev = get_or_404(store.part_revisions, rid)
    if rev["lifecycle_state"] != "IN_REVIEW":
        raise err("ERR_INVALID_STATE", "Revision is not IN_REVIEW")
    rev["lifecycle_state"] = "WORKING"
    touch(rev)
    return success(out_revision(rev), 200)


# =============================================================================
# BomLine (PRD Sections 3.2, 2.7)
# =============================================================================

@app.route("/plm/part-revisions/<rid>/bom-lines", methods=["POST"])
def add_bom_line(rid):
    authorize(["Designer"])
    rev = get_or_404(store.part_revisions, rid)
    body = get_json(request)
    child_part_id = require_str(body, "child_part_id")
    quantity = require_int(body, "quantity", minimum=1)
    scrap_factor = optional_number(body, "scrap_factor", 0, minimum=0)
    reference_designator = optional_str(body, "reference_designator", "")
    expected = require_int(body, "expected_part_revision_version")

    # Existence of child part (left-to-right, after revision).
    get_or_404(store.parts, child_part_id)

    # State: line may only be added to a WORKING revision.
    if rev["lifecycle_state"] != "WORKING":
        raise err("ERR_INVALID_STATE", "BOM lines may only be added to a WORKING revision")

    # OCC on PartRevision.version.
    if expected != rev["version"]:
        raise err("ERR_STALE_VERSION", "expected_part_revision_version does not match current revision version")

    # Cycle check.
    if services.would_create_cycle(rev, child_part_id):
        raise err("ERR_BOM_CYCLE", "Adding this BOM line would create a cycle")

    line = new_entity({
        "parent_revision_id": rid,
        "child_part_id": child_part_id,
        "quantity": quantity,
        "scrap_factor": scrap_factor,
        "reference_designator": reference_designator,
    })
    store.bom_lines[line["id"]] = line

    # Append BomLine increments the revision version.
    touch(rev)
    # Adding a line recomputes the revision's costs (PRD 3.3).
    services.recompute_and_store_costs(rev)
    return success(out_bom_line(line), 201)


@app.route("/plm/part-revisions/<rid>/bom-lines", methods=["GET"])
def list_revision_bom_lines(rid):
    authorize(ALL_ROLES)
    get_or_404(store.part_revisions, rid)
    rows = [l for l in store.bom_lines.values() if l["parent_revision_id"] == rid]
    return list_response(rows, out_bom_line)


@app.route("/plm/bom-lines/<lid>", methods=["GET"])
def get_bom_line(lid):
    authorize(ALL_ROLES)
    return success(out_bom_line(get_or_404(store.bom_lines, lid)), 200)


@app.route("/plm/bom-lines", methods=["GET"])
def list_bom_lines():
    authorize(ALL_ROLES)
    rows = list(store.bom_lines.values())
    cpid = request.args.get("child_part_id")
    if cpid is not None:
        rows = [r for r in rows if r["child_part_id"] == cpid]
    prid = request.args.get("parent_revision_id")
    if prid is not None:
        rows = [r for r in rows if r["parent_revision_id"] == prid]
    return list_response(rows, out_bom_line)


# =============================================================================
# EngineeringChangeRequest (PRD Section 3.5)
# =============================================================================

@app.route("/plm/change-requests", methods=["POST"])
def create_ecr():
    authorize(["Designer"])
    body = get_json(request)
    title = require_str(body, "title")
    affected_part_id = require_str(body, "affected_part_id")
    reason_code = require_enum(
        body, "reason_code",
        {"DESIGN_DEFECT", "COST_REDUCTION", "SUPPLIER_CHANGE", "OBSOLESCENCE"},
    )
    get_or_404(store.parts, affected_part_id)
    ecr = new_entity({
        "title": title,
        "affected_part_id": affected_part_id,
        "reason_code": reason_code,
        "source_pcn_id": None,
        "submitted_by_user_id": None,
        "status": "DRAFT",
    })
    store.change_requests[ecr["id"]] = ecr
    return success(out_ecr(ecr), 201)


@app.route("/plm/change-requests/<cid>", methods=["GET"])
def get_ecr(cid):
    authorize(ALL_ROLES)
    return success(out_ecr(get_or_404(store.change_requests, cid)), 200)


@app.route("/plm/change-requests", methods=["GET"])
def list_ecrs():
    authorize(ALL_ROLES)
    rows = list(store.change_requests.values())
    for field in ("affected_part_id", "source_pcn_id", "status"):
        val = request.args.get(field)
        if val is not None:
            rows = [r for r in rows if r.get(field) == val]
    return list_response(rows, out_ecr)


@app.route("/plm/change-requests/<cid>/submit", methods=["POST"])
def submit_ecr(cid):
    user_id, _ = authorize(["Designer"])
    ecr = get_or_404(store.change_requests, cid)
    if ecr["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "ECR is not DRAFT")
    # Confirm affected part still exists (PRD 3.5).
    get_or_404(store.parts, ecr["affected_part_id"])
    ecr["status"] = "SUBMITTED"
    ecr["submitted_by_user_id"] = user_id
    touch(ecr)
    return success(out_ecr(ecr), 200)


@app.route("/plm/change-requests/<cid>/approve", methods=["POST"])
def approve_ecr(cid):
    authorize(["ChangeAdmin"])
    ecr = get_or_404(store.change_requests, cid)
    if ecr["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "ECR is not SUBMITTED")
    ecr["status"] = "APPROVED"
    touch(ecr)
    return success(out_ecr(ecr), 200)


@app.route("/plm/change-requests/<cid>/reject", methods=["POST"])
def reject_ecr(cid):
    authorize(["ChangeAdmin"])
    ecr = get_or_404(store.change_requests, cid)
    if ecr["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "ECR is not SUBMITTED")
    ecr["status"] = "REJECTED"
    touch(ecr)
    return success(out_ecr(ecr), 200)


@app.route("/plm/change-requests/<cid>/reopen", methods=["POST"])
def reopen_ecr(cid):
    authorize(["Designer"])
    ecr = get_or_404(store.change_requests, cid)
    if ecr["status"] != "REJECTED":
        raise err("ERR_INVALID_STATE", "ECR is not REJECTED")
    ecr["status"] = "DRAFT"
    ecr["submitted_by_user_id"] = None
    touch(ecr)
    return success(out_ecr(ecr), 200)


# =============================================================================
# EngineeringChangeOrder (PRD Sections 3.5, 3.6, 3.7)
# =============================================================================

@app.route("/plm/change-orders", methods=["POST"])
def create_eco():
    user_id, _ = authorize(["ChangeAdmin"])
    body = get_json(request)
    change_request_id = require_str(body, "change_request_id")
    effectivity_iso = require_str(body, "effectivity_date")
    required_approvals = optional_int(body, "required_approvals", 2, minimum=1)
    get_or_404(store.change_requests, change_request_id)
    # Validate effectivity_date is a parseable ISO instant; store the raw string.
    services.parse_iso(effectivity_iso)

    eco = new_entity({
        "change_request_id": change_request_id,
        "created_by_user_id": user_id,
        "required_approvals": required_approvals,
        "approval_count": 0,
        "effectivity_date": effectivity_iso,
        "status": "DRAFT",
    })
    store.change_orders[eco["id"]] = eco
    return success(out_eco(eco), 201)


@app.route("/plm/change-orders/<eid>", methods=["GET"])
def get_eco(eid):
    authorize(ALL_ROLES)
    return success(out_eco(get_or_404(store.change_orders, eid)), 200)


@app.route("/plm/change-orders", methods=["GET"])
def list_ecos():
    authorize(ALL_ROLES)
    rows = list(store.change_orders.values())
    for field in ("change_request_id", "status"):
        val = request.args.get(field)
        if val is not None:
            rows = [r for r in rows if r.get(field) == val]
    return list_response(rows, out_eco)


@app.route("/plm/change-orders/<eid>/affected-items", methods=["POST"])
def add_affected_item(eid):
    authorize(["ChangeAdmin"])
    eco = get_or_404(store.change_orders, eid)
    body = get_json(request)
    part_revision_id = require_str(body, "part_revision_id")
    rev = get_or_404(store.part_revisions, part_revision_id)
    # Affected items are attached only while the ECO is DRAFT (PRD 3.5).
    if eco["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Affected items may only be attached to a DRAFT ECO")
    # Exclusive occupancy: a revision may be governed by at most one
    # non-terminal ECO at a time (PRD 3.5, validation priority 12.5).
    gov_id = rev.get("governing_change_order_id")
    if gov_id is not None:
        gov_eco = store.change_orders.get(gov_id)
        if gov_eco is not None and gov_eco["status"] in services.NON_TERMINAL_ECO_STATES:
            raise err("ERR_REVISION_ALREADY_GOVERNED", "Revision is already governed by a non-terminal ECO")

    item = new_entity({
        "change_order_id": eid,
        "part_revision_id": part_revision_id,
        "pinned": False,
    })
    store.affected_items[item["id"]] = item
    rev["governing_change_order_id"] = eid
    touch(rev)
    return success(out_affected_item(item), 201)


@app.route("/plm/change-orders/<eid>/affected-items", methods=["GET"])
def list_eco_affected_items(eid):
    authorize(ALL_ROLES)
    get_or_404(store.change_orders, eid)
    rows = [i for i in store.affected_items.values() if i["change_order_id"] == eid]
    return list_response(rows, out_affected_item)


@app.route("/plm/affected-items/<iid>", methods=["GET"])
def get_affected_item(iid):
    authorize(ALL_ROLES)
    return success(out_affected_item(get_or_404(store.affected_items, iid)), 200)


@app.route("/plm/affected-items", methods=["GET"])
def list_affected_items():
    authorize(ALL_ROLES)
    rows = list(store.affected_items.values())
    for field in ("part_revision_id", "change_order_id"):
        val = request.args.get(field)
        if val is not None:
            rows = [r for r in rows if r.get(field) == val]
    return list_response(rows, out_affected_item)


@app.route("/plm/change-orders/<eid>/approval-tasks", methods=["POST"])
def add_approval_task(eid):
    authorize(["ChangeAdmin"])
    eco = get_or_404(store.change_orders, eid)
    body = get_json(request)
    assignee_user_id = require_str(body, "assignee_user_id")
    # Approval tasks added to a DRAFT ECO (PRD 3.5).
    if eco["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Approval tasks may only be added to a DRAFT ECO")
    task = new_entity({
        "change_order_id": eid,
        "assignee_user_id": assignee_user_id,
        "decision": "PENDING",
        "decided_by_user_id": None,
    })
    store.approval_tasks[task["id"]] = task
    return success(out_task(task), 201)


@app.route("/plm/change-orders/<eid>/approval-tasks", methods=["GET"])
def list_eco_tasks(eid):
    authorize(ALL_ROLES)
    get_or_404(store.change_orders, eid)
    rows = [t for t in store.approval_tasks.values() if t["change_order_id"] == eid]
    return list_response(rows, out_task)


@app.route("/plm/approval-tasks/<tid>", methods=["GET"])
def get_task(tid):
    authorize(ALL_ROLES)
    return success(out_task(get_or_404(store.approval_tasks, tid)), 200)


@app.route("/plm/change-orders/<eid>/submit-for-approval", methods=["POST"])
def submit_eco(eid):
    authorize(["ChangeAdmin"])
    eco = get_or_404(store.change_orders, eid)
    if eco["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "ECO is not DRAFT")
    # Three checks in order (PRD 3.5).
    items = [i for i in store.affected_items.values() if i["change_order_id"] == eid]
    if len(items) < 1:
        raise err("ERR_NO_AFFECTED_ITEMS", "ECO has no affected items")
    tasks = [t for t in store.approval_tasks.values() if t["change_order_id"] == eid]
    if len(tasks) < eco["required_approvals"]:
        raise err("ERR_INSUFFICIENT_APPROVERS", "ECO has fewer approval tasks than required_approvals")
    ecr = store.change_requests.get(eco["change_request_id"])
    if ecr is None or ecr["status"] != "APPROVED":
        raise err("ERR_ECR_NOT_APPROVED", "ECO's change request is not APPROVED")
    eco["status"] = "IN_APPROVAL"
    touch(eco)
    return success(out_eco(eco), 200)


@app.route("/plm/change-orders/<eid>/recall", methods=["POST"])
def recall_eco(eid):
    authorize(["ChangeAdmin"])
    eco = get_or_404(store.change_orders, eid)
    if eco["status"] != "IN_APPROVAL":
        raise err("ERR_INVALID_STATE", "ECO is not IN_APPROVAL")
    # Reset every approval task and the tally.
    for task in store.approval_tasks.values():
        if task["change_order_id"] == eid:
            task["decision"] = "PENDING"
            task["decided_by_user_id"] = None
            touch(task)
    eco["approval_count"] = 0
    eco["status"] = "DRAFT"
    touch(eco)
    return success(out_eco(eco), 200)


@app.route("/plm/approval-tasks/<tid>/approve", methods=["POST"])
def approve_task(tid):
    user_id, _ = authorize(["Approver"])
    task = get_or_404(store.approval_tasks, tid)
    eco = store.change_orders[task["change_order_id"]]
    # Preconditions in order (PRD 3.6): state, then assignee, then SoD.
    if eco["status"] != "IN_APPROVAL":
        raise err("ERR_INVALID_STATE", "Parent ECO is not IN_APPROVAL")
    if task["decision"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Task is not PENDING")
    if user_id != task["assignee_user_id"]:
        raise err("ERR_NOT_TASK_ASSIGNEE", "Acting user is not the task assignee")
    if user_id == eco["created_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "ECO creator may not approve its tasks")

    task["decision"] = "APPROVED"
    task["decided_by_user_id"] = user_id
    touch(task)
    eco["approval_count"] = eco["approval_count"] + 1
    touch(eco)
    # Quorum: inclusive >=.
    if eco["approval_count"] >= eco["required_approvals"]:
        services.cascade_eco_to_approved(eco)
    return success(out_task(task), 200)


@app.route("/plm/approval-tasks/<tid>/reject", methods=["POST"])
def reject_task(tid):
    user_id, _ = authorize(["Approver"])
    task = get_or_404(store.approval_tasks, tid)
    eco = store.change_orders[task["change_order_id"]]
    if eco["status"] != "IN_APPROVAL":
        raise err("ERR_INVALID_STATE", "Parent ECO is not IN_APPROVAL")
    if task["decision"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Task is not PENDING")
    if user_id != task["assignee_user_id"]:
        raise err("ERR_NOT_TASK_ASSIGNEE", "Acting user is not the task assignee")
    if user_id == eco["created_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "ECO creator may not reject its tasks")

    task["decision"] = "REJECTED"
    task["decided_by_user_id"] = user_id
    touch(task)
    services.cascade_eco_to_rejected(eco)
    return success(out_task(task), 200)


@app.route("/plm/change-orders/<eid>/make-effective", methods=["POST"])
def make_effective(eid):
    authorize(["ChangeAdmin"])
    eco = get_or_404(store.change_orders, eid)
    # make-effective on an ECO whose status is not APPROVED -> ERR_ECO_NOT_APPROVED
    # (PRD Section 5 / scaffold error catalogue; validation priority 9).
    if eco["status"] != "APPROVED":
        raise err("ERR_ECO_NOT_APPROVED", "ECO is not APPROVED")
    # Clock gate: current clock >= effectivity_date.
    effectivity = services.parse_iso(eco["effectivity_date"])
    if store.clock < effectivity:
        raise err("ERR_NOT_YET_EFFECTIVE", "Current clock has not reached effectivity_date")
    eco["status"] = "EFFECTIVE"
    touch(eco)
    services.release_cascade(eco)
    return success(out_eco(eco), 200)


@app.route("/plm/change-orders/<eid>/cancel", methods=["POST"])
def cancel_eco(eid):
    authorize(["ChangeAdmin"])
    eco = get_or_404(store.change_orders, eid)
    if eco["status"] not in ("DRAFT", "IN_APPROVAL"):
        raise err("ERR_INVALID_STATE", "ECO may only be cancelled from DRAFT or IN_APPROVAL")
    from_in_approval = eco["status"] == "IN_APPROVAL"
    # Detach every affected item.
    for item in store.affected_items.values():
        if item["change_order_id"] != eid:
            continue
        rev = store.part_revisions.get(item["part_revision_id"])
        if rev is not None and rev.get("governing_change_order_id") == eid:
            rev["governing_change_order_id"] = None
            touch(rev)
        if from_in_approval:
            item["pinned"] = False
            touch(item)
    eco["status"] = "CANCELLED"
    touch(eco)
    return success(out_eco(eco), 200)


# =============================================================================
# Document (PRD Section 3.9)
# =============================================================================

@app.route("/plm/documents", methods=["POST"])
def create_document():
    authorize(["Designer"])
    body = get_json(request)
    doc_number = require_str(body, "doc_number").upper()
    title = require_str(body, "title")
    doc_type = require_enum(body, "doc_type", {"CAD", "DRAWING", "SPEC"})
    part_id = optional_str(body, "part_id", None)
    for d in store.documents.values():
        if d["doc_number"] == doc_number:
            raise err("ERR_INVALID_REQUEST", "doc_number must be unique")
    if part_id is not None:
        get_or_404(store.parts, part_id)
    doc = new_entity({
        "doc_number": doc_number,
        "title": title,
        "doc_type": doc_type,
        "part_id": part_id,
        "lifecycle_state": "WORKING",
    })
    store.documents[doc["id"]] = doc
    return success(out_document(doc), 201)


@app.route("/plm/documents/<did>", methods=["GET"])
def get_document(did):
    authorize(ALL_ROLES)
    return success(out_document(get_or_404(store.documents, did)), 200)


@app.route("/plm/documents", methods=["GET"])
def list_documents():
    authorize(ALL_ROLES)
    rows = list(store.documents.values())
    for field in ("part_id", "lifecycle_state"):
        val = request.args.get(field)
        if val is not None:
            rows = [r for r in rows if r.get(field) == val]
    return list_response(rows, out_document)


@app.route("/plm/documents/<did>/submit-review", methods=["POST"])
def submit_review_document(did):
    authorize(["Designer"])
    doc = get_or_404(store.documents, did)
    if doc["lifecycle_state"] != "WORKING":
        raise err("ERR_INVALID_STATE", "Document is not WORKING")
    doc["lifecycle_state"] = "IN_REVIEW"
    touch(doc)
    return success(out_document(doc), 200)


@app.route("/plm/documents/<did>/return-to-work", methods=["POST"])
def return_to_work_document(did):
    authorize(["Designer"])
    doc = get_or_404(store.documents, did)
    if doc["lifecycle_state"] != "IN_REVIEW":
        raise err("ERR_INVALID_STATE", "Document is not IN_REVIEW")
    doc["lifecycle_state"] = "WORKING"
    touch(doc)
    return success(out_document(doc), 200)


@app.route("/plm/documents/<did>/release", methods=["POST"])
def release_document(did):
    authorize(["ChangeAdmin"])
    doc = get_or_404(store.documents, did)
    if doc["lifecycle_state"] != "IN_REVIEW":
        raise err("ERR_INVALID_STATE", "Document is not IN_REVIEW")
    # If attached to a part, that part must have a released revision.
    if doc.get("part_id") is not None:
        part = store.parts.get(doc["part_id"])
        if part is None or part.get("released_revision_id") is None:
            raise err("ERR_PART_NOT_RELEASED", "Attached part has no RELEASED revision")
    doc["lifecycle_state"] = "RELEASED"
    touch(doc)
    return success(out_document(doc), 200)


@app.route("/plm/documents/<did>/obsolete", methods=["POST"])
def obsolete_document(did):
    authorize(["ChangeAdmin"])
    doc = get_or_404(store.documents, did)
    if doc["lifecycle_state"] != "RELEASED":
        raise err("ERR_INVALID_STATE", "Document is not RELEASED")
    doc["lifecycle_state"] = "OBSOLETE"
    touch(doc)
    return success(out_document(doc), 200)


# =============================================================================
# Deviation (PRD Section 3.10)
# =============================================================================

@app.route("/plm/deviations", methods=["POST"])
def create_deviation():
    authorize(["Designer"])
    body = get_json(request)
    part_id = require_str(body, "part_id")
    defect_code = require_enum(
        body, "defect_code", {"DIMENSIONAL", "COSMETIC", "MATERIAL", "FUNCTIONAL"}
    )
    max_units = require_int(body, "max_units", minimum=1)
    effective_from = require_str(body, "effective_from")
    effective_to = require_str(body, "effective_to")
    change_order_id = optional_str(body, "change_order_id", None)

    get_or_404(store.parts, part_id)
    if change_order_id is not None:
        get_or_404(store.change_orders, change_order_id)
    # Validate the window endpoints are parseable ISO instants.
    services.parse_iso(effective_from)
    services.parse_iso(effective_to)

    dev = new_entity({
        "part_id": part_id,
        "change_order_id": change_order_id,
        "defect_code": defect_code,
        "max_units": max_units,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "covered_unit_count": 0,
        "status": "DRAFT",
    })
    store.deviations[dev["id"]] = dev
    return success(out_deviation(dev), 201)


@app.route("/plm/deviations/<did>", methods=["GET"])
def get_deviation(did):
    authorize(ALL_ROLES)
    return success(out_deviation(get_or_404(store.deviations, did)), 200)


@app.route("/plm/deviations", methods=["GET"])
def list_deviations():
    authorize(ALL_ROLES)
    rows = list(store.deviations.values())
    for field in ("part_id", "change_order_id", "status"):
        val = request.args.get(field)
        if val is not None:
            rows = [r for r in rows if r.get(field) == val]
    return list_response(rows, out_deviation)


@app.route("/plm/deviations/<did>/submit", methods=["POST"])
def submit_deviation(did):
    authorize(["Designer"])
    dev = get_or_404(store.deviations, did)
    if dev["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Deviation is not DRAFT")
    # effective_to >= effective_from.
    if services.parse_iso(dev["effective_to"]) < services.parse_iso(dev["effective_from"]):
        raise err("ERR_INVALID_WINDOW", "effective_to must be >= effective_from")
    dev["status"] = "SUBMITTED"
    touch(dev)
    return success(out_deviation(dev), 200)


@app.route("/plm/deviations/<did>/grant", methods=["POST"])
def grant_deviation(did):
    authorize(["QualityEngineer"])
    dev = get_or_404(store.deviations, did)
    if dev["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Deviation is not SUBMITTED")
    # No overlapping GRANTED deviation for same part_id + defect_code (inclusive).
    this_from = services.parse_iso(dev["effective_from"])
    this_to = services.parse_iso(dev["effective_to"])
    for other in store.deviations.values():
        if other["id"] == dev["id"]:
            continue
        if other["status"] != "GRANTED":
            continue
        if other["part_id"] != dev["part_id"] or other["defect_code"] != dev["defect_code"]:
            continue
        o_from = services.parse_iso(other["effective_from"])
        o_to = services.parse_iso(other["effective_to"])
        if services.windows_overlap_inclusive(this_from, this_to, o_from, o_to):
            raise err("ERR_DEVIATION_WINDOW_OVERLAP", "Window overlaps another granted deviation")
    dev["status"] = "GRANTED"
    services.grant_deviation_coverage(dev)
    touch(dev)
    return success(out_deviation(dev), 200)


@app.route("/plm/deviations/<did>/deny", methods=["POST"])
def deny_deviation(did):
    authorize(["QualityEngineer"])
    dev = get_or_404(store.deviations, did)
    if dev["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Deviation is not SUBMITTED")
    dev["status"] = "DENIED"
    touch(dev)
    return success(out_deviation(dev), 200)


@app.route("/plm/deviations/<did>/expire", methods=["POST"])
def expire_deviation(did):
    authorize(["QualityEngineer"])
    dev = get_or_404(store.deviations, did)
    if dev["status"] != "GRANTED":
        raise err("ERR_INVALID_STATE", "Deviation is not GRANTED")
    # Clock must have passed strictly beyond effective_to.
    if store.clock <= services.parse_iso(dev["effective_to"]):
        raise err("ERR_NOT_YET_EXPIRED", "Current clock has not passed effective_to")
    dev["status"] = "EXPIRED"
    services.expire_deviation_coverage(dev)
    touch(dev)
    return success(out_deviation(dev), 200)


# =============================================================================
# SupplierChangeNotice (PRD Section 3.8)
# =============================================================================

@app.route("/plm/supplier-change-notices", methods=["POST"])
def create_pcn():
    authorize(["SupplierManager"])
    body = get_json(request)
    supplier_id = require_str(body, "supplier_id")
    affected_part_id = require_str(body, "affected_part_id")
    pcn_reference = require_str(body, "pcn_reference")
    get_or_404(store.suppliers, supplier_id)
    get_or_404(store.parts, affected_part_id)
    pcn = new_entity({
        "supplier_id": supplier_id,
        "affected_part_id": affected_part_id,
        "pcn_reference": pcn_reference,
        "spawned_ecr_id": None,
        "status": "RECEIVED",
    })
    store.supplier_change_notices[pcn["id"]] = pcn
    return success(out_pcn(pcn), 201)


@app.route("/plm/supplier-change-notices/<nid>", methods=["GET"])
def get_pcn(nid):
    authorize(ALL_ROLES)
    return success(out_pcn(get_or_404(store.supplier_change_notices, nid)), 200)


@app.route("/plm/supplier-change-notices", methods=["GET"])
def list_pcns():
    authorize(ALL_ROLES)
    rows = list(store.supplier_change_notices.values())
    for field in ("supplier_id", "affected_part_id", "spawned_ecr_id", "status"):
        val = request.args.get(field)
        if val is not None:
            rows = [r for r in rows if r.get(field) == val]
    return list_response(rows, out_pcn)


@app.route("/plm/supplier-change-notices/<nid>/assess", methods=["POST"])
def assess_pcn(nid):
    authorize(["SupplierManager"])
    pcn = get_or_404(store.supplier_change_notices, nid)
    if pcn["status"] != "RECEIVED":
        raise err("ERR_INVALID_STATE", "PCN is not RECEIVED")
    pcn["status"] = "UNDER_ASSESSMENT"
    touch(pcn)
    return success(out_pcn(pcn), 200)


@app.route("/plm/supplier-change-notices/<nid>/accept", methods=["POST"])
def accept_pcn(nid):
    authorize(["SupplierManager"])
    pcn = get_or_404(store.supplier_change_notices, nid)
    if pcn["status"] != "UNDER_ASSESSMENT":
        raise err("ERR_INVALID_STATE", "PCN is not UNDER_ASSESSMENT")
    part = store.parts.get(pcn["affected_part_id"])
    if part is None or part["part_type"] != "BUY":
        raise err("ERR_PART_NOT_BUY", "PCN accept requires a BUY part")
    pcn["status"] = "ACCEPTED"
    # Cascade: create a DRAFT ECR (reason SUPPLIER_CHANGE, source_pcn_id=this).
    ecr = new_entity({
        "title": "Supplier change for %s" % part["part_number"],
        "affected_part_id": pcn["affected_part_id"],
        "reason_code": "SUPPLIER_CHANGE",
        "source_pcn_id": pcn["id"],
        "submitted_by_user_id": None,
        "status": "DRAFT",
    })
    store.change_requests[ecr["id"]] = ecr
    pcn["spawned_ecr_id"] = ecr["id"]
    touch(pcn)
    return success(out_pcn(pcn), 200)


@app.route("/plm/supplier-change-notices/<nid>/reject", methods=["POST"])
def reject_pcn(nid):
    authorize(["SupplierManager"])
    pcn = get_or_404(store.supplier_change_notices, nid)
    if pcn["status"] != "UNDER_ASSESSMENT":
        raise err("ERR_INVALID_STATE", "PCN is not UNDER_ASSESSMENT")
    pcn["status"] = "REJECTED"
    touch(pcn)
    return success(out_pcn(pcn), 200)


# =============================================================================
# SerializedUnit (PRD Section 3.11)
# =============================================================================

@app.route("/plm/serialized-units", methods=["POST"])
def create_unit():
    authorize(["QualityEngineer"])
    body = get_json(request)
    serial_number = require_str(body, "serial_number").upper()
    part_revision_id = require_str(body, "part_revision_id")
    for u in store.serialized_units.values():
        if u["serial_number"] == serial_number:
            raise err("ERR_INVALID_REQUEST", "serial_number must be unique")
    get_or_404(store.part_revisions, part_revision_id)
    unit = new_entity({
        "serial_number": serial_number,
        "part_revision_id": part_revision_id,
        "deviation_id": None,
        "build_status": "PLANNED",
        "conformance_status": "CONFORMING",
    })
    store.serialized_units[unit["id"]] = unit
    return success(out_unit(unit), 201)


@app.route("/plm/serialized-units/<uid>", methods=["GET"])
def get_unit(uid):
    authorize(ALL_ROLES)
    return success(out_unit(get_or_404(store.serialized_units, uid)), 200)


@app.route("/plm/serialized-units", methods=["GET"])
def list_units():
    authorize(ALL_ROLES)
    rows = list(store.serialized_units.values())
    for field in ("part_revision_id", "deviation_id", "build_status", "conformance_status"):
        val = request.args.get(field)
        if val is not None:
            rows = [r for r in rows if r.get(field) == val]
    return list_response(rows, out_unit)


@app.route("/plm/serialized-units/<uid>/build", methods=["POST"])
def build_unit(uid):
    authorize(["QualityEngineer"])
    unit = get_or_404(store.serialized_units, uid)
    if unit["build_status"] != "PLANNED":
        raise err("ERR_INVALID_STATE", "Unit is not PLANNED")
    rev = store.part_revisions.get(unit["part_revision_id"])
    if rev is None or rev["lifecycle_state"] != "RELEASED":
        raise err("ERR_REVISION_NOT_RELEASED", "Pinned revision is not RELEASED")
    unit["build_status"] = "BUILT"
    touch(unit)
    return success(out_unit(unit), 200)


@app.route("/plm/serialized-units/<uid>/ship", methods=["POST"])
def ship_unit(uid):
    authorize(["QualityEngineer"])
    unit = get_or_404(store.serialized_units, uid)
    if unit["build_status"] != "BUILT":
        raise err("ERR_INVALID_STATE", "Unit is not BUILT")
    if unit["conformance_status"] not in ("CONFORMING", "WAIVED"):
        raise err("ERR_UNIT_NONCONFORMING", "Unit conformance must be CONFORMING or WAIVED to ship")
    unit["build_status"] = "SHIPPED"
    touch(unit)
    return success(out_unit(unit), 200)


@app.route("/plm/serialized-units/<uid>/flag-nonconforming", methods=["POST"])
def flag_unit(uid):
    authorize(["QualityEngineer"])
    unit = get_or_404(store.serialized_units, uid)
    if unit["conformance_status"] != "CONFORMING":
        raise err("ERR_INVALID_STATE", "Unit is not CONFORMING")
    unit["conformance_status"] = "NONCONFORMING"
    touch(unit)
    return success(out_unit(unit), 200)


# =============================================================================
# Entry point
# =============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
