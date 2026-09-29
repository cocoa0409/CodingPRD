"""Back-wage exposure estimates (PRD 3.8)."""
from flask import Blueprint

import db
from constants import BACK_WAGE_METHODS
from errors import fail
from middleware import body, endpoint
from response import success
from services import calculations, derive, lookup, serialize
from validation import req_enum, req_int, req_str

bp = Blueprint("back_wage_estimates", __name__)


@bp.post("/back-wage-estimates")
@endpoint(["CompensationManager"])
def create_estimate():
    payload = body()
    case_id = req_str(payload, "reclassification_case_id")
    method = req_enum(payload, "method", BACK_WAGE_METHODS)
    expected_version = req_int(payload, "expected_reclassification_case_version")

    # rank 5: foreign key
    case = lookup.case(case_id)

    # rank 9: stale-read protection (PRD 2.9)
    if expected_version != case["version"]:
        fail("ERR_STALE_CASE_VERSION")

    position = lookup.position(case["position_id"])
    project = derive.project_of_position(position)
    figures = calculations.back_wage_exposure(position, project, method)

    # only one estimate is ever live per case
    previous = derive.active_estimate_of_case(case["id"])
    if previous is not None:
        previous["status"] = "SUPERSEDED"
        db.touch(previous)

    row = db.make_row(
        reclassification_case_id=case["id"],
        method=method,
        status="ACTIVE",
        **figures
    )
    db.back_wage_estimates[row["id"]] = row

    # the case's exposure and the engagement rollup both move
    db.touch(case)
    return success(serialize.back_wage_estimate(row), 201)
