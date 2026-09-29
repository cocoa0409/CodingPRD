"""Agency budget requests and their review loop."""

from flask import Blueprint

import auth
import db
import response
from errors import fail
from services import constants as C
from services import core
from validators import (
    bad_amount,
    body_json,
    listing,
    peek_fk,
    query_enum,
    query_str,
    read_id,
    read_int,
    read_str,
)

bp = Blueprint("agency_requests", __name__)


def _expansion_measures_present(request_row):
    for package in core.packages_of(request_row["id"]):
        if package["package_type"] != "EXPANSION":
            continue
        measures = core.measures_of(package["id"])
        if not any(m["target_value"] > m["baseline_value"] for m in measures):
            return False
    return True


@bp.post("/fiscal/agency-requests")
def create_request():
    actor = auth.authenticate((auth.AGENCY_BUDGET_OFFICER,))
    body = body_json()

    cycle = peek_fk(body, "budget_cycle_id", core.get_cycle)
    agency = peek_fk(body, "agency_id", core.get_agency)
    if agency is not None:
        auth.require_agency_scope(actor, agency["id"])

    read_id(body, "budget_cycle_id")
    read_id(body, "agency_id")
    base_budget_cents = read_int(body, "base_budget_cents")
    if base_budget_cents <= 0:
        bad_amount("base_budget_cents must be greater than zero.")

    core.require_not_closed(cycle)

    for existing in db.agency_requests.values():
        if (
            existing["budget_cycle_id"] == cycle["id"]
            and existing["agency_id"] == agency["id"]
        ):
            fail(
                "ERR_DUPLICATE_AGENCY_REQUEST",
                "The agency already has a request in this budget cycle.",
            )

    row = db.new_row()
    row.update(
        {
            "budget_cycle_id": cycle["id"],
            "agency_id": agency["id"],
            "base_budget_cents": base_budget_cents,
            "status": "DRAFT",
            "revision_count": 0,
            "last_return_reason": None,
            "total_request_cents": base_budget_cents,
        }
    )
    db.agency_requests[row["id"]] = row
    return response.created(db.serialize(row))


@bp.get("/fiscal/agency-requests/<request_id>")
def read_request(request_id):
    auth.authenticate(auth.ANY_ROLE)
    row = core.get_request(request_id)
    return response.ok(db.serialize(row))


@bp.get("/fiscal/agency-requests")
def list_requests():
    auth.authenticate(auth.ANY_ROLE)
    cycle_id = query_str("budget_cycle_id")
    agency_id = query_str("agency_id")
    status = query_enum("status", C.REQUEST_STATUSES)
    rows = []
    for row in db.agency_requests.values():
        if cycle_id is not None and row["budget_cycle_id"] != cycle_id:
            continue
        if agency_id is not None and row["agency_id"] != agency_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    data, meta = listing(rows)
    return response.ok_list(data, meta)


@bp.post("/fiscal/agency-requests/<request_id>/submit")
def submit_request(request_id):
    actor = auth.authenticate((auth.AGENCY_BUDGET_OFFICER,))
    row = core.get_request(request_id)
    auth.require_agency_scope(actor, row["agency_id"])

    cycle = core.get_cycle(row["budget_cycle_id"])
    core.require_phase(cycle, ("DEVELOPMENT",))

    if row["status"] not in ("DRAFT", "RETURNED_FOR_REVISION"):
        fail(
            "ERR_INVALID_STATE",
            "A request in status %s may not be submitted." % row["status"],
        )
    if not _expansion_measures_present(row):
        fail(
            "ERR_PERFORMANCE_MEASURE_REQUIRED",
            "Every EXPANSION decision package needs a performance measure.",
        )

    core.recompute_request_total(row, {"status": "SUBMITTED"})
    return response.ok(db.serialize(row))


@bp.post("/fiscal/agency-requests/<request_id>/begin-review")
def begin_review(request_id):
    auth.authenticate((auth.BUDGET_ANALYST,))
    row = core.get_request(request_id)
    core.require_not_closed(core.get_cycle(row["budget_cycle_id"]))
    if row["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Only a SUBMITTED request may enter review.")
    db.apply_changes(row, {"status": "UNDER_REVIEW"})
    return response.ok(db.serialize(row))


@bp.post("/fiscal/agency-requests/<request_id>/return-for-revision")
def return_for_revision(request_id):
    auth.authenticate((auth.BUDGET_ANALYST,))
    row = core.get_request(request_id)
    body = body_json()
    reason = read_str(body, "reason", min_len=1, max_len=500)
    core.require_not_closed(core.get_cycle(row["budget_cycle_id"]))
    if row["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", "Only an UNDER_REVIEW request may be returned.")
    db.apply_changes(
        row,
        {
            "status": "RETURNED_FOR_REVISION",
            "revision_count": row["revision_count"] + 1,
            "last_return_reason": reason,
        },
    )
    return response.ok(db.serialize(row))


@bp.post("/fiscal/agency-requests/<request_id>/accept")
def accept_request(request_id):
    auth.authenticate((auth.BUDGET_ANALYST,))
    row = core.get_request(request_id)
    cycle = core.get_cycle(row["budget_cycle_id"])
    core.require_phase(cycle, ("DEVELOPMENT", "EXECUTIVE_PREP"))
    if row["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", "Only an UNDER_REVIEW request may be accepted.")
    core.recompute_request_total(row, {"status": "ACCEPTED"})
    return response.ok(db.serialize(row))
