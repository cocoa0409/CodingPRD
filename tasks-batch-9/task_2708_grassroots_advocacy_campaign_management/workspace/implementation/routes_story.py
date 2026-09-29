"""Spokesperson profiles and in-district meetings (PRD 3.8)."""

from flask import Blueprint

import calc
import gates
import serializers as S
from common import (
    R_COMPLIANCE,
    R_DIRECTOR,
    R_ORGANIZER,
    R_STRATEGIST,
    R_SUPPORTER,
    by_created,
    check_shape,
    db,
    dec,
    err,
    f_dt,
    f_enum,
    f_int,
    f_str,
    get_body,
    must,
    must_fk,
    new_row,
    now_dt,
    ok,
    ok_list,
    pagination,
    q_bool,
    q_str,
    require_role,
    touch,
)

bp = Blueprint("story", __name__)

PUBLICATION_CONSENTS = ("WITHHELD", "INTERNAL", "PUBLIC")
TRAINING_STATES = ("UNTRAINED", "TRAINED", "CERTIFIED")


# ---------------------------------------------------------------------------
# Spokesperson profiles
# ---------------------------------------------------------------------------


@bp.post("/advocacy/spokespersons")
def create_spokesperson():
    require_role(R_ORGANIZER, R_DIRECTOR, R_SUPPORTER)
    body = get_body()
    sup = must_fk("supporter", body, "supporter_id")
    check_shape(
        body,
        required=("supporter_id", "story_summary"),
        optional=("publication_consent",),
    )
    story = f_str(body, "story_summary", max_len=1000)
    consent = f_enum(body, "publication_consent", PUBLICATION_CONSENTS, required=False)
    if consent is None:
        consent = "WITHHELD"
    gates.gate_owner_supporter(sup["id"])
    campaign = db.campaigns[sup["campaign_id"]]
    gates.gate_campaign_active(campaign)
    gates.gate_contactable_any(sup)
    if calc.profiles_of_supporter(sup["id"]):
        err(
            "ERR_DUPLICATE_SPOKESPERSON",
            "a spokesperson profile already exists for this supporter",
        )
    row = new_row()
    row.update(
        {
            "supporter_id": sup["id"],
            "story_summary": story,
            "publication_consent": consent,
            "training_state": "UNTRAINED",
            "training_sessions_completed": 0,
            "media_ready": False,
        }
    )
    db.spokespersons[row["id"]] = row
    return ok(S.spokesperson_out(row), 201)


@bp.get("/advocacy/spokespersons/<spokesperson_id>")
def get_spokesperson(spokesperson_id):
    require_role(R_DIRECTOR, R_COMPLIANCE, R_ORGANIZER, R_SUPPORTER)
    row = must("spokesperson", spokesperson_id)
    gates.gate_owner_supporter(row["supporter_id"])
    return ok(S.spokesperson_out(row))


@bp.get("/advocacy/spokespersons")
def list_spokespersons():
    require_role(R_DIRECTOR, R_COMPLIANCE, R_ORGANIZER, R_STRATEGIST)
    limit, offset = pagination()
    rows = by_created(list(db.spokespersons.values()))
    for param in ("supporter_id", "training_state", "publication_consent"):
        value = q_str(param)
        if value is not None:
            rows = [r for r in rows if r[param] == value]
    media_ready = q_bool("media_ready")
    if media_ready is not None:
        rows = [r for r in rows if bool(r["media_ready"]) is media_ready]
    return ok_list([S.spokesperson_out(r) for r in rows], limit, offset)


@bp.post("/advocacy/spokespersons/<spokesperson_id>/training-advancements")
def advance_training(spokesperson_id):
    require_role(R_ORGANIZER, R_DIRECTOR)
    profile = must("spokesperson", spokesperson_id)
    body = get_body()
    check_shape(body, required=("to_level", "session_reference"))
    to_level = f_enum(body, "to_level", ("TRAINED", "CERTIFIED"))
    f_str(body, "session_reference", max_len=200)
    sup = db.supporters[profile["supporter_id"]]
    campaign = db.campaigns[sup["campaign_id"]]
    gates.gate_campaign_active(campaign)
    if to_level == "TRAINED":
        gates.gate_state(profile["training_state"], ("UNTRAINED",))
    else:
        gates.gate_state(profile["training_state"], ("TRAINED",))
        if profile["publication_consent"] != "PUBLIC":
            err(
                "ERR_STORY_CONSENT_REQUIRED",
                "certification requires publication_consent PUBLIC",
            )
    profile["training_state"] = to_level
    profile["training_sessions_completed"] = (
        int(profile["training_sessions_completed"]) + 1
    )
    profile["media_ready"] = (
        to_level == "CERTIFIED" and profile["publication_consent"] == "PUBLIC"
    )
    touch(profile)
    # the story bonus moved, so both supporter scores and every segment recompute
    calc.refresh_supporter_counters(sup)
    calc.cascade(campaign, segments=True, reach=True, revalidate=True)
    return ok(S.spokesperson_out(profile))


# ---------------------------------------------------------------------------
# In-district meetings
# ---------------------------------------------------------------------------


@bp.post("/advocacy/district-meetings")
def create_meeting():
    require_role(R_ORGANIZER, R_DIRECTOR)
    body = get_body()
    campaign = must_fk("campaign", body, "campaign_id")
    legislator = must_fk("legislator", body, "legislator_id")
    profile = must_fk("spokesperson", body, "lead_spokesperson_id")
    check_shape(
        body,
        required=(
            "campaign_id",
            "legislator_id",
            "lead_spokesperson_id",
            "location_district_code",
            "window_start",
            "window_end",
        ),
    )
    district = f_str(body, "location_district_code", max_len=16)
    start = f_dt(body, "window_start")
    end = f_dt(body, "window_end")
    lead_sup = db.supporters[profile["supporter_id"]]
    gates.gate_campaign_active(campaign)
    gates.gate_not_frozen(campaign)
    gates.gate_contactable(lead_sup, "EMAIL")
    gates.gate_window_sane(start, end)
    gates.gate_window_inside_campaign(campaign, start, end)
    gates.gate_meeting_conflict(legislator["id"], start, end)
    if profile["training_state"] != "CERTIFIED":
        err(
            "ERR_SPOKESPERSON_NOT_CERTIFIED",
            "the lead spokesperson is not CERTIFIED",
        )
    if legislator["campaign_id"] != campaign["id"] or (
        lead_sup["campaign_id"] != campaign["id"]
    ):
        err("ERR_CAMPAIGN_MISMATCH", "co-referenced rows name different campaigns")
    if district != legislator["district_code"]:
        err(
            "ERR_DISTRICT_MISMATCH",
            "location_district_code must equal the legislator's district",
        )
    if lead_sup["district_code"] != district:
        err(
            "ERR_DISTRICT_MISMATCH",
            "the lead spokesperson does not live in the meeting district",
        )
    row = new_row()
    row.update(
        {
            "campaign_id": campaign["id"],
            "legislator_id": legislator["id"],
            "lead_spokesperson_id": profile["id"],
            "location_district_code": district,
            "window_start": start,
            "window_end": end,
            "status": "REQUESTED",
            "attendee_count": None,
            "pressure_credit": dec("0.00"),
            "decline_reason": None,
        }
    )
    db.meetings[row["id"]] = row
    return ok(S.meeting_out(row), 201)


@bp.get("/advocacy/district-meetings/<meeting_id>")
def get_meeting(meeting_id):
    require_role(R_DIRECTOR, R_COMPLIANCE, R_ORGANIZER, R_STRATEGIST)
    row = must("meeting", meeting_id)
    return ok(S.meeting_out(row))


@bp.get("/advocacy/district-meetings")
def list_meetings():
    require_role(R_DIRECTOR, R_COMPLIANCE, R_ORGANIZER, R_STRATEGIST)
    limit, offset = pagination()
    rows = by_created(list(db.meetings.values()))
    for param in (
        "campaign_id",
        "legislator_id",
        "lead_spokesperson_id",
        "location_district_code",
        "status",
    ):
        value = q_str(param)
        if value is not None:
            rows = [r for r in rows if r[param] == value]
    return ok_list([S.meeting_out(r) for r in rows], limit, offset)


@bp.post("/advocacy/district-meetings/<meeting_id>/response")
def meeting_response(meeting_id):
    require_role(R_ORGANIZER, R_DIRECTOR)
    meeting = must("meeting", meeting_id)
    body = get_body()
    check_shape(body, required=("decision",), optional=("decline_reason",))
    decision = f_enum(body, "decision", ("CONFIRM", "DECLINE"))
    reason = f_str(body, "decline_reason", max_len=400, required=False)
    campaign = db.campaigns[meeting["campaign_id"]]
    gates.gate_campaign_active(campaign)
    gates.gate_state(meeting["status"], ("REQUESTED",))
    if decision == "CONFIRM":
        profile = db.spokespersons[meeting["lead_spokesperson_id"]]
        # deliberately re-checked at response time rather than trusted
        if profile["training_state"] != "CERTIFIED":
            err(
                "ERR_SPOKESPERSON_NOT_CERTIFIED",
                "the lead spokesperson is no longer CERTIFIED",
            )
        meeting["status"] = "CONFIRMED"
    else:
        meeting["status"] = "DECLINED"
        meeting["decline_reason"] = reason
    touch(meeting)
    return ok(S.meeting_out(meeting))


@bp.post("/advocacy/district-meetings/<meeting_id>/complete")
def complete_meeting(meeting_id):
    require_role(R_ORGANIZER, R_DIRECTOR)
    meeting = must("meeting", meeting_id)
    body = get_body()
    check_shape(body, required=("attendee_count",))
    attendees = f_int(body, "attendee_count", minimum=0)
    campaign = db.campaigns[meeting["campaign_id"]]
    gates.gate_campaign_active(campaign)
    gates.gate_state(meeting["status"], ("CONFIRMED",))
    if now_dt() < meeting["window_end"]:
        err(
            "ERR_INVALID_STATE_TRANSITION",
            "a meeting cannot be reported before its window has ended",
        )
    meeting["attendee_count"] = attendees
    if attendees == 0:
        # NO_SHOW moves no legislator or supporter counter at all
        meeting["status"] = "NO_SHOW"
        touch(meeting)
        return ok(S.meeting_out(meeting))
    meeting["status"] = "HELD"
    meeting["pressure_credit"] = calc.MEETING_PRESSURE_CREDIT.quantize(dec("0.01"))
    touch(meeting)
    legislator = db.legislators.get(meeting["legislator_id"])
    if legislator is not None:
        calc.refresh_legislator(legislator)
    profile = db.spokespersons.get(meeting["lead_spokesperson_id"])
    if profile is not None:
        lead_sup = db.supporters.get(profile["supporter_id"])
        if lead_sup is not None:
            # the meeting-lead bonus applies to the campaign-final variant only
            new_retention = calc.retention_score(lead_sup)
            if lead_sup["retention_score"] != new_retention:
                lead_sup["retention_score"] = new_retention
                touch(lead_sup)
    calc.refresh_posture(campaign)
    return ok(S.meeting_out(meeting))
