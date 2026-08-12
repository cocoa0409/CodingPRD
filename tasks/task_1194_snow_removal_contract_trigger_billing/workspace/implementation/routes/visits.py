"""ServiceVisit endpoints — schedule, start, complete, cancel, void, reassign."""
from flask import Blueprint, request
from datetime import timedelta
import db
from middleware import require_roles, get_pagination, get_json_body
from response import success_object, success_created, success_list
from errors import *
from services.helpers import (
    recompute_contract_accumulators, _touch, evaluate_visit_billing,
    recompute_draft_invoices, recompute_visit_material_cost,
    compute_billable_minutes, is_night_hour, compute_hourly_charge,
    check_coverage_overlap,
)

bp = Blueprint("visits", __name__)

ALLOWED_CREATE_FIELDS = {"storm_event_id", "contract_site_id", "scheduled_start", "scheduled_end", "assigned_subcontractor_id"}


@bp.route("/visits", methods=["POST"])
def create_visit():
    user_id, role = require_roles("OpsDispatcher")
    body = get_json_body()
    unknown = set(body.keys()) - ALLOWED_CREATE_FIELDS
    if unknown:
        raise ApiError(ERR_INVALID_REQUEST, f"Unknown fields: {', '.join(unknown)}", 400)

    storm_event_id = body.get("storm_event_id")
    contract_site_id = body.get("contract_site_id")
    scheduled_start = body.get("scheduled_start")
    scheduled_end = body.get("scheduled_end")
    assigned_sub = body.get("assigned_subcontractor_id")

    if not storm_event_id:
        raise ApiError(ERR_INVALID_REQUEST, "storm_event_id is required", 400)
    if not contract_site_id:
        raise ApiError(ERR_INVALID_REQUEST, "contract_site_id is required", 400)
    if not scheduled_start or not scheduled_end:
        raise ApiError(ERR_INVALID_REQUEST, "scheduled_start and scheduled_end are required", 400)

    # Resolve IDs left-to-right
    event = db.storm_events.get(storm_event_id)
    if not event:
        raise ApiError(ERR_NOT_FOUND, f"StormEvent {storm_event_id} not found", 404)
    cs = db.contract_sites.get(contract_site_id)
    if not cs:
        raise ApiError(ERR_NOT_FOUND, f"ContractSite {contract_site_id} not found", 404)

    ss = db._parse_iso(scheduled_start)
    se = db._parse_iso(scheduled_end)
    if not ss or not se:
        raise ApiError(ERR_INVALID_REQUEST, "Invalid scheduled dates", 400)
    if se <= ss:
        raise ApiError(ERR_INVALID_REQUEST, "scheduled_end must be > scheduled_start", 400)

    # Contract must be ACTIVE
    contract = db.contracts.get(cs.get("contract_id"))
    if not contract:
        raise ApiError(ERR_NOT_FOUND, "Contract not found", 404)
    if contract.get("status") != "ACTIVE":
        raise ApiError(ERR_CONTRACT_NOT_ACTIVE, f"Contract is {contract.get('status')}", 409)

    # Storm event must be REPORTED/VERIFIED/CHALLENGED
    if event.get("status") not in ("REPORTED", "VERIFIED", "CHALLENGED"):
        raise ApiError(ERR_INVALID_STATE, f"Event status {event.get('status')} does not allow visit creation", 409)

    # If subcontractor assigned, must hold ACTIVE coverage
    if assigned_sub:
        sub = db.subcontractors.get(assigned_sub)
        if not sub:
            raise ApiError(ERR_NOT_FOUND, f"Subcontractor {assigned_sub} not found", 404)
        has_coverage = False
        for ca in db.coverage_assignments.list_all():
            if (ca.get("subcontractor_id") == assigned_sub
                and ca.get("storm_event_id") == storm_event_id
                and ca.get("contract_id") == cs.get("contract_id")
                and ca.get("status") == "ACTIVE"):
                has_coverage = True
                break
        if not has_coverage:
            raise ApiError(ERR_INVALID_STATE, "Subcontractor does not hold ACTIVE coverage for this event+contract", 409)

    # Same-site buffer check
    site_id = cs.get("site_id")
    REAPPLY_GAP = timedelta(minutes=90)
    for v in db.visits.list_all():
        if v.get("site_id") != site_id:
            continue
        if v.get("execution_status") == "CANCELLED":
            continue
        ex_start = db._parse_iso(v.get("scheduled_start"))
        ex_end = db._parse_iso(v.get("scheduled_end"))
        if not ex_start or not ex_end:
            continue
        # Conflict unless: new.start >= ex.end + 90min OR new.end + 90min <= ex.start
        if ss >= ex_end + REAPPLY_GAP or se + REAPPLY_GAP <= ex_start:
            continue
        raise ApiError(ERR_VISIT_GAP_CONFLICT, "Same-site visit violates 90-minute buffer", 409)

    # Compute SLA deadline
    window_end = db._parse_iso(event.get("window_end"))
    completion_target = cs.get("completion_target_minutes") or 0
    sla_deadline = window_end + timedelta(minutes=completion_target) if window_end else None

    visit = {
        "id": db._new_id(),
        "storm_event_id": storm_event_id,
        "contract_site_id": contract_site_id,
        "contract_id": cs.get("contract_id"),
        "site_id": site_id,
        "assigned_subcontractor_id": assigned_sub,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "actual_start_at": None,
        "completed_at": None,
        "execution_status": "SCHEDULED",
        "billing_status": "PENDING",
        "sla_deadline_at": db._to_iso(sla_deadline) if sla_deadline else None,
        "grace_extended": False,
        "sla_miss": None,
        "billable_minutes": None,
        "night_premium_applied": None,
        "billable_amount_cents": None,
        "material_cost_cents": 0,
        "applied_trigger_depth_inches": None,
        "applied_per_push_rate_cents": None,
        "completed_by_user_id": None,
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
    }
    db.visits.create(visit)
    return success_created(visit)


def _get_visit_or_404(id):
    v = db.visits.get(id)
    if not v:
        raise ApiError(ERR_NOT_FOUND, f"Visit {id} not found", 404)
    return v


@bp.route("/visits/<id>", methods=["GET"])
def get_visit(id):
    user_id, role = require_roles("PlatformAdmin", "OpsDispatcher", "ClientContact", "ClaimsAdjuster", "Subcontractor", "CrewLead")
    visit = _get_visit_or_404(id)
    # Ownership checks
    if role == "ClientContact":
        contract = db.contracts.get(visit.get("contract_id"))
        if contract and contract.get("client_id") != user_id:
            raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Not your visit", 403)
    elif role == "Subcontractor":
        if visit.get("assigned_subcontractor_id") != user_id:
            raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Not your assigned visit", 403)
    return success_object(visit)


@bp.route("/visits", methods=["GET"])
def list_visits():
    user_id, role = require_roles("PlatformAdmin", "OpsDispatcher", "ClientContact", "ClaimsAdjuster", "Subcontractor")
    limit, offset = get_pagination()
    all_visits = db.visits.list_all()

    # Filters
    storm_event_id = request.args.get("storm_event_id")
    contract_site_id = request.args.get("contract_site_id")
    contract_id = request.args.get("contract_id")
    site_id = request.args.get("site_id")
    assigned_sub = request.args.get("assigned_subcontractor_id")
    billing_status = request.args.get("billing_status")
    execution_status = request.args.get("execution_status")

    if storm_event_id:
        all_visits = [v for v in all_visits if v.get("storm_event_id") == storm_event_id]
    if contract_site_id:
        all_visits = [v for v in all_visits if v.get("contract_site_id") == contract_site_id]
    if contract_id:
        all_visits = [v for v in all_visits if v.get("contract_id") == contract_id]
    if site_id:
        all_visits = [v for v in all_visits if v.get("site_id") == site_id]
    if assigned_sub:
        all_visits = [v for v in all_visits if v.get("assigned_subcontractor_id") == assigned_sub]
    if billing_status:
        all_visits = [v for v in all_visits if v.get("billing_status") == billing_status]
    if execution_status:
        all_visits = [v for v in all_visits if v.get("execution_status") == execution_status]

    # Role-based scoping
    if role == "ClientContact":
        all_visits = [v for v in all_visits if db.contracts.get(v.get("contract_id", ""), {}) and db.contracts.get(v.get("contract_id", "")).get("client_id") == user_id]
    elif role == "Subcontractor":
        all_visits = [v for v in all_visits if v.get("assigned_subcontractor_id") == user_id]

    all_visits = sorted(all_visits, key=lambda v: v.get("created_at", ""))
    total = len(all_visits)
    page = all_visits[offset:offset + limit]
    return success_list(page, total, limit, offset)


@bp.route("/visits/<id>/start", methods=["POST"])
def start_visit(id):
    user_id, role = require_roles("CrewLead", "Subcontractor")
    visit = _get_visit_or_404(id)
    if visit["execution_status"] in ("COMPLETED", "MISSED", "CANCELLED", "VOIDED"):
        raise ApiError(ERR_ALREADY_TERMINAL, f"Visit is {visit['execution_status']} (terminal)", 409)
    if visit["execution_status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, f"Cannot start from {visit['execution_status']}", 409)

    # Ownership
    if role == "CrewLead":
        if visit.get("assigned_subcontractor_id") is not None:
            raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "CrewLead can only start in-house visits", 403)
    elif role == "Subcontractor":
        if visit.get("assigned_subcontractor_id") != user_id:
            raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Not your assigned visit", 403)

    visit["execution_status"] = "IN_PROGRESS"
    visit["actual_start_at"] = db.now_iso()
    _touch(visit)
    db.visits.update(id, visit)
    return success_object(visit)


@bp.route("/visits/<id>/complete", methods=["POST"])
def complete_visit(id):
    user_id, role = require_roles("CrewLead", "Subcontractor")
    visit = _get_visit_or_404(id)
    if visit["execution_status"] in ("COMPLETED", "MISSED", "CANCELLED", "VOIDED"):
        raise ApiError(ERR_ALREADY_TERMINAL, f"Visit is {visit['execution_status']} (terminal)", 409)
    if visit["execution_status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, f"Cannot complete from {visit['execution_status']}", 409)

    # Ownership
    if role == "CrewLead":
        if visit.get("assigned_subcontractor_id") is not None:
            raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "CrewLead can only complete in-house visits", 403)
    elif role == "Subcontractor":
        if visit.get("assigned_subcontractor_id") != user_id:
            raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Not your assigned visit", 403)

    # Contract must be ACTIVE
    contract = db.contracts.get(visit.get("contract_id"))
    if contract and contract.get("status") != "ACTIVE":
        raise ApiError(ERR_CONTRACT_NOT_ACTIVE, f"Contract is {contract.get('status')}", 409)

    # Photo gate
    if contract and contract.get("require_photo_verification", True):
        accepted_after = False
        for p in db.photos.list_all():
            if p.get("visit_id") == id and p.get("phase") == "AFTER" and p.get("review_status") == "ACCEPTED":
                accepted_after = True
                break
        if not accepted_after:
            raise ApiError(ERR_PHOTO_REQUIRED, "At least one ACCEPTED AFTER photo required", 422)

    clock = db.get_clock()
    visit["completed_at"] = db.now_iso()
    visit["completed_by_user_id"] = user_id
    visit["execution_status"] = "COMPLETED"

    # Freeze snapshots
    cs = db.contract_sites.get(visit.get("contract_site_id"))
    if cs:
        visit["applied_trigger_depth_inches"] = cs.get("effective_trigger_depth_inches")
        visit["applied_per_push_rate_cents"] = cs.get("effective_per_push_rate_cents")

    # SLA evaluation
    deadline = db._parse_iso(visit.get("sla_deadline_at"))
    if deadline:
        visit["sla_miss"] = clock > deadline
        if visit["sla_miss"]:
            # Will be counted in recompute
            pass

    # Billable minutes for hourly
    if contract and contract.get("contract_type") == "HOURLY":
        visit["billable_minutes"] = compute_billable_minutes(visit)

    _touch(visit)
    db.visits.update(id, visit)

    # If event already VERIFIED or CLOSED, evaluate billing immediately
    event = db.storm_events.get(visit.get("storm_event_id"))
    if event and event.get("status") in ("VERIFIED", "CLOSED"):
        evaluate_visit_billing(visit, event)
        recompute_contract_accumulators(visit.get("contract_id"))
        recompute_draft_invoices(contract_id=visit.get("contract_id"))

    recompute_contract_accumulators(visit.get("contract_id"))

    return success_object(visit)


@bp.route("/visits/<id>/cancel", methods=["POST"])
def cancel_visit(id):
    user_id, role = require_roles("OpsDispatcher")
    visit = _get_visit_or_404(id)
    if visit["execution_status"] in ("COMPLETED", "MISSED", "CANCELLED", "VOIDED"):
        raise ApiError(ERR_ALREADY_TERMINAL, f"Visit is {visit['execution_status']} (terminal)", 409)
    if visit["execution_status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, f"Cannot cancel from {visit['execution_status']}", 409)
    visit["execution_status"] = "CANCELLED"
    _touch(visit)
    db.visits.update(id, visit)
    return success_object(visit)


@bp.route("/visits/<id>/void", methods=["POST"])
def void_visit(id):
    user_id, role = require_roles("OpsDispatcher")
    visit = _get_visit_or_404(id)
    if visit["execution_status"] in ("MISSED", "CANCELLED", "VOIDED"):
        raise ApiError(ERR_ALREADY_TERMINAL, f"Visit is {visit['execution_status']} (terminal)", 409)
    if visit["execution_status"] != "COMPLETED":
        raise ApiError(ERR_INVALID_STATE, f"Cannot void from {visit['execution_status']}", 409)
    if visit.get("billing_status") in ("INVOICED", "DISPUTED", "SETTLED", "WRITTEN_OFF"):
        raise ApiError(ERR_INVALID_STATE, "Visit billing is locked by invoice/dispute", 409)

    visit["execution_status"] = "VOIDED"
    visit["billing_status"] = "NON_BILLABLE"

    # Void all RECORDED materials
    for m in db.materials.list_all():
        if m.get("visit_id") == id and m.get("status") == "RECORDED":
            m["status"] = "VOIDED"
            _touch(m)
            db.materials.update(m["id"], m)

    visit["material_cost_cents"] = 0
    _touch(visit)
    db.visits.update(id, visit)

    # Compensation
    recompute_contract_accumulators(visit.get("contract_id"))
    recompute_draft_invoices(contract_id=visit.get("contract_id"))

    return success_object(visit)


@bp.route("/visits/<id>/reassign", methods=["POST"])
def reassign_visit(id):
    user_id, role = require_roles("OpsDispatcher")
    visit = _get_visit_or_404(id)
    if visit["execution_status"] in ("COMPLETED", "MISSED", "CANCELLED", "VOIDED"):
        raise ApiError(ERR_ALREADY_TERMINAL, f"Visit is {visit['execution_status']} (terminal)", 409)
    if visit["execution_status"] != "AWAITING_BACKUP":
        raise ApiError(ERR_INVALID_STATE, f"Cannot reassign from {visit['execution_status']}", 409)

    body = get_json_body()
    preferred_id = body.get("preferred_subcontractor_id")

    event = db.storm_events.get(visit.get("storm_event_id"))
    site = db.sites.get(visit.get("site_id"))
    contract = db.contracts.get(visit.get("contract_id"))

    if preferred_id:
        # Validate preferred subcontractor
        sub = db.subcontractors.get(preferred_id)
        if not sub:
            raise ApiError(ERR_NOT_FOUND, f"Subcontractor {preferred_id} not found", 404)
        if sub.get("status") != "APPROVED":
            raise ApiError(ERR_SUBCONTRACTOR_NOT_APPROVED, "Subcontractor not APPROVED", 409)
        if site and site.get("requires_loader") and not sub.get("has_loader"):
            raise ApiError(ERR_CAPABILITY_MISMATCH, "Subcontractor lacks loader capability", 422)
        # Check no overlapping CREATED/ACTIVE coverage
        if event:
            ew_start = db._parse_iso(event.get("window_start"))
            ew_end = db._parse_iso(event.get("window_end"))
            if check_coverage_overlap(preferred_id, event.get("window_start"), event.get("window_end")):
                raise ApiError(ERR_COVERAGE_OVERLAP, "Subcontractor has overlapping coverage", 409)
        # Check no FAILED for this event
        for ca in db.coverage_assignments.list_all():
            if ca.get("subcontractor_id") == preferred_id and ca.get("storm_event_id") == visit.get("storm_event_id") and ca.get("status") == "FAILED":
                raise ApiError(ERR_INVALID_STATE, "Subcontractor previously failed on this event", 409)
        selected = sub
    else:
        # Selector pool
        pool = []
        for s in db.subcontractors.list_all():
            if s.get("status") != "APPROVED":
                continue
            if site and site.get("requires_loader") and not s.get("has_loader"):
                continue
            # No overlapping CREATED/ACTIVE coverage with event window
            if event:
                if check_coverage_overlap(s["id"], event.get("window_start"), event.get("window_end")):
                    continue
            # No FAILED for this event
            has_failed = False
            for ca in db.coverage_assignments.list_all():
                if ca.get("subcontractor_id") == s["id"] and ca.get("storm_event_id") == visit.get("storm_event_id") and ca.get("status") == "FAILED":
                    has_failed = True
                    break
            if has_failed:
                continue
            pool.append(s)

        if not pool:
            raise ApiError(ERR_NO_BACKUP_AVAILABLE, "No eligible backup subcontractor", 409)

        # Rank: fewest CREATED/ACTIVE assignments for this event, then created_at ASC
        def count_active(sid):
            return sum(1 for ca in db.coverage_assignments.list_all()
                       if ca.get("subcontractor_id") == sid
                       and ca.get("storm_event_id") == visit.get("storm_event_id")
                       and ca.get("status") in ("CREATED", "ACTIVE"))

        pool.sort(key=lambda s: (count_active(s["id"]), s.get("created_at", "")))
        selected = pool[0]

    # Apply reassignment
    visit["assigned_subcontractor_id"] = selected["id"]
    visit["execution_status"] = "SCHEDULED"
    visit["grace_extended"] = True
    old_deadline = db._parse_iso(visit.get("sla_deadline_at"))
    if old_deadline:
        visit["sla_deadline_at"] = db._to_iso(old_deadline + timedelta(minutes=120))
    _touch(visit)
    db.visits.update(id, visit)

    # Create new ACTIVE CoverageAssignment
    if event:
        new_ca = {
            "id": db._new_id(),
            "storm_event_id": event["id"],
            "contract_id": visit.get("contract_id"),
            "subcontractor_id": selected["id"],
            "coverage_start": event.get("window_start"),
            "coverage_end": event.get("window_end"),
            "status": "ACTIVE",
            "failure_reason": None,
            "created_at": db.now_iso(),
            "updated_at": db.now_iso(),
            "version": 1,
        }
        db.coverage_assignments.create(new_ca)
        # Update subcontractor active count
        selected["active_assignment_count"] = (selected.get("active_assignment_count") or 0) + 1
        _touch(selected)
        db.subcontractors.update(selected["id"], selected)

    return success_object(visit)
