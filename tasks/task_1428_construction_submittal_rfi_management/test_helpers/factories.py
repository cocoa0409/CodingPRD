"""Payload factories — one per creatable resource, input fields only (PRD §3).

Optional fields are included only when explicitly supplied so tests can
observe documented server-side defaults (PRD §3.1) on minimal payloads.
"""


def create_project_payload(project_name="Test Project", **overrides) -> dict:
    payload = {"project_name": project_name}
    payload.update(overrides)
    return payload


def create_spec_section_payload(section_number="051200", **overrides) -> dict:
    payload = {"section_number": section_number}
    payload.update(overrides)
    return payload


def create_subcontractor_payload(
    company_name="Test Subcontractor", trade="general", **overrides
) -> dict:
    payload = {"company_name": company_name, "trade": trade}
    payload.update(overrides)
    return payload


def create_reviewer_payload(
    display_name="Reviewer One", discipline="ARCH", **overrides
) -> dict:
    payload = {"display_name": display_name, "discipline": discipline}
    payload.update(overrides)
    return payload


def create_revision_payload(
    document_ref, expected_submittal_version, notes=None
) -> dict:
    payload = {
        "document_ref": document_ref,
        "expected_submittal_version": expected_submittal_version,
    }
    if notes is not None:
        payload["notes"] = notes
    return payload


def create_rfi_payload(
    subject, question_text, expected_project_version, **overrides
) -> dict:
    payload = {
        "subject": subject,
        "question_text": question_text,
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload


def create_rfi_answer_payload(
    answer_text,
    cost_impact_flag=False,
    schedule_impact_flag=False,
    estimated_cost_cents=None,
    estimated_schedule_days=None,
) -> dict:
    payload = {
        "answer_text": answer_text,
        "cost_impact_flag": cost_impact_flag,
        "schedule_impact_flag": schedule_impact_flag,
    }
    if estimated_cost_cents is not None:
        payload["estimated_cost_cents"] = estimated_cost_cents
    if estimated_schedule_days is not None:
        payload["estimated_schedule_days"] = estimated_schedule_days
    return payload


def create_installation_activity_payload(
    submittal_id, subcontractor_id, start_date, end_date, description=None
) -> dict:
    payload = {
        "submittal_id": submittal_id,
        "subcontractor_id": subcontractor_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    if description is not None:
        payload["description"] = description
    return payload


def create_owner_report_payload(
    period_start, period_end, expected_project_version
) -> dict:
    return {
        "period_start": period_start,
        "period_end": period_end,
        "expected_project_version": expected_project_version,
    }


def create_price_payload(sub_quote_cents) -> dict:
    return {"sub_quote_cents": sub_quote_cents}


def create_lli_advance_payload(to_status, actual_date) -> dict:
    return {"to_status": to_status, "actual_date": actual_date}
