"""ScreeningCycle + CutScoreProfile endpoints."""

from decimal import Decimal

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_CYCLE_HAS_OPEN_CASES,
    ERR_CYCLE_WINDOW_OVERLAP,
    ERR_INVALID_CYCLE_STATE,
    ERR_INVALID_REQUEST,
    ERR_NO_PUBLISHED_PROFILE,
    ERR_PROFILE_NOT_DRAFT,
    ERR_STALE_VERSION,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.common import (
    get_json_body,
    require_fields,
    require_string,
    require_int,
    require_number,
    require_enum,
    optional_string,
    get_or_404,
    new_id,
    now_iso,
    pagination_params,
    paginate,
    sort_created,
    parse_date,
    serialize_cycle,
    serialize_profile,
)
from services.domain import touch

bp = Blueprint("cycles", __name__)

GRADE_BANDS = {"ELEMENTARY", "MIDDLE", "HIGH"}

CYCLE_SUCCESSOR = {
    "DRAFT": "OPEN",
    "OPEN": "SCORING",
    "SCORING": "REVIEW",
    "REVIEW": "FINALIZED",
}


# ---------------------------------------------------------------------------
# ScreeningCycle
# ---------------------------------------------------------------------------


@bp.route("/gifted/screening-cycles", methods=["POST"])
def create_cycle():
    require_roles("GiftedCoordinator")
    body = get_json_body()
    require_fields(
        body,
        ["name", "school_year", "grade_band", "screening_open_on",
         "screening_close_on", "referral_close_on"],
    )
    name = require_string(body, "name")
    school_year = require_string(body, "school_year")
    grade_band = require_enum(body, "grade_band", GRADE_BANDS)

    open_raw = body["screening_open_on"]
    close_raw = body["screening_close_on"]
    referral_raw = body["referral_close_on"]
    open_d = parse_date(open_raw, "screening_open_on")
    close_d = parse_date(close_raw, "screening_close_on")
    referral_d = parse_date(referral_raw, "referral_close_on")

    # date-range ordering (shape tier, priority 5)
    if not open_d < close_d:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "screening_open_on must be strictly earlier than screening_close_on",
            400,
        )
    if referral_d > close_d:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "referral_close_on must be no later than screening_close_on",
            400,
        )

    # temporal window overlap (priority 11): half-open [open, close), same band
    for c in db.screening_cycles.values():
        if c["grade_band"] != grade_band:
            continue
        c_open = parse_date(c["screening_open_on"], "screening_open_on")
        c_close = parse_date(c["screening_close_on"], "screening_close_on")
        if open_d < c_close and close_d > c_open:
            raise ApiError(
                ERR_CYCLE_WINDOW_OVERLAP,
                "same grade_band screening window overlaps another cycle",
                409,
            )

    ts = now_iso()
    cycle = {
        "id": new_id(),
        "name": name,
        "school_year": school_year,
        "grade_band": grade_band,
        "screening_open_on": open_raw,
        "screening_close_on": close_raw,
        "referral_close_on": referral_raw,
        "status": "DRAFT",
        "published_profile_id": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.screening_cycles[cycle["id"]] = cycle
    return success_object(serialize_cycle(cycle), 201)


@bp.route("/gifted/screening-cycles/<cid>", methods=["GET"])
def get_cycle(cid):
    require_roles(*ALL_ROLES)
    cycle = get_or_404(db.screening_cycles, cid, "screening cycle")
    return success_object(serialize_cycle(cycle), 200)


@bp.route("/gifted/screening-cycles/<cid>/advance", methods=["POST"])
def advance_cycle(cid):
    require_roles("GiftedCoordinator")
    cycle = get_or_404(db.screening_cycles, cid, "screening cycle")
    body = get_json_body()
    require_fields(body, ["target_state"])
    target = require_enum(body, "target_state", {"DRAFT", "OPEN", "SCORING", "REVIEW", "FINALIZED"})

    expected = CYCLE_SUCCESSOR.get(cycle["status"])
    if expected is None or target != expected:
        raise ApiError(
            ERR_INVALID_CYCLE_STATE,
            f"cannot advance cycle from {cycle['status']} to {target}",
            409,
        )

    if cycle["status"] == "DRAFT" and target == "OPEN":
        has_published = any(
            p["cycle_id"] == cid and p["status"] == "PUBLISHED"
            for p in db.cut_score_profiles.values()
        )
        if not has_published:
            raise ApiError(
                ERR_NO_PUBLISHED_PROFILE,
                "advance DRAFT->OPEN requires a PUBLISHED cut-score profile",
                409,
            )

    if cycle["status"] == "REVIEW" and target == "FINALIZED":
        open_states = {"SCREENING", "AWAITING_COMMITTEE", "APPEAL_PENDING"}
        has_open = any(
            c["cycle_id"] == cid and c["status"] in open_states
            for c in db.gifted_cases.values()
        )
        if has_open:
            raise ApiError(
                ERR_CYCLE_HAS_OPEN_CASES,
                "advance REVIEW->FINALIZED while cases remain open",
                409,
            )

    cycle["status"] = target
    touch(cycle)
    return success_object(serialize_cycle(cycle), 200)


# ---------------------------------------------------------------------------
# CutScoreProfile
# ---------------------------------------------------------------------------


@bp.route("/gifted/screening-cycles/<cid>/cut-score-profiles", methods=["POST"])
def create_profile(cid):
    require_roles("GiftedCoordinator")
    cycle = get_or_404(db.screening_cycles, cid, "screening cycle")
    body = get_json_body()
    require_fields(
        body,
        ["label", "ability_weight", "achievement_weight", "rating_weight",
         "portfolio_weight", "cut_score", "review_band_floor",
         "cut_score_2e", "review_band_floor_2e"],
    )
    label = require_string(body, "label")
    ability_w = require_number(body, "ability_weight")
    achievement_w = require_number(body, "achievement_weight")
    rating_w = require_number(body, "rating_weight")
    portfolio_w = require_number(body, "portfolio_weight")
    cut_score = require_int(body, "cut_score", lo=0, hi=100)
    review_band_floor = require_int(body, "review_band_floor")
    cut_score_2e = require_int(body, "cut_score_2e")
    review_band_floor_2e = require_int(body, "review_band_floor_2e")
    measure_validity_days = body.get("measure_validity_days", 730)
    if isinstance(measure_validity_days, bool) or not isinstance(measure_validity_days, int) or measure_validity_days < 0:
        raise ApiError(ERR_INVALID_REQUEST, "measure_validity_days must be a non-negative integer", 400)

    # weight sum 1.0 within tolerance 0.0001
    total = (
        Decimal(str(ability_w)) + Decimal(str(achievement_w))
        + Decimal(str(rating_w)) + Decimal(str(portfolio_w))
    )
    if abs(total - Decimal("1.0")) > Decimal("0.0001"):
        raise ApiError(ERR_INVALID_REQUEST, "the four weights must sum to 1.0 (tolerance 0.0001)", 400)

    # cut-band sanity trio
    if not review_band_floor < cut_score:
        raise ApiError(ERR_INVALID_REQUEST, "review_band_floor must be strictly below cut_score", 400)
    if not review_band_floor_2e < cut_score_2e:
        raise ApiError(ERR_INVALID_REQUEST, "review_band_floor_2e must be strictly below cut_score_2e", 400)
    if not cut_score_2e <= cut_score:
        raise ApiError(ERR_INVALID_REQUEST, "cut_score_2e must be no greater than cut_score", 400)

    # cycle state gate: create only while DRAFT or OPEN
    if cycle["status"] not in {"DRAFT", "OPEN"}:
        raise ApiError(
            ERR_INVALID_CYCLE_STATE,
            "cut-score profile create requires cycle DRAFT or OPEN",
            409,
        )

    ts = now_iso()
    profile = {
        "id": new_id(),
        "cycle_id": cid,
        "label": label,
        "ability_weight": ability_w,
        "achievement_weight": achievement_w,
        "rating_weight": rating_w,
        "portfolio_weight": portfolio_w,
        "cut_score": cut_score,
        "review_band_floor": review_band_floor,
        "cut_score_2e": cut_score_2e,
        "review_band_floor_2e": review_band_floor_2e,
        "measure_validity_days": measure_validity_days,
        "status": "DRAFT",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.cut_score_profiles[profile["id"]] = profile
    return success_object(serialize_profile(profile), 201)


@bp.route("/gifted/screening-cycles/<cid>/cut-score-profiles", methods=["GET"])
def list_profiles(cid):
    require_roles(*ALL_ROLES)
    get_or_404(db.screening_cycles, cid, "screening cycle")
    st = request.args.get("status")
    items = [p for p in db.cut_score_profiles.values() if p["cycle_id"] == cid]
    if st:
        items = [p for p in items if p["status"] == st]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize_profile(p) for p in page], total, limit, offset)


@bp.route("/gifted/cut-score-profiles/<pid>/publish", methods=["POST"])
def publish_profile(pid):
    require_roles("GiftedCoordinator")
    profile = get_or_404(db.cut_score_profiles, pid, "cut-score profile")
    cycle = get_or_404(db.screening_cycles, profile["cycle_id"], "screening cycle")
    body = get_json_body()
    require_fields(body, ["expected_cycle_version"])
    expected = body["expected_cycle_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(ERR_INVALID_REQUEST, "expected_cycle_version must be an integer", 400)

    # OCC (priority 6) — runs ahead of profile-state (priority 7) per PRD §2.5
    if expected != cycle["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_cycle_version does not match the current ScreeningCycle version",
            412,
        )

    # state preconditions (priority 7)
    if profile["status"] != "DRAFT":
        raise ApiError(ERR_PROFILE_NOT_DRAFT, "publish requires profile status DRAFT", 409)
    if cycle["status"] not in {"DRAFT", "OPEN"}:
        raise ApiError(
            ERR_INVALID_CYCLE_STATE,
            "publish requires parent cycle DRAFT or OPEN",
            409,
        )

    # supersede prior PUBLISHED profile of the same cycle
    for p in db.cut_score_profiles.values():
        if p["cycle_id"] == cycle["id"] and p["status"] == "PUBLISHED" and p["id"] != pid:
            p["status"] = "SUPERSEDED"
            touch(p)

    profile["status"] = "PUBLISHED"
    touch(profile)

    cycle["published_profile_id"] = pid
    touch(cycle)  # bumps cycle.version by 1

    return success_object(serialize_profile(profile), 200)
