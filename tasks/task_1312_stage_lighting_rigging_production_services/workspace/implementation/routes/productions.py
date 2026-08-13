"""Production endpoints: booking, lifecycle spine, and nested collections."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_RESOURCE_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_VENUE_DOUBLE_BOOKED,
    ERR_PRODUCTION_NOT_READY,
    ERR_TOO_EARLY,
    ERR_OPEN_PULL_LIST,
    ERR_OPEN_LOAD_SCHEDULE,
    ERR_ASSET_NOT_AVAILABLE,
    ERR_DOCK_DOOR_INVALID,
    ERR_DUPLICATE_DAMAGE_REPORT,
    ERR_SETTLEMENT_EXISTS,
)
from middleware import require_roles
from response import success_object, success_list
from services import calculations as calc
from services.domain import (
    cancel_cascade,
    check_declared,
    check_terminal,
    check_transition_owner,
    closed_windows_intersect,
    parse_to,
)
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_iso8601,
    parse_pagination,
    require_bool,
    require_enum,
    require_int,
    require_string,
    require_ts,
    serialize,
    serialize_list,
    sort_by_created_at,
)

bp = Blueprint("productions", __name__)

PRODUCTION_STATES = {
    "DRAFT",
    "PLANNING",
    "READY_FOR_LOADIN",
    "LOAD_IN",
    "SHOW_READY",
    "SHOW_COMPLETE",
    "LOAD_OUT",
    "CLOSED",
    "SETTLED",
    "CANCELLED",
}
PRODUCTION_TERMINAL = {"SETTLED", "CANCELLED"}
PRODUCTION_TO_OWNERS = {
    "PLANNING": {"ProductionManager"},
    "READY_FOR_LOADIN": {"ProductionManager"},
    "LOAD_IN": {"ProductionManager"},
    "SHOW_COMPLETE": {"ProductionManager"},
    "LOAD_OUT": {"ProductionManager"},
    "CLOSED": {"ProductionManager"},
    "CANCELLED": {"ProductionManager"},
    # SHOW_READY and SETTLED are system-fired; no role owns them.
}
PRODUCTION_DECLARED = {
    "DRAFT": {"PLANNING", "CANCELLED"},
    "PLANNING": {"READY_FOR_LOADIN", "CANCELLED"},
    "READY_FOR_LOADIN": {"LOAD_IN", "CANCELLED"},
    "LOAD_IN": set(),
    "SHOW_READY": {"SHOW_COMPLETE"},
    "SHOW_COMPLETE": {"LOAD_OUT"},
    "LOAD_OUT": {"CLOSED"},
    "CLOSED": set(),
}


def get_production_or_404(production_id: str) -> dict:
    production = db.productions.get(production_id)
    if production is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Production id does not exist")
    return production


@bp.route("/productions", methods=["POST"])
@require_roles("ProductionManager")
def create_production(_user_id: str, _role: str):
    body = get_json_body()
    venue_id = require_string(body, "venue_id")
    name = require_string(body, "name")
    load_in_at = require_ts(body, "load_in_at")
    show_at = require_ts(body, "show_at")
    load_out_at = require_ts(body, "load_out_at")

    load_in_dt = parse_iso8601(load_in_at, "load_in_at")
    show_dt = parse_iso8601(show_at, "show_at")
    load_out_dt = parse_iso8601(load_out_at, "load_out_at")
    if not (load_in_dt < show_dt < load_out_dt):
        raise_err(ERR_INVALID_REQUEST, "require load_in_at < show_at < load_out_at")

    venue = db.venues.get(venue_id)
    if venue is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Venue id does not exist")

    # Closed-interval venue occupancy exclusivity (non-CANCELLED productions).
    for other in db.productions.values():
        if other["venue_id"] != venue_id or other["status"] == "CANCELLED":
            continue
        o_in = parse_iso8601(other["load_in_at"], "load_in_at")
        o_out = parse_iso8601(other["load_out_at"], "load_out_at")
        if closed_windows_intersect(load_in_dt, load_out_dt, o_in, o_out):
            raise_err(ERR_VENUE_DOUBLE_BOOKED, "Venue occupancy window intersects another production")

    production = {
        "venue_id": venue_id,
        "name": name,
        "load_in_at": load_in_at,
        "show_at": show_at,
        "load_out_at": load_out_at,
        "status": "DRAFT",
        "posture": "BLOCKED",
    }
    db.stamp_new(production)
    db.productions[production["id"]] = production
    return success_object(serialize(production), 201)


@bp.route("/productions", methods=["GET"])
@require_roles("Any")
def list_productions(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.productions.values()))
    items = apply_filters(items, ["venue_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/productions/<production_id>", methods=["GET"])
@require_roles("Any")
def get_production(production_id: str, _user_id: str, _role: str):
    return success_object(serialize(get_production_or_404(production_id)))


@bp.route("/productions/<production_id>/transition", methods=["POST"])
@require_roles("ProductionManager")
def transition_production(production_id: str, _user_id: str, _role: str):
    body = get_json_body()
    to = parse_to(body, PRODUCTION_STATES)
    check_transition_owner(to, PRODUCTION_TO_OWNERS, _role)
    production = get_production_or_404(production_id)
    check_terminal(production, PRODUCTION_TERMINAL, to, PRODUCTION_DECLARED)
    check_declared(production, to, PRODUCTION_DECLARED)

    clock = db.clock_dt()

    if to == "READY_FOR_LOADIN":
        calc.refresh_posture(production)
        if production["posture"] != "READY":
            raise_err(ERR_PRODUCTION_NOT_READY, "Production posture is not READY")
    elif to == "LOAD_IN":
        if clock < parse_iso8601(production["load_in_at"], "load_in_at"):
            raise_err(ERR_TOO_EARLY, "Logical clock has not reached load_in_at")
    elif to == "SHOW_COMPLETE":
        if clock < parse_iso8601(production["show_at"], "show_at"):
            raise_err(ERR_TOO_EARLY, "Logical clock has not reached show_at")
    elif to == "CLOSED":
        for entry in db.pull_list_entries.values():
            if entry["production_id"] == production["id"] and entry["status"] not in (
                "RETURNED",
                "DAMAGED",
                "LOST",
                "CANCELLED",
            ):
                raise_err(ERR_OPEN_PULL_LIST, "Pull list entries still open")
        for schedule in db.load_schedules.values():
            if schedule["production_id"] == production["id"] and schedule["status"] not in (
                "COMPLETE",
                "CANCELLED",
            ):
                raise_err(ERR_OPEN_LOAD_SCHEDULE, "Load schedules still open")
    elif to == "CANCELLED":
        cancel_cascade(production)

    production["status"] = to
    db.touch(production)
    return success_object(serialize(production))


# ---------------------------------------------------------------------------
# Nested: plots
# ---------------------------------------------------------------------------

@bp.route("/productions/<production_id>/plots", methods=["POST"])
@require_roles("ProductionManager")
def create_plot(production_id: str, _user_id: str, _role: str):
    body = get_json_body()
    title = require_string(body, "title")
    expected_version = require_int(body, "expected_production_version")

    production = get_production_or_404(production_id)
    if production["status"] != "PLANNING":
        raise_err(ERR_INVALID_STATE, "Plots may be created only while production is PLANNING")
    if expected_version != production["version"]:
        raise_err(ERR_STALE_VERSION, "expected_production_version does not match Production.version")

    revision = 1 + max(
        [p["revision"] for p in db.plots.values() if p["production_id"] == production_id],
        default=0,
    )
    plot = {
        "production_id": production_id,
        "title": title,
        "revision": revision,
        "status": "DRAFT",
        "total_factored_load_kg": 0.0,
        "rejection_reason": None,
        "approved_by_user_id": None,
        "approved_at": None,
    }
    db.stamp_new(plot)
    db.plots[plot["id"]] = plot
    # Creating a plot is itself a mutation of the production.
    db.touch(production)
    calc.refresh_posture(production)
    return success_object(serialize(plot), 201)


@bp.route("/productions/<production_id>/plots", methods=["GET"])
@require_roles("Any")
def list_production_plots(production_id: str, _user_id: str, _role: str):
    get_production_or_404(production_id)
    limit, offset = parse_pagination()
    items = [p for p in db.plots.values() if p["production_id"] == production_id]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


# ---------------------------------------------------------------------------
# Nested: pull list entries
# ---------------------------------------------------------------------------

@bp.route("/productions/<production_id>/pull-list-entries", methods=["POST"])
@require_roles("WarehouseChief")
def create_pull_list_entry(production_id: str, _user_id: str, _role: str):
    body = get_json_body()
    asset_id = require_string(body, "asset_id")

    production = get_production_or_404(production_id)
    asset = db.assets.get(asset_id)
    if asset is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "EquipmentAsset id does not exist")
    if production["status"] != "PLANNING":
        raise_err(ERR_INVALID_STATE, "Pull list entries may be created only while production is PLANNING")
    if asset["status"] in ("RETIRED", "LOST", "DAMAGED"):
        raise_err(ERR_ASSET_NOT_AVAILABLE, "Asset is RETIRED, LOST, or DAMAGED")

    entry = {
        "production_id": production_id,
        "asset_id": asset_id,
        "status": "REQUESTED",
        "prep_window_start": None,
        "prep_window_end": None,
        "load_schedule_id": None,
        "out_at": None,
        "returned_at": None,
        "rental_charge_cents": None,
    }
    db.stamp_new(entry)
    db.pull_list_entries[entry["id"]] = entry
    calc.refresh_posture(production)
    return success_object(serialize(entry), 201)


@bp.route("/productions/<production_id>/pull-list-entries", methods=["GET"])
@require_roles("Any")
def list_production_pull_list(production_id: str, _user_id: str, _role: str):
    get_production_or_404(production_id)
    limit, offset = parse_pagination()
    items = [e for e in db.pull_list_entries.values() if e["production_id"] == production_id]
    items = apply_filters(items, ["status"])
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


# ---------------------------------------------------------------------------
# Nested: crew calls
# ---------------------------------------------------------------------------

CREW_CALL_DEPARTMENTS = {"LIGHTING", "RIGGING", "STAGEHANDS"}


@bp.route("/productions/<production_id>/crew-calls", methods=["POST"])
@require_roles("ProductionManager")
def create_crew_call(production_id: str, _user_id: str, _role: str):
    body = get_json_body()
    department = require_enum(body, "department", CREW_CALL_DEPARTMENTS)
    call_start = require_ts(body, "call_start")
    call_end = require_ts(body, "call_end")
    headcount = require_int(body, "required_headcount", minimum=1)

    if not (parse_iso8601(call_end, "call_end") > parse_iso8601(call_start, "call_start")):
        raise_err(ERR_INVALID_REQUEST, "call_end must be strictly after call_start")

    production = get_production_or_404(production_id)
    if production["status"] != "PLANNING":
        raise_err(ERR_INVALID_STATE, "Crew calls may be created only while production is PLANNING")

    call = {
        "production_id": production_id,
        "department": department,
        "call_start": call_start,
        "call_end": call_end,
        "required_headcount": headcount,
        "status": "DRAFT",
        "labor_cost_cents": None,
    }
    db.stamp_new(call)
    db.crew_calls[call["id"]] = call
    calc.refresh_posture(production)
    return success_object(serialize(call), 201)


@bp.route("/productions/<production_id>/crew-calls", methods=["GET"])
@require_roles("Any")
def list_production_crew_calls(production_id: str, _user_id: str, _role: str):
    get_production_or_404(production_id)
    limit, offset = parse_pagination()
    items = [c for c in db.crew_calls.values() if c["production_id"] == production_id]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


# ---------------------------------------------------------------------------
# Nested: power plans
# ---------------------------------------------------------------------------

@bp.route("/productions/<production_id>/power-plans", methods=["POST"])
@require_roles("ProductionManager")
def create_power_plan(production_id: str, _user_id: str, _role: str):
    body = get_json_body()
    l1 = require_int(body, "phase_l1_watts", minimum=0)
    l2 = require_int(body, "phase_l2_watts", minimum=0)
    l3 = require_int(body, "phase_l3_watts", minimum=0)
    feeder = require_int(body, "feeder_length_m", minimum=0)
    generator_required = require_bool(body, "generator_required")

    production = get_production_or_404(production_id)
    if production["status"] != "PLANNING":
        raise_err(ERR_INVALID_STATE, "Power plans may be created only while production is PLANNING")

    plan = {
        "production_id": production_id,
        "phase_l1_watts": l1,
        "phase_l2_watts": l2,
        "phase_l3_watts": l3,
        "feeder_length_m": feeder,
        "generator_required": generator_required,
        "total_load_watts": None,
        "required_kva": None,
        "selected_generator_tier_kva": None,
        "max_phase_imbalance_pct": None,
        "status": "DRAFT",
    }
    db.stamp_new(plan)
    db.power_plans[plan["id"]] = plan
    calc.refresh_posture(production)
    return success_object(serialize(plan), 201)


@bp.route("/productions/<production_id>/power-plans", methods=["GET"])
@require_roles("Any")
def list_production_power_plans(production_id: str, _user_id: str, _role: str):
    get_production_or_404(production_id)
    limit, offset = parse_pagination()
    items = [p for p in db.power_plans.values() if p["production_id"] == production_id]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


# ---------------------------------------------------------------------------
# Nested: load schedules
# ---------------------------------------------------------------------------

LOAD_DIRECTIONS = {"LOAD_IN", "LOAD_OUT"}


@bp.route("/productions/<production_id>/load-schedules", methods=["POST"])
@require_roles("ProductionManager")
def create_load_schedule(production_id: str, _user_id: str, _role: str):
    body = get_json_body()
    truck_id = require_string(body, "truck_id")
    direction = require_enum(body, "direction", LOAD_DIRECTIONS)
    dock_door_index = require_int(body, "dock_door_index", minimum=0)
    window_start = require_ts(body, "window_start")
    window_end = require_ts(body, "window_end")

    if not (parse_iso8601(window_end, "window_end") > parse_iso8601(window_start, "window_start")):
        raise_err(ERR_INVALID_REQUEST, "window_end must be strictly after window_start")

    production = get_production_or_404(production_id)
    truck = db.trucks.get(truck_id)
    if truck is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Truck id does not exist")
    if production["status"] != "PLANNING":
        raise_err(ERR_INVALID_STATE, "Load schedules may be created only while production is PLANNING")
    venue = db.venues.get(production["venue_id"])
    if dock_door_index >= venue["dock_doors"]:
        raise_err(ERR_DOCK_DOOR_INVALID, "dock_door_index is not a valid dock door at this venue")

    schedule = {
        "production_id": production_id,
        "truck_id": truck_id,
        "direction": direction,
        "dock_door_index": dock_door_index,
        "window_start": window_start,
        "window_end": window_end,
        "pack_weight_kg": 0.0,
        "status": "PLANNED",
    }
    db.stamp_new(schedule)
    db.load_schedules[schedule["id"]] = schedule
    return success_object(serialize(schedule), 201)


@bp.route("/productions/<production_id>/load-schedules", methods=["GET"])
@require_roles("Any")
def list_production_load_schedules(production_id: str, _user_id: str, _role: str):
    get_production_or_404(production_id)
    limit, offset = parse_pagination()
    items = [s for s in db.load_schedules.values() if s["production_id"] == production_id]
    items = apply_filters(items, ["direction"])
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


# ---------------------------------------------------------------------------
# Nested: inspections
# ---------------------------------------------------------------------------

INSPECTION_TYPES = {"RIGGING", "ELECTRICAL", "FINAL"}


@bp.route("/productions/<production_id>/inspections", methods=["POST"])
@require_roles("ProductionManager")
def create_inspection(production_id: str, _user_id: str, _role: str):
    body = get_json_body()
    inspection_type = require_enum(body, "inspection_type", INSPECTION_TYPES)

    production = get_production_or_404(production_id)
    if production["status"] not in ("PLANNING", "LOAD_IN"):
        raise_err(ERR_INVALID_STATE, "Inspections may be scheduled only while production is PLANNING or LOAD_IN")

    inspection = {
        "production_id": production_id,
        "inspection_type": inspection_type,
        "status": "SCHEDULED",
        "attempt_no": 1,
        "inspector_user_id": None,
        "findings": None,
    }
    db.stamp_new(inspection)
    db.inspections[inspection["id"]] = inspection
    return success_object(serialize(inspection), 201)


@bp.route("/productions/<production_id>/inspections", methods=["GET"])
@require_roles("Any")
def list_production_inspections(production_id: str, _user_id: str, _role: str):
    get_production_or_404(production_id)
    limit, offset = parse_pagination()
    items = [i for i in db.inspections.values() if i["production_id"] == production_id]
    items = apply_filters(items, ["inspection_type"])
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


# ---------------------------------------------------------------------------
# Nested: damage reports
# ---------------------------------------------------------------------------

REPORT_TYPES = {"DAMAGE", "LOSS"}


@bp.route("/productions/<production_id>/damage-reports", methods=["POST"])
@require_roles("WarehouseChief")
def create_damage_report(production_id: str, _user_id: str, _role: str):
    body = get_json_body()
    entry_id = require_string(body, "pull_list_entry_id")
    report_type = require_enum(body, "report_type", REPORT_TYPES)

    production = get_production_or_404(production_id)
    entry = db.pull_list_entries.get(entry_id)
    if entry is None or entry["production_id"] != production_id:
        raise_err(ERR_RESOURCE_NOT_FOUND, "PullListEntry id does not exist for this production")
    if entry["status"] != "OUT":
        raise_err(ERR_INVALID_STATE, "Damage reports require the pull list entry to be OUT")
    for report in db.damage_reports.values():
        if report["pull_list_entry_id"] == entry_id and report["status"] in ("FILED", "ASSESSED"):
            raise_err(ERR_DUPLICATE_DAMAGE_REPORT, "An open damage report already exists for this entry")

    report = {
        "production_id": production_id,
        "pull_list_entry_id": entry_id,
        "report_type": report_type,
        "valuation_method": None,
        "repair_quote_cents": None,
        "assessed_charge_cents": None,
        "status": "FILED",
    }
    db.stamp_new(report)
    db.damage_reports[report["id"]] = report
    return success_object(serialize(report), 201)


@bp.route("/productions/<production_id>/damage-reports", methods=["GET"])
@require_roles("Any")
def list_production_damage_reports(production_id: str, _user_id: str, _role: str):
    get_production_or_404(production_id)
    limit, offset = parse_pagination()
    items = [r for r in db.damage_reports.values() if r["production_id"] == production_id]
    items = apply_filters(items, ["status"])
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


# ---------------------------------------------------------------------------
# Nested: settlement
# ---------------------------------------------------------------------------

@bp.route("/productions/<production_id>/settlement", methods=["POST"])
@require_roles("ProductionManager")
def create_settlement(production_id: str, _user_id: str, _role: str):
    production = get_production_or_404(production_id)
    if production["status"] != "CLOSED":
        raise_err(ERR_INVALID_STATE, "Settlement generation requires production CLOSED")
    for existing in db.settlements.values():
        if existing["production_id"] == production_id:
            raise_err(ERR_SETTLEMENT_EXISTS, "A settlement already exists for this production")

    totals = calc.settlement_live_totals(production_id)
    provisional_damage = calc.settlement_provisional_damage(production_id)
    settlement = {
        "production_id": production_id,
        "labor_total_cents": totals["labor_total_cents"],
        "equipment_total_cents": totals["equipment_total_cents"],
        "damage_total_cents": totals["damage_total_cents"],
        "provisional_damage_cents": provisional_damage,
        "grand_total_cents": totals["grand_total_cents"],
        "provisional_grand_total_cents": totals["labor_total_cents"]
        + totals["equipment_total_cents"]
        + provisional_damage,
        "dispute_adjustment_cents": 0,
        "status": "DRAFT",
    }
    db.stamp_new(settlement)
    db.settlements[settlement["id"]] = settlement
    return success_object(serialize(settlement), 201)


@bp.route("/productions/<production_id>/settlement", methods=["GET"])
@require_roles("Any")
def get_production_settlement(production_id: str, _user_id: str, _role: str):
    get_production_or_404(production_id)
    limit, offset = parse_pagination()
    items = [s for s in db.settlements.values() if s["production_id"] == production_id]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)
