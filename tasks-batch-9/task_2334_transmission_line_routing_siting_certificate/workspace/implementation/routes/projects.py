"""Projects and the escrow ledger (PRD §3.1, §2.9)."""

from flask import Blueprint

import response as resp
from db import insert, store
from errors import ApiError
from middleware import ALL_ROLES, endpoint
from services import derive
from validation import (
    apply_filters,
    collection_list,
    find_path,
    get_body,
    paginate,
    req_dt,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("projects", __name__)

VOLTAGE_CLASSES = ("KV_138", "KV_345", "KV_500")


@bp.get("/siting/projects")
@endpoint(ALL_ROLES)
def list_projects():
    rows, pagination = collection_list(store.projects, ["stage", "jurisdiction_state"])
    return resp.listing(rows, pagination)


@bp.get("/siting/projects/<project_id>")
@endpoint(ALL_ROLES)
def read_project(project_id):
    return resp.ok(find_path(store.projects, project_id))


@bp.get("/siting/projects/<project_id>/planning-studies")
@endpoint(ALL_ROLES)
def list_project_studies(project_id):
    find_path(store.projects, project_id)
    rows = apply_filters(derive.studies_of_project(project_id), ["status", "project_id"])
    rows, pagination = paginate(rows)
    return resp.listing(rows, pagination)


@bp.get("/siting/projects/<project_id>/routes")
@endpoint(ALL_ROLES)
def list_project_routes(project_id):
    find_path(store.projects, project_id)
    rows = apply_filters(derive.routes_of_project(project_id), ["kind", "status", "project_id"])
    rows, pagination = paginate(rows)
    return resp.listing(rows, pagination)


@bp.post("/siting/projects")
@endpoint(["Developer"])
def create_project():
    body = get_body()
    name = req_str(body, "name")
    voltage_class = req_enum(body, "voltage_class", VOLTAGE_CLASSES)
    jurisdiction_state = req_str(body, "jurisdiction_state").strip()
    if len(jurisdiction_state) != 2 or not jurisdiction_state.isalpha():
        raise ApiError("ERR_INVALID_REQUEST", "Field 'jurisdiction_state' must be a two-letter state code.")
    target_energization_at = req_dt(body, "target_energization_at")

    row = insert(
        store.projects,
        {
            "name": name,
            "voltage_class": voltage_class,
            "jurisdiction_state": jurisdiction_state,
            "target_energization_at": target_energization_at,
            "stage": "PLANNING",
            "schedule_posture": "ON_TRACK",
            "right_of_way_hold": False,
            "escrow_funded_cents": 0,
            "escrow_balance_cents": 0,
            "escrow_disbursed_cents": 0,
            "easement_committed_cents": 0,
        },
    )
    return resp.created(row)


@bp.post("/siting/projects/<project_id>/escrow-deposits")
@endpoint(["Developer"])
def create_escrow_deposit(project_id):
    project = find_path(store.projects, project_id)
    body = get_body()
    amount_cents = req_int(body, "amount_cents", minimum=0)
    req_str(body, "reference")
    derive.apply(
        project,
        escrow_funded_cents=project["escrow_funded_cents"] + amount_cents,
        escrow_balance_cents=project["escrow_balance_cents"] + amount_cents,
    )
    return resp.created(project)
