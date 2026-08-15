"""Reit endpoints: register, fetch, list, ep-balance, dividend-characterization-preview."""

from decimal import Decimal
from flask import Blueprint, request

import errors
from db import db
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from services.calculations import (
    calc_ep_balance,
    capital_gain_pool,
    calc_dividend_characterization_waterfall,
    calc_dividend_characterization_pro_rata,
)
from services.common import (
    get_json_body,
    make_entity,
    req_date,
    req_number,
    req_string,
)

bp = Blueprint("reits", __name__)

ALL = ("ComplianceOfficer", "TaxDirector", "BoardDirector")


def reit_view(r):
    return dict(r)


@bp.route("/reit-compliance/reits", methods=["POST"])
def create_reit():
    require_roles("TaxDirector")
    body = get_json_body()
    legal_name = req_string(body, "legal_name")
    ticker = req_string(body, "ticker")
    limit_pct = req_number(body, "charter_ownership_limit_pct")
    # 0 < value < 50.0 (open interval)
    if not (Decimal(str(limit_pct)) > 0 and Decimal(str(limit_pct)) < Decimal("50.0")):
        raise errors.validation(
            "charter_ownership_limit_pct must be strictly between 0 and 50.0"
        )
    taxable_year_start = req_date(body, "taxable_year_start")

    # Uniqueness: ticker unique across all Reit rows
    for existing in db.reits.values():
        if existing["ticker"] == ticker:
            raise errors.duplicate("ticker must be unique across all REITs")

    reit = make_entity({
        "legal_name": legal_name,
        "ticker": ticker,
        "charter_ownership_limit_pct": limit_pct,
        "taxable_year_start": taxable_year_start,
        "status": "ACTIVE",
        "current_ep_balance_cents": 0,
        "dividend_distribution_deficit_cents": 0,
        "five_fifty_blocked": False,
    })
    db.reits[reit["id"]] = reit
    return success_object(reit_view(reit), status=201)


@bp.route("/reit-compliance/reits/<rid>", methods=["GET"])
def get_reit(rid):
    require_roles(*ALL)
    reit = db.reits.get(rid)
    if reit is None:
        raise errors.not_found("REIT not found")
    return success_object(reit_view(reit))


@bp.route("/reit-compliance/reits", methods=["GET"])
def list_reits():
    require_roles(*ALL)
    limit, offset = parse_pagination(request.args)
    page, total = paginate(list(db.reits.values()), limit, offset)
    return success_list([reit_view(r) for r in page], limit, offset, total)


@bp.route("/reit-compliance/reits/<rid>/ep-balance", methods=["GET"])
def get_ep_balance(rid):
    require_roles(*ALL)
    reit = db.reits.get(rid)
    if reit is None:
        raise errors.not_found("REIT not found")
    as_of = request.args.get("as_of")
    if as_of:
        balance = calc_ep_balance(rid, as_of=as_of)
        variant = "frozen_year_end_view"
    else:
        balance = calc_ep_balance(rid)
        variant = "current_ep_view"
    return success_object({"ep_balance_cents": balance, "variant": variant})


@bp.route("/reit-compliance/reits/<rid>/dividend-characterization-preview", methods=["GET"])
def dividend_characterization_preview(rid):
    require_roles("ComplianceOfficer", "TaxDirector")
    reit = db.reits.get(rid)
    if reit is None:
        raise errors.not_found("REIT not found")

    raw_amount = request.args.get("amount_cents")
    raw_year = request.args.get("taxable_year")
    mode = request.args.get("mode") or "WATERFALL"
    if mode not in ("WATERFALL", "PRO_RATA"):
        raise errors.validation("mode must be WATERFALL or PRO_RATA")
    try:
        amount_cents = int(raw_amount)
    except (TypeError, ValueError):
        raise errors.validation("amount_cents is required and must be an integer")
    try:
        taxable_year = int(raw_year)
    except (TypeError, ValueError):
        raise errors.validation("taxable_year is required and must be an integer")

    requirement = next(
        (r for r in db.distribution_requirements.values()
         if r["reit_id"] == rid and r["taxable_year"] == taxable_year
         and r["status"] == "POSTED"),
        None,
    )
    if requirement is None:
        # Fall back to any requirement for the year (pool from its net_capital_gain)
        requirement = next(
            (r for r in db.distribution_requirements.values()
             if r["reit_id"] == rid and r["taxable_year"] == taxable_year),
            None,
        )
    cg_pool = (
        capital_gain_pool(rid, taxable_year, requirement)
        if requirement is not None else 0
    )
    ep_balance = reit["current_ep_balance_cents"]

    if mode == "PRO_RATA":
        result = calc_dividend_characterization_pro_rata(amount_cents, ep_balance, cg_pool)
    else:
        result = calc_dividend_characterization_waterfall(amount_cents, ep_balance, cg_pool)
    result["mode"] = mode
    return success_object(result)
