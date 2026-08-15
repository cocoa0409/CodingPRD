"""StrikeReport endpoints: per-run listing and adjudication."""
from flask import Blueprint, request

from db import DB
from errors import ApiError
from middleware import auth
from response import ok
from services import (
    DONOR_STRIKE_LIMIT,
    STRIKE_PENALTY,
    SUSPEND_THRESHOLD,
    clock_iso,
    get_run,
    get_strike,
    ser_strike,
    suspend_donor_cascade,
    suspend_driver_cascade,
    touch,
)
from util import as_enum, body, paginate, reject_unknown, required

bp = Blueprint("strikes", __name__)


@bp.get("/api/rescue-runs/<rid>/strike-reports")
def list_run_strikes(rid):
    auth(["DispatchAdmin"])
    run = get_run(rid)
    items = [s for s in DB["strikes"].values() if s["rescue_run_id"] == run["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return paginate(items, ser_strike)


@bp.post("/api/strike-reports/<sid>/adjudicate")
def adjudicate(sid):
    user_id, role = auth(["DispatchAdmin"])
    data = body()
    reject_unknown(data, {"outcome"})
    outcome = as_enum(required(data, "outcome"), "outcome", ("UPHELD", "WAIVED"))
    strike = get_strike(sid)
    if strike["status"] != "FILED":
        raise ApiError(
            "ERR_STRIKE_NOT_FILED", 409, "Adjudicate requires a FILED strike report"
        )
    # Segregation of duties: a reporter may not judge their own accusation.
    if strike["reporter_role"] != "SYSTEM" and strike["reporter_user_id"] == user_id:
        raise ApiError(
            "ERR_SELF_ADJUDICATION_FORBIDDEN", 403,
            "The adjudicator must differ from the reporter",
        )
    strike["status"] = outcome
    strike["adjudicated_by_user_id"] = user_id
    strike["adjudicated_at"] = clock_iso()
    touch(strike)
    if outcome == "UPHELD":
        if strike["subject_type"] == "DONOR_SITE":
            donor = DB["donor_sites"].get(strike["subject_id"])
            if donor is not None:
                donor["strike_count"] += 1
                if (
                    donor["strike_count"] >= DONOR_STRIKE_LIMIT
                    and donor["status"] == "ACTIVE"
                ):
                    suspend_donor_cascade(donor)  # touches the donor
                else:
                    touch(donor)
        else:
            driver = DB["drivers"].get(strike["subject_id"])
            if driver is not None:
                driver["reliability_score"] = max(
                    0, driver["reliability_score"] - STRIKE_PENALTY
                )
                if (
                    driver["reliability_score"] < SUSPEND_THRESHOLD
                    and driver["status"] == "ACTIVE"
                ):
                    suspend_driver_cascade(driver)  # touches the driver
                else:
                    touch(driver)
    return ok(ser_strike(strike))
