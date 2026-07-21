"""Reconciliation runs: preparation, finalization and reopening."""
from flask import Blueprint

import calc
from core import (
    ApiError, authenticate, body, db, fetch, get_enum, get_int, get_str,
    new_row, ok, ok_list, paged, pagination, public, q_enum, rows, touch,
)

bp = Blueprint("recon", __name__)

RUN_STATUSES = ("PREPARED", "FINALIZED", "SUPERSEDED")
BASES = ("BOOKED", "CASH_BASIS")
RUN_READERS = ("EventOrganizer", "FinanceOfficer")


@bp.post("/api/events/<eid>/reconciliation-runs")
def create_run(eid):
    uid, _role = authenticate(("FinanceOfficer",))
    payload = body()
    expected_version = get_int(payload, "expected_event_version", minimum=0)
    basis = get_enum(payload, "revenue_basis", BASES)
    event = fetch("events", eid)

    for run in db.runs.values():
        if run["event_id"] == event["id"] and run["status"] == "FINALIZED":
            raise ApiError("ERR_RUN_ALREADY_FINALIZED",
                           "a finalized run already exists for this event")
    if expected_version != event["version"]:
        raise ApiError("ERR_STALE_EVENT_VERSION", "the event version has advanced")

    for run in rows("runs"):
        if run["event_id"] == event["id"] and run["status"] == "PREPARED":
            run["status"] = "SUPERSEDED"
            touch(run)

    run = new_row(event_id=event["id"], revenue_basis=basis,
                  expected_total_cents=0, collected_total_cents=0,
                  variance_cents=0, is_material_variance=False,
                  channel_breakdown=[], prepared_by_user_id=uid,
                  finalized_by_user_id=None, status="PREPARED")
    calc.compute_run(run, event)
    db.runs[run["id"]] = run
    touch(event)
    return ok(public(run), 201)


@bp.get("/api/reconciliation-runs/<rid>")
def read_run(rid):
    authenticate(RUN_READERS)
    return ok(public(fetch("runs", rid)))


@bp.get("/api/events/<eid>/reconciliation-runs")
def list_runs(eid):
    authenticate(RUN_READERS)
    limit, offset = pagination()
    status = q_enum("status", RUN_STATUSES)
    event = fetch("events", eid)
    items = [r for r in rows("runs")
             if r["event_id"] == event["id"]
             and (status is None or r["status"] == status)]
    window, total = paged(items, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.post("/api/reconciliation-runs/<rid>/finalize")
def finalize_run(rid):
    uid, _role = authenticate(("FinanceOfficer",))
    payload = body()
    note = get_str(payload, "variance_override_note", required=False,
                   default=None, allow_empty=True)
    run = fetch("runs", rid)
    event = fetch("events", run["event_id"])
    if run["status"] != "PREPARED":
        raise ApiError("ERR_RUN_ALREADY_FINALIZED", "the run is not PREPARED")
    if uid == run["prepared_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the preparing user may not finalize the run")
    if calc.event_unpaid_invoices(event["id"]) != 0:
        raise ApiError("ERR_OPEN_INVOICES_REMAIN", "unpaid invoices remain")
    if run["is_material_variance"] and (note is None or note.strip() == ""):
        raise ApiError("ERR_MATERIAL_VARIANCE",
                       "a variance override note is required")
    run["status"] = "FINALIZED"
    run["finalized_by_user_id"] = uid
    touch(run)
    return ok(public(run))


@bp.post("/api/reconciliation-runs/<rid>/reopen")
def reopen_run(rid):
    authenticate(("FinanceOfficer",))
    run = fetch("runs", rid)
    event = fetch("events", run["event_id"])
    if run["status"] != "FINALIZED":
        raise ApiError("ERR_INVALID_STATE", "the run is not FINALIZED")
    if event["status"] == "CLOSED":
        raise ApiError("ERR_INVALID_STATE", "the event is already closed")
    run["status"] = "PREPARED"
    run["finalized_by_user_id"] = None
    calc.compute_run(run, event)
    touch(run)
    return ok(public(run))
