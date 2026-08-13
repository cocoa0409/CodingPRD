"""ApplicationLineItem endpoints."""
from flask import Blueprint, g, request

from auth import ALL_ROLES, require_roles
from db import base_fields, store
from errors import ApiError
from lookups import (
    ensure_program_open,
    get_application,
    get_line_item,
    get_measure,
    program_year_of_application,
)
from respond import respond_list, success
from serialize import line_item_out
from validate import get_body, req_int, req_str

bp = Blueprint("line_items", __name__)


@bp.post("/line-items")
@require_roles("TradeAlly")
def create_line_item():
    body = get_body()
    application_id = req_str(body, "application_id")
    measure_id = req_str(body, "measure_id")
    quantity = req_int(body, "quantity", minimum=1)
    # Body FK resolution.
    app = get_application(application_id)
    get_measure(measure_id)
    # Program-open gate.
    ensure_program_open(program_year_of_application(app))
    # Line items are composed while the application is in DRAFT.
    if app["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "RebateApplication.status is %s; line items may only be added "
            "while DRAFT" % app["status"],
        )
    # Ownership.
    if g.user_id != app["trade_ally_id"]:
        raise ApiError(
            "ERR_FORBIDDEN",
            403,
            "TradeAlly %s does not own application %s" % (g.user_id, app["id"]),
        )
    rec = base_fields()
    rec.update(
        {
            "application_id": application_id,
            "measure_id": measure_id,
            "quantity": quantity,
            "pacing_tier_at_submit": None,
            "incentive_cents": None,
            "claimed_kwh": None,
            "measured_kwh": None,
            "final_kwh": None,
        }
    )
    store.line_items[rec["id"]] = rec
    # Line items are independent records: the application's version is NOT
    # incremented.
    return success(line_item_out(rec), "object", 201)


@bp.get("/line-items")
@require_roles(*ALL_ROLES)
def list_line_items():
    application_id = request.args.get("application_id")
    measure_id = request.args.get("measure_id")
    rows = list(store.line_items.values())
    if application_id is not None:
        rows = [r for r in rows if r["application_id"] == application_id]
    if measure_id is not None:
        rows = [r for r in rows if r["measure_id"] == measure_id]
    return respond_list(rows, line_item_out)


@bp.get("/line-items/<rid>")
@require_roles(*ALL_ROLES)
def get_line_item_route(rid):
    return success(line_item_out(get_line_item(rid)), "object", 200)
