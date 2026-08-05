"""Registration: patients, coverages and laboratories (PRD 3.1)."""
from flask import Blueprint

import calc
import envelope
import guards
import nav
import pconst
import projections
from errors import ApiError
from store import db, sorted_rows
from util import ZERO, q2

bp = Blueprint("registry", __name__)

READ_ALL = ["FrontOffice", "Prosthodontist", "ClinicalDirector", "PlatformAdmin"]


# ===========================================================================
# Patient
# ===========================================================================
@bp.post("/prosthetics/patients")
@guards.endpoint(["FrontOffice", "PlatformAdmin"])
def create_patient(ctx):
    # Outside the global write gate: registration precedes any balance.
    guards.require_string(ctx, "full_name", "date_of_birth", "phone")  # rung 7
    row = db.create(
        "patients",
        {
            "full_name": ctx.body["full_name"],
            "date_of_birth": ctx.body["date_of_birth"],
            "phone": ctx.body["phone"],
        },
    )
    return envelope.created(projections.patient(row))


@bp.get("/prosthetics/patients/<patient_id>")
@guards.endpoint(READ_ALL + ["Patient"])
def get_patient(ctx, patient_id):
    guards.owner_patient_guard(ctx, patient_id)  # rung 3
    row = guards.path_row("patient_id", patient_id)  # rung 4
    return envelope.ok(projections.patient(row))


@bp.get("/prosthetics/patients")
@guards.endpoint(READ_ALL)
def list_patients(ctx):
    limit, offset = guards.pagination(ctx)
    rows = sorted_rows(db.patients.values())
    return envelope.listing(
        [projections.patient(r) for r in guards.paginate(rows, limit, offset)],
        limit,
        offset,
        len(rows),
    )


# ===========================================================================
# Coverage
# ===========================================================================
@bp.post("/prosthetics/coverages")
@guards.endpoint(["FrontOffice", "PlatformAdmin"])
def create_coverage(ctx):
    # Outside the global write gate: insurance enrolment precedes any balance.
    guards.body_fks(ctx, ["patient_id"])  # rung 6
    # rung 7
    guards.require_string(ctx, "patient_id", "carrier_name")
    rank = guards.require_enum_value(ctx, "rank")
    effective_date = guards.require_instant(ctx, "effective_date")
    annual_maximum = guards.optional_number(
        ctx, "annual_maximum_amount", pconst.COVERAGE_DEFAULT_ANNUAL_MAXIMUM
    )
    coinsurance = guards.optional_number(
        ctx, "coinsurance_major_rate", pconst.COVERAGE_DEFAULT_COINSURANCE_MAJOR_RATE
    )
    waiting_days = guards.optional_int(
        ctx, "waiting_period_days", pconst.COVERAGE_DEFAULT_WAITING_PERIOD_DAYS
    )
    replacement_months = guards.optional_int(
        ctx,
        "replacement_frequency_months",
        pconst.COVERAGE_DEFAULT_REPLACEMENT_FREQUENCY_MONTHS,
    )
    if "cob_convention" in ctx.body and ctx.body["cob_convention"] is not None:
        cob = guards.require_enum_value(ctx, "cob_convention")
    else:
        cob = "STANDARD"
    alternate_enabled = guards.optional_bool(ctx, "alternate_benefit_enabled", True)

    # rung 8 -- exhaustively routed enum fields on this endpoint
    guards.check_enum("rank", rank)
    guards.check_enum("cob_convention", cob)

    # rung 27 -- coordination-of-benefits rank uniqueness.
    # FRICTION POINT (PRD 2.10): the (patient_id, rank) pair is claimed by both
    # rung 7 and rung 27.  It is implemented here, at rung 27, so the dedicated
    # ERR_COB_RANK_CONFLICT code stays reachable, matching PRD 3.1's prose.
    for existing in nav.coverages_of_patient(ctx.body["patient_id"]):
        if existing["rank"] == rank:
            raise ApiError("ERR_COB_RANK_CONFLICT")

    row = db.create(
        "coverages",
        {
            "patient_id": ctx.body["patient_id"],
            "carrier_name": ctx.body["carrier_name"],
            "rank": rank,
            "effective_date": effective_date,
            "annual_maximum_amount": q2(annual_maximum),
            "coinsurance_major_rate": coinsurance,
            "waiting_period_days": waiting_days,
            "replacement_frequency_months": replacement_months,
            "cob_convention": cob,
            "alternate_benefit_enabled": alternate_enabled,
            "benefit_used_ytd": ZERO,
        },
    )
    return envelope.created(projections.coverage(row))


@bp.get("/prosthetics/coverages/<coverage_id>")
@guards.endpoint(["FrontOffice", "PlatformAdmin", "Prosthodontist"])
def get_coverage(ctx, coverage_id):
    row = guards.path_row("coverage_id", coverage_id)
    return envelope.ok(projections.coverage(row))


@bp.get("/prosthetics/coverages")
@guards.endpoint(["FrontOffice", "PlatformAdmin", "Prosthodontist"])
def list_coverages(ctx):
    limit, offset = guards.pagination(ctx)
    rows = sorted_rows(db.coverages.values())
    rows = guards.apply_filters(
        rows,
        ctx,
        [
            ("patient_id", "patient_id", None),
            ("rank", "rank", pconst.ENUMS["rank"]),
        ],
    )
    return envelope.listing(
        [projections.coverage(r) for r in guards.paginate(rows, limit, offset)],
        limit,
        offset,
        len(rows),
    )


# ===========================================================================
# DentalLab
# ===========================================================================
@bp.post("/prosthetics/labs")
@guards.endpoint(["PlatformAdmin"])
def create_lab(ctx):
    # Outside the global write gate: laboratory configuration is clinic-wide.
    guards.require_string(ctx, "lab_name")  # rung 7
    bench_lines = guards.optional_int(
        ctx,
        "bench_line_count",
        pconst.LAB_DEFAULT_BENCH_LINE_COUNT,
        pconst.LAB_BENCH_LINE_COUNT_MIN,
        pconst.LAB_BENCH_LINE_COUNT_MAX,
    )
    standard_days = guards.optional_int(
        ctx, "standard_turnaround_days", pconst.LAB_STANDARD_TURNAROUND_DAYS
    )
    rush_days = guards.optional_int(
        ctx, "rush_turnaround_days", pconst.LAB_RUSH_TURNAROUND_DAYS
    )
    row = db.create(
        "labs",
        {
            "lab_name": ctx.body["lab_name"],
            "bench_line_count": bench_lines,
            "standard_turnaround_days": standard_days,
            "rush_turnaround_days": rush_days,
            "credit_issued_total": ZERO,
            "credit_applied_total": ZERO,
            "credit_available_balance": ZERO,
        },
    )
    return envelope.created(projections.lab(row))


@bp.get("/prosthetics/labs/<lab_id>")
@guards.endpoint(["PlatformAdmin", "FrontOffice", "Prosthodontist", "LabTechnician"])
def get_lab(ctx, lab_id):
    row = guards.path_row("lab_id", lab_id)
    return envelope.ok(projections.lab(row))


@bp.get("/prosthetics/labs")
@guards.endpoint(["PlatformAdmin", "FrontOffice", "Prosthodontist"])
def list_labs(ctx):
    limit, offset = guards.pagination(ctx)
    rows = sorted_rows(db.labs.values())
    return envelope.listing(
        [projections.lab(r) for r in guards.paginate(rows, limit, offset)],
        limit,
        offset,
        len(rows),
    )
