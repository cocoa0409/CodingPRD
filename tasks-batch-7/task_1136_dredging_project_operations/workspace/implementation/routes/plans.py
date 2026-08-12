"""DredgePlan endpoints (PRD 3.3): dredge type selection, production estimate,
submit/revision cycle, approval with OCC + interval gates."""
import uuid
from decimal import Decimal

from flask import Blueprint

from db import store
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_STALE_PROJECT_VERSION,
    ERR_INVALID_STATE,
    ERR_PLANT_ASSIGNMENT_OVERLAP,
    ERR_PLAN_WINDOW_INFEASIBLE,
    ERR_PLANT_UNAVAILABLE,
    ERR_PLAN_NOT_APPROVED,
)
from middleware import require_roles, ALL_ROLES
from response import ok
from routes.common import list_response
from services import serialize_plan, compute_estimates
from util import as_enum, as_str, check, get_body, new_entity, parse_dt, req_present, touch

bp = Blueprint("plans", __name__)


@bp.post("/dredge-plans")
@require_roles("ContractorOps")
def create_plan():
    body = get_body()
    # Existence (class 3), body FKs left-to-right: project_id then plant_id.
    project_id = body.get("project_id")
    if project_id is not None and project_id not in store.projects:
        raise ApiError(ERR_NOT_FOUND, "Project not found", 404)
    plant_id = body.get("plant_id")
    if plant_id is not None and plant_id not in store.plants:
        raise ApiError(ERR_NOT_FOUND, "DredgePlant not found", 404)
    project_id = as_str(req_present(body, "project_id"), "project_id")
    plant_id = as_str(req_present(body, "plant_id"), "plant_id")
    material = as_enum(
        req_present(body, "material_class"),
        "material_class",
        ["SAND", "SILT", "CLAY", "GRAVEL", "ROCK"],
    )
    start = parse_dt(req_present(body, "planned_start_utc"), "planned_start_utc")
    end = parse_dt(req_present(body, "planned_end_utc"), "planned_end_utc")
    check(end > start, "planned_end_utc must be > planned_start_utc")
    rec = new_entity(
        {
            "id": str(uuid.uuid4()),
            "project_id": project_id,
            "plant_id": plant_id,
            "material_class": material,
            "planned_start_utc": start,
            "planned_end_utc": end,
            "revision": 1,
            "status": "DRAFT",
            "_approved_seq": None,
        }
    )
    compute_estimates(rec)
    store.plans[rec["id"]] = rec
    return ok(serialize_plan(rec), 201)


def _get_plan(pid):
    plan = store.plans.get(pid)
    if plan is None:
        raise ApiError(ERR_NOT_FOUND, "DredgePlan not found", 404)
    return plan


@bp.get("/dredge-plans/<pid>")
@require_roles(*ALL_ROLES)
def get_plan(pid):
    return ok(serialize_plan(_get_plan(pid)))


@bp.get("/dredge-plans")
@require_roles(*ALL_ROLES)
def list_plans():
    return list_response(
        store.plans, serialize_plan, ["project_id", "plant_id", "status"]
    )


@bp.post("/dredge-plans/<pid>/submit")
@require_roles("ContractorOps")
def submit_plan(pid):
    plan = _get_plan(pid)
    if plan["status"] == "DRAFT":
        plan["status"] = "SUBMITTED"
    elif plan["status"] == "CHANGES_REQUESTED":
        # Revision cycle: bump revision and recompute estimates in case reaches
        # or plant changed.
        plan["revision"] += 1
        compute_estimates(plan)
        plan["status"] = "SUBMITTED"
    else:
        raise ApiError(
            ERR_INVALID_STATE,
            "Only a DRAFT or CHANGES_REQUESTED plan can be submitted",
            409,
        )
    touch(plan)
    return ok(serialize_plan(plan))


@bp.post("/dredge-plans/<pid>/request-changes")
@require_roles("OwnerEngineer")
def request_changes(pid):
    plan = _get_plan(pid)
    if plan["status"] != "SUBMITTED":
        raise ApiError(
            ERR_INVALID_STATE, "Only a SUBMITTED plan can have changes requested", 409
        )
    plan["status"] = "CHANGES_REQUESTED"
    touch(plan)
    return ok(serialize_plan(plan))


@bp.post("/dredge-plans/<pid>/approve")
@require_roles("OwnerEngineer")
def approve_plan(pid):
    plan = _get_plan(pid)
    project = store.projects[plan["project_id"]]
    body = get_body()

    # Class 4 (OCC): a provided, well-formed expected_project_version that does
    # not match the current Project.version -> 412.
    epv = body.get("expected_project_version")
    if epv is not None and isinstance(epv, int) and not isinstance(epv, bool):
        if epv != project["version"]:
            raise ApiError(
                ERR_STALE_PROJECT_VERSION,
                "expected_project_version %s does not match current Project.version %s"
                % (epv, project["version"]),
                412,
            )
    # Class 5 (shape): the OCC field is required on this endpoint.
    if epv is None or isinstance(epv, bool) or not isinstance(epv, int):
        raise ApiError(
            ERR_INVALID_REQUEST, "expected_project_version is required and must be an integer", 400
        )
    # Class 6 (state gates).
    if project["status"] not in ("PLANNED", "ACTIVE"):
        raise ApiError(
            ERR_INVALID_STATE, "Project must be PLANNED or ACTIVE to approve a plan", 409
        )
    if plan["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, "Only a SUBMITTED plan can be approved", 409)
    # Class 9 (temporal): HALF-OPEN assignment overlap against other APPROVED
    # plans of the same plant; touching endpoints do NOT conflict.
    for other in store.plans.values():
        if (
            other["id"] != plan["id"]
            and other["plant_id"] == plan["plant_id"]
            and other["status"] == "APPROVED"
        ):
            if (
                plan["planned_start_utc"] < other["planned_end_utc"]
                and other["planned_start_utc"] < plan["planned_end_utc"]
            ):
                raise ApiError(
                    ERR_PLANT_ASSIGNMENT_OVERLAP,
                    "Plan would assign the plant to two overlapping APPROVED plans",
                    409,
                )
    # Class 10 (capacity/aggregate): window feasibility vs risk-adjusted estimate.
    span_seconds = Decimal(
        str((plan["planned_end_utc"] - plan["planned_start_utc"]).total_seconds())
    )
    span_days = int(span_seconds // Decimal(86400))  # floor
    if span_days < plan["risk_adjusted_duration_days"]:
        raise ApiError(
            ERR_PLAN_WINDOW_INFEASIBLE,
            "Planned window of %s days is shorter than the risk-adjusted duration %s"
            % (span_days, plan["risk_adjusted_duration_days"]),
            422,
        )
    # Class 11 (referenced-entity state): plant availability, then ISSUED permit.
    plant = store.plants[plan["plant_id"]]
    if plant["status"] != "REGISTERED":
        raise ApiError(ERR_PLANT_UNAVAILABLE, "DredgePlant is not REGISTERED", 409)
    if not any(
        p["project_id"] == plan["project_id"] and p["status"] == "ISSUED"
        for p in store.permits.values()
    ):
        raise ApiError(ERR_PLAN_NOT_APPROVED, "No ISSUED Permit exists for the project", 409)
    # Side effects: create-with-supersede, then Project.version increment.
    for other in store.plans.values():
        if (
            other["id"] != plan["id"]
            and other["project_id"] == plan["project_id"]
            and other["status"] == "APPROVED"
        ):
            other["status"] = "SUPERSEDED"
            touch(other)
    plan["status"] = "APPROVED"
    plan["_approved_seq"] = store.next_seq()
    touch(plan)
    touch(project)  # OCC-observable version increment
    return ok(serialize_plan(plan))
