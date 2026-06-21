"""MatchException endpoints: resolve / write-off / escalate (PRD §3.4)."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    APIError, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_WRITEOFF_LIMIT_EXCEEDED, ERR_ESCALATE_BELOW_CEILING,
)
from middleware import auth_required, ALL_ROLES, current_user_id
from response import ok_object
from routes._helpers import serialize
from services.calculations import WRITEOFF_CEILING_CENTS
from services.common import touch
from services.audit import append_audit

bp = Blueprint("match_exceptions", __name__)


def _require_exception(eid):
    me = db.match_exceptions.get(eid)
    if me is None:
        raise APIError(ERR_NOT_FOUND, 404, "Match exception not found")
    return me


def _invoice_in_coding_review(me):
    """All three resolutions require the exception PENDING and the invoice still
    in CODING_REVIEW (state precondition)."""
    inv = db.invoices.get(me["invoice_id"])
    if me["resolution"] != "PENDING":
        raise APIError(ERR_INVALID_STATE, 409, "Match exception is not PENDING")
    if inv is None or inv["status"] != "CODING_REVIEW":
        raise APIError(ERR_INVALID_STATE, 409, "Invoice is not in CODING_REVIEW state")
    return inv


@bp.get("/ap/match-exceptions/<eid>")
def get_exception(eid):
    auth_required(ALL_ROLES)()
    me = _require_exception(eid)
    return ok_object(serialize(me))


@bp.post("/ap/match-exceptions/<eid>/resolve")
def resolve_exception(eid):
    auth_required({"APClerk"})()
    me = _require_exception(eid)
    _invoice_in_coding_review(me)
    me["resolution"] = "RESOLVED"
    me["resolved_by"] = current_user_id()
    touch(me)
    append_audit(me["invoice_id"], "EXCEPTION_RESOLVED", current_user_id())
    return ok_object(serialize(me))


@bp.post("/ap/match-exceptions/<eid>/write-off")
def write_off_exception(eid):
    auth_required({"APClerk"})()
    me = _require_exception(eid)
    inv = _invoice_in_coding_review(me)
    # business: write-off only when variance_cents <= ceiling (422).
    if me["variance_cents"] > WRITEOFF_CEILING_CENTS:
        raise APIError(ERR_WRITEOFF_LIMIT_EXCEEDED, 422,
                       "Variance exceeds the write-off ceiling")
    me["resolution"] = "WRITTEN_OFF"
    me["resolved_by"] = current_user_id()
    touch(me)
    # Write-off absorbs the variance: zero the linked invoice variance.
    if inv["variance_cents"] != 0:
        inv["variance_cents"] = 0
        touch(inv)
    append_audit(me["invoice_id"], "EXCEPTION_WRITTEN_OFF", current_user_id())
    return ok_object(serialize(me))


@bp.post("/ap/match-exceptions/<eid>/escalate")
def escalate_exception(eid):
    auth_required({"APClerk"})()
    me = _require_exception(eid)
    _invoice_in_coding_review(me)
    # business: escalate only when variance_cents > ceiling (422).
    if me["variance_cents"] <= WRITEOFF_CEILING_CENTS:
        raise APIError(ERR_ESCALATE_BELOW_CEILING, 422,
                       "Variance at or below the ceiling must be written off, not escalated")
    me["resolution"] = "ESCALATED"
    me["resolved_by"] = current_user_id()
    touch(me)
    append_audit(me["invoice_id"], "EXCEPTION_ESCALATED", current_user_id())
    return ok_object(serialize(me))
