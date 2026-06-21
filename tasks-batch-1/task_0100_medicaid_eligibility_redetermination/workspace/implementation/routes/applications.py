"""Application + EligibilityDetermination endpoints (PRD §3.3-§3.6)."""
from __future__ import annotations

from flask import Blueprint, g

import db
import services
from common import (
    stamp_create, touch, serialize, serialize_list, sort_by_created,
    require_enum, optional_enum,
    get_or_404,
)
from errors import (
    APIError,
    ERR_INVALID_STATE, ERR_EMPTY_HOUSEHOLD, ERR_NOT_VERIFIED,
    ERR_NO_ELIGIBLE_DETERMINATION,
)
from middleware import authenticate, get_json_body, parse_pagination, paginate, current_user_id
from response import ok_object, ok_array

bp = Blueprint("applications", __name__)

PATHWAYS = {"MAGI", "NON_MAGI"}
MAGI_VARIANTS = {"POINT_IN_TIME", "PROJECTED_ANNUAL"}
DECIDE_TARGETS = {"APPROVED", "DENIED"}


# --- Application create / read ----------------------------------------------

@bp.post("/households/<hid>/applications")
def create_application(hid):
    authenticate(["Applicant", "CaseWorker"])
    get_or_404(db.households, hid, "Household")
    body = get_json_body()

    rec = {
        "household_id": hid,
        "pathway": require_enum(body, "pathway", PATHWAYS),
        "magi_variant": optional_enum(body, "magi_variant", MAGI_VARIANTS, "POINT_IN_TIME"),
        "review_status": "DRAFT",
        "verification_status": "UNVERIFIED",
        "assigned_caseworker_id": None,
    }
    stamp_create(rec)
    db.applications[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/applications/<aid>")
def get_application(aid):
    authenticate(["Applicant", "CaseWorker", "HearingOfficer"])
    rec = get_or_404(db.applications, aid, "Application")
    return ok_object(serialize(rec), 200)


@bp.get("/households/<hid>/applications")
def list_applications(hid):
    authenticate(["Applicant", "CaseWorker", "HearingOfficer"])
    get_or_404(db.households, hid, "Household")
    limit, offset = parse_pagination()
    items = sort_by_created([a for a in db.applications.values() if a["household_id"] == hid])
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


# --- Review dimension -------------------------------------------------------

@bp.post("/applications/<aid>/submit")
def submit_application(aid):
    authenticate(["Applicant"])
    app = get_or_404(db.applications, aid, "Application")
    if app["review_status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "Application is not DRAFT")
    # Requires at least one COUNTED member.
    if not services.counted_members(app["household_id"]):
        raise APIError(ERR_EMPTY_HOUSEHOLD, 409, "Household has no COUNTED member")
    app["review_status"] = "SUBMITTED"
    touch(app)
    return ok_object(serialize(app), 200)


@bp.post("/applications/<aid>/claim-review")
def claim_review(aid):
    authenticate(["CaseWorker"])
    app = get_or_404(db.applications, aid, "Application")
    if app["review_status"] != "SUBMITTED":
        raise APIError(ERR_INVALID_STATE, 409, "Application is not SUBMITTED")
    app["review_status"] = "UNDER_REVIEW"
    app["assigned_caseworker_id"] = current_user_id()
    touch(app)
    return ok_object(serialize(app), 200)


@bp.post("/applications/<aid>/request-docs")
def request_docs(aid):
    authenticate(["CaseWorker"])
    app = get_or_404(db.applications, aid, "Application")
    if app["verification_status"] != "UNVERIFIED":
        raise APIError(ERR_INVALID_STATE, 409, "verification_status is not UNVERIFIED")
    app["verification_status"] = "DOCS_REQUESTED"
    touch(app)
    return ok_object(serialize(app), 200)


@bp.post("/applications/<aid>/verify")
def verify(aid):
    authenticate(["CaseWorker"])
    app = get_or_404(db.applications, aid, "Application")
    # VERIFIED reachable from DOCS_REQUESTED (ordinary) or directly from UNVERIFIED.
    if app["verification_status"] not in ("DOCS_REQUESTED", "UNVERIFIED"):
        raise APIError(ERR_INVALID_STATE, 409, "verification_status cannot transition to VERIFIED")
    app["verification_status"] = "VERIFIED"
    touch(app)
    return ok_object(serialize(app), 200)


@bp.post("/applications/<aid>/decide")
def decide(aid):
    authenticate(["CaseWorker"])
    app = get_or_404(db.applications, aid, "Application")
    body = get_json_body()
    target = require_enum(body, "target_status", DECIDE_TARGETS)

    # priority 6: must be UNDER_REVIEW.
    if app["review_status"] != "UNDER_REVIEW":
        raise APIError(ERR_INVALID_STATE, 409, "Application is not UNDER_REVIEW")
    # priority 13: verification must be VERIFIED (both directions).
    if app["verification_status"] != "VERIFIED":
        raise APIError(ERR_NOT_VERIFIED, 409, "verification_status is not VERIFIED")

    if target == "APPROVED":
        # priority 14: needs an existing child determination with decision ELIGIBLE.
        dets = [d for d in db.determinations.values() if d["application_id"] == aid]
        if not any(d["decision"] == "ELIGIBLE" for d in dets):
            raise APIError(ERR_NO_ELIGIBLE_DETERMINATION, 409, "No ELIGIBLE determination exists")
        app["review_status"] = "APPROVED"
    else:  # DENIED
        app["review_status"] = "DENIED"
    touch(app)
    return ok_object(serialize(app), 200)


# --- Eligibility determinations ---------------------------------------------

@bp.post("/applications/<aid>/determinations")
def run_determination(aid):
    authenticate(["CaseWorker"])
    app = get_or_404(db.applications, aid, "Application")

    household_id = app["household_id"]
    hh = db.households[household_id]
    household_size = hh["household_size"]
    pathway = app["pathway"]

    det = {
        "application_id": aid,
        "pathway": pathway,
        "magi_annual_cents": None,
        "fpl_percentage": None,
        "countable_assets_cents": None,
        "applicable_threshold_pct": None,
        "decision": None,
        "decision_reason": None,
    }

    if pathway == "MAGI":
        fpl_schedule = db.fpl_schedules[db.fpl_by_year[hh["fpl_year"]]]
        magi_annual = services.compute_magi_annual_cents(
            household_id, app["magi_variant"], fpl_schedule, household_size
        )
        base = services.fpl_base_for_size(fpl_schedule, household_size)
        fpl_pct = (magi_annual * 100) // base if base > 0 else 0  # floor

        state_rule = db.state_rules[hh["state_code"]]
        has_adult = services.has_adult_household(household_id)
        threshold = (
            state_rule["magi_adult_threshold_pct"] if has_adult
            else state_rule["magi_child_threshold_pct"]
        )
        eligible = fpl_pct <= threshold  # inclusive boundary
        det["magi_annual_cents"] = magi_annual
        det["fpl_percentage"] = fpl_pct
        det["applicable_threshold_pct"] = threshold
        det["decision"] = "ELIGIBLE" if eligible else "INELIGIBLE"
        det["decision_reason"] = "INCOME_UNDER_THRESHOLD" if eligible else "INCOME_OVER_THRESHOLD"
    else:  # NON_MAGI
        countable = services.compute_countable_assets_cents(household_id)
        state_rule = db.state_rules[hh["state_code"]]
        has_disabled = services.household_has_disabled_counted_member(household_id)
        limit = (
            state_rule["abd_asset_limit_cents"] if has_disabled
            else state_rule["standard_asset_limit_cents"]
        )
        eligible = countable <= limit  # inclusive boundary
        det["countable_assets_cents"] = countable
        det["decision"] = "ELIGIBLE" if eligible else "INELIGIBLE"
        det["decision_reason"] = "ASSETS_UNDER_LIMIT" if eligible else "ASSETS_OVER_LIMIT"

    stamp_create(det)
    db.determinations[det["id"]] = det
    return ok_object(serialize(det), 201)


@bp.get("/applications/<aid>/determinations")
def list_determinations(aid):
    authenticate(["CaseWorker", "HearingOfficer", "Applicant"])
    get_or_404(db.applications, aid, "Application")
    limit, offset = parse_pagination()
    items = sort_by_created([d for d in db.determinations.values() if d["application_id"] == aid])
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)
