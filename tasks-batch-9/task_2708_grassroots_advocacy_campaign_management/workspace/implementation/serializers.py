"""Response payload shaping.  Field sets follow SCAFFOLD 1.2 exactly."""

from common import db, fmt_dt, num
import calc


def _base(row):
    return {
        "id": row["id"],
        "created_at": fmt_dt(row["created_at"]),
        "updated_at": fmt_dt(row["updated_at"]),
        "version": int(row["version"]),
    }


def campaign_out(row):
    out = {
        "name": row["name"],
        "goal_statement": row["goal_statement"],
        "bill_reference": row["bill_reference"],
        "target_chamber": row["target_chamber"],
        "start_date": fmt_dt(row["start_date"]),
        "end_date": fmt_dt(row["end_date"]),
        "success_metric_target_actions": int(row["success_metric_target_actions"]),
        "success_metric_target_supporters": int(
            row["success_metric_target_supporters"]
        ),
        "funded_total_cents": int(row["funded_total_cents"]),
        "status": row["status"],
        "posture_override": row["posture_override"],
        "posture": row["posture"],
        "blocked_activation_count": int(row["blocked_activation_count"]),
        "opposed_priority_legislator_count": int(
            row["opposed_priority_legislator_count"]
        ),
        "total_actions_logged": int(row["total_actions_logged"]),
        "distinct_acting_supporter_count": int(row["distinct_acting_supporter_count"]),
        "committed_share_total_cents": int(row["committed_share_total_cents"]),
    }
    out.update(_base(row))
    return out


def milestone_out(row):
    row["status"] = calc.milestone_status(row)
    out = {
        "campaign_id": row["campaign_id"],
        "kind": row["kind"],
        "label": row["label"],
        "window_start": fmt_dt(row["window_start"]),
        "window_end": fmt_dt(row["window_end"]),
        "is_blackout": bool(row["is_blackout"]),
        "pressure_multiplier": num(row["pressure_multiplier"]),
        "status": row["status"],
        "reschedule_count": int(row["reschedule_count"]),
    }
    out.update(_base(row))
    return out


def legislator_out(row):
    out = {
        "campaign_id": row["campaign_id"],
        "full_name": row["full_name"],
        "district_code": row["district_code"],
        "chamber": row["chamber"],
        "stance": row["stance"],
        "initial_stance": row["initial_stance"],
        "contact_pressure_score": num(row["contact_pressure_score"]),
        "priority_tier": row["priority_tier"],
        "constituent_action_count": int(row["constituent_action_count"]),
        "meeting_held_count": int(row["meeting_held_count"]),
    }
    out.update(_base(row))
    return out


def supporter_out(row):
    out = {
        "campaign_id": row["campaign_id"],
        "full_name": row["full_name"],
        "email": row["email"],
        "phone": row["phone"],
        "district_code": row["district_code"],
        "acquisition_source": row["acquisition_source"],
        "email_consent_state": row["email_consent_state"],
        "sms_consent_state": row["sms_consent_state"],
        "phone_consent_state": row["phone_consent_state"],
        "suppressed": bool(row["suppressed"]),
        "consent_event_count": int(row["consent_event_count"]),
        "touches_reserved": int(row["touches_reserved"]),
        "touches_consumed": int(row["touches_consumed"]),
        "action_count": int(row["action_count"]),
        "thanked_count": int(row["thanked_count"]),
        "engagement_score": num(row["engagement_score"]),
        "retention_score": num(row["retention_score"]),
    }
    out.update(_base(row))
    return out


def consent_event_out(row):
    # ConsentEvent is append-only: no updated_at, no version.
    return {
        "id": row["id"],
        "supporter_id": row["supporter_id"],
        "channel": row["channel"],
        "action": row["action"],
        "lawful_basis": row["lawful_basis"],
        "source_reference": row["source_reference"],
        "sequence_no": int(row["sequence_no"]),
        "effective_at": fmt_dt(row["effective_at"]),
        "created_at": fmt_dt(row["created_at"]),
    }


def segment_out(row):
    out = {
        "campaign_id": row["campaign_id"],
        "name": row["name"],
        "rule_required_channel": row["rule_required_channel"],
        "rule_district_codes": list(row["rule_district_codes"]),
        "rule_min_engagement_score": num(row["rule_min_engagement_score"]),
        "rule_sources": list(row["rule_sources"]),
        "member_supporter_ids": list(row["member_supporter_ids"]),
        "member_count": int(row["member_count"]),
        "active_activation_count": int(row["active_activation_count"]),
        "last_refreshed_at": fmt_dt(row["last_refreshed_at"]),
    }
    out.update(_base(row))
    return out


def variant_out(row):
    quorum = calc.quorum_for(row["campaign_id"])
    row["required_endorsement_quorum"] = quorum
    out = {
        "campaign_id": row["campaign_id"],
        "derived_from_variant_id": row["derived_from_variant_id"],
        "test_cell": row["test_cell"],
        "headline": row["headline"],
        "body": row["body"],
        "channel_scope": list(row["channel_scope"]),
        "status": row["status"],
        "submitted_by_user_id": row["submitted_by_user_id"],
        "reviewed_by_user_id": row["reviewed_by_user_id"],
        "revision_round": int(row["revision_round"]),
        "required_endorsement_quorum": int(quorum),
        "endorsement_count": int(row["endorsement_count"]),
        "test_winner": bool(row["test_winner"]),
        "attributed_action_count": int(row["attributed_action_count"]),
        "realized_reach_total": int(row["realized_reach_total"]),
        "send_cost_total_cents": int(row["send_cost_total_cents"]),
        "response_rate_bps": int(row["response_rate_bps"]),
        "cost_per_action_cents": int(row["cost_per_action_cents"]),
    }
    out.update(_base(row))
    return out


def partner_out(row):
    out = {
        "campaign_id": row["campaign_id"],
        "org_name": row["org_name"],
        "tier": row["tier"],
        "branding_asset_ref": row["branding_asset_ref"],
        "share_weight": int(row["share_weight"]),
        "committed_cents": int(row["committed_cents"]),
        "status": row["status"],
        "active_endorsement_count": int(row["active_endorsement_count"]),
    }
    out.update(_base(row))
    return out


def endorsement_out(row):
    out = {
        "partner_id": row["partner_id"],
        "message_variant_id": row["message_variant_id"],
        "discipline_pledge": bool(row["discipline_pledge"]),
        "talking_points_ack": bool(row["talking_points_ack"]),
        "endorsed_variant_version": int(row["endorsed_variant_version"]),
        "status": row["status"],
        "revoked_reason": row["revoked_reason"],
    }
    out.update(_base(row))
    return out


def activation_out(row):
    out = {
        "campaign_id": row["campaign_id"],
        "segment_id": row["segment_id"],
        "message_variant_id": row["message_variant_id"],
        "milestone_id": row["milestone_id"],
        "channel": row["channel"],
        "window_start": fmt_dt(row["window_start"]),
        "window_end": fmt_dt(row["window_end"]),
        "min_viable_reach": int(row["min_viable_reach"]),
        "approval_state": row["approval_state"],
        "delivery_state": row["delivery_state"],
        "effective_touch_cap": int(row["effective_touch_cap"]),
        "target_supporter_ids": list(row["target_supporter_ids"]),
        "projected_reach": int(row["projected_reach"]),
        "realized_reach": (
            None if row["realized_reach"] is None else int(row["realized_reach"])
        ),
        "delivered_count": (
            None if row["delivered_count"] is None else int(row["delivered_count"])
        ),
        "bounced_count": (
            None if row["bounced_count"] is None else int(row["bounced_count"])
        ),
        "send_cost_cents": int(row["send_cost_cents"]),
        "suppressed_by_consent_count": int(row["suppressed_by_consent_count"]),
        "abort_reason": row["abort_reason"],
    }
    out.update(_base(row))
    return out


def action_record_out(row):
    out = {
        "supporter_id": row["supporter_id"],
        "activation_id": row["activation_id"],
        "legislator_id": row["legislator_id"],
        "channel": row["channel"],
        "status": row["status"],
        "pressure_multiplier": num(row["pressure_multiplier"]),
        "thank_channel": row["thank_channel"],
        "acknowledged_at": fmt_dt(row["acknowledged_at"]),
        "thanked_at": fmt_dt(row["thanked_at"]),
        "dispute_reason": row["dispute_reason"],
    }
    out.update(_base(row))
    return out


def spokesperson_out(row):
    out = {
        "supporter_id": row["supporter_id"],
        "story_summary": row["story_summary"],
        "publication_consent": row["publication_consent"],
        "training_state": row["training_state"],
        "training_sessions_completed": int(row["training_sessions_completed"]),
        "media_ready": bool(row["media_ready"]),
    }
    out.update(_base(row))
    return out


def meeting_out(row):
    out = {
        "campaign_id": row["campaign_id"],
        "legislator_id": row["legislator_id"],
        "lead_spokesperson_id": row["lead_spokesperson_id"],
        "location_district_code": row["location_district_code"],
        "window_start": fmt_dt(row["window_start"]),
        "window_end": fmt_dt(row["window_end"]),
        "status": row["status"],
        "attendee_count": (
            None if row["attendee_count"] is None else int(row["attendee_count"])
        ),
        "pressure_credit": num(row["pressure_credit"]),
        "decline_reason": row["decline_reason"],
    }
    out.update(_base(row))
    return out
