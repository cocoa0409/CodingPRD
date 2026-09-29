"""Performance scorecards: reads and republication (PRD 3.7)."""

from flask import Blueprint

import derive
import enums
import lookup
from auth import ROLE_CPA_ADMINISTRATOR, any_role, require
from db import public, store, touch
from response import object_response
from routes.common import collection_listing, guard_state

bp = Blueprint("scorecards", __name__)

LIST_FILTERS = (
    ("cycle_id", "cycle_id", None),
    ("status", "status", enums.SCORECARD_STATUS),
)


@bp.route("/scorecards", methods=["GET"])
@any_role()
def list_scorecards():
    return collection_listing("scorecards", LIST_FILTERS)


@bp.route("/scorecards/<scorecard_id>", methods=["GET"])
@any_role()
def read_scorecard(scorecard_id):
    return object_response(public(lookup.scorecard(scorecard_id)))


@bp.route("/scorecards/<scorecard_id>/recompute", methods=["POST"])
@require(ROLE_CPA_ADMINISTRATOR)
def recompute_scorecard(scorecard_id):
    card = lookup.scorecard(scorecard_id)

    # A scorecard has no terminal state; PUBLISHED and STALE both admit recompute.
    guard_state(card["status"] in ("PUBLISHED", "STALE"))

    cycle = store.schedule_cycles[card["cycle_id"]]
    card.update(derive.scorecard_figures(cycle))
    card["status"] = "PUBLISHED"
    card["recompute_count"] += 1
    touch(card)

    return object_response(public(card))
