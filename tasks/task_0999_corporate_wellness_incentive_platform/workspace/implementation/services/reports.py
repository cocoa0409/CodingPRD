"""AggregateReport endpoints (PRD §3.9)."""
from decimal import ROUND_HALF_UP, Decimal

from flask import Blueprint

from db import DB
from errors import ApiError
from middleware import require_roles
from response import success
from services import serializers
from services.common import (
    get_program_or_404, get_report_or_404, parse_body, require_fields,
    stamp_new, touch,
)

bp = Blueprint("reports", __name__)


def _round(value, places):
    return float(
        Decimal(value).quantize(
            Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP
        )
    )


@bp.post("/wellness/aggregate-reports")
@require_roles("BenefitsAdmin")
def create_report():
    body = parse_body()
    vals = require_fields(body, [
        ("program_id", "string", True),
        ("department", "string", True),
    ])
    program = get_program_or_404(vals["program_id"])
    if program["status"] == "SETTLED":
        raise ApiError(
            "ERR_PROGRAM_ALREADY_SETTLED",
            "No reports against a SETTLED program",
        )
    if program["status"] != "CLOSED":
        raise ApiError(
            "ERR_PROGRAM_NOT_CLOSED",
            "Report generation requires program status CLOSED",
        )
    employer = DB.employers[program["employer_id"]]
    cohort = []
    for enr in DB.enrollments.values():
        if enr["program_id"] != program["id"]:
            continue
        if enr["participation_status"] not in ("ACTIVE", "SUSPENDED", "TERMINATED"):
            continue
        emp = DB.employees[enr["employee_id"]]
        if emp["department"] != vals["department"]:
            continue
        cohort.append((enr, emp))
    cohort_size = len(cohort)
    # k-anonymity guard: nothing is persisted when the cohort is too small
    if cohort_size < employer["k_anonymity_threshold"]:
        raise ApiError(
            "ERR_COHORT_TOO_SMALL",
            "Report cohort_size is below the employer k_anonymity_threshold",
        )
    avg_settled = _round(
        sum(e["points_balance_settled"] for e, _ in cohort) / cohort_size, 2
    )
    participating = sum(
        1
        for e, _ in cohort
        if any(
            p["enrollment_id"] == e["id"] and p["status"] == "COMPLETED"
            for p in DB.participations.values()
        )
    )
    participation_rate = _round(participating / cohort_size, 4)
    tobacco_count = sum(1 for _, emp in cohort if emp["tobacco_attested"])
    tobacco_rate = _round(tobacco_count / cohort_size, 4)
    rec = stamp_new({
        "program_id": program["id"],
        "department": vals["department"],
        "cohort_size": cohort_size,
        "avg_settled_points": avg_settled,
        "participation_rate": participation_rate,
        "tobacco_rate": tobacco_rate,
        "status": "GENERATED",
    })
    DB.reports[rec["id"]] = rec
    return success(serializers.report(rec), status=201)


@bp.post("/wellness/aggregate-reports/<rid>/publish")
@require_roles("BenefitsAdmin")
def publish_report(rid):
    rep = get_report_or_404(rid)
    if rep["status"] != "GENERATED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a GENERATED report may be published"
        )
    program = DB.programs[rep["program_id"]]
    if program["status"] == "SETTLED":
        raise ApiError(
            "ERR_PROGRAM_ALREADY_SETTLED",
            "The program has settled; the report can no longer be published",
        )
    if program["status"] != "CLOSED":
        raise ApiError(
            "ERR_PROGRAM_NOT_CLOSED",
            "Publication requires program status CLOSED",
        )
    rep["status"] = "PUBLISHED"
    touch(rep)
    return success(serializers.report(rep))
