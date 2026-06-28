"""Endorsement endpoints (PRD §3.6). Request (REQUESTED) / get / list / transition
(ATTACH computes charge_cents and requires the parent policy ISSUED; REMOVE).
"""

from flask import Blueprint, request, g

import errors
from db import db, new_id, now_ts, next_seq
from middleware import require_roles
from response import success, list_success
from serializers import serialize_endorsement
from services.domain import touch, require_agency_owns_order
from services.calculations import endorsement_charge
from helpers import (
    get_body, require_enum, require_number,
    parse_pagination, paginate, sort_by_created,
)
from routes.policies import _get_policy_or_404

bp = Blueprint("endorsements", __name__)

FORM_CODES = {"ENV_PROTECTION", "ZONING", "SURVEY", "RESTRICTIONS"}
ENDORSEMENT_STATUSES = {"REQUESTED", "ATTACHED", "REMOVED"}


def _get_endorsement_or_404(eid):
    e = db.endorsements.get(eid)
    if e is None:
        raise errors.not_found("Endorsement not found")
    return e


def _agency_guard_for_policy(policy):
    if g.user_role == "Agency":
        order = db.orders.get(policy["order_id"])
        if order is not None:
            require_agency_owns_order(order)


@bp.route("/title/policies/<pid>/endorsements", methods=["POST"])
@require_roles("Underwriter")
def create_endorsement(pid):
    policy = _get_policy_or_404(pid)
    body = get_body()
    form_code = require_enum(body, "form_code", FORM_CODES)
    charge_pct = require_number(body, "charge_pct")
    # 0 < charge_pct <= 1 (scaffold constraint).
    if not (charge_pct > 0 and charge_pct <= 1):
        raise errors.invalid_request("charge_pct must be > 0 and <= 1")

    ts = now_ts()
    eid = new_id()
    record = {
        "id": eid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
        "policy_id": policy["id"],
        "form_code": form_code,
        "charge_pct": charge_pct,
        "charge_cents": 0,
        "status": "REQUESTED",
    }
    db.endorsements[eid] = record
    return success(serialize_endorsement(record), status=201)


@bp.route("/title/policies/<pid>/endorsements", methods=["GET"])
@require_roles("Underwriter", "TitleOfficer", "Agency")
def list_endorsements(pid):
    policy = _get_policy_or_404(pid)
    _agency_guard_for_policy(policy)
    limit, offset = parse_pagination()
    items = [e for e in db.endorsements.values() if e["policy_id"] == policy["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_endorsement(e) for e in page], limit, offset, total)


@bp.route("/title/endorsements/<eid>", methods=["GET"])
@require_roles("Underwriter", "TitleOfficer")
def get_endorsement(eid):
    e = _get_endorsement_or_404(eid)
    return success(serialize_endorsement(e), status=200)


@bp.route("/title/endorsements/<eid>/transitions", methods=["POST"])
@require_roles("Underwriter")
def transition_endorsement(eid):
    body = get_body()
    e = _get_endorsement_or_404(eid)
    to_status = require_enum(body, "to_status", ENDORSEMENT_STATUSES)
    cur = e["status"]

    if to_status == "ATTACHED":
        if cur != "REQUESTED":
            raise errors.invalid_state("Endorsement is not REQUESTED")
        # Cross-entity (priority 7): parent policy must be ISSUED.
        policy = db.policies.get(e["policy_id"])
        if policy is None or policy["status"] != "ISSUED":
            raise errors.ApiError(errors.ERR_POLICY_NOT_ISSUED, 409,
                                  "Parent policy is not ISSUED")
        # Compute charge_cents = round_half_up(gross_premium_cents * charge_pct).
        e["charge_cents"] = endorsement_charge(policy["gross_premium_cents"], e["charge_pct"])
        e["status"] = "ATTACHED"
        touch(e)
    elif to_status == "REMOVED":
        if cur != "ATTACHED":
            raise errors.invalid_state("Endorsement is not ATTACHED")
        e["status"] = "REMOVED"
        touch(e)
    else:
        raise errors.invalid_state("Unsupported endorsement transition")

    return success(serialize_endorsement(e), status=200)
