"""Milestone and Legislator endpoints (PRD 3.1)."""

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
    f_dt,
    f_enum,
    f_str,
    get_body,
    must,
    must_fk,
    new_row,
    ok,
    ok_list,
    pagination,
    q_bool,
    q_str,
    require_role,
    touch,
)

bp = Blueprint("calendar", __name__)

MILESTONE_KINDS = ("COMMITTEE_HEARING", "FLOOR_VOTE", "RECESS", "SIGNING")
CHAMBERS = ("HOUSE", "SENATE")
STANCES = ("SUPPORT", "LEAN_SUPPORT", "UNDECIDED", "LEAN_OPPOSE", "OPPOSE")


# ---------------------------------------------------------------------------
# Milestones
# ---------------------------------------------------------------------------


@bp.post("/advocacy/milestones")
def create_milestone():
    require_role(R_DIRECTOR)
    body = get_body()
    campaign = must_fk("campaign", body, "campaign_id")
    check_shape(
        body, required=("campaign_id", "kind", "label", "window_start", "window_end")
    )
    kind = f_enum(body, "kind", MILESTONE_KINDS)
    label = f_str(body, "label", max_len=120)
    start = f_dt(body, "window_start")
    end = f_dt(body, "window_end")
    gates.gate_campaign_active(campaign, allow_draft=True)
    gates.gate_window_sane(start, end)
    gates.gate_window_inside_campaign(campaign, start, end)
    row = new_row()
    row.update(
        {
            "campaign_id": campaign["id"],
            "kind": kind,
            "label": label,
            "window_start": start,
            "window_end": end,
            "is_blackout": kind == "RECESS",
            "pressure_multiplier": calc.MILESTONE_PRESSURE_MULTIPLIER[kind],
            "status": "SCHEDULED",
            "reschedule_count": 0,
        }
    )
    row["status"] = calc.milestone_status(row)
    db.milestones[row["id"]] = row
    return ok(S.milestone_out(row), 201)


@bp.get("/advocacy/milestones/<milestone_id>")
def get_milestone(milestone_id):
    require_role(R_DIRECTOR, R_COMPLIANCE, R_ORGANIZER, R_STRATEGIST)
    row = must("milestone", milestone_id)
    return ok(S.milestone_out(row))


@bp.get("/advocacy/milestones")
def list_milestones():
    require_role(R_DIRECTOR, R_COMPLIANCE, R_ORGANIZER, R_STRATEGIST)
    limit, offset = pagination()
    campaign_id = q_str("campaign_id")
    kind = q_str("kind")
    is_blackout = q_bool("is_blackout")
    status = q_str("status")
    calc.refresh_milestone_statuses()
    rows = by_created(list(db.milestones.values()))
    if campaign_id is not None:
        rows = [r for r in rows if r["campaign_id"] == campaign_id]
    if kind is not None:
        rows = [r for r in rows if r["kind"] == kind]
    if is_blackout is not None:
        rows = [r for r in rows if bool(r["is_blackout"]) is is_blackout]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return ok_list([S.milestone_out(r) for r in rows], limit, offset)


@bp.post("/advocacy/milestones/<milestone_id>/reschedule")
def reschedule_milestone(milestone_id):
    require_role(R_DIRECTOR)
    milestone = must("milestone", milestone_id)
    campaign = db.campaigns[milestone["campaign_id"]]
    body = get_body()
    check_shape(body, required=("window_start", "window_end"))
    start = f_dt(body, "window_start")
    end = f_dt(body, "window_end")
    gates.gate_campaign_active(campaign)
    gates.gate_window_sane(start, end)
    gates.gate_window_inside_campaign(campaign, start, end)
    milestone["window_start"] = start
    milestone["window_end"] = end
    milestone["reschedule_count"] = int(milestone["reschedule_count"]) + 1
    milestone["status"] = calc.milestone_status(milestone)
    touch(milestone)
    calc.cascade(campaign, revalidate=True)
    return ok(S.milestone_out(milestone))


# ---------------------------------------------------------------------------
# Legislators
# ---------------------------------------------------------------------------


@bp.post("/advocacy/legislators")
def create_legislator():
    require_role(R_DIRECTOR, R_ORGANIZER)
    body = get_body()
    campaign = must_fk("campaign", body, "campaign_id")
    check_shape(
        body,
        required=("campaign_id", "full_name", "district_code", "chamber"),
        optional=("stance",),
    )
    full_name = f_str(body, "full_name", max_len=120)
    district = f_str(body, "district_code", max_len=16)
    chamber = f_enum(body, "chamber", CHAMBERS)
    stance = f_enum(body, "stance", STANCES, required=False) or "UNDECIDED"
    gates.gate_campaign_active(campaign, allow_draft=True)
    row = new_row()
    row.update(
        {
            "campaign_id": campaign["id"],
            "full_name": full_name,
            "district_code": district,
            "chamber": chamber,
            "stance": stance,
            "initial_stance": stance,
            # PRD 3.1: a new legislator starts at exactly 0.00 / MONITOR; the
            # pressure index only runs on the first mutation that touches it.
            "contact_pressure_score": dec("0.00"),
            "priority_tier": "MONITOR",
            "constituent_action_count": 0,
            "meeting_held_count": 0,
        }
    )
    db.legislators[row["id"]] = row
    return ok(S.legislator_out(row), 201)


@bp.get("/advocacy/legislators/<legislator_id>")
def get_legislator(legislator_id):
    require_role(R_DIRECTOR, R_COMPLIANCE, R_ORGANIZER, R_STRATEGIST)
    row = must("legislator", legislator_id)
    return ok(S.legislator_out(row))


@bp.get("/advocacy/legislators")
def list_legislators():
    require_role(R_DIRECTOR, R_COMPLIANCE, R_ORGANIZER, R_STRATEGIST)
    limit, offset = pagination()
    campaign_id = q_str("campaign_id")
    district = q_str("district_code")
    chamber = q_str("chamber")
    stance = q_str("stance")
    tier = q_str("priority_tier")
    rows = by_created(list(db.legislators.values()))
    if campaign_id is not None:
        rows = [r for r in rows if r["campaign_id"] == campaign_id]
    if district is not None:
        rows = [r for r in rows if r["district_code"] == district]
    if chamber is not None:
        rows = [r for r in rows if r["chamber"] == chamber]
    if stance is not None:
        rows = [r for r in rows if r["stance"] == stance]
    if tier is not None:
        rows = [r for r in rows if r["priority_tier"] == tier]
    return ok_list([S.legislator_out(r) for r in rows], limit, offset)


@bp.post("/advocacy/legislators/<legislator_id>/stance-updates")
def update_stance(legislator_id):
    require_role(R_DIRECTOR, R_ORGANIZER)
    legislator = must("legislator", legislator_id)
    campaign = db.campaigns[legislator["campaign_id"]]
    body = get_body()
    check_shape(body, required=("stance", "evidence_note"))
    stance = f_enum(body, "stance", STANCES)
    f_str(body, "evidence_note", max_len=400)
    gates.gate_campaign_active(campaign)
    legislator["stance"] = stance
    touch(legislator)
    calc.refresh_legislator(legislator)
    calc.refresh_posture(campaign)
    return ok(S.legislator_out(legislator))
