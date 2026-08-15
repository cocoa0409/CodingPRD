"""Payment allocation endpoints (PRD 3.3): read one append-only ledger entry
or list the collection with payment_id / charge_id filters."""

from flask import Blueprint

import db
import errors
import middleware
import response
import serializers
import validators as V

bp = Blueprint("allocations", __name__)


@bp.get("/allocations/<allocation_id>")
def get_allocation(allocation_id):
    uid, role = middleware.current_user()
    middleware.require_role(role, middleware.ALL)
    alloc = db.allocations.get(allocation_id)
    if alloc is None:
        errors.fail(errors.ERR_NOT_FOUND, "Allocation %s does not exist." % allocation_id)
    if role == "Tenant":
        payment = db.payments[alloc["payment_id"]]
        if payment["tenant_id"] != uid:
            errors.fail(
                errors.ERR_UNAUTHORIZED,
                "A Tenant may read only allocations of their own payments.",
            )
    return response.success_object(serializers.allocation_view(alloc))


@bp.get("/allocations")
def list_allocations():
    uid, role = middleware.current_user()
    middleware.require_role(role, middleware.ALL)
    rows = list(db.allocations.values())
    if role == "Tenant":
        rows = [
            a for a in rows
            if db.payments[a["payment_id"]]["tenant_id"] == uid
        ]
    page, limit, offset, total = V.sorted_page(rows, [
        ("payment_id", V.query_filter("payment_id")),
        ("charge_id", V.query_filter("charge_id")),
    ])
    return response.success_list(
        [serializers.allocation_view(a) for a in page], limit, offset, total
    )
