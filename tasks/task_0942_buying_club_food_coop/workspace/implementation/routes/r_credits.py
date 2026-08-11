"""Credit grants (3 endpoints) and the logical clock (1 endpoint)."""

from flask import Blueprint

from core import clock, serialize
from core.constants import CREDIT_SOURCES, CREDIT_STATUSES, ROLES
from core.envelope import created, ok, page
from core.ladder import (body_fk, endpoint, enum_filter, free_filter, pagination,
                         path_row, req_id, req_instant, req_int, rung_occ)
from core.store import DB, touch
from services import credits

bp = Blueprint("credits", __name__)
R5 = list(ROLES)


@bp.post("/credit-grants")
@endpoint(["ClubAdmin"])
def create_credit_grant(ctx):
    member = body_fk(ctx, "member_id")                     # rung 5
    req_id(ctx, "member_id")                               # rung 7
    amount_cents = req_int(ctx, "amount_cents", minimum=1)
    expires_raw, _expires_at = req_instant(ctx, "expires_at")
    req_int(ctx, "expected_member_version")
    rung_occ(ctx, "expected_member_version", member)       # rung 25
    credits.sweep(member["id"])
    row = credits.mint(member["id"], amount_cents, expires_raw, "ADJUSTMENT")
    touch(member)
    return created(serialize.credit_grant(row))


@bp.get("/credit-grants")
@endpoint(R5)
def list_credit_grants(ctx):
    limit, offset = pagination(ctx)
    status = enum_filter(ctx, "status", CREDIT_STATUSES)
    source = enum_filter(ctx, "source", CREDIT_SOURCES)
    member_id = free_filter(ctx, "member_id")
    source_member_order_id = free_filter(ctx, "source_member_order_id")
    rows = []
    for row in DB.all("CreditGrant"):
        if member_id is not None and row["member_id"] != member_id:
            continue
        if source_member_order_id is not None and row["source_member_order_id"] != source_member_order_id:
            continue
        if status is not None and row["status"] != status:
            continue
        if source is not None and row["source"] != source:
            continue
        rows.append(row)
    return page(serialize.project_all(rows), limit, offset)


@bp.get("/credit-grants/<credit_grant_id>")
@endpoint(R5)
def read_credit_grant(ctx, credit_grant_id):
    return ok(serialize.credit_grant(path_row("credit_grant_id", credit_grant_id)))


@bp.post("/_clock/set_current_utc")
@endpoint(["ClubAdmin"])
def set_clock(ctx):
    raw, parsed = req_instant(ctx, "to_iso8601")           # rung 7
    clock.CLOCK.set(parsed)
    # The caller's string is echoed byte-verbatim; it is never re-rendered.
    return ok({"current_utc": raw})
