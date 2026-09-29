"""Loss attribution authoring, superseding and ratification (PRD 3.6)."""
from decimal import Decimal

from flask import Blueprint, g

from db import DerivedWatch, db, new_row, touch
from errors import fail
from middleware import endpoint, ANY_ROLE
from response import list_response, object_response
from util import dec, rhu
from validate import (ATTR_STATUS, body, fk_from_body, fk_from_query, opt_str,
                      paginate, pagination, query_enum, query_str, req_int,
                      req_number, req_str, resolve)

from services import calc, cascade, serialize
from services.listing import by_created_at

bp = Blueprint("attributions", __name__)

MIN_WEIGHT = Decimal("0.50")
MAX_WEIGHT = Decimal("1.00")


def get_attribution(attribution_id):
    return resolve(db.loss_attributions, attribution_id,
                   "ERR_LOSS_ATTRIBUTION_NOT_FOUND")


def _live_attribution_of_deal(deal_id):
    for attribution in db.loss_attributions.values():
        if attribution["deal_id"] == deal_id and \
                attribution["status"] in ("PROVISIONAL", "RATIFIED"):
            return attribution
    return None


@bp.post("/loss-attributions")
@endpoint(("ResearchAnalyst",), analyst_identity=True)
def author_attribution():
    payload = body()
    deal = fk_from_body(payload, "deal_id", db.deals, "ERR_DEAL_NOT_FOUND")
    primary = fk_from_body(payload, "primary_reason_id", db.loss_reasons,
                           "ERR_LOSS_REASON_NOT_FOUND")
    secondary = fk_from_body(payload, "secondary_reason_id", db.loss_reasons,
                             "ERR_LOSS_REASON_NOT_FOUND")
    req_str(payload, "deal_id")
    req_str(payload, "primary_reason_id")
    weight_primary = req_number(payload, "weight_primary")
    expected_deal_version = req_int(payload, "expected_deal_version")
    secondary_id = opt_str(payload, "secondary_reason_id")
    if primary is None:
        fail("ERR_LOSS_REASON_NOT_FOUND")

    # 8. numeric domain
    weight = dec(weight_primary)
    if weight < MIN_WEIGHT or weight > MAX_WEIGHT:
        fail("ERR_VALUE_OUT_OF_RANGE",
             "weight_primary must lie between 0.50 and 1.00 inclusive.")

    # 10. tenancy
    cited = [primary] + ([secondary] if secondary is not None else [])
    for reason in cited:
        if reason["program_id"] != deal["program_id"]:
            fail("ERR_CROSS_PROGRAM_REFERENCE",
                 "A cited loss reason belongs to a different program.")

    # 11. at most one live attribution per deal
    live = _live_attribution_of_deal(deal["id"])
    if live is not None and live["status"] == "PROVISIONAL":
        fail("ERR_DUPLICATE_RESOURCE_KEY",
             "The deal already holds a PROVISIONAL attribution.")

    # 12. optimistic concurrency on the parent deal
    if expected_deal_version != deal["version"]:
        fail("ERR_STALE_DEAL_VERSION",
             "expected_deal_version does not match the deal's current version.")

    # 13. staging state
    superseding = live is not None and live["status"] == "RATIFIED"
    if not superseding and deal["research_status"] != "INTERVIEWED":
        fail("ERR_DEAL_STATE_INVALID",
             "Only an INTERVIEWED deal can be attributed.")

    # 26/27. reason predicates
    for reason in cited:
        if not calc.is_leaf(reason):
            fail("ERR_REASON_NOT_LEAF",
                 "Only a leaf loss reason may be cited.")
    for reason in cited:
        if reason["status"] != "ACTIVE":
            fail("ERR_REASON_DEPRECATED",
                 "A deprecated loss reason may not be cited.")

    # 30. weight conservation
    if weight != rhu(weight, 2):
        fail("ERR_WEIGHT_SPLIT_INVALID",
             "weight_primary must carry at most two decimal places.")
    if secondary is None:
        if weight != MAX_WEIGHT:
            fail("ERR_WEIGHT_SPLIT_INVALID",
                 "weight_primary must be exactly 1.00 without a secondary reason.")
    else:
        if secondary["id"] == primary["id"]:
            fail("ERR_WEIGHT_SPLIT_INVALID",
                 "The secondary reason must differ from the primary reason.")

    weight_secondary = rhu(MAX_WEIGHT - weight, 2)

    watch = DerivedWatch()
    if superseding:
        for reason_id in (live["primary_reason_id"], live.get("secondary_reason_id")):
            if reason_id and reason_id in db.loss_reasons:
                watch.watch(db.loss_reasons[reason_id], calc.reason_ratified_attribution_count)
        old_competitor = db.competitors.get(deal.get("primary_competitor_id"))
        watch.watch(old_competitor, calc.competitor_derived)
        cascade.rescore_gaps_watch(watch, deal["id"])
        live["status"] = "SUPERSEDED"
        touch(live)

    attribution = new_row({
        "deal_id": deal["id"],
        "primary_reason_id": primary["id"],
        "secondary_reason_id": secondary["id"] if secondary is not None else None,
        "authored_by_analyst_id": g.user_id,
        "ratified_by_analyst_id": None,
        "weight_primary": rhu(weight, 2),
        "weight_secondary": weight_secondary,
        "status": "PROVISIONAL",
        "confidence_score": calc.confidence_score(
            weight, calc.interview_coverage_count(deal)),
    })
    db.loss_attributions[attribution["id"]] = attribution

    deal["attribution_status"] = "PROVISIONAL"
    if superseding:
        deal["research_status"] = "INTERVIEWED"
    touch(deal)
    watch.commit()
    return object_response(serialize.loss_attribution(attribution), 201)


@bp.get("/loss-attributions/<attribution_id>")
@endpoint(ANY_ROLE)
def read_attribution(attribution_id):
    return object_response(serialize.loss_attribution(get_attribution(attribution_id)))


@bp.get("/loss-attributions")
@endpoint(ANY_ROLE)
def list_attributions():
    deal_id = fk_from_query("deal_id", db.deals, "ERR_DEAL_NOT_FOUND")
    primary_id = fk_from_query("primary_reason_id", db.loss_reasons,
                               "ERR_LOSS_REASON_NOT_FOUND")
    secondary_id = fk_from_query("secondary_reason_id", db.loss_reasons,
                                 "ERR_LOSS_REASON_NOT_FOUND")
    authored_by = query_str("authored_by_analyst_id")
    ratified_by = query_str("ratified_by_analyst_id")
    status = query_enum("status", ATTR_STATUS)
    limit, offset = pagination()
    rows = list(db.loss_attributions.values())
    if deal_id:
        rows = [a for a in rows if a["deal_id"] == deal_id]
    if primary_id:
        rows = [a for a in rows if a["primary_reason_id"] == primary_id]
    if secondary_id:
        rows = [a for a in rows if a.get("secondary_reason_id") == secondary_id]
    if authored_by:
        rows = [a for a in rows if a["authored_by_analyst_id"] == authored_by]
    if ratified_by:
        rows = [a for a in rows if a.get("ratified_by_analyst_id") == ratified_by]
    if status:
        rows = [a for a in rows if a["status"] == status]
    rows = by_created_at(rows)
    page, total = paginate(rows, limit, offset)
    return list_response([serialize.loss_attribution(r) for r in page],
                         limit, offset, total)


@bp.post("/loss-attributions/<attribution_id>/ratify")
@endpoint(("ResearchAnalyst",), analyst_identity=True)
def ratify_attribution(attribution_id):
    attribution = get_attribution(attribution_id)
    body()
    if attribution["status"] != "PROVISIONAL":
        fail("ERR_ATTRIBUTION_STATE_INVALID",
             "Only a PROVISIONAL attribution can be ratified.")

    deal = db.deals[attribution["deal_id"]]
    # 15. segregation of duties
    if g.user_id == attribution["authored_by_analyst_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The author of an attribution may not ratify it.")
    for interview in calc.interviews_of_deal(deal["id"]):
        if interview["status"] == "COMPLETED" and interview["analyst_id"] == g.user_id:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "An interviewer on this deal may not ratify its attribution.")

    primary = db.loss_reasons.get(attribution["primary_reason_id"])
    secondary = db.loss_reasons.get(attribution.get("secondary_reason_id"))
    competitor = db.competitors.get(deal.get("primary_competitor_id"))

    attribution["status"] = "RATIFIED"
    attribution["ratified_by_analyst_id"] = g.user_id
    touch(attribution)

    deal["attribution_status"] = "RATIFIED"
    deal["research_status"] = "SYNTHESIZED"
    touch(deal)

    if primary is not None:
        touch(primary)
    if secondary is not None:
        touch(secondary)
    if competitor is not None and deal["outcome"] in ("LOST", "NO_DECISION"):
        touch(competitor)
    return object_response(serialize.loss_attribution(attribution))
