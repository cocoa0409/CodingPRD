"""Logical clock + Campaign endpoints (PRD 3.1, 3.4 resolution, 3.9)."""

from flask import Blueprint, g

import calc
import cascades
import gates
import serializers as S
from common import (
    ALL_ROLES,
    Clock,
    R_COMPLIANCE,
    R_DIRECTOR,
    R_ORGANIZER,
    R_PARTNER,
    R_STRATEGIST,
    by_created,
    check_shape,
    db,
    err,
    f_dt,
    f_enum,
    f_int,
    f_str,
    fmt_dt,
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

bp = Blueprint("campaign", __name__)


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5)
# ---------------------------------------------------------------------------


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_role(*ALL_ROLES)
    body = get_body()
    check_shape(body, required=("current_utc",))
    new_value = f_dt(body, "current_utc")
    previous = now_dt()
    Clock.now = new_value
    calc.refresh_milestone_statuses()
    return ok(
        {"current_utc": fmt_dt(new_value), "previous_utc": fmt_dt(previous)}
    )


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------

CHAMBERS = ("HOUSE", "SENATE", "BOTH")
CAMPAIGN_STATUSES = ("DRAFT", "ACTIVE", "CLOSED")
POSTURES = ("OPEN", "RESTRICTED", "FROZEN")
OVERRIDES = ("NONE", "FORCE_OPEN", "FORCE_FROZEN")


@bp.post("/advocacy/campaigns")
def create_campaign():
    require_role(R_DIRECTOR)
    body = get_body()
    check_shape(
        body,
        required=(
            "name",
            "goal_statement",
            "bill_reference",
            "target_chamber",
            "start_date",
            "end_date",
            "success_metric_target_actions",
            "success_metric_target_supporters",
            "funded_total_cents",
        ),
    )
    name = f_str(body, "name", max_len=160)
    goal = f_str(body, "goal_statement", max_len=400)
    bill = f_str(body, "bill_reference", max_len=40)
    chamber = f_enum(body, "target_chamber", CHAMBERS)
    start = f_dt(body, "start_date")
    end = f_dt(body, "end_date")
    actions = f_int(body, "success_metric_target_actions", minimum=0)
    supporters = f_int(body, "success_metric_target_supporters", minimum=0)
    funded = f_int(body, "funded_total_cents", minimum=0)
    if not (end > start):
        err("ERR_INVALID_REQUEST", "end_date must be strictly after start_date")
    row = new_row()
    row.update(
        {
            "name": name,
            "goal_statement": goal,
            "bill_reference": bill,
            "target_chamber": chamber,
            "start_date": start,
            "end_date": end,
            "success_metric_target_actions": actions,
            "success_metric_target_supporters": supporters,
            "funded_total_cents": funded,
            "status": "DRAFT",
            "posture_override": "NONE",
            "posture": "OPEN",
            "blocked_activation_count": 0,
            "opposed_priority_legislator_count": 0,
            "total_actions_logged": 0,
            "distinct_acting_supporter_count": 0,
            "committed_share_total_cents": 0,
        }
    )
    db.campaigns[row["id"]] = row
    return ok(S.campaign_out(row), 201)


@bp.get("/advocacy/campaigns/<campaign_id>")
def get_campaign(campaign_id):
    require_role(R_DIRECTOR, R_COMPLIANCE, R_ORGANIZER, R_STRATEGIST, R_PARTNER)
    campaign = must("campaign", campaign_id)
    return ok(S.campaign_out(campaign))


@bp.get("/advocacy/campaigns")
def list_campaigns():
    require_role(R_DIRECTOR, R_COMPLIANCE, R_ORGANIZER, R_STRATEGIST)
    limit, offset = pagination()
    status = q_str("status")
    posture = q_str("posture")
    rows = by_created(list(db.campaigns.values()))
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if posture is not None:
        rows = [r for r in rows if r["posture"] == posture]
    return ok_list([S.campaign_out(r) for r in rows], limit, offset)


@bp.post("/advocacy/campaigns/<campaign_id>/launch")
def launch_campaign(campaign_id):
    require_role(R_DIRECTOR)
    campaign = must("campaign", campaign_id)
    gates.gate_state(campaign["status"], ("DRAFT",))
    if not calc.legislators_of(campaign_id):
        err("ERR_NO_TARGET_LEGISLATOR", "a campaign needs at least one legislator")
    campaign["status"] = "ACTIVE"
    touch(campaign)
    calc.refresh_posture(campaign)
    return ok(S.campaign_out(campaign))


@bp.post("/advocacy/campaigns/<campaign_id>/close")
def close_campaign(campaign_id):
    require_role(R_DIRECTOR)
    campaign = must("campaign", campaign_id)
    gates.gate_state(campaign["status"], ("ACTIVE",))
    for activation in calc.activations_of(campaign_id):
        if activation["delivery_state"] == "SENDING":
            err(
                "ERR_ACTIVATION_IN_FLIGHT",
                "a wave is still SENDING; complete or abort it first",
            )
    cascades.close_campaign(campaign)
    return ok(S.campaign_out(campaign))


@bp.post("/advocacy/campaigns/<campaign_id>/posture-overrides")
def set_posture_override(campaign_id):
    require_role(R_DIRECTOR)
    campaign = must("campaign", campaign_id)
    body = get_body()
    check_shape(body, required=("posture_override", "override_reason"))
    override = f_enum(body, "posture_override", OVERRIDES)
    f_str(body, "override_reason", max_len=400)
    # PRD 3.1: "In every case the override is stored, the posture is re-derived
    # ... a CLOSED campaign stays FROZEN regardless" -- the closed branch of the
    # posture ladder is what enforces that, not a rejection.
    campaign["posture_override"] = override
    touch(campaign)
    calc.refresh_posture(campaign)
    return ok(S.campaign_out(campaign))


@bp.post("/advocacy/campaigns/<campaign_id>/message-test-resolutions")
def resolve_message_test(campaign_id):
    require_role(R_STRATEGIST)
    campaign = must("campaign", campaign_id)
    body = get_body()
    winner = must_fk("variant", body, "winning_message_variant_id")
    check_shape(body, required=("test_cell", "winning_message_variant_id"))
    test_cell = f_str(body, "test_cell", max_len=60)
    gates.gate_campaign_active(campaign)
    cell = [
        v
        for v in calc.variants_of(campaign_id)
        if v["test_cell"] == test_cell
    ]
    if winner not in cell:
        err("ERR_NO_ELIGIBLE_VARIANT", "the named winner is not in that test cell")
    if not [v for v in cell if v["status"] == "LOCKED"]:
        err("ERR_NO_ELIGIBLE_VARIANT", "no variant in that test cell is LOCKED")
    if winner["status"] != "LOCKED":
        err("ERR_NO_ELIGIBLE_VARIANT", "the named winner is not LOCKED")
    if int(winner["realized_reach_total"]) < calc.MIN_TEST_REACH:
        err(
            "ERR_REACH_BELOW_MINIMUM",
            "the winner's realized_reach_total is below the minimum test reach",
        )
    for variant in cell:
        calc.refresh_variant_metrics(variant)
    for variant in cell:
        if variant["id"] == winner["id"]:
            if variant["test_winner"] is not True:
                variant["test_winner"] = True
                touch(variant)
            continue
        if variant["status"] in ("APPROVED", "LOCKED"):
            cascades.retire_variant(variant)
        elif variant["test_winner"] is not False:
            variant["test_winner"] = False
            touch(variant)
    calc.cascade(campaign)
    return ok(S.variant_out(winner))


@bp.get("/advocacy/campaigns/<campaign_id>/outcome-report")
def get_outcome_report(campaign_id):
    require_role(R_DIRECTOR, R_COMPLIANCE)
    campaign = must("campaign", campaign_id)
    return ok(calc.outcome_report(campaign))


@bp.get("/advocacy/campaigns/<campaign_id>/milestones")
def list_campaign_milestones(campaign_id):
    require_role(R_DIRECTOR, R_COMPLIANCE, R_ORGANIZER, R_STRATEGIST)
    must("campaign", campaign_id)
    limit, offset = pagination()
    kind = q_str("kind")
    rows = calc.milestones_of(campaign_id)
    if kind is not None:
        rows = [r for r in rows if r["kind"] == kind]
    return ok_list([S.milestone_out(r) for r in rows], limit, offset)


@bp.get("/advocacy/campaigns/<campaign_id>/coalition-partners")
def list_campaign_partners(campaign_id):
    require_role(R_DIRECTOR, R_COMPLIANCE, R_STRATEGIST, R_PARTNER)
    must("campaign", campaign_id)
    limit, offset = pagination()
    status = q_str("status")
    rows = calc.partners_of(campaign_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return ok_list([S.partner_out(r) for r in rows], limit, offset)
