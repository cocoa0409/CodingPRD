"""Funding allocations: the per-source encumbrance rows of a funding plan."""
from flask import Blueprint

import serialize
import validate as v
from db import db, force_update
from errors import ApiError
from middleware import authenticate
from response import ok, ok_list
from services import effects, queries

bp = Blueprint("allocations", __name__)

ALLOCATION_STATUSES = ("PROPOSED", "COMMITTED", "RELEASED", "EXPENDED")

READ_ROLES = ["GradSchoolAdmin", "DepartmentAdmin", "GrantAccountant"]


@bp.get("/funding-allocations/<allocation_id>")
def read_allocation(allocation_id):
    authenticate(READ_ROLES)
    allocation = queries.allocation_or_404(allocation_id)
    return ok(serialize.allocation(allocation))


@bp.get("/funding-allocations")
def list_allocations():
    authenticate(READ_ROLES)
    appointment_id = v.query_str("appointment_id")
    funding_source_id = v.query_str("funding_source_id")
    status = v.query_enum("status", ALLOCATION_STATUSES)
    rows = list(db.funding_allocations.values())
    if appointment_id:
        rows = [r for r in rows if r["appointment_id"] == appointment_id]
    if funding_source_id:
        rows = [r for r in rows if r["funding_source_id"] == funding_source_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted(rows, key=lambda r: (r["plan_sequence"], r["created_at"], r["_seq"]))
    page, meta = v.paginate(rows)
    return ok_list([serialize.allocation(r) for r in page], meta)


@bp.post("/funding-allocations/<allocation_id>/release")
def release_allocation(allocation_id):
    authenticate(["GrantAccountant"])
    allocation = queries.allocation_or_404(allocation_id)
    body = v.body_dict()
    release_reason = v.field_str(body, "release_reason")

    if allocation["status"] != "COMMITTED":
        raise ApiError("ERR_INVALID_ALLOCATION_STATE",
                       "Only a COMMITTED allocation may be released, not %s"
                       % allocation["status"])
    if allocation["disbursed_amount_cents"] != 0:
        raise ApiError("ERR_ALLOCATION_PARTIALLY_DISBURSED",
                       "An allocation that has already disbursed money cannot be released")
    appointment = db.appointments.get(allocation["appointment_id"])
    if appointment is not None and appointment["lifecycle_status"] in ("APPROVED", "ACTIVE"):
        raise ApiError("ERR_ALLOCATION_LOCKED_BY_APPROVAL",
                       "The funding of an APPROVED or ACTIVE appointment is locked")

    effects.release_allocations([allocation], release_reason)

    if appointment is not None and appointment["lifecycle_status"] == "FUNDING_VERIFIED":
        force_update(appointment,
                     lifecycle_status="RETURNED",
                     return_reason="FUNDING_RELEASED")
    return ok(serialize.allocation(allocation))
