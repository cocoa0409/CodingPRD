"""AccelerationDirective endpoints (PRD §3.7)."""

from flask import Blueprint, request

from db import store
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_COST_DATA_MISSING,
)
from middleware import (
    require_roles, json_body, req_field, as_str, as_int, as_datetime,
    paginate, sorted_items, touch, serialize, ANY_ROLE,
)
from response import ok_object, ok_list
from util import new_id, clock_iso, parse_dt
from routes.common import get_project, get_directive

bp = Blueprint("acceleration", __name__)

RECOVERY_VARIANTS = {"ACTUAL_COST", "MEASURED_MILE"}


def _opt_query(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None


@bp.route("/construction-projects/<pid>/acceleration-directives",
          methods=["POST"], strict_slashes=False)
def create_directive(pid):
    require_roles("OwnerRepresentative")
    project = get_project(pid)
    data = json_body()
    ref = as_str(req_field(data, "directive_reference"),
                 "directive_reference")
    directed = as_datetime(req_field(data, "directed_completion_date"),
                           "directed_completion_date")
    now = clock_iso()
    directive = {
        "id": new_id(),
        "project_id": project["id"],
        "directive_reference": ref,
        "issued_at": now,
        "directed_completion_date": directed,
        "baseline_completion_date": None,
        "days_to_recover": None,
        "actual_cost_cents": None,
        "measured_mile_cost_cents": None,
        "recovered_cost_cents": None,
        "recovery_variant": None,
        "status": "ISSUED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.acceleration_directives[directive["id"]] = directive
    return ok_object(serialize(directive), 201)


@bp.route("/construction-projects/<pid>/acceleration-directives",
          methods=["GET"], strict_slashes=False)
def list_directives(pid):
    require_roles(*ANY_ROLE)
    project = get_project(pid)
    items = [d for d in store.acceleration_directives.values()
             if d["project_id"] == project["id"]]
    status = _opt_query("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items = sorted_items(items)
    page, pg = paginate(items)
    return ok_list([serialize(d) for d in page], pg)


@bp.route("/construction-projects/<pid>/acceleration-directives/<aid>",
          methods=["GET"], strict_slashes=False)
def get_one_directive(pid, aid):
    require_roles(*ANY_ROLE)
    _, directive = get_directive(pid, aid)
    return ok_object(serialize(directive))


@bp.route(
    "/construction-projects/<pid>/acceleration-directives/<aid>/acknowledge",
    methods=["POST"], strict_slashes=False)
def acknowledge_directive(pid, aid):
    require_roles("ContractorScheduler")
    project, directive = get_directive(pid, aid)
    json_body()
    if directive["status"] != "ISSUED":
        raise ApiError(ERR_INVALID_STATE, 409, "Directive is not in ISSUED")
    # Freeze the reference point: snapshot the current completion date and
    # compute days_to_recover (positive = acceleration genuinely demanded).
    directive["baseline_completion_date"] = project["current_completion_date"]
    delta = parse_dt(project["current_completion_date"],
                     "current_completion_date") - parse_dt(
        directive["directed_completion_date"], "directed_completion_date")
    directive["days_to_recover"] = delta.days
    directive["status"] = "ACKNOWLEDGED"
    touch(directive)
    return ok_object(serialize(directive))


@bp.route(
    "/construction-projects/<pid>/acceleration-directives/<aid>/begin-performance",
    methods=["POST"], strict_slashes=False)
def begin_performance(pid, aid):
    require_roles("ContractorScheduler")
    project, directive = get_directive(pid, aid)
    json_body()
    if directive["status"] != "ACKNOWLEDGED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Directive is not in ACKNOWLEDGED")
    directive["status"] = "PERFORMING"
    touch(directive)
    return ok_object(serialize(directive))


@bp.route(
    "/construction-projects/<pid>/acceleration-directives/<aid>/complete",
    methods=["POST"], strict_slashes=False)
def complete_directive(pid, aid):
    require_roles("ContractorScheduler")
    project, directive = get_directive(pid, aid)
    data = json_body()
    if directive["status"] != "PERFORMING":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Directive is not in PERFORMING")
    if "actual_cost_cents" not in data or data.get("actual_cost_cents") is None \
            or "measured_mile_cost_cents" not in data \
            or data.get("measured_mile_cost_cents") is None:
        raise ApiError(ERR_COST_DATA_MISSING, 422,
                       "Both actual_cost_cents and measured_mile_cost_cents "
                       "must be supplied at completion")
    actual = as_int(data["actual_cost_cents"], "actual_cost_cents")
    measured = as_int(data["measured_mile_cost_cents"],
                      "measured_mile_cost_cents")
    directive["actual_cost_cents"] = actual
    directive["measured_mile_cost_cents"] = measured
    # Owner selects the recovery variant at completion; default ACTUAL_COST
    # recovers the documented actual amount.
    directive["recovery_variant"] = "ACTUAL_COST"
    directive["recovered_cost_cents"] = actual
    directive["status"] = "COMPLETED"
    touch(directive)
    return ok_object(serialize(directive))


@bp.route(
    "/construction-projects/<pid>/acceleration-directives/<aid>/dispute",
    methods=["POST"], strict_slashes=False)
def dispute_directive(pid, aid):
    require_roles("ContractorScheduler")
    project, directive = get_directive(pid, aid)
    json_body()
    if directive["status"] != "PERFORMING":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Directive is not in PERFORMING")
    directive["status"] = "DISPUTED"
    touch(directive)
    return ok_object(serialize(directive))


@bp.route(
    "/construction-projects/<pid>/acceleration-directives/<aid>/negotiate",
    methods=["POST"], strict_slashes=False)
def negotiate_directive(pid, aid):
    require_roles("OwnerRepresentative")
    project, directive = get_directive(pid, aid)
    json_body()
    if directive["status"] != "DISPUTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Directive is not in DISPUTED")
    directive["status"] = "UNDER_NEGOTIATION"
    touch(directive)
    return ok_object(serialize(directive))


@bp.route(
    "/construction-projects/<pid>/acceleration-directives/<aid>/resolve",
    methods=["POST"], strict_slashes=False)
def resolve_directive(pid, aid):
    require_roles("OwnerRepresentative")
    project, directive = get_directive(pid, aid)
    data = json_body()
    if directive["status"] != "UNDER_NEGOTIATION":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Directive is not in UNDER_NEGOTIATION")
    if "recovery_variant" not in data or data.get("recovery_variant") is None \
            or "recovered_cost_cents" not in data \
            or data.get("recovered_cost_cents") is None:
        raise ApiError(ERR_COST_DATA_MISSING, 422,
                       "Both recovery_variant and recovered_cost_cents must "
                       "be supplied at resolution")
    variant = data["recovery_variant"]
    if not isinstance(variant, str) or variant not in RECOVERY_VARIANTS:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "recovery_variant must be ACTUAL_COST or MEASURED_MILE")
    recovered = as_int(data["recovered_cost_cents"], "recovered_cost_cents")
    directive["recovery_variant"] = variant
    directive["recovered_cost_cents"] = recovered
    directive["status"] = "RESOLVED"
    touch(directive)
    return ok_object(serialize(directive))
