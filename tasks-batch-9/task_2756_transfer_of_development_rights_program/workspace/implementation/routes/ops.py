"""Program evaluations plus the clock and compliance-sweep operations (PRD 2.5, 3.9, 3.10)."""

from flask import Blueprint

import serializers
from core import day_of, db, new_record, now, respond_object, set_clock, touch
from errors import fail
from listing import match, paged
from middleware import ADMIN, ALL_ROLES, require_roles
from services import calc
from validators import body, field_datetime, field_enum, filter_enum

bp = Blueprint("ops", __name__)

WEIGHTINGS = ("ACREAGE_WEIGHTED", "PARCEL_COUNT_WEIGHTED")
EVAL_STATUSES = ("COMPUTED", "SUPERSEDED")


@bp.post("/tdr/_clock/set_current_utc")
def set_current_utc():
    require_roles(ADMIN)
    data = body()
    current_utc = field_datetime(data, "current_utc")
    set_clock(current_utc)
    return respond_object({})


@bp.post("/tdr/_ops/compliance-sweep")
def compliance_sweep():
    require_roles(ADMIN)
    body()
    clock = now()
    for inspection in sorted(db.monitoring_inspections.values(), key=lambda r: (r["created_at"], r["_seq"])):
        if inspection["status"] != "CURE_PENDING":
            continue
        deadline = inspection["cure_deadline"]
        if deadline is None or not (deadline < clock):
            continue
        inspection["status"] = "ESCALATED"
        inspection["escalated_at"] = clock
        touch(inspection)
        easement = db.conservation_easements.get(inspection["conservation_easement_id"])
        if easement is not None and easement["compliance_status"] in ("VIOLATION_NOTICED", "UNDER_CURE"):
            easement["compliance_status"] = "ESCALATED"
            easement["prior_violation_count"] = int(easement["prior_violation_count"]) + 1
            touch(easement)
    return respond_object({})


@bp.post("/tdr/evaluations")
def create_evaluation():
    require_roles(ADMIN)
    data = body()
    period_start = field_datetime(data, "period_start")
    period_end = field_datetime(data, "period_end")
    equity_weighting = field_enum(data, "equity_weighting", WEIGHTINGS)
    if period_start > period_end:
        fail("ERR_INVALID_REQUEST", "period_start must not be after period_end")

    start = day_of(period_start)
    end = day_of(period_end)
    superseded = []
    for row in db.program_evaluations.values():
        if row["status"] != "COMPUTED":
            continue
        other_start = day_of(row["period_start"])
        other_end = day_of(row["period_end"])
        if start == other_start and end == other_end:
            superseded.append(row)
            continue
        if start <= other_end and other_start <= end:
            fail("ERR_EVALUATION_PERIOD_OVERLAP", "the period partially overlaps evaluation %s" % row["id"])

    metrics = calc.program_evaluation_metrics(period_start, period_end, equity_weighting)

    for row in superseded:
        row["status"] = "SUPERSEDED"
        touch(row)

    fields = {
        "period_start": period_start,
        "period_end": period_end,
        "equity_weighting": equity_weighting,
        "status": "COMPUTED",
    }
    fields.update(metrics)
    rec = new_record(fields)
    db.program_evaluations[rec["id"]] = rec
    return respond_object(serializers.program_evaluation(rec), 201)


@bp.get("/tdr/evaluations/<evaluation_id>")
def get_evaluation(evaluation_id):
    require_roles(*ALL_ROLES)
    row = db.program_evaluations.get(evaluation_id)
    if row is None:
        fail("ERR_PROGRAM_EVALUATION_NOT_FOUND", "program evaluation %s does not exist" % evaluation_id)
    return respond_object(serializers.program_evaluation(row))


@bp.get("/tdr/evaluations")
def list_evaluations():
    require_roles(*ALL_ROLES)
    rows = match(
        list(db.program_evaluations.values()),
        status=filter_enum("status", EVAL_STATUSES),
        equity_weighting=filter_enum("equity_weighting", WEIGHTINGS),
    )
    return paged(rows, serializers.program_evaluation)
