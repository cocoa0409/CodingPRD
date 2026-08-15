"""Payload factories — one per creatable resource, input fields only."""

SNS_NARRATIVE = (
    "State and local funds are distributed uniformly per pupil across all "
    "district schools regardless of Title I status."
)  # comfortably above the 50-character narrative floor (PRD §3.5)

CAP_NARRATIVE = (
    "The district will revise the documented practice, retrain staff, and "
    "attach corrected evidence for the monitor."
)  # comfortably above the 50-character CAP narrative floor (PRD §3.9)


def create_grant_payload(fiscal_year=2051, total_allocation_cents=10_000_000,
                         poverty_measure="CENSUS_SAIPE",
                         carryover_in_cents=None, admin_reserve_cents=None,
                         equitable_count_method=None, **extra):
    payload = {
        "fiscal_year": fiscal_year,
        "total_allocation_cents": total_allocation_cents,
        "poverty_measure": poverty_measure,
    }
    if carryover_in_cents is not None:
        payload["carryover_in_cents"] = carryover_in_cents
    if admin_reserve_cents is not None:
        payload["admin_reserve_cents"] = admin_reserve_cents
    if equitable_count_method is not None:
        payload["equitable_count_method"] = equitable_count_method
    payload.update(extra)
    return payload


def create_school_payload(name="Test School", nces_id="900001",
                          grade_span_low=0, grade_span_high=12,
                          is_active=None, **extra):
    payload = {
        "name": name,
        "nces_id": nces_id,
        "grade_span_low": grade_span_low,
        "grade_span_high": grade_span_high,
    }
    if is_active is not None:
        payload["is_active"] = is_active
    payload.update(extra)
    return payload


def create_private_school_payload(name="Test Academy",
                                  low_income_resident_count=10,
                                  contact_email="ombudsman@example.org",
                                  nonprofit_verified=None, **extra):
    payload = {
        "name": name,
        "low_income_resident_count": low_income_resident_count,
        "contact_email": contact_email,
    }
    if nonprofit_verified is not None:
        payload["nonprofit_verified"] = nonprofit_verified
    payload.update(extra)
    return payload


def snapshot_entry(school_id, low_income_student_count, total_student_count):
    return {
        "school_id": school_id,
        "low_income_student_count": low_income_student_count,
        "total_student_count": total_student_count,
    }


def create_snapshot_payload(grant_id, entries, measure="CENSUS_SAIPE",
                            **extra):
    payload = {
        "grant_id": grant_id,
        "measure": measure,
        "entries": entries,
    }
    payload.update(extra)
    return payload


def create_sns_payload(school_allocation_id, methodology="PER_PUPIL_FORMULA",
                       coverage_start_date="2026-07-01",
                       coverage_end_date="2027-07-01",
                       narrative=SNS_NARRATIVE, **extra):
    payload = {
        "school_allocation_id": school_allocation_id,
        "methodology": methodology,
        "coverage_start_date": coverage_start_date,
        "coverage_end_date": coverage_end_date,
        "narrative": narrative,
    }
    payload.update(extra)
    return payload


def create_consultation_payload(grant_id, private_school_id, **extra):
    payload = {"grant_id": grant_id, "private_school_id": private_school_id}
    payload.update(extra)
    return payload


def record_session_payload(session_date="2026-08-01", topics="needs assessment",
                           attendee_count=3, **extra):
    payload = {
        "session_date": session_date,
        "topics": topics,
        "attendee_count": attendee_count,
    }
    payload.update(extra)
    return payload


def create_expenditure_payload(grant_id, amount_cents, incurred_date,
                               function_code="INSTRUCTION",
                               description="program cost",
                               school_allocation_id=None, set_aside_id=None,
                               supplant_screen=None, **extra):
    payload = {
        "grant_id": grant_id,
        "amount_cents": amount_cents,
        "function_code": function_code,
        "description": description,
        "incurred_date": incurred_date,
    }
    if school_allocation_id is not None:
        payload["school_allocation_id"] = school_allocation_id
    if set_aside_id is not None:
        payload["set_aside_id"] = set_aside_id
    if supplant_screen is not None:
        payload["supplant_screen"] = supplant_screen
    payload.update(extra)
    return payload


def amendment_line(target_type, target_id, new_amount_cents):
    return {
        "target_type": target_type,
        "target_id": target_id,
        "new_amount_cents": new_amount_cents,
    }


def create_amendment_payload(grant_id, expected_grant_version, lines, **extra):
    payload = {
        "grant_id": grant_id,
        "expected_grant_version": expected_grant_version,
        "lines": lines,
    }
    payload.update(extra)
    return payload


def create_visit_payload(grant_id, visit_start_date="2026-08-01",
                         visit_end_date="2026-08-05", scope="PROGRAMMATIC",
                         **extra):
    payload = {
        "grant_id": grant_id,
        "visit_start_date": visit_start_date,
        "visit_end_date": visit_end_date,
        "scope": scope,
    }
    payload.update(extra)
    return payload


def create_finding_payload(visit_id, citation="34 CFR 200.77",
                           severity="FINDING",
                           description="ranking documentation incomplete",
                           cap_due_date="2026-08-10", **extra):
    payload = {
        "visit_id": visit_id,
        "citation": citation,
        "severity": severity,
        "description": description,
        "cap_due_date": cap_due_date,
    }
    payload.update(extra)
    return payload
