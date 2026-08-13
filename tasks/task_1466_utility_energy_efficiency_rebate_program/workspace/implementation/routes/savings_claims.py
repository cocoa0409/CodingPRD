"""SavingsClaim endpoints (1:1 with a line item; DEEMED or MEASURED)."""
from flask import Blueprint, g, request

from auth import ALL_ROLES, require_roles
from db import light_fields, store
from errors import ApiError
from lookups import (
    claim_of_line,
    ensure_program_open,
    get_line_item,
    get_savings_claim,
    program_year_of_application,
)
from respond import respond_list, success
from serialize import savings_claim_out
from validate import get_body, opt_int, req_enum, req_str

bp = Blueprint("savings_claims", __name__)

# A claim must be in place before verification; attachment remains possible
# until the application is verified.
CLAIMABLE_STATUSES = ("DRAFT", "SUBMITTED", "PRE_INSPECTION", "POST_INSPECTION")


@bp.post("/savings-claims")
@require_roles("TradeAlly")
def create_savings_claim():
    body = get_body()
    line_item_id = req_str(body, "line_item_id")
    claim_method = req_enum(body, "claim_method", ("DEEMED", "MEASURED"))
    if claim_method == "MEASURED":
        pre_annual_kwh = opt_int(body, "pre_annual_kwh", minimum=0)
        post_annual_kwh = opt_int(body, "post_annual_kwh", minimum=0)
        if pre_annual_kwh is None or post_annual_kwh is None:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                400,
                "claim_method MEASURED requires both pre_annual_kwh and "
                "post_annual_kwh",
            )
    else:
        pre_annual_kwh = opt_int(body, "pre_annual_kwh", minimum=0)
        post_annual_kwh = opt_int(body, "post_annual_kwh", minimum=0)
    # Body FK resolution.
    line = get_line_item(line_item_id)
    app = store.applications[line["application_id"]]
    # Program-open gate.
    ensure_program_open(program_year_of_application(app))
    if app["status"] not in CLAIMABLE_STATUSES:
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "RebateApplication.status is %s; savings claims must be attached "
            "before verification" % app["status"],
        )
    # One claim per line item.
    if claim_of_line(line["id"]) is not None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "Line item %s already has a savings claim" % line["id"],
        )
    # Ownership.
    if g.user_id != app["trade_ally_id"]:
        raise ApiError(
            "ERR_FORBIDDEN",
            403,
            "TradeAlly %s does not own application %s" % (g.user_id, app["id"]),
        )
    rec = light_fields()
    rec.update(
        {
            "line_item_id": line_item_id,
            "claim_method": claim_method,
            "pre_annual_kwh": pre_annual_kwh,
            "post_annual_kwh": post_annual_kwh,
            # Populated at verification time.
            "computed_kwh": None,
        }
    )
    store.savings_claims[rec["id"]] = rec
    return success(savings_claim_out(rec), "object", 201)


@bp.get("/savings-claims")
@require_roles(*ALL_ROLES)
def list_savings_claims():
    line_item_id = request.args.get("line_item_id")
    claim_method = request.args.get("claim_method")
    rows = list(store.savings_claims.values())
    if line_item_id is not None:
        rows = [r for r in rows if r["line_item_id"] == line_item_id]
    if claim_method is not None:
        rows = [r for r in rows if r["claim_method"] == claim_method]
    return respond_list(rows, savings_claim_out)


@bp.get("/savings-claims/<rid>")
@require_roles(*ALL_ROLES)
def get_savings_claim_route(rid):
    return success(savings_claim_out(get_savings_claim(rid)), "object", 200)
