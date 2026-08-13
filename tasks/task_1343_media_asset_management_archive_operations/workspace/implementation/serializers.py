"""Entity serializers: whitelist the public field set, format datetimes,
and inject computed fields (asset_count, rights_posture, hold_status,
priority_score)."""
import calc
from db import STORE, fmt_dt


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_dt(rec["created_at"]),
        "updated_at": fmt_dt(rec["updated_at"]),
        "version": rec["version"],
    }


def staff_out(r):
    d = _common(r)
    d.update({
        "email": r["email"],
        "full_name": r["full_name"],
        "department": r["department"],
        "active": r["active"],
    })
    return d


def batch_out(r):
    d = _common(r)
    count = sum(1 for a in STORE.assets.values() if a["ingest_batch_id"] == r["id"])
    d.update({
        "batch_name": r["batch_name"],
        "source_department": r["source_department"],
        "status": r["status"],
        "asset_count": count,
    })
    return d


def asset_out(r):
    d = _common(r)
    d.update({
        "ingest_batch_id": r["ingest_batch_id"],
        "source_asset_id": r["source_asset_id"],
        "title": r["title"],
        "description": r["description"],
        "media_type": r["media_type"],
        "format_class": r["format_class"],
        "duration_seconds": r["duration_seconds"],
        "size_gb": r["size_gb"],
        "rights_holder": r["rights_holder"],
        "keywords": list(r["keywords"]),
        "content_rating": r["content_rating"],
        "catalog_status": r["catalog_status"],
        "storage_tier": r["storage_tier"],
        "rights_posture": calc.rights_posture(r),
        "hold_status": calc.hold_status(r),
        "metadata_submitted_by_user_id": r["metadata_submitted_by_user_id"],
    })
    return d


def proxy_out(r):
    d = _common(r)
    d.update({
        "asset_id": r["asset_id"],
        "rendition_type": r["rendition_type"],
        "status": r["status"],
        "retry_count": r["retry_count"],
        "proxy_url": r["proxy_url"],
        "indexed_at": fmt_dt(r["indexed_at"]),
        "failure_reason": r["failure_reason"],
    })
    return d


def grant_out(r):
    d = _common(r)
    d.update({
        "asset_id": r["asset_id"],
        "grant_type": r["grant_type"],
        "territory": r["territory"],
        "exclusive": r["exclusive"],
        "window_start": fmt_dt(r["window_start"]),
        "window_end": fmt_dt(r["window_end"]),
        "restriction_flags": list(r["restriction_flags"]),
        "status": r["status"],
    })
    return d


def hold_out(r):
    d = _common(r)
    d.update({
        "asset_id": r["asset_id"],
        "matter_reference": r["matter_reference"],
        "reason": r["reason"],
        "placed_by_user_id": r["placed_by_user_id"],
        "status": r["status"],
        "released_by_user_id": r["released_by_user_id"],
        "released_at": fmt_dt(r["released_at"]),
    })
    return d


def policy_out(r):
    d = _common(r)
    d.update({
        "media_type": r["media_type"],
        "min_retention_years": r["min_retention_years"],
        "requires_legal_review": r["requires_legal_review"],
    })
    return d


def order_out(r):
    d = _common(r)
    d.update({
        "asset_id": r["asset_id"],
        "created_by_user_id": r["created_by_user_id"],
        "scheduled_execution_date": fmt_dt(r["scheduled_execution_date"]),
        "retention_override": r["retention_override"],
        "override_reason": r["override_reason"],
        "pinned_asset_version": r["pinned_asset_version"],
        "status": r["status"],
        "approved_by_user_id": r["approved_by_user_id"],
        "reject_reason": r["reject_reason"],
    })
    return d


def request_out(r):
    d = _common(r)
    d.update({
        "asset_id": r["asset_id"],
        "requester_id": r["requester_id"],
        "purpose": r["purpose"],
        "delivery_tier": r["delivery_tier"],
        "requested_delivery_by": fmt_dt(r["requested_delivery_by"]),
        "status": r["status"],
        "quoted_fee_cents": r["quoted_fee_cents"],
        "return_count": r["return_count"],
        "staged_at": fmt_dt(r["staged_at"]),
        "delivered_at": fmt_dt(r["delivered_at"]),
        "review_note": r["review_note"],
    })
    return d


def event_out(r):
    d = _common(r)
    d.update({
        "asset_id": r["asset_id"],
        "reported_by_id": r["reported_by_id"],
        "usage_type": r["usage_type"],
        "market_size": r["market_size"],
        "duration_seconds_used": r["duration_seconds_used"],
        "aired_at": fmt_dt(r["aired_at"]),
        "status": r["status"],
        "provisional_accrual_cents": r["provisional_accrual_cents"],
        "final_accrual_cents": r["final_accrual_cents"],
        "statement_id": r["statement_id"],
        "dispute_reason": r["dispute_reason"],
    })
    return d


def statement_out(r):
    d = _common(r)
    d.update({
        "rights_holder": r["rights_holder"],
        "period_start": fmt_dt(r["period_start"]),
        "period_end": fmt_dt(r["period_end"]),
        "status": r["status"],
        "event_ids": list(r["event_ids"]),
        "total_verified_seconds": r["total_verified_seconds"],
        "volume_tier": r["volume_tier"],
        "provisional_total_cents": r["provisional_total_cents"],
        "total_accrual_cents": r["total_accrual_cents"],
    })
    return d


def job_out(r):
    d = _common(r)
    d.update({
        "asset_id": r["asset_id"],
        "target_tier": r["target_tier"],
        "status": r["status"],
        "retry_count": r["retry_count"],
        "checksum_sha256": r["checksum_sha256"],
        "failure_reason": r["failure_reason"],
    })
    return d


def ticket_out(r):
    d = _common(r)
    d.update({
        "asset_id": r["asset_id"],
        "workstation_id": r["workstation_id"],
        "scheduled_start": fmt_dt(r["scheduled_start"]),
        "scheduled_end": fmt_dt(r["scheduled_end"]),
        "output_format": r["output_format"],
        "priority_score": calc.priority_score(r),
        "status": r["status"],
        "rework_count": r["rework_count"],
        "qc_notes": r["qc_notes"],
    })
    return d


def workstation_out(r):
    d = _common(r)
    d.update({
        "name": r["name"],
        "supported_formats": list(r["supported_formats"]),
        "status": r["status"],
    })
    return d
