"""Split-refund allocations (PRD §3.6): editable right up until transmit."""
import re

from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles
from response import created, no_content, ok, paginate
from services.serialize import allocation_json
from validation import get_body, parse_body, require_entity

bp = Blueprint("allocations", __name__)

ROUTING_RE = re.compile(r"^[0-9]{9}$")

# Allocations may be added/removed while the return is in these statuses.
EDITABLE_STATUSES = ("INTAKE_STARTED", "IN_PREPARATION", "QR_PASSED")

MAX_ALLOCATIONS = 3

CREATE_SCHEMA = {
    "tax_return_id": {"kind": "string", "required": True},
    "account_type": {"kind": "enum", "required": True,
                     "values": ["CHECKING", "SAVINGS"]},
    "routing_number": {"kind": "string", "required": True},
    "account_number_mask": {"kind": "string", "required": True},
    "amount_cents": {"kind": "integer", "required": True, "min": 1},
}


def _require_owner(ret, uid):
    """The owning Preparer manages a return's allocations (PRD §3.6)."""
    if uid != ret["preparer_id"]:
        raise ApiError("ERR_NOT_RETURN_OWNER", 403,
                       "Only the return's owning Preparer manages its allocations")


@bp.post("/refund-allocations")
def create_allocation():
    uid, role, _ = get_context()
    require_roles(["Preparer"])
    raw = get_body()
    return_id = raw.get("tax_return_id")
    if isinstance(return_id, str) and return_id not in store.tax_returns:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced tax return does not exist")
    body = parse_body(CREATE_SCHEMA)
    ret = store.tax_returns.get(body["tax_return_id"])
    if ret is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "tax_return_id has a wrong type")
    if not ROUTING_RE.match(body["routing_number"]):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "routing_number must be exactly nine digits")
    _require_owner(ret, uid)
    if ret["status"] not in EDITABLE_STATUSES:
        raise ApiError("ERR_INVALID_TRANSITION", 409,
                       "Allocations are editable only while the return is "
                       "INTAKE_STARTED, IN_PREPARATION, or QR_PASSED")
    existing = [a for a in store.refund_allocations.values()
                if a["tax_return_id"] == ret["id"]]
    if len(existing) >= MAX_ALLOCATIONS:
        raise ApiError("ERR_ALLOCATION_LIMIT", 422,
                       "Return already carries three refund allocations")
    alloc = db.new_common({
        "tax_return_id": ret["id"],
        "account_type": body["account_type"],
        "routing_number": body["routing_number"],
        "account_number_mask": body["account_number_mask"],
        "amount_cents": body["amount_cents"],
    })
    store.refund_allocations[alloc["id"]] = alloc
    return created(allocation_json(alloc))


@bp.delete("/refund-allocations/<alloc_id>")
def delete_allocation(alloc_id):
    uid, role, _ = get_context()
    require_roles(["Preparer"])
    alloc = require_entity(store.refund_allocations, alloc_id)
    ret = store.tax_returns[alloc["tax_return_id"]]
    _require_owner(ret, uid)
    if ret["status"] not in EDITABLE_STATUSES:
        raise ApiError("ERR_INVALID_TRANSITION", 409,
                       "Allocations are editable only while the return is "
                       "INTAKE_STARTED, IN_PREPARATION, or QR_PASSED")
    del store.refund_allocations[alloc_id]
    return no_content()


@bp.get("/tax-returns/<return_id>/refund-allocations")
def list_allocations(return_id):
    get_context()
    require_entity(store.tax_returns, return_id)
    rows = [a for a in store.refund_allocations.values()
            if a["tax_return_id"] == return_id]
    page = paginate(rows)
    return ok([allocation_json(a) for a in page], rtype="array",
              pagination=paginate)
