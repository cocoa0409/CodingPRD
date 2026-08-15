"""EnergyModel endpoints (PRD 3.3): create (OCC-guarded) and the lock cascade."""
from decimal import Decimal

from flask import Blueprint, request

from db import DB
from errors import ApiError
from middleware import auth_headers, require_role
from response import ok, ok_list
from services import (
    MIN_IMPROVEMENT_PCT,
    get_model,
    get_project,
    locked_model,
    ser_model,
    sorted_created,
    stamp,
    touch,
)
from util import (
    MODELING_STANDARDS,
    MODEL_TYPES,
    as_enum,
    as_int,
    as_opt_bool,
    as_str,
    body,
    pagination_args,
    pct_round_2dp,
    required,
)

bp = Blueprint("energy_models", __name__)

_CREATE_STATES = {"REGISTERED", "STRATEGY_LOCKED", "DESIGN_REVIEWED", "CONSTRUCTION_REVIEWED"}


@bp.post("/energy-models")
def create_model():
    user_id, role = auth_headers()
    data = body()
    project_id = as_str(required(data, "project_id"), "project_id")
    model_type = as_enum(required(data, "model_type"), MODEL_TYPES, "model_type")
    modeling_standard = as_enum(
        required(data, "modeling_standard"), MODELING_STANDARDS, "modeling_standard"
    )
    modeled = as_int(
        required(data, "annual_energy_cost_modeled_cents"),
        "annual_energy_cost_modeled_cents",
    )
    if modeled <= 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "annual_energy_cost_modeled_cents must be > 0"
        )
    confirmed = as_int(
        required(data, "annual_energy_cost_confirmed_only_cents"),
        "annual_energy_cost_confirmed_only_cents",
    )
    if confirmed <= 0:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "annual_energy_cost_confirmed_only_cents must be > 0"
        )
    includes_unconfirmed = as_opt_bool(data, "includes_unconfirmed_measures", False)
    expected = as_int(
        required(data, "expected_project_version"), "expected_project_version"
    )
    require_role(role, {"EnergyModeler"})
    project = get_project(project_id)
    # OCC (stage 6) precedes the creation-time parent state gate (stage 7).
    if expected != project["version"]:
        raise ApiError(
            "ERR_STALE_PROJECT_VERSION",
            412,
            "expected_project_version does not match the current project version",
        )
    if project["status"] not in _CREATE_STATES:
        raise ApiError(
            "ERR_INVALID_PROJECT_STATE",
            409,
            "Energy models are not accepted in the current project state",
        )
    existing = [
        m["version_index"]
        for m in DB["energy_models"].values()
        if m["project_id"] == project["id"] and m["model_type"] == model_type
    ]
    rec = stamp(
        {
            "project_id": project["id"],
            "model_type": model_type,
            "modeling_standard": modeling_standard,
            "annual_energy_cost_modeled_cents": modeled,
            "annual_energy_cost_confirmed_only_cents": confirmed,
            "includes_unconfirmed_measures": includes_unconfirmed,
            "version_index": (max(existing) if existing else 0) + 1,
            "created_by": user_id,
            "status": "DRAFT",
            "improvement_pct_provisional": None,
            "improvement_pct_final": None,
        }
    )
    DB["energy_models"][rec["id"]] = rec
    touch(project)  # model creation mutates the project inventory (PRD 2.5)
    return ok(ser_model(rec), status=201)


@bp.get("/energy-models")
def list_models():
    auth_headers()
    project_id = request.args.get("project_id")
    model_type = request.args.get("model_type")
    status = request.args.get("status")
    created_by = request.args.get("created_by")
    items = list(DB["energy_models"].values())
    if project_id is not None:
        items = [m for m in items if m["project_id"] == project_id]
    if model_type is not None:
        items = [m for m in items if m["model_type"] == model_type]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    if created_by is not None:
        items = [m for m in items if m["created_by"] == created_by]
    items = sorted_created(items)
    limit, offset = pagination_args()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_model(m) for m in page], total, limit, offset)


@bp.get("/energy-models/<model_id>")
def get_one_model(model_id):
    auth_headers()
    return ok(ser_model(get_model(model_id)))


@bp.post("/energy-models/<model_id>/lock")
def lock_model(model_id):
    _user_id, role = auth_headers()
    body()
    require_role(role, {"EnergyModeler"})
    model = get_model(model_id)
    if model["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_MODEL_STATE", 409, "Only a DRAFT model can be locked")
    project = DB["projects"][model["project_id"]]
    provisional = None
    final = None
    if model["model_type"] == "PROPOSED":
        baseline = locked_model(project["id"], "BASELINE")
        if baseline is None:
            raise ApiError(
                "ERR_BASELINE_MODEL_NOT_LOCKED",
                409,
                "A proposed model cannot lock before a LOCKED baseline exists",
            )
        provisional = pct_round_2dp(
            baseline["annual_energy_cost_modeled_cents"]
            - model["annual_energy_cost_modeled_cents"],
            baseline["annual_energy_cost_modeled_cents"],
        )
        final = pct_round_2dp(
            baseline["annual_energy_cost_confirmed_only_cents"]
            - model["annual_energy_cost_confirmed_only_cents"],
            baseline["annual_energy_cost_confirmed_only_cents"],
        )
        if (
            project["compliance_path"] == "PERFORMANCE"
            and Decimal(str(final)) < MIN_IMPROVEMENT_PCT
        ):
            raise ApiError(
                "ERR_MINIMUM_IMPROVEMENT_NOT_MET",
                422,
                "PERFORMANCE path requires improvement_pct_final >= 5.00",
            )
    # Cascade link 1: supersede the previously LOCKED model of the same pair.
    previous = locked_model(project["id"], model["model_type"])
    if previous is not None:
        previous["status"] = "SUPERSEDED"
        touch(previous)
    model["status"] = "LOCKED"
    if model["model_type"] == "PROPOSED":
        model["improvement_pct_provisional"] = provisional
        model["improvement_pct_final"] = final
    touch(model)
    # Cascade links 2+3: stale pins; READY attempts demoted (one mutation each).
    if model["model_type"] == "PROPOSED" and previous is not None:
        for a in DB["credit_attempts"].values():
            if a["pinned_proposed_model_id"] == previous["id"]:
                a["has_stale_model_pin"] = True
                if a["status"] == "READY_FOR_SUBMITTAL":
                    a["status"] = "DOCUMENTATION_IN_PROGRESS"
                touch(a)
    return ok(ser_model(model))
