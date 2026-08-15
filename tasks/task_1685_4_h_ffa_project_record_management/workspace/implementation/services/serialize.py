"""Entity serializers. Only the fields declared for each entity in the scaffold
are emitted; internal helpers (keys starting with "_") are never serialized.

Versioned entities (PRD 2.4) carry id, created_at, updated_at, version.
Audit lines (ledger entries, attendance, screening events, treasury
transactions) carry only id and created_at.
"""


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def _audit(rec):
    return {"id": rec["id"], "created_at": rec["created_at"]}


def club_view(rec):
    out = _common(rec)
    out.update({
        "name": rec["name"],
        "county_code": rec["county_code"],
        "treasury_balance_cents": rec["treasury_balance_cents"],
        "star_nomination_count": rec["star_nomination_count"],
        "status": rec["status"],
    })
    return out


def volunteer_view(rec):
    out = _common(rec)
    out.update({
        "full_name": rec["full_name"],
        "email": rec["email"],
        "base_clearance": rec["base_clearance"],
        "risk_flags": rec["risk_flags"],
        "years_service": rec["years_service"],
        "screening_score": rec["screening_score"],
        "screening_status": rec["screening_status"],
        "club_id": rec["club_id"],
    })
    return out


def member_view(rec):
    out = _common(rec)
    out.update({
        "full_name": rec["full_name"],
        "birth_date": rec["birth_date"],
        "club_id": rec["club_id"],
        "enrollment_status": rec["enrollment_status"],
        "is_club_officer": rec["is_club_officer"],
        "eligibility_posture": rec["eligibility_posture"],
    })
    return out


def project_view(rec):
    out = _common(rec)
    out.update({
        "member_id": rec["member_id"],
        "project_type": rec["project_type"],
        "program_year": rec["program_year"],
        "status": rec["status"],
        "grade": rec["grade"],
    })
    return out


def animal_tag_view(rec):
    out = _common(rec)
    out.update({
        "project_id": rec["project_id"],
        "tag_number": rec["tag_number"],
        "species": rec["species"],
        "owned_since": rec["owned_since"],
        "tagged_at": rec["tagged_at"],
        "tagging_status": rec["tagging_status"],
    })
    return out


def record_book_view(rec):
    out = _common(rec)
    out.update({
        "project_id": rec["project_id"],
        "program_year": rec["program_year"],
        "status": rec["status"],
        "submitted_at": rec["submitted_at"],
        "provisional_score": rec["provisional_score"],
        "final_score": rec["final_score"],
        "late_days": rec["late_days"],
    })
    return out


def ledger_entry_view(rec):
    out = _audit(rec)
    out.update({
        "record_book_id": rec["record_book_id"],
        "entry_kind": rec["entry_kind"],
        "amount_cents": rec["amount_cents"],
        "hours": rec["hours"],
        "entry_status": rec["entry_status"],
        "recorded_on": rec["recorded_on"],
    })
    return out


def meeting_view(rec):
    out = _common(rec)
    out.update({
        "club_id": rec["club_id"],
        "starts_at": rec["starts_at"],
        "ends_at": rec["ends_at"],
        "room_id": rec["room_id"],
        "status": rec["status"],
    })
    return out


def room_view(rec):
    out = _common(rec)
    out.update({
        "name": rec["name"],
        "capacity": rec["capacity"],
    })
    return out


def attendance_view(rec):
    out = _audit(rec)
    out.update({
        "meeting_id": rec["meeting_id"],
        "member_id": rec["member_id"],
        "attendance_status": rec["attendance_status"],
    })
    return out


def fair_entry_view(rec):
    out = _common(rec)
    out.update({
        "member_id": rec["member_id"],
        "project_id": rec["project_id"],
        "fair_level": rec["fair_level"],
        "status": rec["status"],
        "ownership_days_at_entry": rec["ownership_days_at_entry"],
    })
    return out


def stall_assignment_view(rec):
    out = _common(rec)
    out.update({
        "fair_entry_id": rec["fair_entry_id"],
        "pen_id": rec["pen_id"],
        "status": rec["status"],
    })
    return out


def pen_view(rec):
    out = _common(rec)
    out.update({
        "label": rec["label"],
        "animal_capacity": rec["animal_capacity"],
    })
    return out


def award_application_view(rec):
    out = _common(rec)
    out.update({
        "member_id": rec["member_id"],
        "award_track": rec["award_track"],
        "record_book_id": rec["record_book_id"],
        "status": rec["status"],
        "rubric_score": rec["rubric_score"],
        "award_tier": rec["award_tier"],
        "nominated_by": rec["nominated_by"],
    })
    return out


def scholarship_app_view(rec):
    out = _common(rec)
    out.update({
        "member_id": rec["member_id"],
        "linked_award_application_id": rec["linked_award_application_id"],
        "status": rec["status"],
        "scholarship_points": rec["scholarship_points"],
    })
    return out


def screening_event_view(rec):
    out = _audit(rec)
    out.update({
        "volunteer_id": rec["volunteer_id"],
        "event_kind": rec["event_kind"],
        "outcome": rec["outcome"],
    })
    return out


def treasury_transaction_view(rec):
    out = _audit(rec)
    out.update({
        "club_id": rec["club_id"],
        "txn_kind": rec["txn_kind"],
        "amount_cents": rec["amount_cents"],
        "txn_status": rec["txn_status"],
    })
    return out
