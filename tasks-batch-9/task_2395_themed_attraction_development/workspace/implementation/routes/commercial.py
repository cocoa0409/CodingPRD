"""ValueEngineeringItem, VEBallot, RehearsalRun, MaintenanceItem and BudgetLedgerEntry."""

from flask import Blueprint

import auth
import calc
import domain
import response
import store
import validate as V
from errors import ApiError, invalid
from routes.common import body, check_project_version, no_body, page, state

bp = Blueprint("commercial", __name__)

VE_READ = (auth.OWNER_REP, auth.CREATIVE_DIRECTOR, auth.CONTRACTOR_PM, auth.PROGRAM_ADMIN)
RUN_READ = (auth.OWNER_REP, auth.CONTRACTOR_PM, auth.SHOW_PROGRAMMER, auth.PROGRAM_ADMIN)
MAINTENANCE_READ = (auth.OWNER_REP, auth.RIDE_ENGINEER, auth.CONTRACTOR_PM, auth.PROGRAM_ADMIN)
LEDGER_READ = (auth.OWNER_REP, auth.CONTRACTOR_PM, auth.PROGRAM_ADMIN)


# -------------------------------------------------------- ValueEngineeringItem
@bp.post("/value-engineering-items")
def create_ve_item():
    auth.authenticate((auth.CONTRACTOR_PM,))
    data = body(
        V.ID("project_id"),
        V.S("title", min_len=1, max_len=120),
        V.I("gross_saving_cents", minimum=1),
        V.N("rework_loss_pct", minimum=0, exclusive_max=100, max_dp=2),
        V.I("implementation_cost_cents", minimum=0),
        V.I("capacity_impact_guests_per_hour"),
        V.I("scope_impact_delta_cents"),
    )
    project = domain.get_project(data["project_id"])

    row = store.base_row()
    row["project_id"] = project["id"]
    row["title"] = data["title"]
    row["gross_saving_cents"] = data["gross_saving_cents"]
    row["rework_loss_pct"] = data["rework_loss_pct"]
    row["implementation_cost_cents"] = data["implementation_cost_cents"]
    row["capacity_impact_guests_per_hour"] = data["capacity_impact_guests_per_hour"]
    row["scope_impact_delta_cents"] = data["scope_impact_delta_cents"]
    row["net_saving_cents"] = None
    row["ballot_count"] = 0
    row["veto_present"] = False
    row["status"] = "PROPOSED"
    store.ve_items[row["id"]] = row
    return response.created(store.public(row))


@bp.get("/value-engineering-items/<row_id>")
def read_ve_item(row_id):
    auth.authenticate(VE_READ)
    return response.ok(store.public(domain.get_ve_item(row_id)))


@bp.post("/value-engineering-items/<row_id>/open-review")
def open_ve_review(row_id):
    auth.authenticate((auth.OWNER_REP,))
    no_body()
    item = domain.get_ve_item(row_id)
    state(item, ("PROPOSED",), "ERR_VE_ITEM_STATE_INVALID")
    project = domain.get_project(item["project_id"])
    domain.check_phase_in(project, ("SCHEMATIC", "DESIGN_DEVELOPMENT", "PRODUCTION", "INSTALLATION"))
    if item["scope_impact_delta_cents"] != item["implementation_cost_cents"] - item["gross_saving_cents"]:
        raise ApiError("ERR_SCOPE_IMPACT_DELTA_MISMATCH", 422)

    item["net_saving_cents"] = calc.ve_net_saving(
        item["gross_saving_cents"], item["rework_loss_pct"], item["implementation_cost_cents"]
    )
    item["status"] = "UNDER_REVIEW"
    store.touch(item)
    domain.recompute_budget(project)
    store.touch(project)
    return response.ok(store.public(item))


@bp.get("/value-engineering-items/<row_id>/ballots")
def ve_item_ballots(row_id):
    auth.authenticate(VE_READ)
    limit, offset = V.pagination()
    item = domain.get_ve_item(row_id)
    rows = domain.ballots_of(item["id"])
    items, total = page(rows, limit, offset)
    return response.collection(items, limit, offset, total)


@bp.post("/ve-ballots")
def cast_ballot():
    user_id, role = auth.authenticate((auth.OWNER_REP, auth.CONTRACTOR_PM, auth.CREATIVE_DIRECTOR))
    data = body(
        V.ID("value_engineering_item_id"),
        V.E("party_role", V.PARTY_ROLES),
        V.E("decision", V.DECISIONS),
        V.S("comment", min_len=1, max_len=300, required=False, nullable=True),
    )
    item = domain.get_ve_item(data["value_engineering_item_id"])
    state(item, ("UNDER_REVIEW",), "ERR_VE_ITEM_STATE_INVALID")
    if data["party_role"] != role:
        raise ApiError("ERR_BALLOT_PARTY_ROLE_MISMATCH", 422)

    project = domain.get_project(item["project_id"])
    existing = domain.ballots_of(item["id"])
    decision = data["decision"]
    approves = len([b for b in existing if b["decision"] == "APPROVE"]) + (1 if decision == "APPROVE" else 0)
    veto_after = bool(item["veto_present"]) or decision == "VETO"
    count_after = item["ballot_count"] + 1
    would_adopt = (not veto_after) and count_after >= 3 and approves >= 2
    if would_adopt:
        system = domain.selected_ride_system(project)
        operational = system["operational_hourly_capacity_guests"] if system else 0
        if operational + item["capacity_impact_guests_per_hour"] < project["required_hourly_capacity_guests"]:
            raise ApiError("ERR_VE_ADOPTION_BREAKS_CAPACITY", 409)

    if any(b["party_role"] == data["party_role"] for b in existing):
        raise ApiError("ERR_BALLOT_ALREADY_CAST", 409)
    if decision == "VETO" and data["party_role"] not in (auth.OWNER_REP, auth.CONTRACTOR_PM):
        raise ApiError("ERR_VETO_NOT_PERMITTED", 422)

    ballot = store.base_row(with_audit=False)
    ballot["value_engineering_item_id"] = item["id"]
    ballot["party_role"] = data["party_role"]
    ballot["decision"] = decision
    ballot["comment"] = data.get("comment")
    ballot["cast_by_user_id"] = user_id
    store.ve_ballots[ballot["id"]] = ballot

    item["ballot_count"] = count_after
    if decision == "VETO":
        item["veto_present"] = True
    resolved = None
    if item["veto_present"]:
        resolved = "REJECTED"
    elif item["ballot_count"] >= 3:
        resolved = "ADOPTED" if approves >= 2 else "REJECTED"
    if resolved is not None:
        item["status"] = resolved
    store.touch(item)

    if resolved == "ADOPTED":
        domain.mint_ledger_entry(
            project, "VE_SAVING", 0 - item["net_saving_cents"], "VE_SAVING for " + item["title"]
        )
        domain.refresh_project_exposure(project)
        store.touch(project)
    elif resolved == "REJECTED":
        domain.refresh_project_exposure(project)
        store.touch(project)
    return response.created(store.public(ballot))


# ----------------------------------------------------------------- RehearsalRun
@bp.post("/rehearsal-runs")
def create_run():
    auth.authenticate((auth.CONTRACTOR_PM,))
    data = body(
        V.ID("project_id"),
        V.E("run_kind", V.RUN_KINDS),
        V.DT("window_start_utc"),
        V.DT("window_end_utc"),
    )
    start = store.parse_dt(data["window_start_utc"])
    end = store.parse_dt(data["window_end_utc"])
    if end <= start:
        raise invalid("window_end_utc must be strictly after window_start_utc.")
    project = domain.get_project(data["project_id"])
    domain.check_not_frozen(project)
    domain.check_phase_in(project, ("TECHNICAL_REHEARSAL", "SOFT_OPEN"))
    if data["run_kind"] == "SOFT_OPEN" and project["design_phase"] != "SOFT_OPEN":
        raise ApiError("ERR_PROJECT_PHASE_INVALID", 409)

    existing = domain.runs_of(project["id"])
    for other in existing:
        if other["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        other_start = store.parse_dt(other["window_start_utc"])
        other_end = store.parse_dt(other["window_end_utc"])
        if start < other_end + store.CHANGEOVER and end > other_start - store.CHANGEOVER:
            raise ApiError("ERR_REHEARSAL_WINDOW_CONFLICT", 409)
    if data["run_kind"] == "SOFT_OPEN":
        for other in existing:
            if other["run_kind"] != "SOFT_OPEN":
                continue
            if store.parse_dt(other["window_start_utc"]).date() == start.date():
                raise ApiError("ERR_SOFT_OPEN_ALREADY_SCHEDULED", 409)

    row = store.base_row()
    row["project_id"] = project["id"]
    row["run_kind"] = data["run_kind"]
    row["window_start_utc"] = data["window_start_utc"]
    row["window_end_utc"] = data["window_end_utc"]
    row["guests_cycled"] = None
    row["duration_minutes"] = None
    row["measured_hourly_throughput_guests"] = None
    row["pass_threshold_guests"] = None
    row["result"] = None
    row["status"] = "SCHEDULED"
    store.rehearsal_runs[row["id"]] = row
    return response.created(store.public(row))


@bp.get("/rehearsal-runs/<row_id>")
def read_run(row_id):
    auth.authenticate(RUN_READ)
    return response.ok(store.public(domain.get_rehearsal_run(row_id)))


@bp.post("/rehearsal-runs/<row_id>/complete")
def complete_run(row_id):
    auth.authenticate((auth.CONTRACTOR_PM,))
    data = body(V.I("guests_cycled", minimum=0), V.I("duration_minutes", minimum=1))
    run = domain.get_rehearsal_run(row_id)
    state(run, ("SCHEDULED",), "ERR_REHEARSAL_STATE_INVALID")
    project = domain.get_project(run["project_id"])
    domain.check_not_frozen(project)
    domain.check_phase_in(project, ("TECHNICAL_REHEARSAL", "SOFT_OPEN"))
    if store.now() < store.parse_dt(run["window_end_utc"]):
        raise ApiError("ERR_REHEARSAL_WINDOW_NOT_ELAPSED", 409)

    system = domain.selected_ride_system(project)
    operational = system["operational_hourly_capacity_guests"] if system else 0
    measured, threshold, result = calc.rehearsal_throughput(
        data["guests_cycled"], data["duration_minutes"], operational
    )
    run["guests_cycled"] = data["guests_cycled"]
    run["duration_minutes"] = data["duration_minutes"]
    run["measured_hourly_throughput_guests"] = measured
    run["pass_threshold_guests"] = threshold
    run["result"] = result
    run["status"] = "COMPLETED"
    store.touch(run)
    if run["run_kind"] == "SOFT_OPEN" and result == "PASS":
        project["soft_open_validated"] = True
        store.touch(project)
    return response.ok(store.public(run))


# --------------------------------------------------------------- MaintenanceItem
@bp.post("/maintenance-items")
def create_maintenance_item():
    auth.authenticate((auth.RIDE_ENGINEER,))
    data = body(
        V.ID("project_id"),
        V.S("part_number", min_len=1, max_len=48),
        V.S("description", min_len=1, max_len=300),
        V.E("criticality", V.CRITICALITIES),
        V.N("annual_consumption_rate", minimum=0, max_dp=2),
        V.I("lead_time_days", minimum=0),
    )
    project = domain.get_project(data["project_id"])
    domain.check_not_frozen(project)
    for other in domain.maintenance_of(project["id"]):
        if other["part_number"] == data["part_number"]:
            raise ApiError("ERR_MAINTENANCE_PART_DUPLICATE", 409)

    row = store.base_row()
    row["project_id"] = project["id"]
    row["part_number"] = data["part_number"]
    row["description"] = data["description"]
    row["criticality"] = data["criticality"]
    row["annual_consumption_rate"] = data["annual_consumption_rate"]
    row["lead_time_days"] = data["lead_time_days"]
    row["recommended_stock_qty"] = calc.spare_stock(
        data["criticality"], data["annual_consumption_rate"], data["lead_time_days"]
    )
    row["stocked_qty"] = None
    row["status"] = "DRAFT"
    store.maintenance_items[row["id"]] = row
    return response.created(store.public(row))


@bp.get("/maintenance-items/<row_id>")
def read_maintenance_item(row_id):
    auth.authenticate(MAINTENANCE_READ)
    return response.ok(store.public(domain.get_maintenance_item(row_id)))


@bp.post("/maintenance-items/<row_id>/approve")
def approve_maintenance_item(row_id):
    auth.authenticate((auth.RIDE_ENGINEER,))
    data = body(V.I("stocked_qty", minimum=0))
    item = domain.get_maintenance_item(row_id)
    state(item, ("DRAFT",), "ERR_MAINTENANCE_STATE_INVALID")
    project = domain.get_project(item["project_id"])
    domain.check_not_frozen(project)
    if data["stocked_qty"] < item["recommended_stock_qty"]:
        raise ApiError("ERR_SPARE_STOCK_INSUFFICIENT", 422)

    item["stocked_qty"] = data["stocked_qty"]
    item["status"] = "APPROVED"
    store.touch(item)
    return response.ok(store.public(item))


@bp.post("/maintenance-items/<row_id>/hand-over")
def hand_over_maintenance_item(row_id):
    auth.authenticate((auth.OWNER_REP,))
    no_body()
    item = domain.get_maintenance_item(row_id)
    state(item, ("APPROVED",), "ERR_MAINTENANCE_STATE_INVALID")
    project = domain.get_project(item["project_id"])
    domain.check_not_frozen(project)
    domain.check_phase_in(project, ("SOFT_OPEN",))
    if project["soft_open_validated"] is not True:
        raise ApiError("ERR_SOFT_OPEN_NOT_VALIDATED", 409)

    item["status"] = "HANDED_OVER"
    store.touch(item)
    return response.ok(store.public(item))


# ------------------------------------------------------------ BudgetLedgerEntry
@bp.post("/budget-ledger-entries")
def post_ledger_entry():
    auth.authenticate((auth.OWNER_REP,))
    data = body(
        V.ID("project_id"),
        V.E("entry_kind", V.ENTRY_KINDS),
        V.I("amount_cents"),
        V.S("memo", min_len=1, max_len=200),
        V.I("expected_project_version"),
    )
    project = domain.get_project(data["project_id"])
    check_project_version(project, data["expected_project_version"])
    domain.check_not_frozen(project)
    if data["amount_cents"] > 0:
        domain.check_not_restricted(project)
    if data["entry_kind"] != "CHANGE_ORDER":
        raise ApiError("ERR_LEDGER_KIND_NOT_WRITABLE", 422)
    if project["committed_cost_cents"] + data["amount_cents"] > project["budget_ceiling_cents"]:
        raise ApiError("ERR_BUDGET_CEILING_EXCEEDED", 409)

    entry = domain.mint_ledger_entry(project, "CHANGE_ORDER", data["amount_cents"], data["memo"])
    domain.refresh_project_exposure(project)
    store.touch(project)
    return response.created(store.public(entry))


@bp.get("/budget-ledger-entries/<row_id>")
def read_ledger_entry(row_id):
    auth.authenticate(LEDGER_READ)
    return response.ok(store.public(domain.get_ledger_entry(row_id)))


@bp.post("/budget-ledger-entries/<row_id>/reverse")
def reverse_ledger_entry(row_id):
    auth.authenticate((auth.OWNER_REP,))
    data = body(V.S("reason", min_len=1), V.I("expected_project_version"))
    entry = domain.get_ledger_entry(row_id)
    project = domain.get_project(entry["project_id"])
    check_project_version(project, data["expected_project_version"])
    if entry["reversed"] or entry["entry_kind"] == "REVERSAL":
        raise ApiError("ERR_LEDGER_ENTRY_ALREADY_REVERSED", 409)

    entry["reversed"] = True
    reversal = domain.mint_ledger_entry(
        project,
        "REVERSAL",
        0 - entry["amount_cents"],
        data["reason"],
        reversal_of_sequence_no=entry["sequence_no"],
    )
    domain.refresh_project_exposure(project)
    store.touch(project)
    return response.created(store.public(reversal))
