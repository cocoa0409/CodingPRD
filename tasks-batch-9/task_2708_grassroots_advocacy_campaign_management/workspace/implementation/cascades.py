"""Multi-hop cascades shared by several route modules (PRD 2.10 / 3.x)."""

from decimal import Decimal

import calc
from common import db, now_dt, touch


def block_waves_of_variant(variant):
    """Hop: because the variant left LOCKED, its SCHEDULED waves are blocked."""
    for activation in calc.activations_of(variant["campaign_id"]):
        if activation["message_variant_id"] != variant["id"]:
            continue
        if activation["delivery_state"] != "SCHEDULED":
            continue
        if activation["approval_state"] not in ("PENDING", "CLEARED"):
            continue
        activation["approval_state"] = "BLOCKED"
        touch(activation)


def enforce_quorum(variant):
    """System-triggered LOCKED -> CHANGES_REQUESTED when the quorum is lost.

    The revision ceiling and the in-flight check deliberately do not gate this
    form, because the coalition forced the move.
    """
    quorum = calc.quorum_for(variant["campaign_id"])
    if variant["required_endorsement_quorum"] != quorum:
        variant["required_endorsement_quorum"] = quorum
        touch(variant)
    if variant["status"] == "LOCKED" and int(variant["endorsement_count"]) < quorum:
        variant["status"] = "CHANGES_REQUESTED"
        variant["revision_round"] = int(variant["revision_round"]) + 1
        touch(variant)
        block_waves_of_variant(variant)
        return True
    return False


def revoke_endorsement_row(endorsement, reason):
    """ACTIVE -> REVOKED plus the four downstream hops."""
    endorsement["status"] = "REVOKED"
    endorsement["revoked_reason"] = reason
    touch(endorsement)
    partner = db.partners.get(endorsement["partner_id"])
    if partner is not None:
        calc.refresh_partner_endorsement_count(partner)
    variant = db.variants.get(endorsement["message_variant_id"])
    if variant is not None:
        calc.refresh_variant_endorsement_count(variant)
        enforce_quorum(variant)


def retire_variant(variant):
    variant["status"] = "RETIRED"
    variant["test_winner"] = False
    touch(variant)
    for activation in calc.activations_of(variant["campaign_id"]):
        if activation["message_variant_id"] != variant["id"]:
            continue
        if activation["delivery_state"] != "SCHEDULED":
            continue
        if activation["approval_state"] == "BLOCKED":
            continue
        activation["approval_state"] = "BLOCKED"
        touch(activation)


def void_actions_of_activation(activation):
    """Hop: an aborted wave voids the action records it prompted."""
    touched_supporters = set()
    touched_legislators = set()
    for record in calc.by_created(list(db.action_records.values())):
        if record["activation_id"] != activation["id"]:
            continue
        if record["status"] not in ("RECORDED", "MATCHED", "ACKNOWLEDGED"):
            continue
        record["status"] = "VOIDED"
        touch(record)
        touched_supporters.add(record["supporter_id"])
        if record["legislator_id"]:
            touched_legislators.add(record["legislator_id"])
    return touched_supporters, touched_legislators


def abort_activation(activation, reason):
    """Compensating abort from SCHEDULED or SENDING."""
    from_state = activation["delivery_state"]
    activation["delivery_state"] = "ABORTED"
    activation["abort_reason"] = reason
    calc.release_reservations(activation["target_supporter_ids"])
    for supporter_id in set(activation["target_supporter_ids"]):
        sup = db.supporters.get(supporter_id)
        if sup is not None:
            touch(sup)
    touch(activation)
    campaign = db.campaigns[activation["campaign_id"]]
    if from_state == "SENDING":
        supporter_ids, legislator_ids = void_actions_of_activation(activation)
        for supporter_id in supporter_ids:
            sup = db.supporters.get(supporter_id)
            if sup is not None:
                calc.refresh_supporter_counters(sup)
        for legislator_id in legislator_ids:
            leg = db.legislators.get(legislator_id)
            if leg is not None:
                calc.refresh_legislator(leg)
    segment = db.segments.get(activation["segment_id"])
    if segment is not None:
        calc.refresh_segment_activation_count(segment)
    calc.refresh_variant_metrics_of(campaign["id"])
    calc.refresh_posture(campaign)


def close_campaign(campaign):
    """PRD 3.9: the campaign-wrap cascade."""
    campaign["status"] = "CLOSED"
    touch(campaign)
    voided_supporters = set()
    voided_legislators = set()
    for activation in calc.activations_of(campaign["id"]):
        if activation["delivery_state"] != "SCHEDULED":
            continue
        activation["delivery_state"] = "ABORTED"
        activation["abort_reason"] = "CAMPAIGN_CLOSED"
        calc.release_reservations(activation["target_supporter_ids"])
        for supporter_id in set(activation["target_supporter_ids"]):
            sup = db.supporters.get(supporter_id)
            if sup is not None:
                touch(sup)
        touch(activation)
        hop_supporters, hop_legislators = void_actions_of_activation(activation)
        voided_supporters |= hop_supporters
        voided_legislators |= hop_legislators
    for segment in calc.segments_of(campaign["id"]):
        calc.refresh_segment_activation_count(segment)
    for supporter_id in voided_supporters:
        sup = db.supporters.get(supporter_id)
        if sup is not None:
            calc.refresh_supporter_counters(sup)
    for legislator_id in voided_legislators:
        leg = db.legislators.get(legislator_id)
        if leg is not None:
            calc.refresh_legislator(leg)
    for meeting in calc.meetings_of(campaign["id"]):
        if meeting["status"] != "REQUESTED":
            continue
        meeting["status"] = "DECLINED"
        meeting["decline_reason"] = "CAMPAIGN_CLOSED"
        touch(meeting)
    for sup in calc.supporters_of(campaign["id"]):
        final = calc.retention_score(sup)
        if sup["retention_score"] != final:
            sup["retention_score"] = final
            touch(sup)
    calc.refresh_variant_metrics_of(campaign["id"])
    calc.refresh_posture(campaign)


def complete_activation(activation, delivered_count, bounced_count):
    """SENDING -> SENT | PARTIAL with the full ledger settlement."""
    targets = list(activation["target_supporter_ids"])
    delivered_set = targets[:delivered_count]
    remainder = targets[delivered_count:]
    realized = 0
    for supporter_id in delivered_set:
        sup = db.supporters.get(supporter_id)
        if sup is None:
            continue
        if (
            calc.consent_state(sup, activation["channel"]) == "GRANTED"
            and not sup["suppressed"]
        ):
            realized += 1
    activation["realized_reach"] = realized
    activation["suppressed_by_consent_count"] = delivered_count - realized
    activation["send_cost_cents"] = (
        calc.CHANNEL_UNIT_COST_CENTS[activation["channel"]] * delivered_count
    )
    activation["delivered_count"] = delivered_count
    activation["bounced_count"] = bounced_count
    if bounced_count == 0 and delivered_count == len(targets):
        activation["delivery_state"] = "SENT"
    else:
        activation["delivery_state"] = "PARTIAL"
    for supporter_id in delivered_set:
        sup = db.supporters.get(supporter_id)
        if sup is None:
            continue
        sup["touches_consumed"] = int(sup["touches_consumed"]) + 1
        sup["touches_reserved"] = max(0, int(sup["touches_reserved"]) - 1)
        touch(sup)
    for supporter_id in remainder:
        sup = db.supporters.get(supporter_id)
        if sup is None:
            continue
        sup["touches_reserved"] = max(0, int(sup["touches_reserved"]) - 1)
        touch(sup)
    touch(activation)
    segment = db.segments.get(activation["segment_id"])
    if segment is not None:
        calc.refresh_segment_activation_count(segment)
    variant = db.variants.get(activation["message_variant_id"])
    if variant is not None:
        calc.refresh_variant_metrics(variant)
    calc.refresh_posture(db.campaigns[activation["campaign_id"]])
