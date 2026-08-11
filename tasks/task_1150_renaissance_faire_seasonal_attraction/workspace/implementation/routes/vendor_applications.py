"""VendorApplication endpoints."""
from flask import Blueprint

from db import store, new_id, next_seq
from errors import (
    ERR_APPLICATION_NOT_FOUND,
    ERR_SEASON_NOT_FOUND,
    ERR_SEASON_NOT_IN_PLANNING,
    ERR_DUPLICATE_APPLICATION,
    ERR_APPLICATION_NOT_DECIDABLE,
    ERR_APPLICATION_NOT_APPEALABLE,
    ERR_APPEAL_ALREADY_USED,
    ERR_APPLICATION_NOT_WITHDRAWABLE,
    conflict,
)
from middleware import (
    require_roles,
    require_owner,
    get_body,
    load,
    parse_pagination,
    apply_filters,
    sorted_by_creation,
)
from response import obj_response, list_response
from services import rederive_posture, jury_score_of, APPLICATION_TERMINAL
from util import req, check_unknown, new_record, mutate, public_view

bp = Blueprint("vendor_applications", __name__)

TIERS = {"PRIME", "STANDARD", "MEADOW"}
OUTCOMES = {"JURIED_IN", "JURIED_OUT", "WAITLISTED"}
CREATE_FIELDS = {"season_id", "booth_size_sqft", "requested_location_tier"}
DECIDE_FIELDS = {"craft_score", "authenticity_score", "safety_score", "outcome"}
DECIDABLE = {"JURY_REVIEW", "APPEALED", "WAITLISTED"}
WITHDRAWABLE = {"JURY_REVIEW", "APPEALED", "JURIED_OUT", "WAITLISTED"}


def load_application(aid):
    return load(store.applications, aid, ERR_APPLICATION_NOT_FOUND, "vendor application")


@bp.route("/vendor-applications", methods=["POST"])
def create_application():
    uid, _ = require_roles("Vendor")
    body = get_body()
    if isinstance(body.get("season_id"), str):
        load(store.seasons, body["season_id"], ERR_SEASON_NOT_FOUND, "season")
    check_unknown(body, CREATE_FIELDS)
    season_id = req(body, "season_id", "str")
    booth_size_sqft = req(body, "booth_size_sqft", "int", lo=1)
    tier = req(body, "requested_location_tier", "enum", enum=TIERS)

    season = store.seasons[season_id]
    if season["status"] != "PLANNING":
        raise conflict(ERR_SEASON_NOT_IN_PLANNING, "application filing requires season PLANNING")
    for other in store.applications.values():
        if (
            other["season_id"] == season_id
            and other["vendor_id"] == uid
            and other["status"] not in APPLICATION_TERMINAL
        ):
            raise conflict(
                ERR_DUPLICATE_APPLICATION,
                "vendor already has a non-terminal application for the season",
            )
    application = new_record()
    application.update(
        {
            "id": new_id(),
            "_seq": next_seq(),
            "season_id": season_id,
            "vendor_id": uid,
            "status": "JURY_REVIEW",
            "booth_size_sqft": booth_size_sqft,
            "requested_location_tier": tier,
            "craft_score": None,
            "authenticity_score": None,
            "safety_score": None,
            "jury_score": None,
            "appeal_used": False,
        }
    )
    store.applications[application["id"]] = application
    return obj_response(public_view(application), 201)


@bp.route("/vendor-applications", methods=["GET"])
def list_applications():
    require_roles()
    limit, offset = parse_pagination()
    items = apply_filters(
        sorted_by_creation(store.applications),
        [("season_id", "season_id"), ("vendor_id", "vendor_id"), ("status", "status")],
    )
    total = len(items)
    page = items[offset : offset + limit]
    return list_response([public_view(a) for a in page], limit, offset, total)


@bp.route("/vendor-applications/<aid>", methods=["GET"])
def get_application(aid):
    require_roles()
    return obj_response(public_view(load_application(aid)))


@bp.route("/vendor-applications/<aid>/decide", methods=["POST"])
def decide_application(aid):
    require_roles("VendorCoordinator")
    application = load_application(aid)
    body = get_body()
    check_unknown(body, DECIDE_FIELDS)
    craft = req(body, "craft_score", "num", lo=0, hi=10)
    authenticity = req(body, "authenticity_score", "num", lo=0, hi=10)
    safety = req(body, "safety_score", "num", lo=0, hi=10)
    outcome = req(body, "outcome", "enum", enum=OUTCOMES)
    if application["status"] not in DECIDABLE:
        raise conflict(
            ERR_APPLICATION_NOT_DECIDABLE,
            "decide requires JURY_REVIEW, APPEALED, or WAITLISTED",
        )
    mutate(
        application,
        craft_score=craft,
        authenticity_score=authenticity,
        safety_score=safety,
        jury_score=jury_score_of(craft, authenticity, safety),
        status=outcome,
    )
    if outcome == "JURIED_IN":
        season = store.seasons.get(application["season_id"])
        if season is not None:
            rederive_posture(season)
    return obj_response(public_view(application))


@bp.route("/vendor-applications/<aid>/appeal", methods=["POST"])
def appeal_application(aid):
    uid, _ = require_roles("Vendor")
    application = load_application(aid)
    require_owner(uid == application["vendor_id"])
    check_unknown(get_body(), set())
    if application["status"] != "JURIED_OUT":
        raise conflict(ERR_APPLICATION_NOT_APPEALABLE, "appeal requires JURIED_OUT")
    if application["appeal_used"]:
        raise conflict(ERR_APPEAL_ALREADY_USED, "the single appeal has already been consumed")
    mutate(application, status="APPEALED", appeal_used=True)
    return obj_response(public_view(application))


@bp.route("/vendor-applications/<aid>/withdraw", methods=["POST"])
def withdraw_application(aid):
    uid, _ = require_roles("Vendor")
    application = load_application(aid)
    require_owner(uid == application["vendor_id"])
    check_unknown(get_body(), set())
    if application["status"] not in WITHDRAWABLE:
        raise conflict(
            ERR_APPLICATION_NOT_WITHDRAWABLE, "withdraw requires a non-terminal application"
        )
    mutate(application, status="WITHDRAWN")
    return obj_response(public_view(application))
