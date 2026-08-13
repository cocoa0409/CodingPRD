"""Alignment runs and attribution records."""
from datetime import datetime, timedelta

from flask import Blueprint, request

import db
from errors import (ApiError, not_found, ERR_STALE_VERSION,
                    ERR_PERIOD_NOT_OPEN, ERR_ALIGNMENT_WINDOW_OVERLAP,
                    ERR_DATE_OUTSIDE_PERIOD)
from middleware import require_roles, ROLE_ACO_ADMIN, ALL_DOMAIN_ROLES
from response import success, list_success
from serializers import alignment_run_out, attribution_record_out
from services import calc
from validate import get_json_body, validate_body

bp = Blueprint("attribution", __name__)

RUN_SPEC = {
    "methodology": {"type": "enum", "enum": ["PROSPECTIVE", "RETROSPECTIVE"],
                    "required": True},
    "window_start_date": {"type": "date", "required": True},
    "window_end_date": {"type": "date", "required": True},
    "expected_agreement_period_version": {"type": "int", "required": True},
}


@bp.post("/aco/agreement-periods/<period_id>/alignment-runs")
def create_alignment_run(period_id):
    require_roles([ROLE_ACO_ADMIN])
    body = validate_body(get_json_body(), RUN_SPEC)
    period = db.periods.get(period_id)
    if period is None:
        raise not_found("Agreement period not found")
    # OCC (priority 5) precedes period posture (priority 6).
    if body["expected_agreement_period_version"] != period["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_agreement_period_version does not match the "
                       "period's current version")
    if period["status"] != "OPEN":
        raise ApiError(ERR_PERIOD_NOT_OPEN, 409,
                       "Alignment runs require an OPEN period")
    # Window overlap (priority 10): same (period, methodology), half-open
    # semantics -- windows that merely touch at a boundary do not conflict.
    for existing in db.alignment_runs.values():
        if (existing["agreement_period_id"] == period_id
                and existing["methodology"] == body["methodology"]
                and existing["status"] in ("COMPLETED", "LOCKED")):
            if (body["window_start_date"] < existing["window_end_date"]
                    and existing["window_start_date"] < body["window_end_date"]):
                raise ApiError(
                    ERR_ALIGNMENT_WINDOW_OVERLAP, 409,
                    "Alignment window overlaps an existing run for this "
                    "period and methodology")
    # Window placement per methodology (priority 11).
    if body["methodology"] == "PROSPECTIVE":
        if not body["window_end_date"] <= period["performance_start_date"]:
            raise ApiError(
                ERR_DATE_OUTSIDE_PERIOD, 422,
                "PROSPECTIVE window_end_date must fall on or before "
                "performance_start_date")
    else:  # RETROSPECTIVE
        end_plus_one = (datetime.strptime(period["performance_end_date"], "%Y-%m-%d")
                        + timedelta(days=1)).strftime("%Y-%m-%d")
        if not (body["window_start_date"] >= period["performance_start_date"]
                and body["window_end_date"] <= end_plus_one):
            raise ApiError(
                ERR_DATE_OUTSIDE_PERIOD, 422,
                "RETROSPECTIVE window must lie within the performance span "
                "(end may extend at most one day past performance_end_date)")

    run = db.stamp_new({
        "id": db.new_id(),
        "agreement_period_id": period["id"],
        "methodology": body["methodology"],
        "window_start_date": body["window_start_date"],
        "window_end_date": body["window_end_date"],
        "records_created_count": 0,
        "status": "COMPLETED",
    })
    db.alignment_runs[run["id"]] = run
    run["records_created_count"] = calc.run_attribution(period, run)
    calc.supersede_prior_runs(period["id"], run["methodology"], run["id"])
    db.bump(period)
    return success(alignment_run_out(run), 201)


@bp.get("/aco/alignment-runs/<run_id>")
def get_alignment_run(run_id):
    require_roles(ALL_DOMAIN_ROLES)
    run = db.alignment_runs.get(run_id)
    if run is None:
        raise not_found("Alignment run not found")
    return success(alignment_run_out(run))


@bp.get("/aco/alignment-runs")
def list_alignment_runs():
    require_roles(ALL_DOMAIN_ROLES)
    items = list(db.alignment_runs.values())
    for param in ("agreement_period_id", "methodology", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [r for r in items if r[param] == value]
    items.sort(key=lambda r: r["created_at"])
    return list_success([alignment_run_out(r) for r in items])


@bp.get("/aco/attribution-records/<record_id>")
def get_attribution_record(record_id):
    require_roles(ALL_DOMAIN_ROLES)
    record = db.attribution_records.get(record_id)
    if record is None:
        raise not_found("Attribution record not found")
    return success(attribution_record_out(record))


@bp.get("/aco/attribution-records")
def list_attribution_records():
    require_roles(ALL_DOMAIN_ROLES)
    items = list(db.attribution_records.values())
    for param in ("agreement_period_id", "beneficiary_id", "alignment_run_id",
                  "participant_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [r for r in items if r[param] == value]
    items.sort(key=lambda r: r["created_at"])
    return list_success([attribution_record_out(r) for r in items])
