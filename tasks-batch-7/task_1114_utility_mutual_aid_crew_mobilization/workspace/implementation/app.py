"""Utility Mutual Aid API — Flask application."""
import os
from datetime import date, timedelta

from flask import Flask, request, jsonify

import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_INVALID_AMOUNT,
    ERR_EVENT_NOT_ACCEPTING_REQUESTS,
    ERR_EVENT_NOT_DEMOBILIZING,
    ERR_EVENT_CLOSE_BLOCKED,
    ERR_EVENT_NOT_FULLY_DEMOBILIZED,
    ERR_SCHEDULE_WINDOW_OVERLAP,
    ERR_SCHEDULE_NOT_PUBLISHED,
    ERR_NO_EFFECTIVE_SCHEDULE,
    ERR_SUPERSEDED_SCHEDULE,
    ERR_LODGING_CAPACITY_EXCEEDED,
    ERR_LODGING_OVERLAP,
    ERR_CREW_NOT_CLEARED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_DUPLICATE_TIMESHEET,
    ERR_DUPLICATE_CLAIM,
    ERR_CERTIFICATION_WINDOW_CLOSED,
    ERR_MOBILIZATION_DEADLINE_PASSED,
    ERR_INVOICE_WINDOW_CLOSED,
    ERR_INVOICE_EXISTS,
    ERR_EMPTY_INVOICE,
    ERR_PAYMENT_AMOUNT_MISMATCH,
    ERR_DISPUTE_AMOUNT_INVALID,
    ERR_CREDIT_EXCEEDS_DISPUTED,
    ERR_AAR_EXISTS,
    ERR_REFERENTIAL_INTEGRITY,
    bad_request,
    conflict,
    not_found,
)
from middleware import (
    get_caller,
    require_role,
    require_scope,
    ALL_ROLES,
)
from response import success_object, success_array, error_body
from services.core import (
    base_fields,
    touch,
    get_or_404,
    crews_of_request,
    request_of_crew,
    event_of_request,
    event_of_crew,
    recompute_request_counts,
    recompute_request_certified_direct,
    recompute_request_invoiced_total,
    recompute_request_full,
    recompute_event_open_request_count,
    recompute_event_intake_posture,
    recompute_event_totals,
    recompute_event_full,
    recompute_block_assigned_rooms,
    recompute_invoice_outstanding,
    crew_release_check_request,
    maybe_transition_request_on_deployable,
    serialize_company,
    serialize_event,
    serialize_schedule,
    serialize_request,
    serialize_crew,
    serialize_briefing,
    serialize_timesheet,
    serialize_lodging_block,
    serialize_lodging_assignment,
    serialize_per_diem_claim,
    serialize_invoice,
    serialize_aar,
)
from services.calcs import (
    find_effective_schedule,
    crew_daily_billing,
    per_diem_claim_amount,
    mobilization_fee,
    invoice_period_sweep,
    invoice_provisional,
)


app = Flask(__name__)


# ---- error handler ----

@app.errorhandler(ApiError)
def handle_api_error(err):
    return jsonify(error_body(err.error_id, err.message)), err.http_status


@app.errorhandler(404)
def handle_404(err):
    return jsonify(error_body("ERR_NOT_FOUND", "resource not found")), 404


@app.errorhandler(405)
def handle_405(err):
    return jsonify(error_body("ERR_NOT_FOUND", "method not allowed")), 405


@app.errorhandler(Exception)
def handle_generic(err):
    import traceback
    traceback.print_exc()
    return jsonify(error_body("ERR_INVALID_REQUEST", f"internal: {err}")), 500


# ---- payload helpers ----

def body():
    if not request.is_json:
        return {}
    try:
        return request.get_json(silent=True) or {}
    except Exception:
        return {}


def require_field(data, name):
    v = data.get(name)
    if v is None:
        raise bad_request(ERR_INVALID_REQUEST, f"missing required field: {name}")
    return v


def require_int(data, name):
    v = require_field(data, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise bad_request(ERR_INVALID_REQUEST, f"field {name} must be an integer")
    return v


def opt_int(data, name, default=None):
    v = data.get(name, default)
    if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
        raise bad_request(ERR_INVALID_REQUEST, f"field {name} must be an integer")
    return v


def require_enum(data, name, choices):
    v = require_field(data, name)
    if v not in choices:
        raise bad_request(ERR_INVALID_REQUEST, f"field {name} must be one of {choices}")
    return v


def paginate(items):
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    sliced = items[offset: offset + limit]
    has_more = (offset + limit) < total
    return sliced, limit, offset, total, has_more


def list_response(items, serializer):
    items = sorted(items, key=lambda x: x["created_at"])
    sliced, limit, offset, total, has_more = paginate(items)
    data = [serializer(x) for x in sliced]
    body_, code = success_array(data, limit, offset, total, has_more)
    return jsonify(body_), code


def eq_filter(items, field, param):
    v = request.args.get(param)
    if v is None:
        return items
    return [x for x in items if str(x.get(field)) == v]


# ============================================================
# Clock
# ============================================================

@app.route("/mutual-aid/_clock/set_current_utc", methods=["POST"])
def set_clock():
    caller = get_caller()
    require_role(caller, ["ProgramAdmin"])
    data = body()
    to_iso8601 = require_field(data, "to_iso8601")
    dt = db.parse_iso(to_iso8601)
    db.set_clock(dt)
    body_, code = success_object({"current_utc": db.iso_of(db.get_clock())})
    return jsonify(body_), code


# ============================================================
# UtilityCompany
# ============================================================

@app.route("/mutual-aid/utility-companies", methods=["POST"])
def create_utility_company():
    caller = get_caller()
    require_role(caller, ["ProgramAdmin"])
    data = body()
    name = require_field(data, "name")
    company_code = require_field(data, "company_code")
    role_capability = require_enum(data, "role_capability", ["HOST", "RESPONDING", "BOTH"])
    home_region = require_field(data, "home_region")

    # Duplicate company_code
    for c in db.utility_companies.values():
        if c["company_code"] == company_code:
            raise bad_request(ERR_INVALID_REQUEST, "duplicate company_code")

    obj = base_fields()
    obj.update({
        "name": name,
        "company_code": company_code,
        "role_capability": role_capability,
        "home_region": home_region,
    })
    db.utility_companies[obj["id"]] = obj
    body_, code = success_object(serialize_company(obj), status=201)
    return jsonify(body_), code


@app.route("/mutual-aid/utility-companies/<id>", methods=["GET"])
def get_utility_company(id):
    caller = get_caller()
    require_role(caller, ALL_ROLES)
    obj = get_or_404(db.utility_companies, id, "utility_company")
    body_, code = success_object(serialize_company(obj))
    return jsonify(body_), code


# ============================================================
# MutualAidEvent
# ============================================================

@app.route("/mutual-aid/events", methods=["POST"])
def create_event():
    caller = get_caller()
    require_role(caller, ["ProgramAdmin"])
    data = body()
    event_name = require_field(data, "event_name")
    host_utility_id = require_field(data, "host_utility_id")
    event_type = require_enum(data, "event_type", ["STORM", "WILDFIRE", "ICE", "FLOOD"])
    declared_start_date = require_field(data, "declared_start_date")
    premium_window_start = require_field(data, "premium_window_start")
    premium_window_end = require_field(data, "premium_window_end")
    mobilization_deadline = require_field(data, "mobilization_deadline")

    # host utility must exist
    get_or_404(db.utility_companies, host_utility_id, "utility_company")

    obj = base_fields()
    obj.update({
        "event_name": event_name,
        "host_utility_id": host_utility_id,
        "event_type": event_type,
        "declared_start_date": declared_start_date,
        "premium_window_start": premium_window_start,
        "premium_window_end": premium_window_end,
        "mobilization_deadline": mobilization_deadline,
        "status": "OPEN",
        "demobilized_at": None,
        "open_request_count": 0,
        "total_certified_direct_cents": 0,
        "total_invoiced_cents": 0,
        "total_paid_cents": 0,
        "intake_posture": "ACCEPTING",
    })
    db.events[obj["id"]] = obj
    body_, code = success_object(serialize_event(obj), status=201)
    return jsonify(body_), code


@app.route("/mutual-aid/events/<id>", methods=["GET"])
def get_event(id):
    caller = get_caller()
    require_role(caller, ALL_ROLES)
    obj = get_or_404(db.events, id, "event")
    body_, code = success_object(serialize_event(obj))
    return jsonify(body_), code


@app.route("/mutual-aid/events", methods=["GET"])
def list_events():
    caller = get_caller()
    require_role(caller, ALL_ROLES)
    items = list(db.events.values())
    items = eq_filter(items, "host_utility_id", "host_utility_id")
    items = eq_filter(items, "status", "status")
    return list_response(items, serialize_event)


@app.route("/mutual-aid/events/<id>/activate", methods=["POST"])
def activate_event(id):
    caller = get_caller()
    require_role(caller, ["ProgramAdmin"])
    obj = get_or_404(db.events, id, "event")
    if obj["status"] != "OPEN":
        raise conflict(ERR_INVALID_STATE_TRANSITION, "event not OPEN")
    obj["status"] = "ACTIVE"
    recompute_event_intake_posture(obj)
    touch(obj)
    body_, code = success_object(serialize_event(obj))
    return jsonify(body_), code


@app.route("/mutual-aid/events/<id>/begin_demobilization", methods=["POST"])
def begin_demobilization(id):
    caller = get_caller()
    require_role(caller, ["HostCoordinator"])
    obj = get_or_404(db.events, id, "event")
    require_scope(caller, obj["host_utility_id"])
    if obj["status"] != "ACTIVE":
        raise conflict(ERR_INVALID_STATE_TRANSITION, "event not ACTIVE")
    obj["status"] = "DEMOBILIZING"
    obj["demobilized_at"] = db.now_iso()
    obj["intake_posture"] = "SEALED"
    touch(obj)
    body_, code = success_object(serialize_event(obj))
    return jsonify(body_), code


@app.route("/mutual-aid/events/<id>/close", methods=["POST"])
def close_event(id):
    caller = get_caller()
    require_role(caller, ["ProgramAdmin"])
    obj = get_or_404(db.events, id, "event")
    if obj["status"] != "DEMOBILIZING":
        raise conflict(ERR_INVALID_STATE_TRANSITION, "event not DEMOBILIZING")

    # AAR must exist with ACCEPTED
    aar = next(
        (a for a in db.after_action_reports.values() if a["event_id"] == id),
        None,
    )
    if aar is None or aar["status"] != "ACCEPTED":
        raise conflict(ERR_EVENT_CLOSE_BLOCKED, "event lacks an ACCEPTED after-action report")

    # All invoices on event's requests must be PAID or VOID
    req_ids = {r["id"] for r in db.assistance_requests.values() if r["event_id"] == id}
    for inv in db.invoices.values():
        if inv["request_id"] in req_ids and inv["status"] not in ("PAID", "VOID"):
            raise conflict(ERR_EVENT_CLOSE_BLOCKED, "outstanding invoices block event close")

    obj["status"] = "CLOSED"
    recompute_event_intake_posture(obj)
    touch(obj)
    body_, code = success_object(serialize_event(obj))
    return jsonify(body_), code


# ============================================================
# BillingRateSchedule
# ============================================================

@app.route("/mutual-aid/billing-rate-schedules", methods=["POST"])
def create_schedule():
    caller = get_caller()
    require_role(caller, ["RespondingCoordinator"])
    data = body()
    event_id = require_field(data, "event_id")
    effective_start_date = require_field(data, "effective_start_date")
    effective_end_date = require_field(data, "effective_end_date")
    rate_lines = require_field(data, "rate_lines")
    storm_premium_bps = require_int(data, "storm_premium_bps")
    per_diem_rate_cents = require_int(data, "per_diem_rate_cents")
    per_diem_method = require_enum(data, "per_diem_method", ["STANDARD", "ACTUAL"])
    mobilization_fee_tiers = require_field(data, "mobilization_fee_tiers")
    ot_multiplier_bps = opt_int(data, "ot_multiplier_bps", 15000)
    dt_multiplier_bps = opt_int(data, "dt_multiplier_bps", 20000)
    ot_threshold_minutes = opt_int(data, "ot_threshold_minutes", 480)
    dt_threshold_minutes = opt_int(data, "dt_threshold_minutes", 960)
    supersedes_schedule_id = data.get("supersedes_schedule_id")

    event = get_or_404(db.events, event_id, "event")
    if supersedes_schedule_id is not None:
        get_or_404(db.billing_rate_schedules, supersedes_schedule_id, "billing_rate_schedule")

    obj = base_fields()
    obj.update({
        "event_id": event_id,
        "responding_utility_id": caller.user_id,
        "supersedes_schedule_id": supersedes_schedule_id,
        "effective_start_date": effective_start_date,
        "effective_end_date": effective_end_date,
        "rate_lines": rate_lines,
        "ot_multiplier_bps": ot_multiplier_bps,
        "dt_multiplier_bps": dt_multiplier_bps,
        "ot_threshold_minutes": ot_threshold_minutes,
        "dt_threshold_minutes": dt_threshold_minutes,
        "storm_premium_bps": storm_premium_bps,
        "per_diem_rate_cents": per_diem_rate_cents,
        "per_diem_method": per_diem_method,
        "mobilization_fee_tiers": mobilization_fee_tiers,
        "status": "DRAFT",
        "published_at": None,
    })
    db.billing_rate_schedules[obj["id"]] = obj
    body_, code = success_object(serialize_schedule(obj), status=201)
    return jsonify(body_), code


@app.route("/mutual-aid/billing-rate-schedules/<id>", methods=["GET"])
def get_schedule(id):
    caller = get_caller()
    require_role(caller, ALL_ROLES)
    obj = get_or_404(db.billing_rate_schedules, id, "billing_rate_schedule")
    body_, code = success_object(serialize_schedule(obj))
    return jsonify(body_), code


@app.route("/mutual-aid/billing-rate-schedules", methods=["GET"])
def list_schedules():
    caller = get_caller()
    require_role(caller, ALL_ROLES)
    items = list(db.billing_rate_schedules.values())
    items = eq_filter(items, "event_id", "event_id")
    items = eq_filter(items, "responding_utility_id", "responding_utility_id")
    items = eq_filter(items, "supersedes_schedule_id", "supersedes_schedule_id")
    items = eq_filter(items, "status", "status")
    return list_response(items, serialize_schedule)


@app.route("/mutual-aid/billing-rate-schedules/<id>/publish", methods=["POST"])
def publish_schedule(id):
    caller = get_caller()
    require_role(caller, ["RespondingCoordinator"])
    obj = get_or_404(db.billing_rate_schedules, id, "billing_rate_schedule")
    # Scope: caller is the schedule's responding utility
    require_scope(caller, obj["responding_utility_id"])
    if obj["status"] != "DRAFT":
        raise conflict(ERR_INVALID_STATE_TRANSITION, "schedule not DRAFT")
    event = db.events.get(obj["event_id"])
    if event is None:
        raise not_found(f"event {obj['event_id']} not found")
    # Event must be OPEN or ACTIVE
    if event["status"] not in ("OPEN", "ACTIVE"):
        raise conflict(ERR_INVALID_STATE_TRANSITION, "event not in OPEN/ACTIVE for publish")

    data = body()
    expected_version = data.get("expected_superseded_schedule_version")
    supersedes_id = obj.get("supersedes_schedule_id")

    # Overlap check (closed-interval); the superseded schedule is exempt
    new_start = db.parse_date(obj["effective_start_date"])
    new_end = db.parse_date(obj["effective_end_date"])
    for other in db.billing_rate_schedules.values():
        if other["id"] == obj["id"]:
            continue
        if supersedes_id and other["id"] == supersedes_id:
            continue
        if other["event_id"] != obj["event_id"]:
            continue
        if other["responding_utility_id"] != obj["responding_utility_id"]:
            continue
        if other["status"] not in ("PUBLISHED", "LOCKED"):
            continue
        o_start = db.parse_date(other["effective_start_date"])
        o_end = db.parse_date(other["effective_end_date"])
        # closed-interval overlap: o_start <= new_end AND new_start <= o_end
        if o_start <= new_end and new_start <= o_end:
            raise conflict(ERR_SCHEDULE_WINDOW_OVERLAP, "schedule window overlaps an existing PUBLISHED/LOCKED schedule")

    # OCC on supersede
    if supersedes_id:
        predecessor = db.billing_rate_schedules.get(supersedes_id)
        if predecessor is None:
            raise not_found(f"billing_rate_schedule {supersedes_id} not found")
        if expected_version is None or int(expected_version) != int(predecessor.get("version", 1)):
            from errors import stale
            raise stale("expected_superseded_schedule_version does not match the superseded schedule's current version")

    obj["status"] = "PUBLISHED"
    obj["published_at"] = db.now_iso()
    touch(obj)

    if supersedes_id:
        predecessor = db.billing_rate_schedules[supersedes_id]
        predecessor["status"] = "SUPERSEDED"
        touch(predecessor)

    body_, code = success_object(serialize_schedule(obj))
    return jsonify(body_), code


@app.route("/mutual-aid/billing-rate-schedules/<id>/lock", methods=["POST"])
def lock_schedule(id):
    caller = get_caller()
    require_role(caller, ["HostFinance"])
    obj = get_or_404(db.billing_rate_schedules, id, "billing_rate_schedule")
    event = db.events.get(obj["event_id"])
    if event is None:
        raise not_found(f"event {obj['event_id']} not found")
    require_scope(caller, event["host_utility_id"])
    if obj["status"] != "PUBLISHED":
        raise conflict(ERR_INVALID_STATE_TRANSITION, "schedule not PUBLISHED")
    obj["status"] = "LOCKED"
    touch(obj)
    body_, code = success_object(serialize_schedule(obj))
    return jsonify(body_), code


# ============================================================
# AssistanceRequest
# ============================================================

@app.route("/mutual-aid/assistance-requests", methods=["POST"])
def create_request():
    caller = get_caller()
    require_role(caller, ["HostCoordinator"])
    data = body()
    event_id = require_field(data, "event_id")
    responding_utility_id = require_field(data, "responding_utility_id")
    requested_crews = require_field(data, "requested_crews")
    required_minimum_crews = require_int(data, "required_minimum_crews")
    earliest_start_date = require_field(data, "earliest_start_date")
    latest_end_date = require_field(data, "latest_end_date")

    event = get_or_404(db.events, event_id, "event")
    require_scope(caller, event["host_utility_id"])

    # responding utility must exist
    get_or_404(db.utility_companies, responding_utility_id, "utility_company")

    # Date sanity
    if db.parse_date(earliest_start_date) > db.parse_date(latest_end_date):
        raise bad_request(ERR_INVALID_REQUEST, "earliest_start_date after latest_end_date")

    # Intake posture
    recompute_event_open_request_count(event)
    recompute_event_intake_posture(event)
    if event["intake_posture"] != "ACCEPTING":
        raise conflict(ERR_EVENT_NOT_ACCEPTING_REQUESTS, "event is not accepting requests")

    obj = base_fields()
    obj.update({
        "event_id": event_id,
        "responding_utility_id": responding_utility_id,
        "requested_crews": requested_crews,
        "required_minimum_crews": required_minimum_crews,
        "earliest_start_date": earliest_start_date,
        "latest_end_date": latest_end_date,
        "status": "DRAFT",
        "amendment_round": 0,
        "counter_terms": None,
        "committed_crew_count": 0,
        "deployable_crew_count": 0,
        "certified_direct_cents": 0,
        "invoiced_total_cents": 0,
    })
    db.assistance_requests[obj["id"]] = obj
    body_, code = success_object(serialize_request(obj), status=201)
    return jsonify(body_), code


@app.route("/mutual-aid/assistance-requests/<id>", methods=["GET"])
def get_request(id):
    caller = get_caller()
    require_role(caller, ALL_ROLES)
    obj = get_or_404(db.assistance_requests, id, "assistance_request")
    body_, code = success_object(serialize_request(obj))
    return jsonify(body_), code


@app.route("/mutual-aid/assistance-requests", methods=["GET"])
def list_requests():
    caller = get_caller()
    require_role(caller, ALL_ROLES)
    items = list(db.assistance_requests.values())
    items = eq_filter(items, "event_id", "event_id")
    items = eq_filter(items, "responding_utility_id", "responding_utility_id")
    items = eq_filter(items, "status", "status")
    return list_response(items, serialize_request)


def _request_and_event(id):
    req = get_or_404(db.assistance_requests, id, "assistance_request")
    event = db.events.get(req["event_id"])
    return req, event


@app.route("/mutual-aid/assistance-requests/<id>/submit", methods=["POST"])
def submit_request(id):
    caller = get_caller()
    require_role(caller, ["HostCoordinator"])
    req, event = _request_and_event(id)
    require_scope(caller, event["host_utility_id"])
    data = body()

    if req["status"] == "DRAFT":
        req["status"] = "SUBMITTED"
        touch(req)
    elif req["status"] == "COUNTERED":
        amended_crews = data.get("amended_crews")
        if amended_crews is None:
            raise bad_request(ERR_INVALID_REQUEST, "amended_crews required when resubmitting from COUNTERED")
        req["requested_crews"] = amended_crews
        if "amended_required_minimum" in data and data["amended_required_minimum"] is not None:
            req["required_minimum_crews"] = data["amended_required_minimum"]
        req["amendment_round"] = int(req.get("amendment_round", 0)) + 1
        req["status"] = "SUBMITTED"
        touch(req)
    else:
        raise conflict(ERR_INVALID_STATE_TRANSITION, "request cannot be submitted from its current state")

    recompute_event_open_request_count(event)
    recompute_event_intake_posture(event)
    touch(event)
    body_, code = success_object(serialize_request(req))
    return jsonify(body_), code


@app.route("/mutual-aid/assistance-requests/<id>/counter", methods=["POST"])
def counter_request(id):
    caller = get_caller()
    require_role(caller, ["RespondingCoordinator"])
    req, event = _request_and_event(id)
    require_scope(caller, req["responding_utility_id"])
    if req["status"] != "SUBMITTED":
        raise conflict(ERR_INVALID_STATE_TRANSITION, "request not SUBMITTED")
    data = body()
    counter_crews = require_field(data, "counter_crews")
    counter_note = data.get("counter_note")
    req["status"] = "COUNTERED"
    req["counter_terms"] = {"counter_crews": counter_crews, "counter_note": counter_note}
    touch(req)
    recompute_event_open_request_count(event)
    recompute_event_intake_posture(event)
    touch(event)
    body_, code = success_object(serialize_request(req))
    return jsonify(body_), code


@app.route("/mutual-aid/assistance-requests/<id>/accept", methods=["POST"])
def accept_request(id):
    caller = get_caller()
    require_role(caller, ["RespondingCoordinator"])
    req, event = _request_and_event(id)
    require_scope(caller, req["responding_utility_id"])
    if req["status"] != "SUBMITTED":
        raise conflict(ERR_INVALID_STATE_TRANSITION, "request not SUBMITTED")
    # Schedule PUBLISHED/LOCKED required
    ok = any(
        s["event_id"] == req["event_id"]
        and s["responding_utility_id"] == req["responding_utility_id"]
        and s["status"] in ("PUBLISHED", "LOCKED")
        for s in db.billing_rate_schedules.values()
    )
    if not ok:
        raise conflict(ERR_SCHEDULE_NOT_PUBLISHED, "no PUBLISHED/LOCKED schedule for (event, responding utility)")
    req["status"] = "ACCEPTED"
    touch(req)
    recompute_event_open_request_count(event)
    recompute_event_intake_posture(event)
    touch(event)
    body_, code = success_object(serialize_request(req))
    return jsonify(body_), code


@app.route("/mutual-aid/assistance-requests/<id>/decline", methods=["POST"])
def decline_request(id):
    caller = get_caller()
    require_role(caller, ["RespondingCoordinator"])
    req, event = _request_and_event(id)
    require_scope(caller, req["responding_utility_id"])
    if req["status"] not in ("SUBMITTED", "COUNTERED"):
        raise conflict(ERR_INVALID_STATE_TRANSITION, "request cannot be declined from its current state")
    req["status"] = "DECLINED"
    touch(req)
    recompute_event_open_request_count(event)
    recompute_event_intake_posture(event)
    touch(event)
    body_, code = success_object(serialize_request(req))
    return jsonify(body_), code


@app.route("/mutual-aid/assistance-requests/<id>/cancel", methods=["POST"])
def cancel_request(id):
    caller = get_caller()
    require_role(caller, ["HostCoordinator"])
    req, event = _request_and_event(id)
    require_scope(caller, event["host_utility_id"])
    if req["status"] not in ("DRAFT", "SUBMITTED", "COUNTERED"):
        raise conflict(ERR_INVALID_STATE_TRANSITION, "request cannot be cancelled from its current state")
    req["status"] = "CANCELLED"
    touch(req)
    recompute_event_open_request_count(event)
    recompute_event_intake_posture(event)
    touch(event)
    body_, code = success_object(serialize_request(req))
    return jsonify(body_), code


# ============================================================
# Crew
# ============================================================

@app.route("/mutual-aid/crews", methods=["POST"])
def create_crew():
    caller = get_caller()
    require_role(caller, ["RespondingCoordinator"])
    data = body()
    request_id = require_field(data, "request_id")
    crew_type = require_enum(data, "crew_type", ["LINE", "TREE", "DAMAGE_ASSESS", "SUBSTATION", "SUPPORT"])
    home_base = require_field(data, "home_base")
    roster = require_field(data, "roster")
    equipment_units = data.get("equipment_units") or []

    req = get_or_404(db.assistance_requests, request_id, "assistance_request")
    # Scope: caller must equal the request's responding utility
    require_scope(caller, req["responding_utility_id"])

    if req["status"] not in ("ACCEPTED", "IN_PROGRESS", "FULFILLED"):
        raise conflict(ERR_INVALID_STATE_TRANSITION, "request not in ACCEPTED/IN_PROGRESS/FULFILLED")

    if not isinstance(roster, list) or len(roster) == 0:
        raise bad_request(ERR_INVALID_REQUEST, "roster must be non-empty")

    equipment_total = sum(int(u.get("daily_rate_cents", 0)) for u in equipment_units)

    obj = base_fields()
    obj.update({
        "request_id": request_id,
        "owning_utility_id": caller.user_id,
        "crew_type": crew_type,
        "home_base": home_base,
        "roster": roster,
        "roster_size": len(roster),
        "equipment_units": equipment_units,
        "equipment_daily_total_cents": equipment_total,
        "mobility_status": "COMMITTED",
        "readiness_status": "AWAITING_BRIEFING",
        "last_suspended_at": None,
        "arrived_at": None,
        "released_at": None,
        "returned_at": None,
    })
    db.crews[obj["id"]] = obj

    recompute_request_counts(req)
    touch(req)
    body_, code = success_object(serialize_crew(obj), status=201)
    return jsonify(body_), code


@app.route("/mutual-aid/crews/<id>", methods=["GET"])
def get_crew(id):
    caller = get_caller()
    require_role(caller, ALL_ROLES)
    obj = get_or_404(db.crews, id, "crew")
    body_, code = success_object(serialize_crew(obj))
    return jsonify(body_), code


@app.route("/mutual-aid/crews", methods=["GET"])
def list_crews():
    caller = get_caller()
    require_role(caller, ALL_ROLES)
    items = list(db.crews.values())
    items = eq_filter(items, "request_id", "request_id")
    items = eq_filter(items, "owning_utility_id", "owning_utility_id")
    items = eq_filter(items, "mobility_status", "mobility_status")
    items = eq_filter(items, "readiness_status", "readiness_status")
    return list_response(items, serialize_crew)


@app.route("/mutual-aid/crews/<id>/confirm_arrival", methods=["POST"])
def confirm_arrival(id):
    caller = get_caller()
    require_role(caller, ["HostCoordinator"])
    crew = get_or_404(db.crews, id, "crew")
    req = request_of_crew(crew)
    event = event_of_request(req)
    require_scope(caller, event["host_utility_id"])

    if crew["mobility_status"] != "COMMITTED":
        raise conflict(ERR_INVALID_STATE_TRANSITION, "crew not COMMITTED")
    if req["status"] not in ("ACCEPTED", "IN_PROGRESS", "FULFILLED"):
        raise conflict(ERR_INVALID_STATE_TRANSITION, "request not in ACCEPTED/IN_PROGRESS/FULFILLED")

    # Mobilization deadline check
    deadline = db.parse_iso(event["mobilization_deadline"])
    if db.get_clock() > deadline:
        raise conflict(ERR_MOBILIZATION_DEADLINE_PASSED, "mobilization deadline passed")

    crew["mobility_status"] = "ARRIVED"
    crew["arrived_at"] = db.now_iso()
    touch(crew)

    # Arrival cascade link 1: lodging RESERVED -> OCCUPIED
    for a in db.lodging_assignments.values():
        if a["crew_id"] == crew["id"] and a["status"] == "RESERVED":
            a["status"] = "OCCUPIED"
            touch(a)
            block = db.lodging_blocks.get(a["block_id"])
            if block:
                recompute_block_assigned_rooms(block)
                touch(block)

    # Arrival cascade link 2/3
    if req["status"] == "ACCEPTED":
        req["status"] = "IN_PROGRESS"
    recompute_request_counts(req)
    maybe_transition_request_on_deployable(req)
    touch(req)

    body_, code = success_object(serialize_crew(crew))
    return jsonify(body_), code


@app.route("/mutual-aid/crews/<id>/release", methods=["POST"])
def release_crew(id):
    caller = get_caller()
    require_role(caller, ["HostCoordinator"])
    crew = get_or_404(db.crews, id, "crew")
    req = request_of_crew(crew)
    event = event_of_request(req)
    require_scope(caller, event["host_utility_id"])

    if crew["mobility_status"] != "ARRIVED":
        raise conflict(ERR_INVALID_STATE_TRANSITION, "crew not ARRIVED")

    today = db.get_clock().date().isoformat()
    crew["mobility_status"] = "DEMOBILIZING"
    crew["released_at"] = db.now_iso()
    crew["readiness_status"] = "RELEASED"
    touch(crew)

    # Demob cascade link 1: OCCUPIED lodging -> CHECKED_OUT
    for a in db.lodging_assignments.values():
        if a["crew_id"] == crew["id"] and a["status"] == "OCCUPIED":
            a["status"] = "CHECKED_OUT"
            a["actual_check_out_date"] = today
            touch(a)
            block = db.lodging_blocks.get(a["block_id"])
            if block:
                recompute_block_assigned_rooms(block)
                touch(block)

    # Demob cascade link 2: deployable recompute + demotion
    recompute_request_counts(req)
    maybe_transition_request_on_deployable(req)
    touch(req)

    body_, code = success_object(serialize_crew(crew))
    return jsonify(body_), code


@app.route("/mutual-aid/crews/<id>/complete_return", methods=["POST"])
def complete_return(id):
    caller = get_caller()
    require_role(caller, ["RespondingCoordinator"])
    crew = get_or_404(db.crews, id, "crew")
    require_scope(caller, crew["owning_utility_id"])

    if crew["mobility_status"] != "DEMOBILIZING":
        raise conflict(ERR_INVALID_STATE_TRANSITION, "crew not DEMOBILIZING")

    crew["mobility_status"] = "RETURNED"
    crew["returned_at"] = db.now_iso()
    touch(crew)

    req = request_of_crew(crew)
    crew_release_check_request(crew)
    recompute_request_counts(req)
    touch(req)

    body_, code = success_object(serialize_crew(crew))
    return jsonify(body_), code


@app.route("/mutual-aid/crews/<id>/withdraw", methods=["POST"])
def withdraw_crew(id):
    caller = get_caller()
    require_role(caller, ["RespondingCoordinator"])
    crew = get_or_404(db.crews, id, "crew")
    require_scope(caller, crew["owning_utility_id"])

    if crew["mobility_status"] != "COMMITTED":
        raise conflict(ERR_INVALID_STATE_TRANSITION, "crew not COMMITTED")

    crew["mobility_status"] = "WITHDRAWN"
    touch(crew)

    req = request_of_crew(crew)
    recompute_request_counts(req)
    maybe_transition_request_on_deployable(req)
    touch(req)

    body_, code = success_object(serialize_crew(crew))
    return jsonify(body_), code


@app.route("/mutual-aid/crews/<id>/suspend", methods=["POST"])
def suspend_crew(id):
    caller = get_caller()
    require_role(caller, ["HostSafetyOfficer"])
    crew = get_or_404(db.crews, id, "crew")
    req = request_of_crew(crew)
    event = event_of_request(req)
    require_scope(caller, event["host_utility_id"])

    if crew["readiness_status"] != "CLEARED_TO_WORK":
        raise conflict(ERR_INVALID_STATE_TRANSITION, "crew not CLEARED_TO_WORK")

    crew["readiness_status"] = "SAFETY_HOLD"
    crew["last_suspended_at"] = db.now_iso()
    touch(crew)

    # Safety cascade link 2: SUBMITTED timesheets and claims -> HELD
    for t in db.timesheets.values():
        if t["crew_id"] == crew["id"] and t["status"] == "SUBMITTED":
            t["status"] = "HELD"
            touch(t)
    for p in db.per_diem_claims.values():
        if p["crew_id"] == crew["id"] and p["status"] == "SUBMITTED":
            p["status"] = "HELD"
            touch(p)

    # Link 3: deployable recompute + possible FULFILLED -> IN_PROGRESS
    recompute_request_counts(req)
    maybe_transition_request_on_deployable(req)
    touch(req)

    body_, code = success_object(serialize_crew(crew))
    return jsonify(body_), code


# ============================================================
# SafetyBriefing
# ============================================================

@app.route("/mutual-aid/safety-briefings", methods=["POST"])
def create_briefing():
    caller = get_caller()
    require_role(caller, ["HostSafetyOfficer"])
    data = body()
    crew_id = require_field(data, "crew_id")
    event_id = require_field(data, "event_id")
    conductor_operator_ref = require_field(data, "conductor_operator_ref")
    host_rules_version = require_field(data, "host_rules_version")
    topics = require_field(data, "topics")

    crew = get_or_404(db.crews, crew_id, "crew")
    event = get_or_404(db.events, event_id, "event")
    req = request_of_crew(crew)

    # Scope: caller is the host utility
    require_scope(caller, event["host_utility_id"])

    # Referential: event must match crew's event
    if req["event_id"] != event_id:
        raise conflict(ERR_REFERENTIAL_INTEGRITY, "briefing event_id does not match crew's event")

    if not isinstance(topics, list) or len(topics) == 0:
        raise bad_request(ERR_INVALID_REQUEST, "topics must be non-empty")

    obj = base_fields()
    obj.update({
        "crew_id": crew_id,
        "event_id": event_id,
        "conductor_operator_ref": conductor_operator_ref,
        "host_rules_version": host_rules_version,
        "topics": topics,
        "conducted_at": db.now_iso(),
        "supervisor_operator_ref": None,
        "acknowledged_at": None,
        "status": "CONDUCTED",
    })
    db.safety_briefings[obj["id"]] = obj

    # Crew readiness transition: AWAITING_BRIEFING -> BRIEFED; SAFETY_HOLD -> BRIEFED only if conducted_at > last_suspended_at
    if crew["readiness_status"] == "AWAITING_BRIEFING":
        crew["readiness_status"] = "BRIEFED"
        touch(crew)
    elif crew["readiness_status"] == "SAFETY_HOLD":
        last_susp = crew.get("last_suspended_at")
        conducted = db.get_clock()
        if last_susp is None or conducted > db.parse_iso(last_susp):
            crew["readiness_status"] = "BRIEFED"
            touch(crew)

    body_, code = success_object(serialize_briefing(obj), status=201)
    return jsonify(body_), code


@app.route("/mutual-aid/safety-briefings/<id>", methods=["GET"])
def get_briefing(id):
    caller = get_caller()
    require_role(caller, ALL_ROLES)
    obj = get_or_404(db.safety_briefings, id, "safety_briefing")
    body_, code = success_object(serialize_briefing(obj))
    return jsonify(body_), code


@app.route("/mutual-aid/safety-briefings", methods=["GET"])
def list_briefings():
    caller = get_caller()
    require_role(caller, ALL_ROLES)
    items = list(db.safety_briefings.values())
    items = eq_filter(items, "crew_id", "crew_id")
    items = eq_filter(items, "event_id", "event_id")
    items = eq_filter(items, "status", "status")
    return list_response(items, serialize_briefing)


@app.route("/mutual-aid/safety-briefings/<id>/acknowledge", methods=["POST"])
def acknowledge_briefing(id):
    caller = get_caller()
    require_role(caller, ["CrewSupervisor"])
    obj = get_or_404(db.safety_briefings, id, "safety_briefing")
    # Scope: caller's X-User-ID is the briefing's crew id
    require_scope(caller, obj["crew_id"])
    if obj["status"] != "CONDUCTED":
        raise conflict(ERR_INVALID_STATE_TRANSITION, "briefing not CONDUCTED")

    data = body()
    supervisor_operator_ref = require_field(data, "supervisor_operator_ref")
    if supervisor_operator_ref == obj["conductor_operator_ref"]:
        raise conflict(ERR_SEGREGATION_OF_DUTIES, "supervisor_operator_ref must differ from conductor_operator_ref")

    obj["supervisor_operator_ref"] = supervisor_operator_ref
    obj["acknowledged_at"] = db.now_iso()
    obj["status"] = "ACKNOWLEDGED"
    touch(obj)

    # Crew readiness BRIEFED -> CLEARED_TO_WORK, with hold-release cascade if returning from SAFETY_HOLD
    crew = db.crews.get(obj["crew_id"])
    if crew is not None and crew["readiness_status"] == "BRIEFED":
        was_hold_return = False
        # Detect if this BRIEFED came from a SAFETY_HOLD (i.e., there are HELD rows or last_suspended_at set)
        if crew.get("last_suspended_at"):
            was_hold_return = True
        crew["readiness_status"] = "CLEARED_TO_WORK"
        touch(crew)
        if was_hold_return:
            for t in db.timesheets.values():
                if t["crew_id"] == crew["id"] and t["status"] == "HELD":
                    t["status"] = "SUBMITTED"
                    touch(t)
            for p in db.per_diem_claims.values():
                if p["crew_id"] == crew["id"] and p["status"] == "HELD":
                    p["status"] = "SUBMITTED"
                    touch(p)
        # Recompute request deployable + possible promotion
        req = request_of_crew(crew)
        if req is not None:
            recompute_request_counts(req)
            maybe_transition_request_on_deployable(req)
            touch(req)

    body_, code = success_object(serialize_briefing(obj))
    return jsonify(body_), code


# ============================================================
# TimeSheet
# ============================================================

@app.route("/mutual-aid/timesheets", methods=["POST"])
def create_timesheet():
    caller = get_caller()
    require_role(caller, ["CrewSupervisor"])
    data = body()
    crew_id = require_field(data, "crew_id")
    work_date = require_field(data, "work_date")
    day_classification = require_enum(data, "day_classification", ["TRAVEL", "WORK", "STANDBY", "REST"])
    reported_work_minutes = opt_int(data, "reported_work_minutes", 0)
    reported_travel_minutes = opt_int(data, "reported_travel_minutes", 0)

    crew = get_or_404(db.crews, crew_id, "crew")
    require_scope(caller, crew_id)

    # Uniqueness on (crew_id, work_date)
    for t in db.timesheets.values():
        if t["crew_id"] == crew_id and t["work_date"] == work_date:
            raise conflict(ERR_DUPLICATE_TIMESHEET, "timesheet already exists for (crew_id, work_date)")

    obj = base_fields()
    obj.update({
        "crew_id": crew_id,
        "work_date": work_date,
        "day_classification": day_classification,
        "reported_work_minutes": reported_work_minutes,
        "reported_travel_minutes": reported_travel_minutes,
        "submitted_by_operator_ref": None,
        "certified_by_operator_ref": None,
        "certified_schedule_id": None,
        "certified_amount_cents": None,
        "billed_invoice_id": None,
        "status": "DRAFT",
    })
    db.timesheets[obj["id"]] = obj
    body_, code = success_object(serialize_timesheet(obj), status=201)
    return jsonify(body_), code


@app.route("/mutual-aid/timesheets/<id>", methods=["GET"])
def get_timesheet(id):
    caller = get_caller()
    require_role(caller, ALL_ROLES)
    obj = get_or_404(db.timesheets, id, "timesheet")
    body_, code = success_object(serialize_timesheet(obj))
    return jsonify(body_), code


@app.route("/mutual-aid/timesheets", methods=["GET"])
def list_timesheets():
    caller = get_caller()
    require_role(caller, ALL_ROLES)
    items = list(db.timesheets.values())
    items = eq_filter(items, "crew_id", "crew_id")
    items = eq_filter(items, "status", "status")
    items = eq_filter(items, "certified_schedule_id", "certified_schedule_id")
    items = eq_filter(items, "billed_invoice_id", "billed_invoice_id")
    return list_response(items, serialize_timesheet)


@app.route("/mutual-aid/timesheets/<id>/submit", methods=["POST"])
def submit_timesheet(id):
    caller = get_caller()
    require_role(caller, ["CrewSupervisor"])
    obj = get_or_404(db.timesheets, id, "timesheet")
    require_scope(caller, obj["crew_id"])
    if obj["status"] != "DRAFT":
        raise conflict(ERR_INVALID_STATE_TRANSITION, "timesheet not DRAFT")
    data = body()
    submitted_by = require_field(data, "submitted_by_operator_ref")
    obj["submitted_by_operator_ref"] = submitted_by
    obj["status"] = "SUBMITTED"
    touch(obj)
    body_, code = success_object(serialize_timesheet(obj))
    return jsonify(body_), code


def _certify_common(obj, caller, data, is_recertify):
    crew = db.crews.get(obj["crew_id"])
    if crew is None:
        raise not_found(f"crew {obj['crew_id']} not found")
    req = request_of_crew(crew)
    event = event_of_request(req)
    require_scope(caller, event["host_utility_id"])

    if is_recertify:
        if obj["status"] != "CERTIFIED":
            raise conflict(ERR_INVALID_STATE_TRANSITION, "timesheet not CERTIFIED")
        pinned = db.billing_rate_schedules.get(obj.get("certified_schedule_id"))
        if pinned is None or pinned["status"] != "SUPERSEDED":
            raise conflict(ERR_INVALID_STATE_TRANSITION, "pinned schedule is not SUPERSEDED")
    else:
        if obj["status"] != "SUBMITTED":
            raise conflict(ERR_INVALID_STATE_TRANSITION, "timesheet not SUBMITTED")

    # Safety gate (priority 6) — beats temporal
    if crew["readiness_status"] != "CLEARED_TO_WORK":
        raise conflict(ERR_CREW_NOT_CLEARED, "crew readiness is not CLEARED_TO_WORK")

    # Temporal: current date <= work_date + 14 days
    work_date = db.parse_date(obj["work_date"])
    today = db.get_clock().date()
    if today > work_date + timedelta(days=14):
        raise conflict(ERR_CERTIFICATION_WINDOW_CLOSED, "certification window closed (more than 14 days after work_date)")

    # Segregation of duties
    certifier = require_field(data, "certifier_operator_ref")
    if certifier == obj.get("submitted_by_operator_ref"):
        raise conflict(ERR_SEGREGATION_OF_DUTIES, "certifier_operator_ref must differ from submitted_by_operator_ref")

    # Effective-schedule selector
    schedule = find_effective_schedule(event["id"], crew["owning_utility_id"], work_date)
    if schedule is None:
        raise conflict(ERR_NO_EFFECTIVE_SCHEDULE, "no PUBLISHED/LOCKED schedule covers work_date")

    # Price
    amount = crew_daily_billing(obj, crew, schedule, event)
    obj["certified_schedule_id"] = schedule["id"]
    obj["certified_amount_cents"] = amount
    obj["certified_by_operator_ref"] = certifier
    obj["status"] = "CERTIFIED"
    touch(obj)

    # Ledger sync
    recompute_request_certified_direct(req)
    touch(req)
    recompute_event_totals(event)
    touch(event)


@app.route("/mutual-aid/timesheets/<id>/certify", methods=["POST"])
def certify_timesheet(id):
    caller = get_caller()
    require_role(caller, ["HostCoordinator"])
    obj = get_or_404(db.timesheets, id, "timesheet")
    _certify_common(obj, caller, body(), is_recertify=False)
    body_, code = success_object(serialize_timesheet(obj))
    return jsonify(body_), code


@app.route("/mutual-aid/timesheets/<id>/recertify", methods=["POST"])
def recertify_timesheet(id):
    caller = get_caller()
    require_role(caller, ["HostCoordinator"])
    obj = get_or_404(db.timesheets, id, "timesheet")
    _certify_common(obj, caller, body(), is_recertify=True)
    body_, code = success_object(serialize_timesheet(obj))
    return jsonify(body_), code


@app.route("/mutual-aid/timesheets/<id>/reject", methods=["POST"])
def reject_timesheet(id):
    caller = get_caller()
    require_role(caller, ["HostCoordinator"])
    obj = get_or_404(db.timesheets, id, "timesheet")
    crew = db.crews.get(obj["crew_id"])
    req = request_of_crew(crew)
    event = event_of_request(req)
    require_scope(caller, event["host_utility_id"])
    if obj["status"] != "SUBMITTED":
        raise conflict(ERR_INVALID_STATE_TRANSITION, "timesheet not SUBMITTED")
    obj["status"] = "REJECTED"
    touch(obj)
    body_, code = success_object(serialize_timesheet(obj))
    return jsonify(body_), code


@app.route("/mutual-aid/timesheets/<id>/revise", methods=["POST"])
def revise_timesheet(id):
    caller = get_caller()
    require_role(caller, ["CrewSupervisor"])
    obj = get_or_404(db.timesheets, id, "timesheet")
    require_scope(caller, obj["crew_id"])
    if obj["status"] != "REJECTED":
        raise conflict(ERR_INVALID_STATE_TRANSITION, "timesheet not REJECTED")
    data = body()
    if "day_classification" in data and data["day_classification"] is not None:
        if data["day_classification"] not in ("TRAVEL", "WORK", "STANDBY", "REST"):
            raise bad_request(ERR_INVALID_REQUEST, "invalid day_classification")
        obj["day_classification"] = data["day_classification"]
    if "reported_work_minutes" in data and data["reported_work_minutes"] is not None:
        obj["reported_work_minutes"] = data["reported_work_minutes"]
    if "reported_travel_minutes" in data and data["reported_travel_minutes"] is not None:
        obj["reported_travel_minutes"] = data["reported_travel_minutes"]
    obj["status"] = "DRAFT"
    touch(obj)
    body_, code = success_object(serialize_timesheet(obj))
    return jsonify(body_), code


# ============================================================
# LodgingBlock
# ============================================================

@app.route("/mutual-aid/lodging-blocks", methods=["POST"])
def create_lodging_block():
    caller = get_caller()
    require_role(caller, ["HostCoordinator"])
    data = body()
    event_id = require_field(data, "event_id")
    hotel_name = require_field(data, "hotel_name")
    block_code = require_field(data, "block_code")
    total_rooms = require_int(data, "total_rooms")
    nightly_rate_cents = require_int(data, "nightly_rate_cents")

    event = get_or_404(db.events, event_id, "event")
    require_scope(caller, event["host_utility_id"])

    obj = base_fields()
    obj.update({
        "event_id": event_id,
        "hotel_name": hotel_name,
        "block_code": block_code,
        "total_rooms": total_rooms,
        "nightly_rate_cents": nightly_rate_cents,
        "assigned_rooms": 0,
    })
    db.lodging_blocks[obj["id"]] = obj
    body_, code = success_object(serialize_lodging_block(obj), status=201)
    return jsonify(body_), code


@app.route("/mutual-aid/lodging-blocks/<id>", methods=["GET"])
def get_lodging_block(id):
    caller = get_caller()
    require_role(caller, ALL_ROLES)
    obj = get_or_404(db.lodging_blocks, id, "lodging_block")
    body_, code = success_object(serialize_lodging_block(obj))
    return jsonify(body_), code


@app.route("/mutual-aid/lodging-blocks", methods=["GET"])
def list_lodging_blocks():
    caller = get_caller()
    require_role(caller, ALL_ROLES)
    items = list(db.lodging_blocks.values())
    items = eq_filter(items, "event_id", "event_id")
    return list_response(items, serialize_lodging_block)


# ============================================================
# LodgingAssignment
# ============================================================

@app.route("/mutual-aid/lodging-assignments", methods=["POST"])
def create_lodging_assignment():
    caller = get_caller()
    require_role(caller, ["HostCoordinator"])
    data = body()
    block_id = require_field(data, "block_id")
    crew_id = require_field(data, "crew_id")
    room_count = require_int(data, "room_count")
    check_in_date = require_field(data, "check_in_date")
    check_out_date = require_field(data, "check_out_date")

    block = get_or_404(db.lodging_blocks, block_id, "lodging_block")
    crew = get_or_404(db.crews, crew_id, "crew")
    req = request_of_crew(crew)

    require_scope(caller, db.events[block["event_id"]]["host_utility_id"])

    # Referential integrity: block's event == crew's event
    if block["event_id"] != req["event_id"]:
        raise conflict(ERR_REFERENTIAL_INTEGRITY, "block does not belong to the crew's event")

    # Capacity: assigned_rooms + room_count <= total_rooms (equality allowed)
    recompute_block_assigned_rooms(block)
    if block["assigned_rooms"] + room_count > block["total_rooms"]:
        raise conflict(ERR_LODGING_CAPACITY_EXCEEDED, "assigned_rooms + room_count > total_rooms")

    # Overlap: same crew, non-cancelled assignment, half-open intersection
    new_in = db.parse_date(check_in_date)
    new_out = db.parse_date(check_out_date)
    for a in db.lodging_assignments.values():
        if a["crew_id"] != crew_id:
            continue
        if a["status"] == "CANCELLED":
            continue
        ex_in = db.parse_date(a["check_in_date"])
        ex_out = db.parse_date(a["check_out_date"])
        if new_in < ex_out and ex_in < new_out:
            raise conflict(ERR_LODGING_OVERLAP, "same-crew assignment overlap")

    obj = base_fields()
    obj.update({
        "block_id": block_id,
        "crew_id": crew_id,
        "room_count": room_count,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
        "actual_check_out_date": None,
        "status": "RESERVED",
    })
    db.lodging_assignments[obj["id"]] = obj

    recompute_block_assigned_rooms(block)
    touch(block)

    body_, code = success_object(serialize_lodging_assignment(obj), status=201)
    return jsonify(body_), code


@app.route("/mutual-aid/lodging-assignments/<id>", methods=["GET"])
def get_lodging_assignment(id):
    caller = get_caller()
    require_role(caller, ALL_ROLES)
    obj = get_or_404(db.lodging_assignments, id, "lodging_assignment")
    body_, code = success_object(serialize_lodging_assignment(obj))
    return jsonify(body_), code


@app.route("/mutual-aid/lodging-assignments", methods=["GET"])
def list_lodging_assignments():
    caller = get_caller()
    require_role(caller, ALL_ROLES)
    items = list(db.lodging_assignments.values())
    items = eq_filter(items, "block_id", "block_id")
    items = eq_filter(items, "crew_id", "crew_id")
    items = eq_filter(items, "status", "status")
    return list_response(items, serialize_lodging_assignment)


@app.route("/mutual-aid/lodging-assignments/<id>/cancel", methods=["POST"])
def cancel_lodging_assignment(id):
    caller = get_caller()
    require_role(caller, ["HostCoordinator"])
    obj = get_or_404(db.lodging_assignments, id, "lodging_assignment")
    block = db.lodging_blocks.get(obj["block_id"])
    if block is None:
        raise not_found(f"lodging_block {obj['block_id']} not found")
    event = db.events.get(block["event_id"])
    require_scope(caller, event["host_utility_id"])
    if obj["status"] != "RESERVED":
        raise conflict(ERR_INVALID_STATE_TRANSITION, "assignment not RESERVED")
    obj["status"] = "CANCELLED"
    touch(obj)
    recompute_block_assigned_rooms(block)
    touch(block)
    body_, code = success_object(serialize_lodging_assignment(obj))
    return jsonify(body_), code


# ============================================================
# PerDiemClaim
# ============================================================

@app.route("/mutual-aid/per-diem-claims", methods=["POST"])
def create_per_diem_claim():
    caller = get_caller()
    require_role(caller, ["RespondingCoordinator"])
    data = body()
    crew_id = require_field(data, "crew_id")
    claim_date = require_field(data, "claim_date")
    member_count = require_int(data, "member_count")
    meals_provided_count = require_int(data, "meals_provided_count")
    day_factor_type = require_enum(data, "day_factor_type", ["FULL", "TRAVEL"])
    receipts_total_cents = data.get("receipts_total_cents")

    crew = get_or_404(db.crews, crew_id, "crew")
    require_scope(caller, crew["owning_utility_id"])
    req = request_of_crew(crew)
    event = event_of_request(req)

    # Uniqueness on (crew_id, claim_date)
    for p in db.per_diem_claims.values():
        if p["crew_id"] == crew_id and p["claim_date"] == claim_date:
            raise conflict(ERR_DUPLICATE_CLAIM, "claim already exists for (crew_id, claim_date)")

    # member_count range
    if member_count < 1 or member_count > crew["roster_size"]:
        raise bad_request(ERR_INVALID_REQUEST, "member_count out of range 1..roster_size")

    # Effective schedule
    schedule = find_effective_schedule(event["id"], crew["owning_utility_id"], db.parse_date(claim_date))
    if schedule is None:
        raise conflict(ERR_NO_EFFECTIVE_SCHEDULE, "no PUBLISHED/LOCKED schedule covers claim_date")

    if schedule["per_diem_method"] == "ACTUAL" and receipts_total_cents is None:
        raise bad_request(ERR_INVALID_REQUEST, "receipts_total_cents required for ACTUAL per-diem method")

    # lodging_covered: non-cancelled assignment covering claim_date
    cdate = db.parse_date(claim_date)
    lodging_covered = False
    for a in db.lodging_assignments.values():
        if a["crew_id"] != crew_id:
            continue
        if a["status"] == "CANCELLED":
            continue
        ci = db.parse_date(a["check_in_date"])
        co = db.parse_date(a["check_out_date"])
        if ci <= cdate < co:
            lodging_covered = True
            break

    method_applied, amount = per_diem_claim_amount(
        member_count,
        meals_provided_count,
        day_factor_type,
        receipts_total_cents if receipts_total_cents is not None else 0,
        schedule,
    )

    obj = base_fields()
    obj.update({
        "crew_id": crew_id,
        "claim_date": claim_date,
        "member_count": member_count,
        "meals_provided_count": meals_provided_count,
        "day_factor_type": day_factor_type,
        "receipts_total_cents": receipts_total_cents,
        "method_applied": method_applied,
        "lodging_covered": lodging_covered,
        "amount_cents": amount,
        "status": "SUBMITTED",
    })
    db.per_diem_claims[obj["id"]] = obj
    body_, code = success_object(serialize_per_diem_claim(obj), status=201)
    return jsonify(body_), code


@app.route("/mutual-aid/per-diem-claims/<id>", methods=["GET"])
def get_per_diem_claim(id):
    caller = get_caller()
    require_role(caller, ALL_ROLES)
    obj = get_or_404(db.per_diem_claims, id, "per_diem_claim")
    body_, code = success_object(serialize_per_diem_claim(obj))
    return jsonify(body_), code


@app.route("/mutual-aid/per-diem-claims", methods=["GET"])
def list_per_diem_claims():
    caller = get_caller()
    require_role(caller, ALL_ROLES)
    items = list(db.per_diem_claims.values())
    items = eq_filter(items, "crew_id", "crew_id")
    items = eq_filter(items, "status", "status")
    return list_response(items, serialize_per_diem_claim)


@app.route("/mutual-aid/per-diem-claims/<id>/approve", methods=["POST"])
def approve_per_diem_claim(id):
    caller = get_caller()
    require_role(caller, ["HostCoordinator"])
    obj = get_or_404(db.per_diem_claims, id, "per_diem_claim")
    crew = db.crews.get(obj["crew_id"])
    req = request_of_crew(crew)
    event = event_of_request(req)
    require_scope(caller, event["host_utility_id"])
    if obj["status"] != "SUBMITTED":
        raise conflict(ERR_INVALID_STATE_TRANSITION, "claim not SUBMITTED")
    obj["status"] = "APPROVED"
    touch(obj)
    recompute_request_certified_direct(req)
    touch(req)
    recompute_event_totals(event)
    touch(event)
    body_, code = success_object(serialize_per_diem_claim(obj))
    return jsonify(body_), code


@app.route("/mutual-aid/per-diem-claims/<id>/reject", methods=["POST"])
def reject_per_diem_claim(id):
    caller = get_caller()
    require_role(caller, ["HostCoordinator"])
    obj = get_or_404(db.per_diem_claims, id, "per_diem_claim")
    crew = db.crews.get(obj["crew_id"])
    req = request_of_crew(crew)
    event = event_of_request(req)
    require_scope(caller, event["host_utility_id"])
    if obj["status"] != "SUBMITTED":
        raise conflict(ERR_INVALID_STATE_TRANSITION, "claim not SUBMITTED")
    obj["status"] = "REJECTED"
    touch(obj)
    body_, code = success_object(serialize_per_diem_claim(obj))
    return jsonify(body_), code


# ============================================================
# Invoice
# ============================================================

@app.route("/mutual-aid/invoices", methods=["POST"])
def create_invoice():
    caller = get_caller()
    require_role(caller, ["RespondingFinance"])
    data = body()
    request_id = require_field(data, "request_id")
    rate_schedule_id = require_field(data, "rate_schedule_id")
    billing_period_start = require_field(data, "billing_period_start")
    billing_period_end = require_field(data, "billing_period_end")

    req = get_or_404(db.assistance_requests, request_id, "assistance_request")
    schedule = get_or_404(db.billing_rate_schedules, rate_schedule_id, "billing_rate_schedule")
    event = event_of_request(req)

    # Scope: caller is the request's responding utility
    require_scope(caller, req["responding_utility_id"])

    # State: request must be in IN_PROGRESS, FULFILLED, RELEASED
    if req["status"] not in ("IN_PROGRESS", "FULFILLED", "RELEASED"):
        raise conflict(ERR_INVALID_STATE_TRANSITION, "request not in IN_PROGRESS/FULFILLED/RELEASED")

    # Referential integrity: schedule matches (event, responding utility)
    if schedule["event_id"] != req["event_id"] or schedule["responding_utility_id"] != req["responding_utility_id"]:
        raise conflict(ERR_REFERENTIAL_INTEGRITY, "schedule does not belong to the request's (event, responding utility)")

    # Date sanity
    if db.parse_date(billing_period_start) > db.parse_date(billing_period_end):
        raise bad_request(ERR_INVALID_REQUEST, "billing_period_start after billing_period_end")

    # At most one non-DRAFT non-VOID invoice per request
    for inv in db.invoices.values():
        if inv["request_id"] == request_id and inv["status"] not in ("DRAFT", "VOID"):
            raise conflict(ERR_INVOICE_EXISTS, "a non-DRAFT non-VOID invoice already exists for the request")

    obj = base_fields()
    obj.update({
        "request_id": request_id,
        "rate_schedule_id": rate_schedule_id,
        "billing_period_start": billing_period_start,
        "billing_period_end": billing_period_end,
        "provisional_subtotal_cents": None,
        "provisional_fee_cents": None,
        "provisional_total_cents": None,
        "labor_subtotal_cents": None,
        "per_diem_subtotal_cents": None,
        "mobilization_fee_cents": None,
        "final_total_cents": None,
        "dispute_reason": None,
        "disputed_amount_cents": None,
        "proposed_credit_cents": None,
        "applied_credit_total_cents": 0,
        "amount_paid_cents": 0,
        "outstanding_cents": None,
        "approved_by_operator_ref": None,
        "status": "DRAFT",
        "submitted_at": None,
        "paid_at": None,
        "_swept_claim_ids": [],
        "_swept_timesheet_ids": [],
    })

    # Provisional totals computed at creation
    sub, fee, total = invoice_provisional(obj, req, schedule, event)
    obj["provisional_subtotal_cents"] = sub
    obj["provisional_fee_cents"] = fee
    obj["provisional_total_cents"] = total

    db.invoices[obj["id"]] = obj
    body_, code = success_object(serialize_invoice(obj), status=201)
    return jsonify(body_), code


@app.route("/mutual-aid/invoices/<id>", methods=["GET"])
def get_invoice(id):
    caller = get_caller()
    require_role(caller, ALL_ROLES)
    obj = get_or_404(db.invoices, id, "invoice")
    body_, code = success_object(serialize_invoice(obj))
    return jsonify(body_), code


@app.route("/mutual-aid/invoices", methods=["GET"])
def list_invoices():
    caller = get_caller()
    require_role(caller, ALL_ROLES)
    items = list(db.invoices.values())
    items = eq_filter(items, "request_id", "request_id")
    items = eq_filter(items, "rate_schedule_id", "rate_schedule_id")
    items = eq_filter(items, "status", "status")
    return list_response(items, serialize_invoice)


@app.route("/mutual-aid/invoices/<id>/submit", methods=["POST"])
def submit_invoice(id):
    caller = get_caller()
    require_role(caller, ["RespondingFinance"])
    obj = get_or_404(db.invoices, id, "invoice")
    req = db.assistance_requests.get(obj["request_id"])
    event = event_of_request(req)
    schedule = db.billing_rate_schedules.get(obj["rate_schedule_id"])

    require_scope(caller, req["responding_utility_id"])

    if obj["status"] != "DRAFT":
        raise conflict(ERR_INVALID_STATE_TRANSITION, "invoice not DRAFT")

    # Event must be DEMOBILIZING
    if event["status"] != "DEMOBILIZING":
        raise conflict(ERR_EVENT_NOT_DEMOBILIZING, "event is not DEMOBILIZING")

    # 30-day window: current <= demobilized_at + 30 days
    demob_at = db.parse_iso(event.get("demobilized_at")) if event.get("demobilized_at") else None
    if demob_at is None:
        raise conflict(ERR_INVOICE_WINDOW_CLOSED, "event has no demobilized_at")
    if db.get_clock() > demob_at + timedelta(days=30):
        raise conflict(ERR_INVOICE_WINDOW_CLOSED, "invoice submission window closed (>30 days after demobilized_at)")

    # Compute final totals via sweep (identifies covered timesheets/claims)
    labor, perdiem, swept_ts_ids, swept_pd_ids = invoice_period_sweep(obj, req, schedule)

    # Check no covered CERTIFIED timesheet is pinned to a SUPERSEDED schedule
    for tid in swept_ts_ids:
        ts = db.timesheets[tid]
        pinned = db.billing_rate_schedules.get(ts.get("certified_schedule_id"))
        if pinned is not None and pinned["status"] == "SUPERSEDED":
            raise conflict(ERR_SUPERSEDED_SCHEDULE, "covered timesheet pinned to SUPERSEDED schedule; recertify first")

    fee = mobilization_fee(labor + perdiem, schedule["mobilization_fee_tiers"])
    final_total = labor + perdiem + fee
    if final_total <= 0:
        raise conflict(ERR_EMPTY_INVOICE, "final_total_cents == 0; nothing newly billable in period")

    obj["labor_subtotal_cents"] = labor
    obj["per_diem_subtotal_cents"] = perdiem
    obj["mobilization_fee_cents"] = fee
    obj["final_total_cents"] = final_total
    obj["status"] = "SUBMITTED"
    obj["submitted_at"] = db.now_iso()
    obj["outstanding_cents"] = final_total
    obj["_swept_timesheet_ids"] = swept_ts_ids
    obj["_swept_claim_ids"] = swept_pd_ids
    touch(obj)

    # Sweep: stamp billed_invoice_id on each swept timesheet
    for tid in swept_ts_ids:
        ts = db.timesheets[tid]
        ts["billed_invoice_id"] = obj["id"]
        touch(ts)

    # Ledger sync
    recompute_request_invoiced_total(req)
    touch(req)
    recompute_event_totals(event)
    touch(event)

    body_, code = success_object(serialize_invoice(obj))
    return jsonify(body_), code


@app.route("/mutual-aid/invoices/<id>/approve", methods=["POST"])
def approve_invoice(id):
    caller = get_caller()
    require_role(caller, ["HostFinance"])
    obj = get_or_404(db.invoices, id, "invoice")
    req = db.assistance_requests.get(obj["request_id"])
    event = event_of_request(req)
    require_scope(caller, event["host_utility_id"])
    if obj["status"] != "SUBMITTED":
        raise conflict(ERR_INVALID_STATE_TRANSITION, "invoice not SUBMITTED")

    data = body()
    approver = require_field(data, "approver_operator_ref")

    # Segregation: approver must differ from EVERY covered timesheet's certified_by
    for tid in obj.get("_swept_timesheet_ids", []) or []:
        ts = db.timesheets.get(tid)
        if ts and ts.get("certified_by_operator_ref") == approver:
            raise conflict(ERR_SEGREGATION_OF_DUTIES, "approver certified a covered timesheet")

    obj["approved_by_operator_ref"] = approver
    obj["status"] = "APPROVED"
    touch(obj)
    body_, code = success_object(serialize_invoice(obj))
    return jsonify(body_), code


@app.route("/mutual-aid/invoices/<id>/mark_paid", methods=["POST"])
def mark_paid_invoice(id):
    caller = get_caller()
    require_role(caller, ["HostFinance"])
    obj = get_or_404(db.invoices, id, "invoice")
    req = db.assistance_requests.get(obj["request_id"])
    event = event_of_request(req)
    require_scope(caller, event["host_utility_id"])
    if obj["status"] != "APPROVED":
        raise conflict(ERR_INVALID_STATE_TRANSITION, "invoice not APPROVED")

    data = body()
    amount = require_int(data, "amount_cents")
    if amount <= 0:
        raise bad_request(ERR_INVALID_AMOUNT, "amount_cents must be positive")

    recompute_invoice_outstanding(obj)
    if amount != obj["outstanding_cents"]:
        raise conflict(ERR_PAYMENT_AMOUNT_MISMATCH, "amount_cents != outstanding_cents")

    obj["amount_paid_cents"] = amount
    obj["paid_at"] = db.now_iso()
    obj["status"] = "PAID"
    recompute_invoice_outstanding(obj)
    touch(obj)

    recompute_event_totals(event)
    touch(event)

    # Settlement cascade: if request is RELEASED, close it
    if req["status"] == "RELEASED":
        req["status"] = "CLOSED"
        touch(req)

    body_, code = success_object(serialize_invoice(obj))
    return jsonify(body_), code


@app.route("/mutual-aid/invoices/<id>/void", methods=["POST"])
def void_invoice(id):
    caller = get_caller()
    require_role(caller, ["RespondingFinance"])
    obj = get_or_404(db.invoices, id, "invoice")
    req = db.assistance_requests.get(obj["request_id"])
    event = event_of_request(req)
    require_scope(caller, req["responding_utility_id"])
    if obj["status"] not in ("DRAFT", "SUBMITTED"):
        raise conflict(ERR_INVALID_STATE_TRANSITION, "invoice not DRAFT or SUBMITTED")

    was_submitted = obj["status"] == "SUBMITTED"
    obj["status"] = "VOID"
    touch(obj)

    if was_submitted:
        # Clear billed_invoice_id on swept timesheets
        for tid in obj.get("_swept_timesheet_ids", []) or []:
            ts = db.timesheets.get(tid)
            if ts and ts.get("billed_invoice_id") == obj["id"]:
                ts["billed_invoice_id"] = None
                touch(ts)
        # Recompute invoiced totals (compensating)
        recompute_request_invoiced_total(req)
        touch(req)
        recompute_event_totals(event)
        touch(event)

    body_, code = success_object(serialize_invoice(obj))
    return jsonify(body_), code


@app.route("/mutual-aid/invoices/<id>/dispute", methods=["POST"])
def dispute_invoice(id):
    caller = get_caller()
    require_role(caller, ["HostFinance"])
    obj = get_or_404(db.invoices, id, "invoice")
    req = db.assistance_requests.get(obj["request_id"])
    event = event_of_request(req)
    require_scope(caller, event["host_utility_id"])
    if obj["status"] != "SUBMITTED":
        raise conflict(ERR_INVALID_STATE_TRANSITION, "invoice not SUBMITTED")

    data = body()
    reason = require_enum(data, "reason", ["RATE_MISMATCH", "HOURS_MISMATCH", "PER_DIEM_MISMATCH", "DUPLICATE", "OTHER"])
    disputed_amount = require_int(data, "disputed_amount_cents")

    recompute_invoice_outstanding(obj)
    if disputed_amount < 1 or disputed_amount > obj["outstanding_cents"]:
        raise conflict(ERR_DISPUTE_AMOUNT_INVALID, "disputed_amount_cents outside 1..outstanding_cents")

    obj["dispute_reason"] = reason
    obj["disputed_amount_cents"] = disputed_amount
    obj["status"] = "DISPUTED"
    touch(obj)
    body_, code = success_object(serialize_invoice(obj))
    return jsonify(body_), code


@app.route("/mutual-aid/invoices/<id>/propose_credit", methods=["POST"])
def propose_credit_invoice(id):
    caller = get_caller()
    require_role(caller, ["RespondingFinance"])
    obj = get_or_404(db.invoices, id, "invoice")
    req = db.assistance_requests.get(obj["request_id"])
    require_scope(caller, req["responding_utility_id"])
    if obj["status"] != "DISPUTED":
        raise conflict(ERR_INVALID_STATE_TRANSITION, "invoice not DISPUTED")

    data = body()
    credit = require_int(data, "credit_cents")
    disputed = obj.get("disputed_amount_cents") or 0
    if credit < 1 or credit > disputed:
        raise conflict(ERR_CREDIT_EXCEEDS_DISPUTED, "credit_cents outside 1..disputed_amount_cents")

    obj["proposed_credit_cents"] = credit
    obj["status"] = "CREDIT_PROPOSED"
    touch(obj)
    body_, code = success_object(serialize_invoice(obj))
    return jsonify(body_), code


@app.route("/mutual-aid/invoices/<id>/accept_credit", methods=["POST"])
def accept_credit_invoice(id):
    caller = get_caller()
    require_role(caller, ["HostFinance"])
    obj = get_or_404(db.invoices, id, "invoice")
    req = db.assistance_requests.get(obj["request_id"])
    event = event_of_request(req)
    require_scope(caller, event["host_utility_id"])
    if obj["status"] != "CREDIT_PROPOSED":
        raise conflict(ERR_INVALID_STATE_TRANSITION, "invoice not CREDIT_PROPOSED")

    proposed = obj.get("proposed_credit_cents") or 0
    obj["applied_credit_total_cents"] = int(obj.get("applied_credit_total_cents", 0)) + proposed
    obj["dispute_reason"] = None
    obj["disputed_amount_cents"] = None
    obj["proposed_credit_cents"] = None
    obj["status"] = "SUBMITTED"
    recompute_invoice_outstanding(obj)
    touch(obj)
    body_, code = success_object(serialize_invoice(obj))
    return jsonify(body_), code


@app.route("/mutual-aid/invoices/<id>/reject_credit", methods=["POST"])
def reject_credit_invoice(id):
    caller = get_caller()
    require_role(caller, ["HostFinance"])
    obj = get_or_404(db.invoices, id, "invoice")
    req = db.assistance_requests.get(obj["request_id"])
    event = event_of_request(req)
    require_scope(caller, event["host_utility_id"])
    if obj["status"] != "CREDIT_PROPOSED":
        raise conflict(ERR_INVALID_STATE_TRANSITION, "invoice not CREDIT_PROPOSED")
    obj["status"] = "ESCALATED"
    touch(obj)
    body_, code = success_object(serialize_invoice(obj))
    return jsonify(body_), code


@app.route("/mutual-aid/invoices/<id>/arbitrate", methods=["POST"])
def arbitrate_invoice(id):
    caller = get_caller()
    require_role(caller, ["ProgramAdmin"])
    obj = get_or_404(db.invoices, id, "invoice")
    if obj["status"] != "ESCALATED":
        raise conflict(ERR_INVALID_STATE_TRANSITION, "invoice not ESCALATED")
    data = body()
    final_credit = require_int(data, "final_credit_cents")
    disputed = obj.get("disputed_amount_cents") or 0
    if final_credit < 0 or final_credit > disputed:
        raise conflict(ERR_CREDIT_EXCEEDS_DISPUTED, "final_credit_cents outside 0..disputed_amount_cents")

    obj["applied_credit_total_cents"] = int(obj.get("applied_credit_total_cents", 0)) + final_credit
    obj["dispute_reason"] = None
    obj["disputed_amount_cents"] = None
    obj["proposed_credit_cents"] = None
    obj["status"] = "SUBMITTED"
    recompute_invoice_outstanding(obj)
    touch(obj)
    body_, code = success_object(serialize_invoice(obj))
    return jsonify(body_), code


# ============================================================
# AfterActionReport
# ============================================================

@app.route("/mutual-aid/after-action-reports", methods=["POST"])
def create_aar():
    caller = get_caller()
    require_role(caller, ["HostCoordinator"])
    data = body()
    event_id = require_field(data, "event_id")
    summary = require_field(data, "summary")
    lessons_learned = data.get("lessons_learned")

    event = get_or_404(db.events, event_id, "event")
    require_scope(caller, event["host_utility_id"])

    # Uniqueness: one AAR per event
    for a in db.after_action_reports.values():
        if a["event_id"] == event_id:
            raise conflict(ERR_AAR_EXISTS, "an after-action report already exists for the event")

    obj = base_fields()
    obj.update({
        "event_id": event_id,
        "summary": summary,
        "lessons_learned": lessons_learned,
        "total_crew_days": 0,
        "as_certified_total_cents": 0,
        "as_billed_total_cents": 0,
        "variance_cents": 0,
        "status": "DRAFTING",
    })
    db.after_action_reports[obj["id"]] = obj
    body_, code = success_object(serialize_aar(obj), status=201)
    return jsonify(body_), code


@app.route("/mutual-aid/after-action-reports/<id>", methods=["GET"])
def get_aar(id):
    caller = get_caller()
    require_role(caller, ALL_ROLES)
    obj = get_or_404(db.after_action_reports, id, "after_action_report")
    body_, code = success_object(serialize_aar(obj))
    return jsonify(body_), code


@app.route("/mutual-aid/after-action-reports", methods=["GET"])
def list_aar():
    caller = get_caller()
    require_role(caller, ALL_ROLES)
    items = list(db.after_action_reports.values())
    items = eq_filter(items, "event_id", "event_id")
    items = eq_filter(items, "status", "status")
    return list_response(items, serialize_aar)


@app.route("/mutual-aid/after-action-reports/<id>/submit", methods=["POST"])
def submit_aar(id):
    caller = get_caller()
    require_role(caller, ["HostCoordinator"])
    obj = get_or_404(db.after_action_reports, id, "after_action_report")
    event = db.events.get(obj["event_id"])
    if event is None:
        raise not_found(f"event {obj['event_id']} not found")
    require_scope(caller, event["host_utility_id"])
    if obj["status"] != "DRAFTING":
        raise conflict(ERR_INVALID_STATE_TRANSITION, "report not DRAFTING")

    # All crews on event's requests must be in terminal mobility
    reqs = [r for r in db.assistance_requests.values() if r["event_id"] == event["id"]]
    req_ids = {r["id"] for r in reqs}
    crews = [c for c in db.crews.values() if c["request_id"] in req_ids]
    for c in crews:
        if c["mobility_status"] not in ("RETURNED", "WITHDRAWN"):
            raise conflict(ERR_EVENT_NOT_FULLY_DEMOBILIZED, "a crew is not in terminal mobility")

    crew_ids = {c["id"] for c in crews}

    total_crew_days = sum(
        1 for t in db.timesheets.values()
        if t["crew_id"] in crew_ids and t["status"] == "CERTIFIED" and t["day_classification"] == "WORK"
    )
    as_certified = sum(
        (t.get("certified_amount_cents") or 0)
        for t in db.timesheets.values()
        if t["crew_id"] in crew_ids and t["status"] == "CERTIFIED"
    ) + sum(
        (p.get("amount_cents") or 0)
        for p in db.per_diem_claims.values()
        if p["crew_id"] in crew_ids and p["status"] == "APPROVED"
    )
    as_billed = sum(
        (i.get("final_total_cents") or 0)
        for i in db.invoices.values()
        if i["request_id"] in req_ids and i["status"] in ("APPROVED", "PAID")
    )

    obj["total_crew_days"] = total_crew_days
    obj["as_certified_total_cents"] = as_certified
    obj["as_billed_total_cents"] = as_billed
    obj["variance_cents"] = as_billed - as_certified
    obj["status"] = "SUBMITTED"
    touch(obj)
    body_, code = success_object(serialize_aar(obj))
    return jsonify(body_), code


@app.route("/mutual-aid/after-action-reports/<id>/accept", methods=["POST"])
def accept_aar(id):
    caller = get_caller()
    require_role(caller, ["ProgramAdmin"])
    obj = get_or_404(db.after_action_reports, id, "after_action_report")
    if obj["status"] != "SUBMITTED":
        raise conflict(ERR_INVALID_STATE_TRANSITION, "report not SUBMITTED")
    obj["status"] = "ACCEPTED"
    touch(obj)
    body_, code = success_object(serialize_aar(obj))
    return jsonify(body_), code


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
