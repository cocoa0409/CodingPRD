"""The order cutoff calendar: election windows, publishing and the lock cascade."""

from flask import Blueprint

import serialize
from auth import authenticate, resolve_employer, resolve_window
from cascades import lock_window_cascade
from errors import fail
from guards import TERMINAL_WINDOW, require_employer_active, require_not_terminal, \
    require_transition
from responses import array_response, created_response, object_response, paginate
from store import bump, sorted_rows, stamp_new, store
from validate import (
    WINDOW_STATUSES,
    enum_filter,
    field,
    pagination,
    parse_body,
    str_filter,
)

bp = Blueprint("windows", __name__)

BLOCKING_WINDOW_STATUSES = ("SCHEDULED", "OPEN", "LOCKED")


@bp.post("/benefits/election-windows")
def create_window():
    authenticate(["ProgramAdmin"])
    specs = [
        field("employer_id", "id", required=True),
        field("benefit_month", "month", required=True),
        field("opens_at", "datetime", required=True),
        field("cutoff_at", "datetime", required=True),
        field("fulfillment_lead_days", "integer", default=5, minimum=0),
        field("mid_month_change_allowed", "boolean", default=False),
    ]
    body, values = parse_body(specs)
    employer = resolve_employer(values["employer_id"])

    opens_at = values["opens_at"]
    cutoff_at = values["cutoff_at"]
    for existing in store.election_windows.values():
        if existing["employer_id"] != employer["id"]:
            continue
        if existing["status"] not in BLOCKING_WINDOW_STATUSES:
            continue
        if opens_at < existing["_cutoff_at"] and cutoff_at > existing["_opens_at"]:
            fail("ERR_ELECTION_WINDOW_OVERLAP",
                 "The requested calendar interval intersects election window %s."
                 % existing["id"])

    row = {
        "employer_id": employer["id"],
        "benefit_month": values["benefit_month"],
        "opens_at": body["opens_at"],
        "cutoff_at": body["cutoff_at"],
        "_opens_at": opens_at,
        "_cutoff_at": cutoff_at,
        "fulfillment_lead_days": values["fulfillment_lead_days"],
        "mid_month_change_allowed": values["mid_month_change_allowed"],
        "status": "SCHEDULED",
        "locked_at": None,
    }
    stamp_new(row)
    store.election_windows[row["id"]] = row
    return created_response(serialize.election_window(row))


@bp.get("/benefits/election-windows/<window_id>")
def read_window(window_id):
    authenticate(["ProgramAdmin", "Employee", "OrderDesk"])
    row = resolve_window(window_id)
    return object_response(serialize.election_window(row))


@bp.get("/benefits/election-windows")
def list_windows():
    authenticate(["ProgramAdmin", "Employee", "OrderDesk"])
    employer_id = str_filter("employer_id")
    status = enum_filter("status", WINDOW_STATUSES)
    month = str_filter("benefit_month")
    limit, offset = pagination()
    rows = []
    for row in store.election_windows.values():
        if employer_id is not None and row["employer_id"] != employer_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if month is not None and row["benefit_month"] != month:
            continue
        rows.append(row)
    rows = sorted_rows(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([serialize.election_window(r) for r in page],
                          limit, offset, total)


@bp.post("/benefits/election-windows/<window_id>/open")
def open_window(window_id):
    authenticate(["ProgramAdmin"])
    row = resolve_window(window_id)
    employer = store.employers.get(row["employer_id"])
    require_employer_active(employer)
    require_not_terminal(row, "status", TERMINAL_WINDOW, "ElectionWindow")
    require_transition(row["status"] == "SCHEDULED",
                       "ElectionWindow %s cannot be published from %s."
                       % (row["id"], row["status"]))
    row["status"] = "OPEN"
    bump(row)
    return object_response(serialize.election_window(row))


@bp.post("/benefits/election-windows/<window_id>/lock")
def lock_window(window_id):
    authenticate(["ProgramAdmin"])
    row = resolve_window(window_id)
    employer = store.employers.get(row["employer_id"])
    require_employer_active(employer)
    require_not_terminal(row, "status", TERMINAL_WINDOW, "ElectionWindow")
    require_transition(row["status"] == "OPEN",
                       "ElectionWindow %s cannot be locked from %s."
                       % (row["id"], row["status"]))
    lock_window_cascade(row, employer)
    return object_response(serialize.election_window(row))
