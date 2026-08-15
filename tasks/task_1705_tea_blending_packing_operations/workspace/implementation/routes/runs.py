"""Production runs: scheduling, start, completion, cancellation (PRD 3.7)."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import store
from auth import ALL_ROLES, authenticate, authorize
from errors import (
    ERR_ALLERGEN_CHANGEOVER_BUFFER,
    ERR_ALREADY_TERMINAL,
    ERR_BATCH_NOT_RELEASABLE,
    ERR_CONTRACT_NOT_ACTIVE,
    ERR_CONTRACT_RECIPE_MISMATCH,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_INVALID_WINDOW,
    ERR_LINE_FORMAT_MISMATCH,
    ERR_LINE_NOT_ACTIVE,
    ERR_LINE_WINDOW_CONFLICT,
    ERR_PRIVATE_LABEL_MINIMUM_UNMET,
    ERR_RUN_OUTSIDE_WINDOW,
    raise_err,
)
from services import (
    RUN_TERMINAL_STATES,
    compute_final_shelf_life_days,
    compute_provisional_shelf_life_days,
    run_out,
)
from util import (
    body_json, bump, get_or_404, list_response, new_record, req_datetime,
    success_object,
)

bp = Blueprint("production_runs", __name__)

ALLERGEN_CHANGEOVER_MINUTES = 45


def _run_or_404(rid):
    return get_or_404(store.production_runs, rid, "ProductionRun")


def _guard_run_terminal(run):
    if run["status"] in RUN_TERMINAL_STATES:
        raise_err(
            ERR_ALREADY_TERMINAL,
            "ProductionRun %s is in terminal state %s" % (run["id"], run["status"]),
        )


def _booked_runs_on_line(line_id):
    return [
        r for r in store.production_runs.values()
        if r["line_id"] == line_id and r["status"] in ("SCHEDULED", "IN_PROGRESS")
    ]


@bp.route("/tea-ops/runs", methods=["POST"])
def create_run():
    _, role = authenticate()
    authorize(role, ["ProductionPlanner"])
    body = body_json()
    # Priority 3: body FK resolution in canonical order
    # (line_id, batch_id, contract_id).
    line_id = body.get("line_id")
    batch_id = body.get("batch_id")
    contract_id = body.get("contract_id")
    line = batch = contract = None
    if line_id is not None:
        line = get_or_404(store.packaging_lines, line_id, "PackagingLine")
    if batch_id is not None:
        batch = get_or_404(store.batches, batch_id, "BlendBatch")
    if contract_id is not None:
        contract = get_or_404(store.contracts, contract_id, "PrivateLabelContract")

    # Priority 6: batch RELEASED; line ACTIVE; contract ACTIVE.
    if batch is not None and batch["status"] != "RELEASED":
        raise_err(ERR_BATCH_NOT_RELEASABLE, "Packed batch is not RELEASED")
    if line is not None and line["status"] != "ACTIVE":
        raise_err(ERR_LINE_NOT_ACTIVE, "Packaging line is not ACTIVE")
    if contract is not None and contract["status"] != "ACTIVE":
        raise_err(ERR_CONTRACT_NOT_ACTIVE, "Referenced contract is not ACTIVE")

    # Priority 13: field shape.
    if not isinstance(line_id, str) or not line_id:
        raise_err(ERR_INVALID_REQUEST, "line_id is required and must be a string")
    if not isinstance(batch_id, str) or not batch_id:
        raise_err(ERR_INVALID_REQUEST, "batch_id is required and must be a string")
    planned_start = req_datetime(body, "planned_start")
    planned_end = req_datetime(body, "planned_end")
    planned_units = body.get("planned_units")
    if not isinstance(planned_units, int) or isinstance(planned_units, bool) \
            or planned_units < 1:
        raise_err(ERR_INVALID_REQUEST, "planned_units must be an integer >= 1")

    # Priority 9: temporal checks — window validity, half-open overlap,
    # allergen changeover buffer.
    if planned_start >= planned_end:
        raise_err(ERR_INVALID_WINDOW, "planned_start must be strictly before planned_end")
    booked = _booked_runs_on_line(line["id"])
    for other in booked:
        # Half-open [start, end) overlap; adjacency allowed.
        if planned_start < other["planned_end"] and other["planned_start"] < planned_end:
            raise_err(
                ERR_LINE_WINDOW_CONFLICT,
                "Window overlaps another booked run on this line",
            )
    new_tags = set(batch["allergen_tags"])
    for other in booked:
        other_batch = store.batches.get(other["batch_id"])
        other_tags = set(other_batch["allergen_tags"]) if other_batch else set()
        if other_tags == new_tags:
            continue
        if other["planned_end"] <= planned_start:
            gap = planned_start - other["planned_end"]
        else:
            gap = other["planned_start"] - planned_end
        if gap < timedelta(minutes=ALLERGEN_CHANGEOVER_MINUTES):
            raise_err(
                ERR_ALLERGEN_CHANGEOVER_BUFFER,
                "Gap to an adjacent run with a different allergen tag set "
                "is under 45 minutes",
            )

    # Priority 10: contract-recipe agreement, then line format.
    if contract is not None and contract["recipe_id"] != batch["recipe_id"]:
        raise_err(
            ERR_CONTRACT_RECIPE_MISMATCH,
            "Contract recipe does not match the packed batch's recipe",
        )
    if line["line_type"] != batch["pack_format"]:
        raise_err(
            ERR_LINE_FORMAT_MISMATCH,
            "Packaging line type does not match the batch pack format",
        )
    # Priority 12: private-label minimum at scheduling.
    if contract is not None and planned_units < contract["minimum_units_per_run"]:
        raise_err(
            ERR_PRIVATE_LABEL_MINIMUM_UNMET,
            "planned_units below the contract minimum_units_per_run",
        )

    rec = new_record()
    rec.update({
        "line_id": line["id"],
        "batch_id": batch["id"],
        "contract_id": contract["id"] if contract else None,
        "planned_start": planned_start,
        "planned_end": planned_end,
        "planned_units": planned_units,
        "actual_units": None,
        "provisional_shelf_life_days": compute_provisional_shelf_life_days(batch),
        "final_shelf_life_days": None,
        "started_at": None,
        "completed_at": None,
        "status": "SCHEDULED",
    })
    store.production_runs[rec["id"]] = rec
    return success_object(run_out(rec), 201)


@bp.route("/tea-ops/runs/<rid>", methods=["GET"])
def get_run(rid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    return success_object(run_out(_run_or_404(rid)))


@bp.route("/tea-ops/runs", methods=["GET"])
def list_runs():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    records = list(store.production_runs.values())
    line_id = request.args.get("line_id")
    batch_id = request.args.get("batch_id")
    contract_id = request.args.get("contract_id")
    status = request.args.get("status")
    if line_id is not None:
        records = [r for r in records if r["line_id"] == line_id]
    if batch_id is not None:
        records = [r for r in records if r["batch_id"] == batch_id]
    if contract_id is not None:
        records = [r for r in records if r["contract_id"] == contract_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records, run_out)


@bp.route("/tea-ops/runs/<rid>/start", methods=["POST"])
def start_run(rid):
    _, role = authenticate()
    authorize(role, ["ProductionPlanner"])
    run = _run_or_404(rid)
    _guard_run_terminal(run)
    if run["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Run is not SCHEDULED")
    line = store.packaging_lines.get(run["line_id"])
    if line is None or line["status"] != "ACTIVE":
        raise_err(ERR_LINE_NOT_ACTIVE, "Packaging line is not ACTIVE")
    now = clock.now()
    if not (run["planned_start"] <= now < run["planned_end"]):
        raise_err(
            ERR_RUN_OUTSIDE_WINDOW,
            "Logical clock is outside [planned_start, planned_end)",
        )
    run["started_at"] = now
    run["status"] = "IN_PROGRESS"
    bump(run)
    return success_object(run_out(run))


@bp.route("/tea-ops/runs/<rid>/complete", methods=["POST"])
def complete_run(rid):
    _, role = authenticate()
    authorize(role, ["ProductionPlanner"])
    run = _run_or_404(rid)
    _guard_run_terminal(run)
    if run["status"] != "IN_PROGRESS":
        raise_err(ERR_INVALID_STATE, "Run is not IN_PROGRESS")
    batch = store.batches.get(run["batch_id"])
    if batch is None or batch["status"] != "RELEASED":
        raise_err(ERR_BATCH_NOT_RELEASABLE, "Packed batch is not RELEASED")
    # Priority 13: field shape.
    body = body_json()
    actual_units = body.get("actual_units")
    if not isinstance(actual_units, int) or isinstance(actual_units, bool) \
            or actual_units < 1:
        raise_err(ERR_INVALID_REQUEST, "actual_units must be an integer >= 1")
    # Priority 12: private-label minimum at completion.
    contract = None
    if run["contract_id"] is not None:
        contract = store.contracts.get(run["contract_id"])
    if contract is not None and actual_units < contract["minimum_units_per_run"]:
        raise_err(
            ERR_PRIVATE_LABEL_MINIMUM_UNMET,
            "actual_units below the contract minimum_units_per_run",
        )

    now = clock.now()
    run["completed_at"] = now
    run["actual_units"] = actual_units
    run["final_shelf_life_days"] = compute_final_shelf_life_days(run, batch, now)
    run["status"] = "COMPLETED"
    bump(run)

    if contract is not None:
        contract["fulfilled_units"] += actual_units
        if contract["status"] == "ACTIVE" \
                and contract["fulfilled_units"] >= contract["contracted_total_units"]:
            # Bubble-up: contract promotes itself ACTIVE -> FULFILLED.
            contract["status"] = "FULFILLED"
        bump(contract)
    return success_object(run_out(run))


@bp.route("/tea-ops/runs/<rid>/cancel", methods=["POST"])
def cancel_run(rid):
    _, role = authenticate()
    authorize(role, ["ProductionPlanner"])
    run = _run_or_404(rid)
    _guard_run_terminal(run)
    if run["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Only a SCHEDULED run can be cancelled")
    run["status"] = "CANCELLED"
    bump(run)
    return success_object(run_out(run))
