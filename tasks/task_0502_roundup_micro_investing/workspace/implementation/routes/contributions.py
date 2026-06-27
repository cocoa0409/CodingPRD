"""RecurringContribution routes (PRD §3.9)."""

import datetime

from flask import Blueprint, request

from db import store
from errors import err
from middleware import get_json, require_auth, require_owner
from models import new_entity, serialize, touch
from response import format_ts, success
from routes.helpers import (
    fetch_or_404,
    list_response,
    require_enum,
    require_int,
    require_str,
)

bp = Blueprint("contributions", __name__)

_CADENCE_DELTA = {
    "DAILY": datetime.timedelta(days=1),
    "WEEKLY": datetime.timedelta(weeks=1),
    "MONTHLY": datetime.timedelta(days=30),
}


@bp.route("/recurring-contributions", methods=["POST"])
def create_contribution():
    role, user_id = require_auth({"Investor"})
    body = get_json()
    account_id = require_str(body, "account_id")
    amount_cents = require_int(body, "amount_cents", minimum=100)
    cadence = require_enum(body, "cadence", {"DAILY", "WEEKLY", "MONTHLY"})
    run_day_index = require_int(body, "run_day_index", minimum=0)

    account = fetch_or_404(store.accounts, account_id)
    require_owner(role, user_id, account["id"])

    # Day collision: new run_day_index must not fall within +/-1 inclusive buffer
    # of any existing ACTIVE contribution on the same account (PRD §3.9).
    for rc in store.recurring_contributions.values():
        if rc["account_id"] == account_id and rc["status"] == "ACTIVE":
            d = rc["run_day_index"]
            if (d - 1) <= run_day_index <= (d + 1):
                raise err(
                    "ERR_CONTRIBUTION_DAY_COLLISION",
                    "run_day_index collides with an existing active contribution.",
                )

    next_run = store.now() + _CADENCE_DELTA[cadence]

    contribution = new_entity(
        {
            "account_id": account_id,
            "amount_cents": amount_cents,
            "cadence": cadence,
            "run_day_index": run_day_index,
            "next_run_at": format_ts(next_run),
            "runs_completed": 0,
            "status": "ACTIVE",
        }
    )
    store.recurring_contributions[contribution["id"]] = contribution
    return success(serialize(contribution), status=201)


@bp.route("/recurring-contributions/<entity_id>", methods=["GET"])
def get_contribution(entity_id):
    role, user_id = require_auth({"PlatformAdmin", "Investor"})
    rc = fetch_or_404(store.recurring_contributions, entity_id)
    require_owner(role, user_id, rc["account_id"])
    return success(serialize(rc))


@bp.route("/recurring-contributions", methods=["GET"])
def list_contributions():
    role, user_id = require_auth({"PlatformAdmin", "Investor"})
    items = list(store.recurring_contributions.values())
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    if account_id is not None:
        items = [c for c in items if c["account_id"] == account_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if role == "Investor":
        items = [c for c in items if c["account_id"] == user_id]
    data, pagination = list_response(items)
    return success(data, pagination=pagination)


@bp.route("/recurring-contributions/<entity_id>/cancel", methods=["POST"])
def cancel_contribution(entity_id):
    role, user_id = require_auth({"Investor"})
    rc = fetch_or_404(store.recurring_contributions, entity_id)
    require_owner(role, user_id, rc["account_id"])
    if rc["status"] not in ("ACTIVE", "PAUSED"):
        raise err("ERR_INVALID_STATE", "Only an ACTIVE or PAUSED contribution can be cancelled.")
    rc["status"] = "CANCELLED"
    touch(rc)
    return success(serialize(rc))
