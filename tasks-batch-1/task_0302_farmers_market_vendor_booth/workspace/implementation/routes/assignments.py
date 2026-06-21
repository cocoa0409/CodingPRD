"""BoothAssignment routes (§3.3): create (reserve/waitlist), activate,
complete, cancel, promote."""
from flask import Blueprint, request

from common import init_common, touch, require_fields, req_str, req_enum, req_int, paginate
from db import db
from errors import err
from middleware import get_auth, require_role, get_json_body
from response import success
from routes.helpers import get_or_404, fk_or_404
from serializers import view, view_list
from services import assignment as svc
from services import derived

bp = Blueprint("assignments", __name__)

ASSIGNMENT_TYPES = {"SEASON", "DAILY"}


def _approved_category(vendor_id):
    cats = [a["product_category"] for a in db.applications.values()
            if a["vendor_id"] == vendor_id and a["status"] == "APPROVED"]
    return cats


@bp.route("/booth-assignments", methods=["POST"])
def create_assignment():
    user_id, role = get_auth()
    require_role(role, {"MarketAdmin", "Vendor"})
    body = get_json_body()

    # ----- priority 4: structural validation -----
    require_fields(body, ["market_id", "booth_id", "vendor_id", "assignment_type"])
    market_id = req_str(body, "market_id")
    booth_id = req_str(body, "booth_id")
    vendor_id = req_str(body, "vendor_id")
    assignment_type = req_enum(body, "assignment_type", ASSIGNMENT_TYPES)
    market_day_id = body.get("market_day_id")
    if market_day_id is not None and not isinstance(market_day_id, str):
        raise err("ERR_INVALID_REQUEST", "market_day_id must be a string")
    allow_waitlist = body.get("allow_waitlist", True)
    if not isinstance(allow_waitlist, bool):
        raise err("ERR_INVALID_REQUEST", "allow_waitlist must be a boolean")
    expected_booth_version = body.get("expected_booth_version")
    if expected_booth_version is not None and (
            isinstance(expected_booth_version, bool) or not isinstance(expected_booth_version, int)):
        raise err("ERR_INVALID_REQUEST", "expected_booth_version must be an integer")

    # ----- priority 2 (ownership): Vendor must act on own vendor_id -----
    if role == "Vendor" and vendor_id != user_id:
        raise err("ERR_FORBIDDEN_ROLE", "Vendor may only request its own assignment")

    # ----- priority 3: existence of body FKs -----
    market = fk_or_404("market", market_id)
    booth = fk_or_404("booth", booth_id)
    vendor = fk_or_404("vendor", vendor_id)
    if booth["market_id"] != market_id or vendor["market_id"] != market_id:
        raise err("ERR_NOT_FOUND", "booth/vendor not in market scope")
    md = None
    if market_day_id is not None:
        md = fk_or_404("market_day", market_day_id)
        if md["market_id"] != market_id:
            raise err("ERR_NOT_FOUND", "market_day not in market scope")

    # ----- priority 5: referential — DAILY needs market_day_id, SEASON omits -----
    if assignment_type == "DAILY" and market_day_id is None:
        raise err("ERR_REFERENTIAL_MISMATCH", "DAILY assignment requires market_day_id")
    if assignment_type == "SEASON" and market_day_id is not None:
        raise err("ERR_REFERENTIAL_MISMATCH", "SEASON assignment must omit market_day_id")
    # SEASON requires expected_booth_version (§2.8) — treated as structural here.
    if assignment_type == "SEASON" and expected_booth_version is None:
        raise err("ERR_INVALID_REQUEST", "expected_booth_version required for SEASON")

    # ----- priority 7: temporal — DAILY day must be SCHEDULED or OPEN -----
    if assignment_type == "DAILY":
        if md["status"] not in ("SCHEDULED", "OPEN"):
            raise err("ERR_OUTSIDE_WINDOW", "DAILY market day must be SCHEDULED or OPEN")

    # ----- priority 8: permit/category gates require the vendor's APPROVED app -----
    # Vendor must be ACTIVE first (state precondition for the transition).
    if vendor["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Vendor is not ACTIVE")

    # permit gate evaluated against the assignment window date
    window_date = (market["season_start_date"] if assignment_type == "SEASON"
                   else md["market_date"])
    if not derived.vendor_permit_ok_for_date(vendor, window_date):
        raise err("ERR_PERMIT_NOT_VERIFIED", "Vendor permit not verified for window")

    # ----- priority 9: category gate -----
    cats = _approved_category(vendor_id)
    if booth["allowed_categories"]:
        if not any(c in booth["allowed_categories"] for c in cats):
            raise err("ERR_CATEGORY_NOT_ALLOWED", "Vendor category not allowed at booth")

    # build the REQUESTED assignment row
    asg = {
        "market_id": market_id,
        "booth_id": booth_id,
        "vendor_id": vendor_id,
        "assignment_type": assignment_type,
        "market_day_id": market_day_id,
        "status": "REQUESTED",
        "waitlist_rank": None,
        "fee_charged_cents": 0,
        "fee_refunded_cents": 0,
    }
    init_common(asg)

    free = svc.slot_free(asg, booth)

    # ----- priority 10: booth-occupancy hard rejection (allow_waitlist=false) -----
    if not free and not allow_waitlist:
        raise err("ERR_BOOTH_OCCUPIED", "Booth occupied and waitlist disabled")

    # ----- priority 12: OCC for SEASON (stale-version) -----
    # Evaluated after the occupancy rejection (§2.11). For SEASON the client must
    # supply expected_booth_version matching the booth's current version.
    if assignment_type == "SEASON" and expected_booth_version != booth["version"]:
        raise err("ERR_STALE_BOOTH_VERSION", "expected_booth_version does not match")

    if free:
        db.booth_assignments[asg["id"]] = asg
        # bump_assignment_version False on first reserve so version stays 1
        # (REQUESTED->RESERVED is synchronous within create; the row is new).
        svc.do_reserve(asg, market, booth, bump_assignment_version=False)
    else:
        # occupied -> waitlist
        db.booth_assignments[asg["id"]] = asg
        asg["status"] = "WAITLISTED"
        svc.assign_waitlist_rank(asg)
    return success(view(asg), 201)


@bp.route("/booth-assignments/<assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    _, role = get_auth()
    require_role(role, {"MarketAdmin", "MarketManager", "Vendor"})
    a = get_or_404("booth_assignment", assignment_id)
    return success(view(a), 200)


@bp.route("/booth-assignments", methods=["GET"])
def list_assignments():
    _, role = get_auth()
    require_role(role, {"MarketAdmin", "MarketManager", "Vendor"})
    items = list(db.booth_assignments.values())
    for key in ("market_id", "booth_id", "vendor_id", "market_day_id",
                "status", "assignment_type"):
        val = request.args.get(key)
        if val is not None:
            items = [a for a in items if a.get(key) == val]
    page, meta = paginate(items)
    return success(view_list(page), 200, is_list=True, pagination=meta)


@bp.route("/booth-assignments/<assignment_id>/activate", methods=["POST"])
def activate_assignment(assignment_id):
    _, role = get_auth()
    require_role(role, {"MarketAdmin"})
    asg = get_or_404("booth_assignment", assignment_id)
    if asg["status"] != "RESERVED":
        raise err("ERR_INVALID_STATE", "Assignment is not RESERVED")
    # DAILY: market day must be OPEN (not CANCELLED/CLOSED) (§3.3)
    if asg["assignment_type"] == "DAILY":
        md = db.market_days.get(asg["market_day_id"])
        if md is None or md["status"] != "OPEN":
            raise err("ERR_OUTSIDE_WINDOW", "DAILY market day must be OPEN to activate")
    asg["status"] = "ACTIVE"
    touch(asg)
    return success(view(asg), 200)


@bp.route("/booth-assignments/<assignment_id>/complete", methods=["POST"])
def complete_assignment(assignment_id):
    _, role = get_auth()
    require_role(role, {"MarketAdmin"})
    asg = get_or_404("booth_assignment", assignment_id)
    if asg["status"] not in ("RESERVED", "ACTIVE"):
        raise err("ERR_INVALID_STATE", "Assignment is not RESERVED/ACTIVE")
    svc.do_complete(asg)
    return success(view(asg), 200)


@bp.route("/booth-assignments/<assignment_id>/cancel", methods=["POST"])
def cancel_assignment(assignment_id):
    user_id, role = get_auth()
    require_role(role, {"MarketAdmin", "Vendor"})
    asg = get_or_404("booth_assignment", assignment_id)
    if role == "Vendor" and asg["vendor_id"] != user_id:
        raise err("ERR_FORBIDDEN_ROLE", "Vendor does not own this assignment")
    if asg["status"] not in ("REQUESTED", "WAITLISTED", "RESERVED", "ACTIVE"):
        raise err("ERR_INVALID_STATE", "Assignment cannot be cancelled from its state")
    svc.do_cancel(asg, weather=False)
    return success(view(asg), 200)


@bp.route("/booth-assignments/<assignment_id>/promote", methods=["POST"])
def promote_assignment(assignment_id):
    _, role = get_auth()
    require_role(role, {"MarketAdmin"})
    asg = get_or_404("booth_assignment", assignment_id)
    if asg["status"] != "WAITLISTED":
        raise err("ERR_INVALID_STATE", "Assignment is not WAITLISTED")
    market = db.markets[asg["market_id"]]
    booth = db.booths[asg["booth_id"]]
    # rank-1 and slot free (§3.3 -> ERR_WAITLIST_NOT_HEAD)
    if asg["waitlist_rank"] != 1 or not svc.slot_free(asg, booth):
        raise err("ERR_WAITLIST_NOT_HEAD", "Not the head of the waitlist or slot occupied")
    # permit still OK at promotion time
    window_date = svc._window_date(asg, market)
    if not derived.vendor_permit_ok_for_date(db.vendors[asg["vendor_id"]], window_date):
        raise err("ERR_PERMIT_NOT_VERIFIED", "Vendor permit not verified at promotion")
    svc.do_reserve(asg, market, booth)
    svc.rerank_waitlist(asg)
    return success(view(asg), 200)
