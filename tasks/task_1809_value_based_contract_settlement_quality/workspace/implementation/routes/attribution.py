"""AttributionRun and AttributionRecord endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_STATE_TRANSITION,
    ERR_MEMBER_DISENROLLED,
    ERR_MEMBER_NO_ELIGIBLE_MONTHS,
    ERR_MEMBER_PROGRAM_MISMATCH,
    ERR_NOT_FOUND,
    ERR_PRACTICE_GROUP_MISMATCH,
    ERR_PRACTICE_INACTIVE,
    ERR_RUN_ALREADY_LOCKED,
    ERR_RUN_NOT_DRAFT,
    ERR_RUN_NOT_LOCKED,
    ERR_STALE_VERSION,
    ERR_YEAR_LOCKED,
    ERR_YEAR_NOT_OPEN,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services import calculations as calc
from services import engine
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    reject_unknown_fields,
    require_int,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("attribution", __name__)


def _get_run_or_404(run_id: str) -> dict:
    run = db.attribution_runs.get(run_id)
    if run is None:
        raise_err(ERR_NOT_FOUND, "AttributionRun id does not exist")
    return run


# ---------------------------------------------------------------------------
# AttributionRun
# ---------------------------------------------------------------------------

@bp.route("/vbc/performance-years/<year_id>/attribution-runs", methods=["POST"])
@require_roles("AttributionAnalyst")
def create_run(year_id: str, _user_id: str, _role: str):
    # Priority 3: path id.
    year = db.performance_years.get(year_id)
    if year is None:
        raise_err(ERR_NOT_FOUND, "PerformanceYear id does not exist")
    # Priority 5: shape.
    body = get_json_body()
    reject_unknown_fields(body, {"run_label", "expected_performance_year_version"})
    run_label = require_string(body, "run_label")
    expected_version = require_int(body, "expected_performance_year_version")
    # Priority 6 (state): year must be ATTRIBUTION_OPEN.
    if year["year_status"] != "ATTRIBUTION_OPEN":
        raise_err(ERR_YEAR_NOT_OPEN, "Attribution runs can only be created while the year is ATTRIBUTION_OPEN")
    # Priority 14: OCC against the year.
    if expected_version != year["version"]:
        raise_err(ERR_STALE_VERSION, "expected_performance_year_version does not match the year's current version")

    # Supersede prior DRAFT/COMPUTED runs of the year (a LOCKED run is only
    # superseded by the reopen-attribution cascade, never by run creation).
    for run in db.attribution_runs.values():
        if (
            run["performance_year_id"] == year_id
            and run["run_status"] in ("DRAFT", "COMPUTED")
        ):
            db.apply_updates(run, {"run_status": "SUPERSEDED"})

    seq = max(
        (r["run_seq"] for r in db.attribution_runs.values() if r["performance_year_id"] == year_id),
        default=0,
    ) + 1
    run = {
        "performance_year_id": year_id,
        "run_label": run_label,
        "run_seq": seq,
        "run_status": "DRAFT",
        "attributed_member_count": 0,
    }
    db.stamp_new(run)
    db.attribution_runs[run["id"]] = run
    # Creating the run mutates the parent year's version (§1.2.1).
    db.touch(year)
    return success_object(run, 201)


@bp.route("/vbc/attribution-runs", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_runs(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.attribution_runs.values()))
    items = apply_filters(items, ["performance_year_id", "run_status"])
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/vbc/attribution-runs/<run_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_run(run_id: str, _user_id: str, _role: str):
    return success_object(_get_run_or_404(run_id))


@bp.route("/vbc/attribution-runs/<run_id>/compute", methods=["POST"])
@require_roles("AttributionAnalyst")
def compute_run(run_id: str, _user_id: str, _role: str):
    run = _get_run_or_404(run_id)
    if run["run_status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a DRAFT run can be computed")
    year = db.performance_years.get(run["performance_year_id"])
    period_start = db.parse_date(year["period_start"])
    period_end = db.parse_date(year["period_end"])
    confirmed = 0
    for record in db.attribution_records.values():
        if record["attribution_run_id"] != run_id:
            continue
        # Recompute member_months per the mid-month rule (CLOSED spans ignored),
        # then PROVISIONAL -> CONFIRMED.
        record["member_months"] = calc.member_months_for(record["member_id"], period_start, period_end)
        record["record_status"] = "CONFIRMED"
        db.touch(record)
        confirmed += 1
    run["attributed_member_count"] = confirmed
    run["run_status"] = "COMPUTED"
    db.touch(run)
    return success_object(run)


@bp.route("/vbc/attribution-runs/<run_id>/lock", methods=["POST"])
@require_roles("AttributionAnalyst")
def lock_run(run_id: str, _user_id: str, _role: str):
    run = _get_run_or_404(run_id)
    if run["run_status"] != "COMPUTED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a COMPUTED run can be locked")
    year = db.performance_years.get(run["performance_year_id"])
    if year is None or year["year_status"] != "ATTRIBUTION_OPEN":
        raise_err(ERR_YEAR_NOT_OPEN, "Run lock requires the year to be ATTRIBUTION_OPEN")
    for other in db.attribution_runs.values():
        if (
            other["id"] != run_id
            and other["performance_year_id"] == run["performance_year_id"]
            and other["run_status"] == "LOCKED"
        ):
            raise_err(ERR_RUN_ALREADY_LOCKED, "Another run of the year is already LOCKED")
    run["run_status"] = "LOCKED"
    db.touch(run)
    return success_object(run)


# ---------------------------------------------------------------------------
# AttributionRecord
# ---------------------------------------------------------------------------

@bp.route("/vbc/attribution-runs/<run_id>/records", methods=["POST"])
@require_roles("AttributionAnalyst")
def create_record(run_id: str, _user_id: str, _role: str):
    # Priority 3: path id, then body FKs.
    run = db.attribution_runs.get(run_id)
    if run is None:
        raise_err(ERR_NOT_FOUND, "AttributionRun id does not exist")
    body = get_json_body()
    raw_member = body.get("member_id")
    if isinstance(raw_member, str) and raw_member != "" and raw_member not in db.members:
        raise_err(ERR_NOT_FOUND, "member_id does not exist")
    raw_practice = body.get("practice_id")
    if isinstance(raw_practice, str) and raw_practice != "" and raw_practice not in db.practices:
        raise_err(ERR_NOT_FOUND, "practice_id does not exist")
    # Priority 5: shape.
    reject_unknown_fields(body, {"member_id", "practice_id"})
    member_id = require_string(body, "member_id")
    practice_id = require_string(body, "practice_id")
    if member_id not in db.members:
        raise_err(ERR_NOT_FOUND, "member_id does not exist")
    if practice_id not in db.practices:
        raise_err(ERR_NOT_FOUND, "practice_id does not exist")
    # Priority 6 (state): run must be DRAFT.
    if run["run_status"] != "DRAFT":
        raise_err(ERR_RUN_NOT_DRAFT, "Records can only be added to a DRAFT run")

    # Priority 10: referential integrity, in the declared check order.
    year = db.performance_years[run["performance_year_id"]]
    contract = engine.contract_of_year(year)
    practice = db.practices[practice_id]
    member = db.members[member_id]
    if practice["practice_group_id"] != contract["practice_group_id"]:
        raise_err(ERR_PRACTICE_GROUP_MISMATCH, "Practice does not belong to the contract's group")
    if practice["practice_status"] != "ACTIVE":
        raise_err(ERR_PRACTICE_INACTIVE, "Practice is not ACTIVE")
    if member["program_id"] != contract["program_id"]:
        raise_err(ERR_MEMBER_PROGRAM_MISMATCH, "Member does not belong to the contract's program")
    if member["member_status"] != "ELIGIBLE":
        raise_err(ERR_MEMBER_DISENROLLED, "Member is DISENROLLED")
    eligible_months = calc.member_months_for(
        member_id, db.parse_date(year["period_start"]), db.parse_date(year["period_end"])
    )
    if eligible_months < 1:
        raise_err(ERR_MEMBER_NO_ELIGIBLE_MONTHS, "Member has no mid-month-eligible month in the year window")

    record = {
        "attribution_run_id": run_id,
        "member_id": member_id,
        "practice_id": practice_id,
        "member_months": 0,
        "record_status": "PROVISIONAL",
    }
    db.stamp_new(record)
    db.attribution_records[record["id"]] = record
    return success_object(record, 201)


@bp.route("/vbc/attribution-records", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_records(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.attribution_records.values()))
    items = apply_filters(items, ["attribution_run_id", "member_id", "practice_id", "record_status"])
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


def _get_record_or_404(record_id: str) -> dict:
    record = db.attribution_records.get(record_id)
    if record is None:
        raise_err(ERR_NOT_FOUND, "AttributionRecord id does not exist")
    return record


def _check_record_mutation_guards(record: dict) -> dict:
    """Shared guards for exclude/reinstate: run LOCKED, year not SETTLED/CLOSED."""
    run = db.attribution_runs.get(record["attribution_run_id"])
    if run is None or run["run_status"] != "LOCKED":
        raise_err(ERR_RUN_NOT_LOCKED, "Record mutation requires the run to be LOCKED")
    year = db.performance_years.get(run["performance_year_id"])
    if year is not None and year["year_status"] in ("SETTLED", "CLOSED"):
        raise_err(ERR_YEAR_LOCKED, "Year is locked for data mutations")
    return year


@bp.route("/vbc/attribution-records/<record_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_record(record_id: str, _user_id: str, _role: str):
    return success_object(_get_record_or_404(record_id))


@bp.route("/vbc/attribution-records/<record_id>/exclude", methods=["POST"])
@require_roles("AttributionAnalyst")
def exclude_record(record_id: str, _user_id: str, _role: str):
    record = _get_record_or_404(record_id)
    if record["record_status"] != "CONFIRMED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a CONFIRMED record can be excluded")
    year = _check_record_mutation_guards(record)
    record["record_status"] = "EXCLUDED"
    db.touch(record)
    # Cascade: population rollups recomputed without the record; published
    # reports stale; settlement flagged when PROVISIONAL/FINALIZED.
    engine.after_population_mutation(year)
    return success_object(record)


@bp.route("/vbc/attribution-records/<record_id>/reinstate", methods=["POST"])
@require_roles("AttributionAnalyst")
def reinstate_record(record_id: str, _user_id: str, _role: str):
    record = _get_record_or_404(record_id)
    if record["record_status"] != "EXCLUDED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only an EXCLUDED record can be reinstated")
    year = _check_record_mutation_guards(record)
    record["record_status"] = "CONFIRMED"
    db.touch(record)
    # Cascade: rollups recomputed with the record restored (compensating
    # invariant: exclude-then-reinstate leaves total_member_months identical).
    engine.after_population_mutation(year)
    return success_object(record)
