"""Entity -> public JSON dict serializers. Every serializer emits exactly the
fields from SCAFFOLD §1.1 plus the common fields (id, created_at, updated_at,
version). Internal bookkeeping keys (e.g. _seq) never leak.
"""

import services


def _common(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def student_out(e):
    out = _common(e)
    out.update({
        "sevis_id": e["sevis_id"],
        "full_name": e["full_name"],
        "email": e["email"],
        "date_of_birth": e["date_of_birth"],
        "country_of_citizenship": e["country_of_citizenship"],
        "degree_level": e["degree_level"],
        "compliance_posture": e["compliance_posture"],
    })
    return out


def financial_document_out(e):
    out = _common(e)
    out.update({
        "student_id": e["student_id"],
        "document_type": e["document_type"],
        "amount_usd_cents": e["amount_usd_cents"],
        "issue_date": e["issue_date"],
        "status": e["status"],
        "review_note": e["review_note"],
    })
    return out


def sevis_record_out(e):
    out = _common(e)
    out.update({
        "student_id": e["student_id"],
        "program_start_date": e["program_start_date"],
        "program_end_date": e["program_end_date"],
        "status": e["status"],
        "termination_reason": e["termination_reason"],
    })
    return out


def i20_form_out(e):
    out = _common(e)
    # Funding figures are snapshotted at issuance; on a DRAFT form the
    # provisional/verified figures are live advisory pre-checks (PRD §3.2).
    if e["status"] == "DRAFT":
        verified, provisional = services.funding_cents(e["student_id"])
    else:
        verified = e["verified_funding_cents"]
        provisional = e["provisional_funding_cents"]
    out.update({
        "student_id": e["student_id"],
        "sevis_record_id": e["sevis_record_id"],
        "program_name": e["program_name"],
        "program_start_date": e["program_start_date"],
        "program_end_date": e["program_end_date"],
        "tuition_cents": e["tuition_cents"],
        "living_cents": e["living_cents"],
        "insurance_cents": e["insurance_cents"],
        "other_cents": e["other_cents"],
        "estimated_total_cents": (
            e["tuition_cents"] + e["living_cents"]
            + e["insurance_cents"] + e["other_cents"]
        ),
        "verified_funding_cents": verified,
        "provisional_funding_cents": provisional,
        "supersedes_i20_form_id": e["supersedes_i20_form_id"],
        "status": e["status"],
    })
    return out


def term_enrollment_out(e):
    out = _common(e)
    out.update({
        "student_id": e["student_id"],
        "term_code": e["term_code"],
        "term_start_date": e["term_start_date"],
        "term_end_date": e["term_end_date"],
        "enrolled_credits": e["enrolled_credits"],
        "effective_min_credits": e["effective_min_credits"],
        "status": e["status"],
    })
    return out


def reduced_course_load_out(e):
    out = _common(e)
    out.update({
        "enrollment_id": e["enrollment_id"],
        "reason_category": e["reason_category"],
        "requested_credits": e["requested_credits"],
        "status": e["status"],
        "decision_note": e["decision_note"],
    })
    return out


def employment_authorization_out(e):
    out = _common(e)
    settled, as_of = services.unemployment_counters(e)
    out.update({
        "student_id": e["student_id"],
        "auth_type": e["auth_type"],
        "employer_name": e["employer_name"],
        "hours_per_week": e["hours_per_week"],
        "start_date": e["start_date"],
        "end_date": e["end_date"],
        "uscis_receipt_number": e["uscis_receipt_number"],
        "unemployment_days_settled": settled,
        "unemployment_days_as_of": as_of,
        "status": e["status"],
    })
    return out


def employment_period_out(e):
    out = _common(e)
    out.update({
        "authorization_id": e["authorization_id"],
        "employer_name": e["employer_name"],
        "start_date": e["start_date"],
        "end_date": e["end_date"],
        "hours_per_week": e["hours_per_week"],
    })
    return out


def travel_endorsement_out(e):
    out = _common(e)
    out.update({
        "i20_form_id": e["i20_form_id"],
        "travel_departure_date": e["travel_departure_date"],
        "travel_return_date": e["travel_return_date"],
        "valid_until": e["valid_until"],
        "status": e["status"],
    })
    return out


def transfer_request_out(e):
    out = _common(e)
    out.update({
        "student_id": e["student_id"],
        "direction": e["direction"],
        "target_school_code": e["target_school_code"],
        "release_date": e["release_date"],
        "status": e["status"],
    })
    return out


def program_extension_out(e):
    out = _common(e)
    out.update({
        "student_id": e["student_id"],
        "new_program_end_date": e["new_program_end_date"],
        "reason": e["reason"],
        "status": e["status"],
        "decision_note": e["decision_note"],
    })
    return out


def status_violation_out(e):
    out = _common(e)
    out.update({
        "student_id": e["student_id"],
        "violation_type": e["violation_type"],
        "description": e["description"],
        "status": e["status"],
    })
    return out


def address_report_out(e):
    out = _common(e)
    out.update({
        "student_id": e["student_id"],
        "move_date": e["move_date"],
        "address_line1": e["address_line1"],
        "city": e["city"],
        "state_code": e["state_code"],
        "postal_code": e["postal_code"],
        "status": e["status"],
    })
    return out
