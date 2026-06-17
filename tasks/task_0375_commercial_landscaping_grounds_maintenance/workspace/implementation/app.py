"""Commercial Landscaping & Grounds Maintenance API — Flask entry point.

In-memory only; the store starts empty on every boot (no seeding). See db.py.
"""

import os

from flask import Flask, request

import db
import errors
import response
import services
from middleware import get_user_context, require_role
from validation import (
    get_json_body, parse_pagination, require_str, require_int,
    require_enum, optional_enum, optional_bool,
)

app = Flask(__name__)

ALL_ROLES = ["AccountManager", "CrewLead", "QualityInspector", "DispatchOperator"]


# =========================================================================
# Error handling
# =========================================================================
@app.errorhandler(errors.ApiError)
def handle_api_error(exc):
    return response.error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(_exc):
    # Unknown route — generic invalid request (no specific resource semantics).
    return response.error_response("ERR_INVALID_REQUEST", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(_exc):
    return response.error_response("ERR_INVALID_REQUEST", "Method not allowed", 405)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, errors.ApiError):
        return handle_api_error(exc)
    return response.error_response("ERR_INVALID_REQUEST", "Internal error: %s" % exc, 500)


# =========================================================================
# Lookup helpers (existence checks, priority 3)
# =========================================================================
def get_or_404(coll, entity_id, err_spec):
    rec = coll.get(entity_id)
    if rec is None:
        errors.fail(err_spec, "Resource not found")
    return rec


def paginate_and_respond(records):
    """Sort by created_at ASC (PRD 2.3, tie-break by _seq), paginate, respond."""
    records = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(records)
    limit, offset = parse_pagination()
    page = records[offset:offset + limit]
    return response.array_response([db.public(r) for r in page], limit, offset, total)


# =========================================================================
# Service Accounts + clock
# =========================================================================
@app.route("/v1/accounts", methods=["POST"])
def create_account():
    _uid, role = get_user_context()
    require_role(role, ["AccountManager"])
    body = get_json_body()
    name = require_str(body, "name")
    region_code = require_str(body, "region_code")
    rec = db.make_common({
        "name": name,
        "region_code": region_code,
        "current_utc": "1970-01-01T00:00:00.000Z",
    })
    db.ACCOUNTS[rec["id"]] = rec
    return response.object_response(db.public(rec), 201)


@app.route("/v1/accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    rec = get_or_404(db.ACCOUNTS, account_id, errors.ERR_ACCOUNT_NOT_FOUND)
    return response.object_response(db.public(rec), 200)


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _uid, role = get_user_context()
    require_role(role, ["AccountManager"])
    body = get_json_body()
    account_id = require_str(body, "account_id")
    to_iso8601 = require_str(body, "to_iso8601")
    rec = get_or_404(db.ACCOUNTS, account_id, errors.ERR_ACCOUNT_NOT_FOUND)
    rec["current_utc"] = to_iso8601
    db.touch(rec)
    return response.object_response(db.public(rec), 200)


# =========================================================================
# Sites
# =========================================================================
@app.route("/v1/sites", methods=["POST"])
def create_site():
    _uid, role = get_user_context()
    require_role(role, ["AccountManager"])
    body = get_json_body()
    service_account_id = require_str(body, "service_account_id")
    name = require_str(body, "name")
    address = require_str(body, "address")
    turf_area_sqft = require_int(body, "turf_area_sqft", gt=0)
    snow_zone = optional_enum(body, "snow_zone", {"PRIORITY", "STANDARD", "EXEMPT"}, "STANDARD")
    get_or_404(db.ACCOUNTS, service_account_id, errors.ERR_ACCOUNT_NOT_FOUND)
    rec = db.make_common({
        "service_account_id": service_account_id,
        "name": name,
        "address": address,
        "turf_area_sqft": turf_area_sqft,
        "snow_zone": snow_zone,
    })
    db.SITES[rec["id"]] = rec
    return response.object_response(db.public(rec), 201)


@app.route("/v1/sites/<site_id>", methods=["GET"])
def get_site(site_id):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    rec = get_or_404(db.SITES, site_id, errors.ERR_SITE_NOT_FOUND)
    return response.object_response(db.public(rec), 200)


@app.route("/v1/sites", methods=["GET"])
def list_sites():
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    sid = request.args.get("service_account_id")
    recs = [r for r in db.SITES.values()
            if sid is None or r["service_account_id"] == sid]
    return paginate_and_respond(recs)


# =========================================================================
# Contracts
# =========================================================================
@app.route("/v1/contracts", methods=["POST"])
def create_contract():
    _uid, role = get_user_context()
    require_role(role, ["AccountManager"])
    body = get_json_body()
    service_account_id = require_str(body, "service_account_id")
    site_id = require_str(body, "site_id")
    annual_budget_cents = require_int(body, "annual_budget_cents", gt=0)
    billing_cycle = require_enum(body, "billing_cycle", {"MONTHLY", "QUARTERLY"})
    get_or_404(db.ACCOUNTS, service_account_id, errors.ERR_ACCOUNT_NOT_FOUND)
    get_or_404(db.SITES, site_id, errors.ERR_SITE_NOT_FOUND)
    rec = db.make_common({
        "service_account_id": service_account_id,
        "site_id": site_id,
        "annual_budget_cents": annual_budget_cents,
        "billing_cycle": billing_cycle,
        "committed_cents": 0,
        "billed_cents": 0,
        "budget_remaining_cents": annual_budget_cents,
        "status": "DRAFT",
    })
    db.CONTRACTS[rec["id"]] = rec
    return response.object_response(db.public(rec), 201)


@app.route("/v1/contracts/<contract_id>", methods=["GET"])
def get_contract(contract_id):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    rec = get_or_404(db.CONTRACTS, contract_id, errors.ERR_CONTRACT_NOT_FOUND)
    return response.object_response(db.public(rec), 200)


@app.route("/v1/contracts", methods=["GET"])
def list_contracts():
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    sid = request.args.get("service_account_id")
    site_id = request.args.get("site_id")
    recs = [r for r in db.CONTRACTS.values()
            if (sid is None or r["service_account_id"] == sid)
            and (site_id is None or r["site_id"] == site_id)]
    return paginate_and_respond(recs)


@app.route("/v1/contracts/<contract_id>/activate", methods=["POST"])
def activate_contract(contract_id):
    _uid, role = get_user_context()
    require_role(role, ["AccountManager"])
    contract = get_or_404(db.CONTRACTS, contract_id, errors.ERR_CONTRACT_NOT_FOUND)
    status = contract["status"]
    if status == "DRAFT":
        # Activation from DRAFT requires at least one plan.
        has_plan = any(p["service_contract_id"] == contract_id for p in db.PLANS.values())
        if not has_plan:
            errors.fail(errors.ERR_NO_PLAN_DEFINED, "Contract has no service plan")
        contract["status"] = "ACTIVE"
        db.touch(contract)
    elif status == "SUSPENDED":
        contract["status"] = "ACTIVE"
        db.touch(contract)
    else:
        # Not DRAFT and not SUSPENDED. PRD: activation needs DRAFT
        # (ERR_CONTRACT_NOT_DRAFT) or reactivation needs SUSPENDED
        # (ERR_CONTRACT_NOT_SUSPENDED). ACTIVE / TERMINATED are neither.
        if status == "TERMINATED":
            errors.fail(errors.ERR_CONTRACT_NOT_SUSPENDED, "Contract is terminated")
        # status == ACTIVE
        errors.fail(errors.ERR_CONTRACT_NOT_DRAFT, "Contract is not DRAFT")
    return response.object_response(db.public(contract), 200)


@app.route("/v1/contracts/<contract_id>/suspend", methods=["POST"])
def suspend_contract(contract_id):
    _uid, role = get_user_context()
    require_role(role, ["AccountManager"])
    contract = get_or_404(db.CONTRACTS, contract_id, errors.ERR_CONTRACT_NOT_FOUND)
    if contract["status"] != "ACTIVE":
        errors.fail(errors.ERR_CONTRACT_NOT_ACTIVE, "Contract is not ACTIVE")
    contract["status"] = "SUSPENDED"
    db.touch(contract)
    # Cascade-cancel SCHEDULED visits under this contract.
    for v in list(db.VISITS.values()):
        if v["service_contract_id"] == contract_id and v["execution_status"] == "SCHEDULED":
            services.cancel_visit_cascade(v)
    services.reconcile_committed(contract)
    return response.object_response(db.public(contract), 200)


@app.route("/v1/contracts/<contract_id>/terminate", methods=["POST"])
def terminate_contract(contract_id):
    _uid, role = get_user_context()
    require_role(role, ["AccountManager"])
    contract = get_or_404(db.CONTRACTS, contract_id, errors.ERR_CONTRACT_NOT_FOUND)
    if contract["status"] not in ("ACTIVE", "SUSPENDED"):
        errors.fail(errors.ERR_CONTRACT_NOT_TERMINABLE, "Contract is not terminable")
    # No visit under the contract may be IN_PROGRESS.
    for v in db.VISITS.values():
        if v["service_contract_id"] == contract_id and v["execution_status"] == "IN_PROGRESS":
            errors.fail(errors.ERR_VISIT_IN_PROGRESS, "A visit is in progress")
    was_active = contract["status"] == "ACTIVE"
    contract["status"] = "TERMINATED"
    db.touch(contract)
    if was_active:
        for v in list(db.VISITS.values()):
            if v["service_contract_id"] == contract_id and v["execution_status"] == "SCHEDULED":
                services.cancel_visit_cascade(v)
        services.reconcile_committed(contract)
    return response.object_response(db.public(contract), 200)


# =========================================================================
# Plans
# =========================================================================
@app.route("/v1/plans", methods=["POST"])
def create_plan():
    _uid, role = get_user_context()
    require_role(role, ["AccountManager"])
    body = get_json_body()
    service_contract_id = require_str(body, "service_contract_id")
    service_type = require_enum(body, "service_type", {"MOWING", "MULCH", "AERATION"})
    frequency = require_enum(body, "frequency", {"WEEKLY", "BIWEEKLY", "SEASONAL"})
    base_rate_cents = require_int(body, "base_rate_cents", gt=0)
    contract = get_or_404(db.CONTRACTS, service_contract_id, errors.ERR_CONTRACT_NOT_FOUND)
    rec = db.make_common({
        "service_contract_id": service_contract_id,
        "site_id": contract["site_id"],  # copied from parent contract
        "service_type": service_type,
        "frequency": frequency,
        "base_rate_cents": base_rate_cents,
        "status": "ACTIVE",
    })
    db.PLANS[rec["id"]] = rec
    return response.object_response(db.public(rec), 201)


@app.route("/v1/plans/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    rec = get_or_404(db.PLANS, plan_id, errors.ERR_PLAN_NOT_FOUND)
    return response.object_response(db.public(rec), 200)


@app.route("/v1/plans", methods=["GET"])
def list_plans():
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    cid = request.args.get("service_contract_id")
    site_id = request.args.get("site_id")
    recs = [r for r in db.PLANS.values()
            if (cid is None or r["service_contract_id"] == cid)
            and (site_id is None or r["site_id"] == site_id)]
    return paginate_and_respond(recs)


@app.route("/v1/plans/<plan_id>/pause", methods=["POST"])
def pause_plan(plan_id):
    _uid, role = get_user_context()
    require_role(role, ["AccountManager"])
    plan = get_or_404(db.PLANS, plan_id, errors.ERR_PLAN_NOT_FOUND)
    plan["status"] = "PAUSED"
    db.touch(plan)
    return response.object_response(db.public(plan), 200)


# =========================================================================
# Crews
# =========================================================================
@app.route("/v1/crews", methods=["POST"])
def create_crew():
    _uid, role = get_user_context()
    require_role(role, ["AccountManager"])
    body = get_json_body()
    service_account_id = require_str(body, "service_account_id")
    name = require_str(body, "name")
    hourly_rate_cents = require_int(body, "hourly_rate_cents", gt=0)
    certified_for_snow = optional_bool(body, "certified_for_snow", False)
    get_or_404(db.ACCOUNTS, service_account_id, errors.ERR_ACCOUNT_NOT_FOUND)
    rec = db.make_common({
        "service_account_id": service_account_id,
        "name": name,
        "hourly_rate_cents": hourly_rate_cents,
        "certified_for_snow": certified_for_snow,
    })
    db.CREWS[rec["id"]] = rec
    return response.object_response(db.public(rec), 201)


@app.route("/v1/crews/<crew_id>", methods=["GET"])
def get_crew(crew_id):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    rec = get_or_404(db.CREWS, crew_id, errors.ERR_CREW_NOT_FOUND)
    return response.object_response(db.public(rec), 200)


@app.route("/v1/crews", methods=["GET"])
def list_crews():
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    sid = request.args.get("service_account_id")
    recs = [r for r in db.CREWS.values()
            if sid is None or r["service_account_id"] == sid]
    return paginate_and_respond(recs)


# =========================================================================
# Routes
# =========================================================================
@app.route("/v1/routes", methods=["POST"])
def create_route():
    _uid, role = get_user_context()
    require_role(role, ["AccountManager", "CrewLead"])
    body = get_json_body()
    crew_id = require_str(body, "crew_id")
    route_date = require_str(body, "route_date")
    shift_start_minute = require_int(body, "shift_start_minute", ge=0)
    shift_end_minute = require_int(body, "shift_end_minute")
    if not (shift_start_minute < 1440):
        errors.fail(errors.ERR_INVALID_REQUEST, "shift_start_minute must be in [0,1440)")
    if not (shift_end_minute > shift_start_minute):
        errors.fail(errors.ERR_INVALID_REQUEST, "shift_end_minute must be > shift_start_minute")
    if not (shift_end_minute <= 1440):
        errors.fail(errors.ERR_INVALID_REQUEST, "shift_end_minute must be <= 1440")
    crew = get_or_404(db.CREWS, crew_id, errors.ERR_CREW_NOT_FOUND)
    rec = db.make_common({
        "crew_id": crew_id,
        "service_account_id": crew["service_account_id"],  # copied from crew
        "route_date": route_date,
        "shift_start_minute": shift_start_minute,
        "shift_end_minute": shift_end_minute,
        "booked_minutes": 0,
        "status": "OPEN",
    })
    db.ROUTES[rec["id"]] = rec
    return response.object_response(db.public(rec), 201)


@app.route("/v1/routes/<route_id>", methods=["GET"])
def get_route(route_id):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    rec = get_or_404(db.ROUTES, route_id, errors.ERR_ROUTE_NOT_FOUND)
    return response.object_response(db.public(rec), 200)


@app.route("/v1/routes", methods=["GET"])
def list_routes():
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    crew_id = request.args.get("crew_id")
    sid = request.args.get("service_account_id")
    recs = [r for r in db.ROUTES.values()
            if (crew_id is None or r["crew_id"] == crew_id)
            and (sid is None or r["service_account_id"] == sid)]
    return paginate_and_respond(recs)


@app.route("/v1/routes/<route_id>/lock", methods=["POST"])
def lock_route(route_id):
    _uid, role = get_user_context()
    require_role(role, ["CrewLead"])
    route = get_or_404(db.ROUTES, route_id, errors.ERR_ROUTE_NOT_FOUND)
    route["status"] = "LOCKED"
    db.touch(route)
    return response.object_response(db.public(route), 200)


# =========================================================================
# Visits
# =========================================================================
@app.route("/v1/visits", methods=["POST"])
def create_visit():
    _uid, role = get_user_context()
    require_role(role, ["AccountManager", "CrewLead"])
    body = get_json_body()
    service_plan_id = require_str(body, "service_plan_id")
    route_schedule_id = require_str(body, "route_schedule_id")
    slot_start_minute = require_int(body, "slot_start_minute", ge=0)
    slot_duration_minute = require_int(body, "slot_duration_minute", gt=0)
    expected_version = require_int(body, "expected_service_contract_version", ge=0)

    # Existence (priority 3): body FKs left-to-right.
    plan = get_or_404(db.PLANS, service_plan_id, errors.ERR_PLAN_NOT_FOUND)
    route = get_or_404(db.ROUTES, route_schedule_id, errors.ERR_ROUTE_NOT_FOUND)
    contract = db.CONTRACTS.get(plan["service_contract_id"])
    if contract is None:
        errors.fail(errors.ERR_CONTRACT_NOT_FOUND, "Contract not found")

    # OCC (priority 5) — runs before state/business checks.
    if expected_version != contract["version"]:
        errors.fail(errors.ERR_STALE_CONTRACT_VERSION, "Stale contract version")

    # Cross-entity state guards (priority 7).
    if contract["status"] != "ACTIVE":
        errors.fail(errors.ERR_CONTRACT_NOT_ACTIVE, "Contract is not ACTIVE")
    if plan["status"] != "ACTIVE":
        errors.fail(errors.ERR_PLAN_PAUSED, "Plan is PAUSED")
    if route["status"] != "OPEN":
        errors.fail(errors.ERR_ROUTE_NOT_OPEN, "Route is not OPEN")

    # Cross-account integrity (priority 8): plan, route, contract share one account.
    crew = db.CREWS.get(route["crew_id"])
    acct = contract["service_account_id"]
    plan_account = db.SITES[plan["site_id"]]["service_account_id"]
    if route["service_account_id"] != acct or plan_account != acct:
        errors.fail(errors.ERR_CROSS_ACCOUNT_REFERENCE, "Cross-account reference")

    # Temporal: slot must lie within shift and not overlap (half-open) a
    # non-CANCELLED visit on the route (priority 9).
    slot_end = slot_start_minute + slot_duration_minute
    if slot_start_minute < route["shift_start_minute"] or slot_end > route["shift_end_minute"]:
        errors.fail(errors.ERR_VISIT_SLOT_CONFLICT, "Slot outside shift window")
    for other in db.VISITS.values():
        if other["route_schedule_id"] != route_schedule_id:
            continue
        if other["execution_status"] == "CANCELLED":
            continue
        o_start = other["slot_start_minute"]
        o_end = other["slot_start_minute"] + other["slot_duration_minute"]
        # Half-open overlap: collide iff start < o_end and o_start < end.
        if slot_start_minute < o_end and o_start < slot_end:
            errors.fail(errors.ERR_VISIT_SLOT_CONFLICT, "Slot overlaps an existing visit")

    site = db.SITES[plan["site_id"]]
    rec = db.make_common({
        "service_plan_id": service_plan_id,
        "service_contract_id": contract["id"],  # copied from plan
        "route_schedule_id": route_schedule_id,
        "crew_id": route["crew_id"],  # copied from route's crew
        "slot_start_minute": slot_start_minute,
        "slot_duration_minute": slot_duration_minute,
        "actual_labor_minutes": 0,
        "estimated_charge_cents": 0,
        "final_charge_cents": 0,
        "execution_status": "SCHEDULED",
        "billing_status": "UNBILLED",
    })
    rec["estimated_charge_cents"] = services.visit_estimated_charge(rec, plan, site, crew)
    db.VISITS[rec["id"]] = rec

    # Side effects: route booked_minutes, contract reconcile + version bump.
    route["booked_minutes"] += slot_duration_minute
    db.touch(route)
    services.reconcile_committed(contract)
    return response.object_response(db.public(rec), 201)


@app.route("/v1/visits/<visit_id>", methods=["GET"])
def get_visit(visit_id):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    rec = get_or_404(db.VISITS, visit_id, errors.ERR_VISIT_NOT_FOUND)
    return response.object_response(db.public(rec), 200)


@app.route("/v1/visits", methods=["GET"])
def list_visits():
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    plan_id = request.args.get("service_plan_id")
    contract_id = request.args.get("service_contract_id")
    route_id = request.args.get("route_schedule_id")
    crew_id = request.args.get("crew_id")
    recs = [r for r in db.VISITS.values()
            if (plan_id is None or r["service_plan_id"] == plan_id)
            and (contract_id is None or r["service_contract_id"] == contract_id)
            and (route_id is None or r["route_schedule_id"] == route_id)
            and (crew_id is None or r["crew_id"] == crew_id)]
    return paginate_and_respond(recs)


@app.route("/v1/visits/<visit_id>/start", methods=["POST"])
def start_visit(visit_id):
    _uid, role = get_user_context()
    require_role(role, ["CrewLead"])
    visit = get_or_404(db.VISITS, visit_id, errors.ERR_VISIT_NOT_FOUND)
    if visit["execution_status"] != "SCHEDULED":
        errors.fail(errors.ERR_VISIT_NOT_SCHEDULED, "Visit is not SCHEDULED")
    contract = db.CONTRACTS.get(visit["service_contract_id"])
    if contract is None or contract["status"] != "ACTIVE":
        errors.fail(errors.ERR_CONTRACT_NOT_ACTIVE, "Contract is not ACTIVE")
    route = db.ROUTES.get(visit["route_schedule_id"])
    if route is None or route["status"] != "LOCKED":
        errors.fail(errors.ERR_ROUTE_NOT_LOCKED, "Route is not LOCKED")
    visit["execution_status"] = "IN_PROGRESS"
    db.touch(visit)
    return response.object_response(db.public(visit), 200)


@app.route("/v1/visits/<visit_id>/complete", methods=["POST"])
def complete_visit(visit_id):
    _uid, role = get_user_context()
    require_role(role, ["CrewLead"])
    visit = get_or_404(db.VISITS, visit_id, errors.ERR_VISIT_NOT_FOUND)
    if visit["execution_status"] != "IN_PROGRESS":
        errors.fail(errors.ERR_VISIT_NOT_IN_PROGRESS, "Visit is not IN_PROGRESS")
    body = get_json_body()
    actual = body.get("actual_labor_minutes")
    if not isinstance(actual, int) or isinstance(actual, bool) or actual <= 0:
        errors.fail(errors.ERR_INVALID_ACTUAL_MINUTES, "actual_labor_minutes must be > 0")
    visit["actual_labor_minutes"] = actual
    plan = db.PLANS[visit["service_plan_id"]]
    site = db.SITES[plan["site_id"]]
    crew = db.CREWS[visit["crew_id"]]
    visit["final_charge_cents"] = services.visit_final_charge(visit, plan, site, crew)
    visit["execution_status"] = "COMPLETED"
    db.touch(visit)
    # Cross-entity: RESERVED reservations for this visit -> CONSUMED (usage retained).
    for r in db.RESERVATIONS.values():
        if r["service_visit_id"] == visit_id and r["status"] == "RESERVED":
            r["status"] = "CONSUMED"
            db.touch(r)
    contract = db.CONTRACTS.get(visit["service_contract_id"])
    if contract is not None:
        services.reconcile_committed(contract)
    return response.object_response(db.public(visit), 200)


@app.route("/v1/visits/<visit_id>/cancel", methods=["POST"])
def cancel_visit(visit_id):
    _uid, role = get_user_context()
    require_role(role, ["CrewLead", "AccountManager"])
    visit = get_or_404(db.VISITS, visit_id, errors.ERR_VISIT_NOT_FOUND)
    if visit["execution_status"] != "SCHEDULED":
        errors.fail(errors.ERR_VISIT_NOT_CANCELLABLE, "Visit is not SCHEDULED")
    services.cancel_visit_cascade(visit)
    contract = db.CONTRACTS.get(visit["service_contract_id"])
    if contract is not None:
        services.reconcile_committed(contract)
    return response.object_response(db.public(visit), 200)


@app.route("/v1/visits/<visit_id>/write-off", methods=["POST"])
def write_off_visit(visit_id):
    _uid, role = get_user_context()
    require_role(role, ["AccountManager"])
    visit = get_or_404(db.VISITS, visit_id, errors.ERR_VISIT_NOT_FOUND)
    visit["billing_status"] = "WRITTEN_OFF"
    db.touch(visit)
    return response.object_response(db.public(visit), 200)


# =========================================================================
# Add-ons
# =========================================================================
@app.route("/v1/addons", methods=["POST"])
def create_addon():
    _uid, role = get_user_context()
    require_role(role, ["AccountManager", "CrewLead"])
    body = get_json_body()
    service_visit_id = require_str(body, "service_visit_id")
    addon_type = require_enum(body, "addon_type",
                              {"IRRIGATION_TUNEUP", "MULCH_INSTALL", "AERATION_PASS"})
    quantity = require_int(body, "quantity", gt=0)
    unit_price_cents = require_int(body, "unit_price_cents", gt=0)
    get_or_404(db.VISITS, service_visit_id, errors.ERR_VISIT_NOT_FOUND)
    rec = db.make_common({
        "service_visit_id": service_visit_id,
        "addon_type": addon_type,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
        "addon_charge_cents": 0,
        "status": "REQUESTED",
    })
    db.ADDONS[rec["id"]] = rec
    return response.object_response(db.public(rec), 201)


@app.route("/v1/addons/<addon_id>", methods=["GET"])
def get_addon(addon_id):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    rec = get_or_404(db.ADDONS, addon_id, errors.ERR_ADDON_NOT_FOUND)
    return response.object_response(db.public(rec), 200)


@app.route("/v1/addons", methods=["GET"])
def list_addons():
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    visit_id = request.args.get("service_visit_id")
    recs = [r for r in db.ADDONS.values()
            if visit_id is None or r["service_visit_id"] == visit_id]
    return paginate_and_respond(recs)


@app.route("/v1/addons/<addon_id>/approve", methods=["POST"])
def approve_addon(addon_id):
    _uid, role = get_user_context()
    require_role(role, ["AccountManager"])
    addon = get_or_404(db.ADDONS, addon_id, errors.ERR_ADDON_NOT_FOUND)
    if addon["status"] != "REQUESTED":
        errors.fail(errors.ERR_ADDON_NOT_REQUESTED, "Add-on is not REQUESTED")
    visit = db.VISITS.get(addon["service_visit_id"])
    if visit is None or visit["execution_status"] not in ("SCHEDULED", "IN_PROGRESS"):
        errors.fail(errors.ERR_VISIT_NOT_OPEN_FOR_ADDON, "Visit is not open for add-on")
    addon["status"] = "APPROVED"
    addon["addon_charge_cents"] = services.addon_charge(addon["quantity"], addon["unit_price_cents"])
    db.touch(addon)
    # Cascade: recompute visit estimate, then contract committed.
    services.recompute_visit_estimate(visit)
    db.touch(visit)
    contract = db.CONTRACTS.get(visit["service_contract_id"])
    if contract is not None:
        services.reconcile_committed(contract)
    return response.object_response(db.public(addon), 200)


@app.route("/v1/addons/<addon_id>/reject", methods=["POST"])
def reject_addon(addon_id):
    _uid, role = get_user_context()
    require_role(role, ["AccountManager"])
    addon = get_or_404(db.ADDONS, addon_id, errors.ERR_ADDON_NOT_FOUND)
    if addon["status"] != "REQUESTED":
        errors.fail(errors.ERR_ADDON_NOT_REQUESTED, "Add-on is not REQUESTED")
    addon["status"] = "REJECTED"
    addon["addon_charge_cents"] = 0
    db.touch(addon)
    return response.object_response(db.public(addon), 200)


# =========================================================================
# Equipment
# =========================================================================
@app.route("/v1/equipment", methods=["POST"])
def create_equipment():
    _uid, role = get_user_context()
    require_role(role, ["AccountManager"])
    body = get_json_body()
    service_account_id = require_str(body, "service_account_id")
    name = require_str(body, "name")
    hourly_usage_cost_cents = require_int(body, "hourly_usage_cost_cents", gt=0)
    service_interval_hours = require_int(body, "service_interval_hours", gt=0)
    get_or_404(db.ACCOUNTS, service_account_id, errors.ERR_ACCOUNT_NOT_FOUND)
    rec = db.make_common({
        "service_account_id": service_account_id,
        "name": name,
        "hourly_usage_cost_cents": hourly_usage_cost_cents,
        "service_interval_hours": service_interval_hours,
        "accumulated_usage_minutes": 0,
        "status": "AVAILABLE",
    })
    db.EQUIPMENT[rec["id"]] = rec
    return response.object_response(db.public(rec), 201)


@app.route("/v1/equipment/<asset_id>", methods=["GET"])
def get_equipment(asset_id):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    rec = get_or_404(db.EQUIPMENT, asset_id, errors.ERR_EQUIPMENT_NOT_FOUND)
    return response.object_response(db.public(rec), 200)


@app.route("/v1/equipment", methods=["GET"])
def list_equipment():
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    sid = request.args.get("service_account_id")
    recs = [r for r in db.EQUIPMENT.values()
            if sid is None or r["service_account_id"] == sid]
    return paginate_and_respond(recs)


@app.route("/v1/equipment/<asset_id>/maintenance-reset", methods=["POST"])
def maintenance_reset(asset_id):
    _uid, role = get_user_context()
    require_role(role, ["AccountManager"])
    asset = get_or_404(db.EQUIPMENT, asset_id, errors.ERR_EQUIPMENT_NOT_FOUND)
    asset["accumulated_usage_minutes"] = 0
    asset["status"] = "AVAILABLE"
    db.touch(asset)
    return response.object_response(db.public(asset), 200)


@app.route("/v1/equipment/<asset_id>/decommission", methods=["POST"])
def decommission(asset_id):
    _uid, role = get_user_context()
    require_role(role, ["AccountManager"])
    asset = get_or_404(db.EQUIPMENT, asset_id, errors.ERR_EQUIPMENT_NOT_FOUND)
    asset["status"] = "OUT_OF_SERVICE"
    db.touch(asset)
    return response.object_response(db.public(asset), 200)


# =========================================================================
# Reservations
# =========================================================================
@app.route("/v1/reservations", methods=["POST"])
def create_reservation():
    _uid, role = get_user_context()
    require_role(role, ["CrewLead", "AccountManager"])
    body = get_json_body()
    equipment_asset_id = require_str(body, "equipment_asset_id")
    service_visit_id = require_str(body, "service_visit_id")
    window_start_minute = require_int(body, "window_start_minute", ge=0)
    window_end_minute = require_int(body, "window_end_minute")
    if not (window_end_minute > window_start_minute):
        errors.fail(errors.ERR_INVALID_REQUEST, "window_end_minute must be > window_start_minute")

    asset = get_or_404(db.EQUIPMENT, equipment_asset_id, errors.ERR_EQUIPMENT_NOT_FOUND)
    visit = get_or_404(db.VISITS, service_visit_id, errors.ERR_VISIT_NOT_FOUND)

    # State guard (priority 7): asset must be AVAILABLE.
    if asset["status"] != "AVAILABLE":
        errors.fail(errors.ERR_EQUIPMENT_OUT_OF_SERVICE, "Asset is OUT_OF_SERVICE")

    # Cross-account integrity (priority 8): asset and visit share one account.
    # The visit's account is derived from its parent contract.
    visit_contract = db.CONTRACTS.get(visit["service_contract_id"])
    visit_account = visit_contract["service_account_id"] if visit_contract else None
    if asset["service_account_id"] != visit_account:
        errors.fail(errors.ERR_CROSS_ACCOUNT_REFERENCE, "Cross-account reference")

    reserved_minutes = window_end_minute - window_start_minute

    # Temporal (priority 10): closed-interval overlap with non-RELEASED reservations.
    for other in db.RESERVATIONS.values():
        if other["equipment_asset_id"] != equipment_asset_id:
            continue
        if other["status"] == "RELEASED":
            continue
        o_start = other["window_start_minute"]
        o_end = other["window_end_minute"]
        # Closed-interval overlap: collide iff start <= o_end and o_start <= end.
        if window_start_minute <= o_end and o_start <= window_end_minute:
            errors.fail(errors.ERR_EQUIPMENT_DOUBLE_BOOKED, "Reservation window overlaps")

    # Maintenance interval (priority 12): strict-excess rejection.
    if asset["accumulated_usage_minutes"] + reserved_minutes > asset["service_interval_hours"] * 60:
        errors.fail(errors.ERR_SERVICE_INTERVAL_EXCEEDED, "Asset due for maintenance")

    usage_cost = services.equipment_usage_cost(reserved_minutes, asset["hourly_usage_cost_cents"])
    rec = db.make_common({
        "equipment_asset_id": equipment_asset_id,
        "service_visit_id": service_visit_id,
        "window_start_minute": window_start_minute,
        "window_end_minute": window_end_minute,
        "reserved_minutes": reserved_minutes,
        "usage_cost_cents": usage_cost,
        "status": "RESERVED",
    })
    db.RESERVATIONS[rec["id"]] = rec
    asset["accumulated_usage_minutes"] += reserved_minutes
    db.touch(asset)
    return response.object_response(db.public(rec), 201)


@app.route("/v1/reservations/<reservation_id>", methods=["GET"])
def get_reservation(reservation_id):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    rec = get_or_404(db.RESERVATIONS, reservation_id, errors.ERR_RESERVATION_NOT_FOUND)
    return response.object_response(db.public(rec), 200)


@app.route("/v1/reservations", methods=["GET"])
def list_reservations():
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    asset_id = request.args.get("equipment_asset_id")
    visit_id = request.args.get("service_visit_id")
    recs = [r for r in db.RESERVATIONS.values()
            if (asset_id is None or r["equipment_asset_id"] == asset_id)
            and (visit_id is None or r["service_visit_id"] == visit_id)]
    return paginate_and_respond(recs)


@app.route("/v1/reservations/<reservation_id>/release", methods=["POST"])
def release_reservation(reservation_id):
    _uid, role = get_user_context()
    require_role(role, ["CrewLead", "AccountManager"])
    rec = get_or_404(db.RESERVATIONS, reservation_id, errors.ERR_RESERVATION_NOT_FOUND)
    if rec["status"] != "RESERVED":
        errors.fail(errors.ERR_RESERVATION_NOT_RESERVED, "Reservation is not RESERVED")
    rec["status"] = "RELEASED"
    db.touch(rec)
    asset = db.EQUIPMENT.get(rec["equipment_asset_id"])
    if asset is not None:
        asset["accumulated_usage_minutes"] -= rec["reserved_minutes"]
        db.touch(asset)
    return response.object_response(db.public(rec), 200)


# =========================================================================
# Storm events
# =========================================================================
@app.route("/v1/storm-events", methods=["POST"])
def create_storm_event():
    _uid, role = get_user_context()
    require_role(role, ["DispatchOperator", "AccountManager"])
    body = get_json_body()
    site_id = require_str(body, "site_id")
    snowfall_inches = require_int(body, "snowfall_inches", ge=0)
    response_deadline_minute = require_int(body, "response_deadline_minute", ge=0)
    site = get_or_404(db.SITES, site_id, errors.ERR_SITE_NOT_FOUND)
    rec = db.make_common({
        "site_id": site_id,
        "service_account_id": site["service_account_id"],  # copied from site
        "assigned_crew_id": None,
        "snowfall_inches": snowfall_inches,
        "response_deadline_minute": response_deadline_minute,
        "dispatch_charge_cents": 0,
        "status": "REPORTED",
    })
    db.STORM_EVENTS[rec["id"]] = rec
    return response.object_response(db.public(rec), 201)


@app.route("/v1/storm-events/<event_id>", methods=["GET"])
def get_storm_event(event_id):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    rec = get_or_404(db.STORM_EVENTS, event_id, errors.ERR_EVENT_NOT_FOUND)
    return response.object_response(db.public(rec), 200)


@app.route("/v1/storm-events", methods=["GET"])
def list_storm_events():
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    site_id = request.args.get("site_id")
    sid = request.args.get("service_account_id")
    crew_id = request.args.get("assigned_crew_id")
    recs = [r for r in db.STORM_EVENTS.values()
            if (site_id is None or r["site_id"] == site_id)
            and (sid is None or r["service_account_id"] == sid)
            and (crew_id is None or r["assigned_crew_id"] == crew_id)]
    return paginate_and_respond(recs)


@app.route("/v1/storm-events/<event_id>/dispatch", methods=["POST"])
def dispatch_storm_event(event_id):
    _uid, role = get_user_context()
    require_role(role, ["DispatchOperator"])
    event = get_or_404(db.STORM_EVENTS, event_id, errors.ERR_EVENT_NOT_FOUND)
    if event["status"] != "REPORTED":
        errors.fail(errors.ERR_EVENT_NOT_REPORTED, "Event is not REPORTED")
    crew = services.storm_crew_selector(event["service_account_id"])
    if crew is None:
        errors.fail(errors.ERR_NO_CERTIFIED_CREW, "No certified crew available")
    site = db.SITES[event["site_id"]]
    event["assigned_crew_id"] = crew["id"]
    event["dispatch_charge_cents"] = services.storm_dispatch_charge(
        event["snowfall_inches"], site["snow_zone"])
    event["status"] = "DISPATCHED"
    db.touch(event)
    return response.object_response(db.public(event), 200)


@app.route("/v1/storm-events/<event_id>/abandon", methods=["POST"])
def abandon_storm_event(event_id):
    _uid, role = get_user_context()
    require_role(role, ["DispatchOperator"])
    event = get_or_404(db.STORM_EVENTS, event_id, errors.ERR_EVENT_NOT_FOUND)
    if event["status"] != "DISPATCHED":
        errors.fail(errors.ERR_EVENT_NOT_DISPATCHED, "Event is not DISPATCHED")
    event["assigned_crew_id"] = None
    event["status"] = "REPORTED"  # dispatch_charge_cents retained
    db.touch(event)
    return response.object_response(db.public(event), 200)


@app.route("/v1/storm-events/<event_id>/resolve", methods=["POST"])
def resolve_storm_event(event_id):
    _uid, role = get_user_context()
    require_role(role, ["DispatchOperator"])
    event = get_or_404(db.STORM_EVENTS, event_id, errors.ERR_EVENT_NOT_FOUND)
    if event["status"] != "DISPATCHED":
        errors.fail(errors.ERR_EVENT_NOT_DISPATCHED, "Event is not DISPATCHED")
    event["status"] = "RESOLVED"
    db.touch(event)
    return response.object_response(db.public(event), 200)


@app.route("/v1/storm-events/<event_id>/stand-down", methods=["POST"])
def stand_down_storm_event(event_id):
    _uid, role = get_user_context()
    require_role(role, ["DispatchOperator"])
    event = get_or_404(db.STORM_EVENTS, event_id, errors.ERR_EVENT_NOT_FOUND)
    if event["status"] != "REPORTED":
        errors.fail(errors.ERR_EVENT_NOT_REPORTED, "Event is not REPORTED")
    event["status"] = "STOOD_DOWN"
    event["dispatch_charge_cents"] = 0
    db.touch(event)
    return response.object_response(db.public(event), 200)


# =========================================================================
# Inspections
# =========================================================================
@app.route("/v1/inspections", methods=["POST"])
def create_inspection():
    uid, role = get_user_context()
    require_role(role, ["QualityInspector"])
    body = get_json_body()
    service_visit_id = require_str(body, "service_visit_id")
    get_or_404(db.VISITS, service_visit_id, errors.ERR_VISIT_NOT_FOUND)
    rec = db.make_common({
        "service_visit_id": service_visit_id,
        "inspector_user_id": uid,  # opaque X-User-ID of the opening inspector
        "score": 0,
        "rework_count": 0,
        "status": "PENDING",
    })
    db.INSPECTIONS[rec["id"]] = rec
    return response.object_response(db.public(rec), 201)


@app.route("/v1/inspections/<inspection_id>", methods=["GET"])
def get_inspection(inspection_id):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    rec = get_or_404(db.INSPECTIONS, inspection_id, errors.ERR_INSPECTION_NOT_FOUND)
    return response.object_response(db.public(rec), 200)


@app.route("/v1/inspections", methods=["GET"])
def list_inspections():
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    visit_id = request.args.get("service_visit_id")
    recs = [r for r in db.INSPECTIONS.values()
            if visit_id is None or r["service_visit_id"] == visit_id]
    return paginate_and_respond(recs)


@app.route("/v1/inspections/<inspection_id>/grade", methods=["POST"])
def grade_inspection(inspection_id):
    _uid, role = get_user_context()
    require_role(role, ["QualityInspector"])
    inspection = get_or_404(db.INSPECTIONS, inspection_id, errors.ERR_INSPECTION_NOT_FOUND)
    if inspection["status"] != "PENDING":
        errors.fail(errors.ERR_INSPECTION_NOT_PENDING, "Inspection is not PENDING")
    visit = db.VISITS.get(inspection["service_visit_id"])
    if visit is None or visit["execution_status"] != "COMPLETED":
        errors.fail(errors.ERR_VISIT_NOT_COMPLETED, "Parent visit is not COMPLETED")
    body = get_json_body()
    score = require_int(body, "score", ge=0)
    inspection["score"] = score
    # Route by score and rework_count (PRD 3.9).
    if score >= services.PASS_THRESHOLD:
        inspection["status"] = "PASSED"
    elif score >= services.REWORK_FLOOR and inspection["rework_count"] < services.MAX_REWORK:
        inspection["status"] = "REWORK_REQUIRED"
    else:
        inspection["status"] = "FAILED"
        # Cross-entity: write off the visit charge if still UNBILLED.
        if visit["billing_status"] == "UNBILLED":
            visit["billing_status"] = "WRITTEN_OFF"
            db.touch(visit)
    db.touch(inspection)
    return response.object_response(db.public(inspection), 200)


@app.route("/v1/inspections/<inspection_id>/reopen", methods=["POST"])
def reopen_inspection(inspection_id):
    _uid, role = get_user_context()
    require_role(role, ["QualityInspector"])
    inspection = get_or_404(db.INSPECTIONS, inspection_id, errors.ERR_INSPECTION_NOT_FOUND)
    if inspection["status"] != "REWORK_REQUIRED":
        errors.fail(errors.ERR_INSPECTION_NOT_REWORK, "Inspection is not REWORK_REQUIRED")
    inspection["rework_count"] += 1
    inspection["status"] = "PENDING"
    db.touch(inspection)
    return response.object_response(db.public(inspection), 200)


# =========================================================================
# Invoices
# =========================================================================
@app.route("/v1/invoices", methods=["POST"])
def create_invoice():
    _uid, role = get_user_context()
    require_role(role, ["AccountManager"])
    body = get_json_body()
    service_contract_id = require_str(body, "service_contract_id")
    period_label = require_str(body, "period_label")
    contract = get_or_404(db.CONTRACTS, service_contract_id, errors.ERR_CONTRACT_NOT_FOUND)
    # period_label unique among non-VOID invoices of this contract.
    for inv in db.INVOICES.values():
        if (inv["service_contract_id"] == service_contract_id
                and inv["status"] != "VOID"
                and inv["period_label"] == period_label):
            errors.fail(errors.ERR_DUPLICATE_PERIOD_LABEL, "Duplicate period label")
    swept_ids, line_item_count, subtotal_cents = services.invoice_sweep(service_contract_id)
    tax_cents, total_cents = services.invoice_tax_total(subtotal_cents)
    rec = db.make_common({
        "service_contract_id": service_contract_id,
        "period_label": period_label,
        "subtotal_cents": subtotal_cents,
        "tax_cents": tax_cents,
        "total_cents": total_cents,
        "line_item_count": line_item_count,
        "status": "DRAFT",
        "_swept_visit_ids": swept_ids,  # fixed at draft creation; not re-run on issue
    })
    db.INVOICES[rec["id"]] = rec
    return response.object_response(db.public(rec), 201)


@app.route("/v1/invoices/<invoice_id>", methods=["GET"])
def get_invoice(invoice_id):
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    rec = get_or_404(db.INVOICES, invoice_id, errors.ERR_INVOICE_NOT_FOUND)
    return response.object_response(db.public(rec), 200)


@app.route("/v1/invoices", methods=["GET"])
def list_invoices():
    _uid, role = get_user_context()
    require_role(role, ALL_ROLES)
    cid = request.args.get("service_contract_id")
    recs = [r for r in db.INVOICES.values()
            if cid is None or r["service_contract_id"] == cid]
    return paginate_and_respond(recs)


@app.route("/v1/invoices/<invoice_id>/issue", methods=["POST"])
def issue_invoice(invoice_id):
    _uid, role = get_user_context()
    require_role(role, ["AccountManager"])
    invoice = get_or_404(db.INVOICES, invoice_id, errors.ERR_INVOICE_NOT_FOUND)
    body = get_json_body()
    expected_version = require_int(body, "expected_service_contract_version", ge=0)
    # Order per PRD 3.10: DRAFT, then OCC, then not-terminated, then non-empty, then budget.
    if invoice["status"] != "DRAFT":
        errors.fail(errors.ERR_INVOICE_NOT_DRAFT, "Invoice is not DRAFT")
    contract = db.CONTRACTS.get(invoice["service_contract_id"])
    if expected_version != contract["version"]:
        errors.fail(errors.ERR_STALE_CONTRACT_VERSION, "Stale contract version")
    if contract["status"] == "TERMINATED":
        errors.fail(errors.ERR_CONTRACT_TERMINATED, "Contract is TERMINATED")
    if invoice["line_item_count"] <= 0:
        errors.fail(errors.ERR_EMPTY_INVOICE, "Invoice has no line items")
    # Budget: resulting billed_cents must not strictly exceed annual_budget_cents.
    if contract["billed_cents"] + invoice["total_cents"] > contract["annual_budget_cents"]:
        errors.fail(errors.ERR_BUDGET_EXCEEDED, "Issuing would exceed annual budget")

    invoice["status"] = "ISSUED"
    db.touch(invoice)
    # Cross-entity: swept visits still UNBILLED -> INVOICED.
    for vid in invoice["_swept_visit_ids"]:
        v = db.VISITS.get(vid)
        if v is not None and v["billing_status"] == "UNBILLED":
            v["billing_status"] = "INVOICED"
            db.touch(v)
    # Recompute billed_cents and bump contract version.
    services.recompute_billed(contract)
    return response.object_response(db.public(invoice), 200)


@app.route("/v1/invoices/<invoice_id>/pay", methods=["POST"])
def pay_invoice(invoice_id):
    _uid, role = get_user_context()
    require_role(role, ["AccountManager"])
    invoice = get_or_404(db.INVOICES, invoice_id, errors.ERR_INVOICE_NOT_FOUND)
    if invoice["status"] != "ISSUED":
        errors.fail(errors.ERR_INVOICE_NOT_ISSUED, "Invoice is not ISSUED")
    invoice["status"] = "PAID"
    db.touch(invoice)
    contract = db.CONTRACTS.get(invoice["service_contract_id"])
    if contract is not None:
        services.recompute_billed(contract)
    return response.object_response(db.public(invoice), 200)


@app.route("/v1/invoices/<invoice_id>/void", methods=["POST"])
def void_invoice(invoice_id):
    _uid, role = get_user_context()
    require_role(role, ["AccountManager"])
    invoice = get_or_404(db.INVOICES, invoice_id, errors.ERR_INVOICE_NOT_FOUND)
    if invoice["status"] != "DRAFT":
        errors.fail(errors.ERR_INVOICE_NOT_VOIDABLE, "Invoice is not DRAFT")
    invoice["status"] = "VOID"
    db.touch(invoice)
    return response.object_response(db.public(invoice), 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Serve via waitress: the werkzeug dev server intermittently drops kept-alive
    # connections that the test client (a requests.Session) tries to reuse,
    # surfacing as BadStatusLine / ConnectionAborted races under the rapid
    # per-test-server reboot + connection-reuse pattern. Waitress handles HTTP
    # keep-alive correctly. Fall back to the dev server only if waitress is absent.
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8, channel_timeout=120)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
