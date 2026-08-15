"""Bid entry endpoints: submission (version-guarded) and withdrawal."""
from flask import Blueprint

from db import db, mint, touch, ser
from errors import (
    ApiError,
    forbidden,
    invalid_state,
    validation,
    ERR_DUPLICATE_PREFERENCE,
    ERR_RUN_NOT_BIDDABLE,
    ERR_STALE_VERSION,
)
from helpers import (
    body_json,
    req_int,
    get_period_or_404,
    get_bid_or_404,
    ref_operator_or_404,
    ref_run_or_404,
    is_int,
    req_field,
)
from middleware import authenticate, require_roles
from response import ok_obj

bp = Blueprint("bids", __name__)


@bp.post("/api/sign-up-periods/<pid>/bid-entries")
def submit_bid(pid):
    auth = authenticate()
    require_roles(auth, ["Operator"])
    period = get_period_or_404(pid)
    body = body_json()
    operator_id = req_field(body, "operator_id")
    run_id = req_field(body, "run_id")
    preference_rank = req_int(body, "preference_rank", 1)
    expected_version = req_field(body, "expected_sign_up_period_version")
    if not isinstance(operator_id, str) or not isinstance(run_id, str):
        raise validation("operator_id and run_id must be strings")
    if not is_int(expected_version):
        raise validation("expected_sign_up_period_version must be an integer")

    # Ownership: an Operator caller submits only their own bids
    if operator_id != auth["user_id"]:
        raise forbidden("Operators may submit bids only for themselves")

    # Body FK existence
    ref_operator_or_404(operator_id)
    run = ref_run_or_404(run_id)

    # State: submission accepted only while the period is OPEN or PICKING
    if period["status"] not in ("OPEN", "PICKING"):
        raise invalid_state("Bids are accepted only while the period is OPEN or PICKING")

    # Business rules in PRD order:
    # 1. preference_rank unique per (period, operator) among SUBMITTED bids
    for b in db.bid_entries.values():
        if (
            b["sign_up_period_id"] == pid
            and b["operator_id"] == operator_id
            and b["status"] == "SUBMITTED"
            and b["preference_rank"] == preference_rank
        ):
            raise ApiError(
                ERR_DUPLICATE_PREFERENCE,
                "operator already holds a SUBMITTED bid with this preference_rank",
                409,
            )
    # 2. run must belong to this sign-up period and be biddable
    if run["sign_up_period_id"] != pid or run["status"] != "POSTED":
        raise ApiError(
            ERR_RUN_NOT_BIDDABLE,
            "run_id does not belong to this sign-up period or is not biddable",
            422,
        )
    # 3. optimistic concurrency: stale-version check closes the ladder
    if expected_version != period["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_sign_up_period_version does not match the period's current version",
            412,
        )

    bid = mint()
    bid.update(
        {
            "sign_up_period_id": pid,
            "operator_id": operator_id,
            "run_id": run_id,
            "preference_rank": preference_rank,
            "status": "SUBMITTED",
        }
    )
    db.bid_entries[bid["id"]] = bid
    touch(period)  # every accepted submission advances the period version
    return ok_obj(ser(bid), 201)


@bp.post("/api/bid-entries/<bid>/withdraw")
def withdraw_bid(bid):
    auth = authenticate()
    require_roles(auth, ["Operator"])
    entry = get_bid_or_404(bid)
    if entry["operator_id"] != auth["user_id"]:
        raise forbidden("Operators may withdraw only their own bid entries")
    period = db.sign_up_periods.get(entry["sign_up_period_id"])
    if (
        period is None
        or period["status"] not in ("OPEN", "PICKING")
        or entry["status"] != "SUBMITTED"
    ):
        raise invalid_state(
            "Only a SUBMITTED bid may be withdrawn while the period is OPEN or PICKING"
        )
    entry["status"] = "WITHDRAWN"
    touch(entry)
    return ok_obj(ser(entry))
