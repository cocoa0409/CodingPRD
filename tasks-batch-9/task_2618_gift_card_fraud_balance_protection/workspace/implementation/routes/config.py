"""Risk policy register and the logical clock (PRD 2.4, 2.5)."""
from flask import Blueprint

import clock
import db as dbm
import response
import validate
from db import POLICY_LIMITS
from errors import fail
from routes.common import READ_ROLES, authenticate
from services.holds import sweep_expired

bp = Blueprint("config", __name__)


@bp.get("/risk-policy")
def get_risk_policy():
    authenticate(READ_ROLES)
    return response.ok(dbm.policy())


@bp.put("/risk-policy")
def put_risk_policy():
    authenticate(["PlatformAdmin"])
    body = validate.body()
    policy = dbm.policy()
    supplied = {}
    for name, (minimum, maximum) in POLICY_LIMITS.items():
        if name not in body or body.get(name) is None:
            continue
        supplied[name] = validate.integer(
            body, name, required=True, minimum=minimum, maximum=maximum
        )
    if not supplied:
        dbm.touch(policy)
        return response.ok(policy)
    merged = dict(policy)
    merged.update(supplied)
    if merged["drain_restrict_score_threshold"] <= merged["drain_watch_score_threshold"]:
        fail("ERR_INVALID_REQUEST",
             "drain_restrict_score_threshold must exceed drain_watch_score_threshold.")
    if merged["digital_decline_score_threshold"] <= merged["digital_hold_score_threshold"]:
        fail("ERR_INVALID_REQUEST",
             "digital_decline_score_threshold must exceed digital_hold_score_threshold.")
    policy.update(supplied)
    dbm.touch(policy)
    return response.ok(policy)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(["PlatformAdmin"])
    body = validate.body()
    target = validate.datetime_field(body, "to_iso8601", required=True)
    previous = clock.now()
    clock.set_now(target)
    expired = 0
    if target >= previous:
        expired = sweep_expired()
    return response.ok({
        "current_utc": clock.fmt(clock.now()),
        "expired_hold_count": expired,
    })
