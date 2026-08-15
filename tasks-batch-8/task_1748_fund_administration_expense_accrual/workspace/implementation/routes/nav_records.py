"""NavRecord endpoints: create (with auto ADMIN_FEE accrual), get, list,
finalize (OCC-guarded, SoD), reopen (latest-only, fiscal-lock aware)."""
from decimal import Decimal
from flask import Blueprint, g

import db
from db import store
from errors import ApiError
from middleware import ALL_ROLES, get_context, require_roles
from response import created, filter_arg, ok, paginate
from services import navmath
from validation import parse_body, require_fk, require_path_entity

bp = Blueprint("nav_records", __name__)

NAV_CREATE_SCHEMA = {
    "share_class_id": ("string", True, None),
    "accounting_date": ("date", True, None),
}

FINALIZE_SCHEMA = {
    "expected_nav_record_version": ("integer", True, None),
}


@bp.post("/nav-records")
def create_nav_record():
    get_context()
    require_roles(["FundAccountant"])
    body = parse_body(NAV_CREATE_SCHEMA)
    cls = require_fk(store.share_classes, body["share_class_id"], "share_class_id")
    accounting_date = body["accounting_date"]

    # Constraints (priority 9): strictly-sequential accounting date, then
    # every OPEN position's security priced (any status) on the date.
    for other in store.nav_records.values():
        if other["share_class_id"] == cls["id"] \
                and other["accounting_date"] >= accounting_date:
            raise ApiError("ERR_NAV_DATE_NOT_SEQUENTIAL", 409,
                           "accounting_date must be strictly later than all existing records")
    for pos in navmath.open_positions(cls["id"]):
        has_price = any(
            o["security_id"] == pos["security_id"] and o["price_date"] == accounting_date
            for o in store.price_observations.values())
        if not has_price:
            raise ApiError("ERR_MISSING_PRICE", 422,
                           "An OPEN position's security has no observation on accounting_date")

    # Fiscal check (priority 10, last): the class must have shares outstanding.
    if navmath.D(cls["shares_outstanding"]) <= 0:
        raise ApiError("ERR_NO_SHARES_OUTSTANDING", 422,
                       "Cannot create a NavRecord while shares_outstanding is zero")

    nav = {
        "id": db.new_id(),
        "share_class_id": cls["id"],
        "accounting_date": accounting_date,
        "status": "ESTIMATED",
        "pricing_variant_used": "PROVISIONAL",
        "gross_asset_value": Decimal("0"),
        "expense_accrual_total": Decimal("0"),
        "total_net_assets": Decimal("0"),
        "nav_per_share": None,
        "provisional_nav_per_share": None,
        "final_nav_per_share": None,
        "created_by_user_id": g.user_id,
    }
    db.new_common(nav)
    store.nav_records[nav["id"]] = nav

    # The automatic ADMIN_FEE accrual for the same date.
    fund = navmath.fund_of_class(cls)
    prior = navmath.prior_final_tna(cls["id"], accounting_date)
    if prior is not None:
        base = prior
    else:
        base, _ = navmath.compute_gav(cls["id"], accounting_date, "PROVISIONAL")
    navmath.new_accrual(cls["id"], accounting_date, "ADMIN_FEE",
                        fund["admin_fee_bps"], base)

    navmath.recompute_nav(nav, bump=False)
    return created(nav)


@bp.get("/nav-records/<nav_record_id>")
def get_nav_record(nav_record_id):
    get_context()
    nav = require_path_entity(store.nav_records, nav_record_id)
    require_roles(ALL_ROLES)
    return ok(nav)


@bp.get("/nav-records")
def list_nav_records():
    get_context()
    require_roles(ALL_ROLES)
    rows = list(store.nav_records.values())
    rows = filter_arg(rows, "share_class_id")
    rows = filter_arg(rows, "status")
    rows = filter_arg(rows, "accounting_date")
    page, meta = paginate(rows)
    return ok(page, rtype="array", pagination=meta)


@bp.post("/nav-records/<nav_record_id>/finalize")
def finalize_nav_record(nav_record_id):
    get_context()
    nav = require_path_entity(store.nav_records, nav_record_id)
    require_roles(["FundController"])
    body = parse_body(FINALIZE_SCHEMA)

    # State (priority 5) -> OCC (5b) -> SoD (6) -> price gate (9).
    if nav["status"] not in ("ESTIMATED", "REOPENED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Only an ESTIMATED or REOPENED record can be finalized")
    if body["expected_nav_record_version"] != nav["version"]:
        raise ApiError("ERR_STALE_NAV_VERSION", 412,
                       "expected_nav_record_version does not match the record's current version")
    if g.user_id == nav["created_by_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION", 403,
                       "The record's preparer cannot finalize it")

    cls = store.share_classes[nav["share_class_id"]]
    for pos in navmath.open_positions(cls["id"]):
        observations = [o for o in store.price_observations.values()
                        if o["security_id"] == pos["security_id"]
                        and o["price_date"] == nav["accounting_date"]]
        if any(o["status"] == "SUBMITTED" for o in observations):
            raise ApiError("ERR_PRICE_NOT_APPROVED", 409,
                           "A held security still has a SUBMITTED observation on accounting_date")
        if not any(o["status"] == "APPROVED" for o in observations):
            raise ApiError("ERR_PRICE_NOT_APPROVED", 409,
                           "A held security lacks an APPROVED observation on accounting_date")

    nav["status"] = "FINAL"
    navmath.recompute_nav(nav, bump=False)  # full FINAL_PRICED recompute
    for row in navmath.class_accruals(cls["id"], nav["accounting_date"]):
        if row["status"] == "ESTIMATED":
            row["status"] = "POSTED"
            db.touch(row)
    navmath.run_cap_test(nav)
    db.touch(nav)  # exactly one version increment for the whole finalize
    return ok(nav)


@bp.post("/nav-records/<nav_record_id>/reopen")
def reopen_nav_record(nav_record_id):
    get_context()
    nav = require_path_entity(store.nav_records, nav_record_id)
    require_roles(["FundController"])
    parse_body({})

    if nav["status"] != "FINAL":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a FINAL record can be reopened")
    if not navmath.is_latest_nav(nav):
        raise ApiError("ERR_NAV_NOT_LATEST", 409,
                       "Only the class's latest record can be reopened")
    fund = navmath.fund_of_class(store.share_classes[nav["share_class_id"]])
    closed_end = fund["last_closed_fiscal_year_end"]
    if closed_end is not None and nav["accounting_date"] <= closed_end:
        raise ApiError("ERR_NAV_LOCKED_FISCAL_CLOSED", 409,
                       "The record falls inside an already-closed fiscal year")

    nav["status"] = "REOPENED"
    for row in navmath.class_accruals(nav["share_class_id"], nav["accounting_date"]):
        if row["status"] == "POSTED":
            row["status"] = "ESTIMATED"
            db.touch(row)
    navmath.recompute_nav(nav, bump=False)  # FINAL_PRICED recompute
    db.touch(nav)  # exactly one version increment for the reopen
    return ok(nav)
