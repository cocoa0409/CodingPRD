"""CoverageAssignment endpoints."""
from flask import Blueprint, request
import db
from middleware import require_roles, get_pagination, get_json_body
from response import success_object, success_created, success_list
from errors import *
from services.helpers import check_coverage_overlap, update_subcontractor_reliability, _touch

bp = Blueprint("coverage", __name__)

ALLOWED_CREATE_FIELDS = {"storm_event_id", "contract_id", "subcontractor_id", "coverage_start", "coverage_end"}


@bp.route("/coverage-assignments", methods=["POST"])
def create_coverage():
    user_id, role = require_roles("OpsDispatcher")
    body = get_json_body()
    unknown = set(body.keys()) - ALLOWED_CREATE_FIELDS
    if unknown:
        raise ApiError(ERR_INVALID_REQUEST, f"Unknown fields: {', '.join(unknown)}", 400)

    storm_event_id = body.get("storm_event_id")
    contract_id = body.get("contract_id")
    subcontractor_id = body.get("subcontractor_id")
    coverage_start = body.get("coverage_start")
    coverage_end = body.get("coverage_end")

    if not storm_event_id:
        raise ApiError(ERR_INVALID_REQUEST, "storm_event_id is required", 400)
    if not contract_id:
        raise ApiError(ERR_INVALID_REQUEST, "contract_id is required", 400)
    if not subcontractor_id:
        raise ApiError(ERR_INVALID_REQUEST, "subcontractor_id is required", 400)
    if not coverage_start or not coverage_end:
        raise ApiError(ERR_INVALID_REQUEST, "coverage_start and coverage_end are required", 400)

    # Resolve IDs left-to-right
    event = db.storm_events.get(storm_event_id)
    if not event:
        raise ApiError(ERR_NOT_FOUND, f"StormEvent {storm_event_id} not found", 404)
    contract = db.contracts.get(contract_id)
    if not contract:
        raise ApiError(ERR_NOT_FOUND, f"Contract {contract_id} not found", 404)
    sub = db.subcontractors.get(subcontractor_id)
    if not sub:
        raise ApiError(ERR_NOT_FOUND, f"Subcontractor {subcontractor_id} not found", 404)

    cs_dt = db._parse_iso(coverage_start)
    ce_dt = db._parse_iso(coverage_end)
    if not cs_dt or not ce_dt:
        raise ApiError(ERR_INVALID_REQUEST, "Invalid coverage dates", 400)
    if ce_dt <= cs_dt:
        raise ApiError(ERR_INVALID_REQUEST, "coverage_end must be > coverage_start", 400)

    # Coverage window must overlap event window
    ew_start = db._parse_iso(event.get("window_start"))
    ew_end = db._parse_iso(event.get("window_end"))
    if ew_start and ew_end:
        if not (cs_dt < ew_end and ew_start < ce_dt):
            raise ApiError(ERR_INVALID_REQUEST, "Coverage window does not overlap event window", 400)

    # Capability check: subcontractor must cover every loader-requiring site of the contract
    for cs in db.contract_sites.list_all():
        if cs.get("contract_id") == contract_id:
            site = db.sites.get(cs.get("site_id"))
            if site and site.get("requires_loader") and not sub.get("has_loader"):
                raise ApiError(ERR_CAPABILITY_MISMATCH, "Subcontractor lacks loader for a site in this contract", 422)

    # Uniqueness: one non-terminal coverage per (subcontractor, event, contract)
    for ca in db.coverage_assignments.list_all():
        if (ca.get("subcontractor_id") == subcontractor_id
            and ca.get("storm_event_id") == storm_event_id
            and ca.get("contract_id") == contract_id
            and ca.get("status") not in ("RELEASED", "FAILED", "CANCELLED")):
            raise ApiError(ERR_DUPLICATE_COVERAGE, "Non-terminal coverage already exists for this triple", 409)

    # Overlap check
    if check_coverage_overlap(subcontractor_id, coverage_start, coverage_end):
        raise ApiError(ERR_COVERAGE_OVERLAP, "Coverage window overlaps existing assignment", 409)

    ca = {
        "id": db._new_id(),
        "storm_event_id": storm_event_id,
        "contract_id": contract_id,
        "subcontractor_id": subcontractor_id,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "status": "CREATED",
        "failure_reason": None,
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
    }
    db.coverage_assignments.create(ca)
    return success_created(ca)


def _get_ca_or_404(id):
    ca = db.coverage_assignments.get(id)
    if not ca:
        raise ApiError(ERR_NOT_FOUND, f"CoverageAssignment {id} not found", 404)
    return ca


@bp.route("/coverage-assignments/<id>", methods=["GET"])
def get_coverage(id):
    user_id, role = require_roles("PlatformAdmin", "OpsDispatcher", "Subcontractor")
    ca = _get_ca_or_404(id)
    if role == "Subcontractor" and ca.get("subcontractor_id") != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Not your coverage assignment", 403)
    return success_object(ca)


@bp.route("/coverage-assignments", methods=["GET"])
def list_coverage():
    user_id, role = require_roles("PlatformAdmin", "OpsDispatcher", "Subcontractor")
    limit, offset = get_pagination()
    all_cas = db.coverage_assignments.list_all()

    storm_event_id = request.args.get("storm_event_id")
    contract_id = request.args.get("contract_id")
    subcontractor_id = request.args.get("subcontractor_id")
    status = request.args.get("status")
    if storm_event_id:
        all_cas = [c for c in all_cas if c.get("storm_event_id") == storm_event_id]
    if contract_id:
        all_cas = [c for c in all_cas if c.get("contract_id") == contract_id]
    if subcontractor_id:
        all_cas = [c for c in all_cas if c.get("subcontractor_id") == subcontractor_id]
    if status:
        all_cas = [c for c in all_cas if c.get("status") == status]
    if role == "Subcontractor":
        all_cas = [c for c in all_cas if c.get("subcontractor_id") == user_id]

    all_cas = sorted(all_cas, key=lambda c: c.get("created_at", ""))
    total = len(all_cas)
    page = all_cas[offset:offset + limit]
    return success_list(page, total, limit, offset)


@bp.route("/coverage-assignments/<id>/activate", methods=["POST"])
def activate_coverage(id):
    user_id, role = require_roles("Subcontractor")
    ca = _get_ca_or_404(id)
    if ca["status"] in ("RELEASED", "FAILED", "CANCELLED"):
        raise ApiError(ERR_ALREADY_TERMINAL, f"Coverage is {ca['status']} (terminal)", 409)
    if ca["status"] != "CREATED":
        raise ApiError(ERR_INVALID_STATE, f"Cannot activate from {ca['status']}", 409)

    # Caller must be the subcontractor
    if ca.get("subcontractor_id") != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Not your coverage assignment", 403)

    # Subcontractor must be APPROVED
    sub = db.subcontractors.get(ca.get("subcontractor_id"))
    if not sub or sub.get("status") != "APPROVED":
        raise ApiError(ERR_SUBCONTRACTOR_NOT_APPROVED, "Subcontractor not APPROVED", 409)

    # Overlap check (exclude self)
    if check_coverage_overlap(ca.get("subcontractor_id"), ca.get("coverage_start"), ca.get("coverage_end"), exclude_id=id):
        raise ApiError(ERR_COVERAGE_OVERLAP, "Coverage overlaps with another assignment", 409)

    ca["status"] = "ACTIVE"
    _touch(ca)
    db.coverage_assignments.update(id, ca)

    # Update sub active count
    if sub:
        sub["active_assignment_count"] = (sub.get("active_assignment_count") or 0) + 1
        _touch(sub)
        db.subcontractors.update(sub["id"], sub)

    return success_object(ca)


@bp.route("/coverage-assignments/<id>/fail", methods=["POST"])
def fail_coverage(id):
    user_id, role = require_roles("Subcontractor", "OpsDispatcher")
    ca = _get_ca_or_404(id)
    if ca["status"] in ("RELEASED", "FAILED", "CANCELLED"):
        raise ApiError(ERR_ALREADY_TERMINAL, f"Coverage is {ca['status']} (terminal)", 409)
    if ca["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, f"Cannot fail from {ca['status']}", 409)

    # Caller must be the subcontractor or OpsDispatcher
    if role == "Subcontractor" and ca.get("subcontractor_id") != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Not your coverage assignment", 403)

    body = get_json_body()
    failure_reason = body.get("failure_reason", "Equipment failure")

    ca["status"] = "FAILED"
    ca["failure_reason"] = failure_reason
    _touch(ca)
    db.coverage_assignments.update(id, ca)

    # CASCADE L1: SCHEDULED visits assigned to this sub under this event -> AWAITING_BACKUP
    for v in db.visits.list_all():
        if (v.get("assigned_subcontractor_id") == ca.get("subcontractor_id")
            and v.get("storm_event_id") == ca.get("storm_event_id")
            and v.get("execution_status") == "SCHEDULED"):
            v["assigned_subcontractor_id"] = None
            v["execution_status"] = "AWAITING_BACKUP"
            _touch(v)
            db.visits.update(v["id"], v)

    # CASCADE L2: Update subcontractor counters and reliability
    sub = db.subcontractors.get(ca.get("subcontractor_id"))
    if sub:
        sub["active_assignment_count"] = max(0, (sub.get("active_assignment_count") or 0) - 1)
        sub["assignments_failed_count"] = (sub.get("assignments_failed_count") or 0) + 1
        update_subcontractor_reliability(sub["id"])

        # CASCADE L3: Auto-suspend check
        released = sub.get("assignments_released_count") or 0
        failed = sub.get("assignments_failed_count") or 0
        if (released + failed) >= 3 and sub.get("reliability_score", 100) < 70:
            sub["status"] = "SUSPENDED"
            _touch(sub)
            db.subcontractors.update(sub["id"], sub)

    return success_object(ca)


@bp.route("/coverage-assignments/<id>/release", methods=["POST"])
def release_coverage(id):
    user_id, role = require_roles("OpsDispatcher")
    ca = _get_ca_or_404(id)
    if ca["status"] in ("RELEASED", "FAILED", "CANCELLED"):
        raise ApiError(ERR_ALREADY_TERMINAL, f"Coverage is {ca['status']} (terminal)", 409)

    if ca["status"] == "CREATED":
        ca["status"] = "CANCELLED"
        _touch(ca)
        db.coverage_assignments.update(id, ca)
        return success_object(ca)

    # ACTIVE -> RELEASED
    # Check: storm event CLOSED, or all visits via this coverage terminal
    event = db.storm_events.get(ca.get("storm_event_id"))
    if event and event.get("status") == "CLOSED":
        pass  # OK
    else:
        terminal_states = {"COMPLETED", "MISSED", "CANCELLED", "VOIDED"}
        all_terminal = True
        for v in db.visits.list_all():
            if (v.get("assigned_subcontractor_id") == ca.get("subcontractor_id")
                and v.get("storm_event_id") == ca.get("storm_event_id")):
                if v.get("execution_status") not in terminal_states:
                    all_terminal = False
                    break
        if not all_terminal:
            raise ApiError(ERR_INVALID_STATE, "Not all visits are in terminal execution state", 409)

    ca["status"] = "RELEASED"
    _touch(ca)
    db.coverage_assignments.update(id, ca)

    # Update sub
    sub = db.subcontractors.get(ca.get("subcontractor_id"))
    if sub:
        sub["active_assignment_count"] = max(0, (sub.get("active_assignment_count") or 0) - 1)
        sub["assignments_released_count"] = (sub.get("assignments_released_count") or 0) + 1
        update_subcontractor_reliability(sub["id"])

    return success_object(ca)
