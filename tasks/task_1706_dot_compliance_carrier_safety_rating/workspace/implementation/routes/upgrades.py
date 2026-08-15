"""RatingUpgradeRequest endpoints (PRD 3.8): file, review, decide with rating cascade."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_COOLING_OFF_ACTIVE, ERR_OPEN_UPGRADE_REQUEST_EXISTS,
    ERR_RATING_NOT_UPGRADABLE, ERR_UPGRADE_INVALID_STATE,
)
from middleware import authorized
from response import success_object
from routes.helpers import public, list_response, get_one
from services import calc
from services.core import (
    stamp_new, touch, recompute_posture, sweep_quoted_premiums,
    OPEN_UPGRADE_STATES, _clock_plus_days,
)
from validate import (
    get_body, req_str, req_enum, require_path_resource, require_ref,
)
from util import new_id, parse_datetime, CLOCK, fmt_datetime

bp = Blueprint("upgrades", __name__)

REQUESTABLE_RATINGS = ["SATISFACTORY", "CONDITIONAL"]
UPGRADEABLE_CURRENT = ("CONDITIONAL", "UNSATISFACTORY")


@bp.post("/safety/rating-upgrade-requests")
def create_upgrade():
    authorized(["SafetyManager"])
    body = get_body()
    # Stage 3: shape
    carrier_id = req_str(body, "carrier_id")
    requested_rating = req_enum(body, "requested_rating", REQUESTABLE_RATINGS)
    justification_note = req_str(body, "justification_note")
    # Stage 4: existence
    carrier = require_ref("carriers", carrier_id, "carrier_id")
    # Stage 8: temporal — cooling-off gate
    cooling = carrier.get("rating_cooling_off_until")
    if cooling and CLOCK.now() < parse_datetime(cooling):
        raise_error(ERR_COOLING_OFF_ACTIVE, "carrier is in a rating cooling-off period")
    # Stage 9: one open request per carrier
    for r in db["rating_upgrade_requests"].values():
        if r["carrier_id"] == carrier_id and r["status"] in OPEN_UPGRADE_STATES:
            raise_error(ERR_OPEN_UPGRADE_REQUEST_EXISTS,
                        "an open upgrade request already exists for the carrier")
    # Stage 10: rating eligibility — current must be CONDITIONAL|UNSATISFACTORY and
    # the requested rating must rank strictly above the current one
    current = carrier["safety_rating"]
    if current not in UPGRADEABLE_CURRENT:
        raise_error(ERR_RATING_NOT_UPGRADABLE,
                    f"current rating {current} is not upgradable")
    if calc.RATING_BADNESS[requested_rating] >= calc.RATING_BADNESS[current]:
        raise_error(ERR_RATING_NOT_UPGRADABLE,
                    "requested_rating must rank strictly above the current rating")
    req = stamp_new({
        "id": new_id(),
        "carrier_id": carrier_id,
        "requested_rating": requested_rating,
        "justification_note": justification_note,
        "decided_at": None,
        "status": "SUBMITTED",
    })
    db["rating_upgrade_requests"][req["id"]] = req
    return success_object(public(req), 201)


@bp.get("/safety/rating-upgrade-requests")
def list_upgrades():
    return list_response("rating_upgrade_requests", filters={
        "carrier_id": request.args.get("carrier_id"),
        "status": request.args.get("status"),
    })


@bp.get("/safety/rating-upgrade-requests/<rid>")
def get_upgrade(rid):
    return get_one("rating_upgrade_requests", rid)


@bp.post("/safety/rating-upgrade-requests/<rid>/start-review")
def start_review(rid):
    authorized(["SafetyDirector"])
    req = require_path_resource("rating_upgrade_requests", rid)
    if req["status"] != "SUBMITTED":
        raise_error(ERR_UPGRADE_INVALID_STATE, "start-review requires SUBMITTED")
    req["status"] = "UNDER_REVIEW"
    touch(req)
    return success_object(public(req))


@bp.post("/safety/rating-upgrade-requests/<rid>/decide")
def decide(rid):
    authorized(["SafetyDirector"])
    body = get_body()
    outcome = req_enum(body, "outcome", ["APPROVED", "DENIED"])
    req = require_path_resource("rating_upgrade_requests", rid)
    if req["status"] != "UNDER_REVIEW":
        raise_error(ERR_UPGRADE_INVALID_STATE, "decide requires UNDER_REVIEW")
    carrier = db["carriers"].get(req["carrier_id"])
    req["decided_at"] = fmt_datetime(CLOCK.now())
    if outcome == "APPROVED":
        req["status"] = "APPROVED"
        carrier["safety_rating"] = req["requested_rating"]
        carrier["rating_cooling_off_until"] = None
        recompute_posture(carrier)
        touch(carrier)
        sweep_quoted_premiums(carrier["id"])
    else:  # DENIED
        req["status"] = "DENIED"
        carrier["rating_cooling_off_until"] = _clock_plus_days(90)
        touch(carrier)
    touch(req)
    return success_object(public(req))
