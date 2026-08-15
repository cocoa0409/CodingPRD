"""Serializers: internal record dicts -> public JSON-able dicts.

Datetime internals become ISO 8601 UTC strings with three fractional digits;
Decimal percentages become JSON numbers; internal bookkeeping keys (_seq) are
stripped. QCReview carries only id and created_at (no updated_at, no version).
"""
from db import DB
from util import fmt_dt

ACTIVE_COMPLAINT_STATUSES = {"OPEN", "TRIAGED", "REMEDIATING", "REOPENED"}


def _common(rec):
    return {
        "created_at": fmt_dt(rec["created_at"]),
        "updated_at": fmt_dt(rec["updated_at"]),
        "version": rec["version"],
    }


def client(r):
    out = {
        "id": r["id"],
        "name": r["name"],
        "compliance_standard": r["compliance_standard"],
        "default_turnaround_tier": r["default_turnaround_tier"],
        "client_status": r["client_status"],
        "ytd_completed_minutes": r["ytd_completed_minutes"],
    }
    out.update(_common(r))
    return out


def media_asset(r):
    out = {
        "id": r["id"],
        "client_id": r["client_id"],
        "title": r["title"],
        "media_kind": r["media_kind"],
        "duration_seconds": r["duration_seconds"],
        "frame_rate": r["frame_rate"],
        "intake_status": r["intake_status"],
        "rejection_reason": r["rejection_reason"],
    }
    out.update(_common(r))
    return out


def order_active_complaint_count(order_id):
    """Count of complaints on any track of this order with complaint_status in
    {OPEN, TRIAGED, REMEDIATING, REOPENED} (computed)."""
    ct_ids = {tid for tid, t in DB.caption_tracks.items() if t["work_order_id"] == order_id}
    ad_ids = {tid for tid, t in DB.ad_tracks.items() if t["work_order_id"] == order_id}
    n = 0
    for c in DB.complaints.values():
        if c["complaint_status"] not in ACTIVE_COMPLAINT_STATUSES:
            continue
        if (c["caption_track_id"] and c["caption_track_id"] in ct_ids) or (
            c["audio_description_track_id"] and c["audio_description_track_id"] in ad_ids
        ):
            n += 1
    return n


def work_order(r):
    out = {
        "id": r["id"],
        "client_id": r["client_id"],
        "media_asset_id": r["media_asset_id"],
        "service_type": r["service_type"],
        "turnaround_tier": r["turnaround_tier"],
        "language": r["language"],
        "order_status": r["order_status"],
        "quoted_price_cents": r["quoted_price_cents"],
        "quote_expires_at": fmt_dt(r["quote_expires_at"]),
        "due_at": fmt_dt(r["due_at"]),
        "sla_breached": r["sla_breached"],
        "delivered_at": fmt_dt(r["delivered_at"]),
        "active_complaint_count": order_active_complaint_count(r["id"]),
    }
    out.update(_common(r))
    return out


def caption_track(r):
    out = {
        "id": r["id"],
        "work_order_id": r["work_order_id"],
        "supersedes_track_id": r["supersedes_track_id"],
        "version_no": r["version_no"],
        "language": r["language"],
        "caption_format": r["caption_format"],
        "speaker_id_style": r["speaker_id_style"],
        "track_status": r["track_status"],
        "author_user_id": r["author_user_id"],
        "qc_attempts": r["qc_attempts"],
        "last_accuracy_pct": (float(r["last_accuracy_pct"]) if r["last_accuracy_pct"] is not None else None),
    }
    out.update(_common(r))
    return out


def qc_review(r):
    # Immutable measurement record: only id and created_at, no updated_at/version.
    return {
        "id": r["id"],
        "caption_track_id": r["caption_track_id"],
        "reviewer_user_id": r["reviewer_user_id"],
        "review_mode": r["review_mode"],
        "total_words": r["total_words"],
        "sampled_words": r["sampled_words"],
        "minor_errors": r["minor_errors"],
        "major_errors": r["major_errors"],
        "critical_errors": r["critical_errors"],
        "weighted_errors": r["weighted_errors"],
        "accuracy_pct": float(r["accuracy_pct"]),
        "threshold_pct": float(r["threshold_pct"]),
        "outcome": r["outcome"],
        "created_at": fmt_dt(r["created_at"]),
    }


def ad_track(r):
    out = {
        "id": r["id"],
        "work_order_id": r["work_order_id"],
        "language": r["language"],
        "narrator_name": r["narrator_name"],
        "author_user_id": r["author_user_id"],
        "ad_status": r["ad_status"],
        "gaps": r["gaps"],
        "segments": r["segments"],
        "gap_coverage_pct": (float(r["gap_coverage_pct"]) if r["gap_coverage_pct"] is not None else None),
        "studio_id": r["studio_id"],
        "record_start_at": fmt_dt(r["record_start_at"]),
        "record_end_at": fmt_dt(r["record_end_at"]),
    }
    out.update(_common(r))
    return out


def live_event(r):
    out = {
        "id": r["id"],
        "client_id": r["client_id"],
        "title": r["title"],
        "channel_id": r["channel_id"],
        "start_at": fmt_dt(r["start_at"]),
        "end_at": fmt_dt(r["end_at"]),
        "required_certification": r["required_certification"],
        "prep_minutes": r["prep_minutes"],
        "wrap_minutes": r["wrap_minutes"],
        "event_status": r["event_status"],
    }
    out.update(_common(r))
    return out


def stenographer(r):
    out = {
        "id": r["id"],
        "display_name": r["display_name"],
        "certification": r["certification"],
        "certified_since": fmt_dt(r["certified_since"]),
        "cert_valid_until": fmt_dt(r["cert_valid_until"]),
        "max_daily_live_minutes": r["max_daily_live_minutes"],
        "steno_status": r["steno_status"],
        "make_up_minutes_credited": r["make_up_minutes_credited"],
        "no_show_count": r["no_show_count"],
    }
    out.update(_common(r))
    return out


def assignment(r):
    out = {
        "id": r["id"],
        "live_event_id": r["live_event_id"],
        "stenographer_id": r["stenographer_id"],
        "assignment_status": r["assignment_status"],
        "origin": r["origin"],
        "offered_at": fmt_dt(r["offered_at"]),
        "offer_expires_at": fmt_dt(r["offer_expires_at"]),
        "booked_minutes": r["booked_minutes"],
        "preemption_reason": r["preemption_reason"],
    }
    out.update(_common(r))
    return out


def complaint(r):
    out = {
        "id": r["id"],
        "client_id": r["client_id"],
        "caption_track_id": r["caption_track_id"],
        "audio_description_track_id": r["audio_description_track_id"],
        "live_event_id": r["live_event_id"],
        "severity": r["severity"],
        "description": r["description"],
        "complaint_status": r["complaint_status"],
        "escalation_level": r["escalation_level"],
        "remediation_track_id": r["remediation_track_id"],
        "resolved_at": fmt_dt(r["resolved_at"]),
        "resolver_user_id": r["resolver_user_id"],
    }
    out.update(_common(r))
    return out


def conversion_job(r):
    out = {
        "id": r["id"],
        "source_track_id": r["source_track_id"],
        "target_format": r["target_format"],
        "embed": r["embed"],
        "job_status": r["job_status"],
        "attempt_count": r["attempt_count"],
        "output_duration_ms": r["output_duration_ms"],
        "last_delta_ms": r["last_delta_ms"],
    }
    out.update(_common(r))
    return out


def archive_item(r):
    out = {
        "id": r["id"],
        "caption_track_id": r["caption_track_id"],
        "audio_description_track_id": r["audio_description_track_id"],
        "live_event_id": r["live_event_id"],
        "retention_class": r["retention_class"],
        "archive_status": r["archive_status"],
        "archived_at": fmt_dt(r["archived_at"]),
        "purge_after": fmt_dt(r["purge_after"]),
        "legal_hold": r["legal_hold"],
        "dispute_freeze": r["dispute_freeze"],
    }
    out.update(_common(r))
    return out
