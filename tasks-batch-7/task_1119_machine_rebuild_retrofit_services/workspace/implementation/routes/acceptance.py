"""AcceptanceTest endpoints (PRD §3.6)."""

from flask import Blueprint, request

from calc import evaluate_acceptance, fail_surcharge
from db import bump, new_record, sorted_records, store
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_OPEN_ACCEPTANCE_TEST,
    ERR_PROJECT_NOT_AWAITING_ACCEPTANCE,
    ERR_SEGREGATION_OF_DUTIES,
)
from middleware import forbidden, require_roles
from response import list_response, success
from serializers import serialize, serialize_list
from services import create_training_record, park_planned_stages, project_tests
from util import (
    get_body,
    pagination_params,
    paginate,
    req_number,
    req_samples,
)
from routes.common import check_customer_ownership, customer_owns, get_or_404
import constants as C

bp = Blueprint("acceptance", __name__)


@bp.post("/api/projects/<pid>/acceptance-tests")
@require_roles("QualityInspector")
def create_acceptance_test(user_id, role, pid):
    project = get_or_404(store.projects, pid, "project")
    # Segregation of duties (gate 2): scheduler != assigned rebuild engineer.
    if project["assigned_engineer_id"] is not None and project["assigned_engineer_id"] == user_id:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "the acceptance inspector must differ from the project's assigned engineer",
            403,
        )
    if project["work_status"] != "AWAITING_ACCEPTANCE":
        raise ApiError(
            ERR_PROJECT_NOT_AWAITING_ACCEPTANCE,
            "project must be AWAITING_ACCEPTANCE to schedule a test",
            409,
        )
    for t in project_tests(pid):
        if t["status"] == "SCHEDULED":
            raise ApiError(
                ERR_OPEN_ACCEPTANCE_TEST,
                "another acceptance test of this project is still SCHEDULED",
                409,
            )
    rec = new_record(
        {
            "project_id": pid,
            "inspector_id": user_id,
            "attempt_number": 1 + len(project_tests(pid)),
            "samples_microns": None,
            "repeatability_microns": None,
            "evaluation_variant": None,
            "max_abs_sample_microns": None,
            "statistic_value": None,
            "status": "SCHEDULED",
        }
    )
    store.tests[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp.get("/api/acceptance-tests/<tid>")
@require_roles("QualityInspector", "ProjectManager", "Customer", "PlatformAdmin")
def get_acceptance_test(user_id, role, tid):
    rec = get_or_404(store.tests, tid, "acceptance test")
    check_customer_ownership(user_id, role, "test", rec)
    return success(serialize(rec))


@bp.get("/api/acceptance-tests")
@require_roles("QualityInspector", "ProjectManager", "Customer", "PlatformAdmin")
def list_acceptance_tests(user_id, role):
    limit, offset = pagination_params()
    items = sorted_records(store.tests)
    project_filter = request.args.get("project_id")
    if project_filter is not None:
        items = [t for t in items if t["project_id"] == project_filter]
    if role == "Customer":
        items = [t for t in items if customer_owns(user_id, "test", t)]
    page, meta = paginate(items, limit, offset)
    return list_response(serialize_list(page), meta)


@bp.post("/api/acceptance-tests/<tid>/record")
@require_roles("QualityInspector")
def record_acceptance_test(user_id, role, tid):
    test = get_or_404(store.tests, tid, "acceptance test")
    # Ownership: only the scheduling inspector records the result.
    if test["inspector_id"] != user_id:
        raise forbidden("only the scheduling inspector may record this test")
    body = get_body()
    samples = req_samples(body, "samples_microns", C.N_SAMPLES)
    repeatability = req_number(body, "repeatability_microns", minimum=0)
    if test["status"] != "SCHEDULED":
        raise ApiError(
            ERR_INVALID_STATE,
            f"acceptance test in status {test['status']} cannot be recorded",
            409,
        )
    project = store.projects[test["project_id"]]
    variant, max_abs, statistic, passed = evaluate_acceptance(
        samples, repeatability, project["decision"]
    )
    test["samples_microns"] = samples
    test["repeatability_microns"] = repeatability
    test["evaluation_variant"] = variant
    test["max_abs_sample_microns"] = max_abs
    test["statistic_value"] = statistic
    if passed:
        test["status"] = "PASSED"
        bump(test)
        # Acceptance cascade: AWAITING_ACCEPTANCE -> ACCEPTED.
        project["work_status"] = "ACCEPTED"
        project["consecutive_fail_count"] = 0
        project["accepted_positioning_microns"] = max_abs
        bump(project)
        # Bubble-up: TrainingRecord auto-created in PLANNED.
        create_training_record(project)
    else:
        test["status"] = "FAILED"
        bump(test)
        # Rework cascade: counters + 5% surcharge; destination depends on streak.
        project["consecutive_fail_count"] += 1
        project["rework_count"] += 1
        project["rework_cost_cents"] += fail_surcharge(project["quote_price_cents"])
        if project["consecutive_fail_count"] >= 3:
            project["work_status"] = "ESCALATED"
        else:
            project["work_status"] = "REWORK"
        bump(project)
        park_planned_stages(project["id"])
    return success(serialize(test))
