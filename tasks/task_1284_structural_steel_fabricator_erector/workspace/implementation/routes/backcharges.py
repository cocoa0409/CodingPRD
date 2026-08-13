"""Backcharge endpoints: respond / settle (fiscal cap) + reads."""

from flask import Blueprint

import domain
from envelope import ok_object
from errors import (
    ApiError,
    ERR_BACKCHARGE_EXCEEDS_EARNED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
)
from store import store, touch, public
from validate import authenticate, get_body, req_enum, req_int, require_role
from . import list_response

bp = Blueprint("backcharges", __name__)

ADMIN = {"FABRICATOR_ADMIN"}
GC_PM = {"GC_PM"}
READERS = {"FABRICATOR_ADMIN", "DETAILER", "EOR", "FOREMAN", "WELDER", "QC_INSPECTOR", "GC_PM"}


def view(b):
    return public(b)


def get_backcharge_or_404(bid):
    b = store.backcharges.get(bid)
    if b is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Backcharge not found.")
    return b


@bp.get("/backcharges")
def list_backcharges():
    uid, role = authenticate()
    require_role(role, READERS)
    return list_response(
        store.backcharges.values(),
        view,
        [("job_id", "job_id"), ("field_fix_id", "field_fix_id"), ("status", "status")],
    )


@bp.get("/backcharges/<bid>")
def get_backcharge(bid):
    uid, role = authenticate()
    require_role(role, READERS)
    return ok_object(view(get_backcharge_or_404(bid)))


@bp.post("/backcharges/<bid>/respond")
def respond_backcharge(bid):
    uid, role = authenticate()
    require_role(role, GC_PM)
    b = get_backcharge_or_404(bid)
    body = get_body()
    response = req_enum(body, "response", ("ACCEPT", "DISPUTE"))
    if b["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409, "Backcharge must be PENDING to respond.")
    b["status"] = "ACCEPTED" if response == "ACCEPT" else "DISPUTED"
    touch(b)
    return ok_object(view(b))


@bp.post("/backcharges/<bid>/settle")
def settle_backcharge(bid):
    uid, role = authenticate()
    require_role(role, ADMIN)
    b = get_backcharge_or_404(bid)
    body = get_body()
    settled_amount_cents = req_int(body, "settled_amount_cents")
    if settled_amount_cents < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "settled_amount_cents must be non-negative.")
    if b["status"] not in ("ACCEPTED", "DISPUTED"):
        raise ApiError(ERR_INVALID_STATE, 409, "Backcharge must be ACCEPTED or DISPUTED to settle.")
    # Rung 10: fiscal cap — the shop cannot settle out of unbilled money
    job = store.jobs.get(b["job_id"])
    settled_so_far = domain.settled_backcharge(b["job_id"])
    billed = domain.billed_to_date(b["job_id"])
    if settled_so_far + settled_amount_cents > billed:
        raise ApiError(
            ERR_BACKCHARGE_EXCEEDS_EARNED,
            409,
            "settled_backcharge_cents + settled_amount_cents would exceed billed_to_date_cents.",
        )
    b["settled_amount_cents"] = settled_amount_cents
    b["status"] = "SETTLED"
    touch(b)
    if job is not None:
        touch(job)  # pending/settled backcharge aggregates updated
        domain.compound_completion_check(job)
    return ok_object(view(b))
