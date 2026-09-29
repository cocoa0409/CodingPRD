"""Water systems, street projects, funding sources and the logical clock."""

from flask import Blueprint, g

import logic
import lookup
from core import (
    ANY_ROLE, db, endpoint, fail, field, filter_arg, iso_ms, new_row,
    paginate, parse_date, parse_datetime, read_pagination, respond_list,
    respond_object, touch, validate_body, body_json, by_created_at,
)

bp = Blueprint("water", __name__)

INVENTORY_STATUSES = ("DRAFT", "VALIDATION_PENDING", "PUBLISHED", "AMENDMENT_PENDING")
FUNDING_MODES = ("WATERFALL", "PRO_RATA")
CCT_STATUSES = ("NOT_REQUIRED", "OPTIMIZED", "PENDING_REOPTIMIZATION")
SOURCE_KINDS = ("STATE_REVOLVING_FUND", "FEDERAL_GRANT", "RATE_REVENUE")
SOURCE_STATUSES = ("ACTIVE", "SUSPENDED", "CLOSED")


# ---------------------------------------------------------------- WaterSystem
@bp.post("/lsl/water-systems")
@endpoint(["ProgramAdministrator"])
def create_water_system():
    data = validate_body(body_json(), [
        field("pwsid", "string", required=True, nonempty=True),
        field("system_name", "string", required=True, nonempty=True),
        field("compliance_deadline_date", "date", required=True),
        field("baseline_lead_and_grr_count", "integer", default=0, min=0),
        field("disadvantaged_tract_codes", "array", default=None, item_type="string"),
        field("funding_mode", "string", default="WATERFALL", enum=FUNDING_MODES),
        field("cct_optimization_status", "string", default="NOT_REQUIRED",
              enum=CCT_STATUSES),
        field("cct_orthophosphate_mg_l", "number", default=None, min=0),
        field("cct_target_ph", "number", default=None, min=6.0, max=9.5),
    ])

    for row in db.water_systems.values():
        if row["pwsid"] == data["pwsid"]:
            fail("ERR_DUPLICATE_PWSID",
                 "pwsid %s is already registered." % data["pwsid"])

    ws = new_row()
    ws.update({
        "pwsid": data["pwsid"],
        "system_name": data["system_name"],
        "compliance_deadline_date": data["compliance_deadline_date"],
        "baseline_lead_and_grr_count": data["baseline_lead_and_grr_count"],
        "disadvantaged_tract_codes": list(data["disadvantaged_tract_codes"] or []),
        "funding_mode": data["funding_mode"],
        "cct_optimization_status": data["cct_optimization_status"],
        "cct_orthophosphate_mg_l": data["cct_orthophosphate_mg_l"],
        "cct_target_ph": data["cct_target_ph"],
        "inventory_status": "DRAFT",
    })
    db.water_systems[ws["id"]] = ws
    return respond_object(logic.serialize_water_system(ws), 201)


@bp.get("/lsl/water-systems")
@endpoint(ANY_ROLE)
def list_water_systems():
    limit, offset = read_pagination()
    rows = by_created_at(list(db.water_systems.values()))
    status = filter_arg("inventory_status")
    if status is not None:
        rows = [r for r in rows if r["inventory_status"] == status]
    posture = filter_arg("program_posture")
    if posture is not None:
        rows = [r for r in rows if logic.program_posture(r) == posture]
    page, total = paginate(rows, limit, offset)
    return respond_list([logic.serialize_water_system(r) for r in page],
                        limit, offset, total)


@bp.get("/lsl/water-systems/<ws_id>")
@endpoint(ANY_ROLE)
def read_water_system(ws_id):
    ws = lookup.water_system(ws_id)
    return respond_object(logic.serialize_water_system(ws))


@bp.post("/lsl/water-systems/<ws_id>/advance-inventory-status")
@endpoint(["ComplianceOfficer"])
def advance_inventory_status(ws_id):
    data = validate_body(body_json(), [
        field("target_status", "string", required=True, enum=INVENTORY_STATUSES),
    ])
    ws = lookup.water_system(ws_id)

    target = data["target_status"]
    lines = logic.lines_of_system(ws["id"])
    declared = (ws["inventory_status"] == "DRAFT"
                and target == "VALIDATION_PENDING"
                and len(lines) >= 1
                and all(l["inventory_state"] != "UNCLASSIFIED" for l in lines))
    if not declared:
        fail("ERR_INVENTORY_STATE_INVALID",
             "No declared inventory_status transition from %s to %s under the "
             "current inventory." % (ws["inventory_status"], target))

    ws["inventory_status"] = target
    touch(ws)
    return respond_object(logic.serialize_water_system(ws))


@bp.patch("/lsl/water-systems/<ws_id>/funding-policy")
@endpoint(["ProgramAdministrator"])
def update_funding_policy(ws_id):
    data = validate_body(body_json(), [
        field("funding_mode", "string", required=True, enum=FUNDING_MODES),
    ])
    ws = lookup.water_system(ws_id)
    ws["funding_mode"] = data["funding_mode"]
    touch(ws)
    return respond_object(logic.serialize_water_system(ws))


@bp.patch("/lsl/water-systems/<ws_id>/corrosion-control")
@endpoint(["ComplianceOfficer"])
def update_corrosion_control(ws_id):
    payload = body_json()
    data = validate_body(payload, [
        field("cct_optimization_status", "string", required=True, enum=CCT_STATUSES),
        field("cct_orthophosphate_mg_l", "number", default=None, min=0),
        field("cct_target_ph", "number", default=None, min=6.0, max=9.5),
    ])
    ws = lookup.water_system(ws_id)
    ws["cct_optimization_status"] = data["cct_optimization_status"]
    if "cct_orthophosphate_mg_l" in payload:
        ws["cct_orthophosphate_mg_l"] = data["cct_orthophosphate_mg_l"]
    if "cct_target_ph" in payload:
        ws["cct_target_ph"] = data["cct_target_ph"]
    touch(ws)
    return respond_object(logic.serialize_water_system(ws))


# --------------------------------------------------------------- StreetProject
@bp.post("/lsl/street-projects")
@endpoint(["ProgramAdministrator"])
def create_street_project():
    data = validate_body(body_json(), [
        field("water_system_id", "string", required=True),
        field("project_name", "string", required=True, nonempty=True),
        field("moratorium_start_date", "date", required=True),
        field("moratorium_end_date", "date", required=True),
        field("paving_start_date", "date", required=True),
        field("max_concurrent_excavations", "integer", default=1, min=1),
    ])
    if parse_date(data["moratorium_end_date"]) < parse_date(data["moratorium_start_date"]):
        fail("ERR_INVALID_DATE_RANGE",
             "moratorium_end_date must be on or after moratorium_start_date.")
    lookup.water_system(data["water_system_id"])

    project = new_row()
    project.update({
        "water_system_id": data["water_system_id"],
        "project_name": data["project_name"],
        "moratorium_start_date": data["moratorium_start_date"],
        "moratorium_end_date": data["moratorium_end_date"],
        "paving_start_date": data["paving_start_date"],
        "max_concurrent_excavations": data["max_concurrent_excavations"],
    })
    db.street_projects[project["id"]] = project

    # Registering a project re-tiers the coordination term of every linked line.
    for line in db.service_lines.values():
        if line["street_project_id"] == project["id"]:
            before = line["replacement_priority_score"]
            logic.recompute_priority(line)
            if line["replacement_priority_score"] != before:
                touch(line)

    return respond_object(logic.serialize_street_project(project), 201)


@bp.get("/lsl/street-projects")
@endpoint(["ProgramAdministrator", "InventoryAnalyst", "ComplianceOfficer",
           "ReplacementContractor"])
def list_street_projects():
    limit, offset = read_pagination()
    rows = by_created_at(list(db.street_projects.values()))
    ws_id = filter_arg("water_system_id")
    if ws_id is not None:
        rows = [r for r in rows if r["water_system_id"] == ws_id]
    page, total = paginate(rows, limit, offset)
    return respond_list([logic.serialize_street_project(r) for r in page],
                        limit, offset, total)


@bp.get("/lsl/street-projects/<project_id>")
@endpoint(["ProgramAdministrator", "InventoryAnalyst", "ComplianceOfficer",
           "ReplacementContractor"])
def read_street_project(project_id):
    project = lookup.street_project(project_id)
    return respond_object(logic.serialize_street_project(project))


# --------------------------------------------------------------- FundingSource
@bp.post("/lsl/funding-sources")
@endpoint(["ProgramAdministrator"])
def create_funding_source():
    data = validate_body(body_json(), [
        field("water_system_id", "string", required=True),
        field("source_kind", "string", required=True, enum=SOURCE_KINDS),
        field("authorized_cents", "integer", required=True, min=1),
        field("priority_rank", "integer", required=True, min=1),
        field("max_share_pct", "number", default=100.0, gt=0, max=100.0),
        field("equity_required_pct", "number", default=0.0, min=0.0, max=100.0),
    ])
    lookup.water_system(data["water_system_id"])

    source = new_row()
    source.update({
        "water_system_id": data["water_system_id"],
        "source_kind": data["source_kind"],
        "authorized_cents": data["authorized_cents"],
        "priority_rank": data["priority_rank"],
        "max_share_pct": data["max_share_pct"],
        "equity_required_pct": data["equity_required_pct"],
        "status": "ACTIVE",
    })
    db.funding_sources[source["id"]] = source
    return respond_object(logic.serialize_funding_source(source), 201)


@bp.get("/lsl/funding-sources")
@endpoint(["ProgramAdministrator", "InventoryAnalyst", "ComplianceOfficer"])
def list_funding_sources():
    limit, offset = read_pagination()
    rows = by_created_at(list(db.funding_sources.values()))
    ws_id = filter_arg("water_system_id")
    if ws_id is not None:
        rows = [r for r in rows if r["water_system_id"] == ws_id]
    kind = filter_arg("source_kind")
    if kind is not None:
        rows = [r for r in rows if r["source_kind"] == kind]
    status = filter_arg("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return respond_list([logic.serialize_funding_source(r) for r in page],
                        limit, offset, total)


@bp.get("/lsl/funding-sources/<source_id>")
@endpoint(["ProgramAdministrator", "InventoryAnalyst", "ComplianceOfficer"])
def read_funding_source(source_id):
    source = lookup.funding_source(source_id)
    return respond_object(logic.serialize_funding_source(source))


@bp.post("/lsl/funding-sources/<source_id>/status")
@endpoint(["ProgramAdministrator"])
def set_funding_source_status(source_id):
    data = validate_body(body_json(), [
        field("status", "string", required=True, enum=SOURCE_STATUSES),
    ])
    source = lookup.funding_source(source_id)
    source["status"] = data["status"]
    touch(source)
    return respond_object(logic.serialize_funding_source(source))


# ------------------------------------------------------------- logical clock
@bp.post("/lsl/_clock/set_current_utc")
@endpoint(["ProgramAdministrator"])
def set_clock():
    data = validate_body(body_json(), [
        field("to_iso8601", "datetime", required=True),
    ])
    target = parse_datetime(data["to_iso8601"])
    previous = db.clock
    if target < previous:
        fail("ERR_CLOCK_NOT_MONOTONIC",
             "The logical clock may not move backwards from %s." % iso_ms(previous))
    db.clock = target
    # overdue on every notification and program_posture on every water system are
    # derived on read, so the move is observable immediately and everywhere.
    return respond_object({
        "current_utc": iso_ms(db.clock),
        "previous_utc": iso_ms(previous),
    })
