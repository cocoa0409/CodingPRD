"""Distribution endpoints: declare (snapshot + per-share-first rounding),
pay (optional reinvestment cascade), cancel (compensating no-op on balances)."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import ALL_ROLES, get_context, require_roles
from response import created, filter_arg, ok, paginate
from services import navmath
from services.navmath import D, round2, round4
from validation import parse_body, require_fk, require_path_entity

bp = Blueprint("distributions", __name__)

DECLARE_SCHEMA = {
    "share_class_id": ("string", True, None),
    "declaration_date": ("date", True, None),
    "ex_date": ("date", True, None),
    "record_date": ("date", True, None),
    "payable_date": ("date", True, None),
}

PAY_SCHEMA = {
    "reinvest": ("boolean", False, None),
}


@bp.post("/distributions")
def declare_distribution():
    get_context()
    require_roles(["FundAccountant"])
    body = parse_body(DECLARE_SCHEMA)
    cls = require_fk(store.share_classes, body["share_class_id"], "share_class_id")

    # Constraints (priority 9): strict date ordering, then latest record FINAL.
    if not (body["declaration_date"] < body["ex_date"]
            <= body["record_date"] <= body["payable_date"]):
        raise ApiError("ERR_DISTRIBUTION_DATE_ORDER", 422,
                       "Dates must satisfy declaration_date < ex_date <= record_date <= payable_date")
    latest = navmath.latest_nav(cls["id"])
    if latest is None or latest["status"] != "FINAL":
        raise ApiError("ERR_NAV_NOT_FINAL", 409,
                       "The class's latest NavRecord must be FINAL to declare a distribution")

    # Fiscal check (priority 10, last): the class must hold distributable income.
    retained = D(cls["retained_income"])
    if retained <= 0:
        raise ApiError("ERR_NO_DISTRIBUTABLE_INCOME", 422,
                       "retained_income is zero")

    distributable = retained
    shares_snapshot = D(cls["shares_outstanding"])
    # Per-share rounding happens FIRST, then multiply back over the share count.
    income_per_share = round4(distributable / shares_snapshot)
    total_amount = round2(income_per_share * shares_snapshot)

    distribution = {
        "id": db.new_id(),
        "share_class_id": cls["id"],
        "declaration_date": body["declaration_date"],
        "ex_date": body["ex_date"],
        "record_date": body["record_date"],
        "payable_date": body["payable_date"],
        "distributable_amount": distributable,
        "shares_snapshot": shares_snapshot,
        "income_per_share": income_per_share,
        "total_amount": total_amount,
        "status": "DECLARED",
        "reinvested_shares": None,
        "paid_at": None,
    }
    db.new_common(distribution)
    store.distributions[distribution["id"]] = distribution
    return created(distribution)


@bp.get("/distributions/<distribution_id>")
def get_distribution(distribution_id):
    get_context()
    distribution = require_path_entity(store.distributions, distribution_id)
    require_roles(ALL_ROLES)
    return ok(distribution)


@bp.get("/distributions")
def list_distributions():
    get_context()
    require_roles(ALL_ROLES)
    rows = list(store.distributions.values())
    rows = filter_arg(rows, "share_class_id")
    rows = filter_arg(rows, "status")
    page, meta = paginate(rows)
    return ok(page, rtype="array", pagination=meta)


@bp.post("/distributions/<distribution_id>/pay")
def pay_distribution(distribution_id):
    get_context()
    distribution = require_path_entity(store.distributions, distribution_id)
    require_roles(["FundController"])
    body = parse_body(PAY_SCHEMA)

    if distribution["status"] != "DECLARED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a DECLARED distribution can be paid")
    # Temporal (priority 8): the clock date must be on or after payable_date.
    if db.clock_today() < navmath.date_of(distribution["payable_date"]):
        raise ApiError("ERR_DISTRIBUTION_NOT_PAYABLE", 422,
                       "The distribution is not yet payable")

    cls = store.share_classes[distribution["share_class_id"]]
    reinvest = body.get("reinvest", False)
    reinvested_shares = None
    if reinvest:
        # Constraint (priority 9): a FINAL record on or before payable_date.
        finals = [n for n in store.nav_records.values()
                  if n["share_class_id"] == cls["id"] and n["status"] == "FINAL"
                  and n["accounting_date"] <= distribution["payable_date"]]
        if not finals:
            raise ApiError("ERR_NAV_NOT_FINAL", 409,
                           "No FINAL NavRecord on or before payable_date for reinvestment")
        reinvest_nav = max(finals, key=lambda n: n["accounting_date"])
        reinvested_shares = round4(D(distribution["total_amount"])
                                   / D(reinvest_nav["nav_per_share"]))

    distribution["status"] = "PAID"
    distribution["paid_at"] = db.logical_now()
    distribution["reinvested_shares"] = reinvested_shares
    cls["retained_income"] = D(cls["retained_income"]) - D(distribution["total_amount"])
    if reinvested_shares is not None:
        cls["shares_outstanding"] = D(cls["shares_outstanding"]) + reinvested_shares
    db.touch(distribution)
    db.touch(cls)

    if reinvested_shares is not None:
        # The share-count mutation recomputes the class's latest ESTIMATED
        # record, if one exists.
        navmath.recompute_latest_estimated(cls["id"])
    return ok(distribution)


@bp.post("/distributions/<distribution_id>/cancel")
def cancel_distribution(distribution_id):
    get_context()
    distribution = require_path_entity(store.distributions, distribution_id)
    require_roles(["FundController"])
    parse_body({})
    if distribution["status"] != "DECLARED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only a DECLARED distribution can be cancelled")
    distribution["status"] = "CANCELLED"
    db.touch(distribution)
    return ok(distribution)
