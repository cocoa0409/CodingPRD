"""Campaign assembly, certification, suspension, resumption and closure (§3.7)."""

from flask import Blueprint, g

import lookup
import validation as v
from db import base_row, by_created_at, db, now, public
from derive import (
    active_policies_for_state,
    campaign_view,
    newest_scrub_job,
    recompute_campaign,
    rows,
    select_policy,
    suspend_campaign,
    touch_campaign,
    void_attempt,
    attempts_of_campaign,
)
from errors import ApiError
from middleware import endpoint, payload
from response import created, listing, ok
from util import date_str, dt_of

bp = Blueprint("campaigns", __name__)

CHANNELS = ("VOICE", "SMS")
PURPOSES = ("MARKETING", "INFORMATIONAL", "DEBT_COLLECTION")
STATUSES = ("DRAFT", "PENDING_LAUNCH", "ACTIVE", "SUSPENDED", "CLOSED")
READ_ROLES = ["CampaignManager", "ComplianceOfficer", "DialerOperator", "PlatformAdmin"]


@bp.post("/compliance/campaigns")
@endpoint(["CampaignManager"])
def create_campaign():
    body = payload()
    name = v.req_str(body, "name")
    channel = v.req_enum(body, "channel", CHANNELS)
    campaign_purpose = v.req_enum(body, "campaign_purpose", PURPOSES)
    target_state_codes = v.req_str_list(
        body, "target_state_codes", min_len=1, pattern=v.STATE_RE
    )
    dialer_profile_id = v.req_str(body, "dialer_profile_id")
    agent_script_id = v.req_str(body, "agent_script_id")

    lookup.dialer_profile(dialer_profile_id)
    script = lookup.agent_script(agent_script_id)
    if script["channel"] != channel:
        raise ApiError(
            "ERR_SCRIPT_CHANNEL_MISMATCH", "The pinned script's channel must equal the campaign's."
        )

    row = base_row()
    row.update(
        {
            "name": name,
            "channel": channel,
            "campaign_purpose": campaign_purpose,
            "target_state_codes": list(target_state_codes),
            "dialer_profile_id": dialer_profile_id,
            "agent_script_id": agent_script_id,
            "status": "DRAFT",
            "suspension_reason": None,
            "launch_certified_by_user_id": None,
            "pinned_script_version": None,
            "latest_scrub_status": None,
            "eligible_target_count": 0,
            "measurement_date": None,
            "live_answer_count_today": 0,
            "abandoned_count_today": 0,
            "machine_count_today": 0,
            "no_answer_count_today": 0,
            "regulatory_abandonment_rate_pct": 0.00,
            "internal_abandonment_rate_pct": 0.00,
            "daily_rate_history": [],
            "rolling_compliance_rate_pct": 0.00,
            "permitted_attempt_count": 0,
            "voided_attempt_count": 0,
        }
    )
    db.campaigns[row["id"]] = row
    return created(public(row))


@bp.get("/compliance/campaigns/<campaign_id>")
@endpoint(READ_ROLES)
def read_campaign(campaign_id):
    campaign = lookup.campaign(campaign_id)
    return ok(campaign_view(campaign))


@bp.get("/compliance/campaigns")
@endpoint(READ_ROLES)
def list_campaigns():
    limit, offset = v.pagination()
    agent_script_id = v.query_str("agent_script_id")
    dialer_profile_id = v.query_str("dialer_profile_id")
    status = v.query_enum("status", STATUSES)
    channel = v.query_enum("channel", CHANNELS)

    matches = rows("campaigns")
    if agent_script_id is not None:
        matches = [c for c in matches if c["agent_script_id"] == agent_script_id]
    if dialer_profile_id is not None:
        matches = [c for c in matches if c["dialer_profile_id"] == dialer_profile_id]
    if status is not None:
        matches = [c for c in matches if c["status"] == status]
    if channel is not None:
        matches = [c for c in matches if c["channel"] == channel]
    matches = by_created_at(matches)
    page, total = v.paginate(matches, limit, offset)
    return listing([campaign_view(c) for c in page], limit, offset, total)


@bp.post("/compliance/campaigns/<campaign_id>/launch")
@endpoint(["ComplianceOfficer"])
def launch_campaign(campaign_id):
    body = payload()
    v.req_str(body, "certification_note")
    expected_campaign_version = v.req_int(body, "expected_campaign_version")

    campaign = lookup.campaign(campaign_id)
    recompute_campaign(campaign)
    if expected_campaign_version != campaign["version"]:
        raise ApiError(
            "ERR_STALE_CAMPAIGN_VERSION",
            "expected_campaign_version does not match the campaign's current version.",
        )
    if campaign["status"] != "PENDING_LAUNCH":
        raise ApiError(
            "ERR_CAMPAIGN_STATE_INVALID", "Only a PENDING_LAUNCH campaign may be certified."
        )

    # Step 9 - a governing policy for every targeted state.
    policies = []
    for state_code in campaign["target_state_codes"]:
        policy = select_policy(state_code)
        if policy is None:
            raise ApiError(
                "ERR_CALLING_WINDOW_POLICY_MISSING",
                "No ACTIVE calling-window policy covers state %s right now." % state_code,
            )
        policies.append(policy)

    script = db.agent_scripts.get(campaign["agent_script_id"])
    profile = db.dialer_profiles.get(campaign["dialer_profile_id"])

    # Step 11 - recording-consent adequacy, then state coverage.
    if any(p["recording_consent_regime"] == "ALL_PARTY" for p in policies):
        if script is None or script["recording_consent_mode"] != "ALL_PARTY":
            raise ApiError(
                "ERR_RECORDING_CONSENT_DISCLOSURE_MISSING",
                "An all-party recording-consent state requires an ALL_PARTY script.",
            )
    covered = set(script["covered_state_codes"]) if script else set()
    for state_code in campaign["target_state_codes"]:
        if state_code not in covered:
            raise ApiError(
                "ERR_SCRIPT_STATE_NOT_COVERED",
                "The pinned script does not cover state %s." % state_code,
            )

    # Step 12 - launch readiness.
    if script["status"] != "APPROVED":
        raise ApiError("ERR_SCRIPT_NOT_APPROVED", "The pinned script is not APPROVED.")
    if script["channel"] != campaign["channel"]:
        raise ApiError(
            "ERR_SCRIPT_CHANNEL_MISMATCH", "The pinned script's channel must equal the campaign's."
        )
    if profile["status"] == "DRAFT":
        raise ApiError(
            "ERR_DIALER_PROFILE_NOT_APPROVED", "The pinned dialer profile has never been approved."
        )
    if profile["status"] == "LOCKED":
        raise ApiError("ERR_DIALER_PROFILE_LOCKED", "The pinned dialer profile is LOCKED.")
    newest = newest_scrub_job(campaign["id"])
    if newest is None or newest["status"] != "COMPLETED":
        raise ApiError("ERR_SCRUB_NOT_CURRENT", "The campaign's newest scrub job is not COMPLETED.")
    if campaign["eligible_target_count"] < 1:
        raise ApiError("ERR_EMPTY_TARGET_SET", "No eligible target remains after scrubbing.")
    if script.get("approved_by_user_id") is not None and script["approved_by_user_id"] == g.user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The officer who approved the pinned script may not certify this launch.",
        )

    # Step 13 - the temporal block.
    for state_code in campaign["target_state_codes"]:
        for policy in active_policies_for_state(state_code):
            if policy["emergency_status"] == "ACTIVE":
                raise ApiError(
                    "ERR_EMERGENCY_RESTRICTION",
                    "An emergency restriction is in force for state %s." % state_code,
                )
    if not now() < dt_of(newest["expires_at"]):
        raise ApiError("ERR_SCRUB_EXPIRED", "The campaign's completed scrub has expired.")

    campaign["status"] = "ACTIVE"
    campaign["suspension_reason"] = None
    campaign["launch_certified_by_user_id"] = g.user_id
    campaign["pinned_script_version"] = script["version"]
    campaign["measurement_date"] = date_str(now())
    campaign["live_answer_count_today"] = 0
    campaign["abandoned_count_today"] = 0
    campaign["machine_count_today"] = 0
    campaign["no_answer_count_today"] = 0
    campaign["regulatory_abandonment_rate_pct"] = 0.00
    campaign["internal_abandonment_rate_pct"] = 0.00
    touch_campaign(campaign)
    return ok(public(campaign))


@bp.post("/compliance/campaigns/<campaign_id>/suspend")
@endpoint(["ComplianceOfficer"])
def suspend(campaign_id):
    body = payload()
    v.req_str(body, "suspension_note")
    campaign = lookup.campaign(campaign_id)
    if campaign["status"] != "ACTIVE":
        raise ApiError("ERR_CAMPAIGN_STATE_INVALID", "Only an ACTIVE campaign may be suspended.")
    suspend_campaign(campaign, "MANUAL")
    return ok(public(campaign))


def _resume_permitted(campaign):
    reason = campaign["suspension_reason"]
    if reason == "SCRUB_STALE":
        newest = newest_scrub_job(campaign["id"])
        if newest is None or newest["status"] != "COMPLETED":
            return False
        return now() < dt_of(newest["expires_at"])
    if reason in ("PROFILE_LOCKED", "ABANDONMENT_BREACH"):
        profile = db.dialer_profiles.get(campaign["dialer_profile_id"])
        if profile is None or profile["status"] != "APPROVED":
            return False
        if reason == "ABANDONMENT_BREACH" and date_str(now()) == campaign["measurement_date"]:
            return False
        return True
    if reason == "EMERGENCY_RESTRICTION":
        for state_code in campaign["target_state_codes"]:
            for policy in active_policies_for_state(state_code):
                if policy["emergency_status"] == "ACTIVE":
                    return False
        return True
    return True


@bp.post("/compliance/campaigns/<campaign_id>/resume")
@endpoint(["ComplianceOfficer"])
def resume(campaign_id):
    body = payload()
    v.req_str(body, "resume_note")
    campaign = lookup.campaign(campaign_id)
    if campaign["status"] != "SUSPENDED":
        raise ApiError("ERR_CAMPAIGN_STATE_INVALID", "Only a SUSPENDED campaign may be resumed.")
    if not _resume_permitted(campaign):
        raise ApiError(
            "ERR_RESUME_BLOCKED", "The condition named by the suspension reason is not yet cleared."
        )
    campaign["status"] = "ACTIVE"
    campaign["suspension_reason"] = None
    touch_campaign(campaign)
    return ok(public(campaign))


@bp.post("/compliance/campaigns/<campaign_id>/close")
@endpoint(["CampaignManager"])
def close(campaign_id):
    body = payload()
    v.req_str(body, "closure_note")
    campaign = lookup.campaign(campaign_id)
    if campaign["status"] == "CLOSED":
        raise ApiError("ERR_CAMPAIGN_STATE_INVALID", "A CLOSED campaign accepts nothing further.")

    was_active = campaign["status"] == "ACTIVE"
    campaign["status"] = "CLOSED"
    campaign["suspension_reason"] = None
    if was_active:
        for attempt in by_created_at(attempts_of_campaign(campaign["id"])):
            if attempt["outcome"] == "PENDING" and attempt["voided_at"] is None:
                void_attempt(attempt, "CAMPAIGN_SUSPENDED", bump_campaign=False)
    touch_campaign(campaign)
    return ok(public(campaign))
