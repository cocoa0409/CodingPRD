"""Agency endpoints (PRD §3.1). Register / get / suspend-reactivate.

Underwriter registers and transitions agencies. Reads are open to Underwriter and
Agency (an Agency may read its own record; the GET-by-id ownership constraint in
§2.1 applies only to order-reachable resources, and an Agency reading an arbitrary
agency by id is not order-scoped — but the agency record IS the agency, so when an
Agency role reads, it must be reading its own id).
"""

from flask import Blueprint, g

import errors
from db import db, new_id, now_ts, next_seq
from middleware import require_roles
from response import success
from serializers import serialize_agency
from services.domain import touch
from helpers import get_body, require_str, require_number, require_enum

bp = Blueprint("agencies", __name__)

AGENCY_STATUSES = {"ACTIVE", "SUSPENDED"}


@bp.route("/title/agencies", methods=["POST"])
@require_roles("Underwriter")
def create_agency():
    body = get_body()
    name = require_str(body, "name")
    remit_split_pct = require_number(body, "remit_split_pct")
    # 0 <= remit_split_pct <= 1 (scaffold constraint).
    if remit_split_pct < 0 or remit_split_pct > 1:
        raise errors.invalid_request("remit_split_pct must be between 0 and 1 inclusive")
    ts = now_ts()
    aid = new_id()
    record = {
        "id": aid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "name": name,
        "remit_split_pct": remit_split_pct,
        "status": "ACTIVE",
    }
    db.agencies[aid] = record
    return success(serialize_agency(record), status=201)


@bp.route("/title/agencies/<aid>", methods=["GET"])
@require_roles("Underwriter", "Agency")
def get_agency(aid):
    record = db.agencies.get(aid)
    if record is None:
        raise errors.not_found("Agency not found")
    # An Agency principal may only read its own agency record (entity-backed).
    if g.user_role == "Agency" and record["id"] != g.user_id:
        raise errors.unauthorized("Agency may only read its own record")
    return success(serialize_agency(record), status=200)


@bp.route("/title/agencies/<aid>/transitions", methods=["POST"])
@require_roles("Underwriter")
def transition_agency(aid):
    body = get_body()
    record = db.agencies.get(aid)
    if record is None:
        raise errors.not_found("Agency not found")
    to_status = require_enum(body, "to_status", AGENCY_STATUSES)
    # ACTIVE <-> SUSPENDED, both directions permitted, no precondition.
    if to_status == record["status"]:
        raise errors.invalid_state("Agency is already in status " + to_status)
    record["status"] = to_status
    touch(record)
    return success(serialize_agency(record), status=200)
