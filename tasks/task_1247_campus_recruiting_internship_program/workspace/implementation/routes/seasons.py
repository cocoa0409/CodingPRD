"""Seasons + logical clock + conversion summary."""

from flask import Blueprint, request

from db import db
from errors import (
    err_season_advance_blocked,
    err_season_close_blocked,
)
from middleware import require_auth
from response import success_object, success_list
from services.calculations import conversion_rate
from services.domain import (
    get_season,
    season_view,
    get_application,
)
from utils import (
    parse_pagination,
    parse_iso,
    require_int,
    require_string,
    require_timestamp,
    optional_int,
    optional_enum,
    stamp_new,
    touch,
    format_iso,
    now_utc,
    set_clock,
)

bp = Blueprint("seasons", __name__)

SEASON_STATUSES = {"DRAFT", "OPEN", "SELECTION", "OFFER_PERIOD", "INTERN_ACTIVE", "CLOSED"}
DEADLINE_MODES = {"WALL_CLOCK", "BUSINESS_HOURS"}


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_auth(["RecruitingAdmin"])
def set_current_utc():
    payload = request.get_json(silent=True) or {}
    to_iso = require_string(payload, "to_iso8601")
    dt = parse_iso(to_iso)
    set_clock(dt)
    return success_object({"current_utc": format_iso(dt)}, 200)


@bp.route("/seasons", methods=["POST"])
@require_auth(["RecruitingAdmin"])
def create_season():
    payload = request.get_json(silent=True) or {}
    name = require_string(payload, "name")
    application_open_at = require_timestamp(payload, "application_open_at")
    application_close_at = require_timestamp(payload, "application_close_at")
    interview_window_start_at = require_timestamp(payload, "interview_window_start_at")
    interview_window_end_at = require_timestamp(payload, "interview_window_end_at")
    offer_window_open_at = require_timestamp(payload, "offer_window_open_at")
    offer_window_close_at = require_timestamp(payload, "offer_window_close_at")
    shortlist_score_threshold = require_int(payload, "shortlist_score_threshold", min_value=0)
    if shortlist_score_threshold > 100:
        from errors import err_validation
        raise err_validation("shortlist_score_threshold must be 0..100")
    stipend_budget_cents = require_int(payload, "stipend_budget_cents", min_value=0)
    exploding_offer_hours_default = optional_int(payload, "exploding_offer_hours_default", default=72, min_value=1)
    deadline_policy_mode = optional_enum(payload, "deadline_policy_mode", DEADLINE_MODES, default="WALL_CLOCK")
    max_extension_hours = optional_int(payload, "max_extension_hours", default=72, min_value=1)

    s = {
        "name": name,
        "status": "DRAFT",
        "_application_open_at": application_open_at,
        "_application_close_at": application_close_at,
        "_interview_window_start_at": interview_window_start_at,
        "_interview_window_end_at": interview_window_end_at,
        "_offer_window_open_at": offer_window_open_at,
        "_offer_window_close_at": offer_window_close_at,
        "exploding_offer_hours_default": exploding_offer_hours_default,
        "deadline_policy_mode": deadline_policy_mode,
        "max_extension_hours": max_extension_hours,
        "shortlist_score_threshold": shortlist_score_threshold,
        "stipend_budget_cents": stipend_budget_cents,
        "stipend_reserved_cents": 0,
        "stipend_disbursed_cents": 0,
        "applications_total_count": 0,
        "offers_extended_count": 0,
        "offers_accepted_count": 0,
        "completed_assignments_count": 0,
        "return_offers_extended_count": 0,
        "return_offers_accepted_count": 0,
    }
    stamp_new(s)
    db.seasons[s["id"]] = s
    return success_object(season_view(s), 201)


@bp.route("/seasons", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter"])
def list_seasons():
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = [s for s in db.seasons.values() if (status is None or s["status"] == status)]
    items.sort(key=lambda s: s["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([season_view(s) for s in page], total, limit, offset)


@bp.route("/seasons/<sid>", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter"])
def get_one_season(sid):
    s = get_season(sid)
    return success_object(season_view(s))


@bp.route("/seasons/<sid>/advance", methods=["POST"])
@require_auth(["RecruitingAdmin"])
def advance_season(sid):
    s = get_season(sid)
    cur = s["status"]
    now = now_utc()
    if cur == "DRAFT":
        active_targets = [
            t for t in db.school_targets.values()
            if t["season_id"] == sid and t["status"] == "ACTIVE"
        ]
        if len(active_targets) < 1:
            raise err_season_advance_blocked("DRAFT->OPEN requires at least one ACTIVE school target")
        s["status"] = "OPEN"
    elif cur == "OPEN":
        if not (now > s["_application_close_at"]):
            raise err_season_advance_blocked("OPEN->SELECTION requires now > application_close_at")
        s["status"] = "SELECTION"
    elif cur == "SELECTION":
        submitted = [
            a for a in db.applications.values()
            if a["season_id"] == sid and a["status"] == "SUBMITTED"
        ]
        if submitted:
            raise err_season_advance_blocked("SELECTION->OFFER_PERIOD requires zero SUBMITTED applications")
        s["status"] = "OFFER_PERIOD"
    elif cur == "OFFER_PERIOD":
        # No Offer whose application's season is this season has status EXTENDED
        ext = [
            o for o in db.offers.values()
            if o["status"] == "EXTENDED"
            and get_application(o["application_id"])["season_id"] == sid
        ]
        if ext:
            raise err_season_advance_blocked("OFFER_PERIOD->INTERN_ACTIVE requires zero EXTENDED offers")
        s["status"] = "INTERN_ACTIVE"
    else:
        # INTERN_ACTIVE or CLOSED — advance not allowed here (close is separate)
        raise err_season_advance_blocked(f"Cannot advance season from {cur}")
    touch(s)
    return success_object(season_view(s))


@bp.route("/seasons/<sid>/close", methods=["POST"])
@require_auth(["RecruitingAdmin"])
def close_season(sid):
    s = get_season(sid)
    # Gate: zero ACTIVE ProjectAssignments in the season
    active_assignments = [
        a for a in db.project_assignments.values()
        if a["status"] == "ACTIVE"
        and get_application(a["application_id"])["season_id"] == sid
    ]
    if active_assignments:
        raise err_season_close_blocked()
    # Posture: must be INTERN_ACTIVE -> CLOSED
    if s["status"] != "INTERN_ACTIVE":
        # closing from non-INTERN_ACTIVE has no defined transition; treat as blocked
        raise err_season_close_blocked(f"Season status {s['status']} cannot close")
    # Cascades:
    # L1: EXTENDED offers (in this season) -> EXPIRED
    for o in db.offers.values():
        if o["status"] != "EXTENDED":
            continue
        app = get_application(o["application_id"])
        if app["season_id"] != sid:
            continue
        o["status"] = "EXPIRED"
        touch(o)
        if app["status"] == "OFFER_PENDING":
            app["status"] = "EXPIRED"
            touch(app)
    # L1: RESERVED disbursements of this season -> RELEASED
    for d in db.stipend_disbursements.values():
        if d["status"] != "RESERVED":
            continue
        offer = db.offers.get(d["offer_id"])
        if offer is None:
            continue
        app = get_application(offer["application_id"])
        if app["season_id"] != sid:
            continue
        d["status"] = "RELEASED"
        touch(d)
        s["stipend_reserved_cents"] -= d["amount_cents"]
    s["status"] = "CLOSED"
    touch(s)
    return success_object(season_view(s))


@bp.route("/seasons/<sid>/conversion-summary", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter"])
def conversion_summary(sid):
    s = get_season(sid)
    ro_acc = s["return_offers_accepted_count"]
    off_acc = s["offers_accepted_count"]
    comp_assign = s["completed_assignments_count"]
    body = {
        "applications_total_count": s["applications_total_count"],
        "offers_extended_count": s["offers_extended_count"],
        "offers_accepted_count": off_acc,
        "completed_assignments_count": comp_assign,
        "return_offers_extended_count": s["return_offers_extended_count"],
        "return_offers_accepted_count": ro_acc,
        "stipend_budget_cents": s["stipend_budget_cents"],
        "stipend_reserved_cents": s["stipend_reserved_cents"],
        "stipend_disbursed_cents": s["stipend_disbursed_cents"],
        "conversion_rate_provisional": conversion_rate(ro_acc, off_acc),
        "conversion_rate_final": conversion_rate(ro_acc, comp_assign),
    }
    return success_object(body)
