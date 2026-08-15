"""HedgeRelationship and HedgeEffectivenessTest endpoints (PRD 3.6)."""

import store
from calc import effectiveness_result
from envelope import list_response, object_response
from errors import ApiError
from serializers import eff_test_json, hedge_json
from services import (
    hedge_coverage_floor_check,
    recompute_hedged_notional,
    stamp_event,
    stamp_new,
    touch,
)
from timeutil import clock, month_index
from validate import opt_int, opt_num, req_enum, req_int, req_month, req_str

from routes.common import READ_ROLES, endpoint, get_or_404

INSTRUMENTS = ("PAYER_SWAP", "RECEIVER_SWAP", "CAP", "FLOOR")
DESIGNATION_TYPES = ("FAIR_VALUE", "CASH_FLOW")
EFFECTIVENESS_METHODS = ("DOLLAR_OFFSET", "REGRESSION")


def _decrease_hedged_notional(book):
    """Shared side effect of dedesignate / terminate / FAIL: recompute the
    hedged total downward and run the coverage floor check. Hedge lifecycle
    events do not advance the book version (PRD 2.8)."""
    recompute_hedged_notional(book)
    hedge_coverage_floor_check(book)


@endpoint("POST", "/books/<book_id>/hedges", roles=["TreasuryAnalyst"])
def create_hedge(ctx):
    book = get_or_404(store.books, ctx.param("book_id"))
    body = ctx.body
    # Rung 4: body shape.
    position_id = req_str(body, "position_id")
    instrument = req_enum(body, "instrument", INSTRUMENTS)
    designation_type = req_enum(body, "designation_type", DESIGNATION_TYPES)
    notional = req_int(body, "notional_cents", min_v=1)
    fixed_rate = req_int(body, "fixed_rate_bps", min_v=0)
    # Body reference must exist and belong to the path book (nested scoping).
    position = store.positions.get(position_id)
    if position is None or position["book_id"] != book["id"]:
        raise ApiError("ERR_NOT_FOUND")
    hedge = {
        "book_id": book["id"],
        "position_id": position_id,
        "instrument": instrument,
        "designation_type": designation_type,
        "notional_cents": notional,
        "fixed_rate_bps": fixed_rate,
        "start_month": None,
        "end_month": None,
        "effectiveness_method": None,
        "status": "PROPOSED",
    }
    stamp_new(hedge)
    store.hedges[hedge["id"]] = hedge
    return object_response(hedge_json(hedge), 201)


@endpoint("GET", "/books/<book_id>/hedges", roles=READ_ROLES)
def list_book_hedges(ctx):
    book = get_or_404(store.books, ctx.param("book_id"))
    rows = [h for h in store.hedges.values() if h["book_id"] == book["id"]]
    status = ctx.args.get("status")
    if status is not None:
        rows = [h for h in rows if h["status"] == status]
    return list_response(rows, ctx.args, hedge_json)


@endpoint("GET", "/positions/<position_id>/hedges", roles=READ_ROLES)
def list_position_hedges(ctx):
    position = get_or_404(store.positions, ctx.param("position_id"))
    rows = [h for h in store.hedges.values() if h["position_id"] == position["id"]]
    return list_response(rows, ctx.args, hedge_json)


@endpoint("GET", "/hedges/<hedge_id>", roles=READ_ROLES)
def get_hedge(ctx):
    hedge = get_or_404(store.hedges, ctx.param("hedge_id"))
    return object_response(hedge_json(hedge))


@endpoint("POST", "/hedges/<hedge_id>/designate", roles=["ALCOChair"])
def designate_hedge(ctx):
    hedge = get_or_404(store.hedges, ctx.param("hedge_id"))
    body = ctx.body
    # Rung 4: window fields and the pinned effectiveness method; the window
    # must be non-empty (end_month after start_month).
    start_month = req_month(body, "start_month")
    end_month = req_month(body, "end_month")
    method = req_enum(body, "effectiveness_method", EFFECTIVENESS_METHODS)
    start_idx = month_index(start_month)
    end_idx = month_index(end_month)
    if end_idx <= start_idx:
        raise ApiError("ERR_INVALID_REQUEST")
    # Rung 6: only a PROPOSED hedge can be designated.
    if hedge["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    position = get_or_404(store.positions, hedge["position_id"])
    # Guards in the PRD 2.9 priority order (PRD 3.6 defers to it).
    # Rung 8: half-open [start, end) must not overlap another DESIGNATED/ACTIVE
    # hedge on the same position; adjacency is allowed.
    for other in store.hedges.values():
        if (
            other["id"] != hedge["id"]
            and other["position_id"] == hedge["position_id"]
            and other["status"] in ("DESIGNATED", "ACTIVE")
        ):
            o_start = month_index(other["start_month"])
            o_end = month_index(other["end_month"])
            if start_idx < o_end and o_start < end_idx:
                raise ApiError("ERR_HEDGE_WINDOW_OVERLAP")
    # Rung 9: start_month must not be before the current logical month.
    if start_idx < clock.current_month_index():
        raise ApiError("ERR_DESIGNATION_WINDOW_PAST")
    # Rung 10: notional must not exceed the hedged position's balance.
    if hedge["notional_cents"] > position["balance_cents"]:
        raise ApiError("ERR_HEDGE_NOTIONAL_EXCEEDS_EXPOSURE")
    # Rung 11: the hedged position must be ACTIVE.
    if position["status"] != "ACTIVE":
        raise ApiError("ERR_POSITION_RETIRED")
    hedge["start_month"] = start_month
    hedge["end_month"] = end_month
    hedge["effectiveness_method"] = method  # pinned, immutable thereafter
    hedge["status"] = "DESIGNATED"
    touch(hedge)
    # A DESIGNATED hedge now counts toward the book's hedged total (increase;
    # the coverage floor check never fires on increases).
    book = get_or_404(store.books, hedge["book_id"])
    recompute_hedged_notional(book)
    return object_response(hedge_json(hedge))


@endpoint("POST", "/hedges/<hedge_id>/activate", roles=["ALCOChair"])
def activate_hedge(ctx):
    hedge = get_or_404(store.hedges, ctx.param("hedge_id"))
    # Rung 6: DESIGNATED -> ACTIVE.
    if hedge["status"] != "DESIGNATED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    # Rung 9: the logical clock must have reached start_month.
    if clock.current_month_index() < month_index(hedge["start_month"]):
        raise ApiError("ERR_HEDGE_NOT_ACTIVATABLE")
    hedge["status"] = "ACTIVE"
    touch(hedge)
    return object_response(hedge_json(hedge))


@endpoint("POST", "/hedges/<hedge_id>/dedesignate", roles=["ALCOChair"])
def dedesignate_hedge(ctx):
    hedge = get_or_404(store.hedges, ctx.param("hedge_id"))
    req_str(ctx.body, "reason")  # rung 4: accompanied by a reason
    # Rung 6: allowed from DESIGNATED or ACTIVE.
    if hedge["status"] not in ("DESIGNATED", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    hedge["status"] = "DEDESIGNATED"
    touch(hedge)
    book = get_or_404(store.books, hedge["book_id"])
    _decrease_hedged_notional(book)
    return object_response(hedge_json(hedge))


@endpoint("POST", "/hedges/<hedge_id>/terminate", roles=["ALCOChair"])
def terminate_hedge(ctx):
    hedge = get_or_404(store.hedges, ctx.param("hedge_id"))
    req_str(ctx.body, "reason")  # rung 4: accompanied by a reason
    # Rung 6: allowed from ACTIVE only.
    if hedge["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    hedge["status"] = "TERMINATED"
    touch(hedge)
    book = get_or_404(store.books, hedge["book_id"])
    _decrease_hedged_notional(book)
    return object_response(hedge_json(hedge))


@endpoint("POST", "/hedges/<hedge_id>/effectiveness-tests", roles=["ModelRiskValidator"])
def create_effectiveness_test(ctx):
    hedge = get_or_404(store.hedges, ctx.param("hedge_id"))
    body = ctx.body
    # Rung 4: body shape. Regression inputs are optional; r_squared is 0..1.
    test_month = req_month(body, "test_month")
    hedge_change = req_int(body, "hedge_value_change_cents")
    hedged_change = req_int(body, "hedged_item_value_change_cents")
    slope = opt_num(body, "slope", default=None)
    r_squared = opt_num(body, "r_squared", min_v=0, max_v=1, default=None)
    sample_count = opt_int(body, "sample_count", min_v=0, default=None)
    # Rung 6: a test is recorded against an ACTIVE hedge.
    if hedge["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    # The method snapshots the hedge's pinned effectiveness_method.
    method = hedge["effectiveness_method"]
    result, offset_ratio = effectiveness_result(
        method, hedge_change, hedged_change, slope, r_squared, sample_count
    )
    test = {
        "hedge_id": hedge["id"],
        "test_month": test_month,
        "method": method,
        "hedge_value_change_cents": hedge_change,
        "hedged_item_value_change_cents": hedged_change,
        "slope": slope,
        "r_squared": r_squared,
        "sample_count": sample_count,
        "offset_ratio": offset_ratio,
        "result": result,
    }
    stamp_event(test)  # append-only: id + created_at only
    store.eff_tests[test["id"]] = test
    if result == "FAIL":
        # FAIL drives the hedge ACTIVE -> DEDESIGNATED, recomputes the hedged
        # total downward, and runs the coverage floor check.
        hedge["status"] = "DEDESIGNATED"
        touch(hedge)
        book = get_or_404(store.books, hedge["book_id"])
        _decrease_hedged_notional(book)
    return object_response(eff_test_json(test), 201)


@endpoint("GET", "/hedges/<hedge_id>/effectiveness-tests", roles=READ_ROLES)
def list_effectiveness_tests(ctx):
    hedge = get_or_404(store.hedges, ctx.param("hedge_id"))
    rows = [t for t in store.eff_tests.values() if t["hedge_id"] == hedge["id"]]
    return list_response(rows, ctx.args, eff_test_json)
