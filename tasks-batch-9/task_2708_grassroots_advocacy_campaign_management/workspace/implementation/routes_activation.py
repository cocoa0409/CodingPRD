"""Activation endpoints (PRD 3.5, 3.6)."""

from flask import Blueprint, g

import calc
import cascades
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
    q_str,
    require_role,
    touch,
)

bp = Blueprint("activation", __name__)


def _surge_grant(campaign, milestone, start, end):
    """Step two of the pinned touch-cap evaluation order (PRD 3.5)."""
    if milestone is None:
        return 0
    if milestone["kind"] not in ("COMMITTEE_HEARING", "FLOOR_VOTE"):
        return 0
    if not (milestone["window_start"] <= start and end <= milestone["window_end"]):
        return 0
    posture = campaign["posture"]
    if posture == "OPEN":
        return calc.SURGE_GRANT_OPEN
    if posture == "RESTRICTED":
        return calc.SURGE_GRANT_RESTRICTED
    return 0


@bp.post("/advocacy/activations")
def create_activation():
    require_role(R_DIRECTOR, R_STRATEGIST)
    body = get_body()
    campaign = must_fk("campaign", body, "campaign_id")
    segment = must_fk("segment", body, "segment_id")
    variant = must_fk("variant", body, "message_variant_id")
    milestone = must_fk("milestone", body, "milestone_id", required=False)
    check_shape(
        body,
        required=(
            "campaign_id",
            "segment_id",
            "message_variant_id",
            "channel",
            "window_start",
            "window_end",
            "expected_segment_version",
        ),
        optional=("milestone_id", "min_viable_reach"),
    )
    channel = f_enum(body, "channel", calc.CHANNELS)
    start = f_dt(body, "window_start")
    end = f_dt(body, "window_end")
    expected = f_int(body, "expected_segment_version", minimum=0)
    min_viable = f_int(body, "min_viable_reach", required=False, minimum=1)
    if min_viable is None:
        min_viable = 1
    gates.gate_segment_version(segment, expected)
    gates.gate_campaign_active(campaign)
    gates.gate_not_frozen(campaign)
    gates.gate_not_restricted(campaign, channel)
    gates.gate_window_sane(start, end)
    gates.gate_window_inside_campaign(campaign, start, end)
    gates.gate_blackout(campaign["id"], start, end)
    gates.gate_channel_saturation(campaign["id"], channel, start, end)
    if variant["status"] != "LOCKED":
        err("ERR_VARIANT_NOT_LOCKED", "an activation may only name a LOCKED variant")
    for related in (segment, variant):
        if related["campaign_id"] != campaign["id"]:
            err("ERR_CAMPAIGN_MISMATCH", "co-referenced rows name different campaigns")
    if milestone is not None and milestone["campaign_id"] != campaign["id"]:
        err("ERR_CAMPAIGN_MISMATCH", "co-referenced rows name different campaigns")
    if channel not in variant["channel_scope"]:
        err(
            "ERR_CHANNEL_NOT_IN_VARIANT_SCOPE",
            "the channel is not inside the variant's channel_scope",
        )
    if int(segment["member_count"]) == 0:
        err("ERR_SEGMENT_EMPTY", "the target segment has no members")
    # Steps 1-4 of the pinned evaluation order; step 5 (posture) runs last.
    grant = _surge_grant(campaign, milestone, start, end)
    row = new_row()
    row.update(
        {
            "campaign_id": campaign["id"],
            "segment_id": segment["id"],
            "message_variant_id": variant["id"],
            "milestone_id": milestone["id"] if milestone else None,
            "channel": channel,
            "window_start": start,
            "window_end": end,
            "min_viable_reach": min_viable,
            "approval_state": "PENDING",
            "delivery_state": "SCHEDULED",
            "effective_touch_cap": calc.BASE_TOUCH_CAP_PER_SUPPORTER + grant,
            "target_supporter_ids": [],
            "projected_reach": 0,
            "realized_reach": None,
            "delivered_count": None,
            "bounced_count": None,
            "send_cost_cents": 0,
            "suppressed_by_consent_count": 0,
            "abort_reason": None,
            "_created_by_user_id": g.user_id,
        }
    )
    targets = calc.eligible_targets(row, segment)
    if len(targets) == 0:
        err(
            "ERR_FREQUENCY_CAP_EXHAUSTED",
            "every segment member already sits at the wave's effective_touch_cap",
        )
    if len(targets) < min_viable:
        err(
            "ERR_REACH_BELOW_MINIMUM",
            "projected reach %d is below min_viable_reach %d"
            % (len(targets), min_viable),
        )
    row["target_supporter_ids"] = targets
    row["projected_reach"] = len(targets)
    db.activations[row["id"]] = row
    calc.take_reservations(targets)
    for supporter_id in targets:
        sup = db.supporters.get(supporter_id)
        if sup is not None:
            touch(sup)
    calc.refresh_segment_activation_count(segment)
    calc.refresh_posture(campaign)
    return ok(S.activation_out(row), 201)


@bp.get("/advocacy/activations/<activation_id>")
def get_activation(activation_id):
    require_role(R_DIRECTOR, R_COMPLIANCE, R_ORGANIZER, R_STRATEGIST)
    row = must("activation", activation_id)
    return ok(S.activation_out(row))


@bp.get("/advocacy/activations")
def list_activations():
    require_role(R_DIRECTOR, R_COMPLIANCE, R_ORGANIZER, R_STRATEGIST)
    limit, offset = pagination()
    filters = (
        ("campaign_id", "campaign_id"),
        ("segment_id", "segment_id"),
        ("message_variant_id", "message_variant_id"),
        ("milestone_id", "milestone_id"),
        ("channel", "channel"),
        ("approval_state", "approval_state"),
        ("delivery_state", "delivery_state"),
    )
    rows = by_created(list(db.activations.values()))
    for param, field in filters:
        value = q_str(param)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return ok_list([S.activation_out(r) for r in rows], limit, offset)


def _clearance_preconditions(activation, campaign):
    variant = db.variants.get(activation["message_variant_id"])
    if variant is None or variant["status"] != "LOCKED":
        err("ERR_VARIANT_NOT_LOCKED", "the wave's variant is not LOCKED")
    if int(activation["projected_reach"] or 0) < int(activation["min_viable_reach"]):
        err(
            "ERR_REACH_BELOW_MINIMUM",
            "projected reach has fallen below min_viable_reach",
        )


@bp.post("/advocacy/activations/<activation_id>/clear")
def clear_activation(activation_id):
    require_role(R_COMPLIANCE)
    activation = must("activation", activation_id)
    campaign = db.campaigns[activation["campaign_id"]]
    body = get_body()
    check_shape(body, required=("clearance_note",))
    f_str(body, "clearance_note", max_len=400)
    gates.gate_campaign_active(campaign)
    gates.gate_not_frozen(campaign)
    gates.gate_not_restricted(campaign, activation["channel"])
    if activation["delivery_state"] != "SCHEDULED":
        err(
            "ERR_INVALID_STATE_TRANSITION",
            "clearance requires delivery_state SCHEDULED",
        )
    gates.gate_state(activation["approval_state"], ("PENDING", "BLOCKED"))
    gates.gate_sod(activation.get("_created_by_user_id"))
    gates.gate_blackout(
        campaign["id"], activation["window_start"], activation["window_end"]
    )
    _clearance_preconditions(activation, campaign)
    activation["approval_state"] = "CLEARED"
    touch(activation)
    calc.refresh_posture(campaign)
    return ok(S.activation_out(activation))


@bp.post("/advocacy/activations/<activation_id>/block")
def block_activation(activation_id):
    require_role(R_COMPLIANCE)
    activation = must("activation", activation_id)
    campaign = db.campaigns[activation["campaign_id"]]
    body = get_body()
    check_shape(body, required=("block_reason",))
    f_str(body, "block_reason", max_len=400)
    gates.gate_campaign_active(campaign)
    if activation["delivery_state"] != "SCHEDULED":
        err("ERR_INVALID_STATE_TRANSITION", "blocking requires delivery_state SCHEDULED")
    gates.gate_state(activation["approval_state"], ("PENDING", "CLEARED"))
    activation["approval_state"] = "BLOCKED"
    touch(activation)
    calc.refresh_posture(campaign)
    return ok(S.activation_out(activation))


@bp.post("/advocacy/activations/<activation_id>/start-send")
def start_send(activation_id):
    require_role(R_DIRECTOR, R_ORGANIZER)
    activation = must("activation", activation_id)
    campaign = db.campaigns[activation["campaign_id"]]
    gates.gate_campaign_active(campaign)
    gates.gate_not_frozen(campaign)
    gates.gate_not_restricted(campaign, activation["channel"])
    gates.gate_state(activation["delivery_state"], ("SCHEDULED",))
    if activation["approval_state"] != "CLEARED":
        err("ERR_INVALID_STATE_TRANSITION", "the wave has not been cleared")
    clock = now_dt()
    if clock < activation["window_start"] or clock > activation["window_end"]:
        err(
            "ERR_OUTSIDE_SEND_WINDOW",
            "the logical clock is outside the wave's closed send window",
        )
    activation["delivery_state"] = "SENDING"
    touch(activation)
    calc.refresh_posture(campaign)
    return ok(S.activation_out(activation))


@bp.post("/advocacy/activations/<activation_id>/complete")
def complete_activation(activation_id):
    require_role(R_DIRECTOR, R_ORGANIZER)
    activation = must("activation", activation_id)
    campaign = db.campaigns[activation["campaign_id"]]
    body = get_body()
    check_shape(body, required=("delivered_count", "bounced_count"))
    delivered = f_int(body, "delivered_count", minimum=0)
    bounced = f_int(body, "bounced_count", minimum=0)
    gates.gate_campaign_active(campaign)
    gates.gate_state(activation["delivery_state"], ("SENDING",))
    if delivered + bounced != len(activation["target_supporter_ids"]):
        err(
            "ERR_DELIVERY_TALLY_MISMATCH",
            "delivered_count plus bounced_count must equal the target count",
        )
    cascades.complete_activation(activation, delivered, bounced)
    return ok(S.activation_out(activation))


@bp.post("/advocacy/activations/<activation_id>/abort")
def abort_activation(activation_id):
    require_role(R_DIRECTOR, R_COMPLIANCE)
    activation = must("activation", activation_id)
    campaign = db.campaigns[activation["campaign_id"]]
    body = get_body()
    check_shape(body, required=("abort_reason",))
    reason = f_str(body, "abort_reason", max_len=400)
    gates.gate_campaign_active(campaign)
    gates.gate_state(activation["delivery_state"], ("SCHEDULED", "SENDING"))
    cascades.abort_activation(activation, reason)
    return ok(S.activation_out(activation))
