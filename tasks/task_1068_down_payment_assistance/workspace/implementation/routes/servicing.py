from flask import Blueprint

import store
from errors import ApiError
import context as ctx
import domain
from serializers import public, public_list
import envelope as env

bp = Blueprint("servicing", __name__)


@bp.get("/servicing-accounts/<sid>")
def get_servicing(sid):
    ctx.authenticate(["Servicer", "CaseManager", "ProgramAdmin"])
    rec = ctx.lookup("servicing", sid)
    return env.success(public(rec), 200)


@bp.get("/servicing-accounts")
def list_servicing():
    ctx.authenticate(["Servicer", "ProgramAdmin"])
    limit, offset = ctx.pagination_params()
    filters = {
        "award_id": ctx.query_filter("award_id"),
        "lifecycle_status": ctx.query_filter("lifecycle_status"),
        "payment_status": ctx.query_filter("payment_status"),
    }
    page, total = ctx.paginate(store.servicing.values(), limit, offset, filters)
    return env.list_response(public_list(page), limit, offset, total)


@bp.post("/servicing-accounts/<sid>/report-sale")
def report_sale(sid):
    ctx.authenticate(["Servicer"])
    sa = ctx.lookup("servicing", sid)
    data = ctx.body()
    sale_price_cents = ctx.req_int(data, "sale_price_cents", 1)
    sale_raw, sale_dt = ctx.req_datetime(data, "sale_date")

    if sa["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Servicing account is not ACTIVE.")
    if sale_dt < sa["_opened_dt"]:
        raise ApiError("ERR_SALE_BEFORE_OPEN", "sale_date precedes the account opening.")

    award = store.awards[sa["award_id"]]
    application = store.applications[award["application_id"]]
    program = store.programs[application["program_id"]]
    ev = domain.report_sale(sa, award, application, program,
                            sale_price_cents, sale_raw, sale_dt)
    return env.success(public(ev), 201)


@bp.get("/servicing-accounts/<sid>/sale-events")
def list_sale_events(sid):
    ctx.authenticate(["Servicer", "ProgramAdmin", "CaseManager"])
    ctx.lookup("servicing", sid)
    limit, offset = ctx.pagination_params()
    rows = [e for e in store.sale_events.values() if e["servicing_account_id"] == sid]
    page, total = ctx.paginate(rows, limit, offset)
    return env.list_response(public_list(page), limit, offset, total)


@bp.post("/servicing-accounts/<sid>/close")
def close_servicing(sid):
    ctx.authenticate(["Servicer"])
    sa = ctx.lookup("servicing", sid)
    if sa["lifecycle_status"] != "IN_SALE":
        raise ApiError("ERR_INVALID_STATE", "Servicing account is not IN_SALE.")
    has_sale = any(e["servicing_account_id"] == sid for e in store.sale_events.values())
    if not has_sale:
        raise ApiError("ERR_INVALID_STATE", "No sale event exists for this account.")
    award = store.awards[sa["award_id"]]
    domain.close_servicing(sa, award)
    return env.success(public(sa), 200)


@bp.post("/servicing-accounts/<sid>/payment-status")
def payment_status(sid):
    ctx.authenticate(["Servicer"])
    sa = ctx.lookup("servicing", sid)
    data = ctx.body()
    to = ctx.req_enum(data, "to", {"CURRENT", "DELINQUENT"})
    if sa["lifecycle_status"] == "CLOSED":
        raise ApiError("ERR_INVALID_STATE", "Servicing account is CLOSED.")
    if sa["payment_status"] == to:
        raise ApiError("ERR_INVALID_STATE", "Payment status is already %s." % to)
    sa["payment_status"] = to
    store.touch(sa)
    return env.success(public(sa), 200)
