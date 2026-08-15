"""BacktestReview endpoints (PRD 3.7): observation window rules, deviation
verdict, governance flag, and closure."""

import store
from calc import PREDICTED_PARAM_KEY, backtest_outcome
from envelope import list_response, object_response
from errors import ApiError
from serializers import backtest_json
from services import stamp_new, touch
from timeutil import clock, month_index
from validate import req_enum, req_int, req_month, req_str

from routes.common import READ_ROLES, endpoint, get_or_404

CLOSE_OUTCOMES = ("CLOSED_ACCEPTED", "CLOSED_REVISED")


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


@endpoint("POST", "/books/<book_id>/backtests", roles=["ModelRiskValidator"])
def create_backtest(ctx):
    book = get_or_404(store.books, ctx.param("book_id"))
    body = ctx.body
    # Rung 4: required fields, ranges; observed_value_pct has its own error.
    assumption_set_id = req_str(body, "assumption_set_id")
    start_month = req_month(body, "start_month")
    observation_months = req_int(body, "observation_months", min_v=1)
    if "observed_value_pct" not in body or not _is_number(body["observed_value_pct"]):
        raise ApiError("ERR_INVALID_REQUEST")
    observed = body["observed_value_pct"]
    from decimal import Decimal as _D
    if _D(str(observed)) < 0 or _D(str(observed)) > 100:
        raise ApiError("ERR_OBSERVED_VALUE_INVALID")
    # Body reference must exist and belong to the path book (nested scoping).
    aset = store.assumption_sets.get(assumption_set_id)
    if aset is None or aset["book_id"] != book["id"]:
        raise ApiError("ERR_NOT_FOUND")
    start_idx = month_index(start_month)
    end_idx = start_idx + observation_months  # half-open [start, start + months)
    # Rung 8: the window must neither overlap nor abut an existing review
    # window on the same assumption set - a gap of >= 1 month is required.
    for other in store.backtests.values():
        if other["assumption_set_id"] != aset["id"] or other["id"] == body.get("id"):
            continue
        o_start = month_index(other["start_month"])
        o_end = o_start + other["observation_months"]
        if not (end_idx + 1 <= o_start or o_end + 1 <= start_idx):
            raise ApiError("ERR_BACKTEST_WINDOW_OVERLAP")
    # Rung 9: the observation window must be fully elapsed relative to the
    # logical clock (calendar month index comparison).
    if clock.current_month_index() < end_idx:
        raise ApiError("ERR_BACKTEST_WINDOW_NOT_ELAPSED")
    # The verdict: predicted value per domain, deviation, tolerance outcome.
    predicted_key = PREDICTED_PARAM_KEY[aset["domain"]]
    params = aset["params"] if isinstance(aset["params"], dict) else {}
    predicted = params.get(predicted_key)
    if not _is_number(predicted):
        raise ApiError("ERR_ASSUMPTION_PARAMS_MISMATCH")
    deviation, outcome = backtest_outcome(aset["domain"], predicted, observed)
    review = {
        "book_id": book["id"],
        "assumption_set_id": aset["id"],
        "domain": aset["domain"],  # snapshot of the set's domain
        "start_month": start_month,
        "observation_months": observation_months,
        "observed_value_pct": observed,
        "predicted_value_pct": predicted,
        "deviation_pct": float(deviation),
        "outcome": outcome,
        "status": "OPEN",
    }
    stamp_new(review)
    store.backtests[review["id"]] = review
    if outcome == "BREACH":
        # BREACH raises the governance flag on the reviewed set.
        aset["governance_flag"] = "REVIEW_REQUIRED"
        touch(aset)
    return object_response(backtest_json(review), 201)


@endpoint("GET", "/backtests", roles=READ_ROLES)
def list_backtests(ctx):
    rows = list(store.backtests.values())
    book_id = ctx.args.get("book_id")
    if book_id is not None:
        rows = [r for r in rows if r["book_id"] == book_id]
    assumption_set_id = ctx.args.get("assumption_set_id")
    if assumption_set_id is not None:
        rows = [r for r in rows if r["assumption_set_id"] == assumption_set_id]
    return list_response(rows, ctx.args, backtest_json)


@endpoint("GET", "/backtests/<review_id>", roles=READ_ROLES)
def get_backtest(ctx):
    review = get_or_404(store.backtests, ctx.param("review_id"))
    return object_response(backtest_json(review))


@endpoint("POST", "/backtests/<review_id>/close", roles=["ALCOChair"])
def close_backtest(ctx):
    review = get_or_404(store.backtests, ctx.param("review_id"))
    outcome = req_enum(ctx.body, "outcome", CLOSE_OUTCOMES)  # rung 4
    # Rung 6: only an OPEN review can close.
    if review["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    reviewed_set = get_or_404(store.assumption_sets, review["assumption_set_id"])
    if outcome == "CLOSED_REVISED":
        # Rung 11: another set in the same (book, domain) must be APPROVED with
        # a strictly later created_at than the reviewed set.
        newer_approved = any(
            other["id"] != reviewed_set["id"]
            and other["book_id"] == review["book_id"]
            and other["domain"] == review["domain"]
            and other["status"] == "APPROVED"
            and other["_created_dt"] > reviewed_set["_created_dt"]
            for other in store.assumption_sets.values()
        )
        if not newer_approved:
            raise ApiError("ERR_BACKTEST_CLOSURE_REQUIRES_REVISION")
    review["status"] = outcome
    touch(review)
    # When no other OPEN review references the same set, the governance flag
    # returns to NONE.
    still_open = any(
        other["id"] != review["id"]
        and other["assumption_set_id"] == review["assumption_set_id"]
        and other["status"] == "OPEN"
        for other in store.backtests.values()
    )
    if not still_open and reviewed_set["governance_flag"] != "NONE":
        reviewed_set["governance_flag"] = "NONE"
        touch(reviewed_set)
    return object_response(backtest_json(review))
