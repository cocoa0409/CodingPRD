"""Scheduling runs (PRD 3.3): DRAFT lifecycle, OCC on the term version, and
the finalization placement pass."""

import db
import serializers
from clock import clock, render_server
from errors import ApiError
from middleware import endpoint
from routes.common import list_response, one
from services.placement import run_placement
from validate import get_run, get_term, req_int, req_str


@endpoint("POST", "/campus/scheduling-runs", roles=["Scheduler"], code=201)
def create_run(ctx):
    body = ctx.body
    term_id = req_str(body, "term_id")
    term = get_term(term_id)  # body FK existence (rung 3)
    expected_term_version = req_int(body, "expected_term_version")
    # OCC (rung 5): the client's last observed term version must still be
    # current.
    if expected_term_version != term["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_term_version does not match the term's current version.",
        )
    if term["status"] == "CLOSED":
        raise ApiError("ERR_INVALID_STATE", "A closed term accepts no new scheduling runs.")

    prior_draft = None
    if term.get("current_draft_run_id"):
        prior_draft = db.scheduling_runs.get(term["current_draft_run_id"])

    row = db.new_row(
        db.scheduling_runs,
        term_id=term["id"],
        status="DRAFT",
        placed_count=0,
        bumped_event_ids=[],
        unplaced_block_ids=[],
        finalized_at=None,
    )
    # Creating a new run supersedes the term's prior DRAFT and repoints the
    # term's live draft.
    if prior_draft is not None and prior_draft.get("status") == "DRAFT":
        db.set_fields(prior_draft, status="SUPERSEDED")
    term["current_draft_run_id"] = row["id"]
    db.touch(term)
    return one(serializers.scheduling_run(row), status=201)


@endpoint("GET", "/campus/scheduling-runs/{id}", roles=["Scheduler"], code=200)
def get_run_detail(ctx):
    return one(serializers.scheduling_run(get_run(ctx.id)))


@endpoint("GET", "/campus/scheduling-runs", roles=["Scheduler"], code=200)
def list_runs(ctx):
    rows = db.all_of(db.scheduling_runs)
    return list_response(
        rows,
        ctx.args,
        serializers.scheduling_run,
        mapping={
            "term_id": lambda r: r.get("term_id"),
            "status": lambda r: r.get("status"),
        },
    )


@endpoint("POST", "/campus/scheduling-runs/{id}/finalize", roles=["Scheduler"], code=200)
def finalize_run(ctx):
    run = get_run(ctx.id)
    if run["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT run can be finalized.")
    term = get_term(run["term_id"])
    if term["status"] != "SCHEDULING":
        raise ApiError(
            "ERR_TERM_PRIORITY_LOCKED",
            "Finalizing a placement run requires the term to be in SCHEDULING.",
        )
    for other in db.scheduling_runs.values():
        if (
            other["id"] != run["id"]
            and other.get("term_id") == term["id"]
            and other.get("status") == "FINALIZED"
        ):
            raise ApiError(
                "ERR_TERM_ALREADY_FINALIZED",
                "Another finalized scheduling run already exists for the term.",
            )

    run_placement(run, term, clock.now)

    run["status"] = "FINALIZED"
    run["finalized_at"] = render_server(clock.now)
    db.touch(run)
    # The run is no longer DRAFT, so the term's live-draft pointer clears.
    term["current_draft_run_id"] = None
    db.touch(term)
    return one(serializers.scheduling_run(run))
