"""Constituent action records and the thank-you loop (PRD 3.7)."""

from flask import Blueprint, g

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
    err,
    f_enum,
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

bp = Blueprint("action", __name__)


def _campaign_of(record):
    sup = db.supporters[record["supporter_id"]]
    return db.campaigns[sup["campaign_id"]]


def _recount_supporter(sup, with_engagement=True, with_retention=True):
    records = calc.actions_of_supporter(sup["id"])
    sup["action_count"] = len(
        [r for r in records if r["status"] in calc.COUNTED_ACTION_STATES]
    )
    sup["thanked_count"] = len([r for r in records if r["status"] == "THANKED"])
    if with_engagement:
        sup["engagement_score"] = calc.engagement_score(sup)
    if with_retention:
        sup["retention_score"] = calc.retention_score(sup)
    touch(sup)


def _propagate(record, sup, campaign):
    """Shared tail for every edge that changes the counted input set."""
    if record["legislator_id"] is not None:
        leg = db.legislators.get(record["legislator_id"])
        if leg is not None:
            calc.refresh_legislator(leg)
    _recount_supporter(sup)
    # an engagement_score change is itself a segment-membership cascade trigger
    for segment in calc.segments_of(campaign["id"]):
        calc.refresh_segment_membership(segment)
    calc.recompute_scheduled_reach(campaign["id"])
    calc.revalidate_activations_of(campaign["id"])
    for segment in calc.segments_of(campaign["id"]):
        calc.refresh_segment_activation_count(segment)
    calc.refresh_posture(campaign)


@bp.post("/advocacy/action-records")
def create_action():
    require_role(R_ORGANIZER, R_DIRECTOR)
    body = get_body()
    sup = must_fk("supporter", body, "supporter_id")
    activation = must_fk("activation", body, "activation_id", required=False)
    check_shape(body, required=("supporter_id", "channel"), optional=("activation_id",))
    channel = f_enum(body, "channel", calc.CHANNELS)
    campaign = db.campaigns[sup["campaign_id"]]
    gates.gate_campaign_active(campaign)
    gates.gate_not_frozen(campaign)
    gates.gate_contactable(sup, channel)
    if activation is not None and activation["campaign_id"] != campaign["id"]:
        err("ERR_CAMPAIGN_MISMATCH", "the activation belongs to another campaign")
    row = new_row()
    row.update(
        {
            "supporter_id": sup["id"],
            "activation_id": activation["id"] if activation else None,
            "legislator_id": None,
            "channel": channel,
            "status": "RECORDED",
            # the multiplier is stamped before matching runs and never recomputed
            "pressure_multiplier": calc.milestone_multiplier(campaign["id"]),
            "thank_channel": None,
            "acknowledged_at": None,
            "thanked_at": None,
            "dispute_reason": None,
            "_created_by_user_id": g.user_id,
        }
    )
    winner = calc.select_legislator(campaign, sup)
    if winner is None:
        # empty-pool fallback: terminal UNMATCHED, nothing else moves at all
        row["status"] = "UNMATCHED"
        db.action_records[row["id"]] = row
        return ok(S.action_record_out(row), 201)
    row["legislator_id"] = winner["id"]
    row["status"] = "MATCHED"
    db.action_records[row["id"]] = row
    _propagate(row, sup, campaign)
    return ok(S.action_record_out(row), 201)


@bp.get("/advocacy/action-records/<action_record_id>")
def get_action(action_record_id):
    require_role(R_DIRECTOR, R_COMPLIANCE, R_ORGANIZER, R_STRATEGIST)
    row = must("action_record", action_record_id)
    return ok(S.action_record_out(row))


@bp.get("/advocacy/action-records")
def list_actions():
    require_role(R_DIRECTOR, R_COMPLIANCE, R_ORGANIZER, R_STRATEGIST)
    limit, offset = pagination()
    rows = by_created(list(db.action_records.values()))
    for param in ("supporter_id", "activation_id", "legislator_id", "channel", "status"):
        value = q_str(param)
        if value is not None:
            rows = [r for r in rows if r[param] == value]
    return ok_list([S.action_record_out(r) for r in rows], limit, offset)


@bp.post("/advocacy/action-records/<action_record_id>/acknowledge")
def acknowledge_action(action_record_id):
    require_role(R_ORGANIZER, R_DIRECTOR)
    record = must("action_record", action_record_id)
    body = get_body()
    check_shape(body, optional=("acknowledgement_note",))
    f_str(body, "acknowledgement_note", max_len=400, required=False)
    campaign = _campaign_of(record)
    gates.gate_campaign_active(campaign)
    gates.gate_not_frozen(campaign)
    gates.gate_state(record["status"], ("MATCHED",))
    record["status"] = "ACKNOWLEDGED"
    record["acknowledged_at"] = now_dt()
    touch(record)
    return ok(S.action_record_out(record))


@bp.post("/advocacy/action-records/<action_record_id>/thank")
def thank_action(action_record_id):
    require_role(R_ORGANIZER, R_DIRECTOR)
    record = must("action_record", action_record_id)
    body = get_body()
    check_shape(body, required=("thank_channel",))
    thank_channel = f_enum(body, "thank_channel", calc.CHANNELS)
    sup = db.supporters[record["supporter_id"]]
    campaign = db.campaigns[sup["campaign_id"]]
    gates.gate_campaign_active(campaign)
    gates.gate_not_frozen(campaign)
    gates.gate_state(record["status"], ("ACKNOWLEDGED",))
    gates.gate_contactable(sup, thank_channel)
    held = int(sup["touches_consumed"]) + int(sup["touches_reserved"])
    if held >= calc.BASE_TOUCH_CAP_PER_SUPPORTER:
        # the thank-you touch is measured against the BASE allowance only
        err(
            "ERR_FREQUENCY_CAP_EXHAUSTED",
            "the supporter has no remaining touch inside the base allowance",
        )
    record["status"] = "THANKED"
    record["thank_channel"] = thank_channel
    record["thanked_at"] = now_dt()
    touch(record)
    sup["touches_consumed"] = int(sup["touches_consumed"]) + 1
    # engagement_score is deliberately left unchanged by a thank-you
    _recount_supporter(sup, with_engagement=False)
    return ok(S.action_record_out(record))


@bp.post("/advocacy/action-records/<action_record_id>/dispute")
def dispute_action(action_record_id):
    require_role(R_COMPLIANCE, R_ORGANIZER)
    record = must("action_record", action_record_id)
    body = get_body()
    check_shape(body, required=("dispute_reason",))
    reason = f_str(body, "dispute_reason", max_len=400)
    sup = db.supporters[record["supporter_id"]]
    campaign = db.campaigns[sup["campaign_id"]]
    gates.gate_campaign_active(campaign)
    gates.gate_state(record["status"], ("MATCHED", "ACKNOWLEDGED"))
    record["status"] = "DISPUTED"
    record["dispute_reason"] = reason
    touch(record)
    _propagate(record, sup, campaign)
    return ok(S.action_record_out(record))


@bp.post("/advocacy/action-records/<action_record_id>/dispute-resolutions")
def resolve_dispute(action_record_id):
    require_role(R_COMPLIANCE, R_DIRECTOR)
    record = must("action_record", action_record_id)
    body = get_body()
    check_shape(body, required=("outcome", "resolution_note"))
    outcome = f_enum(body, "outcome", ("REINSTATED", "VOIDED"))
    f_str(body, "resolution_note", max_len=400)
    sup = db.supporters[record["supporter_id"]]
    campaign = db.campaigns[sup["campaign_id"]]
    gates.gate_campaign_active(campaign)
    gates.gate_state(record["status"], ("DISPUTED",))
    gates.gate_sod(record.get("_created_by_user_id"))
    # acknowledged_at is preserved on both edges
    record["status"] = "MATCHED" if outcome == "REINSTATED" else "VOIDED"
    touch(record)
    _propagate(record, sup, campaign)
    return ok(S.action_record_out(record))
