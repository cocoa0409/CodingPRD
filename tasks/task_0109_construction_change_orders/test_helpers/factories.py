"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PROJECT_NAME": "Test Project",
    "OWNER_USER_ID": "owner-1",
    "ORIGINAL_CONTRACT_SUM_CENTS": 1_000_000,
    "DEFAULT_RETAINAGE_PCT": 0.10,
}


def create_project_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PROJECT_NAME"],
        "owner_user_id": DEFAULTS["OWNER_USER_ID"],
        "original_contract_sum_cents": DEFAULTS["ORIGINAL_CONTRACT_SUM_CENTS"],
        "default_retainage_pct": DEFAULTS["DEFAULT_RETAINAGE_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_sov_line_payload(project_id, item_no, scheduled_value_cents, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "item_no": item_no,
        "description": "Work item",
        "scheduled_value_cents": scheduled_value_cents,
    }
    defaults.update(overrides)
    return defaults


def create_change_order_payload(project_id, co_number, change_order_amount_cents,
                                line_edits, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "co_number": co_number,
        "change_order_amount_cents": change_order_amount_cents,
        "line_edits": line_edits,
    }
    defaults.update(overrides)
    return defaults


def create_pay_application_payload(project_id, application_number, period_from,
                                   period_to, expected_project_version, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "application_number": application_number,
        "period_from": period_from,
        "period_to": period_to,
        "expected_project_version": expected_project_version,
    }
    defaults.update(overrides)
    return defaults


def create_pay_app_line_payload(pay_app_id, sov_line_id,
                                work_completed_this_period_cents, **overrides) -> dict:
    defaults = {
        "pay_app_id": pay_app_id,
        "sov_line_id": sov_line_id,
        "work_completed_this_period_cents": work_completed_this_period_cents,
    }
    defaults.update(overrides)
    return defaults


def create_subcontractor_commitment_payload(project_id, subcontractor_name,
                                            committed_amount_cents, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "subcontractor_name": subcontractor_name,
        "committed_amount_cents": committed_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_rfi_payload(project_id, subject, question, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "subject": subject,
        "question": question,
    }
    defaults.update(overrides)
    return defaults


def create_submittal_payload(project_id, spec_section, title, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "spec_section": spec_section,
        "title": title,
    }
    defaults.update(overrides)
    return defaults


def create_lien_waiver_payload(project_id, pay_app_id, waiver_type, through_date,
                               amount_cents, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "pay_app_id": pay_app_id,
        "waiver_type": waiver_type,
        "through_date": through_date,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_punch_item_payload(project_id, location, description, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "location": location,
        "description": description,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_window_payload(project_id, inspector_name, scheduled_start,
                                     scheduled_end, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "inspector_name": inspector_name,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults


def create_retention_release_payload(project_id, amount_cents,
                                     expected_project_version, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "amount_cents": amount_cents,
        "expected_project_version": expected_project_version,
    }
    defaults.update(overrides)
    return defaults
