"""ExpansionProject endpoints: hydraulic sizing, NPV gate and conversion (PRD 3.9)."""

from flask import Blueprint

import calc
import enums
import services as svc
from calc import D
from db import base_record, store, touch
from errors import fail
from middleware import endpoint, paginate
from routes.agreements import new_agreement
from validators import (bad, get_dt, get_enum, get_num, get_str, json_body,
                        present, query_enum, query_str)

bp = Blueprint("expansion", __name__, url_prefix="/district-energy")

READERS = ("SystemController", "NetworkEngineer", "BillingAnalyst")

REVISION_FIELDS = (
    ("requested_capacity_kw", "gt"),
    ("route_length_m", "gt"),
    ("assumed_annual_energy_mwh", "gt"),
    ("assumed_marginal_cost_per_mwh", "ge"),
    ("design_delta_t_c", "gt"),
)


@endpoint(bp, "/expansion-projects", ["POST"], ["NetworkEngineer"], status=201)
def create_project():
    body = json_body()
    loop_id = get_str(body, "loop_id")
    rate_schedule_id = get_str(body, "rate_schedule_id")
    candidate_customer_name = get_str(body, "candidate_customer_name")
    customer_class = get_enum(body, "customer_class", enums.CUSTOMER_CLASS)
    requested_capacity_kw = get_num(body, "requested_capacity_kw", gt=0)
    route_length_m = get_num(body, "route_length_m", gt=0)
    assumed_annual_energy_mwh = get_num(body, "assumed_annual_energy_mwh", gt=0)
    assumed_marginal_cost = get_num(body, "assumed_marginal_cost_per_mwh", ge=0)
    design_delta_t_c = get_num(body, "design_delta_t_c", gt=0)

    loop = svc.fk_get("loops", loop_id)
    rate = svc.fk_get("rate_schedules", rate_schedule_id)

    if customer_class != rate["customer_class"]:
        fail("ERR_CUSTOMER_CLASS_MISMATCH",
             "the tariff serves customer class '%s'" % rate["customer_class"])

    project = base_record()
    project.update({
        "loop_id": loop["id"],
        "rate_schedule_id": rate["id"],
        "candidate_customer_name": candidate_customer_name,
        "customer_class": customer_class,
        "requested_capacity_kw": requested_capacity_kw,
        "route_length_m": route_length_m,
        "assumed_annual_energy_mwh": assumed_annual_energy_mwh,
        "assumed_marginal_cost_per_mwh": assumed_marginal_cost,
        "design_delta_t_c": design_delta_t_c,
        "selected_diameter_mm": None,
        "design_flow_m3_per_h": 0.0,
        "estimated_capex": 0.0,
        "annual_net_margin": 0.0,
        "npv": 0.0,
        "project_state": "SCREENING",
    })
    store.projects[project["id"]] = project
    return project


@endpoint(bp, "/expansion-projects", ["GET"], READERS)
def list_projects():
    filters = {}
    loop_id = query_str("loop_id")
    rate_schedule_id = query_str("rate_schedule_id")
    project_state = query_enum("project_state", enums.PROJECT_STATE)
    if loop_id is not None:
        filters["loop_id"] = loop_id
    if rate_schedule_id is not None:
        filters["rate_schedule_id"] = rate_schedule_id
    if project_state is not None:
        filters["project_state"] = project_state
    return paginate(svc.where("projects", **filters))


@endpoint(bp, "/expansion-projects/<project_id>", ["GET"], READERS)
def get_project(project_id):
    return svc.path_get("projects", project_id)


@endpoint(bp, "/expansion-projects/<project_id>/size", ["POST"], ["NetworkEngineer"])
def size_project(project_id):
    body = json_body()
    revisions = {}
    for name, bound in REVISION_FIELDS:
        if bound == "gt":
            value = get_num(body, name, required=False, default=None, gt=0)
        else:
            value = get_num(body, name, required=False, default=None, ge=0)
        if value is not None:
            revisions[name] = value

    project = svc.path_get("projects", project_id)
    if project["project_state"] not in ("SCREENING", "SIZED"):
        fail("ERR_PROJECT_STATE_INVALID",
             "only a SCREENING or SIZED project can be sized")

    inputs = {}
    for name, bound in REVISION_FIELDS:
        inputs[name] = revisions.get(name, project[name])
        del bound

    rate = store.rate_schedules[project["rate_schedule_id"]]
    sizing = calc.expansion_sizing_and_npv(inputs, rate)
    if sizing is None:
        # Nothing is persisted when no standard diameter is hydraulically feasible.
        fail("ERR_NO_FEASIBLE_PIPE_SIZE",
             "no standard diameter satisfies the velocity and pressure-drop limits")

    project.update(inputs)
    project.update(sizing)
    project["project_state"] = "SIZED"
    touch(project)
    return project


@endpoint(bp, "/expansion-projects/<project_id>/decision", ["POST"],
          ["SystemController"])
def decide_project(project_id):
    body = json_body()
    decision = get_enum(body, "decision", enums.REVIEW_DECISION)
    if present(body, "decision_note"):
        get_str(body, "decision_note", min_len=0)

    project = svc.path_get("projects", project_id)
    state = project["project_state"]
    if state not in ("SIZED", "APPROVED"):
        fail("ERR_PROJECT_STATE_INVALID",
             "only a SIZED or APPROVED project can receive a decision")
    if decision == "APPROVE" and state != "SIZED":
        fail("ERR_PROJECT_STATE_INVALID",
             "only a SIZED project can be approved")

    if decision == "APPROVE":
        if D(project["npv"]) < D(0):
            fail("ERR_PROJECT_NPV_NEGATIVE",
                 "the project net present value %s is negative" % project["npv"])
        project["project_state"] = "APPROVED"
    else:
        project["project_state"] = "REJECTED"
    touch(project)
    return project


@endpoint(bp, "/expansion-projects/<project_id>/convert", ["POST"], ["BillingAnalyst"])
def convert_project(project_id):
    body = json_body()
    reserved_capacity_kw = get_num(body, "reserved_capacity_kw", gt=0)
    service_mode = get_enum(body, "service_mode", enums.SERVICE_MODE)
    start_raw, start_dt = get_dt(body, "service_start_date")
    end_raw, end_dt = get_dt(body, "service_end_date")
    customer_name = get_str(body, "customer_name", required=False, default=None)
    if not end_dt > start_dt:
        bad("service_end_date must be after service_start_date")

    project = svc.path_get("projects", project_id)
    if project["project_state"] != "APPROVED":
        fail("ERR_PROJECT_STATE_INVALID",
             "only an APPROVED project can be converted")

    loop = store.loops[project["loop_id"]]
    rate = store.rate_schedules[project["rate_schedule_id"]]
    new_agreement(loop, rate,
                  customer_name or project["candidate_customer_name"],
                  project["customer_class"], reserved_capacity_kw, service_mode,
                  start_raw, start_dt, end_raw, end_dt)

    project["project_state"] = "CONVERTED"
    touch(project)
    return project
