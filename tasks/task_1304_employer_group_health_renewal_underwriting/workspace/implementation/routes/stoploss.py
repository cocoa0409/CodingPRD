"""Stop-loss quote endpoints (PRD 3.7)."""
from flask import Blueprint

from db import store, new_record, touch
from errors import (
    ApiError, not_found,
    ERR_STOP_LOSS_NOT_DRAFT, ERR_STOP_LOSS_NOT_QUOTED,
    ERR_QUOTE_NOT_ACTIVE, ERR_QUOTE_NOT_ACCEPTED, ERR_NOT_LEVEL_FUNDED,
)
from middleware import auth
from response import ok, created, paginated, sorted_items
from serializers import stop_loss_json
from services import calcs
from services.workflow import latest_validated_census
from validators import body, req_int, req_num, opt_int, opt_list

bp = Blueprint("stoploss", __name__)

READ_ROLES = ["Underwriter", "SeniorUnderwriter", "Broker", "ComplianceOfficer"]


def get_slq_or_404(slq_id):
    slq = store.stop_losses.get(slq_id)
    if slq is None:
        raise not_found("Stop-loss quote does not exist")
    return slq


@bp.post("/quotes/<quoteId>/stop-loss-quotes")
def create_stop_loss(quoteId):
    auth(["Underwriter"])
    quote = store.quotes.get(quoteId)
    if quote is None:
        raise not_found("Quote does not exist")
    data = body()
    rec = new_record()
    rec.update({
        "quote_id": quoteId,
        "case_id": quote["case_id"],
        "specific_deductible_cents": req_int(data, "specific_deductible_cents"),
        "aggregate_attachment_pct": req_num(data, "aggregate_attachment_pct"),
        "expected_annual_claims_cents": 0,
        "aggregate_attachment_cents": 0,
        "specific_premium_cents": 0,
        "aggregate_premium_cents": 0,
        "total_stop_loss_premium_cents": 0,
        "laser_claimant_ids": opt_list(data, "laser_claimant_ids") or [],
        "laser_deductible_cents": opt_int(data, "laser_deductible_cents"),
        "status": "DRAFT",
    })
    store.stop_losses[rec["id"]] = rec
    return created(stop_loss_json(rec))


@bp.get("/quotes/<quoteId>/stop-loss-quotes")
def list_stop_loss(quoteId):
    auth(READ_ROLES)
    if quoteId not in store.quotes:
        raise not_found("Quote does not exist")
    items = [s for s in store.stop_losses.values() if s["quote_id"] == quoteId]
    return paginated([stop_loss_json(s) for s in sorted_items(items)])


@bp.get("/stop-loss-quotes/<slqId>")
def get_stop_loss(slqId):
    auth(READ_ROLES)
    return ok(stop_loss_json(get_slq_or_404(slqId)))


@bp.post("/stop-loss-quotes/<slqId>/quote")
def quote_stop_loss(slqId):
    auth(["Underwriter"])
    slq = get_slq_or_404(slqId)
    if slq["status"] != "DRAFT":
        raise ApiError(ERR_STOP_LOSS_NOT_DRAFT,
                       "Stop-loss quote must be in DRAFT to quote", 409)
    quote = store.quotes.get(slq["quote_id"])
    if quote is None:
        raise not_found("Quote does not exist")
    if quote["status"] not in ("PROPOSED", "COUNTERED"):
        raise ApiError(ERR_QUOTE_NOT_ACTIVE,
                       "Quote must be in PROPOSED or COUNTERED for stop-loss quoting", 409)
    if quote["funding_type"] != "LEVEL_FUNDED":
        raise ApiError(ERR_NOT_LEVEL_FUNDED,
                       "Stop-loss quoting requires LEVEL_FUNDED funding type", 409)

    case = store.cases[quote["case_id"]]
    census = latest_validated_census(case["id"])
    enrolled = census["enrolled_employees"] if census else 0
    # Experience rate projected across the year; manual stands in when absent
    base_rate = case["experience_rate_cents"] or case["manual_rate_cents"]

    expected = calcs.expected_annual_claims(base_rate, enrolled)
    attachment = calcs.aggregate_attachment(expected, slq["aggregate_attachment_pct"])
    specific = calcs.specific_premium(slq["specific_deductible_cents"], enrolled)
    aggregate = calcs.aggregate_premium(attachment)
    if slq["laser_claimant_ids"]:
        specific = calcs.apply_laser_load(specific)
    slq["expected_annual_claims_cents"] = expected
    slq["aggregate_attachment_cents"] = attachment
    slq["specific_premium_cents"] = specific
    slq["aggregate_premium_cents"] = aggregate
    slq["total_stop_loss_premium_cents"] = specific + aggregate
    slq["status"] = "QUOTED"
    touch(slq)
    return ok(stop_loss_json(slq))


@bp.post("/stop-loss-quotes/<slqId>/bind")
def bind_stop_loss(slqId):
    auth(["Underwriter"])
    slq = get_slq_or_404(slqId)
    if slq["status"] != "QUOTED":
        raise ApiError(ERR_STOP_LOSS_NOT_QUOTED,
                       "Stop-loss quote must be in QUOTED status", 409)
    quote = store.quotes.get(slq["quote_id"])
    if quote is None:
        raise not_found("Quote does not exist")
    if quote["status"] != "ACCEPTED":
        raise ApiError(ERR_QUOTE_NOT_ACCEPTED,
                       "Quote must be ACCEPTED to bind stop-loss", 409)
    slq["status"] = "BOUND"
    touch(slq)
    return ok(stop_loss_json(slq))


@bp.post("/stop-loss-quotes/<slqId>/decline-slq")
def decline_stop_loss(slqId):
    auth(["Underwriter"])
    slq = get_slq_or_404(slqId)
    if slq["status"] != "QUOTED":
        raise ApiError(ERR_STOP_LOSS_NOT_QUOTED,
                       "Stop-loss quote must be in QUOTED status", 409)
    slq["status"] = "DECLINED"
    touch(slq)
    return ok(stop_loss_json(slq))
