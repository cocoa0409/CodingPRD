"""Parcel inventory, pre-event value, participation dimension and adjacency edges."""
from decimal import Decimal

from flask import Blueprint

import calc
import lookups
import store
import web
from core import clock_date, clock_now, fail, fmt_dt
from web import endpoint

bp = Blueprint("parcels", __name__)


@bp.post("/mitigation-projects/<project_id>/parcels")
@endpoint("SubrecipientCoordinator")
def create_parcel(project_id):
    project = lookups.get_project(project_id)
    web.scope_project(project_id)
    body = web.get_body()
    apn = web.req_string(body, "apn")
    site_address = web.req_string(body, "site_address")
    acreage = web.decimal_field(body, "acreage", places=2, minimum=Decimal(0), exclusive_min=True)
    occupancy = web.req_enum(body, "occupancy_type", store.OCCUPANCY_TYPES)
    structure = web.req_enum(body, "structure_type", store.STRUCTURE_TYPES)
    damage = web.decimal_field(body, "substantial_damage_pct", required=False,
                               default=Decimal("0.00"), places=2,
                               minimum=Decimal(0), maximum=Decimal(100))
    if project["status"] not in ("DRAFT", "SUBMITTED"):
        fail("ERR_INVALID_PROJECT_STATE")
    for existing in store.parcels.values():
        if existing["project_id"] == project_id and existing["apn"] == apn:
            fail("ERR_DUPLICATE_APN")

    record = store.new_record("Parcel", {
        "project_id": project_id,
        "apn": apn,
        "site_address": site_address,
        "acreage": acreage,
        "occupancy_type": occupancy,
        "structure_type": structure,
        "substantial_damage_pct": damage,
        "pre_event_fmv_cents": None,
        "pre_event_value_basis": None,
        "pre_event_value_determined_at": None,
        "voluntary_acknowledgement_signed_on": None,
        "participation_status": "NOT_CONTACTED",
        "acquisition_status": "NOT_STARTED",
        "dob_deduction_total_cents": 0,
    })
    store.parcels[record["id"]] = record
    calc.recompute_participating(project)
    calc.recompute_ratio_only(project)
    store.touch(project)
    return web.respond_object(record, 201)


@bp.get("/parcels")
@endpoint()
def list_parcels():
    project_id = web.query_str("project_id")
    participation = web.query_enum("participation_status", store.PARTICIPATION_STATUSES)
    acquisition = web.query_enum("acquisition_status", store.ACQUISITION_STATUSES)
    occupancy = web.query_enum("occupancy_type", store.OCCUPANCY_TYPES)
    rows = list(store.parcels.values())
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if participation is not None:
        rows = [r for r in rows if r["participation_status"] == participation]
    if acquisition is not None:
        rows = [r for r in rows if r["acquisition_status"] == acquisition]
    if occupancy is not None:
        rows = [r for r in rows if r["occupancy_type"] == occupancy]
    return web.list_response(rows)


@bp.get("/parcels/<parcel_id>")
@endpoint()
def read_parcel(parcel_id):
    return web.respond_object(lookups.get_parcel(parcel_id))


@bp.post("/parcels/<parcel_id>/pre-event-value")
@endpoint("StaffAppraiser")
def set_pre_event_value(parcel_id):
    parcel = lookups.get_parcel(parcel_id)
    body = web.get_body()
    amount = web.int_field(body, "pre_event_fmv_cents", minimum=1)
    basis = web.req_enum(body, "pre_event_value_basis", store.PRE_EVENT_VALUE_BASES)
    project = lookups.project_of_parcel(parcel)
    if project is None or project["status"] != "APPROVED":
        fail("ERR_PROJECT_NOT_APPROVED")
    parcel["pre_event_fmv_cents"] = amount
    parcel["pre_event_value_basis"] = basis
    parcel["pre_event_value_determined_at"] = fmt_dt(clock_now())
    store.touch(parcel)
    return web.respond_object(parcel)


def _cancel_acquisition_pipeline(parcel):
    """Links one and two of the holdout/withdrawal cascade. Returns True when offers moved."""
    if parcel["acquisition_status"] in store.PRE_CLOSING_ACQUISITION:
        parcel["acquisition_status"] = "ACQUISITION_CANCELLED"
        for offer in store.by_created(calc.parcel_offers(parcel["id"])):
            if offer["status"] not in ("DRAFT", "PRESENTED"):
                continue
            offer["status"] = "WITHDRAWN"
            store.touch(offer)


@bp.post("/parcels/<parcel_id>/participation")
@endpoint("SubrecipientCoordinator")
def record_participation(parcel_id):
    parcel = lookups.get_parcel(parcel_id)
    web.scope_project(parcel["project_id"])
    project = lookups.project_of_parcel(parcel)
    body = web.get_body()
    decision = web.req_enum(body, "participation_decision",
                            ["INTERESTED", "CONFIRM_VOLUNTARY", "DECLINE", "WITHDRAW"])
    signed_on = web.opt_date(body, "voluntary_acknowledgement_signed_on")
    web.opt_string(body, "decision_note")
    current = parcel["participation_status"]

    if decision == "CONFIRM_VOLUNTARY":
        if signed_on is None:
            fail("ERR_INVALID_REQUEST", "Field 'voluntary_acknowledgement_signed_on' is required.")
        if signed_on > clock_date():
            fail("ERR_INVALID_REQUEST",
                 "Field 'voluntary_acknowledgement_signed_on' may not be future dated.")

    if decision == "INTERESTED":
        if project is None or project["status"] != "APPROVED":
            fail("ERR_PROJECT_NOT_APPROVED")

    if decision == "CONFIRM_VOLUNTARY" and parcel.get("pre_event_fmv_cents") is None:
        fail("ERR_PRE_EVENT_VALUE_NOT_DETERMINED")

    if decision == "WITHDRAW" and parcel["acquisition_status"] in store.ACQUIRED_ACQUISITION:
        fail("ERR_OPEN_SPACE_RESTRICTION_ACTIVE")

    project_moved = False

    if decision == "INTERESTED":
        parcel["participation_status"] = "INTERESTED"
        if current == "DECLINED":
            if parcel["acquisition_status"] == "ACQUISITION_CANCELLED":
                parcel["acquisition_status"] = "NOT_STARTED"
            calc.recompute_holdout(project)
            calc.recompute_ratio(project)
            project_moved = True
    elif decision == "CONFIRM_VOLUNTARY":
        parcel["participation_status"] = "VOLUNTARY_CONFIRMED"
        parcel["voluntary_acknowledgement_signed_on"] = body["voluntary_acknowledgement_signed_on"]
    elif decision == "DECLINE":
        parcel["participation_status"] = "DECLINED"
        if current == "INTERESTED":
            _cancel_acquisition_pipeline(parcel)
            calc.recompute_federal_obligated(project)
            calc.recompute_holdout(project)
            calc.recompute_components(project)
            calc.recompute_ratio(project)
        else:
            calc.recompute_holdout(project)
            calc.recompute_ratio(project)
        project_moved = True
    else:
        parcel["participation_status"] = "WITHDRAWN"
        _cancel_acquisition_pipeline(parcel)
        for case in store.by_created(calc.parcel_cases(parcel["id"])):
            if case["status"] not in store.NON_TERMINAL_CASE_STATUSES:
                continue
            case["status"] = "CLAIM_DENIED_FINAL"
            store.touch(case)
        calc.recompute_federal_obligated(project)
        calc.recompute_participating(project)
        calc.recompute_ratio(project)
        project_moved = True

    store.touch(parcel)
    if project_moved and project is not None:
        store.touch(project)
    return web.respond_object(parcel)


# --------------------------------------------------------------------------
# Adjacency edges
# --------------------------------------------------------------------------

@bp.post("/parcel-adjacencies")
@endpoint("SubrecipientCoordinator")
def create_adjacency():
    body = web.get_body()
    project_id = web.req_string(body, "project_id")
    parcel_a_id = web.req_string(body, "parcel_a_id")
    parcel_b_id = web.req_string(body, "parcel_b_id")
    feet = web.decimal_field(body, "shared_boundary_feet", places=2,
                             minimum=Decimal(0), exclusive_min=True)
    web.scope_project(project_id)
    project = lookups.get_project(project_id)
    parcel_a = lookups.get_parcel(parcel_a_id)
    parcel_b = lookups.get_parcel(parcel_b_id)
    if parcel_a_id == parcel_b_id:
        fail("ERR_ADJACENCY_SELF_REFERENCE")
    if parcel_a["project_id"] != project_id or parcel_b["project_id"] != project_id:
        fail("ERR_PARCEL_PROJECT_MISMATCH")
    if project["status"] != "APPROVED":
        fail("ERR_PROJECT_NOT_APPROVED")
    pair = {parcel_a_id, parcel_b_id}
    for edge in store.adjacencies.values():
        if {edge["parcel_a_id"], edge["parcel_b_id"]} == pair:
            fail("ERR_DUPLICATE_ADJACENCY")

    record = store.new_record("ParcelAdjacency", {
        "project_id": project_id,
        "parcel_a_id": parcel_a_id,
        "parcel_b_id": parcel_b_id,
        "shared_boundary_feet": feet,
    }, versioned=False)
    store.adjacencies[record["id"]] = record
    calc.recompute_components(project)
    calc.recompute_ratio(project)
    store.touch(project)
    return web.respond_object(record, 201)


@bp.get("/parcel-adjacencies")
@endpoint("ProgramAdministrator", "SubrecipientCoordinator", "ComplianceMonitor")
def list_adjacencies():
    project_id = web.query_str("project_id")
    parcel_a_id = web.query_str("parcel_a_id")
    parcel_b_id = web.query_str("parcel_b_id")
    rows = list(store.adjacencies.values())
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if parcel_a_id is not None:
        rows = [r for r in rows if r["parcel_a_id"] == parcel_a_id]
    if parcel_b_id is not None:
        rows = [r for r in rows if r["parcel_b_id"] == parcel_b_id]
    return web.list_response(rows)


@bp.get("/parcel-adjacencies/<adjacency_id>")
@endpoint("ProgramAdministrator", "SubrecipientCoordinator", "ComplianceMonitor")
def read_adjacency(adjacency_id):
    return web.respond_object(lookups.get_adjacency(adjacency_id))
