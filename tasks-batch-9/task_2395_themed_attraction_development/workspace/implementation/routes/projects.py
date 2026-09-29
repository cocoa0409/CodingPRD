"""Logical clock and AttractionProject endpoints."""

from decimal import Decimal

from flask import Blueprint

import auth
import calc
import domain
import response
import store
import validate as V
from errors import ApiError
from routes.common import body, check_project_version, no_body, page

bp = Blueprint("projects", __name__)

READ_ALL = auth.ALL_ROLES


# --------------------------------------------------------------- logical clock
@bp.post("/_clock/set_current_utc")
def set_clock():
    auth.authenticate((auth.PROGRAM_ADMIN,))
    data = body(V.DT("to_iso8601"))
    store.set_now(store.parse_dt(data["to_iso8601"]))
    return response.ok({})


# ------------------------------------------------------------- create and list
@bp.post("/attraction-projects")
def create_project():
    auth.authenticate((auth.OWNER_REP,))
    data = body(
        V.S("project_code", min_len=1, max_len=32),
        V.S("name", min_len=1, max_len=120),
        V.I("design_day_attendance", minimum=1),
        V.N("peak_hour_share", exclusive_min=0, maximum=1, max_dp=4),
        V.I("budget_ceiling_cents", minimum=1),
        V.N("virtual_queue_share_pct", minimum=0, maximum=100, max_dp=2, required=False),
    )
    code = data["project_code"]
    for existing in store.projects.values():
        if existing["project_code"] == code:
            raise ApiError("ERR_PROJECT_CODE_DUPLICATE", 409)
    share = data.get("virtual_queue_share_pct", Decimal(0))
    if share > calc.MAX_VIRTUAL_QUEUE_SHARE_PCT:
        raise ApiError("ERR_VIRTUAL_QUEUE_SHARE_EXCEEDED", 422)

    row = store.base_row()
    row["project_code"] = code
    row["name"] = data["name"]
    row["design_day_attendance"] = data["design_day_attendance"]
    row["peak_hour_share"] = data["peak_hour_share"]
    row["virtual_queue_share_pct"] = share
    row["budget_ceiling_cents"] = data["budget_ceiling_cents"]
    row["required_hourly_capacity_guests"] = calc.required_hourly_capacity(
        data["design_day_attendance"], data["peak_hour_share"]
    )
    row["design_phase"] = "BLUE_SKY"
    row["readiness_posture"] = "OPEN"
    row["selected_ride_system_id"] = None
    row["committed_cost_cents"] = 0
    row["forecast_cost_cents"] = 0
    row["open_critical_finding_count"] = 0
    row["open_major_finding_count"] = 0
    row["queue_capacity_total_guests"] = 0
    row["show_quality_score"] = calc.ZERO_2DP
    row["soft_open_validated"] = False
    row["handover_accepted_at"] = None
    row["ledger_sequence_high_water"] = 0
    store.projects[row["id"]] = row
    return response.created(store.public(row))


@bp.get("/attraction-projects")
def list_projects():
    auth.authenticate(READ_ALL)
    limit, offset = V.pagination()
    phase = V.enum_filter("design_phase", V.DESIGN_PHASES)
    posture = V.enum_filter("readiness_posture", V.READINESS_POSTURES)
    rows = store.sorted_rows(list(store.projects.values()))
    if phase is not None:
        rows = [r for r in rows if r["design_phase"] == phase]
    if posture is not None:
        rows = [r for r in rows if r["readiness_posture"] == posture]
    items, total = page(rows, limit, offset)
    return response.collection(items, limit, offset, total)


@bp.get("/attraction-projects/<project_id>")
def read_project(project_id):
    auth.authenticate(READ_ALL)
    project = domain.get_project(project_id)
    return response.ok(store.public(project))


# ------------------------------------------------------------------ patch
@bp.patch("/attraction-projects/<project_id>")
def patch_project(project_id):
    auth.authenticate((auth.OWNER_REP,))
    data = body(
        V.I("expected_project_version"),
        V.I("budget_ceiling_cents", minimum=1, required=False),
        V.N("virtual_queue_share_pct", minimum=0, maximum=100, max_dp=2, required=False),
        V.I("design_day_attendance", minimum=1, required=False),
        V.N("peak_hour_share", exclusive_min=0, maximum=1, max_dp=4, required=False),
    )
    project = domain.get_project(project_id)
    check_project_version(project, data["expected_project_version"])
    if "virtual_queue_share_pct" in data and data["virtual_queue_share_pct"] > calc.MAX_VIRTUAL_QUEUE_SHARE_PCT:
        raise ApiError("ERR_VIRTUAL_QUEUE_SHARE_EXCEEDED", 422)

    recompute_capacity = False
    for field in ("budget_ceiling_cents", "virtual_queue_share_pct", "design_day_attendance", "peak_hour_share"):
        if field in data:
            project[field] = data[field]
            if field in ("design_day_attendance", "peak_hour_share"):
                recompute_capacity = True
    if recompute_capacity:
        domain.recompute_required_capacity(project)
    domain.refresh_project_exposure(project)
    store.touch(project)
    return response.ok(store.public(project))


# ----------------------------------------------------------- advance the ladder
def _gate(condition, error_id, http_status=409):
    if not condition:
        raise ApiError(error_id, http_status)


def _check_phase_entry(project, to_phase):
    project_id = project["id"]
    scenes = domain.scenes_of(project_id)
    if to_phase == "CONCEPT":
        _gate(len(scenes) >= 1, "ERR_PHASE_PRECONDITION_UNMET")
        return
    if to_phase == "SCHEMATIC":
        ready = [s for s in scenes if s["status"] in ("SEQUENCED", "PROGRAMMED", "VALIDATED")]
        _gate(project["selected_ride_system_id"] is not None and len(ready) >= 2, "ERR_PHASE_PRECONDITION_UNMET")
        return
    if to_phase == "DESIGN_DEVELOPMENT":
        packages = domain.packages_of(project_id)
        _gate(
            any(p["status"] in ("SUBMITTED", "APPROVED") for p in packages),
            "ERR_PHASE_PRECONDITION_UNMET",
        )
        return
    if to_phase == "PRODUCTION":
        system = domain.selected_ride_system(project)
        operational = system["operational_hourly_capacity_guests"] if system else 0
        _gate(operational >= project["required_hourly_capacity_guests"], "ERR_CAPACITY_TARGET_NOT_MET")
        packages = domain.packages_of(project_id)
        _gate(any(p["status"] == "APPROVED" for p in packages), "ERR_PHASE_PRECONDITION_UNMET")
        return
    if to_phase == "INSTALLATION":
        _gate(
            project["open_critical_finding_count"] == 0 and domain.has_cleared_review(project),
            "ERR_SAFETY_REVIEW_NOT_CLEARED",
        )
        return
    if to_phase == "TECHNICAL_REHEARSAL":
        accepted = [s for s in domain.segments_of(project_id) if s["status"] == "ACCEPTED"]
        _gate(
            any(s["routing_type"] == "ACCESSIBLE" for s in accepted),
            "ERR_ACCESSIBLE_ROUTE_MISSING",
        )
        totals = domain.queue_position(project)
        _gate(
            totals["accessible_share_pct"] >= calc.MIN_ACCESSIBLE_SHARE_PCT,
            "ERR_ACCESSIBLE_SHARE_INSUFFICIENT",
        )
        system = domain.selected_ride_system(project)
        _gate(system is not None and system["status"] == "COMMISSIONED", "ERR_PHASE_PRECONDITION_UNMET")
        return
    if to_phase == "SOFT_OPEN":
        _gate(
            not any(s["status"] in ("DRAFT", "SEQUENCED", "PROGRAMMED", "HELD") for s in scenes),
            "ERR_SCENE_NOT_READY",
        )
        _gate(
            calc.dec(project["show_quality_score"]) >= calc.MIN_SHOW_QUALITY_SCORE,
            "ERR_SHOW_QUALITY_BELOW_MINIMUM",
        )
        return
    if to_phase == "OPERATIONS_HANDOVER":
        _gate(project["open_critical_finding_count"] == 0, "ERR_SAFETY_REVIEW_NOT_CLEARED")
        items = domain.maintenance_of(project_id)
        _gate(
            len(items) >= 1 and all(i["status"] == "HANDED_OVER" for i in items),
            "ERR_MAINTENANCE_NOT_HANDED_OVER",
        )
        _gate(project["soft_open_validated"] is True, "ERR_SOFT_OPEN_NOT_VALIDATED")
        return


@bp.post("/attraction-projects/<project_id>/advance-phase")
def advance_phase(project_id):
    auth.authenticate((auth.OWNER_REP,))
    data = body(V.E("to_phase", V.DESIGN_PHASES), V.I("expected_project_version"))
    project = domain.get_project(project_id)
    check_project_version(project, data["expected_project_version"])
    domain.check_not_frozen(project)
    to_phase = data["to_phase"]
    if domain.successor(project["design_phase"]) != to_phase:
        raise ApiError("ERR_PHASE_SEQUENCE_INVALID", 409)
    _check_phase_entry(project, to_phase)

    project["design_phase"] = to_phase
    if to_phase == "OPERATIONS_HANDOVER":
        project["handover_accepted_at"] = store.now_iso()
    store.touch(project)
    return response.ok(store.public(project))


# --------------------------------------------------------------- derived reads
@bp.get("/attraction-projects/<project_id>/capacity-summary")
def capacity_summary(project_id):
    auth.authenticate(
        (
            auth.OWNER_REP,
            auth.CREATIVE_DIRECTOR,
            auth.RIDE_ENGINEER,
            auth.SHOW_PROGRAMMER,
            auth.CONTRACTOR_PM,
            auth.PROGRAM_ADMIN,
        )
    )
    project = domain.get_project(project_id)
    totals = domain.queue_position(project)
    system = domain.selected_ride_system(project)
    return response.ok(
        {
            "required_hourly_capacity_guests": project["required_hourly_capacity_guests"],
            "selected_ride_system_id": project["selected_ride_system_id"],
            "theoretical_hourly_capacity_guests": system["theoretical_hourly_capacity_guests"] if system else 0,
            "operational_hourly_capacity_guests": system["operational_hourly_capacity_guests"] if system else 0,
            "queue_capacity_total_guests": totals["queue_capacity_total_guests"],
            "accessible_capacity_guests": totals["accessible_capacity_guests"],
            "accessible_share_pct": totals["accessible_share_pct"],
            "virtual_queue_allocation_guests": totals["virtual_queue_allocation_guests"],
            "posted_wait_minutes": totals["posted_wait_minutes"],
            "show_quality_score": domain.compute_show_quality(project),
        }
    )


@bp.get("/attraction-projects/<project_id>/budget-position")
def budget_position(project_id):
    auth.authenticate((auth.OWNER_REP, auth.CONTRACTOR_PM, auth.CREATIVE_DIRECTOR, auth.PROGRAM_ADMIN))
    project = domain.get_project(project_id)
    committed = domain.committed_cost(project)
    forecast = domain.forecast_cost(project, committed)
    ceiling = project["budget_ceiling_cents"]
    return response.ok(
        {
            "committed_cost_cents": committed,
            "forecast_cost_cents": forecast,
            "budget_ceiling_cents": ceiling,
            "headroom_cents": ceiling - committed,
            "restricted_utilisation_cents": calc.restricted_utilisation_cents(ceiling),
            "readiness_posture": project["readiness_posture"],
            "ve_program_net_savings_cents": domain.ve_program_net_savings(project),
        }
    )


# ------------------------------------------------------- reverse-reachability
@bp.get("/attraction-projects/<project_id>/ride-systems")
def project_ride_systems(project_id):
    auth.authenticate(
        (auth.OWNER_REP, auth.RIDE_ENGINEER, auth.CREATIVE_DIRECTOR, auth.CONTRACTOR_PM, auth.PROGRAM_ADMIN)
    )
    limit, offset = V.pagination()
    status = V.enum_filter("status", V.RIDE_SYSTEM_STATUSES)
    project = domain.get_project(project_id)
    rows = domain.ride_systems_of(project["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, total = page(rows, limit, offset)
    return response.collection(items, limit, offset, total)


@bp.get("/attraction-projects/<project_id>/queue-segments")
def project_queue_segments(project_id):
    auth.authenticate((auth.OWNER_REP, auth.CREATIVE_DIRECTOR, auth.CONTRACTOR_PM, auth.PROGRAM_ADMIN))
    limit, offset = V.pagination()
    status = V.enum_filter("status", V.QUEUE_STATUSES)
    project = domain.get_project(project_id)
    rows = domain.segments_of(project["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, total = page(rows, limit, offset)
    return response.collection(items, limit, offset, total)


@bp.get("/attraction-projects/<project_id>/value-engineering-items")
def project_ve_items(project_id):
    auth.authenticate((auth.OWNER_REP, auth.CONTRACTOR_PM, auth.CREATIVE_DIRECTOR, auth.PROGRAM_ADMIN))
    limit, offset = V.pagination()
    status = V.enum_filter("status", V.VE_STATUSES)
    project = domain.get_project(project_id)
    rows = domain.ve_items_of(project["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, total = page(rows, limit, offset)
    return response.collection(items, limit, offset, total)


@bp.get("/attraction-projects/<project_id>/rehearsal-runs")
def project_rehearsal_runs(project_id):
    auth.authenticate((auth.OWNER_REP, auth.CONTRACTOR_PM, auth.SHOW_PROGRAMMER, auth.PROGRAM_ADMIN))
    limit, offset = V.pagination()
    run_kind = V.enum_filter("run_kind", V.RUN_KINDS)
    project = domain.get_project(project_id)
    rows = domain.runs_of(project["id"])
    if run_kind is not None:
        rows = [r for r in rows if r["run_kind"] == run_kind]
    items, total = page(rows, limit, offset)
    return response.collection(items, limit, offset, total)


@bp.get("/attraction-projects/<project_id>/budget-ledger-entries")
def project_ledger(project_id):
    auth.authenticate((auth.OWNER_REP, auth.CONTRACTOR_PM, auth.PROGRAM_ADMIN))
    limit, offset = V.pagination()
    entry_kind = V.enum_filter("entry_kind", V.ENTRY_KINDS)
    project = domain.get_project(project_id)
    rows = domain.ledger_of(project["id"])
    if entry_kind is not None:
        rows = [r for r in rows if r["entry_kind"] == entry_kind]
    items, total = page(rows, limit, offset)
    return response.collection(items, limit, offset, total)


@bp.get("/attraction-projects/<project_id>/maintenance-items")
def project_maintenance_items(project_id):
    auth.authenticate((auth.OWNER_REP, auth.RIDE_ENGINEER, auth.CONTRACTOR_PM, auth.PROGRAM_ADMIN))
    limit, offset = V.pagination()
    status = V.enum_filter("status", V.MAINTENANCE_STATUSES)
    project = domain.get_project(project_id)
    rows = domain.maintenance_of(project["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, total = page(rows, limit, offset)
    return response.collection(items, limit, offset, total)
