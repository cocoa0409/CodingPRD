import db
from errors import raise_error
from flask import Blueprint, request
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from serializers import serialize
from services import calculations as calc
from services.clock import parse_iso
from util import (apply_filters, get_json_body, get_pagination, opt_number,
                  paginate, req_datetime, req_enum, req_int, req_string,
                  sorted_by_created, stamp_new, touch)

bp = Blueprint("sublicense", __name__)

PLATFORM_CLASSES = {"LINEAR_TV", "SVOD", "AVOD", "MOBILE", "RADIO", "SOCIAL_CLIP"}


def _get_deal_or_404(deal_id):
    d = db.deals.get(deal_id)
    if d is None:
        raise_error("ERR_DEAL_NOT_FOUND")
    return d


def _get_request_scoped(deal_id, request_id):
    _get_deal_or_404(deal_id)
    s = db.sublicense_requests.get(request_id)
    if s is None or s["deal_id"] != deal_id:
        raise_error("ERR_SUBLICENSE_NOT_FOUND")
    return s


def _blackout_covers(s, b):
    return (
        s["sublicensee_territory"] == b["territory_code"]
        and s["sublicensee_platform_class"] == b["platform_class"]
        and calc.sublicense_intersects_blackout(
            s["requested_window_start"], s["requested_window_end"],
            b["blackout_start"], b["blackout_end"],
        )
    )


@bp.route("/deals/<dealId>/sublicense-requests", methods=["POST"])
def create_sublicense(dealId):
    require_roles({"BidCoordinator"})
    _get_deal_or_404(dealId)
    body = get_json_body()
    sublicensee_name = req_string(body, "sublicensee_name")
    sublicensee_territory = req_string(body, "sublicensee_territory")
    sublicensee_platform_class = req_enum(body, "sublicensee_platform_class", PLATFORM_CLASSES)
    window_start = req_datetime(body, "requested_window_start", parse_iso)
    window_end = req_datetime(body, "requested_window_end", parse_iso)
    if window_end <= window_start:
        raise_error("ERR_INVALID_REQUEST", "requested_window_end must be strictly later than requested_window_start")
    proposed_fee_cents = req_int(body, "proposed_fee_cents", minimum=0)
    league_share_pct = opt_number(body, "league_share_pct", default=0.15)
    if not (0.0 <= league_share_pct <= 0.5):
        raise_error("ERR_INVALID_REQUEST", "league_share_pct must be within [0.0, 0.5]")
    s = {
        "deal_id": dealId,
        "sublicensee_name": sublicensee_name,
        "sublicensee_territory": sublicensee_territory,
        "sublicensee_platform_class": sublicensee_platform_class,
        "requested_window_start": window_start,
        "requested_window_end": window_end,
        "proposed_fee_cents": proposed_fee_cents,
        "league_share_pct": league_share_pct,
        "status": "PENDING",
        "revoked_reason": None,
    }
    stamp_new(s)
    db.sublicense_requests[s["id"]] = s
    return success_object(serialize(s), status_code=201)


@bp.route("/deals/<dealId>/sublicense-requests", methods=["GET"])
def list_sublicenses(dealId):
    require_roles(ALL_ROLES)
    _get_deal_or_404(dealId)
    limit, offset = get_pagination()
    items = [s for s in db.sublicense_requests.values() if s["deal_id"] == dealId]
    items = sorted_by_created(items)
    items = apply_filters(items, [
        ("status", request.args.get("status")),
        ("sublicensee_territory", request.args.get("sublicensee_territory")),
        ("deal_id", request.args.get("deal_id")),
    ])
    page, total = paginate(items, limit, offset)
    return success_list([serialize(s) for s in page], limit, offset, total)


@bp.route("/deals/<dealId>/sublicense-requests/<requestId>", methods=["GET"])
def get_sublicense(dealId, requestId):
    require_roles(ALL_ROLES)
    return success_object(serialize(_get_request_scoped(dealId, requestId)))


@bp.route("/sublicense-requests", methods=["GET"])
def list_sublicenses_flat():
    require_roles(ALL_ROLES)
    limit, offset = get_pagination()
    items = sorted_by_created(list(db.sublicense_requests.values()))
    items = apply_filters(items, [
        ("deal_id", request.args.get("deal_id")),
        ("status", request.args.get("status")),
        ("sublicensee_territory", request.args.get("sublicensee_territory")),
    ])
    page, total = paginate(items, limit, offset)
    return success_list([serialize(s) for s in page], limit, offset, total)


@bp.route("/sublicense-requests/<requestId>", methods=["GET"])
def get_sublicense_flat(requestId):
    require_roles(ALL_ROLES)
    s = db.sublicense_requests.get(requestId)
    if s is None:
        raise_error("ERR_SUBLICENSE_NOT_FOUND")
    return success_object(serialize(s))


@bp.route("/deals/<dealId>/sublicense-requests/<requestId>/approve", methods=["POST"])
def approve_sublicense(dealId, requestId):
    require_roles({"RightsManager"})
    s = _get_request_scoped(dealId, requestId)
    deal = db.deals[dealId]
    if s["status"] != "PENDING":
        raise_error("ERR_INVALID_REQUEST", "Approve requires sublicense PENDING")
    if deal["status"] != "ACTIVE":
        raise_error("ERR_DEAL_NOT_ACTIVE")
    if deal.get("posture") == "FROZEN":
        raise_error("ERR_DEAL_FROZEN")
    # Business order: blackout → window-subset → overlap.
    for b in db.blackout_windows.values():
        if b["asset_id"] == deal["asset_id"] and _blackout_covers(s, b):
            raise_error("ERR_BLACKOUT_VIOLATION")
    package = db.packages.get(deal["package_id"])
    if package is not None:
        if not (package["window_start"] <= s["requested_window_start"]
                and s["requested_window_end"] <= package["window_end"]):
            raise_error("ERR_SUBLICENSE_WINDOW_OUTSIDE_PACKAGE")
    for other in db.sublicense_requests.values():
        if other["id"] == s["id"] or other["deal_id"] != dealId or other["status"] != "APPROVED":
            continue
        if (other["sublicensee_territory"] == s["sublicensee_territory"]
                and other["sublicensee_platform_class"] == s["sublicensee_platform_class"]
                and calc.half_open_overlap(
                    other["requested_window_start"], other["requested_window_end"],
                    s["requested_window_start"], s["requested_window_end"])):
            raise_error("ERR_SUBLICENSE_OVERLAP")
    s["status"] = "APPROVED"
    touch(s)
    return success_object(serialize(s))


@bp.route("/deals/<dealId>/sublicense-requests/<requestId>/reject", methods=["POST"])
def reject_sublicense(dealId, requestId):
    require_roles({"RightsManager"})
    s = _get_request_scoped(dealId, requestId)
    if s["status"] != "PENDING":
        raise_error("ERR_INVALID_REQUEST", "Reject requires sublicense PENDING")
    s["status"] = "REJECTED"
    touch(s)
    return success_object(serialize(s))


@bp.route("/deals/<dealId>/sublicense-requests/<requestId>/revoke", methods=["POST"])
def revoke_sublicense(dealId, requestId):
    require_roles({"ComplianceOfficer"})
    s = _get_request_scoped(dealId, requestId)
    deal = db.deals[dealId]
    body = get_json_body() if request.is_json or request.content_length else {}
    reason = body.get("reason") if isinstance(body, dict) else None
    if s["status"] != "APPROVED":
        raise_error("ERR_INVALID_REQUEST", "Revoke requires sublicense APPROVED")
    deal_terminated = deal["status"] in ("TERMINATED_BREACH", "TERMINATED_CONVENIENCE")
    covering_blackout = None
    for b in db.blackout_windows.values():
        if b["asset_id"] == deal["asset_id"] and _blackout_covers(s, b):
            covering_blackout = b
            break
    if not deal_terminated and covering_blackout is None:
        raise_error("ERR_REVOKE_CONDITION_NOT_MET")
    s["status"] = "REVOKED"
    s["revoked_reason"] = reason if isinstance(reason, str) and reason else ("TERMINATION" if deal_terminated else "BLACKOUT")
    touch(s)
    if covering_blackout is not None and not deal_terminated:
        calc.write_conflict(
            deal["asset_id"], "BLACKOUT_VIOLATION",
            "SUBLICENSE_REQUEST", s["id"],
            "BLACKOUT_WINDOW", covering_blackout["id"],
            f"Sublicense {s['id']} revoked: blackout window covers territory "
            f"{s['sublicensee_territory']} platform {s['sublicensee_platform_class']}.",
        )
    return success_object(serialize(s))


# --- Blackout windows ---------------------------------------------------------

@bp.route("/blackout-windows", methods=["POST"])
def create_blackout():
    require_roles({"ComplianceOfficer"})
    body = get_json_body()
    asset_id = body.get("asset_id")
    if not isinstance(asset_id, str) or asset_id not in db.rights_assets:
        raise_error("ERR_ASSET_NOT_FOUND")
    territory_code = req_string(body, "territory_code")
    platform_class = req_enum(body, "platform_class", PLATFORM_CLASSES)
    blackout_start = req_datetime(body, "blackout_start", parse_iso)
    blackout_end = req_datetime(body, "blackout_end", parse_iso)
    if blackout_end < blackout_start:
        raise_error("ERR_INVALID_REQUEST", "blackout_end must be >= blackout_start")
    from util import opt_bool
    applies_to_sublicense_only = opt_bool(body, "applies_to_sublicense_only", default=False)
    reason = req_string(body, "reason")
    b = {
        "asset_id": asset_id,
        "territory_code": territory_code,
        "platform_class": platform_class,
        "blackout_start": blackout_start,
        "blackout_end": blackout_end,
        "applies_to_sublicense_only": applies_to_sublicense_only,
        "reason": reason,
    }
    stamp_new(b)
    db.blackout_windows[b["id"]] = b
    return success_object(serialize(b), status_code=201)


@bp.route("/blackout-windows", methods=["GET"])
def list_blackouts():
    require_roles(ALL_ROLES)
    limit, offset = get_pagination()
    items = sorted_by_created(list(db.blackout_windows.values()))
    items = apply_filters(items, [
        ("asset_id", request.args.get("asset_id")),
        ("territory_code", request.args.get("territory_code")),
        ("platform_class", request.args.get("platform_class")),
    ])
    page, total = paginate(items, limit, offset)
    return success_list([serialize(b) for b in page], limit, offset, total)


@bp.route("/blackout-windows/<windowId>", methods=["GET"])
def get_blackout(windowId):
    require_roles(ALL_ROLES)
    b = db.blackout_windows.get(windowId)
    if b is None:
        raise_error("ERR_BLACKOUT_NOT_FOUND")
    return success_object(serialize(b))
