from datetime import timedelta

from flask import Blueprint

import store
from errors import ApiError
import context as ctx
import domain
from serializers import public, public_list
import envelope as env

bp = Blueprint("closings", __name__)


@bp.post("/awards/<wid>/closings")
def schedule_closing(wid):
    ctx.authenticate(["ClosingCoordinator"])
    award = ctx.lookup("award", wid)
    data = ctx.body()
    property_id = data.get("property_id")
    if property_id is not None:
        ctx.lookup("property", property_id)
    property_id = ctx.req_str(data, "property_id")
    scheduled_raw, scheduled_dt = ctx.req_datetime(data, "scheduled_date")
    window_days = ctx.opt_int(data, "window_days", 7, 1)
    window_end = scheduled_dt + timedelta(days=window_days)

    # Priority 15: closing-window conflict on the same property (half-open windows).
    for other in store.closings.values():
        if other["property_id"] != property_id or other["status"] == "CANCELLED":
            continue
        if scheduled_dt < other["_window_end_dt"] and other["_scheduled_dt"] < window_end:
            raise ApiError("ERR_CLOSING_WINDOW_CONFLICT",
                           "Overlapping occupation window on this property.")

    rec = store.new_record("closing")
    rec.update({
        "award_id": wid,
        "property_id": property_id,
        "scheduled_date": scheduled_raw,
        "window_days": window_days,
        "final_purchase_price_cents": None,
        "final_first_mortgage_cents": None,
        "status": "SCHEDULED",
        "_scheduled_dt": scheduled_dt,
        "_window_end_dt": window_end,
    })
    store.closings[rec["id"]] = rec
    return env.success(public(rec), 201)


@bp.get("/closings/<cid>")
def get_closing(cid):
    ctx.authenticate(["ClosingCoordinator", "CaseManager", "ProgramAdmin"])
    rec = ctx.lookup("closing", cid)
    return env.success(public(rec), 200)


@bp.get("/closings")
def list_closings():
    ctx.authenticate(["ClosingCoordinator", "CaseManager", "ProgramAdmin"])
    limit, offset = ctx.pagination_params()
    filters = {
        "award_id": ctx.query_filter("award_id"),
        "property_id": ctx.query_filter("property_id"),
        "status": ctx.query_filter("status"),
    }
    page, total = ctx.paginate(store.closings.values(), limit, offset, filters)
    return env.list_response(public_list(page), limit, offset, total)


@bp.post("/closings/<cid>/docs-pending")
def docs_pending(cid):
    ctx.authenticate(["ClosingCoordinator"])
    rec = ctx.lookup("closing", cid)
    if rec["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Closing is not SCHEDULED.")
    rec["status"] = "DOCS_PENDING"
    store.touch(rec)
    return env.success(public(rec), 200)


@bp.post("/closings/<cid>/complete")
def complete_closing(cid):
    ctx.authenticate(["ClosingCoordinator"])
    closing = ctx.lookup("closing", cid)
    data = ctx.body()
    final_purchase_price = ctx.req_int(data, "final_purchase_price_cents", 1)
    final_first_mortgage = ctx.req_int(data, "final_first_mortgage_cents", 0)

    if closing["status"] != "DOCS_PENDING":
        raise ApiError("ERR_INVALID_STATE", "Closing is not DOCS_PENDING.")
    award = store.awards[closing["award_id"]]
    if award["status"] != "FUNDED":
        raise ApiError("ERR_INVALID_STATE", "Award is not FUNDED.")
    prop = store.properties[closing["property_id"]]
    if prop["appraised_value_cents"] is None:
        raise ApiError("ERR_APPRAISAL_MISSING", "Property has no recorded appraisal.")

    closing["final_purchase_price_cents"] = final_purchase_price
    closing["final_first_mortgage_cents"] = final_first_mortgage
    closing["status"] = "COMPLETED"
    store.touch(closing)

    application = store.applications[award["application_id"]]
    program = store.programs[application["program_id"]]
    domain.complete_closing_cascade(closing, award, application, program, prop)
    return env.success(public(closing), 200)


@bp.post("/closings/<cid>/cancel")
def cancel_closing(cid):
    ctx.authenticate(["ClosingCoordinator"])
    rec = ctx.lookup("closing", cid)
    if rec["status"] not in ("SCHEDULED", "DOCS_PENDING"):
        raise ApiError("ERR_INVALID_STATE", "Closing is not cancellable.")
    rec["status"] = "CANCELLED"
    store.touch(rec)
    return env.success(public(rec), 200)
