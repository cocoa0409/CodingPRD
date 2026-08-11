"""Grants, scholarship awards, charges and allocation lines (PRD §3.8)."""

from flask import Blueprint, request

from core import timeutil as T
from core.constants import (
    DEMOGRAPHIC_GROUPS,
    PROGRAM_CODES,
    SCHOLARSHIP_MAX_CAP_PCT,
)
from core.envelope import list_response, object_response
from core.errors import fail
from core.ladder import (
    Field, endpoint, pagination, paginate, query_enum, validate_body,
)
from core.lookups import resource_or_404, rider_or_404
from core.store import all_rows, clock, new_row, touch
from domain import derive, funding, serialize

bp = Blueprint("money", __name__)

AWARD_STATUSES = ["ACTIVE", "EXHAUSTED", "SUPERSEDED"]
CHARGE_STATUSES = ["PENDING", "FUNDED", "REVERSED"]
CHARGE_TYPES = ["SESSION_FEE", "LATE_CANCELLATION_FEE", "NO_SHOW_FEE"]
SOURCE_TYPES = ["GRANT", "SCHOLARSHIP", "SLIDING_SCALE", "PAYER", "PRIVATE_PAY"]
ALLOCATION_STATUSES = ["ALLOCATED", "RELEASED"]


def _period_cross(payload):
    start = payload.get("period_start")
    end = payload.get("period_end")
    if isinstance(start, str) and isinstance(end, str):
        parsed_start = T.parse_date(start)
        parsed_end = T.parse_date(end)
        if parsed_start is not None and parsed_end is not None \
                and parsed_end < parsed_start:
            fail("ERR_VALIDATION", "period_end must not precede period_start.")


@bp.post("/grants")
@endpoint(["ProgramAdmin"])
def create_grant():
    payload = validate_body([
        Field("grant_name", "string", required=True),
        Field("funder_name", "string", required=True),
        Field("awarded_amount_cents", "int", required=True, exclusive_min=0),
        Field("period_start", "date", required=True),
        Field("period_end", "date", required=True),
        Field("restricted_program_code", "enum", members=PROGRAM_CODES),
        Field("restricted_demographic", "enum", members=DEMOGRAPHIC_GROUPS),
    ], cross=_period_cross)
    row = new_row("grants")
    row.update({
        "grant_name": payload["grant_name"],
        "funder_name": payload["funder_name"],
        "awarded_amount_cents": payload["awarded_amount_cents"],
        "restricted_program_code": payload.get("restricted_program_code"),
        "restricted_demographic": payload.get("restricted_demographic"),
        "period_start": payload["period_start"],
        "period_end": payload["period_end"],
    })
    return object_response(serialize.grant(row), 201)


@bp.get("/grants/<grant_id>")
@endpoint(["ProgramAdmin", "BillingClerk"])
def read_grant(grant_id):
    return object_response(serialize.grant(resource_or_404("grants", grant_id)))


@bp.post("/riders/<rider_id>/scholarship-awards")
@endpoint(["IntakeCoordinator", "ProgramAdmin"])
def create_award(rider_id):
    payload = validate_body([
        Field("cap_pct", "number", required=True, exclusive_min=0,
              maximum=float(SCHOLARSHIP_MAX_CAP_PCT)),
        Field("period_cap_cents", "int", required=True, exclusive_min=0),
        Field("period_start", "date", required=True),
        Field("period_end", "date", required=True),
    ], cross=_period_cross)
    rider_or_404(rider_id)
    new_start = T.parse_date(payload["period_start"])
    new_end = T.parse_date(payload["period_end"])

    row = new_row("scholarship_awards")
    row.update({
        "rider_id": rider_id,
        "cap_pct": payload["cap_pct"],
        "period_cap_cents": payload["period_cap_cents"],
        "period_start": payload["period_start"],
        "period_end": payload["period_end"],
        "superseded_at": None,
    })
    for award in derive.rider_awards(rider_id):
        if award["id"] == row["id"]:
            continue
        if derive.award_status(award) != "ACTIVE":
            continue
        start = T.parse_date(award["period_start"])
        end = T.parse_date(award["period_end"])
        if new_start <= end and start <= new_end:
            award["superseded_at"] = clock.stamp()
            touch(award)
    return object_response(serialize.scholarship_award(row), 201)


@bp.get("/scholarship-awards")
@endpoint(["IntakeCoordinator", "ProgramAdmin", "BillingClerk"])
def list_awards():
    limit, offset = pagination()
    status = query_enum("status", AWARD_STATUSES)
    rider_id = request.args.get("rider_id")
    rows = all_rows("scholarship_awards")
    if rider_id is not None:
        rows = [r for r in rows if r["rider_id"] == rider_id]
    if status is not None:
        rows = [r for r in rows if derive.award_status(r) == status]
    page = paginate(rows, limit, offset)
    return list_response([serialize.scholarship_award(r) for r in page],
                         limit, offset, len(rows))


@bp.get("/scholarship-awards/<award_id>")
@endpoint(["IntakeCoordinator", "ProgramAdmin", "BillingClerk"])
def read_award(award_id):
    return object_response(serialize.scholarship_award(
        resource_or_404("scholarship_awards", award_id)))


@bp.get("/charges")
@endpoint(["BillingClerk", "ProgramAdmin", "IntakeCoordinator"])
def list_charges():
    limit, offset = pagination()
    status = query_enum("status", CHARGE_STATUSES)
    charge_type = query_enum("charge_type", CHARGE_TYPES)
    session_id = request.args.get("session_id")
    rows = all_rows("charges")
    if session_id is not None:
        rows = [r for r in rows if r["session_id"] == session_id]
    if charge_type is not None:
        rows = [r for r in rows if r["charge_type"] == charge_type]
    if status is not None:
        rows = [r for r in rows if derive.charge_status(r) == status]
    page = paginate(rows, limit, offset)
    return list_response([serialize.charge(r) for r in page],
                         limit, offset, len(rows))


@bp.get("/charges/<charge_id>")
@endpoint(["BillingClerk", "ProgramAdmin", "IntakeCoordinator"])
def read_charge(charge_id):
    return object_response(serialize.charge(resource_or_404("charges", charge_id)))


@bp.post("/charges/<charge_id>/reverse")
@endpoint(["BillingClerk", "ProgramAdmin"])
def reverse_charge(charge_id):
    payload = validate_body([Field("reason", "string", required=True)])
    row = resource_or_404("charges", charge_id)
    if derive.charge_status(row) not in ("PENDING", "FUNDED"):
        fail("ERR_INVALID_STATE", "That charge is already reversed.")
    funding.reverse_charge(row, payload["reason"])
    return object_response(serialize.charge(row))


@bp.get("/funding-allocations")
@endpoint(["BillingClerk", "ProgramAdmin"])
def list_allocations():
    limit, offset = pagination()
    status = query_enum("status", ALLOCATION_STATUSES)
    source_type = query_enum("source_type", SOURCE_TYPES)
    charge_id = request.args.get("charge_id")
    grant_id = request.args.get("grant_id")
    award_id = request.args.get("scholarship_award_id")
    rows = all_rows("funding_allocations")
    if charge_id is not None:
        rows = [r for r in rows if r["charge_id"] == charge_id]
    if grant_id is not None:
        rows = [r for r in rows if r.get("grant_id") == grant_id]
    if award_id is not None:
        rows = [r for r in rows if r.get("scholarship_award_id") == award_id]
    if source_type is not None:
        rows = [r for r in rows if r["source_type"] == source_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page = paginate(rows, limit, offset)
    return list_response([serialize.funding_allocation(r) for r in page],
                         limit, offset, len(rows))


@bp.get("/funding-allocations/<allocation_id>")
@endpoint(["BillingClerk", "ProgramAdmin"])
def read_allocation(allocation_id):
    return object_response(serialize.funding_allocation(
        resource_or_404("funding_allocations", allocation_id)))
