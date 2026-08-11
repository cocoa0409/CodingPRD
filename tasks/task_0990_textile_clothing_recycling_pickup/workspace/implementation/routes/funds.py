"""SponsorFund endpoints."""
from flask import Blueprint

from db import store, new_record, touch
from errors import fail
from middleware import endpoint
from response import success
from services import domain
from util import check_fields, get_body, paginate

bp = Blueprint("funds", __name__)


@bp.route("/sponsor-funds", methods=["POST"])
@endpoint(["ZoneOperator"])
def create_fund(user_id, role):
    body = get_body()
    check_fields(body, {
        "zone_id": ("str", True),
        "sponsor_name": ("str", True),
        "initial_cents": ("int", True),
    })
    if body["initial_cents"] <= 0:
        fail("ERR_INVALID_REQUEST", "initial_cents must be > 0")
    if body["zone_id"] not in store.zones:
        fail("ERR_NOT_FOUND", "ServiceZone not found: %s" % body["zone_id"])
    # p9f: at most one ACTIVE fund per zone
    if domain.active_fund_for_zone(body["zone_id"]) is not None:
        fail("ERR_FUND_ALREADY_ACTIVE", "Zone already has an ACTIVE sponsor fund")
    rec = new_record()
    rec.update({
        "zone_id": body["zone_id"],
        "sponsor_name": body["sponsor_name"],
        "initial_cents": body["initial_cents"],
        "funded_total_cents": body["initial_cents"],
        "status": "ACTIVE",
    })
    store.funds[rec["id"]] = rec
    return success(domain.fund_view(rec), code=201)


@bp.route("/sponsor-funds/<fid>", methods=["GET"])
@endpoint(["ZoneOperator", "SponsorManager"])
def get_fund(user_id, role, fid):
    if role == "SponsorManager" and user_id != fid:
        fail("ERR_UNAUTHORIZED", "SponsorManagers may only read their own fund")
    fund = domain.get_or_404(store.funds, fid, "SponsorFund")
    return success(domain.fund_view(fund))


@bp.route("/sponsor-funds/<fid>/topups", methods=["POST"])
@endpoint(["SponsorManager"])
def topup_fund(user_id, role, fid):
    if user_id != fid:
        fail("ERR_UNAUTHORIZED", "SponsorManagers may only top up their own fund")
    fund = store.funds.get(fid)
    body = get_body()
    check_fields(body, {"amount_cents": ("int", True)})
    if body["amount_cents"] <= 0:
        fail("ERR_INVALID_REQUEST", "amount_cents must be > 0")
    if fund is None:
        fail("ERR_NOT_FOUND", "SponsorFund not found: %s" % fid)
    if fund["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "Fund must be ACTIVE to top up")
    fund["funded_total_cents"] += body["amount_cents"]
    touch(fund)
    return success(domain.fund_view(fund))


@bp.route("/sponsor-funds/<fid>/close", methods=["POST"])
@endpoint(["ZoneOperator"])
def close_fund(user_id, role, fid):
    fund = store.funds.get(fid)
    get_body()
    if fund is None:
        fail("ERR_NOT_FOUND", "SponsorFund not found: %s" % fid)
    if fund["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "Fund must be ACTIVE to close")
    held, _ = domain.fund_amounts(fid)
    if held != 0:
        fail("ERR_INVALID_STATE", "Open holds block fund close")
    fund["status"] = "CLOSED"
    touch(fund)
    return success(domain.fund_view(fund))


@bp.route("/sponsor-funds/<fid>/diversion-credits", methods=["GET"])
@endpoint(["ZoneOperator", "SponsorManager"])
def list_fund_credits(user_id, role, fid):
    if role == "SponsorManager" and user_id != fid:
        fail("ERR_UNAUTHORIZED", "SponsorManagers may only read their own fund's credits")
    domain.get_or_404(store.funds, fid, "SponsorFund")
    items = [c for c in store.credits.values() if c.get("fund_id") == fid]
    page, meta = paginate(items)
    return success([domain.credit_view(c) for c in page], response_type="array",
                   pagination=meta)
