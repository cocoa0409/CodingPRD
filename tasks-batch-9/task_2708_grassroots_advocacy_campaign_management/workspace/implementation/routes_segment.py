"""Segment endpoints (PRD 3.5)."""

from flask import Blueprint

import calc
import gates
import serializers as S
from common import (
    R_COMPLIANCE,
    R_DIRECTOR,
    R_ORGANIZER,
    R_STRATEGIST,
    by_created,
    check_shape,
    db,
    dec,
    f_enum,
    f_num,
    f_str,
    f_str_list,
    get_body,
    must,
    must_fk,
    new_row,
    now_dt,
    ok,
    ok_list,
    pagination,
    q_str,
    require_role,
    touch,
)

bp = Blueprint("segment", __name__)

SOURCES = ("PETITION", "EVENT", "DIGITAL_AD", "REFERRAL")


@bp.post("/advocacy/segments")
def create_segment():
    require_role(R_STRATEGIST, R_DIRECTOR)
    body = get_body()
    campaign = must_fk("campaign", body, "campaign_id")
    check_shape(
        body,
        required=("campaign_id", "name", "rule_required_channel"),
        optional=("rule_district_codes", "rule_min_engagement_score", "rule_sources"),
    )
    name = f_str(body, "name", max_len=120)
    channel = f_enum(body, "rule_required_channel", calc.CHANNELS)
    districts = f_str_list(
        body, "rule_district_codes", required=False, max_len=16
    )
    floor = f_num(body, "rule_min_engagement_score", required=False, minimum=0)
    sources = f_str_list(body, "rule_sources", choices=SOURCES, required=False)
    gates.gate_campaign_active(campaign)
    row = new_row()
    row.update(
        {
            "campaign_id": campaign["id"],
            "name": name,
            "rule_required_channel": channel,
            "rule_district_codes": districts if districts is not None else [],
            "rule_min_engagement_score": (
                dec("0.00") if floor is None else calc.r2(floor)
            ),
            "rule_sources": sources if sources is not None else [],
            "member_supporter_ids": [],
            "member_count": 0,
            "active_activation_count": 0,
            "last_refreshed_at": None,
        }
    )
    db.segments[row["id"]] = row
    calc.refresh_segment_membership(row)
    row["version"] = 1
    row["updated_at"] = row["created_at"]
    return ok(S.segment_out(row), 201)


@bp.get("/advocacy/segments/<segment_id>")
def get_segment(segment_id):
    require_role(R_DIRECTOR, R_COMPLIANCE, R_ORGANIZER, R_STRATEGIST)
    row = must("segment", segment_id)
    return ok(S.segment_out(row))


@bp.get("/advocacy/segments")
def list_segments():
    require_role(R_DIRECTOR, R_COMPLIANCE, R_ORGANIZER, R_STRATEGIST)
    limit, offset = pagination()
    campaign_id = q_str("campaign_id")
    channel = q_str("rule_required_channel")
    rows = by_created(list(db.segments.values()))
    if campaign_id is not None:
        rows = [r for r in rows if r["campaign_id"] == campaign_id]
    if channel is not None:
        rows = [r for r in rows if r["rule_required_channel"] == channel]
    return ok_list([S.segment_out(r) for r in rows], limit, offset)


@bp.post("/advocacy/segments/<segment_id>/refresh")
def refresh_segment(segment_id):
    require_role(R_STRATEGIST, R_DIRECTOR)
    segment = must("segment", segment_id)
    campaign = db.campaigns[segment["campaign_id"]]
    gates.gate_campaign_active(campaign)
    members = []
    for sup in calc.supporters_of(segment["campaign_id"]):
        if calc.consent_state(sup, segment["rule_required_channel"]) != "GRANTED":
            continue
        if sup["suppressed"]:
            continue
        if (
            segment["rule_district_codes"]
            and sup["district_code"] not in segment["rule_district_codes"]
        ):
            continue
        if dec(sup["engagement_score"]) < dec(segment["rule_min_engagement_score"]):
            continue
        if (
            segment["rule_sources"]
            and sup["acquisition_source"] not in segment["rule_sources"]
        ):
            continue
        members.append(sup["id"])
    segment["member_supporter_ids"] = members
    segment["member_count"] = len(members)
    segment["last_refreshed_at"] = now_dt()
    # PRD 3.5: an explicit refresh always increments the segment's version.
    touch(segment)
    calc.cascade(campaign, reach=True, revalidate=True)
    return ok(S.segment_out(segment))
