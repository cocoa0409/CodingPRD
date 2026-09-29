"""Third-party reclamation cost estimates and their acceptance (PRD 3.2)."""

from flask import Blueprint

import constants as C
import engine
import serialization as ser
from db import base_row, days, db, now
from engine import bump
from errors import ApiError
from response import created_response, object_response
from routes._shared import (
    collection_filtered,
    require_permit_operator,
    require_permit_status,
    require_state,
)
from validation import (
    authorize,
    datetime_field,
    get_body,
    int_field,
    lookup,
    number_field,
    resolve,
    str_field,
)

bp = Blueprint("estimates", __name__)

LIST_FILTERS = [
    ("permit_id", "permit_id", None),
    ("status", "status", C.ESTIMATE_STATUSES),
]


@bp.post("/mining/reclamation-cost-estimates")
def create_estimate():
    user_id, role = authorize([C.ROLE_OPERATOR])
    body = get_body()
    permit_id = str_field(body, "permit_id")
    estimator_firm = str_field(body, "estimator_firm")
    estimator_license_no = str_field(body, "estimator_license_no")
    effective_date = datetime_field(body, "estimate_effective_date")
    direct_cost_per_acre = number_field(body, "direct_cost_per_acre", gt=0)

    permit = resolve(db.permits, permit_id, "ERR_PERMIT_NOT_FOUND")
    require_permit_operator(role, user_id, permit)
    require_permit_status(permit, C.PERMIT_STATUSES_ESTIMATE)

    # Band 12 — pricing effective in the future is nonsense.
    if effective_date > now():
        raise ApiError(
            "ERR_ESTIMATE_DATE_IN_FUTURE",
            "estimate_effective_date may not be later than the current logical clock.",
        )

    row = base_row()
    row.update(
        {
            "permit_id": permit_id,
            "estimator_firm": estimator_firm,
            "estimator_license_no": estimator_license_no,
            "estimate_effective_date": effective_date,
            "direct_cost_per_acre": direct_cost_per_acre,
            "status": "SUBMITTED",
            "accepted_at": None,
        }
    )
    db.estimates[row["id"]] = row
    return created_response(ser.estimate_out(row))


@bp.get("/mining/reclamation-cost-estimates/<estimate_id>")
def get_estimate(estimate_id):
    authorize(C.ROLES_OP_STAFF)
    row = lookup(db.estimates, estimate_id, "ERR_ESTIMATE_NOT_FOUND")
    return object_response(ser.estimate_out(row))


@bp.get("/mining/reclamation-cost-estimates")
def list_estimates():
    authorize(C.ROLES_OP_STAFF)
    return collection_filtered(db.estimates.values(), LIST_FILTERS, ser.estimate_out)


@bp.post("/mining/reclamation-cost-estimates/<estimate_id>/accept")
def accept_estimate(estimate_id):
    authorize([C.ROLE_PERMIT_REVIEWER])
    body = get_body()
    expected_version = int_field(body, "expected_permit_version")

    estimate = lookup(db.estimates, estimate_id, "ERR_ESTIMATE_NOT_FOUND")
    permit = db.permits[estimate["permit_id"]]

    # Band 8 — the stale-determination guard on the permit named by the estimate.
    if expected_version != permit["version"]:
        raise ApiError(
            "ERR_STALE_PERMIT_VERSION",
            "The permit has moved since it was last read; re-read its version.",
        )

    # Band 9 — the estimate's own state.
    require_state(estimate, "status", ["SUBMITTED"], "ERR_ESTIMATE_STATE_INVALID")

    # Band 10 — the permit's state.
    require_permit_status(permit, C.PERMIT_STATUSES_ESTIMATE)

    # Band 12 — three-year currency.
    if (now() - estimate["estimate_effective_date"]) > days(C.ESTIMATE_MAX_AGE_DAYS):
        raise ApiError(
            "ERR_ESTIMATE_EXPIRED", "The cost estimate is more than three years old."
        )

    # Any other accepted estimate on the same permit is superseded.
    for other in db.estimates.values():
        if (
            other["id"] != estimate["id"]
            and other["permit_id"] == permit["id"]
            and other["status"] == "ACCEPTED"
        ):
            other["status"] = "SUPERSEDED"
            bump(other)

    estimate["status"] = "ACCEPTED"
    estimate["accepted_at"] = now()
    bump(estimate)

    engine.rerun_bond_determination(permit)
    engine.recompute_posture(permit)
    bump(permit)

    return object_response(ser.estimate_out(estimate))
