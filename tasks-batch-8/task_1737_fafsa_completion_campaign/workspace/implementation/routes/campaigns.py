"""Campaign, clock, school, staff-profile routes."""

from flask import Blueprint, request

import dates
import errors
import middleware
import validate
from db import store, make_common, touch
from response import success_object, success_list
from services import core

bp = Blueprint("campaigns", __name__)

ALL_ROLES = ["CampaignAdmin", "SchoolCoordinator", "StaffMember", "Specialist", "MatchReviewer", "DataImporter"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["CampaignAdmin"])
    body = validate.get_json_body(required=True)
    validate.check_fields(body, required=["to_iso8601"], optional=[])
    to_str = validate.req_datetime(body, "to_iso8601")
    to_dt = dates.parse_datetime(to_str)
    core.advance_clock(to_dt)
    return success_object({"now": dates.format_dt(store.clock_now)})


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------

@bp.route("/fafsa/campaigns", methods=["POST"])
def create_campaign():
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["CampaignAdmin"])
    body = validate.get_json_body(required=True)
    validate.check_fields(
        body,
        required=["name", "academic_year", "state_grant_deadline", "federal_deadline", "total_budget_cents"],
        optional=["auto_confirm_threshold", "review_floor", "min_subgroup_size", "max_caseload", "no_show_limit", "min_recognition_seniors"],
    )
    name = validate.req_string(body, "name")
    academic_year = validate.req_string(body, "academic_year")
    state_grant_deadline = validate.req_datetime(body, "state_grant_deadline")
    federal_deadline = validate.req_datetime(body, "federal_deadline")
    total_budget_cents = validate.req_int(body, "total_budget_cents")
    auto_confirm_threshold = validate.req_number(body, "auto_confirm_threshold", required=False, default=None)
    review_floor = validate.req_number(body, "review_floor", required=False, default=None)
    min_subgroup_size = validate.req_int(body, "min_subgroup_size", required=False, default=None, minimum=1)
    max_caseload = validate.req_int(body, "max_caseload", required=False, default=None, minimum=0)
    no_show_limit = validate.req_int(body, "no_show_limit", required=False, default=None, minimum=1)
    min_recognition_seniors = validate.req_int(body, "min_recognition_seniors", required=False, default=None, minimum=0)

    common = make_common()
    campaign = {
        **common,
        "name": name,
        "academic_year": academic_year,
        "state_grant_deadline": state_grant_deadline,
        "federal_deadline": federal_deadline,
        "total_budget_cents": total_budget_cents,
        "auto_confirm_threshold": float(auto_confirm_threshold) if auto_confirm_threshold is not None else 0.90,
        "review_floor": float(review_floor) if review_floor is not None else 0.60,
        "min_subgroup_size": min_subgroup_size if min_subgroup_size is not None else 5,
        "max_caseload": max_caseload if max_caseload is not None else 25,
        "no_show_limit": no_show_limit if no_show_limit is not None else 3,
        "min_recognition_seniors": min_recognition_seniors if min_recognition_seniors is not None else 10,
        "status": "DRAFT",
        "committed_budget_cents": 0,
        "spent_budget_cents": 0,
        "budget_balance_cents": total_budget_cents,
        "_seq": store.next_seq(),
    }
    store.campaigns[campaign["id"]] = campaign
    return success_object(core.serialize(campaign), 201)


@bp.route("/fafsa/campaigns", methods=["GET"])
def list_campaigns():
    auth = middleware.get_auth()
    middleware.require_roles(auth, ALL_ROLES)
    limit, offset = validate.parse_pagination()
    items = list(store.campaigns.values())
    page, total = core.sorted_page(items, limit, offset)
    return success_list([core.serialize(c) for c in page], limit, offset, total)


@bp.route("/fafsa/campaigns/<cid>", methods=["GET"])
def get_campaign(cid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, ALL_ROLES)
    campaign = core.get_campaign_or_404(cid)
    return success_object(core.serialize(campaign))


@bp.route("/fafsa/campaigns/<cid>/activate", methods=["POST"])
def activate_campaign(cid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["CampaignAdmin"])
    campaign = core.get_campaign_or_404(cid)
    if campaign["status"] != "DRAFT":
        errors.raise_error(errors.ERR_CAMPAIGN_NOT_DRAFT, "activate requires DRAFT")
    campaign["status"] = "OPEN"
    touch(campaign)
    # Recompute deadline classification for all seniors (trigger per calc table)
    for s in store.senior_records.values():
        sc = core.campaign_of_senior(s)
        if sc and sc["id"] == campaign["id"]:
            core.recompute_submitted_at(s)
    return success_object(core.serialize(campaign))


# ---------------------------------------------------------------------------
# Schools
# ---------------------------------------------------------------------------

@bp.route("/fafsa/schools", methods=["POST"])
def create_school():
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["CampaignAdmin"])
    body = validate.get_json_body(required=True)
    validate.check_fields(body, required=["campaign_id", "name", "district_code", "school_code"], optional=[])
    campaign_id = validate.req_string(body, "campaign_id")
    name = validate.req_string(body, "name")
    district_code = validate.req_string(body, "district_code")
    school_code = validate.req_string(body, "school_code")
    core.get_campaign_or_404(campaign_id)
    common = make_common()
    school = {
        **common,
        "campaign_id": campaign_id,
        "name": name,
        "district_code": district_code,
        "school_code": school_code,
        "status": "INVITED",
        "recognition_tier": "UNRATED",
        "_seq": store.next_seq(),
    }
    store.schools[school["id"]] = school
    return success_object(core.serialize(school), 201)


@bp.route("/fafsa/schools", methods=["GET"])
def list_schools():
    auth = middleware.get_auth()
    middleware.require_roles(auth, ALL_ROLES)
    limit, offset = validate.parse_pagination()
    campaign_id = request.args.get("campaign_id")
    status = request.args.get("status")
    items = list(store.schools.values())
    if campaign_id is not None:
        items = [s for s in items if s["campaign_id"] == campaign_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, total = core.sorted_page(items, limit, offset)
    return success_list([core.serialize(s) for s in page], limit, offset, total)


@bp.route("/fafsa/schools/<sid>", methods=["GET"])
def get_school(sid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, ALL_ROLES)
    school = core.get_school_or_404(sid)
    return success_object(core.serialize(school))


@bp.route("/fafsa/schools/<sid>/enroll", methods=["POST"])
def enroll_school(sid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["CampaignAdmin"])
    school = core.get_school_or_404(sid)
    if school["status"] != "INVITED":
        errors.raise_error(errors.ERR_SCHOOL_NOT_INVITED, "enroll requires INVITED")
    campaign = core.get_campaign_or_404(school["campaign_id"])
    if campaign["status"] != "OPEN":
        errors.raise_error(errors.ERR_CAMPAIGN_NOT_OPEN, "enroll requires campaign OPEN")
    school["status"] = "ENROLLED"
    touch(school)
    return success_object(core.serialize(school))


@bp.route("/fafsa/schools/<sid>/suspend", methods=["POST"])
def suspend_school(sid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["CampaignAdmin"])
    school = core.get_school_or_404(sid)
    if school["status"] != "ENROLLED":
        errors.raise_error(errors.ERR_SCHOOL_NOT_ENROLLED, "suspend requires ENROLLED")
    school["status"] = "SUSPENDED"
    touch(school)
    # Cancel DRAFT/PUBLISHED events of this school with cascades.
    for ev in list(store.events.values()):
        if ev["school_id"] == school["id"] and ev["status"] in ("DRAFT", "PUBLISHED"):
            core.cancel_event_cascade(ev)
    return success_object(core.serialize(school))


@bp.route("/fafsa/schools/<sid>/reinstate", methods=["POST"])
def reinstate_school(sid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["CampaignAdmin"])
    school = core.get_school_or_404(sid)
    if school["status"] != "SUSPENDED":
        errors.raise_error(errors.ERR_SCHOOL_NOT_SUSPENDED, "reinstate requires SUSPENDED")
    campaign = core.get_campaign_or_404(school["campaign_id"])
    if campaign["status"] != "OPEN":
        errors.raise_error(errors.ERR_CAMPAIGN_NOT_OPEN, "reinstate requires campaign OPEN")
    school["status"] = "ENROLLED"
    touch(school)
    return success_object(core.serialize(school))


# ---------------------------------------------------------------------------
# Staff profiles
# ---------------------------------------------------------------------------

@bp.route("/fafsa/staff-profiles", methods=["POST"])
def create_staff():
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["CampaignAdmin"])
    body = validate.get_json_body(required=True)
    validate.check_fields(body, required=["campaign_id", "full_name", "capabilities", "languages"], optional=[])
    campaign_id = validate.req_string(body, "campaign_id")
    full_name = validate.req_string(body, "full_name")
    capabilities = validate.req_array(body, "capabilities")
    languages = validate.req_array(body, "languages")
    for cap in capabilities:
        if cap not in core.CAPABILITIES:
            errors.raise_error(errors.ERR_INVALID_REQUEST, f"Invalid capability: {cap}")
    core.get_campaign_or_404(campaign_id)
    common = make_common()
    profile = {
        **common,
        "campaign_id": campaign_id,
        "full_name": full_name,
        "capabilities": capabilities,
        "languages": languages,
        "background_check_status": "PENDING",
        "status": "ACTIVE",
        "confirmed_hours_total": 0,
        "no_show_count": 0,
        "active_case_count": 0,
        "_seq": store.next_seq(),
    }
    store.staff_profiles[profile["id"]] = profile
    return success_object(core.serialize(profile), 201)


@bp.route("/fafsa/staff-profiles", methods=["GET"])
def list_staff():
    auth = middleware.get_auth()
    middleware.require_roles(auth, ALL_ROLES)
    limit, offset = validate.parse_pagination()
    campaign_id = request.args.get("campaign_id")
    status = request.args.get("status")
    items = list(store.staff_profiles.values())
    if campaign_id is not None:
        items = [p for p in items if p["campaign_id"] == campaign_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, total = core.sorted_page(items, limit, offset)
    return success_list([core.serialize(p) for p in page], limit, offset, total)


@bp.route("/fafsa/staff-profiles/<pid>", methods=["GET"])
def get_staff(pid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, ALL_ROLES)
    profile = core.get_staff_or_404(pid)
    return success_object(core.serialize(profile))


@bp.route("/fafsa/staff-profiles/<pid>/background-check", methods=["POST"])
def background_check(pid):
    auth = middleware.get_auth()
    middleware.require_roles(auth, ["CampaignAdmin"])
    profile = core.get_staff_or_404(pid)
    body = validate.get_json_body(required=True)
    validate.check_fields(body, required=["result"], optional=[])
    result = validate.req_enum(body, "result", core.BACKGROUND_RESULTS)
    profile["background_check_status"] = result
    touch(profile)
    return success_object(core.serialize(profile))
