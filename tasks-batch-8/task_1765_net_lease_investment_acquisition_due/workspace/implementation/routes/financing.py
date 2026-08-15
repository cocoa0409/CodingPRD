"""Financing application routes (PRD §3.9)."""

from decimal import Decimal

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import bump, require_role
from response import created, ok, ok_list
from routes.common import body, req_enum, req_int
from services import domain

bp = Blueprint("financing", __name__)

READ_ROLES = ("AcquisitionsAnalyst", "UnderwritingCommittee", "CapitalMarketsOfficer",
              "EscrowOfficer", "PlatformAdmin")
LOAN_TYPES = {"NEW_LOAN", "ASSUMPTION"}


@bp.route("/acquisition-deals/deals/<deal_id>/financing-applications", methods=["POST"])
def create_financing(deal_id):
    require_role("CapitalMarketsOfficer")
    deal = domain.get_deal(deal_id)
    data = body()
    app = db.make_record({
        "deal_id": deal["id"],
        "loan_type": req_enum(data, "loan_type", LOAN_TYPES),
        "loan_amount_cents": req_int(data, "loan_amount_cents"),
        "interest_rate_bps": req_int(data, "interest_rate_bps"),
        "amortization_months": req_int(data, "amortization_months"),
        "annual_debt_service_cents": None,
        "dscr": None,
        "assumption_fee_cents": None,
        "committed_at": None,
        "status": "DRAFT",
    })
    db.stores["financing"][app["id"]] = app
    return created(db.pub(app))


@bp.route("/acquisition-deals/deals/<deal_id>/financing-applications", methods=["GET"])
def list_financing(deal_id):
    require_role(*READ_ROLES)
    deal = domain.get_deal(deal_id)
    items = domain.financing_of(deal["id"])
    for param in ("status", "loan_type"):
        v = request.args.get(param)
        if v is not None:
            items = [f for f in items if str(f.get(param)) == v]
    return ok_list(items)


@bp.route("/acquisition-deals/deals/<deal_id>/financing-applications/<app_id>", methods=["GET"])
def get_financing(deal_id, app_id):
    require_role(*READ_ROLES)
    deal = domain.get_deal(deal_id)
    return ok(db.pub(domain.get_financing_scoped(deal, app_id)))


@bp.route("/acquisition-deals/deals/<deal_id>/financing-applications/<app_id>/submit", methods=["POST"])
def submit_financing(deal_id, app_id):
    require_role("CapitalMarketsOfficer")
    deal = domain.get_deal(deal_id)
    app = domain.get_financing_scoped(deal, app_id)
    if app["status"] != "DRAFT":
        raise ApiError("ERR_FINANCING_INVALID_STATE",
                       "submit requires status DRAFT", 409)
    psa = domain.active_psa(deal["id"])
    if psa is not None and app["loan_amount_cents"] * 100 > domain.MAX_LTV_PCT * psa["psa_price_cents"]:
        raise ApiError("ERR_LTV_EXCEEDED",
                       "loan_amount_cents exceeds 65% of psa_price_cents", 422)
    # Dual-variant debt service + assumption fee, computed at submission.
    app["annual_debt_service_cents"] = domain.compute_annual_debt_service(
        app["loan_amount_cents"], app["interest_rate_bps"], app["amortization_months"])
    app["assumption_fee_cents"] = domain.compute_assumption_fee(
        app["loan_type"], app["loan_amount_cents"])
    app["status"] = "SUBMITTED"
    bump(app)
    return ok(db.pub(app))


@bp.route("/acquisition-deals/deals/<deal_id>/financing-applications/<app_id>/commit", methods=["POST"])
def commit_financing(deal_id, app_id):
    require_role("CapitalMarketsOfficer")
    deal = domain.get_deal(deal_id)
    app = domain.get_financing_scoped(deal, app_id)
    if app["status"] != "SUBMITTED":
        raise ApiError("ERR_FINANCING_INVALID_STATE",
                       "commit requires status SUBMITTED", 409)
    model = domain.latest_approved_model(deal["id"])
    noi = model["noi_cents"] if model else 0
    dscr = domain.compute_dscr(noi, app.get("annual_debt_service_cents"))
    if dscr is not None:
        app["dscr"] = float(dscr)
    if dscr is None or dscr < domain.MIN_DSCR:
        raise ApiError("ERR_DSCR_BELOW_MINIMUM",
                       "dscr must be at least 1.25 at commitment", 422)
    fc_end = deal.get("financing_contingency_end")
    if fc_end is not None and db.clock_now() > db.parse_dt(fc_end):
        raise ApiError("ERR_FINANCING_CONTINGENCY_LAPSED",
                       "Financing contingency window has lapsed", 422)
    app["committed_at"] = db.now_iso()
    app["status"] = "COMMITTED"
    bump(app)
    domain.satisfy_milestone(deal, "FINANCING_COMMITMENT")
    domain.recompute_posture(deal)
    return ok(db.pub(app))


@bp.route("/acquisition-deals/deals/<deal_id>/financing-applications/<app_id>/decline", methods=["POST"])
def decline_financing(deal_id, app_id):
    require_role("CapitalMarketsOfficer")
    deal = domain.get_deal(deal_id)
    app = domain.get_financing_scoped(deal, app_id)
    if app["status"] != "SUBMITTED":
        raise ApiError("ERR_FINANCING_INVALID_STATE",
                       "decline requires status SUBMITTED", 409)
    app["status"] = "DECLINED"
    bump(app)
    return ok(db.pub(app))


@bp.route("/acquisition-deals/deals/<deal_id>/financing-applications/<app_id>/withdraw", methods=["POST"])
def withdraw_financing(deal_id, app_id):
    require_role("CapitalMarketsOfficer")
    deal = domain.get_deal(deal_id)
    app = domain.get_financing_scoped(deal, app_id)
    if app["status"] not in ("DRAFT", "SUBMITTED"):
        raise ApiError("ERR_FINANCING_INVALID_STATE",
                       "withdraw requires status DRAFT or SUBMITTED", 409)
    app["status"] = "WITHDRAWN"
    bump(app)
    return ok(db.pub(app))
