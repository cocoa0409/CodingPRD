"""Payment records (2 endpoints)."""

from flask import Blueprint

from core import serialize
from core.constants import PAYMENT_KINDS, PAYMENT_RECORD_STATUSES, ROLES
from core.envelope import ok, page
from core.ladder import endpoint, enum_filter, free_filter, pagination, path_row
from core.store import DB

bp = Blueprint("payments", __name__)
R5 = list(ROLES)


@bp.get("/payments")
@endpoint(R5)
def list_payments(ctx):
    limit, offset = pagination(ctx)
    kind = enum_filter(ctx, "kind", PAYMENT_KINDS)
    status = enum_filter(ctx, "status", PAYMENT_RECORD_STATUSES)
    member_order_id = free_filter(ctx, "member_order_id")
    rows = []
    for row in DB.all("Payment"):
        if member_order_id is not None and row["member_order_id"] != member_order_id:
            continue
        if kind is not None and row["kind"] != kind:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return page(serialize.project_all(rows), limit, offset)


@bp.get("/payments/<payment_id>")
@endpoint(R5)
def read_payment(ctx, payment_id):
    return ok(serialize.payment(path_row("payment_id", payment_id)))
