"""Public JSON projections of each entity.

Each serializer returns the exact field set declared in SCAFFOLD §1.1 plus the
common fields. Internal bookkeeping (the _seq insertion sequence) is stripped.
We project explicitly (rather than dumping the dict) so field presence is
deterministic regardless of how the record was built internally.
"""


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def onboarding(rec):
    out = _common(rec)
    out.update({
        "employee_full_name": rec.get("employee_full_name"),
        "employee_email": rec.get("employee_email"),
        "citizenship_status": rec.get("citizenship_status"),
        "hire_date": rec.get("hire_date"),
        "work_auth_expiration": rec.get("work_auth_expiration"),
        "status": rec.get("status"),
        "section2_deadline": rec.get("section2_deadline"),
        "is_overdue": rec.get("is_overdue", False),
        "requires_everify": rec.get("requires_everify", True),
    })
    return out


def i9_form(rec):
    out = _common(rec)
    out.update({
        "onboarding_id": rec.get("onboarding_id"),
        "section1_attested_at": rec.get("section1_attested_at"),
        "section1_preparer_used": rec.get("section1_preparer_used", False),
        "chosen_document_path": rec.get("chosen_document_path", "UNSET"),
        "section2_reviewer_id": rec.get("section2_reviewer_id"),
        "section2_completed_at": rec.get("section2_completed_at"),
        "current_section3_count": rec.get("current_section3_count", 0),
        "status": rec.get("status"),
    })
    return out


def identity_document(rec):
    out = _common(rec)
    out.update({
        "onboarding_id": rec.get("onboarding_id"),
        "list_category": rec.get("list_category"),
        "document_title": rec.get("document_title"),
        "document_number": rec.get("document_number"),
        "expiration_date": rec.get("expiration_date"),
        "is_receipt": rec.get("is_receipt", False),
        "receipt_resolution_deadline": rec.get("receipt_resolution_deadline"),
        "accepted_for_section2": rec.get("accepted_for_section2", False),
        "status": rec.get("status"),
    })
    return out


def everify_case(rec):
    out = _common(rec)
    out.update({
        "onboarding_id": rec.get("onboarding_id"),
        "i9_form_id": rec.get("i9_form_id"),
        "submitted_at": rec.get("submitted_at"),
        "everify_deadline": rec.get("everify_deadline"),
        "was_late": rec.get("was_late", False),
        "late_reason": rec.get("late_reason"),
        "tnc_type": rec.get("tnc_type", "NONE"),
        "tnc_issued_at": rec.get("tnc_issued_at"),
        "referral_deadline": rec.get("referral_deadline"),
        "status": rec.get("status"),
    })
    return out


def work_authorization(rec):
    out = _common(rec)
    out.update({
        "onboarding_id": rec.get("onboarding_id"),
        "auth_type": rec.get("auth_type"),
        "valid_from": rec.get("valid_from"),
        "valid_until": rec.get("valid_until"),
        "stem_extension_applied": rec.get("stem_extension_applied", False),
        "cap_gap_days": rec.get("cap_gap_days", 0),
        "effective_valid_until": rec.get("effective_valid_until"),
        "supersedes_id": rec.get("supersedes_id"),
        "status": rec.get("status"),
    })
    return out


def reverification_event(rec):
    out = _common(rec)
    out.update({
        "i9_form_id": rec.get("i9_form_id"),
        "work_authorization_id": rec.get("work_authorization_id"),
        "reverification_reason": rec.get("reverification_reason"),
        "new_expiration_date": rec.get("new_expiration_date"),
        "reviewer_id": rec.get("reviewer_id"),
        "completed_at": rec.get("completed_at"),
        "status": rec.get("status"),
    })
    return out


def audit_entry(rec):
    # AuditEntry: only id + created_at among the common fields (PRD §2.4).
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "onboarding_id": rec.get("onboarding_id"),
        "actor_role": rec.get("actor_role"),
        "actor_user_id": rec.get("actor_user_id"),
        "action": rec.get("action"),
        "detail": rec.get("detail"),
    }
