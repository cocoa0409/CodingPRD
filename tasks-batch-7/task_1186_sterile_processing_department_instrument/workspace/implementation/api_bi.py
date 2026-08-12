"""Biological indicators: list/get and record-result with load cascades."""
from flask import Blueprint

import domain
import store
import views
from common import (
    ANY, ApiError, auth, get_body, logical_now, ok, ok_list, paginate,
    pagination, query_str, req_enum,
)

bp = Blueprint("biological_indicators", __name__)

BI_RESULTS = ("NEGATIVE", "POSITIVE")


@bp.get("/spd/biological-indicators")
def list_biological_indicators():
    auth(ANY)
    limit, offset = pagination()
    load_id = query_str("load_id")
    result = query_str("result")
    rows = [r for r in store.BIOLOGICAL_INDICATORS.values()
            if (load_id is None or r["load_id"] == load_id)
            and (result is None or r["result"] == result)]
    page, total = paginate(store.ordered(rows), limit, offset)
    return ok_list([views.bi_view(r) for r in page], limit, offset, total)


@bp.get("/spd/biological-indicators/<bi_id>")
def get_biological_indicator(bi_id):
    auth(ANY)
    record = store.fetch(store.BIOLOGICAL_INDICATORS, bi_id)
    return ok(views.bi_view(record))


@bp.post("/spd/biological-indicators/<bi_id>/record-result")
def record_biological_indicator_result(bi_id):
    auth(("QualityAuditor",))
    bi = store.fetch(store.BIOLOGICAL_INDICATORS, bi_id)
    body = get_body()
    result = req_enum(body, "result", BI_RESULTS)

    # p6 state gate
    if bi["status"] != "INCUBATING":
        raise ApiError("ERR_BI_ALREADY_RECORDED", 409,
                       "The BI result has already been recorded.")
    # p8 temporal gate: exactly at due_at is accepted
    if logical_now() < bi["due_at"]:
        raise ApiError("ERR_BI_STILL_INCUBATING", 409,
                       "The BI is still incubating.")

    bi["result"] = result
    bi["recorded_at"] = logical_now()
    bi["status"] = "RESULT_RECORDED"
    store.touch(bi)

    if result == "POSITIVE":
        load = store.STERILIZATION_LOADS.get(bi["load_id"])
        if load is not None and load["status"] == "COMPLETED":
            load["status"] = "FAILED_BI"
            store.touch(load)
            domain.release_member_trays(load, "DECONTAMINATED")
        elif load is not None and load["status"] == "RELEASED":
            domain.recall_load(load, "BI_POSITIVE")

    return ok(views.bi_view(bi))
