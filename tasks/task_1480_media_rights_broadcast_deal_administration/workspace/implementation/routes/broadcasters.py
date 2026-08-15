import db
from errors import raise_error
from flask import Blueprint, request
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from serializers import serialize
from services.system import (bid_terminal_statuses, deal_terminal_statuses,
                             milestone_active_statuses, suspend_broadcaster_with_consequences)
from util import (apply_filters, get_json_body, get_pagination, paginate,
                  req_enum, req_list, req_string, sorted_by_created, stamp_new, touch)
from services import calculations as calc

bp = Blueprint("broadcasters", __name__)

PLATFORM_CLASSES = {"LINEAR_TV", "SVOD", "AVOD", "MOBILE", "RADIO", "SOCIAL_CLIP"}
CREDIT_RATINGS = {"INVESTMENT_GRADE", "SPECULATIVE", "UNRATED"}


def get_broadcaster_or_404(broadcaster_id):
    b = db.broadcasters.get(broadcaster_id)
    if b is None:
        raise_error("ERR_BROADCASTER_NOT_FOUND")
    return b


@bp.route("/broadcasters", methods=["POST"])
def create_broadcaster():
    require_roles({"RightsManager"})
    body = get_json_body()
    legal_name = req_string(body, "legal_name")
    home_territory = req_string(body, "home_territory")
    platform_classes = req_list(body, "platform_classes")
    for pc in platform_classes:
        if pc not in PLATFORM_CLASSES:
            raise_error("ERR_INVALID_REQUEST", f"platform_classes entries must be drawn from {sorted(PLATFORM_CLASSES)}")
    credit_rating = req_enum(body, "credit_rating", CREDIT_RATINGS)
    broadcaster = {
        "legal_name": legal_name,
        "home_territory": home_territory,
        "platform_classes": platform_classes,
        "credit_rating": credit_rating,
        "status": "REGISTERED",
    }
    stamp_new(broadcaster)
    db.broadcasters[broadcaster["id"]] = broadcaster
    return success_object(serialize(broadcaster), status_code=201)


@bp.route("/broadcasters", methods=["GET"])
def list_broadcasters():
    require_roles(ALL_ROLES)
    limit, offset = get_pagination()
    items = sorted_by_created(list(db.broadcasters.values()))
    items = apply_filters(items, [
        ("status", request.args.get("status")),
        ("credit_rating", request.args.get("credit_rating")),
    ])
    page, total = paginate(items, limit, offset)
    return success_list([serialize(b) for b in page], limit, offset, total)


@bp.route("/broadcasters/<broadcasterId>", methods=["GET"])
def get_broadcaster(broadcasterId):
    require_roles(ALL_ROLES)
    return success_object(serialize(get_broadcaster_or_404(broadcasterId)))


@bp.route("/broadcasters/<broadcasterId>/accredit", methods=["POST"])
def accredit_broadcaster(broadcasterId):
    require_roles({"RightsManager"})
    b = get_broadcaster_or_404(broadcasterId)
    if b["status"] != "REGISTERED":
        raise_error("ERR_BROADCASTER_NOT_REGISTERED")
    if b["credit_rating"] == "UNRATED":
        raise_error("ERR_BROADCASTER_UNRATED")
    b["status"] = "ACCREDITED"
    touch(b)
    return success_object(serialize(b))


@bp.route("/broadcasters/<broadcasterId>/suspend", methods=["POST"])
def suspend_broadcaster(broadcasterId):
    require_roles({"ComplianceOfficer"})
    b = get_broadcaster_or_404(broadcasterId)
    if b["status"] != "ACCREDITED":
        raise_error("ERR_BROADCASTER_NOT_ACCREDITED")
    suspend_broadcaster_with_consequences(b)
    return success_object(serialize(b))


@bp.route("/broadcasters/<broadcasterId>/reinstate", methods=["POST"])
def reinstate_broadcaster(broadcasterId):
    require_roles({"ComplianceOfficer"})
    b = get_broadcaster_or_404(broadcasterId)
    if b["status"] != "SUSPENDED":
        raise_error("ERR_BROADCASTER_NOT_SUSPENDED")
    b["status"] = "ACCREDITED"
    touch(b)
    return success_object(serialize(b))


@bp.route("/broadcasters/<broadcasterId>/bar", methods=["POST"])
def bar_broadcaster(broadcasterId):
    require_roles({"ComplianceOfficer"})
    b = get_broadcaster_or_404(broadcasterId)
    if b["status"] != "SUSPENDED":
        raise_error("ERR_BROADCASTER_NOT_SUSPENDED")
    has_breach_deal = any(
        d["broadcaster_id"] == b["id"] and d["status"] == "TERMINATED_BREACH"
        for d in db.deals.values()
    )
    if not has_breach_deal:
        raise_error("ERR_NO_BREACH_DEAL")
    # Cascade: all non-terminal deals with this broadcaster → TERMINATED_BREACH,
    # posture → FROZEN, outstanding milestones → DEFAULTED.
    for deal in db.deals.values():
        if deal["broadcaster_id"] != b["id"] or deal["status"] in deal_terminal_statuses():
            continue
        deal["status"] = "TERMINATED_BREACH"
        touch(deal)
        for m in db.payment_milestones.values():
            if m["deal_id"] == deal["id"] and m["status"] in milestone_active_statuses():
                if m["status"] == "OVERDUE":
                    deal["payment_delinquency_count"] = max(0, deal.get("payment_delinquency_count", 0) - 1)
                m["status"] = "DEFAULTED"
                touch(m)
        deal["posture"] = "FROZEN"
        touch(deal)
    b["status"] = "BARRED"
    touch(b)
    return success_object(serialize(b))
