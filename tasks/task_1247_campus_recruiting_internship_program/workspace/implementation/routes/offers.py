"""Offer routes: create, revise (OCC), extend, accept, decline, rescind, expire, extend-deadline."""

from datetime import timedelta

from flask import Blueprint, request, g

from db import db
from errors import (
    err_validation,
    err_forbidden,
    err_season_posture_forbidden,
    err_application_state_forbidden,
    err_offer_state_forbidden,
    err_offer_already_exists,
    err_offer_window_closed,
    err_offer_expired,
    err_offer_not_yet_expired,
    err_extension_cap_exceeded,
    err_stale_offer_version,
    err_stipend_budget_exceeded,
)
from middleware import require_auth
from response import success_object, success_list
from services.calculations import (
    exploding_deadline,
    stipend_amount,
    offer_total_comp,
)
from services.domain import (
    get_season,
    get_application,
    get_school_target,
    get_offer,
    offer_view,
    maybe_lazy_expire_offer,
    offer_season,
)
from utils import (
    parse_pagination,
    require_field,
    require_int,
    optional_int,
    stamp_new,
    touch,
    new_id,
    format_iso,
    now_utc,
)

bp = Blueprint("offers", __name__)


def _find_offer_by_application(aid):
    for o in db.offers.values():
        if o["application_id"] == aid:
            return o
    return None


@bp.route("/applications/<aid>/offers", methods=["POST"])
@require_auth(["Recruiter"])
def create_offer(aid):
    application = get_application(aid)
    season = get_season(application["season_id"])
    payload = request.get_json(silent=True) or {}
    weekly_rate_cents = require_int(payload, "weekly_rate_cents", min_value=1)
    duration_weeks = require_int(payload, "duration_weeks", min_value=1)
    sign_on_bonus_cents = optional_int(payload, "sign_on_bonus_cents", default=0, min_value=0)
    # Posture
    if season["status"] not in ("SELECTION", "OFFER_PERIOD"):
        raise err_season_posture_forbidden()
    # Application state
    if application["status"] != "DECISION_PENDING":
        raise err_application_state_forbidden("offer creation requires DECISION_PENDING")
    # Uniqueness: at most one offer per application
    if _find_offer_by_application(aid) is not None:
        raise err_offer_already_exists()
    school = get_school_target(application["school_target_id"])
    total_comp = offer_total_comp(
        weekly_rate_cents, duration_weeks, sign_on_bonus_cents, school["stipend_region"]
    )
    o = {
        "application_id": aid,
        "status": "DRAFT",
        "weekly_rate_cents": weekly_rate_cents,
        "duration_weeks": duration_weeks,
        "sign_on_bonus_cents": sign_on_bonus_cents,
        "total_comp_cents": total_comp,
        "policy_hours_snapshot": None,
        "_extended_at": None,
        "_deadline_at": None,
        "extension_hours_granted": 0,
        "stipend_amount_cents": None,
    }
    stamp_new(o)
    db.offers[o["id"]] = o
    return success_object(offer_view(o), 201)


@bp.route("/offers/<oid>", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter", "Candidate"])
def get_one_offer(oid):
    o = get_offer(oid)
    # Lazy flip on read is a "offer operation" observation; do it
    maybe_lazy_expire_offer(o)
    if g.role == "Candidate":
        app = get_application(o["application_id"])
        if g.user_id != app["candidate_id"]:
            raise err_forbidden("Candidate may read only its own offers")
    return success_object(offer_view(o))


@bp.route("/applications/<aid>/offers", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter", "Candidate"])
def list_application_offers(aid):
    a = get_application(aid)
    if g.role == "Candidate" and g.user_id != a["candidate_id"]:
        raise err_forbidden("Candidate may read only its own offers")
    limit, offset = parse_pagination(request.args)
    items = [o for o in db.offers.values() if o["application_id"] == aid]
    # Lazy flip observation
    for o in items:
        maybe_lazy_expire_offer(o)
    items.sort(key=lambda o: o["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([offer_view(o) for o in page], total, limit, offset)


@bp.route("/offers/<oid>", methods=["PUT"])
@require_auth(["Recruiter"])
def revise_offer(oid):
    o = get_offer(oid)
    payload = request.get_json(silent=True) or {}
    # Body shape: required OCC field
    if "expected_offer_version" not in payload or payload["expected_offer_version"] is None:
        raise err_validation("expected_offer_version is required")
    expected = payload["expected_offer_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err_validation("expected_offer_version must be an integer")

    # Optional field shape validation
    if "weekly_rate_cents" in payload and payload["weekly_rate_cents"] is not None:
        v = payload["weekly_rate_cents"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 1:
            raise err_validation("weekly_rate_cents must be an integer > 0")
    if "duration_weeks" in payload and payload["duration_weeks"] is not None:
        v = payload["duration_weeks"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 1:
            raise err_validation("duration_weeks must be an integer >= 1")
    if "sign_on_bonus_cents" in payload and payload["sign_on_bonus_cents"] is not None:
        v = payload["sign_on_bonus_cents"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise err_validation("sign_on_bonus_cents must be an integer >= 0")

    # OCC
    if expected != o["version"]:
        raise err_stale_offer_version()

    # State: PUT revision requires DRAFT or DECLINED
    if o["status"] not in ("DRAFT", "DECLINED"):
        raise err_offer_state_forbidden("PUT revision requires DRAFT or DECLINED")

    # Apply
    if "weekly_rate_cents" in payload and payload["weekly_rate_cents"] is not None:
        o["weekly_rate_cents"] = payload["weekly_rate_cents"]
    if "duration_weeks" in payload and payload["duration_weeks"] is not None:
        o["duration_weeks"] = payload["duration_weeks"]
    if "sign_on_bonus_cents" in payload and payload["sign_on_bonus_cents"] is not None:
        o["sign_on_bonus_cents"] = payload["sign_on_bonus_cents"]

    # Recompute total_comp with school's current region
    application = get_application(o["application_id"])
    school = get_school_target(application["school_target_id"])
    o["total_comp_cents"] = offer_total_comp(
        o["weekly_rate_cents"], o["duration_weeks"], o["sign_on_bonus_cents"], school["stipend_region"]
    )
    # DECLINED -> DRAFT
    if o["status"] == "DECLINED":
        o["status"] = "DRAFT"
    touch(o)
    return success_object(offer_view(o))


@bp.route("/offers/<oid>/extend", methods=["POST"])
@require_auth(["Recruiter"])
def extend_offer(oid):
    o = get_offer(oid)
    application = get_application(o["application_id"])
    season = get_season(application["season_id"])
    school = get_school_target(application["school_target_id"])
    # Posture
    if season["status"] not in ("OFFER_PERIOD", "INTERN_ACTIVE"):
        raise err_season_posture_forbidden()
    # Offer state: DRAFT only
    if o["status"] != "DRAFT":
        raise err_offer_state_forbidden("extend requires DRAFT")
    # Application state
    if application["status"] != "DECISION_PENDING":
        raise err_application_state_forbidden("extend requires application DECISION_PENDING")
    # Offer window
    now = now_utc()
    if not (season["_offer_window_open_at"] <= now <= season["_offer_window_close_at"]):
        raise err_offer_window_closed()

    # Pin policy hours
    policy_hours = school.get("exploding_offer_hours_override")
    if policy_hours is None:
        policy_hours = season["exploding_offer_hours_default"]
    o["policy_hours_snapshot"] = policy_hours
    o["_extended_at"] = now
    o["_deadline_at"] = exploding_deadline(now, policy_hours, season["deadline_policy_mode"])
    o["stipend_amount_cents"] = stipend_amount(
        school["stipend_region"], school["tier"], application["relocation_distance_miles"]
    )
    # Recompute total_comp at extend
    o["total_comp_cents"] = offer_total_comp(
        o["weekly_rate_cents"], o["duration_weeks"], o["sign_on_bonus_cents"], school["stipend_region"]
    )
    o["status"] = "EXTENDED"
    touch(o)
    # Application DECISION_PENDING -> OFFER_PENDING
    application["status"] = "OFFER_PENDING"
    touch(application)
    # Bubble-up season.offers_extended_count
    season["offers_extended_count"] += 1
    touch(season)
    return success_object(offer_view(o))


@bp.route("/offers/<oid>/accept", methods=["POST"])
@require_auth(["Candidate"])
def accept_offer(oid):
    o = get_offer(oid)
    application = get_application(o["application_id"])
    season = get_season(application["season_id"])
    # Ownership
    if g.user_id != application["candidate_id"]:
        raise err_forbidden("X-User-ID must equal application.candidate_id")
    # Posture
    if season["status"] not in ("OFFER_PERIOD", "INTERN_ACTIVE"):
        raise err_season_posture_forbidden()
    # Offer state: EXTENDED
    if o["status"] != "EXTENDED":
        raise err_offer_state_forbidden("accept requires EXTENDED")
    # Deadline: lazy flip on accept-after-deadline
    now = now_utc()
    if o.get("_deadline_at") is not None and now > o["_deadline_at"]:
        # flip EXTENDED -> EXPIRED with conditional application cascade
        o["status"] = "EXPIRED"
        touch(o)
        if application["status"] == "OFFER_PENDING":
            application["status"] = "EXPIRED"
            touch(application)
        raise err_offer_expired()
    # Fiscal gate (last)
    if season["stipend_reserved_cents"] + o["stipend_amount_cents"] > season["stipend_budget_cents"]:
        raise err_stipend_budget_exceeded()
    # Success: flip to ACCEPTED, create RESERVED disbursement, flip app, bump counters
    o["status"] = "ACCEPTED"
    touch(o)
    d = {
        "offer_id": o["id"],
        "amount_cents": o["stipend_amount_cents"],
        "status": "RESERVED",
    }
    stamp_new(d)
    db.stipend_disbursements[d["id"]] = d
    season["stipend_reserved_cents"] += d["amount_cents"]
    if application["status"] == "OFFER_PENDING":
        application["status"] = "ACCEPTED"
        touch(application)
    season["offers_accepted_count"] += 1
    touch(season)
    return success_object(offer_view(o))


@bp.route("/offers/<oid>/decline", methods=["POST"])
@require_auth(["Candidate"])
def decline_offer(oid):
    o = get_offer(oid)
    application = get_application(o["application_id"])
    season = get_season(application["season_id"])
    if g.user_id != application["candidate_id"]:
        raise err_forbidden("X-User-ID must equal application.candidate_id")
    if season["status"] not in ("OFFER_PERIOD", "INTERN_ACTIVE"):
        raise err_season_posture_forbidden()
    # Lazy expire first if deadline passed (any offer operation observes)
    if maybe_lazy_expire_offer(o):
        # now EXPIRED; decline against non-EXTENDED fails
        raise err_offer_state_forbidden("decline requires EXTENDED")
    if o["status"] != "EXTENDED":
        raise err_offer_state_forbidden("decline requires EXTENDED")
    o["status"] = "DECLINED"
    touch(o)
    if application["status"] == "OFFER_PENDING":
        application["status"] = "DECISION_PENDING"
        touch(application)
    return success_object(offer_view(o))


@bp.route("/offers/<oid>/rescind", methods=["POST"])
@require_auth(["Recruiter", "RecruitingAdmin"])
def rescind_offer(oid):
    o = get_offer(oid)
    application = get_application(o["application_id"])
    # Lazy expire first if deadline passed
    if maybe_lazy_expire_offer(o):
        raise err_offer_state_forbidden("rescind requires EXTENDED")
    if o["status"] != "EXTENDED":
        raise err_offer_state_forbidden("rescind requires EXTENDED")
    o["status"] = "RESCINDED"
    touch(o)
    if application["status"] == "OFFER_PENDING":
        application["status"] = "DECISION_PENDING"
        touch(application)
    return success_object(offer_view(o))


@bp.route("/offers/<oid>/expire", methods=["POST"])
@require_auth(["Recruiter", "RecruitingAdmin"])
def expire_offer(oid):
    o = get_offer(oid)
    application = get_application(o["application_id"])
    if o["status"] != "EXTENDED":
        raise err_offer_state_forbidden("expire requires EXTENDED")
    now = now_utc()
    if not (o.get("_deadline_at") is not None and now > o["_deadline_at"]):
        raise err_offer_not_yet_expired()
    o["status"] = "EXPIRED"
    touch(o)
    if application["status"] == "OFFER_PENDING":
        application["status"] = "EXPIRED"
        touch(application)
    return success_object(offer_view(o))


@bp.route("/offers/<oid>/extend-deadline", methods=["POST"])
@require_auth(["RecruitingAdmin"])
def extend_deadline(oid):
    o = get_offer(oid)
    application = get_application(o["application_id"])
    season = get_season(application["season_id"])
    payload = request.get_json(silent=True) or {}
    additional_hours = require_int(payload, "additional_hours", min_value=1)
    # Posture
    if season["status"] not in ("OFFER_PERIOD", "INTERN_ACTIVE"):
        raise err_season_posture_forbidden()
    # Offer state
    if o["status"] != "EXTENDED":
        raise err_offer_state_forbidden("extend-deadline requires EXTENDED")
    # Cap
    if o["extension_hours_granted"] + additional_hours > season["max_extension_hours"]:
        raise err_extension_cap_exceeded()
    o["extension_hours_granted"] += additional_hours
    o["_deadline_at"] = o["_deadline_at"] + timedelta(hours=additional_hours)
    touch(o)
    return success_object(offer_view(o))
