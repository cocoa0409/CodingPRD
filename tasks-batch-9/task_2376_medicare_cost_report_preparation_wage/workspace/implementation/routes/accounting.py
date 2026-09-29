"""Worksheet A structure, the trial balance ledger, workpapers and the stepdown.

PRD 3.2, 3.3 and 3.4.
"""

from flask import Blueprint, request

import errors
import services.calc as calc
from arith import is_number
from common import (READ_ROLES, body, check_scope, endpoint, find, ok_list_of, pagination, public,
                    reference, require_editable)
from db import (centers_of, db, entries_of, iso, new_row, ordered, runs_of, tb_lines_of, touch)
from response import ok
from validators import query_enum

bp = Blueprint("accounting", __name__)

CENTER_TYPES = ("GENERAL_SERVICE", "ANCILLARY", "ROUTINE", "NONREIMBURSABLE")
ALLOCATION_BASES = ("SQUARE_FEET", "MEALS_SERVED", "POUNDS_LAUNDRY", "NURSING_HOURS", "NONE")
TB_STATUSES = ("UNMAPPED", "MAPPED")
ENTRY_TYPES = ("RECLASSIFICATION", "ADJUSTMENT")
ENTRY_STATUSES = ("ACTIVE", "REVERSED")
ENTRY_SOURCES = ("MANUAL", "AUDIT")
RUN_STATUSES = ("QUEUED", "COMPLETED", "FAILED", "STALE")
RUN_METHODS = ("SINGLE_APPORTIONMENT", "DOUBLE_APPORTIONMENT")
DUPLICATE_ORDER_REASON = "DUPLICATE_STEPDOWN_ORDER"


def _statistics(raw):
    """Validate values at band 3; report unknown keys back to the caller."""
    if raw is None:
        return {}, False
    for key, value in raw.items():
        if not is_number(value) or value < 0:
            raise errors.invalid_request(
                "statistics['%s'] must be a number greater than or equal to zero." % key)
    unknown = any(key not in calc.BASIS_KEYS for key in raw)
    return dict(raw), unknown


def _legs(raw):
    legs = []
    for item in raw:
        if not isinstance(item, dict):
            raise errors.invalid_request("Every element of 'legs' must be an object.")
        center_id = item.get("cost_center_id")
        amount = item.get("amount_cents")
        if not isinstance(center_id, str) or not center_id:
            raise errors.invalid_request("Every leg requires a 'cost_center_id' string.")
        if not isinstance(amount, int) or isinstance(amount, bool):
            raise errors.invalid_request("Every leg requires an integer 'amount_cents'.")
        if amount == 0:
            raise errors.invalid_request("A leg 'amount_cents' may not be zero.")
        legs.append({"cost_center_id": center_id, "amount_cents": amount})
    return legs


# --------------------------------------------------------------- CostCenter
@bp.post("/cost-reports/<report_id>/cost-centers")
@endpoint(roles=["ReimbursementAnalyst"])
def create_cost_center(report_id):
    payload = body()
    code = payload.string("code", length=5, digits=True)
    name = payload.string("name")
    center_type = payload.enum("center_type", CENTER_TYPES)
    allocation_basis = payload.enum("allocation_basis", ALLOCATION_BASES, required=False,
                                    default=None)
    stepdown_order = payload.integer("stepdown_order", required=False, default=None, minimum=1)
    statistics, unknown_basis = _statistics(payload.mapping("statistics", default=None))

    report = find("CostReport", report_id)
    check_scope(report["provider_id"])
    require_editable(report)

    centers = centers_of(report["id"])
    if center_type == "GENERAL_SERVICE":
        if allocation_basis is None or allocation_basis == "NONE":
            raise errors.business(
                "ERR_STEPDOWN_ORDER_CONFLICT",
                "A general service center requires an allocation_basis other than NONE.")
        if stepdown_order is None:
            raise errors.business("ERR_STEPDOWN_ORDER_CONFLICT",
                                 "A general service center requires a stepdown_order.")
        for other in centers:
            if (other["center_type"] == "GENERAL_SERVICE"
                    and other["stepdown_order"] == stepdown_order):
                raise errors.business("ERR_STEPDOWN_ORDER_CONFLICT",
                                     "Another general service center already holds that order.")
    else:
        if payload.present("allocation_basis") or payload.present("stepdown_order"):
            raise errors.business(
                "ERR_STEPDOWN_ORDER_CONFLICT",
                "allocation_basis and stepdown_order belong to general service centers only.")

    if unknown_basis:
        raise errors.business("ERR_COST_CENTER_CODE_DUPLICATE",
                             "statistics carries an unrecognized allocation basis key.")
    for other in centers:
        if other["code"] == code:
            raise errors.business("ERR_COST_CENTER_CODE_DUPLICATE",
                                 "That worksheet line code is already used in this report.")

    center = new_row(
        cost_report_id=report["id"],
        code=code,
        name=name,
        center_type=center_type,
        allocation_basis=allocation_basis if center_type == "GENERAL_SERVICE" else "NONE",
        stepdown_order=stepdown_order if center_type == "GENERAL_SERVICE" else None,
        statistics=statistics,
        direct_cost_cents=0,
        reclassified_amount_cents=0,
        adjustment_amount_cents=0,
        post_reclass_direct_cost_cents=0,
        post_adjustment_cost_cents=0,
        allocated_in_cents=0,
        allocated_out_cents=0,
        allocated_total_cost_cents=0,
    )
    db.cost_centers[center["id"]] = center

    before = report["allocation_status"]
    calc.stale_when_completed_run(report)
    if report["allocation_status"] != before:
        touch(report)
    return ok(public(center), 201)


@bp.get("/cost-centers/<center_id>")
@endpoint(roles=list(READ_ROLES))
def read_cost_center(center_id):
    return ok(public(find("CostCenter", center_id)))


@bp.get("/cost-reports/<report_id>/cost-centers")
@endpoint(roles=list(READ_ROLES))
def list_cost_centers(report_id):
    limit, offset = pagination()
    center_type = query_enum(request.args, "center_type", CENTER_TYPES)
    report = find("CostReport", report_id)
    rows = centers_of(report["id"])
    if center_type is not None:
        rows = [r for r in rows if r["center_type"] == center_type]
    return ok_list_of(rows, limit, offset)


@bp.patch("/cost-centers/<center_id>")
@endpoint(roles=["ReimbursementAnalyst"])
def revise_cost_center(center_id):
    payload = body()
    name = payload.string("name", required=False, default=None)
    allocation_basis = payload.enum("allocation_basis", ALLOCATION_BASES, required=False,
                                   default=None)
    stepdown_order = payload.integer("stepdown_order", required=False, default=None, minimum=1)
    raw_statistics = payload.mapping("statistics", default=None)

    center = find("CostCenter", center_id)
    report = db.cost_reports[center["cost_report_id"]]

    if center["center_type"] == "GENERAL_SERVICE":
        if allocation_basis == "NONE":
            raise errors.invalid_request(
                "A general service center may not drop its allocation_basis to NONE.")
    elif payload.present("allocation_basis") or payload.present("stepdown_order"):
        raise errors.invalid_request(
            "allocation_basis and stepdown_order belong to general service centers only.")

    statistics = None
    if raw_statistics is not None:
        statistics, unknown_basis = _statistics(raw_statistics)
        if unknown_basis:
            raise errors.invalid_request(
                "statistics carries an unrecognized allocation basis key.")

    check_scope(report["provider_id"])
    require_editable(report)

    if name is not None:
        center["name"] = name
    if allocation_basis is not None:
        center["allocation_basis"] = allocation_basis
    if stepdown_order is not None:
        center["stepdown_order"] = stepdown_order
    if statistics is not None:
        center["statistics"] = statistics
    touch(center)

    calc.invalidate_allocation(report, calc.STALE_COST_CENTER)
    touch(report)
    return ok(public(center))


# ---------------------------------------------------------- TrialBalanceLine
@bp.post("/cost-reports/<report_id>/trial-balance-lines")
@endpoint(roles=["ReimbursementAnalyst"])
def create_trial_balance_line(report_id):
    payload = body()
    gl_account = payload.string("gl_account")
    description = payload.string("description")
    amount_cents = payload.integer("amount_cents")
    mapped_cost_center_id = payload.string("mapped_cost_center_id", required=False, default=None)

    report = find("CostReport", report_id)
    center = None
    if mapped_cost_center_id is not None:
        center = reference("CostCenter", mapped_cost_center_id)
    check_scope(report["provider_id"])
    require_editable(report)
    if center is not None and center["cost_report_id"] != report["id"]:
        raise errors.business("ERR_COST_CENTER_FOREIGN_TO_REPORT",
                             "That cost center belongs to a different cost report.")

    line = new_row(
        cost_report_id=report["id"],
        gl_account=gl_account,
        description=description,
        amount_cents=amount_cents,
        mapped_cost_center_id=center["id"] if center is not None else None,
        status="MAPPED" if center is not None else "UNMAPPED",
    )
    db.trial_balance_lines[line["id"]] = line

    calc.rollup(report)
    calc.stale_when_completed_run(report)
    touch(report)
    return ok(public(line), 201)


@bp.get("/trial-balance-lines/<line_id>")
@endpoint(roles=list(READ_ROLES))
def read_trial_balance_line(line_id):
    return ok(public(find("TrialBalanceLine", line_id)))


@bp.get("/cost-reports/<report_id>/trial-balance-lines")
@endpoint(roles=list(READ_ROLES))
def list_trial_balance_lines(report_id):
    limit, offset = pagination()
    status = query_enum(request.args, "status", TB_STATUSES)
    report = find("CostReport", report_id)
    rows = tb_lines_of(report["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return ok_list_of(rows, limit, offset)


@bp.get("/cost-centers/<center_id>/trial-balance-lines")
@endpoint(roles=list(READ_ROLES))
def list_center_trial_balance_lines(center_id):
    limit, offset = pagination()
    center = find("CostCenter", center_id)
    rows = [r for r in ordered(list(db.trial_balance_lines.values()))
            if r["mapped_cost_center_id"] == center["id"]]
    return ok_list_of(rows, limit, offset)


@bp.post("/trial-balance-lines/<line_id>/map")
@endpoint(roles=["ReimbursementAnalyst"])
def map_trial_balance_line(line_id):
    payload = body()
    cost_center_id = payload.string("cost_center_id")

    line = find("TrialBalanceLine", line_id)
    center = reference("CostCenter", cost_center_id)
    report = db.cost_reports[line["cost_report_id"]]
    check_scope(report["provider_id"])
    require_editable(report)
    if line["status"] != "UNMAPPED":
        raise errors.invalid_state("The ledger line is already MAPPED.")
    if center["cost_report_id"] != report["id"]:
        raise errors.business("ERR_COST_CENTER_FOREIGN_TO_REPORT",
                             "That cost center belongs to a different cost report.")

    line["mapped_cost_center_id"] = center["id"]
    line["status"] = "MAPPED"
    touch(line)

    calc.rollup(report)
    calc.stale_when_completed_run(report)
    touch(report)
    return ok(public(line))


# ----------------------------------------------------------- WorkpaperEntry
@bp.post("/cost-reports/<report_id>/workpaper-entries")
@endpoint(roles=["ReimbursementAnalyst"])
def create_workpaper_entry(report_id):
    payload = body()
    entry_type = payload.enum("entry_type", ENTRY_TYPES)
    code = payload.string("code")
    description = payload.string("description")
    legs = _legs(payload.array("legs", min_items=1))
    is_non_allowable = payload.boolean("is_non_allowable", required=False, default=False)

    report = find("CostReport", report_id)
    centers = {}
    for leg in legs:
        centers[leg["cost_center_id"]] = reference("CostCenter", leg["cost_center_id"])
    check_scope(report["provider_id"])
    require_editable(report)

    for center in centers.values():
        if center["cost_report_id"] != report["id"]:
            raise errors.business("ERR_COST_CENTER_FOREIGN_TO_REPORT",
                                 "A leg names a cost center of a different cost report.")

    if entry_type == "RECLASSIFICATION":
        if len(legs) < 2 or sum(leg["amount_cents"] for leg in legs) != 0:
            raise errors.business(
                "ERR_RECLASS_NOT_BALANCED",
                "A reclassification needs at least two legs netting to exactly zero.")
    elif len(legs) != 1:
        raise errors.business("ERR_RECLASS_NOT_BALANCED",
                             "An adjustment entry carries exactly one leg.")

    if is_non_allowable and any(leg["amount_cents"] >= 0 for leg in legs):
        raise errors.business("ERR_NON_ALLOWABLE_MUST_BE_NEGATIVE",
                             "A non-allowable adjustment must carry negative leg amounts.")

    entry = new_row(
        cost_report_id=report["id"],
        entry_type=entry_type,
        code=code,
        description=description,
        legs=legs,
        source="MANUAL",
        is_non_allowable=is_non_allowable,
        status="ACTIVE",
        source_audit_adjustment_id=None,
        reversed_at=None,
    )
    db.workpaper_entries[entry["id"]] = entry

    calc.rollup(report)
    calc.invalidate_allocation(report, calc.STALE_WORKPAPER)
    touch(report)
    return ok(public(entry), 201)


@bp.get("/workpaper-entries/<entry_id>")
@endpoint(roles=list(READ_ROLES))
def read_workpaper_entry(entry_id):
    return ok(public(find("WorkpaperEntry", entry_id)))


@bp.get("/cost-reports/<report_id>/workpaper-entries")
@endpoint(roles=list(READ_ROLES))
def list_workpaper_entries(report_id):
    limit, offset = pagination()
    entry_type = query_enum(request.args, "entry_type", ENTRY_TYPES)
    status = query_enum(request.args, "status", ENTRY_STATUSES)
    source = query_enum(request.args, "source", ENTRY_SOURCES)
    report = find("CostReport", report_id)
    rows = entries_of(report["id"])
    if entry_type is not None:
        rows = [r for r in rows if r["entry_type"] == entry_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if source is not None:
        rows = [r for r in rows if r["source"] == source]
    return ok_list_of(rows, limit, offset)


@bp.get("/audit-adjustments/<adjustment_id>/workpaper-entries")
@endpoint(roles=list(READ_ROLES))
def list_audit_workpaper_entries(adjustment_id):
    limit, offset = pagination()
    adjustment = find("AuditAdjustment", adjustment_id)
    rows = [r for r in ordered(list(db.workpaper_entries.values()))
            if r["source_audit_adjustment_id"] == adjustment["id"]]
    return ok_list_of(rows, limit, offset)


@bp.post("/workpaper-entries/<entry_id>/reverse")
@endpoint(roles=["ReimbursementAnalyst"])
def reverse_workpaper_entry(entry_id):
    entry = find("WorkpaperEntry", entry_id)
    report = db.cost_reports[entry["cost_report_id"]]
    check_scope(report["provider_id"])
    require_editable(report)
    if entry["status"] != "ACTIVE":
        raise errors.invalid_state("The workpaper entry is already REVERSED.")

    entry["status"] = "REVERSED"
    entry["reversed_at"] = iso(db.clock)
    touch(entry)

    calc.rollup(report)
    calc.invalidate_allocation(report, calc.STALE_WORKPAPER)
    touch(report)
    return ok(public(entry))


# -------------------------------------------------------------- StepdownRun
@bp.post("/cost-reports/<report_id>/stepdown-runs")
@endpoint(roles=["ReimbursementAnalyst", "MacAuditor"])
def create_stepdown_run(report_id):
    payload = body()
    expected_version = payload.integer("expected_cost_report_version")
    method = payload.enum("method", RUN_METHODS, required=False, default=None)

    report = find("CostReport", report_id)
    check_scope(report["provider_id"])
    if expected_version != report["version"]:
        raise errors.stale_cost_report_version()

    if report["unmapped_tb_total_cents"] != 0:
        raise errors.business("ERR_UNMAPPED_TRIAL_BALANCE",
                             "Trial balance lines remain unmapped.")
    centers = centers_of(report["id"])
    has_general = any(c["center_type"] == "GENERAL_SERVICE" for c in centers)
    has_target = any(c["center_type"] in ("ROUTINE", "ANCILLARY") for c in centers)
    if not has_general or not has_target:
        raise errors.business(
            "ERR_STEPDOWN_STRUCTURE_INCOMPLETE",
            "The report needs a general service center and a routine or ancillary center.")

    if method is None:
        method = report["apportionment_method"]

    if calc.has_duplicate_stepdown_order(report["id"]):
        run = new_row(
            cost_report_id=report["id"],
            method=method,
            status="FAILED",
            total_allocated_cents=0,
            residual_unallocated_cents=0,
            allocation_lines=[],
            failure_reason=DUPLICATE_ORDER_REASON,
            stale_reason=None,
            completed_at=None,
        )
        db.stepdown_runs[run["id"]] = run
        touch(report)
        return ok(public(run), 201)

    lines, residual = calc.execute_stepdown(report, method)
    calc.demote_completed_runs(report, calc.STALE_SUPERSEDED)
    run = new_row(
        cost_report_id=report["id"],
        method=method,
        status="COMPLETED",
        total_allocated_cents=sum(line["amount_cents"] for line in lines),
        residual_unallocated_cents=residual,
        allocation_lines=lines,
        failure_reason=None,
        stale_reason=None,
        completed_at=iso(db.clock),
    )
    db.stepdown_runs[run["id"]] = run

    calc.publish_allocation(report, lines)
    touch(report)
    return ok(public(run), 201)


@bp.get("/stepdown-runs/<run_id>")
@endpoint(roles=list(READ_ROLES))
def read_stepdown_run(run_id):
    return ok(public(find("StepdownRun", run_id)))


@bp.get("/cost-reports/<report_id>/stepdown-runs")
@endpoint(roles=list(READ_ROLES))
def list_stepdown_runs(report_id):
    limit, offset = pagination()
    status = query_enum(request.args, "status", RUN_STATUSES)
    method = query_enum(request.args, "method", RUN_METHODS)
    report = find("CostReport", report_id)
    rows = runs_of(report["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if method is not None:
        rows = [r for r in rows if r["method"] == method]
    return ok_list_of(rows, limit, offset)
