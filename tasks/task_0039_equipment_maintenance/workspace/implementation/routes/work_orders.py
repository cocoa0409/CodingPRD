"""WorkOrder routes."""
import math

from flask import Blueprint, request

from db import db
from errors import (
    ERR_BAD_REQUEST,
    ERR_CROSS_SITE_REFERENCE,
    ERR_EQUIPMENT_LIFECYCLE,
    ERR_EVIDENCE_MISSING,
    ERR_FORBIDDEN_NOT_OWNER,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_PARTS_NOT_ISSUED,
    ERR_PAUSE_TOO_FRESH,
    ERR_REQUISITIONS_PENDING,
    ERR_SKILL_MISMATCH,
    raise_err,
)
from middleware import require_auth, require_role
from response import success_array, success_object
from services.audit import append_audit
from services.calculations import (
    bucket_for_score,
    compute_parts_cost,
    compute_priority_score,
    parts_replaced_snapshot,
    recompute_sla_breached,
    refresh_technician_open_loads,
    replenish_eval,
    sla_due_at,
)
from services.common import (
    get_equipment_or_404,
    get_json_body,
    get_site_or_404,
    get_template_or_404,
    get_work_order_or_404,
    paginate,
    parse_pagination,
)
from services.serialize import serialize_work_order
from services.work_order import create_work_order
from db import new_id

bp = Blueprint("work_orders", __name__)

VALID_PRIORITIES = {"P1", "P2", "P3", "P4"}
VALID_PAUSE_REASONS = {"WAIT_PARTS", "WAIT_VENDOR", "WAIT_INFO"}


@bp.route("/sites/<site_id>/work-orders", methods=["POST"])
def create_ad_hoc_wo(site_id):
    require_role(["Dispatcher", "SiteManager"])
    get_site_or_404(site_id)
    body = get_json_body()

    for f in ["equipment_id", "template_id"]:
        if f not in body or body.get(f) in (None, ""):
            raise_err(ERR_BAD_REQUEST, f"{f} is required")

    # Cross-site validation per priority 4
    eq = db.equipment.get(body["equipment_id"])
    if eq is None:
        raise_err(ERR_NOT_FOUND, "equipment_id not found")
    if eq["site_id"] != site_id:
        raise_err(ERR_CROSS_SITE_REFERENCE, "equipment belongs to a different site")
    tpl = db.templates.get(body["template_id"])
    if tpl is None:
        raise_err(ERR_NOT_FOUND, "template_id not found")
    if tpl["site_id"] != site_id:
        raise_err(ERR_CROSS_SITE_REFERENCE, "template belongs to a different site")

    explicit_priority = body.get("explicit_priority")
    if explicit_priority is not None and explicit_priority not in VALID_PRIORITIES:
        raise_err(ERR_BAD_REQUEST, "invalid explicit_priority")

    preferred_technician_id = body.get("preferred_technician_id")
    if preferred_technician_id is not None:
        ptech = db.technicians.get(preferred_technician_id)
        if ptech is None:
            raise_err(ERR_NOT_FOUND, "preferred_technician_id not found")
        if ptech["site_id"] != site_id:
            raise_err(ERR_CROSS_SITE_REFERENCE, "preferred_technician belongs to a different site")

    wo = create_work_order(
        site_id=site_id,
        equipment_id=body["equipment_id"],
        template_id=body["template_id"],
        source="AD_HOC",
        plan_id=None,
        explicit_priority=explicit_priority,
        preferred_technician_id=preferred_technician_id,
    )
    return success_object(serialize_work_order(wo), 201)


@bp.route("/sites/<site_id>/work-orders/<wo_id>", methods=["GET"])
def get_wo(site_id, wo_id):
    require_role(["Any"])
    get_site_or_404(site_id)
    w = get_work_order_or_404(site_id, wo_id)
    return success_object(serialize_work_order(w))


@bp.route("/sites/<site_id>/work-orders", methods=["GET"])
def list_wo(site_id):
    require_role(["Any"])
    get_site_or_404(site_id)
    limit, offset = parse_pagination()

    items = list(db.work_orders_for_site(site_id))

    status = request.args.get("status")
    equipment_id = request.args.get("equipment_id")
    assigned_technician_id = request.args.get("assigned_technician_id")
    priority = request.args.get("priority")

    if status:
        items = [w for w in items if w["status"] == status]
    if equipment_id:
        items = [w for w in items if w["equipment_id"] == equipment_id]
    if assigned_technician_id:
        items = [w for w in items if w.get("assigned_technician_id") == assigned_technician_id]
    if priority:
        items = [w for w in items if w["priority"] == priority]

    items.sort(key=lambda w: (w["created_at"], w["id"]))
    page, total = paginate(items, limit, offset)
    return success_array([serialize_work_order(w) for w in page], limit, offset, total)


@bp.route("/sites/<site_id>/work-orders/<wo_id>/reassign", methods=["POST"])
def reassign(site_id, wo_id):
    require_role(["Dispatcher"])
    get_site_or_404(site_id)
    w = get_work_order_or_404(site_id, wo_id)
    if w["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "WorkOrder must be PENDING to reassign")

    body = get_json_body()
    new_tid = body.get("new_technician_id")
    if not isinstance(new_tid, str) or not new_tid:
        raise_err(ERR_BAD_REQUEST, "new_technician_id is required")
    nt = db.technicians.get(new_tid)
    if nt is None:
        raise_err(ERR_NOT_FOUND, "Technician not found")
    if nt["site_id"] != site_id:
        raise_err(ERR_CROSS_SITE_REFERENCE, "Technician belongs to a different site")
    if nt["status"] != "ACTIVE":
        raise_err(ERR_SKILL_MISMATCH, "Technician is not ACTIVE")
    if w["required_skill"] not in nt["skills"]:
        raise_err(ERR_SKILL_MISMATCH, "Technician lacks required skill")

    prev = w.get("assigned_technician_id")
    w["assigned_technician_id"] = new_tid
    if prev is not None and prev != new_tid:
        w["reassign_count"] += 1
    w["updated_at"] = db.site_clock(site_id)
    w["version"] += 1

    append_audit(site_id, "TECHNICIAN_ASSIGNED", w["id"], prev or "", new_tid)
    refresh_technician_open_loads(site_id)
    return success_object(serialize_work_order(w))


@bp.route("/sites/<site_id>/work-orders/<wo_id>/start", methods=["POST"])
def start(site_id, wo_id):
    role, user_id = require_role(["Technician"])
    get_site_or_404(site_id)
    w = get_work_order_or_404(site_id, wo_id)
    if w["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "WorkOrder must be PENDING to start")

    eq = db.equipment.get(w["equipment_id"])
    if eq is None or eq["lifecycle_status"] not in {"IN_SERVICE", "COMMISSIONED"}:
        raise_err(ERR_EQUIPMENT_LIFECYCLE, "Equipment lifecycle does not permit start")

    # Ownership check
    if w.get("assigned_technician_id") != user_id:
        raise_err(ERR_FORBIDDEN_NOT_OWNER, "Caller is not the assigned technician")
    tech = db.technicians.get(user_id)
    if tech is None or tech["site_id"] != site_id:
        raise_err(ERR_FORBIDDEN_NOT_OWNER, "Technician record not found at this site")
    if tech["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Technician is not ACTIVE")

    clock = db.site_clock(site_id)
    old_status = w["status"]
    w["status"] = "IN_PROGRESS"
    if w["started_at"] is None:
        w["started_at"] = clock
    w["_in_progress_started_at"] = clock
    w["updated_at"] = clock
    w["version"] += 1

    eq["lifecycle_status"] = "UNDER_MAINTENANCE"
    eq["open_work_order_id"] = w["id"]
    eq["updated_at"] = clock
    eq["version"] += 1

    append_audit(site_id, "WORK_ORDER_STATE_CHANGE", w["id"], old_status, w["status"])
    return success_object(serialize_work_order(w))


@bp.route("/sites/<site_id>/work-orders/<wo_id>/pause", methods=["POST"])
def pause(site_id, wo_id):
    role, user_id = require_role(["Technician"])
    get_site_or_404(site_id)
    w = get_work_order_or_404(site_id, wo_id)
    if w["status"] != "IN_PROGRESS":
        raise_err(ERR_INVALID_STATE, "WorkOrder must be IN_PROGRESS to pause")

    if w.get("assigned_technician_id") != user_id:
        raise_err(ERR_FORBIDDEN_NOT_OWNER, "Caller is not the assigned technician")

    body = get_json_body()
    pause_reason = body.get("pause_reason")
    if pause_reason not in VALID_PAUSE_REASONS:
        raise_err(ERR_BAD_REQUEST, "invalid pause_reason")

    clock = db.site_clock(site_id)
    if w.get("_in_progress_started_at") is not None:
        delta = (clock - w["_in_progress_started_at"]).total_seconds()
        w["total_active_minutes"] += int(delta // 60)

    w["_pause_started_sweep"] = db.sites[site_id]["sweep_run_index"]
    w["status"] = "PAUSED"
    w["pause_reason"] = pause_reason
    w["updated_at"] = clock
    w["version"] += 1
    w["_in_progress_started_at"] = None

    append_audit(site_id, "WORK_ORDER_STATE_CHANGE", w["id"], "IN_PROGRESS", "PAUSED")
    return success_object(serialize_work_order(w))


@bp.route("/sites/<site_id>/work-orders/<wo_id>/resume", methods=["POST"])
def resume(site_id, wo_id):
    role, user_id = require_role(["Technician"])
    get_site_or_404(site_id)
    w = get_work_order_or_404(site_id, wo_id)
    if w["status"] != "PAUSED":
        raise_err(ERR_INVALID_STATE, "WorkOrder must be PAUSED to resume")

    if w.get("assigned_technician_id") != user_id:
        raise_err(ERR_FORBIDDEN_NOT_OWNER, "Caller is not the assigned technician")

    if w.get("pause_reason") == "WAIT_PARTS":
        has_issued = any(
            r for r in db.requisitions_for_work_order(w["id"]) if r["status"] == "ISSUED"
        )
        if not has_issued:
            raise_err(ERR_PARTS_NOT_ISSUED, "Resume from WAIT_PARTS requires at least one ISSUED requisition")

    clock = db.site_clock(site_id)
    w["status"] = "IN_PROGRESS"
    w["pause_reason"] = None
    w["_in_progress_started_at"] = clock
    w["updated_at"] = clock
    w["version"] += 1

    append_audit(site_id, "WORK_ORDER_STATE_CHANGE", w["id"], "PAUSED", "IN_PROGRESS")
    return success_object(serialize_work_order(w))


@bp.route("/sites/<site_id>/work-orders/<wo_id>/complete", methods=["POST"])
def complete(site_id, wo_id):
    role, user_id = require_role(["Technician"])
    get_site_or_404(site_id)
    w = get_work_order_or_404(site_id, wo_id)
    if w["status"] != "IN_PROGRESS":
        raise_err(ERR_INVALID_STATE, "WorkOrder must be IN_PROGRESS to complete")

    if w.get("assigned_technician_id") != user_id:
        raise_err(ERR_FORBIDDEN_NOT_OWNER, "Caller is not the assigned technician")

    body = get_json_body()
    # PRD §3.6: completion body "must include" these fields, but PRD only
    # asserts the non-empty check on before/after evidence URLs at the
    # acceptance step (ERR_EVIDENCE_MISSING). Empty strings are therefore
    # allowed at completion; presence (key in body) is what matters here.
    for f in ["fault_description", "root_cause", "repair_actions",
              "working_minutes", "before_evidence_url", "after_evidence_url"]:
        if f not in body or body.get(f) is None:
            raise_err(ERR_BAD_REQUEST, f"{f} is required")
    wm = body["working_minutes"]
    if not isinstance(wm, int) or isinstance(wm, bool) or wm <= 0:
        raise_err(ERR_BAD_REQUEST, "working_minutes must be positive integer")

    # Check no still-RESERVED requisitions
    for r in db.requisitions_for_work_order(w["id"]):
        if r["status"] == "RESERVED":
            raise_err(ERR_REQUISITIONS_PENDING, "WorkOrder has RESERVED requisitions")

    clock = db.site_clock(site_id)
    if w.get("_in_progress_started_at") is not None:
        delta = (clock - w["_in_progress_started_at"]).total_seconds()
        w["total_active_minutes"] += int(delta // 60)
        w["_in_progress_started_at"] = None

    # Build RepairRecord
    rr_id = new_id()
    rr = {
        "id": rr_id,
        "created_at": clock,
        "work_order_id": w["id"],
        "fault_description": body["fault_description"],
        "root_cause": body["root_cause"],
        "repair_actions": body["repair_actions"],
        "working_minutes": wm,
        "before_evidence_url": body["before_evidence_url"],
        "after_evidence_url": body["after_evidence_url"],
        "parts_replaced": parts_replaced_snapshot(w["id"]),
        "acceptance_user_id": None,
        "acceptance_at": None,
    }
    db.repair_records[rr_id] = rr

    w["parts_cost_cents"] = compute_parts_cost(w["id"])
    w["completed_at"] = clock
    w["status"] = "COMPLETED"
    w["updated_at"] = clock
    w["version"] += 1

    eq = db.equipment.get(w["equipment_id"])
    if eq is not None:
        eq["lifecycle_status"] = "IN_SERVICE"
        eq["open_work_order_id"] = None
        eq["last_repair_completed_at"] = clock
        eq["updated_at"] = clock
        eq["version"] += 1

    append_audit(site_id, "WORK_ORDER_STATE_CHANGE", w["id"], "IN_PROGRESS", "COMPLETED")
    refresh_technician_open_loads(site_id)
    return success_object(serialize_work_order(w))


@bp.route("/sites/<site_id>/work-orders/<wo_id>/accept", methods=["POST"])
def accept(site_id, wo_id):
    role, user_id = require_role(["SiteManager"])
    get_site_or_404(site_id)
    w = get_work_order_or_404(site_id, wo_id)
    if w["status"] != "COMPLETED":
        raise_err(ERR_INVALID_STATE, "WorkOrder must be COMPLETED to accept")

    eq = db.equipment.get(w["equipment_id"])
    if eq is None:
        raise_err(ERR_NOT_FOUND, "Equipment not found")

    # Find repair record
    rr = next((r for r in db.repair_records.values() if r["work_order_id"] == w["id"]), None)

    # Priority order: ERR_EVIDENCE_MISSING (priority 8) before ERR_FORBIDDEN_NOT_OWNER (priority 10)
    if rr is None or not rr.get("before_evidence_url") or not rr.get("after_evidence_url"):
        raise_err(ERR_EVIDENCE_MISSING, "Acceptance requires before/after evidence URLs")

    if user_id != eq.get("responsible_user_id"):
        raise_err(ERR_FORBIDDEN_NOT_OWNER, "Acceptance requires the equipment's responsible user")

    clock = db.site_clock(site_id)
    rr["acceptance_user_id"] = user_id
    rr["acceptance_at"] = clock
    w["status"] = "CLOSED"
    w["closed_at"] = clock
    w["updated_at"] = clock
    w["version"] += 1

    append_audit(site_id, "WORK_ORDER_STATE_CHANGE", w["id"], "COMPLETED", "CLOSED")
    return success_object(serialize_work_order(w))


@bp.route("/sites/<site_id>/work-orders/<wo_id>/cancel", methods=["POST"])
def cancel(site_id, wo_id):
    require_role(["Dispatcher"])
    get_site_or_404(site_id)
    w = get_work_order_or_404(site_id, wo_id)
    body = get_json_body()
    cancel_reason = body.get("cancel_reason")

    if w["status"] not in {"PENDING", "PAUSED"}:
        raise_err(ERR_INVALID_STATE, "WorkOrder must be PENDING or PAUSED to cancel")

    # Common: no ISSUED requisitions
    has_issued = any(
        r for r in db.requisitions_for_work_order(w["id"]) if r["status"] == "ISSUED"
    )
    if has_issued:
        raise_err(ERR_INVALID_STATE, "Cannot cancel: WorkOrder has ISSUED requisitions")

    if w["status"] == "PAUSED":
        # PAUSED: pause_too_fresh check
        pause_sweep = w.get("_pause_started_sweep", db.sites[site_id]["sweep_run_index"])
        if db.sites[site_id]["sweep_run_index"] <= pause_sweep:
            raise_err(ERR_PAUSE_TOO_FRESH, "Cancel of PAUSED requires sweep tick since pause")

    clock = db.site_clock(site_id)
    old_status = w["status"]

    # Cancel RESERVED requisitions
    for r in db.requisitions_for_work_order(w["id"]):
        if r["status"] == "RESERVED":
            r["status"] = "CANCELLED"
            r["updated_at"] = clock
            r["version"] += 1
            sp = db.spare_parts.get(r["part_id"])
            if sp is not None:
                sp["stock_reserved"] = max(0, sp["stock_reserved"] - r["qty"])
                replenish_eval(sp)

    if old_status == "PAUSED":
        eq = db.equipment.get(w["equipment_id"])
        if eq is not None and eq["lifecycle_status"] == "UNDER_MAINTENANCE":
            eq["lifecycle_status"] = "IN_SERVICE"
            eq["open_work_order_id"] = None
            eq["updated_at"] = clock
            eq["version"] += 1
    else:
        # PENDING was never started; just clear open_work_order_id reference
        eq = db.equipment.get(w["equipment_id"])
        if eq is not None and eq.get("open_work_order_id") == w["id"]:
            eq["open_work_order_id"] = None
            eq["updated_at"] = clock
            eq["version"] += 1

    w["status"] = "CANCELLED"
    if cancel_reason:
        w["cancel_reason"] = cancel_reason
    w["updated_at"] = clock
    w["version"] += 1

    append_audit(site_id, "WORK_ORDER_STATE_CHANGE", w["id"], old_status, "CANCELLED")
    refresh_technician_open_loads(site_id)
    return success_object(serialize_work_order(w))


@bp.route("/sites/<site_id>/work-orders/<wo_id>/repair-record", methods=["GET"])
def get_repair_record(site_id, wo_id):
    require_role(["Any"])
    get_site_or_404(site_id)
    w = get_work_order_or_404(site_id, wo_id)
    rr = next((r for r in db.repair_records.values() if r["work_order_id"] == w["id"]), None)
    if rr is None:
        raise_err(ERR_NOT_FOUND, "RepairRecord not found")
    from services.serialize import serialize_repair_record
    return success_object(serialize_repair_record(rr))
