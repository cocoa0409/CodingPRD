"""GasIncident endpoints and all incident-scoped child resources/actions."""
from flask import Blueprint, request

import clock
import db
import domain
import response
from auth import require_roles
from errors import ApiError
from routes.common import (check_incident_read_scope,
                           check_technician_active_assignment,
                           check_technician_ever_assigned, incident_visible,
                           load_incident)
from validate import (get_body, opt_bool, opt_str, pagination_params, paginate,
                      req_bool, req_enum, req_int, req_number, req_str,
                      sort_by_creation)

bp = Blueprint("incidents", __name__)

ALL = ("SystemAdmin", "Dispatcher", "FieldTechnician", "Supervisor", "Regulator")


# ---------------------------------------------------------------------------
# Incident reads
# ---------------------------------------------------------------------------
@bp.route("/gas-ops/incidents", methods=["GET"])
@require_roles(*ALL)
def list_incidents(user_id, role):
    limit, offset = pagination_params()
    items = sort_by_creation(db.incidents.values())
    territory_id = request.args.get("territory_id")
    lifecycle = request.args.get("lifecycle_status")
    priority = request.args.get("priority")
    if territory_id is not None:
        items = [i for i in items if i["territory_id"] == territory_id]
    if lifecycle is not None:
        items = [i for i in items if i["lifecycle_status"] == lifecycle]
    if priority is not None:
        items = [i for i in items if i["priority"] == priority]
    items = [i for i in items if incident_visible(i, role, user_id)]
    page, total = paginate([domain.ser_incident(i) for i in items], limit, offset)
    return response.success_list(page, limit, offset, total)


@bp.route("/gas-ops/incidents/<incidentId>", methods=["GET"])
@require_roles(*ALL)
def get_incident(incidentId, user_id, role):
    incident = load_incident(incidentId)
    check_incident_read_scope(incident, role, user_id)
    return response.success(domain.ser_incident(incident), 200)


# ---------------------------------------------------------------------------
# Triage / reclassify / close / merge / entry-status
# ---------------------------------------------------------------------------
@bp.route("/gas-ops/incidents/<incidentId>/triage", methods=["POST"])
@require_roles("Dispatcher", "Supervisor")
def triage(incidentId, user_id, role):
    incident = load_incident(incidentId)
    body = get_body()
    priority = req_enum(body, "priority", set(domain.PRIORITIES))
    opt_str(body, "classification_notes")
    if incident["lifecycle_status"] not in ("NEW", "REOPENED"):
        raise ApiError("ERR_INCIDENT_NOT_ACTIVE",
                       "Triage requires lifecycle NEW or REOPENED", 409)
    incident["priority"] = priority
    incident["lifecycle_status"] = "TRIAGED"
    domain.auto_priority_notify(incident)
    domain.bump(incident)
    domain.mark_reports_stale(incident)
    return response.success(domain.ser_incident(incident), 200)


@bp.route("/gas-ops/incidents/<incidentId>/reclassify-priority", methods=["POST"])
@require_roles("Dispatcher", "Supervisor")
def reclassify(incidentId, user_id, role):
    incident = load_incident(incidentId)
    body = get_body()
    new_priority = req_enum(body, "new_priority", set(domain.PRIORITIES))
    expected = req_int(body, "expected_incident_version")
    req_str(body, "reason")
    if incident["lifecycle_status"] not in ("TRIAGED", "DISPATCHED", "ON_SCENE",
                                            "MAKE_SAFE_IN_PROGRESS", "MONITORING"):
        raise ApiError("ERR_INCIDENT_NOT_ACTIVE",
                       "Reclassification requires an active (triaged-or-later) incident", 409)
    if expected != incident["version"]:
        raise ApiError("ERR_STALE_INCIDENT_VERSION",
                       "expected_incident_version does not match the incident's current version", 412)
    incident["priority"] = new_priority
    domain.auto_priority_notify(incident)
    domain.bump(incident)
    domain.mark_reports_stale(incident)
    return response.success(domain.ser_incident(incident), 200)


@bp.route("/gas-ops/incidents/<incidentId>/close", methods=["POST"])
@require_roles("Supervisor")
def close(incidentId, user_id, role):
    incident = load_incident(incidentId)
    body = get_body()
    opt_str(body, "notes")
    if incident["lifecycle_status"] != "MONITORING":
        raise ApiError("ERR_INCIDENT_NOT_ACTIVE", "Close requires lifecycle MONITORING", 409)
    if not incident["make_safe_completed"]:
        raise ApiError("ERR_MAKE_SAFE_NOT_COMPLETED",
                       "Close requires make_safe_completed", 422)
    if incident["leak_confirmed"] and domain.final_determination(incident["id"]) is None:
        raise ApiError("ERR_DETERMINATION_REQUIRED",
                       "A FINAL responsibility determination is required when leak_confirmed", 422)
    if any(a["status"] in domain.ACTIVE_ASSIGNMENT_STATUSES
           for a in domain.assignments_of_incident(incident["id"])):
        raise ApiError("ERR_OPEN_DISPATCHES_EXIST",
                       "An assignment is still EN_ROUTE or ON_SCENE", 409)
    if any(s["status"] in ("REQUESTED", "AUTHORIZED")
           for s in domain.shutoffs_of(incident["id"])):
        raise ApiError("ERR_OPEN_SHUTOFF_ORDER",
                       "A shutoff order is still REQUESTED or AUTHORIZED", 409)
    incident["lifecycle_status"] = "CLOSED"
    incident["closed_at"] = clock.now()
    incident["entry_status"] = "NOT_REQUIRED"
    domain.bump(incident)
    domain.mark_reports_stale(incident)
    return response.success(domain.ser_incident(incident), 200)


@bp.route("/gas-ops/incidents/<incidentId>/merge-duplicate", methods=["POST"])
@require_roles("Supervisor")
def merge_duplicate(incidentId, user_id, role):
    # The path incident is the merge TARGET; the body names the SOURCE to absorb.
    target = load_incident(incidentId)
    body = get_body()
    source_id = req_str(body, "source_incident_id")
    source = db.incidents.get(source_id)
    if source is None:
        raise ApiError("ERR_INCIDENT_NOT_FOUND", "Source incident not found", 404)
    if source["lifecycle_status"] not in ("NEW", "TRIAGED", "DISPATCHED"):
        raise ApiError("ERR_INVALID_STATE",
                       "Merge source must be NEW, TRIAGED, or DISPATCHED", 409)
    if (source["id"] == target["id"] or target["lifecycle_status"] in ("MERGED", "CLOSED")
            or target["normalized_address"] != source["normalized_address"]):
        raise ApiError("ERR_MERGE_TARGET_INVALID",
                       "Merge target must exist, be non-terminal, differ from the source, "
                       "and share the source's normalized address", 409)
    if source["lifecycle_status"] == "DISPATCHED" and any(
            a["status"] in domain.ACTIVE_ASSIGNMENT_STATUSES
            for a in domain.assignments_of_incident(source["id"])):
        raise ApiError("ERR_OPEN_DISPATCHES_EXIST",
                       "Merge source has an assignment still EN_ROUTE or ON_SCENE", 409)
    for c in domain.calls_of(source["id"]):
        c["incident_id"] = target["id"]
    if domain.PRIORITY_RANK[source["priority"]] > domain.PRIORITY_RANK[target["priority"]]:
        target["priority"] = source["priority"]
        domain.auto_priority_notify(target)
    source["lifecycle_status"] = "MERGED"
    domain.bump(source)
    domain.bump(target)
    return response.success(domain.ser_incident(target), 200)


@bp.route("/gas-ops/incidents/<incidentId>/entry-status", methods=["POST"])
@require_roles("FieldTechnician", "Supervisor")
def entry_status(incidentId, user_id, role):
    incident = load_incident(incidentId)
    if role == "FieldTechnician":
        check_technician_ever_assigned(incident["id"], user_id)
    body = get_body()
    to_status = req_enum(body, "to_status", domain.ENTRY_STATUSES)
    if to_status in ("AUTHORIZED", "FORCED"):
        raise ApiError("ERR_INVALID_REQUEST",
                       "AUTHORIZED/FORCED are reachable only via premise-entry-authorizations", 400)
    if to_status == "AWAITING_AUTHORIZATION":
        if incident["lifecycle_status"] not in ("ON_SCENE", "MAKE_SAFE_IN_PROGRESS", "MONITORING"):
            raise ApiError("ERR_INCIDENT_NOT_ACTIVE",
                           "Entry authorization requires an on-scene-stage incident", 409)
        if incident["entry_status"] not in ("NOT_REQUIRED", "REFUSED"):
            raise ApiError("ERR_INVALID_STATE",
                           "AWAITING_AUTHORIZATION is legal only from NOT_REQUIRED or REFUSED", 409)
    elif to_status == "REFUSED":
        if incident["entry_status"] != "AWAITING_AUTHORIZATION":
            raise ApiError("ERR_INVALID_STATE",
                           "REFUSED is legal only from AWAITING_AUTHORIZATION", 409)
    else:  # NOT_REQUIRED has no request-driven transition (system close/reopen only)
        raise ApiError("ERR_INVALID_STATE",
                       "No entry-status transition to NOT_REQUIRED is available", 409)
    incident["entry_status"] = to_status
    domain.bump(incident)
    return response.success(domain.ser_incident(incident), 200)


# ---------------------------------------------------------------------------
# Response-clock pauses (incident-scoped create/list)
# ---------------------------------------------------------------------------
@bp.route("/gas-ops/incidents/<incidentId>/response-clock-pauses", methods=["POST"])
@require_roles("Dispatcher", "Supervisor")
def open_pause(incidentId, user_id, role):
    incident = load_incident(incidentId)
    body = get_body()
    reason = req_enum(body, "reason", domain.PAUSE_REASONS)
    if (incident["lifecycle_status"] not in ("TRIAGED", "DISPATCHED")
            or incident["first_arrival_at"] is not None
            or any(p["ended_at"] is None for p in domain.pauses_of(incident["id"]))):
        raise ApiError("ERR_OPEN_PAUSE_EXISTS",
                       "A pause requires lifecycle TRIAGED/DISPATCHED, no arrival yet, "
                       "and no other OPEN pause", 409)
    rec = domain.new_record(common_fields=True)
    rec.update({
        "incident_id": incident["id"],
        "reason": reason,
        "started_at": clock.now(),
        "ended_at": None,
    })
    db.pauses[rec["id"]] = rec
    return response.success(domain.ser_pause(rec), 201)


@bp.route("/gas-ops/incidents/<incidentId>/response-clock-pauses", methods=["GET"])
@require_roles(*ALL)
def list_pauses(incidentId, user_id, role):
    incident = load_incident(incidentId)
    check_incident_read_scope(incident, role, user_id)
    limit, offset = pagination_params()
    items = sort_by_creation(domain.pauses_of(incident["id"]))
    page, total = paginate([domain.ser_pause(p) for p in items], limit, offset)
    return response.success_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Dispatch assignment creation (incident-scoped)
# ---------------------------------------------------------------------------
@bp.route("/gas-ops/incidents/<incidentId>/dispatches", methods=["POST"])
@require_roles("Dispatcher", "Supervisor")
def create_dispatch(incidentId, user_id, role):
    incident = load_incident(incidentId)
    body = get_body()
    technician_id = body.get("technician_id")
    if technician_id is not None and not isinstance(technician_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "technician_id must be a string", 400)
    notes = opt_str(body, "notes")
    if incident["lifecycle_status"] != "TRIAGED":
        raise ApiError("ERR_INCIDENT_NOT_TRIAGED",
                       "Dispatch requires the incident in TRIAGED", 409)

    if technician_id:
        tech = db.technicians.get(technician_id)
        if tech is None:
            raise ApiError("ERR_TECHNICIAN_NOT_FOUND", "Technician not found", 404)
        if not tech["is_active"]:
            raise ApiError("ERR_INVALID_STATE", "Technician is inactive", 409)
        if not domain.tech_on_shift(tech):
            raise ApiError("ERR_TECHNICIAN_OFF_SHIFT",
                           "Technician is not on shift at the current logical time", 409)
        if tech["home_territory_id"] != incident["territory_id"]:
            raise ApiError("ERR_TECHNICIAN_TERRITORY_MISMATCH",
                           "Technician's home territory differs from the incident territory", 409)
        if domain.tech_active_count(tech["id"]) >= 2:
            raise ApiError("ERR_TECHNICIAN_CAPACITY_REACHED",
                           "Technician already holds 2 active assignments", 409)
    else:
        # Deterministic selector: freeze current priorities, then rank.
        eligible = [t for t in db.technicians.values()
                    if t["is_active"] and domain.tech_on_shift(t)
                    and t["home_territory_id"] == incident["territory_id"]
                    and domain.tech_active_count(t["id"]) < 2]

        def rank_key(t):
            last_cleared = domain.tech_last_cleared_at(t["id"])
            # weighted_load ASC, then last_cleared_at ASC with nulls first, then created_at ASC.
            return (domain.tech_weighted_load(t["id"]),
                    0 if last_cleared is None else 1,
                    last_cleared or clock.now(),
                    t["created_at"],
                    t["_seq"])

        if not eligible:
            raise ApiError("ERR_NO_AVAILABLE_TECHNICIAN",
                           "No eligible technician is available for dispatch", 409)
        tech = min(eligible, key=rank_key)
        technician_id = tech["id"]

    rec = domain.new_record(common_fields=True)
    rec.update({
        "incident_id": incident["id"],
        "technician_id": technician_id,
        "status": "EN_ROUTE",
        "sla_threshold_minutes": domain.threshold_minutes(incident),
        "dispatched_at": clock.now(),
        "arrived_at": None,
        "cleared_at": None,
        "preempt_reason": None,
        "notes": notes,
    })
    db.assignments[rec["id"]] = rec
    incident["lifecycle_status"] = "DISPATCHED"
    domain.bump(incident)
    return response.success(domain.ser_assignment(rec), 201)


@bp.route("/gas-ops/incidents/<incidentId>/dispatches", methods=["GET"])
@require_roles(*ALL)
def list_incident_dispatches(incidentId, user_id, role):
    incident = load_incident(incidentId)
    check_incident_read_scope(incident, role, user_id)
    limit, offset = pagination_params()
    items = sort_by_creation(domain.assignments_of_incident(incident["id"]))
    page, total = paginate([domain.ser_assignment(a) for a in items], limit, offset)
    return response.success_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Atmospheric readings / make-safe actions / make-safe completion
# ---------------------------------------------------------------------------
@bp.route("/gas-ops/incidents/<incidentId>/atmospheric-readings", methods=["POST"])
@require_roles("FieldTechnician")
def create_reading(incidentId, user_id, role):
    incident = load_incident(incidentId)
    check_technician_active_assignment(incident["id"], user_id)
    body = get_body()
    pct_lel = req_number(body, "pct_lel")
    co_ppm = req_number(body, "co_ppm")
    context = req_enum(body, "reading_context", domain.READING_CONTEXTS)
    if pct_lel < 0.0 or pct_lel > 100.0:
        raise ApiError("ERR_INVALID_REQUEST", "pct_lel must be within 0.0-100.0", 400)
    if co_ppm < 0:
        raise ApiError("ERR_INVALID_REQUEST", "co_ppm must be >= 0", 400)
    if incident["lifecycle_status"] not in ("ON_SCENE", "MAKE_SAFE_IN_PROGRESS"):
        raise ApiError("ERR_INCIDENT_NOT_ACTIVE",
                       "Readings require an on-scene-stage incident", 409)
    rec = domain.new_record(common_fields=False)
    rec.update({
        "incident_id": incident["id"],
        "technician_id": user_id,
        "pct_lel": pct_lel,
        "co_ppm": co_ppm,
        "reading_context": context,
        "taken_at": clock.now(),
    })
    db.readings[rec["id"]] = rec
    # Severity recompute event: advances the incident version and may notify.
    incident["severity_score"] = domain.severity_score(incident)
    if incident["severity_score"] >= 80:
        domain.auto_severity_notify(incident, "PUBLIC_ALERT")
    domain.bump(incident)
    domain.mark_reports_stale(incident)
    return response.success(domain.ser_reading(rec), 201)


@bp.route("/gas-ops/incidents/<incidentId>/atmospheric-readings", methods=["GET"])
@require_roles(*ALL)
def list_readings(incidentId, user_id, role):
    incident = load_incident(incidentId)
    check_incident_read_scope(incident, role, user_id)
    limit, offset = pagination_params()
    items = sort_by_creation(domain.readings_of(incident["id"]))
    page, total = paginate([domain.ser_reading(r) for r in items], limit, offset)
    return response.success_list(page, limit, offset, total)


@bp.route("/gas-ops/incidents/<incidentId>/make-safe-actions", methods=["POST"])
@require_roles("FieldTechnician")
def create_action(incidentId, user_id, role):
    incident = load_incident(incidentId)
    check_technician_active_assignment(incident["id"], user_id)
    body = get_body()
    action_type = req_enum(body, "action_type", domain.ACTION_TYPES)
    notes = opt_str(body, "notes")
    if incident["lifecycle_status"] not in ("ON_SCENE", "MAKE_SAFE_IN_PROGRESS"):
        raise ApiError("ERR_INCIDENT_NOT_ACTIVE",
                       "Make-safe actions require an on-scene-stage incident", 409)
    rec = domain.new_record(common_fields=False)
    rec.update({
        "incident_id": incident["id"],
        "technician_id": user_id,
        "action_type": action_type,
        "notes": notes,
        "performed_at": clock.now(),
    })
    db.actions[rec["id"]] = rec
    if incident["lifecycle_status"] == "ON_SCENE":
        incident["lifecycle_status"] = "MAKE_SAFE_IN_PROGRESS"
        domain.bump(incident)
    return response.success(domain.ser_action(rec), 201)


@bp.route("/gas-ops/incidents/<incidentId>/make-safe-actions", methods=["GET"])
@require_roles(*ALL)
def list_actions(incidentId, user_id, role):
    incident = load_incident(incidentId)
    check_incident_read_scope(incident, role, user_id)
    limit, offset = pagination_params()
    items = sort_by_creation(domain.actions_of(incident["id"]))
    page, total = paginate([domain.ser_action(a) for a in items], limit, offset)
    return response.success_list(page, limit, offset, total)


@bp.route("/gas-ops/incidents/<incidentId>/make-safe/complete", methods=["POST"])
@require_roles("FieldTechnician")
def complete_make_safe(incidentId, user_id, role):
    incident = load_incident(incidentId)
    if role == "FieldTechnician":
        check_technician_ever_assigned(incident["id"], user_id)
    body = get_body()
    leak_confirmed = req_bool(body, "leak_confirmed")
    opt_bool(body, "no_make_safe_required", False)
    opt_str(body, "leak_location_guess")
    if incident["lifecycle_status"] not in ("ON_SCENE", "MAKE_SAFE_IN_PROGRESS"):
        raise ApiError("ERR_INCIDENT_NOT_ACTIVE",
                       "Make-safe completion requires an on-scene-stage incident", 409)
    odor = any(c["odor_reported"] for c in domain.calls_of(incident["id"]))
    if odor and not domain.readings_of(incident["id"]):
        raise ApiError("ERR_ATMOSPHERIC_READING_REQUIRED",
                       "An atmospheric reading is required before completing make-safe "
                       "on an odor-reported incident", 422)
    if domain.evacuation_required(incident) and not any(
            a["action_type"] == "EVACUATE" for a in domain.actions_of(incident["id"])):
        raise ApiError("ERR_MAKE_SAFE_NOT_COMPLETED",
                       "Evacuation is required but no EVACUATE action exists", 422)
    incident["make_safe_completed"] = True
    incident["leak_confirmed"] = leak_confirmed
    incident["lifecycle_status"] = "MONITORING"
    domain.bump(incident)
    domain.mark_reports_stale(incident)
    return response.success(domain.ser_incident(incident), 200)


# ---------------------------------------------------------------------------
# Premise entry authorizations
# ---------------------------------------------------------------------------
@bp.route("/gas-ops/incidents/<incidentId>/premise-entry-authorizations", methods=["POST"])
@require_roles("Dispatcher", "Supervisor")
def create_authorization(incidentId, user_id, role):
    incident = load_incident(incidentId)
    body = get_body()
    method = req_enum(body, "method", domain.ENTRY_METHODS)
    authorized_by_name = req_str(body, "authorized_by_name")
    if method in ("EMERGENCY_FORCED", "WARRANT") and role != "Supervisor":
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS",
                       "EMERGENCY_FORCED and WARRANT require a Supervisor", 403)
    if incident["entry_status"] != "AWAITING_AUTHORIZATION":
        raise ApiError("ERR_INVALID_STATE",
                       "Recording an authorization requires entry_status AWAITING_AUTHORIZATION", 409)
    rec = domain.new_record(common_fields=False)
    rec.update({
        "incident_id": incident["id"],
        "method": method,
        "authorized_by_name": authorized_by_name,
        "recorded_by_user_id": user_id,
    })
    db.authorizations[rec["id"]] = rec
    incident["entry_status"] = "AUTHORIZED" if method == "CUSTOMER_CONSENT" else "FORCED"
    domain.bump(incident)
    return response.success(domain.ser_authorization(rec), 201)


@bp.route("/gas-ops/incidents/<incidentId>/premise-entry-authorizations", methods=["GET"])
@require_roles(*ALL)
def list_authorizations(incidentId, user_id, role):
    incident = load_incident(incidentId)
    check_incident_read_scope(incident, role, user_id)
    limit, offset = pagination_params()
    items = sort_by_creation([a for a in db.authorizations.values()
                              if a["incident_id"] == incident["id"]])
    page, total = paginate([domain.ser_authorization(a) for a in items], limit, offset)
    return response.success_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Shutoff orders (incident-scoped create/list)
# ---------------------------------------------------------------------------
@bp.route("/gas-ops/incidents/<incidentId>/shutoff-orders", methods=["POST"])
@require_roles("FieldTechnician", "Supervisor")
def create_shutoff(incidentId, user_id, role):
    incident = load_incident(incidentId)
    if role == "FieldTechnician":
        check_technician_ever_assigned(incident["id"], user_id)
    body = get_body()
    rec = domain.new_record(common_fields=True)
    rec.update({
        "incident_id": incident["id"],
        "scope": req_enum(body, "scope", domain.SHUTOFF_SCOPES),
        "entry_required": req_bool(body, "entry_required"),
        "reason": req_str(body, "reason"),
        "status": "REQUESTED",
        "requested_by_user_id": user_id,
        "authorized_by_user_id": None,
        "executed_by_technician_id": None,
        "executed_at": None,
        "restored_at": None,
    })
    db.shutoffs[rec["id"]] = rec
    return response.success(domain.ser_shutoff(rec), 201)


@bp.route("/gas-ops/incidents/<incidentId>/shutoff-orders", methods=["GET"])
@require_roles(*ALL)
def list_shutoffs(incidentId, user_id, role):
    incident = load_incident(incidentId)
    check_incident_read_scope(incident, role, user_id)
    limit, offset = pagination_params()
    items = sort_by_creation(domain.shutoffs_of(incident["id"]))
    page, total = paginate([domain.ser_shutoff(s) for s in items], limit, offset)
    return response.success_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Responsibility determinations (incident-scoped create/list)
# ---------------------------------------------------------------------------
@bp.route("/gas-ops/incidents/<incidentId>/responsibility-determinations", methods=["POST"])
@require_roles("Supervisor")
def create_determination(incidentId, user_id, role):
    incident = load_incident(incidentId)
    body = get_body()
    responsibility = req_enum(body, "responsibility", domain.RESPONSIBILITIES)
    basis = req_enum(body, "basis", domain.DETERMINATION_BASES)
    expected = req_int(body, "expected_incident_version")
    notes = opt_str(body, "notes")
    if expected != incident["version"]:
        raise ApiError("ERR_STALE_INCIDENT_VERSION",
                       "expected_incident_version does not match the incident's current version", 412)
    rec = domain.new_record(common_fields=True)
    rec.update({
        "incident_id": incident["id"],
        "responsibility": responsibility,
        "basis": basis,
        "notes": notes,
        "status": "DRAFT",
        "drafted_by_user_id": user_id,
        "finalized_by_user_id": None,
        "finalized_at": None,
    })
    db.determinations[rec["id"]] = rec
    domain.bump(incident)
    return response.success(domain.ser_determination(rec), 201)


@bp.route("/gas-ops/incidents/<incidentId>/responsibility-determinations", methods=["GET"])
@require_roles(*ALL)
def list_determinations(incidentId, user_id, role):
    incident = load_incident(incidentId)
    check_incident_read_scope(incident, role, user_id)
    limit, offset = pagination_params()
    items = sort_by_creation(domain.determinations_of(incident["id"]))
    page, total = paginate([domain.ser_determination(d) for d in items], limit, offset)
    return response.success_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Repair work orders (incident-scoped manual create/list)
# ---------------------------------------------------------------------------
@bp.route("/gas-ops/incidents/<incidentId>/repair-work-orders", methods=["POST"])
@require_roles("Supervisor")
def create_work_order(incidentId, user_id, role):
    incident = load_incident(incidentId)
    get_body()  # optional notes; no stored field on the work order
    if not incident["leak_confirmed"]:
        raise ApiError("ERR_INVALID_STATE",
                       "Manual work-order creation requires leak_confirmed == true", 409)
    responsibility = domain.incident_responsibility(incident)
    estimate = domain.provisional_estimate(responsibility, incident["priority"])
    rec = domain.new_record(common_fields=True)
    rec.update({
        "incident_id": incident["id"],
        "origin": "MANUAL",
        "status": "OPEN",
        "crew_id": None,
        "provisional_estimate_cents": estimate,
        "current_estimate_cents": estimate,
        "scheduled_window_start": None,
        "scheduled_window_end": None,
        "lines": None,
        "labor_minutes": None,
        "labor_billed_minutes": None,
        "final_cost_cents": None,
        "completed_at": None,
        "cancel_reason": None,
    })
    db.work_orders[rec["id"]] = rec
    return response.success(domain.ser_work_order(rec), 201)


@bp.route("/gas-ops/incidents/<incidentId>/repair-work-orders", methods=["GET"])
@require_roles(*ALL)
def list_work_orders(incidentId, user_id, role):
    incident = load_incident(incidentId)
    check_incident_read_scope(incident, role, user_id)
    limit, offset = pagination_params()
    items = sort_by_creation(domain.work_orders_of_incident(incident["id"]))
    page, total = paginate([domain.ser_work_order(w) for w in items], limit, offset)
    return response.success_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Public notifications (incident-scoped manual create/list)
# ---------------------------------------------------------------------------
@bp.route("/gas-ops/incidents/<incidentId>/public-notifications", methods=["POST"])
@require_roles("Supervisor")
def create_notification(incidentId, user_id, role):
    incident = load_incident(incidentId)
    body = get_body()
    channel = req_enum(body, "channel", domain.NOTIFICATION_CHANNELS)
    headline = req_str(body, "headline")
    text = req_str(body, "body")
    rec = domain.create_notification(incident, channel, "MANUAL", headline, text)
    return response.success(domain.ser_notification(rec), 201)


@bp.route("/gas-ops/incidents/<incidentId>/public-notifications", methods=["GET"])
@require_roles(*ALL)
def list_notifications(incidentId, user_id, role):
    incident = load_incident(incidentId)
    check_incident_read_scope(incident, role, user_id)
    limit, offset = pagination_params()
    items = sort_by_creation([n for n in db.notifications.values()
                              if n["incident_id"] == incident["id"]])
    page, total = paginate([domain.ser_notification(n) for n in items], limit, offset)
    return response.success_list(page, limit, offset, total)
