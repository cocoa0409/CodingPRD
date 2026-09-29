"""Price rules (PRD 3.2)."""

from flask import Blueprint

import validate
from auth import CO, PCA, RIA, SA, require
from derive import find, price_rule_view, recompute_facility
from envelope import list_response, ok
from errors import fail
from routes_facilities import body_facility
from store import STORE, fmt_iso, serialize

bp = Blueprint("routes_pricing", __name__)

PRICING_METHODS = ("COST_PLUS_MARKUP", "MEDICARE_MULTIPLE", "FLAT_FEE")
RULE_READERS = [SA, RIA, PCA, CO]


def body_revenue_code(data, field="revenue_code_id", required=True):
    """Rank 10 — body FK resolution."""
    if field in data and isinstance(data.get(field), str):
        row = STORE.revenue_codes.get(data[field])
        if row is None:
            fail(
                "ERR_REFERENCED_RESOURCE_NOT_FOUND",
                "RevenueCode %s does not exist." % data[field],
            )
        return row
    if required:
        validate.req_id(data, field)
    return None


def _intervals_overlap(a_from, a_to, b_from, b_to):
    """Half-open [from, to) intersection; None `to` means open-ended."""
    if a_to is not None and b_from >= a_to:
        return False
    if b_to is not None and a_from >= b_to:
        return False
    return True


@bp.route("/chargemaster/price-rules", methods=["POST"])
def create_price_rule():
    require(RIA)
    data = validate.body()
    facility = body_facility(data)
    revenue_code = body_revenue_code(data)
    supersede = None
    if "supersede_rule_id" in data and isinstance(data.get("supersede_rule_id"), str):
        supersede = STORE.price_rules.get(data["supersede_rule_id"])
        if supersede is None:
            fail(
                "ERR_REFERENCED_RESOURCE_NOT_FOUND",
                "PriceRule %s does not exist." % data["supersede_rule_id"],
            )

    pricing_method = validate.req_enum(data, "pricing_method", PRICING_METHODS)
    effective_from = validate.req_dt(data, "effective_from")
    effective_to = validate.opt_dt(data, "effective_to")
    tiers = validate.markup_tiers(data, "markup_tiers")
    min_medicare = validate.opt_int(data, "min_medicare_multiple_bp", 12000)
    market_cap = validate.opt_int(data, "market_cap_multiple_bp", 11000)
    flat_fee = validate.opt_int(data, "flat_fee_cents")
    if effective_to is not None and not (effective_to > effective_from):
        fail("ERR_VALIDATION", "effective_to must be strictly later than effective_from.")

    for rule in STORE.ordered(STORE.price_rules):
        if rule["status"] != "ACTIVE":
            continue
        if rule["facility_id"] != facility["id"]:
            continue
        if rule["revenue_code_id"] != revenue_code["id"]:
            continue
        if supersede is not None and rule["id"] == supersede["id"]:
            continue
        if _intervals_overlap(
            rule["_effective_from"], rule.get("_effective_to"), effective_from, effective_to
        ):
            fail(
                "ERR_PRICE_RULE_OVERLAP",
                "An ACTIVE price rule already covers part of this interval.",
            )

    rule = {
        "facility_id": facility["id"],
        "revenue_code_id": revenue_code["id"],
        "pricing_method": pricing_method,
        "markup_tiers": tiers,
        "min_medicare_multiple_bp": min_medicare,
        "market_cap_multiple_bp": market_cap,
        "flat_fee_cents": flat_fee if pricing_method == "FLAT_FEE" else None,
        "effective_from": fmt_iso(effective_from),
        "effective_to": fmt_iso(effective_to),
        "status": "ACTIVE",
        "superseded_by_rule_id": None,
        "applied_item_count": 0,
        "_effective_from": effective_from,
        "_effective_to": effective_to,
    }
    STORE.stamp_new(rule)
    STORE.price_rules[rule["id"]] = rule

    if supersede is not None:
        supersede["status"] = "SUPERSEDED"
        supersede["effective_to"] = fmt_iso(effective_from)
        supersede["_effective_to"] = effective_from
        supersede["superseded_by_rule_id"] = rule["id"]
        STORE.touch(supersede)
        for item in STORE.ordered(STORE.charge_items):
            if item.get("applied_price_rule_id") != supersede["id"]:
                continue
            if item["price_status"] != "PRICED_CURRENT":
                continue
            item["price_status"] = "PRICE_STALE"
            STORE.touch(item)
        recompute_facility(facility, bump=True)

    return ok(serialize(price_rule_view(rule)), 201)


@bp.route("/chargemaster/price-rules", methods=["GET"])
def list_price_rules():
    require(RULE_READERS)
    facility_id = validate.query_filter("facility_id")
    revenue_code_id = validate.query_filter("revenue_code_id")
    superseded_by_rule_id = validate.query_filter("superseded_by_rule_id")
    status = validate.query_filter("status")

    def keep(row):
        if facility_id is not None and row["facility_id"] != facility_id:
            return False
        if revenue_code_id is not None and row["revenue_code_id"] != revenue_code_id:
            return False
        if (
            superseded_by_rule_id is not None
            and row.get("superseded_by_rule_id") != superseded_by_rule_id
        ):
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    rows = [price_rule_view(row) for row in STORE.ordered(STORE.price_rules, keep)]
    return list_response(rows, serialize)


@bp.route("/chargemaster/price-rules/<price_rule_id>", methods=["GET"])
def read_price_rule(price_rule_id):
    require(RULE_READERS)
    rule = find(
        STORE.price_rules,
        price_rule_id,
        "ERR_GOVERNANCE_RESOURCE_NOT_FOUND",
        "PriceRule",
    )
    return ok(serialize(price_rule_view(rule)))
