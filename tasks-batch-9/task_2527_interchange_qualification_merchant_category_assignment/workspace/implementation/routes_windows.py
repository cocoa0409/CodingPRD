"""Acquirer implementation windows (PRD 3.2)."""

from flask import Blueprint

import calc
import listing
import resolve
import validate as v
from auth import ALL_ROLES, authenticate, require_scope
from envelope import array_response, object_response, paginate
from errors import (
    ERR_IMPLEMENTATION_WINDOW_OUT_OF_BOUNDS,
    ERR_INVALID_STATE,
    ERR_PLATFORM_WINDOW_CONFLICT,
    fail,
)
from store import new_row, serialize, serialize_many, sorted_rows, store, touch

bp = Blueprint("windows", __name__)


@bp.post("/implementation-windows")
def create_window():
    caller = authenticate(["AcquirerOps", "NetworkAdmin"])
    data = v.body()

    # Priority 4: body references, in the order the endpoint declares them.
    acquirer_id = v.raw_id(data, "acquirer_id")
    if acquirer_id is not None:
        resolve.acquirer(acquirer_id)
    version_id = v.raw_id(data, "rate_program_version_id")
    if version_id is not None:
        resolve.rate_version(version_id)
    platform_id = v.raw_id(data, "platform_id")
    if platform_id is not None:
        resolve.platform(platform_id)

    # Priority 5: request shape.
    fields = {
        "acquirer_id": v.req_str(data, "acquirer_id"),
        "rate_program_version_id": v.req_str(data, "rate_program_version_id"),
        "platform_id": v.req_str(data, "platform_id"),
        "window_start": v.req_ts(data, "window_start"),
        "window_end": v.req_ts(data, "window_end"),
        "status": "SCHEDULED",
        "started_at": None,
        "completion_note": None,
    }
    if not fields["window_start"] < fields["window_end"]:
        v.bad("'window_start' must be strictly earlier than 'window_end'.")

    # Priority 6: the acting acquirer owns the window it schedules.
    require_scope(caller, fields["acquirer_id"])

    version = store.rate_versions[fields["rate_program_version_id"]]
    platform = store.platforms[fields["platform_id"]]

    # Priority 7: the referenced version must be PUBLISHED.
    if version["status"] != "PUBLISHED":
        fail(ERR_INVALID_STATE, "The rate program version is not PUBLISHED.")

    # Priority 20: the publication-to-deadline envelope, both bounds inclusive.
    if (version["published_at"] is None
            or fields["window_start"] < version["published_at"]
            or fields["window_end"] > version["implementation_deadline"]):
        fail(ERR_IMPLEMENTATION_WINDOW_OUT_OF_BOUNDS)

    # Priority 22: buffered platform capacity.
    if calc.platform_window_conflict(platform, fields["window_start"], fields["window_end"]):
        fail(ERR_PLATFORM_WINDOW_CONFLICT)

    row = new_row(fields)
    store.windows[row["id"]] = row
    return object_response(serialize("AcquirerImplementationWindow", row), 201)


@bp.post("/implementation-windows/<row_id>/start")
def start_window(row_id):
    caller = authenticate(["AcquirerOps", "NetworkAdmin"])
    row = resolve.window(row_id)
    require_scope(caller, row["acquirer_id"])
    if row["status"] != "SCHEDULED":
        fail(ERR_INVALID_STATE, "Only a SCHEDULED window may be started.")
    version = store.rate_versions.get(row["rate_program_version_id"])
    if version is None or version["status"] != "PUBLISHED":
        fail(ERR_INVALID_STATE, "The rate program version is no longer PUBLISHED.")
    row["status"] = "IN_PROGRESS"
    row["started_at"] = store.now_ms()
    touch(row)
    return object_response(serialize("AcquirerImplementationWindow", row))


@bp.post("/implementation-windows/<row_id>/complete")
def complete_window(row_id):
    caller = authenticate(["AcquirerOps", "NetworkAdmin"])
    row = resolve.window(row_id)
    data = v.body()
    note = v.req_str(data, "completion_note", 1, 500)
    require_scope(caller, row["acquirer_id"])
    if row["status"] == "IN_PROGRESS":
        row["status"] = "COMPLETED"
    elif row["status"] == "MISSED":
        row["status"] = "COMPLETED_LATE"
    else:
        fail(ERR_INVALID_STATE, "Completion is only reportable from IN_PROGRESS or MISSED.")
    row["completion_note"] = note
    touch(row)
    acquirer = store.acquirers.get(row["acquirer_id"])
    if acquirer is not None:
        calc.recompute_acquirer_compliance(acquirer)
    return object_response(serialize("AcquirerImplementationWindow", row))


@bp.get("/implementation-windows/<row_id>")
def get_window(row_id):
    caller = authenticate(ALL_ROLES)
    row = resolve.window(row_id)
    require_scope(caller, row["acquirer_id"])
    return object_response(serialize("AcquirerImplementationWindow", row))


@bp.get("/implementation-windows")
def list_windows():
    authenticate(ALL_ROLES)
    rows = sorted_rows(list(store.windows.values()))
    rows = listing.apply_string_filters(rows, [
        ("acquirer_id", "acquirer_id"),
        ("rate_program_version_id", "rate_program_version_id"),
        ("platform_id", "platform_id"),
        ("status", "status"),
    ])
    page, meta = paginate(rows)
    return array_response(serialize_many("AcquirerImplementationWindow", page), meta)
