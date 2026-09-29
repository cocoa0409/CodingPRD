"""Contact attempts: the full gate ladder, dispositions and the breach cascade (§3.8)."""

from datetime import timedelta

from flask import Blueprint

import calculations as calc
import lookup
import validation as v
from db import base_row, by_created_at, db, now, now_iso, public, touch
from derive import (
    attempts_of_campaign,
    attempts_of_contact,
    active_policies_for_state,
    newest_scrub_job,
    number_is_suppressed,
    pacing_lines,
    recompute_campaign,
    recompute_contact,
    refresh_profile_lines,
    rollover_measurement_day,
    rows,
    select_consent,
    select_policy,
    suspend_campaign,
    touch_campaign,
    touch_contact,
    void_attempt,
)
from errors import ApiError
from middleware import endpoint, payload
from response import created, listing, ok
from util import D, dt_of, iso

bp = Blueprint("attempts", __name__)

CHANNELS = ("VOICE", "SMS")
OUTCOMES = ("PENDING", "CONNECTED_LIVE", "ABANDONED", "MACHINE_ANSWERED", "NO_ANSWER", "VOIDED")
RECORDABLE = ("CONNECTED_LIVE", "ABANDONED", "MACHINE_ANSWERED", "NO_ANSWER")
VOID_REASONS = ("MISDIAL", "CAMPAIGN_SUSPENDED", "COMPLIANCE_CORRECTION")
READ_ROLES = ["DialerOperator", "ComplianceOfficer", "CampaignManager"]


def _rnd_check_is_current(contact, stamp):
    checked_at = dt_of(contact.get("rnd_checked_at"))
    if checked_at is None:
        return False
    return stamp < checked_at + timedelta(days=calc.RND_VALIDITY_DAYS)


def _last_non_voided_attempt(contact_id):
    candidates = [a for a in attempts_of_contact(contact_id) if a["voided_at"] is None]
    if not candidates:
        return None
    candidates.sort(key=lambda a: (a["requested_at"], a["created_at"], a["_seq"]))
    return candidates[-1]


@bp.post("/compliance/contact-attempts")
@endpoint(["DialerOperator"])
def create_attempt():
    body = payload()
    campaign_id = v.req_str(body, "campaign_id")
    contact_id = v.req_str(body, "contact_id")
    channel = v.req_enum(body, "channel", CHANNELS)

    # Step 5 - existence, Contact before Campaign.
    contact = lookup.contact(contact_id)
    campaign = lookup.campaign(campaign_id)

    # Step 7 - campaign state.
    if campaign["status"] != "ACTIVE":
        raise ApiError("ERR_CAMPAIGN_STATE_INVALID", "Only an ACTIVE campaign may place attempts.")

    # Step 9 - governing policy for the recipient's state.
    policy = select_policy(contact["state_code"])
    if policy is None:
        raise ApiError(
            "ERR_CALLING_WINDOW_POLICY_MISSING",
            "No ACTIVE calling-window policy covers state %s right now." % contact["state_code"],
        )

    stamp = now()
    recompute_contact(contact)

    # Step 10 - the attempt-time safety block.
    if number_is_suppressed(contact) or contact["internal_dnc_status"] != "CLEAR":
        raise ApiError("ERR_SUPPRESSED_NUMBER", "This number is covered by a do-not-call entry.")

    consent = select_consent(contact_id, channel)
    if consent is None:
        raise ApiError(
            "ERR_NO_CONSENT_ON_RECORD", "No ACTIVE consent record covers this contact and channel."
        )
    if campaign["campaign_purpose"] == "MARKETING" and consent["consent_type"] != "EXPRESS_WRITTEN":
        raise ApiError(
            "ERR_NO_EXPRESS_WRITTEN_CONSENT",
            "A MARKETING campaign requires EXPRESS_WRITTEN consent.",
        )
    if contact["phone_type"] in ("WIRELESS", "UNKNOWN"):
        if not _rnd_check_is_current(contact, stamp):
            raise ApiError(
                "ERR_RND_CHECK_REQUIRED",
                "A current reassigned-number check is required for this number.",
            )
        if contact["rnd_result"] == "REASSIGNED":
            raise ApiError("ERR_REASSIGNED_NUMBER", "This number has been reassigned.")

    script = db.agent_scripts.get(campaign["agent_script_id"])
    profile = db.dialer_profiles.get(campaign["dialer_profile_id"])

    # Step 11 - recording-consent adequacy, then state coverage.
    if policy["recording_consent_regime"] == "ALL_PARTY":
        if script is None or script["recording_consent_mode"] != "ALL_PARTY":
            raise ApiError(
                "ERR_RECORDING_CONSENT_DISCLOSURE_MISSING",
                "An all-party recording-consent state requires an ALL_PARTY script.",
            )
    if script is None or contact["state_code"] not in script["covered_state_codes"]:
        raise ApiError(
            "ERR_SCRIPT_STATE_NOT_COVERED",
            "The pinned script does not cover state %s." % contact["state_code"],
        )

    # Step 12 - profile lock and scrub currency.
    if profile is not None and profile["status"] == "LOCKED":
        raise ApiError("ERR_DIALER_PROFILE_LOCKED", "The pinned dialer profile is LOCKED.")
    newest = newest_scrub_job(campaign["id"])
    if newest is None or newest["status"] != "COMPLETED":
        raise ApiError("ERR_SCRUB_NOT_CURRENT", "The campaign's newest scrub job is not COMPLETED.")

    # Step 13 - the temporal block.
    for state_code in campaign["target_state_codes"]:
        for candidate in active_policies_for_state(state_code):
            if candidate["emergency_status"] == "ACTIVE":
                raise ApiError(
                    "ERR_EMERGENCY_RESTRICTION",
                    "An emergency restriction is in force for state %s." % state_code,
                )

    local_minutes = calc.recipient_local_minutes(stamp, contact["utc_offset_minutes"])
    local_date = calc.recipient_local_date(stamp, contact["utc_offset_minutes"])
    if local_date.isoformat() in (policy["holiday_dates"] or []):
        raise ApiError(
            "ERR_HOLIDAY_RESTRICTION", "The recipient's local date is a holiday for this state."
        )

    window_start, window_end = calc.effective_calling_window(
        policy["window_start_minutes"],
        policy["window_end_minutes"],
        consent["consent_type"],
        channel,
    )
    if not calc.window_permits(local_minutes, window_start, window_end):
        raise ApiError(
            "ERR_OUTSIDE_CALLING_WINDOW",
            "The recipient's local time falls outside the permitted window.",
        )
    if not stamp < dt_of(newest["expires_at"]):
        raise ApiError("ERR_SCRUB_EXPIRED", "The campaign's completed scrub has expired.")

    # Step 14 - channel agreement.
    if channel != campaign["channel"]:
        raise ApiError(
            "ERR_ATTEMPT_CHANNEL_MISMATCH", "The attempt's channel must equal the campaign's."
        )

    # Step 15 - contact cooldown, a closed interval.
    last = _last_non_voided_attempt(contact_id)
    if last is not None:
        horizon = dt_of(last["requested_at"]) + timedelta(minutes=calc.CONTACT_COOLDOWN_MINUTES)
        if stamp <= horizon:
            raise ApiError(
                "ERR_CONTACT_COOLDOWN_ACTIVE",
                "Another attempt to this consumer is still inside the 30-minute cooldown.",
            )

    # Step 16 - instantaneous pacing capacity.
    max_lines = pacing_lines(profile, campaign) if profile is not None else 0
    pending = len(
        [
            a
            for a in attempts_of_campaign(campaign["id"])
            if a["outcome"] == "PENDING" and a["voided_at"] is None
        ]
    )
    if not pending < max_lines:
        raise ApiError(
            "ERR_PACING_CAPACITY_EXCEEDED", "The campaign is already at its line ceiling."
        )

    # Step 17 - the consumer's frequency cap.
    if contact["attempt_budget_remaining"] < 1:
        raise ApiError("ERR_ATTEMPT_BUDGET_EXHAUSTED", "This consumer's attempt budget is spent.")

    row = base_row()
    row.update(
        {
            "campaign_id": campaign_id,
            "contact_id": contact_id,
            "channel": channel,
            "consent_record_id": consent["id"],
            "calling_window_policy_id": policy["id"],
            "requested_at": iso(stamp),
            "recipient_local_minutes": local_minutes,
            "recipient_local_time": calc.recipient_local_time(local_minutes),
            "effective_window_start_minutes": window_start,
            "effective_window_end_minutes": window_end,
            "cooldown_until": iso(stamp + timedelta(minutes=calc.CONTACT_COOLDOWN_MINUTES)),
            "max_lines_snapshot": max_lines,
            "outcome": "PENDING",
            "agent_connect_seconds": None,
            "abandon_message_played": False,
            "outcome_recorded_at": None,
            "voided_at": None,
            "void_reason": None,
        }
    )
    db.contact_attempts[row["id"]] = row

    touch_contact(contact)
    touch_campaign(campaign)
    return created(public(row))


@bp.get("/compliance/contact-attempts/<attempt_id>")
@endpoint(READ_ROLES)
def read_attempt(attempt_id):
    return ok(public(lookup.contact_attempt(attempt_id)))


@bp.get("/compliance/contact-attempts")
@endpoint(READ_ROLES)
def list_attempts():
    limit, offset = v.pagination()
    campaign_id = v.query_str("campaign_id")
    contact_id = v.query_str("contact_id")
    consent_record_id = v.query_str("consent_record_id")
    calling_window_policy_id = v.query_str("calling_window_policy_id")
    outcome = v.query_enum("outcome", OUTCOMES)

    matches = rows("contact_attempts")
    if campaign_id is not None:
        matches = [a for a in matches if a["campaign_id"] == campaign_id]
    if contact_id is not None:
        matches = [a for a in matches if a["contact_id"] == contact_id]
    if consent_record_id is not None:
        matches = [a for a in matches if a["consent_record_id"] == consent_record_id]
    if calling_window_policy_id is not None:
        matches = [
            a for a in matches if a["calling_window_policy_id"] == calling_window_policy_id
        ]
    if outcome is not None:
        matches = [a for a in matches if a["outcome"] == outcome]
    matches = by_created_at(matches)
    page, total = v.paginate(matches, limit, offset)
    return listing([public(a) for a in page], limit, offset, total)


def _breach_cascade(campaign, profile):
    suspend_campaign(campaign, "ABANDONMENT_BREACH")
    if profile is None:
        return
    if profile["status"] == "APPROVED":
        profile["status"] = "LOCKED"
        profile["locked_reason"] = "ABANDONMENT_BREACH"
        touch(profile)
    for sibling in by_created_at(rows("campaigns")):
        if sibling["id"] == campaign["id"]:
            continue
        if sibling["dialer_profile_id"] != profile["id"] or sibling["status"] != "ACTIVE":
            continue
        suspend_campaign(sibling, "PROFILE_LOCKED")


@bp.post("/compliance/contact-attempts/<attempt_id>/outcome")
@endpoint(["DialerOperator"])
def record_outcome(attempt_id):
    body = payload()
    outcome = v.req_enum(body, "outcome", RECORDABLE)
    agent_connect_seconds = v.opt_int(body, "agent_connect_seconds", None, 0)
    abandon_message_played = v.opt_bool(body, "abandon_message_played", False)

    attempt = lookup.contact_attempt(attempt_id)
    if attempt["outcome"] != "PENDING" or attempt["voided_at"] is not None:
        raise ApiError("ERR_ATTEMPT_STATE_INVALID", "Only a PENDING attempt may take an outcome.")

    campaign = db.campaigns.get(attempt["campaign_id"])
    profile = None
    if campaign is not None:
        profile = db.dialer_profiles.get(campaign["dialer_profile_id"])

    # Step 14 - branch admission rules, message before classification before AMD.
    if outcome == "ABANDONED":
        if not abandon_message_played:
            raise ApiError(
                "ERR_ABANDON_MESSAGE_REQUIRED",
                "An abandoned call requires the recorded abandonment message.",
            )
        if agent_connect_seconds is not None and agent_connect_seconds <= calc.ABANDON_CONNECT_SECONDS:
            raise ApiError(
                "ERR_ABANDON_CLASSIFICATION_INVALID",
                "A call an agent took within two seconds was not abandoned.",
            )
    elif outcome == "CONNECTED_LIVE":
        if agent_connect_seconds is None or agent_connect_seconds > calc.ABANDON_CONNECT_SECONDS:
            raise ApiError(
                "ERR_ABANDON_CLASSIFICATION_INVALID",
                "A live connect requires agent_connect_seconds of at most two.",
            )
    elif outcome == "MACHINE_ANSWERED":
        if profile is None or not profile["amd_enabled"]:
            raise ApiError(
                "ERR_AMD_NOT_ENABLED",
                "A machine answer may only be asserted when AMD is enabled.",
            )

    if campaign is not None:
        recompute_campaign(campaign)
        rollover_measurement_day(campaign)

    attempt["outcome"] = outcome
    attempt["outcome_recorded_at"] = now_iso()
    if outcome == "CONNECTED_LIVE":
        attempt["agent_connect_seconds"] = agent_connect_seconds
    elif outcome == "ABANDONED":
        attempt["abandon_message_played"] = True
        if agent_connect_seconds is not None:
            attempt["agent_connect_seconds"] = agent_connect_seconds
    touch(attempt)

    if campaign is not None:
        touch_campaign(campaign)
        if profile is not None:
            refresh_profile_lines(profile, campaign)
        if outcome == "ABANDONED" and profile is not None:
            breached = calc.is_breach(
                campaign["live_answer_count_today"],
                D(campaign["regulatory_abandonment_rate_pct"]),
                D(profile["abandonment_limit_pct"]),
            )
            if breached and campaign["status"] == "ACTIVE":
                _breach_cascade(campaign, profile)
    return ok(public(attempt))


@bp.post("/compliance/contact-attempts/<attempt_id>/void")
@endpoint(["ComplianceOfficer"])
def void(attempt_id):
    body = payload()
    void_reason = v.req_enum(body, "void_reason", VOID_REASONS)
    attempt = lookup.contact_attempt(attempt_id)
    if attempt["voided_at"] is not None:
        raise ApiError("ERR_ATTEMPT_STATE_INVALID", "This attempt has already been voided.")
    void_attempt(attempt, void_reason)
    return ok(public(attempt))
