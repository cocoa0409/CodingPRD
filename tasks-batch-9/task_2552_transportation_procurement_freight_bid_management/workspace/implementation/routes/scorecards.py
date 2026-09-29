"""Scorecard publication and dispute — PRD §3.2."""
from flask import Blueprint

import auth
import helpers
import responses
import store
import validators as v
from errors import ApiError
from services import scoring

bp = Blueprint("scorecards", __name__)


@bp.post("/freight-procurement/scorecards/<scorecard_id>/publish")
@auth.roles_required("CategoryManager")
def publish(scorecard_id):
    scorecard = helpers.get_scorecard(scorecard_id)
    v.body()

    if scorecard["status"] in ("PUBLISHED", "DISPUTED"):
        raise ApiError("ERR_SCORECARD_ALREADY_PUBLISHED")
    if store.parse_dt(scorecard["period_end"]) > store.now():
        raise ApiError("ERR_SCORECARD_ALREADY_PUBLISHED",
                       "An unfinished measurement period cannot be published.")

    # Publication re-evaluates the period score from current data before recording it.
    scoring.scorecard_period_metrics(scorecard)
    scorecard["status"] = "PUBLISHED"
    scorecard["published_at"] = store.now_iso()
    store.touch(scorecard)

    carrier = store.carriers.get(scorecard["carrier_id"])
    if carrier is not None:
        scoring.recompute_composite(carrier)
        scoring.reevaluate_standing(carrier)
        store.touch(carrier)
    return responses.ok(scorecard)


@bp.post("/freight-procurement/scorecards/<scorecard_id>/dispute")
@auth.roles_required("CarrierRep")
def dispute(scorecard_id):
    scorecard = helpers.get_scorecard(scorecard_id)
    payload = v.body()
    reason = v.string_field(payload, "disputed_reason", min_len=1)

    auth.own_carrier_or_raise(scorecard["carrier_id"])
    if scorecard["status"] != "PUBLISHED":
        raise ApiError("ERR_SCORECARD_NOT_PUBLISHED")

    scorecard["status"] = "DISPUTED"
    scorecard["disputed_reason"] = reason
    store.touch(scorecard)
    return responses.ok(scorecard)
