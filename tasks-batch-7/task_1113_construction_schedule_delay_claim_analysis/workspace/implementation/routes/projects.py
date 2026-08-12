"""ConstructionProject endpoints (PRD §3.1, §3.8)."""

from flask import Blueprint

from db import store
from errors import (
    ApiError,
    ERR_BASELINE_NOT_ACCEPTED,
    ERR_INVALID_STATE,
    ERR_ACTIVITIES_INCOMPLETE,
    ERR_CLAIMS_OPEN,
    ERR_ACCELERATION_OPEN,
    ERR_LD_OPEN,
)
from middleware import (
    require_roles, json_body, req_field, as_str, as_int, as_datetime,
    as_enum, paginate, sorted_items, touch, serialize, ANY_ROLE,
)
from response import ok_object, ok_list
from util import new_id, clock_iso, clock_now
from routes.common import (
    get_project, activities_of, latest_accepted_update,
    latest_accepted_baseline,
)
from services.lda import assess_lda
from util import parse_dt

bp = Blueprint("projects", __name__)

FLOAT_POLICIES = {"CONTRACTOR_OWNS", "OWNER_OWNS", "SHARED_FIRST_COME"}


def _accepted_baseline_exists(project_id):
    return latest_accepted_baseline(project_id) is not None


@bp.route("/construction-projects", methods=["POST"], strict_slashes=False)
def create_project():
    require_roles("ProjectControlsEngineer")
    data = json_body()
    name = as_str(req_field(data, "project_name"), "project_name")
    csd = as_datetime(req_field(data, "contract_start_date"),
                      "contract_start_date")
    ccd = as_datetime(req_field(data, "contract_completion_date"),
                      "contract_completion_date")
    rate = as_int(req_field(data, "liquidated_damages_daily_rate_cents"),
                  "liquidated_damages_daily_rate_cents")
    cap = as_int(req_field(data, "ld_cap_cents"), "ld_cap_cents")
    fop = as_enum(data.get("float_ownership_policy", "CONTRACTOR_OWNS"),
                  "float_ownership_policy", FLOAT_POLICIES)
    nwd = as_int(data.get("notice_window_days", 21), "notice_window_days")
    now = clock_iso()
    project = {
        "id": new_id(),
        "project_name": name,
        "contract_start_date": csd,
        "contract_completion_date": ccd,
        "current_completion_date": ccd,
        "liquidated_damages_daily_rate_cents": rate,
        "ld_cap_cents": cap,
        "float_ownership_policy": fop,
        "notice_window_days": nwd,
        "status": "PRECONSTRUCTION",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
        "_actual_sc_date": None,
    }
    store.projects[project["id"]] = project
    return ok_object(serialize(project), 201)


@bp.route("/construction-projects", methods=["GET"], strict_slashes=False)
def list_projects():
    require_roles(*ANY_ROLE)
    items = sorted_items(store.projects.values())
    page, pg = paginate(items)
    return ok_list([serialize(p) for p in page], pg)


@bp.route("/construction-projects/<pid>", methods=["GET"], strict_slashes=False)
def get_one_project(pid):
    require_roles(*ANY_ROLE)
    project = get_project(pid)
    return ok_object(serialize(project))


@bp.route("/construction-projects/<pid>/activate", methods=["POST"],
          strict_slashes=False)
def activate_project(pid):
    require_roles("ProjectControlsEngineer")
    project = get_project(pid)
    json_body()
    if project["status"] != "PRECONSTRUCTION":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Project is not in PRECONSTRUCTION")
    if not _accepted_baseline_exists(project["id"]):
        raise ApiError(ERR_BASELINE_NOT_ACCEPTED, 409,
                       "An ACCEPTED BASELINE schedule version is required")
    project["status"] = "ACTIVE"
    project["current_completion_date"] = project["contract_completion_date"]
    touch(project)
    return ok_object(serialize(project))


@bp.route("/construction-projects/<pid>/declare-substantial-completion",
          methods=["POST"], strict_slashes=False)
def declare_substantial_completion(pid):
    require_roles("OwnerRepresentative")
    project = get_project(pid)
    json_body()
    if project["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Project is not ACTIVE")
    latest_update = latest_accepted_update(project["id"])
    if latest_update is not None:
        for a in activities_of(latest_update["id"]):
            if a.get("percent_complete") != 100:
                raise ApiError(
                    ERR_ACTIVITIES_INCOMPLETE, 409,
                    "Every Activity in the latest ACCEPTED UPDATE must be at "
                    "percent_complete == 100")
    now = clock_now()
    project["status"] = "SUBSTANTIALLY_COMPLETE"
    project["_actual_sc_date"] = clock_iso()
    touch(project)
    # LD auto-assess at SC: every PROPOSED assessment whose period end falls
    # on or after the declaration date transitions to ASSESSED.
    from routes.common import ldas_of
    due = [l for l in ldas_of(project["id"]) if l["status"] == "PROPOSED"]
    due.sort(key=lambda l: (l.get("created_at", ""), l.get("_seq", 0)))
    for lda in due:
        if parse_dt(lda["assessment_period_end"],
                    "assessment_period_end") >= now:
            assess_lda(project, lda)
    return ok_object(serialize(project))


@bp.route("/construction-projects/<pid>/close", methods=["POST"],
          strict_slashes=False)
def close_project(pid):
    require_roles("OwnerRepresentative")
    project = get_project(pid)
    json_body()
    if project["status"] != "SUBSTANTIALLY_COMPLETE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Project is not SUBSTANTIALLY_COMPLETE")
    open_eots = [e for e in store.eot_requests.values()
                 if e["project_id"] == project["id"] and e["status"] not in
                 ("APPROVED", "PARTIALLY_APPROVED", "DENIED")]
    if open_eots:
        raise ApiError(ERR_CLAIMS_OPEN, 409,
                       "All EOT requests must be in a terminal state")
    open_dirs = [d for d in store.acceleration_directives.values()
                 if d["project_id"] == project["id"] and d["status"] not in
                 ("COMPLETED", "RESOLVED")]
    if open_dirs:
        raise ApiError(ERR_ACCELERATION_OPEN, 409,
                       "All acceleration directives must be in a terminal state")
    open_ldas = [l for l in store.ld_assessments.values()
                 if l["project_id"] == project["id"] and l["status"] not in
                 ("ASSESSED", "WAIVED", "OFFSET_BY_EOT", "UPHELD", "REDUCED",
                  "REVERSED")]
    if open_ldas:
        raise ApiError(ERR_LD_OPEN, 409,
                       "All LD assessments must be in a terminal state")
    project["status"] = "CLOSED"
    touch(project)
    return ok_object(serialize(project))
