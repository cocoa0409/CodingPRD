"""MessageVariant endpoints (PRD 3.4)."""

from flask import Blueprint, g

import calc
import cascades
import gates
import serializers as S
from common import (
    R_COMPLIANCE,
    R_DIRECTOR,
    R_PARTNER,
    R_STRATEGIST,
    by_created,
    check_shape,
    db,
    err,
    f_enum,
    f_str,
    f_str_list,
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

bp = Blueprint("variant", __name__)

DECISIONS = ("APPROVE", "REQUEST_CHANGES")


@bp.post("/advocacy/message-variants")
def create_variant():
    require_role(R_STRATEGIST)
    body = get_body()
    campaign = must_fk("campaign", body, "campaign_id")
    derived = must_fk("variant", body, "derived_from_variant_id", required=False)
    check_shape(
        body,
        required=("campaign_id", "test_cell", "headline", "body", "channel_scope"),
        optional=("derived_from_variant_id",),
    )
    test_cell = f_str(body, "test_cell", max_len=60)
    headline = f_str(body, "headline", max_len=160)
    copy = f_str(body, "body", max_len=2000)
    scope = f_str_list(
        body, "channel_scope", choices=calc.CHANNELS, allow_empty=False
    )
    gates.gate_campaign_active(campaign)
    row = new_row()
    row.update(
        {
            "campaign_id": campaign["id"],
            "derived_from_variant_id": derived["id"] if derived else None,
            "test_cell": test_cell,
            "headline": headline,
            "body": copy,
            "channel_scope": scope,
            "status": "DRAFT",
            "submitted_by_user_id": None,
            "reviewed_by_user_id": None,
            "revision_round": 1,
            "required_endorsement_quorum": calc.quorum_for(campaign["id"]),
            "endorsement_count": 0,
            "test_winner": False,
            "attributed_action_count": 0,
            "realized_reach_total": 0,
            "send_cost_total_cents": 0,
            "response_rate_bps": 0,
            "cost_per_action_cents": calc.NO_ACTION_CPA_SENTINEL_CENTS,
        }
    )
    db.variants[row["id"]] = row
    return ok(S.variant_out(row), 201)


@bp.get("/advocacy/message-variants/<variant_id>")
def get_variant(variant_id):
    require_role(R_DIRECTOR, R_COMPLIANCE, R_STRATEGIST, R_PARTNER)
    row = must("variant", variant_id)
    return ok(S.variant_out(row))


@bp.get("/advocacy/message-variants")
def list_variants():
    require_role(R_DIRECTOR, R_COMPLIANCE, R_STRATEGIST, R_PARTNER)
    limit, offset = pagination()
    campaign_id = q_str("campaign_id")
    derived_from = q_str("derived_from_variant_id")
    status = q_str("status")
    test_cell = q_str("test_cell")
    winner = q_bool("test_winner")
    rows = by_created(list(db.variants.values()))
    if campaign_id is not None:
        rows = [r for r in rows if r["campaign_id"] == campaign_id]
    if derived_from is not None:
        rows = [r for r in rows if r["derived_from_variant_id"] == derived_from]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if test_cell is not None:
        rows = [r for r in rows if r["test_cell"] == test_cell]
    if winner is not None:
        rows = [r for r in rows if bool(r["test_winner"]) is winner]
    return ok_list([S.variant_out(r) for r in rows], limit, offset)


@bp.post("/advocacy/message-variants/<variant_id>/submit")
def submit_variant(variant_id):
    require_role(R_STRATEGIST)
    variant = must("variant", variant_id)
    campaign = db.campaigns[variant["campaign_id"]]
    body = get_body()
    check_shape(body, optional=("submission_note",))
    f_str(body, "submission_note", max_len=400, required=False)
    gates.gate_campaign_active(campaign)
    gates.gate_state(variant["status"], ("DRAFT", "CHANGES_REQUESTED"))
    if variant["status"] == "CHANGES_REQUESTED":
        # PRD 3.4: refused once revision_round has reached the ceiling of 3.
        if int(variant["revision_round"]) >= calc.MAX_REVISION_ROUNDS:
            err(
                "ERR_REVISION_LIMIT_REACHED",
                "the variant has exhausted its revision allowance",
            )
    variant["status"] = "IN_REVIEW"
    variant["submitted_by_user_id"] = g.user_id
    touch(variant)
    return ok(S.variant_out(variant))


@bp.post("/advocacy/message-variants/<variant_id>/review-decisions")
def review_variant(variant_id):
    require_role(R_COMPLIANCE, R_DIRECTOR)
    variant = must("variant", variant_id)
    campaign = db.campaigns[variant["campaign_id"]]
    body = get_body()
    check_shape(body, required=("decision", "review_note"))
    decision = f_enum(body, "decision", DECISIONS)
    f_str(body, "review_note", max_len=400)
    gates.gate_campaign_active(campaign)
    gates.gate_state(variant["status"], ("IN_REVIEW",))
    gates.gate_sod(variant["submitted_by_user_id"])
    if decision == "APPROVE":
        variant["status"] = "APPROVED"
    else:
        variant["status"] = "CHANGES_REQUESTED"
        variant["revision_round"] = int(variant["revision_round"]) + 1
    variant["reviewed_by_user_id"] = g.user_id
    touch(variant)
    return ok(S.variant_out(variant))


@bp.post("/advocacy/message-variants/<variant_id>/lock")
def lock_variant(variant_id):
    require_role(R_STRATEGIST, R_DIRECTOR)
    variant = must("variant", variant_id)
    campaign = db.campaigns[variant["campaign_id"]]
    gates.gate_campaign_active(campaign)
    gates.gate_not_frozen(campaign)
    gates.gate_state(variant["status"], ("APPROVED",))
    quorum = calc.quorum_for(campaign["id"])
    if variant["required_endorsement_quorum"] != quorum:
        variant["required_endorsement_quorum"] = quorum
    if int(variant["endorsement_count"]) < quorum:
        err(
            "ERR_ENDORSEMENT_QUORUM_NOT_MET",
            "the variant holds %s of %s required ACTIVE endorsements"
            % (variant["endorsement_count"], quorum),
        )
    variant["status"] = "LOCKED"
    touch(variant)
    return ok(S.variant_out(variant))


@bp.post("/advocacy/message-variants/<variant_id>/reopen")
def reopen_variant(variant_id):
    require_role(R_STRATEGIST, R_DIRECTOR)
    variant = must("variant", variant_id)
    campaign = db.campaigns[variant["campaign_id"]]
    body = get_body()
    check_shape(body, required=("reopen_reason",))
    f_str(body, "reopen_reason", max_len=400)
    gates.gate_campaign_active(campaign)
    gates.gate_state(variant["status"], ("LOCKED",))
    if int(variant["revision_round"]) >= calc.MAX_REVISION_ROUNDS:
        err(
            "ERR_REVISION_LIMIT_REACHED",
            "the variant has exhausted its revision allowance",
        )
    for activation in calc.activations_of(campaign["id"]):
        if (
            activation["message_variant_id"] == variant["id"]
            and activation["delivery_state"] == "SENDING"
        ):
            err(
                "ERR_ACTIVATION_IN_FLIGHT",
                "a wave carrying this variant is still SENDING",
            )
    variant["status"] = "CHANGES_REQUESTED"
    variant["revision_round"] = int(variant["revision_round"]) + 1
    touch(variant)
    cascades.block_waves_of_variant(variant)
    calc.cascade(campaign)
    return ok(S.variant_out(variant))
