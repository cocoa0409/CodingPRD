"""Serializers: convert internal entity dicts to API JSON (PRD §2.4, §1.1)."""
from db import iso_ts

COMMON = ["id", "created_at", "updated_at", "version"]


def _common(e):
    return {
        "id": e["id"],
        "created_at": iso_ts(e["created_at"]),
        "updated_at": iso_ts(e["updated_at"]),
        "version": e["version"],
    }


def case_out(e):
    return {
        **_common(e),
        "caption": e["caption"],
        "docket_number": e["docket_number"],
        "jurisdiction": e["jurisdiction"],
        "noticing_attorney_id": e["noticing_attorney_id"],
    }


def attorney_out(e):
    return {
        **_common(e),
        "full_name": e["full_name"],
        "firm_name": e["firm_name"],
        "bar_state": e["bar_state"],
        "email": e["email"],
    }


def resource_out(e):
    return {
        **_common(e),
        "full_name": e["full_name"],
        "kind": e["kind"],
        "certifications": e["certifications"],
        "realtime_capable": e["realtime_capable"],
        "hourly_appearance_cents": e["hourly_appearance_cents"],
        "active": e["active"],
    }


def job_out(e):
    return {
        **_common(e),
        "case_id": e["case_id"],
        "deponent_name": e["deponent_name"],
        "scheduled_start": iso_ts(e["scheduled_start"]),
        "scheduled_end": iso_ts(e["scheduled_end"]),
        "requires_videographer": e["requires_videographer"],
        "requires_interpreter": e["requires_interpreter"],
        "interpreter_language": e["interpreter_language"],
        "requires_realtime": e["requires_realtime"],
        "status": e["status"],
        "staffing_posture": e["staffing_posture"],
        "actual_start": iso_ts(e["actual_start"]),
        "actual_end": iso_ts(e["actual_end"]),
    }


def assignment_out(e):
    return {
        **_common(e),
        "job_id": e["job_id"],
        "resource_id": e["resource_id"],
        "role": e["role"],
        "status": e["status"],
        "appearance_fee_cents": e["appearance_fee_cents"],
    }


def stream_out(e):
    return {
        **_common(e),
        "job_id": e["job_id"],
        "reporter_assignment_id": e["reporter_assignment_id"],
        "access_token": e["access_token"],
        "status": e["status"],
        "started_at": iso_ts(e["started_at"]),
        "stopped_at": iso_ts(e["stopped_at"]),
    }


def transcript_out(e):
    return {
        **_common(e),
        "job_id": e["job_id"],
        "ordering_attorney_id": e["ordering_attorney_id"],
        "turnaround_tier": e["turnaround_tier"],
        "certified_copy": e["certified_copy"],
        "estimated_pages": e["estimated_pages"],
        "final_pages": e["final_pages"],
        "status": e["status"],
        "read_sign_deadline": iso_ts(e["read_sign_deadline"]),
        "errata_round": e["errata_round"],
    }


def exhibit_out(e):
    return {
        **_common(e),
        "transcript_order_id": e["transcript_order_id"],
        "marked_label": e["marked_label"],
        "page_count": e["page_count"],
        "confidential": e["confidential"],
    }


def errata_out(e):
    return {
        **_common(e),
        "transcript_order_id": e["transcript_order_id"],
        "round": e["round"],
        "corrections": e["corrections"],
        "reason": e["reason"],
    }


def invoice_out(e):
    return {
        **_common(e),
        "job_id": e["job_id"],
        "transcript_order_id": e["transcript_order_id"],
        "bill_to_attorney_id": e["bill_to_attorney_id"],
        "appearance_subtotal_cents": e["appearance_subtotal_cents"],
        "page_subtotal_cents": e["page_subtotal_cents"],
        "exhibit_subtotal_cents": e["exhibit_subtotal_cents"],
        "total_cents": e["total_cents"],
        "status": e["status"],
    }
