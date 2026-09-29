"""Explicit per-entity field lists (SCAFFOLD section 1.1)."""

from decimal import Decimal

from timeutil import iso


def _num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(row):
    return {
        "id": row["id"],
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
        "version": row["version"],
    }


def term(row):
    data = _common(row)
    data.update(
        {
            "code": row["code"],
            "announcement_lead_business_days": row["announcement_lead_business_days"],
            "defense_deadline": iso(row["defense_deadline"]),
            "format_review_deposit_deadline": iso(row["format_review_deposit_deadline"]),
            "degree_conferral_date": iso(row["degree_conferral_date"]),
            "status": row["status"],
            "conferred_count": row["conferred_count"],
        }
    )
    return data


def student(row):
    data = _common(row)
    data.update(
        {
            "full_name": row["full_name"],
            "email": row["email"],
            "degree_level": row["degree_level"],
            "program_code": row["program_code"],
            "graduation_clearance_state": row["graduation_clearance_state"],
            "degree_conferred": row["degree_conferred"],
            "transcript_notation": row["transcript_notation"],
        }
    )
    return data


def faculty_member(row):
    data = _common(row)
    data.update(
        {
            "full_name": row["full_name"],
            "email": row["email"],
            "appointment_type": row["appointment_type"],
            "graduate_faculty_certified": row["graduate_faculty_certified"],
            "active_chair_load": row["active_chair_load"],
        }
    )
    return data


def defense_room(row):
    data = _common(row)
    data.update(
        {
            "code": row["code"],
            "building": row["building"],
            "seat_capacity": row["seat_capacity"],
            "turnover_buffer_minutes": row["turnover_buffer_minutes"],
            "status": row["status"],
            "booked_minutes_total": row["booked_minutes_total"],
        }
    )
    return data


def thesis(row):
    data = _common(row)
    data.update(
        {
            "student_id": row["student_id"],
            "term_id": row["term_id"],
            "title": row["title"],
            "document_type": row["document_type"],
            "page_count": row["page_count"],
            "third_party_item_count": row["third_party_item_count"],
            "workflow_state": row["workflow_state"],
            "integrity_state": row["integrity_state"],
            "format_cycle_count": row["format_cycle_count"],
            "documented_permission_count": row["documented_permission_count"],
            "analyst_turnaround_bdays_total": row["analyst_turnaround_bdays_total"],
            "accepted_at": iso(row["accepted_at"]),
        }
    )
    return data


def committee(row):
    data = _common(row)
    data.update(
        {
            "thesis_id": row["thesis_id"],
            "status": row["status"],
            "member_count": row["member_count"],
            "external_member_count": row["external_member_count"],
            "approved_by_user_id": row["approved_by_user_id"],
            "approved_at": iso(row["approved_at"]),
            "rejection_note": row["rejection_note"],
        }
    )
    return data


def committee_member(row):
    data = _common(row)
    data.update(
        {
            "committee_id": row["committee_id"],
            "faculty_id": row["faculty_id"],
            "role": row["role"],
            "status": row["status"],
            "withdrawal_reason": row["withdrawal_reason"],
        }
    )
    return data


def defense_event(row):
    data = _common(row)
    data.update(
        {
            "thesis_id": row["thesis_id"],
            "room_id": row["room_id"],
            "scheduled_start": iso(row["scheduled_start"]),
            "scheduled_end": iso(row["scheduled_end"]),
            "status": row["status"],
            "announced_at": iso(row["announced_at"]),
            "announcement_lead_bdays": row["announcement_lead_bdays"],
            "outcome_note": row["outcome_note"],
            "cancellation_reason": row["cancellation_reason"],
        }
    )
    return data


def format_review(row):
    data = _common(row)
    data.update(
        {
            "thesis_id": row["thesis_id"],
            "cycle_number": row["cycle_number"],
            "opened_at": iso(row["opened_at"]),
            "decided_at": iso(row["decided_at"]),
            "decided_by_user_id": row["decided_by_user_id"],
            "decision": row["decision"],
            "critical_defect_count": row["critical_defect_count"],
            "major_defect_count": row["major_defect_count"],
            "minor_defect_count": row["minor_defect_count"],
            "severity_weighted_defect_score": _num(row["severity_weighted_defect_score"]),
            "revision_due_at": iso(row["revision_due_at"]),
            "turnaround_bdays": row["turnaround_bdays"],
            "status": row["status"],
        }
    )
    return data


def embargo_request(row):
    data = _common(row)
    data.update(
        {
            "thesis_id": row["thesis_id"],
            "reason_code": row["reason_code"],
            "requested_months": row["requested_months"],
            "justification": row["justification"],
            "approved_months": row["approved_months"],
            "status": row["status"],
            "info_request_count": row["info_request_count"],
            "decided_by_user_id": row["decided_by_user_id"],
            "decided_at": iso(row["decided_at"]),
            "release_date": iso(row["release_date"]),
            "release_anchor": row["release_anchor"],
            "decision_note": row["decision_note"],
        }
    )
    return data


def permission_record(row):
    data = _common(row)
    data.update(
        {
            "thesis_id": row["thesis_id"],
            "material_type": row["material_type"],
            "rights_basis": row["rights_basis"],
            "page_reference": row["page_reference"],
            "excerpt_word_count": row["excerpt_word_count"],
            "document_uri": row["document_uri"],
            "status": row["status"],
            "reviewed_by_user_id": row["reviewed_by_user_id"],
            "review_note": row["review_note"],
        }
    )
    return data


def integrity_screening(row):
    data = _common(row)
    data.update(
        {
            "thesis_id": row["thesis_id"],
            "similarity_pct": _num(row["similarity_pct"]),
            "excluded_quoted_pct": _num(row["excluded_quoted_pct"]),
            "adjusted_similarity_pct": _num(row["adjusted_similarity_pct"]),
            "status": row["status"],
            "screened_at": iso(row["screened_at"]),
            "referred_at": iso(row["referred_at"]),
            "referred_by_user_id": row["referred_by_user_id"],
            "resolved_by_user_id": row["resolved_by_user_id"],
            "resolution_note": row["resolution_note"],
        }
    )
    return data


def repository_deposit(row):
    data = _common(row)
    data.update(
        {
            "thesis_id": row["thesis_id"],
            "handle": row["handle"],
            "abstract_word_count": row["abstract_word_count"],
            "subject_keywords": list(row["subject_keywords"]),
            "advisor_name": row["advisor_name"],
            "department_code": row["department_code"],
            "metadata_completeness_score": _num(row["metadata_completeness_score"]),
            "access_level": row["access_level"],
            "embargo_release_date": iso(row["embargo_release_date"]),
            "deposited_at": iso(row["deposited_at"]),
            "depositor_user_id": row["depositor_user_id"],
            "late_fee_cents": row["late_fee_cents"],
            "status": row["status"],
        }
    )
    return data


def graduation_clearance(row):
    data = _common(row)
    data.update(
        {
            "student_id": row["student_id"],
            "status": row["status"],
            "outstanding_items": list(row["outstanding_items"]),
            "projection_variant": row["projection_variant"],
            "cleared_at": iso(row["cleared_at"]),
            "conferral_posted_at": iso(row["conferral_posted_at"]),
            "transcript_notation": row["transcript_notation"],
            "withheld_reason": row["withheld_reason"],
        }
    )
    return data
