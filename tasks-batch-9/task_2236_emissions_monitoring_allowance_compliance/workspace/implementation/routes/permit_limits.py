"""Permit limits and their rolling-average evaluations (PRD 3.8)."""

from flask import Blueprint

from constants import (
    API_PREFIX,
    AVERAGING_BASES,
    EVALUATION_STATUSES,
    LIMIT_UNITS,
    POLLUTANTS,
    ROLE_PREPARER,
    ROLE_REGULATORY_REVIEWER,
)
from db import base_record, db, public, public_list, sort_rows
from errors import fail
from lookup import get, limits_of_unit
from middleware import ANY_ROLE, authenticate
from response import array_response, object_response
from services.permits import evaluate_limit
from validation import (
    apply_pagination,
    body_dict,
    check_range,
    dt_field,
    enum_field,
    match_filters,
    num_field,
    pagination,
    query_filters,
)

bp = Blueprint("permit_limits", __name__)


@bp.route(API_PREFIX + "/units/<unit_id>/permit-limits", methods=["POST"])
def add_limit(unit_id):
    authenticate((ROLE_REGULATORY_REVIEWER,))
    body = body_dict()

    pollutant = enum_field(body, "pollutant", POLLUTANTS, required=True)
    limit_value = num_field(body, "limit_value", required=True)
    limit_units = enum_field(body, "limit_units", LIMIT_UNITS, required=True)
    averaging_basis = enum_field(body, "averaging_basis", AVERAGING_BASES, required=True)
    effective_raw, effective_dt = dt_field(body, "effective_from_utc", required=True)

    unit = get("unit", unit_id)

    check_range("limit_value", limit_value, minimum=0, min_exclusive=True)

    for existing in limits_of_unit(unit["id"]):
        if (
            existing["pollutant"] == pollutant
            and existing["averaging_basis"] == averaging_basis
            and existing["_effective_from"] == effective_dt
        ):
            fail(
                "ERR_DUPLICATE_PERMIT_LIMIT",
                "This unit already carries that pollutant, basis and effective instant.",
            )

    limit = base_record()
    limit.update(
        {
            "unit_id": unit["id"],
            "pollutant": pollutant,
            "limit_value": float(limit_value),
            "limit_units": limit_units,
            "averaging_basis": averaging_basis,
            "effective_from_utc": effective_raw,
            "evaluation_status": "NOT_EVALUATED",
            "current_rolling_value": None,
            "window_sample_count": 0,
            "window_evaluated_utc": None,
            "_effective_from": effective_dt,
            "_window_evaluated": None,
        }
    )
    db.permit_limits[limit["id"]] = limit
    return object_response(public(limit), 201)


@bp.route(API_PREFIX + "/permit-limits", methods=["GET"])
def list_limits():
    authenticate(ANY_ROLE)
    filters = query_filters(
        {
            "unit_id": "str",
            "pollutant": POLLUTANTS,
            "averaging_basis": AVERAGING_BASES,
            "evaluation_status": EVALUATION_STATUSES,
        }
    )
    limit_arg, offset = pagination()
    rows = match_filters(list(db.permit_limits.values()), filters)
    rows = sort_rows(rows)
    return array_response(
        public_list(apply_pagination(rows, limit_arg, offset)), limit_arg, offset, len(rows)
    )


@bp.route(API_PREFIX + "/permit-limits/<limit_id>", methods=["GET"])
def read_limit(limit_id):
    authenticate(ANY_ROLE)
    return object_response(public(get("permit_limit", limit_id)))


@bp.route(API_PREFIX + "/permit-limits/<limit_id>/evaluate", methods=["POST"])
def evaluate(limit_id):
    authenticate((ROLE_REGULATORY_REVIEWER, ROLE_PREPARER))
    body = body_dict()
    anchor_raw, anchor_dt = dt_field(body, "anchor_utc", required=True)

    limit = get("permit_limit", limit_id)
    evaluate_limit(limit, anchor_raw, anchor_dt)
    return object_response(public(limit))
