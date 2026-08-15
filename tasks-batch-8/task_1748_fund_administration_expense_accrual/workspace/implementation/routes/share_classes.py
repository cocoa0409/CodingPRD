"""Share class endpoints: create, get, list, capital activity, performance."""
from decimal import Decimal

from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import ALL_ROLES, get_context, require_roles
from response import created, filter_arg, ok, paginate
from services.navmath import D, round4
from validation import (parse_body, query_param_date, query_param_number,
                        require_fk, require_path_entity)

bp = Blueprint("share_classes", __name__)

CLASS_SCHEMA = {
    "fund_id": ("string", True, None),
    "class_ticker": ("string", True, None),
    "distribution_frequency": ("enum", True, ["DAILY", "MONTHLY", "QUARTERLY", "ANNUALLY"]),
}

ACTIVITY_SCHEMA = {
    "activity_type": ("enum", True, ["SUBSCRIPTION", "REDEMPTION", "INCOME_POSTING"]),
    "activity_date": ("date", True, None),
    "shares": ("posnumber", False, None),
    "amount": ("posnumber", False, None),
}


@bp.post("/share-classes")
def create_share_class():
    get_context()
    require_roles(["FundController"])
    body = parse_body(CLASS_SCHEMA)
    fund = require_fk(store.funds, body["fund_id"], "fund_id")
    for existing in store.share_classes.values():
        if existing["fund_id"] == fund["id"] and existing["class_ticker"] == body["class_ticker"]:
            raise ApiError("ERR_TICKER_ALREADY_EXISTS", 409,
                           "class_ticker already exists within the fund")
    cls = {
        "id": db.new_id(),
        "fund_id": fund["id"],
        "class_ticker": body["class_ticker"],
        "distribution_frequency": body["distribution_frequency"],
        "shares_outstanding": Decimal("0"),
        "retained_income": Decimal("0"),
    }
    db.new_common(cls)
    store.share_classes[cls["id"]] = cls
    return created(cls)


@bp.get("/share-classes/<share_class_id>")
def get_share_class(share_class_id):
    get_context()
    cls = require_path_entity(store.share_classes, share_class_id)
    require_roles(ALL_ROLES)
    return ok(cls)


@bp.get("/share-classes")
def list_share_classes():
    get_context()
    require_roles(ALL_ROLES)
    rows = filter_arg(list(store.share_classes.values()), "fund_id")
    page, meta = paginate(rows)
    return ok(page, rtype="array", pagination=meta)


@bp.post("/share-classes/<share_class_id>/capital-activity")
def capital_activity(share_class_id):
    get_context()
    cls = require_path_entity(store.share_classes, share_class_id)
    require_roles(["FundAccountant"])
    body = parse_body(ACTIVITY_SCHEMA)
    activity_type = body["activity_type"]
    if activity_type in ("SUBSCRIPTION", "REDEMPTION"):
        if "shares" not in body:
            raise ApiError("ERR_VALIDATION", 400, "shares is required for %s" % activity_type)
        shares = D(body["shares"])
        if activity_type == "SUBSCRIPTION":
            cls["shares_outstanding"] = D(cls["shares_outstanding"]) + shares
        else:
            if shares > D(cls["shares_outstanding"]):
                raise ApiError("ERR_REDEMPTION_EXCEEDS_SHARES", 422,
                               "REDEMPTION shares exceed shares_outstanding")
            cls["shares_outstanding"] = D(cls["shares_outstanding"]) - shares
    else:  # INCOME_POSTING
        if "amount" not in body:
            raise ApiError("ERR_VALIDATION", 400, "amount is required for INCOME_POSTING")
        cls["retained_income"] = D(cls["retained_income"]) + D(body["amount"])
    db.touch(cls)
    return ok(cls)


@bp.get("/share-classes/<share_class_id>/performance")
def performance(share_class_id):
    get_context()
    cls = require_path_entity(store.share_classes, share_class_id)
    require_roles(ALL_ROLES)
    from_date = query_param_date("from_date")
    to_date = query_param_date("to_date")
    benchmark = query_param_number("benchmark_return_pct")

    finals = [n for n in store.nav_records.values()
              if n["share_class_id"] == cls["id"] and n["status"] == "FINAL"]
    begins = [n for n in finals if n["accounting_date"] >= from_date]
    ends = [n for n in finals if n["accounting_date"] <= to_date]
    if not begins or not ends:
        raise ApiError("ERR_NO_FINAL_NAV_IN_PERIOD", 422,
                       "No FINAL NavRecord of the class in the requested window")
    begin = min(begins, key=lambda n: n["accounting_date"])
    end = max(ends, key=lambda n: n["accounting_date"])

    dps = sum((D(d["income_per_share"]) for d in store.distributions.values()
               if d["share_class_id"] == cls["id"] and d["status"] == "PAID"
               and begin["accounting_date"] < d["payable_date"] <= end["accounting_date"]),
              Decimal("0"))
    begin_nav = D(begin["nav_per_share"])
    end_nav = D(end["nav_per_share"])
    period_return = round4(((end_nav + dps) / begin_nav - 1) * 100)
    excess = round4(period_return - D(benchmark))
    return ok({
        "begin_nav_per_share": begin_nav,
        "end_nav_per_share": end_nav,
        "distributions_per_share_total": dps,
        "period_return_pct": period_return,
        "benchmark_return_pct": benchmark,
        "excess_return_pct": excess,
    })
