"""Fund and ShareClass endpoints (PRD 3.1)."""
from flask import Blueprint

from db import db
from middleware import require_roles
from response import success_object, success_list
from services.core import (
    stamp_new, touch, serialize, paginate, filter_by, get_fund, child_of,
)
from validate import (
    get_body, req_str, req_int, req_number, req_bool, req_enum,
)

bp = Blueprint("funds", __name__)

READ_ALL = ("FundAdmin", "ComplianceOfficer", "TransferAgent", "PortfolioManager", "Investor")
REDEMPTION_FREQUENCIES = {"MONTHLY", "QUARTERLY", "SEMI_ANNUAL", "ANNUAL"}


# ---------------------------------------------------------------------------
# Fund
# ---------------------------------------------------------------------------


@bp.post("/funds")
def create_fund():
    require_roles("FundAdmin")
    body = get_body()
    fund = stamp_new({
        "fund_name": req_str(body, "fund_name"),
        "domicile": req_str(body, "domicile"),
        "gate_threshold_pct": req_number(body, "gate_threshold_pct"),
        "lockup_months_default": req_int(body, "lockup_months_default", minimum=0),
        "notice_days_default": req_int(body, "notice_days_default", minimum=0),
        "fiscal_year_end_month": req_int(body, "fiscal_year_end_month", minimum=1, maximum=12),
        "suspension_status": "NOT_SUSPENDED",
        "current_nav_period_id": None,
        "total_net_assets_cents": 0,
    })
    db["funds"][fund["id"]] = fund
    return success_object(serialize(fund), 201)


@bp.get("/funds")
def list_funds():
    require_roles(*READ_ALL)
    items, total, limit, offset = paginate(list(db["funds"].values()))
    return success_list(items, total, limit, offset)


@bp.get("/funds/<fund_id>")
def get_fund_route(fund_id):
    require_roles(*READ_ALL)
    return success_object(serialize(get_fund(fund_id)))


@bp.post("/funds/<fund_id>/suspend-redemptions")
def suspend_redemptions(fund_id):
    require_roles("FundAdmin")
    fund = get_fund(fund_id)
    fund["suspension_status"] = "SUSPENDED"
    touch(fund)
    return success_object(serialize(fund))


@bp.post("/funds/<fund_id>/resume-redemptions")
def resume_redemptions(fund_id):
    require_roles("FundAdmin")
    fund = get_fund(fund_id)
    fund["suspension_status"] = "NOT_SUSPENDED"
    touch(fund)
    return success_object(serialize(fund))


# ---------------------------------------------------------------------------
# ShareClass
# ---------------------------------------------------------------------------


@bp.post("/funds/<fund_id>/share-classes")
def create_share_class(fund_id):
    require_roles("FundAdmin")
    fund = get_fund(fund_id)
    body = get_body()
    share_class = stamp_new({
        "fund_id": fund["id"],
        "class_code": req_str(body, "class_code"),
        "min_initial_investment_cents": req_int(body, "min_initial_investment_cents", minimum=0),
        "min_additional_investment_cents": req_int(body, "min_additional_investment_cents", minimum=0),
        "management_fee_bps": req_int(body, "management_fee_bps", minimum=0),
        "performance_fee_bps": req_int(body, "performance_fee_bps", minimum=0),
        "hurdle_rate_bps": req_int(body, "hurdle_rate_bps", minimum=0),
        "high_water_mark_required": req_bool(body, "high_water_mark_required"),
        "lockup_months": req_int(body, "lockup_months", minimum=0),
        "notice_days": req_int(body, "notice_days", minimum=0),
        "redemption_frequency": req_enum(body, "redemption_frequency", REDEMPTION_FREQUENCIES),
        "is_open_for_subscription": True,
        "is_open_for_redemption": True,
    })
    db["share_classes"][share_class["id"]] = share_class
    return success_object(serialize(share_class), 201)


@bp.get("/funds/<fund_id>/share-classes")
def list_share_classes(fund_id):
    require_roles(*READ_ALL)
    fund = get_fund(fund_id)
    items, total, limit, offset = paginate(filter_by(
        db["share_classes"].values(), fund_id=fund["id"]))
    return success_list(items, total, limit, offset)


@bp.get("/funds/<fund_id>/share-classes/<class_id>")
def get_share_class_route(fund_id, class_id):
    require_roles(*READ_ALL)
    fund = get_fund(fund_id)
    from services.core import get_share_class
    share_class = get_share_class(class_id)
    child_of(share_class, "fund_id", fund["id"])
    return success_object(serialize(share_class))


@bp.post("/funds/<fund_id>/share-classes/<class_id>/close-subscription")
def close_subscription(fund_id, class_id):
    require_roles("FundAdmin")
    fund = get_fund(fund_id)
    from services.core import get_share_class
    share_class = get_share_class(class_id)
    child_of(share_class, "fund_id", fund["id"])
    share_class["is_open_for_subscription"] = False
    touch(share_class)
    return success_object(serialize(share_class))


@bp.post("/funds/<fund_id>/share-classes/<class_id>/close-redemption")
def close_redemption(fund_id, class_id):
    require_roles("FundAdmin")
    fund = get_fund(fund_id)
    from services.core import get_share_class
    share_class = get_share_class(class_id)
    child_of(share_class, "fund_id", fund["id"])
    share_class["is_open_for_redemption"] = False
    touch(share_class)
    return success_object(serialize(share_class))
