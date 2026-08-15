"""StateFilingProfile endpoints (PRD §3.1)."""

import re

import db
import util
from errors import (
    err_invalid_request,
    err_invalid_state,
    err_state_profile_conflict,
    err_state_profile_in_use,
)
from middleware import require_roles
from response import success_list, success_object
from services import domain
from flask import Blueprint, request

bp = Blueprint("state_profiles", __name__)

_STATE_CODE_RE = re.compile(r"^[A-Za-z]{2}$")

ALL_READERS = ("ComplianceOfficer", "Underwriter", "Policyholder")


@bp.post("/carrier/state-profiles")
@require_roles("ComplianceOfficer")
def create_profile(_user_id, _role):
    body = util.get_body()
    util.check_fields(
        body,
        required=[
            "state_code",
            "permissible_grounds",
            "nonpayment_notice_days",
            "other_grounds_notice_days",
            "mortgagee_notice_days",
            "nonrenewal_notice_days",
            "short_rate_penalty_pct",
            "reinstatement_window_days",
            "max_reinstatements",
            "nonrenewal_content_codes",
        ],
        optional=["version_note"],
    )
    state_code = util.require_str(body, "state_code")
    if not _STATE_CODE_RE.match(state_code):
        raise err_invalid_request("state_code must be a 2-letter code")
    permissible_grounds = util.require_str_list(body, "permissible_grounds", domain.PERMISSIBLE_GROUND_CODES)
    nonpayment_notice_days = util.require_int(body, "nonpayment_notice_days")
    other_grounds_notice_days = util.require_int(body, "other_grounds_notice_days")
    mortgagee_notice_days = util.require_int(body, "mortgagee_notice_days")
    nonrenewal_notice_days = util.require_int(body, "nonrenewal_notice_days")
    short_rate_penalty_pct = util.require_number(body, "short_rate_penalty_pct")
    reinstatement_window_days = util.require_int(body, "reinstatement_window_days")
    max_reinstatements = util.require_int(body, "max_reinstatements")
    nonrenewal_content_codes = util.require_str_list(
        body, "nonrenewal_content_codes", domain.NONRENEWAL_CONTENT_CODES
    )
    version_note = body.get("version_note", "")
    if not isinstance(version_note, str):
        raise err_invalid_request("version_note must be a string")

    rec = util.stamp_new(
        {
            "state_code": state_code,
            "status": "DRAFT",
            "permissible_grounds": permissible_grounds,
            "nonpayment_notice_days": nonpayment_notice_days,
            "other_grounds_notice_days": other_grounds_notice_days,
            "mortgagee_notice_days": mortgagee_notice_days,
            "nonrenewal_notice_days": nonrenewal_notice_days,
            "short_rate_penalty_pct": short_rate_penalty_pct,
            "reinstatement_window_days": reinstatement_window_days,
            "max_reinstatements": max_reinstatements,
            "nonrenewal_content_codes": nonrenewal_content_codes,
            "version_note": version_note,
        }
    )
    db.state_profiles[rec["id"]] = rec
    return success_object(util.public(rec), 201)


@bp.get("/carrier/state-profiles/<profileId>")
@require_roles(*ALL_READERS)
def get_profile(profileId, _user_id, _role):
    rec = util.resolve(db.state_profiles, profileId)
    return success_object(util.public(rec), 200)


@bp.get("/carrier/state-profiles")
@require_roles(*ALL_READERS)
def list_profiles(_user_id, _role):
    limit, offset = util.get_pagination()
    records = util.apply_filters(
        list(db.state_profiles.values()),
        {
            "state_code": request.args.get("state_code"),
            "status": request.args.get("status"),
        },
    )
    records = util.sort_chronological(records)
    page = records[offset : offset + limit]
    return success_list([util.public(r) for r in page], limit, offset, len(records))


@bp.post("/carrier/state-profiles/<profileId>/activate")
@require_roles("ComplianceOfficer")
def activate_profile(profileId, _user_id, _role):
    rec = util.resolve(db.state_profiles, profileId)
    if rec["status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT profile can be activated")
    for other in db.state_profiles.values():
        if (
            other["id"] != rec["id"]
            and other["state_code"] == rec["state_code"]
            and other["status"] == "ACTIVE"
        ):
            raise err_state_profile_conflict()
    rec["status"] = "ACTIVE"
    util.touch(rec)
    return success_object(util.public(rec), 200)


@bp.post("/carrier/state-profiles/<profileId>/retire")
@require_roles("ComplianceOfficer")
def retire_profile(profileId, _user_id, _role):
    rec = util.resolve(db.state_profiles, profileId)
    if rec["status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE profile can be retired")
    for policy in db.policies.values():
        if (
            policy["state_profile_id"] == rec["id"]
            and policy["status"] in domain.LIVE_POLICY_STATUSES
        ):
            raise err_state_profile_in_use()
    rec["status"] = "RETIRED"
    util.touch(rec)
    return success_object(util.public(rec), 200)
