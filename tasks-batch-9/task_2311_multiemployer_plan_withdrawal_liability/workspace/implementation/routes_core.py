"""Plans, controlled groups, employers, valuations, contribution history, clock."""

from flask import Blueprint

import calc
import serialize
import services as svc
from clockutil import add_days, fmt, now, parse_iso
from db import db
from errors import fail, invalid
from listing import int_filter, paged, str_filters
from response import created, obj
from validate import (ANY_ROLE, authorize, body, field_bool, field_datetime,
                      field_enum, field_int, field_str, present)

bp = Blueprint("core", __name__)

INDUSTRIES = ("GENERAL", "CONSTRUCTION", "ENTERTAINMENT", "TRUCKING")
ALLOCATION_METHODS = ("PRESUMPTIVE", "MODIFIED_PRESUMPTIVE", "ROLLING_5",
                      "DIRECT_ATTRIBUTION")
DE_MINIMIS_VARIANTS = ("STATUTORY", "PLAN_ELECTED_HIGH")
COMMON_CONTROL_BASES = ("PARENT_SUBSIDIARY", "BROTHER_SISTER", "COMBINED")
COVERED_WORK_STATUSES = ("PERFORMING", "CEASED")

YEAR_MIN = 1900
YEAR_MAX = 2200


# --------------------------------------------------------------------------
# Plan
# --------------------------------------------------------------------------

@bp.post("/plans")
def create_plan():
    authorize(("FundAdministrator",))
    data = body()
    fields = {
        "name": field_str(data, "name", required=True, min_len=1, max_len=200),
        "industry": field_enum(data, "industry", INDUSTRIES, default="GENERAL"),
        "allocation_method": field_enum(data, "allocation_method",
                                        ALLOCATION_METHODS, default="PRESUMPTIVE"),
        "de_minimis_variant": field_enum(data, "de_minimis_variant",
                                         DE_MINIMIS_VARIANTS, default="STATUTORY"),
        "interest_rate_bps": field_int(data, "interest_rate_bps", required=True,
                                       minimum=1, maximum=3000),
        "unattributable_uvb_cents": field_int(data, "unattributable_uvb_cents",
                                              default=0, minimum=0),
        "mass_withdrawal_declared": field_bool(data, "mass_withdrawal_declared",
                                               default=False),
        "employer_count": 0,
        "issued_assessment_count": 0,
    }
    return created(serialize.plan(svc.new_row(db.plans, fields)))


@bp.patch("/plans/<plan_id>")
def patch_plan(plan_id):
    authorize(("FundAdministrator",))
    data = body()
    changes = {}
    if present(data, "allocation_method"):
        changes["allocation_method"] = field_enum(data, "allocation_method",
                                                  ALLOCATION_METHODS)
    if present(data, "de_minimis_variant"):
        changes["de_minimis_variant"] = field_enum(data, "de_minimis_variant",
                                                   DE_MINIMIS_VARIANTS)
    if present(data, "interest_rate_bps"):
        changes["interest_rate_bps"] = field_int(data, "interest_rate_bps",
                                                 minimum=1, maximum=3000)
    if present(data, "unattributable_uvb_cents"):
        changes["unattributable_uvb_cents"] = field_int(
            data, "unattributable_uvb_cents", minimum=0)
    if present(data, "mass_withdrawal_declared"):
        changes["mass_withdrawal_declared"] = field_bool(
            data, "mass_withdrawal_declared")
    plan = svc.get_plan(plan_id)
    plan.update(changes)
    svc.touch(plan)
    return obj(serialize.plan(plan))


@bp.get("/plans/<plan_id>")
def read_plan(plan_id):
    authorize(ANY_ROLE)
    return obj(serialize.plan(svc.get_plan(plan_id)))


# --------------------------------------------------------------------------
# ControlledGroup
# --------------------------------------------------------------------------

@bp.post("/controlled-groups")
def create_group():
    authorize(("FundAdministrator",))
    data = body()
    fields = {
        "name": field_str(data, "name", required=True, min_len=1, max_len=200),
        "common_control_basis": field_enum(data, "common_control_basis",
                                           COMMON_CONTROL_BASES, required=True),
        "bond_posture": "UNBONDED",
        "joint_exposure_cents": 0,
        "contingent_exposure_cents": 0,
        "exposure_score": 0.0,
        "_successor_extra_cents": 0,
    }
    return created(serialize.controlled_group(svc.new_row(db.controlled_groups, fields)))


@bp.get("/controlled-groups/<controlled_group_id>")
def read_group(controlled_group_id):
    authorize(ANY_ROLE)
    return obj(serialize.controlled_group(svc.get_group(controlled_group_id)))


# --------------------------------------------------------------------------
# Employer
# --------------------------------------------------------------------------

@bp.post("/employers")
def create_employer():
    authorize(("FundAdministrator",))
    data = body()
    plan_id = field_str(data, "plan_id", required=True)
    group_id = field_str(data, "controlled_group_id", required=True)
    legal_name = field_str(data, "legal_name", required=True, min_len=1, max_len=200)
    ein = field_str(data, "ein", required=True)
    if len(ein) != 9 or not ein.isdigit():
        invalid("Field 'ein' must be exactly nine digits.")
    obligation_start_year = field_int(data, "obligation_start_year", required=True,
                                      minimum=YEAR_MIN, maximum=YEAR_MAX)
    covered_work_status = field_enum(data, "covered_work_status",
                                     COVERED_WORK_STATUSES, default="PERFORMING")
    cba_count = field_int(data, "cba_count", default=1, minimum=1)
    dvb = field_int(data, "directly_attributed_vested_benefits_cents",
                    default=0, minimum=0)
    dassets = field_int(data, "directly_attributed_assets_cents",
                        default=0, minimum=0)

    plan = svc.get_plan(plan_id)
    svc.get_group(group_id)

    if any(e["ein"] == ein for e in db.employers.values()):
        fail("ERR_DUPLICATE_EIN")

    employer = svc.new_row(db.employers, {
        "plan_id": plan["id"],
        "controlled_group_id": group_id,
        "legal_name": legal_name,
        "ein": ein,
        "obligation_start_year": obligation_start_year,
        "obligation_end_year": None,
        "covered_work_status": covered_work_status,
        "cba_count": cba_count,
        "ceased_cba_count": 0,
        "directly_attributed_vested_benefits_cents": dvb,
        "directly_attributed_assets_cents": dassets,
        "status": "CONTRIBUTING",
        "outstanding_liability_cents": 0,
        "credit_watch": False,
        "delinquency_strikes": 0,
    })
    return created(serialize.employer(employer))


@bp.get("/employers")
def list_employers():
    authorize(ANY_ROLE)
    rows = str_filters(list(db.employers.values()), {
        "plan_id": "plan_id",
        "controlled_group_id": "controlled_group_id",
        "status": "status",
    })
    return paged(rows, serialize.employer)


@bp.get("/employers/<employer_id>")
def read_employer(employer_id):
    authorize(ANY_ROLE)
    return obj(serialize.employer(svc.get_employer(employer_id)))


@bp.patch("/employers/<employer_id>")
def patch_employer(employer_id):
    authorize(("FundAdministrator",))
    data = body()
    changes = {}
    if present(data, "covered_work_status"):
        changes["covered_work_status"] = field_enum(data, "covered_work_status",
                                                    COVERED_WORK_STATUSES)
    if present(data, "cba_count"):
        changes["cba_count"] = field_int(data, "cba_count", minimum=1)
    if present(data, "directly_attributed_vested_benefits_cents"):
        changes["directly_attributed_vested_benefits_cents"] = field_int(
            data, "directly_attributed_vested_benefits_cents", minimum=0)
    if present(data, "directly_attributed_assets_cents"):
        changes["directly_attributed_assets_cents"] = field_int(
            data, "directly_attributed_assets_cents", minimum=0)
    employer = svc.get_employer(employer_id)
    employer.update(changes)
    svc.touch(employer)
    return obj(serialize.employer(employer))


# --------------------------------------------------------------------------
# PlanYearValuation
# --------------------------------------------------------------------------

def _certify(valuation, user_id):
    valuation["status"] = "CERTIFIED"
    valuation["certified_by_user_id"] = user_id
    valuation["certified_at"] = now()


@bp.post("/plan-year-valuations")
def create_valuation():
    ctx = authorize(("PlanActuary",))
    data = body()
    plan_id = field_str(data, "plan_id", required=True)
    plan_year = field_int(data, "plan_year", required=True,
                          minimum=YEAR_MIN, maximum=YEAR_MAX)
    window_start = field_datetime(data, "measurement_window_start", required=True)
    window_end = field_datetime(data, "measurement_window_end", required=True)
    if window_end <= window_start:
        invalid("'measurement_window_end' must be strictly after "
                "'measurement_window_start'.")
    uvb_total = field_int(data, "uvb_total_cents", required=True, minimum=0)
    uvb_pool = field_int(data, "uvb_pool_cents", required=True, minimum=0)
    all_dollars = field_int(data, "all_employer_contributions_cents",
                            required=True, minimum=0)
    all_cbu = field_int(data, "all_employer_cbu", required=True, minimum=0)
    interest_rate_bps = field_int(data, "interest_rate_bps", required=True,
                                  minimum=1, maximum=3000)
    certify_on_create = field_bool(data, "certify_on_create", default=False)

    plan = svc.get_plan(plan_id)

    # tier 11: measurement windows of the same plan may not crowd each other
    for other in db.valuations.values():
        if other["plan_id"] != plan["id"] or other["status"] not in ("DRAFT", "CERTIFIED"):
            continue
        buffered_end = add_days(other["measurement_window_end"],
                                calc.VALUATION_QUIET_BUFFER_DAYS)
        if window_start < buffered_end and window_end > other["measurement_window_start"]:
            fail("ERR_VALUATION_WINDOW_CONFLICT")

    valuation = svc.new_row(db.valuations, {
        "plan_id": plan["id"],
        "plan_year": plan_year,
        "measurement_window_start": window_start,
        "measurement_window_end": window_end,
        "uvb_total_cents": uvb_total,
        "uvb_pool_cents": uvb_pool,
        "all_employer_contributions_cents": all_dollars,
        "all_employer_cbu": all_cbu,
        "interest_rate_bps": interest_rate_bps,
        "certify_on_create_used": bool(certify_on_create),
        "status": "DRAFT",
        "certified_by_user_id": None,
        "certified_at": None,
        "allocated_uvb_cents": 0,
        "unallocated_uvb_cents": uvb_total,
    })
    if certify_on_create:
        _certify(valuation, ctx.user_id)

    # an unreferenced certified incumbent for the same plan year is superseded
    for other in db.valuations.values():
        if (other["id"] == valuation["id"] or other["plan_id"] != plan["id"]
                or other["plan_year"] != plan_year or other["status"] != "CERTIFIED"):
            continue
        referenced = any(a.get("valuation_id") == other["id"]
                         for a in db.assessments.values())
        if not referenced:
            svc.apply_changes(other, {"status": "SUPERSEDED"})

    return created(serialize.valuation(valuation))


@bp.post("/plan-year-valuations/<plan_year_valuation_id>/certify")
def certify_valuation(plan_year_valuation_id):
    ctx = authorize(("PlanActuary",))
    valuation = svc.get_valuation(plan_year_valuation_id)
    if valuation["status"] != "DRAFT":
        fail("ERR_VALUATION_ALREADY_CERTIFIED")
    _certify(valuation, ctx.user_id)
    svc.touch(valuation)
    return obj(serialize.valuation(valuation))


@bp.get("/plan-year-valuations")
def list_valuations():
    authorize(ANY_ROLE)
    rows = str_filters(list(db.valuations.values()), {
        "plan_id": "plan_id",
        "status": "status",
    })
    rows = int_filter(rows, "plan_year", "plan_year")
    return paged(rows, serialize.valuation)


@bp.get("/plan-year-valuations/<plan_year_valuation_id>")
def read_valuation(plan_year_valuation_id):
    authorize(ANY_ROLE)
    return obj(serialize.valuation(svc.get_valuation(plan_year_valuation_id)))


# --------------------------------------------------------------------------
# ContributionRecord
# --------------------------------------------------------------------------

@bp.post("/contribution-records")
def create_contribution_record():
    authorize(("FundAdministrator",))
    data = body()
    employer_id = field_str(data, "employer_id", required=True)
    plan_year_start = field_int(data, "plan_year_start", required=True,
                                minimum=YEAR_MIN, maximum=YEAR_MAX)
    plan_year_end = field_int(data, "plan_year_end", required=True,
                              minimum=YEAR_MIN, maximum=YEAR_MAX)
    if plan_year_start > plan_year_end:
        invalid("'plan_year_start' must not exceed 'plan_year_end'.")
    cbu = field_int(data, "contribution_base_units", required=True, minimum=0)
    amount = field_int(data, "contribution_amount_cents", required=True, minimum=0)
    rate = field_int(data, "contribution_rate_cents_per_cbu", required=True, minimum=0)
    expected_version = field_int(data, "expected_employer_version", required=True)
    supersedes_id = field_str(data, "supersedes_record_id")

    employer = svc.get_employer(employer_id)
    superseded = svc.get_record(supersedes_id) if supersedes_id is not None else None

    if expected_version != employer["version"]:
        fail("ERR_STALE_EMPLOYER_VERSION")

    # tier 11: certified intervals of the same employer may not overlap
    for other in db.contribution_records.values():
        if (other["employer_id"] != employer["id"] or other["status"] != "CERTIFIED"):
            continue
        if superseded is not None and other["id"] == superseded["id"]:
            continue
        if plan_year_start <= other["plan_year_end"] and plan_year_end >= other["plan_year_start"]:
            fail("ERR_CONTRIBUTION_PERIOD_OVERLAP")

    # tier 12: a supersession must match the incumbent exactly
    if superseded is not None:
        if (superseded["status"] != "CERTIFIED"
                or superseded["employer_id"] != employer["id"]
                or superseded["plan_year_start"] != plan_year_start
                or superseded["plan_year_end"] != plan_year_end):
            fail("ERR_SUPERSEDED_RECORD_PERIOD_MISMATCH")

    if superseded is not None:
        svc.apply_changes(superseded, {"status": "AMENDED"})
    svc.touch(employer)

    record = svc.new_row(db.contribution_records, {
        "employer_id": employer["id"],
        "supersedes_record_id": superseded["id"] if superseded else None,
        "plan_year_start": plan_year_start,
        "plan_year_end": plan_year_end,
        "contribution_base_units": cbu,
        "contribution_amount_cents": amount,
        "contribution_rate_cents_per_cbu": rate,
        "status": "CERTIFIED",
        "employer_version_at_apply": employer["version"],
    })
    return created(serialize.contribution_record(record))


@bp.get("/contribution-records")
def list_contribution_records():
    authorize(ANY_ROLE)
    rows = str_filters(list(db.contribution_records.values()), {
        "employer_id": "employer_id",
        "status": "status",
        "supersedes_record_id": "supersedes_record_id",
    })
    from validate import query_int_filter
    plan_year = query_int_filter("plan_year")
    if plan_year is not None:
        rows = [r for r in rows
                if r["plan_year_start"] <= plan_year <= r["plan_year_end"]]
    return paged(rows, serialize.contribution_record)


@bp.get("/contribution-records/<contribution_record_id>")
def read_contribution_record(contribution_record_id):
    authorize(ANY_ROLE)
    return obj(serialize.contribution_record(svc.get_record(contribution_record_id)))


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    authorize(("FundAdministrator",))
    data = body()
    target = field_datetime(data, "to_iso8601", required=True)
    previous = db.clock
    if target <= previous:
        fail("ERR_CLOCK_MUST_ADVANCE")
    db.clock = target
    return obj({"current_utc": fmt(target), "previous_utc": fmt(previous)})


# --------------------------------------------------------------------------
# Collection sweep
# --------------------------------------------------------------------------

@bp.post("/collection-sweeps")
def collection_sweep():
    authorize(("FundAdministrator",))
    data = body()
    plan_id = field_str(data, "plan_id", required=True)
    plan = svc.get_plan(plan_id)
    counters = svc.run_sweep(plan)
    payload = {"swept_at": fmt(now())}
    payload.update(counters)
    return obj(payload)
