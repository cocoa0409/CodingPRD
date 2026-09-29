"""Talent-community consent, nurture campaigns and send evaluation."""

from datetime import timedelta

from flask import Blueprint, g

import db
import response
import validation as V
from errors import ApiError
from middleware import require
from services import calc, serialize

bp = Blueprint("community", __name__)

MEMBER_READ = ("BrandProgramLead", "CommunityManager", "RecruitingOps", "Candidate")
LIST_READ = ("BrandProgramLead", "CommunityManager", "RecruitingOps")


@bp.route("/talent-community-members", methods=["POST"])
@require("Anonymous", "CommunityManager")
def create_member():
    data = V.body()
    program_id = V.field(data, "program_id", "string", required=True)
    interest_job_family_id = V.field(data, "interest_job_family_id", "string",
                                     nullable=True)
    email = V.field(data, "email", "email", required=True, max_len=200)
    frequency_cap = V.field(data, "frequency_cap_per_30d", "integer",
                            default=4, min_value=1)
    program = calc.must_get(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    family = None
    if interest_job_family_id is not None:
        family = calc.must_get(db.job_families, interest_job_family_id,
                               "ERR_JOB_FAMILY_NOT_FOUND")
    for existing in db.members.values():
        if existing["program_id"] == program["id"] and existing["email"] == email:
            raise ApiError("ERR_DUPLICATE_MEMBER_EMAIL",
                           "This email already joined the program's community.")
    row = {
        "id": db.new_id(),
        "program_id": program["id"],
        "interest_job_family_id": family["id"] if family else None,
        "email": email,
        "consent_status": "PENDING_CONFIRMATION",
        "consent_token": db.new_token(),
        "frequency_cap_per_30d": frequency_cap,
        "consent_confirmed_at": None,
        "consent_changed_at": None,
    }
    stamp = db.wall_now()
    row.update({"created_at": stamp, "updated_at": stamp, "version": 1})
    db.members[row["id"]] = row
    return response.ok(serialize.member(row), 201)


@bp.route("/talent-community-members/<member_id>/confirm-consent", methods=["POST"])
@require("Anonymous", "Candidate")
def confirm_consent(member_id):
    data = V.body()
    token = V.field(data, "consent_token", "string", required=True, max_len=200)
    member = calc.must_get(db.members, member_id, "ERR_MEMBER_NOT_FOUND")
    if member["consent_status"] != "PENDING_CONFIRMATION":
        raise ApiError("ERR_CONSENT_ALREADY_RESOLVED",
                       "The member's consent is already resolved.")
    if token != member["consent_token"]:
        raise ApiError("ERR_CONSENT_TOKEN_INVALID", "The consent token does not match.")
    member["consent_status"] = "SUBSCRIBED"
    member["consent_confirmed_at"] = db.clock()
    member["consent_changed_at"] = db.clock()
    db.touch(member)
    return response.ok(serialize.member(member))


@bp.route("/talent-community-members/<member_id>/consent-change", methods=["POST"])
@require("Candidate", "CommunityManager")
def change_consent(member_id):
    data = V.body()
    action = V.field(data, "action", "enum", required=True,
                     values=("PAUSE", "RESUME", "UNSUBSCRIBE"))
    member = calc.must_get(db.members, member_id, "ERR_MEMBER_NOT_FOUND")
    if g.role == "Candidate" and g.user_id != member["id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "A Candidate may only act on their own member record.")
    if action == "PAUSE":
        if member["consent_status"] != "SUBSCRIBED":
            raise ApiError("ERR_CONSENT_TRANSITION_INVALID",
                           "PAUSE requires a SUBSCRIBED member.")
        member["consent_status"] = "PAUSED"
    elif action == "RESUME":
        if member["consent_status"] != "PAUSED":
            raise ApiError("ERR_CONSENT_TRANSITION_INVALID",
                           "RESUME requires a PAUSED member.")
        member["consent_status"] = "SUBSCRIBED"
    else:
        if member["consent_status"] == "UNSUBSCRIBED":
            raise ApiError("ERR_CONSENT_ALREADY_RESOLVED",
                           "The member is already UNSUBSCRIBED.")
        member["consent_status"] = "UNSUBSCRIBED"
    member["consent_changed_at"] = db.clock()
    db.touch(member)
    return response.ok(serialize.member(member))


@bp.route("/talent-community-members/<member_id>", methods=["GET"])
@require(*MEMBER_READ)
def get_member(member_id):
    member = calc.must_get(db.members, member_id, "ERR_MEMBER_NOT_FOUND")
    return response.ok(serialize.member(member))


@bp.route("/talent-community-members", methods=["GET"])
@require(*LIST_READ)
def list_members():
    limit, offset = V.pagination()
    rows = sorted(db.members.values(), key=lambda r: (r["created_at"], r["email"]))
    for name in ("program_id", "interest_job_family_id", "consent_status", "email"):
        value = V.qs(name)
        if value:
            rows = [r for r in rows if r[name] == value]
    page, meta = V.window(rows, limit, offset)
    return response.ok_list([serialize.member(r) for r in page], meta)


# ------------------------------------------------------------------ campaigns
@bp.route("/nurture-campaigns", methods=["POST"])
@require("CommunityManager")
def create_campaign():
    data = V.body()
    program_id = V.field(data, "program_id", "string", required=True)
    job_family_id = V.field(data, "job_family_id", "string", nullable=True)
    name = V.field(data, "name", "string", required=True, min_len=1, max_len=160)
    max_sends = V.field(data, "max_sends", "integer", required=True, min_value=1)
    program = calc.must_get(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    family = None
    if job_family_id is not None:
        family = calc.must_get(db.job_families, job_family_id,
                               "ERR_JOB_FAMILY_NOT_FOUND")
    row = {
        "id": db.new_id(),
        "program_id": program["id"],
        "job_family_id": family["id"] if family else None,
        "name": name,
        "max_sends": max_sends,
        "state": "DRAFT",
        "scheduled_for": None,
        "dispatched_at": None,
    }
    stamp = db.wall_now()
    row.update({"created_at": stamp, "updated_at": stamp, "version": 1})
    db.campaigns[row["id"]] = row
    return response.ok(serialize.campaign(row), 201)


@bp.route("/nurture-campaigns/<campaign_id>/schedule", methods=["POST"])
@require("CommunityManager")
def schedule_campaign(campaign_id):
    data = V.body()
    scheduled_for = V.field(data, "scheduled_for", "datetime", required=True)
    campaign = calc.must_get(db.campaigns, campaign_id, "ERR_CAMPAIGN_NOT_FOUND")
    if campaign["state"] != "DRAFT":
        raise ApiError("ERR_CAMPAIGN_NOT_DRAFT", "The campaign is not in DRAFT.")
    if scheduled_for < db.clock():
        raise ApiError("ERR_SCHEDULE_IN_PAST",
                       "scheduled_for must be at or after the current instant.")
    campaign["scheduled_for"] = scheduled_for
    campaign["state"] = "SCHEDULED"
    db.touch(campaign)
    return response.ok(serialize.campaign(campaign))


def _audience(campaign):
    rows = [m for m in db.members.values()
            if m["program_id"] == campaign["program_id"]
            and m["consent_status"] in ("SUBSCRIBED", "PAUSED")]
    if campaign["job_family_id"] is not None:
        rows = [m for m in rows
                if m["interest_job_family_id"] == campaign["job_family_id"]]
    rows.sort(key=lambda m: (m["created_at"], m["email"]))
    return rows


@bp.route("/nurture-campaigns/<campaign_id>/dispatch", methods=["POST"])
@require("CommunityManager")
def dispatch_campaign(campaign_id):
    campaign = calc.must_get(db.campaigns, campaign_id, "ERR_CAMPAIGN_NOT_FOUND")
    if campaign["state"] != "SCHEDULED":
        raise ApiError("ERR_CAMPAIGN_NOT_SCHEDULED", "The campaign is not SCHEDULED.")
    audience = _audience(campaign)
    if not any(m["consent_status"] == "SUBSCRIBED" for m in audience):
        raise ApiError("ERR_NO_CONSENTED_AUDIENCE",
                       "No member of the dispatch audience is SUBSCRIBED.")
    if campaign["scheduled_for"] is not None and db.clock() < campaign["scheduled_for"]:
        raise ApiError("ERR_DISPATCH_TOO_EARLY",
                       "The scheduled dispatch instant has not been reached.")
    program = db.programs[campaign["program_id"]]
    remaining = program["send_quota_total"] - calc.send_quota_used(program)
    if campaign["max_sends"] > remaining:
        raise ApiError("ERR_SEND_QUOTA_EXCEEDED",
                       "max_sends exceeds the program's remaining send quota.")

    now = db.clock()
    lower = now - timedelta(days=30)
    evaluated = audience[:campaign["max_sends"]]
    sequence_no = 0
    for member in evaluated:
        sequence_no += 1
        window_count = len([s for s in calc.member_sends(member["id"])
                            if s["outcome"] == "SENT"
                            and s["sent_at"] is not None and s["sent_at"] > lower])
        if member["consent_status"] != "SUBSCRIBED":
            outcome = "SUPPRESSED_CONSENT"
        elif window_count >= member["frequency_cap_per_30d"]:
            outcome = "SUPPRESSED_FREQUENCY"
        else:
            outcome = "SENT"
        row = {
            "id": db.new_id(),
            "campaign_id": campaign["id"],
            "member_id": member["id"],
            "outcome": outcome,
            "evaluated_at": now,
            "sent_at": now if outcome == "SENT" else None,
            "window_send_count_at_eval": window_count,
            "sequence_no": sequence_no,
            "created_at": db.wall_now(),
        }
        db.sends[row["id"]] = row
        if outcome == "SENT":
            db.touch(member)
    campaign["state"] = "DISPATCHED"
    campaign["dispatched_at"] = now
    db.touch(campaign)
    db.touch(program)
    return response.ok(serialize.campaign(campaign))


@bp.route("/nurture-campaigns/<campaign_id>/cancel", methods=["POST"])
@require("CommunityManager")
def cancel_campaign(campaign_id):
    data = V.body()
    V.field(data, "reason", "string", nullable=True, min_len=0, max_len=500)
    campaign = calc.must_get(db.campaigns, campaign_id, "ERR_CAMPAIGN_NOT_FOUND")
    if campaign["state"] not in ("DRAFT", "SCHEDULED"):
        raise ApiError("ERR_CAMPAIGN_ALREADY_TERMINAL",
                       "The campaign is already terminal.")
    campaign["state"] = "CANCELLED"
    db.touch(campaign)
    return response.ok(serialize.campaign(campaign))


@bp.route("/nurture-campaigns/<campaign_id>", methods=["GET"])
@require(*LIST_READ)
def get_campaign(campaign_id):
    campaign = calc.must_get(db.campaigns, campaign_id, "ERR_CAMPAIGN_NOT_FOUND")
    return response.ok(serialize.campaign(campaign))


@bp.route("/nurture-campaigns", methods=["GET"])
@require(*LIST_READ)
def list_campaigns():
    limit, offset = V.pagination()
    rows = calc.by_created(db.campaigns.values())
    for name in ("program_id", "job_family_id", "state"):
        value = V.qs(name)
        if value:
            rows = [r for r in rows if r[name] == value]
    page, meta = V.window(rows, limit, offset)
    return response.ok_list([serialize.campaign(r) for r in page], meta)


# ---------------------------------------------------------------- nurture sends
@bp.route("/nurture-sends/<send_id>", methods=["GET"])
@require(*LIST_READ)
def get_send(send_id):
    row = calc.must_get(db.sends, send_id, "ERR_RECORD_NOT_FOUND")
    return response.ok(serialize.send(row))


@bp.route("/nurture-sends", methods=["GET"])
@require(*LIST_READ)
def list_sends():
    limit, offset = V.pagination()
    rows = sorted(db.sends.values(), key=lambda r: (r["sequence_no"], r["created_at"]))
    for name in ("campaign_id", "member_id", "outcome"):
        value = V.qs(name)
        if value:
            rows = [r for r in rows if r[name] == value]
    page, meta = V.window(rows, limit, offset)
    return response.ok_list([serialize.send(r) for r in page], meta)
