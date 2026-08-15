"""PricingPeriod + PriceAnnouncement endpoints, incl. FINAL true-up."""

from flask import Blueprint, request

from db import DB
from middleware import require_role, require_any
from util import (
    get_json_body, check_unknown_fields, require_fields, opt_int, opt_enum,
    opt_month_str, base_fields, paginate, err, touch,
)
from response import success_object, success_list
from errors import (
    ERR_INVALID_REQUEST, ERR_PRICING_PERIOD_NOT_FOUND, ERR_ANNOUNCEMENT_NOT_FOUND,
    ERR_PERIOD_CLOSED, ERR_STALE_PRICING_PERIOD_VERSION,
)
from serializers import serialize_pricing_period, serialize_announcement
from services import run_true_up

bp = Blueprint("pricing", __name__)


def get_period_or_404(period_id):
    p = DB.pricing_periods.get(period_id)
    if p is None:
        raise err(ERR_PRICING_PERIOD_NOT_FOUND, "PricingPeriod id not found")
    return p


@bp.post("/dairy/pricing-periods")
def create_period():
    require_role("MarketAdministrator")
    body = get_json_body()
    check_unknown_fields(body, {"month"})
    require_fields(body, ["month"])
    month = opt_month_str(body, "month")
    for p in DB.pricing_periods.values():
        if p["month"] == month:
            raise err(ERR_INVALID_REQUEST, "month must be unique across pricing periods")
    p = base_fields()
    p.update({
        "month": month,
        "status": "OPEN",
        "current_provisional_id": None,
        "current_final_id": None,
    })
    DB.pricing_periods[p["id"]] = p
    return success_object(serialize_pricing_period(p), status=201)


@bp.get("/dairy/pricing-periods/<periodId>")
def get_period(periodId):
    require_any()
    return success_object(serialize_pricing_period(get_period_or_404(periodId)))


@bp.post("/dairy/pricing-periods/<periodId>/close")
def close_period(periodId):
    require_role("MarketAdministrator")
    p = get_period_or_404(periodId)
    if p["status"] != "OPEN":
        raise err(ERR_PERIOD_CLOSED, "Period is already CLOSED")
    if not p.get("current_final_id"):
        raise err(ERR_PERIOD_CLOSED, "Close requires an ACTIVE FINAL announcement")
    p["status"] = "CLOSED"
    touch(p)
    return success_object(serialize_pricing_period(p))


@bp.post("/dairy/pricing-periods/<periodId>/announcements")
def publish_announcement(periodId):
    require_role("MarketAdministrator")
    p = get_period_or_404(periodId)
    body = get_json_body()
    allowed = {"kind", "class_i_base_cents_per_cwt",
               "processor_assessment_cents_per_cwt", "hauling_cents_per_cwt",
               "diesel_index_cents", "expected_pricing_period_version"}
    check_unknown_fields(body, allowed)
    require_fields(body, ["kind", "class_i_base_cents_per_cwt",
                          "processor_assessment_cents_per_cwt",
                          "hauling_cents_per_cwt", "diesel_index_cents",
                          "expected_pricing_period_version"])
    kind = opt_enum(body, "kind", {"PROVISIONAL", "FINAL"})
    base = opt_int(body, "class_i_base_cents_per_cwt", ge=0)
    assessment = opt_int(body, "processor_assessment_cents_per_cwt", ge=0)
    hauling = opt_int(body, "hauling_cents_per_cwt", ge=0)
    diesel = opt_int(body, "diesel_index_cents", ge=0)
    expected = opt_int(body, "expected_pricing_period_version")
    # OCC guard (rule announcement-publish-stale-period).
    if expected != p["version"]:
        raise err(ERR_STALE_PRICING_PERIOD_VERSION,
                  "expected_pricing_period_version does not match the period's current version")
    if p["status"] != "OPEN":
        raise err(ERR_PERIOD_CLOSED, "A closed period accepts no further announcements")
    # Supersede the prior ACTIVE announcement of the same kind.
    prior = None
    for a in DB.price_announcements.values():
        if (a["pricing_period_id"] == p["id"] and a["kind"] == kind
                and a["status"] == "ACTIVE"):
            prior = a
            break
    a = base_fields()
    a.update({
        "pricing_period_id": p["id"],
        "kind": kind,
        "class_i_base_cents_per_cwt": base,
        "processor_assessment_cents_per_cwt": assessment,
        "hauling_cents_per_cwt": hauling,
        "diesel_index_cents": diesel,
        "supersedes_announcement_id": prior["id"] if prior else None,
        "status": "ACTIVE",
    })
    DB.price_announcements[a["id"]] = a
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)
    if kind == "PROVISIONAL":
        p["current_provisional_id"] = a["id"]
    else:
        p["current_final_id"] = a["id"]
    touch(p)  # a successful publish increments the period's version by one
    if kind == "FINAL":
        run_true_up(p, a)
    return success_object(serialize_announcement(a), status=201)


@bp.get("/dairy/pricing-periods/<periodId>/announcements")
def list_period_announcements(periodId):
    require_any()
    p = get_period_or_404(periodId)
    items = [a for a in DB.price_announcements.values() if a["pricing_period_id"] == p["id"]]
    kind = request.args.get("kind")
    if kind is not None:
        items = [a for a in items if a["kind"] == kind]
    items.sort(key=lambda a: a["_seq"])
    page, limit, offset, total = paginate(items)
    return success_list([serialize_announcement(a) for a in page], limit, offset, total)


@bp.get("/dairy/price-announcements/<annId>")
def get_announcement(annId):
    require_any()
    a = DB.price_announcements.get(annId)
    if a is None:
        raise err(ERR_ANNOUNCEMENT_NOT_FOUND, "PriceAnnouncement id not found")
    return success_object(serialize_announcement(a))


@bp.get("/dairy/price-announcements")
def list_announcements():
    require_any()
    items = list(DB.price_announcements.values())
    period_id = request.args.get("pricing_period_id")
    if period_id is not None:
        items = [a for a in items if a["pricing_period_id"] == period_id]
    supersedes = request.args.get("supersedes_announcement_id")
    if supersedes is not None:
        items = [a for a in items if a["supersedes_announcement_id"] == supersedes]
    items.sort(key=lambda a: a["_seq"])
    page, limit, offset, total = paginate(items)
    return success_list([serialize_announcement(a) for a in page], limit, offset, total)
