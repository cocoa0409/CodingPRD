"""LiquidatedDamagesAssessment endpoints (PRD §3.8)."""

from flask import Blueprint, request

from db import store
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_NO_CULPABLE_DELAY,
    ERR_REDUCTION_NOT_SMALLER,
)
from middleware import (
    require_roles, json_body, req_field, as_int, as_datetime, paginate,
    sorted_items, touch, serialize, ANY_ROLE,
)
from response import ok_object, ok_list
from util import new_id, clock_iso, parse_dt
from routes.common import get_project, get_lda, ldas_of
from services.lda import compute_exposure, assess_lda

bp = Blueprint("lda", __name__)


def _opt_query(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None


@bp.route("/construction-projects/<pid>/ld-assessments", methods=["POST"],
          strict_slashes=False)
def create_lda(pid):
    require_roles("OwnerRepresentative")
    project = get_project(pid)
    data = json_body()
    start = as_datetime(req_field(data, "assessment_period_start"),
                        "assessment_period_start")
    end = as_datetime(req_field(data, "assessment_period_end"),
                      "assessment_period_end")
    culpable, gross = compute_exposure(
        project, parse_dt(start, "assessment_period_start"),
        parse_dt(end, "assessment_period_end"))
    now = clock_iso()
    lda = {
        "id": new_id(),
        "project_id": project["id"],
        "assessment_period_start": start,
        "assessment_period_end": end,
        "culpable_days": culpable,
        "gross_ld_cents": gross,
        "assessed_ld_cents": None,
        "prior_assessed_total_cents": None,
        "status": "PROPOSED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.ld_assessments[lda["id"]] = lda
    return ok_object(serialize(lda), 201)


@bp.route("/construction-projects/<pid>/ld-assessments", methods=["GET"],
          strict_slashes=False)
def list_ldas(pid):
    require_roles(*ANY_ROLE)
    project = get_project(pid)
    items = ldas_of(project["id"])
    status = _opt_query("status")
    if status is not None:
        items = [l for l in items if l["status"] == status]
    items = sorted_items(items)
    page, pg = paginate(items)
    return ok_list([serialize(l) for l in page], pg)


@bp.route("/construction-projects/<pid>/ld-assessments/<lid>", methods=["GET"],
          strict_slashes=False)
def get_one_lda(pid, lid):
    require_roles(*ANY_ROLE)
    _, lda = get_lda(pid, lid)
    return ok_object(serialize(lda))


@bp.route("/construction-projects/<pid>/ld-assessments/<lid>/assess",
          methods=["POST"], strict_slashes=False)
def assess(pid, lid):
    require_roles("OwnerRepresentative")
    project, lda = get_lda(pid, lid)
    json_body()
    if lda["status"] != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE, 409, "LDA is not in PROPOSED")
    # Evaluate the culpable-day precondition before any mutation (atomicity).
    culpable, _ = compute_exposure(
        project,
        parse_dt(lda["assessment_period_start"], "assessment_period_start"),
        parse_dt(lda["assessment_period_end"], "assessment_period_end"))
    if culpable <= 0:
        raise ApiError(ERR_NO_CULPABLE_DELAY, 422,
                       "LDA culpable_days is zero — nothing to assess")
    assess_lda(project, lda)
    return ok_object(serialize(lda))


@bp.route("/construction-projects/<pid>/ld-assessments/<lid>/waive",
          methods=["POST"], strict_slashes=False)
def waive(pid, lid):
    require_roles("OwnerRepresentative")
    project, lda = get_lda(pid, lid)
    json_body()
    if lda["status"] != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE, 409, "LDA is not in PROPOSED")
    lda["status"] = "WAIVED"
    lda["assessed_ld_cents"] = 0
    touch(lda)
    return ok_object(serialize(lda))


@bp.route("/construction-projects/<pid>/ld-assessments/<lid>/appeal",
          methods=["POST"], strict_slashes=False)
def appeal(pid, lid):
    require_roles("ContractorScheduler")
    project, lda = get_lda(pid, lid)
    json_body()
    if lda["status"] != "ASSESSED":
        raise ApiError(ERR_INVALID_STATE, 409, "LDA is not in ASSESSED")
    lda["status"] = "APPEALED"
    touch(lda)
    return ok_object(serialize(lda))


@bp.route("/construction-projects/<pid>/ld-assessments/<lid>/uphold",
          methods=["POST"], strict_slashes=False)
def uphold(pid, lid):
    require_roles("OwnerRepresentative")
    project, lda = get_lda(pid, lid)
    json_body()
    if lda["status"] != "APPEALED":
        raise ApiError(ERR_INVALID_STATE, 409, "LDA is not in APPEALED")
    lda["status"] = "UPHELD"
    touch(lda)
    return ok_object(serialize(lda))


@bp.route("/construction-projects/<pid>/ld-assessments/<lid>/reduce",
          methods=["POST"], strict_slashes=False)
def reduce(pid, lid):
    require_roles("OwnerRepresentative")
    project, lda = get_lda(pid, lid)
    data = json_body()
    reduced = as_int(req_field(data, "reduced_ld_cents"), "reduced_ld_cents")
    if lda["status"] != "APPEALED":
        raise ApiError(ERR_INVALID_STATE, 409, "LDA is not in APPEALED")
    if reduced >= (lda.get("assessed_ld_cents") or 0):
        raise ApiError(ERR_REDUCTION_NOT_SMALLER, 422,
                       "Reduced LD must be strictly less than currently "
                       "assessed")
    lda["assessed_ld_cents"] = reduced
    lda["status"] = "REDUCED"
    touch(lda)
    return ok_object(serialize(lda))


@bp.route("/construction-projects/<pid>/ld-assessments/<lid>/reverse",
          methods=["POST"], strict_slashes=False)
def reverse(pid, lid):
    require_roles("OwnerRepresentative")
    project, lda = get_lda(pid, lid)
    json_body()
    if lda["status"] != "APPEALED":
        raise ApiError(ERR_INVALID_STATE, 409, "LDA is not in APPEALED")
    lda["status"] = "REVERSED"
    lda["assessed_ld_cents"] = 0
    touch(lda)
    return ok_object(serialize(lda))
