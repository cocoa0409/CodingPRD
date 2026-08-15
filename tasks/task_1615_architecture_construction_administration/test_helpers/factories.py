"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PROJECT_NAME": "Test Project",
    "OWNER_USER_ID": "user-owner-1",
    "CONTRACTOR_USER_ID": "user-contractor-1",
    "ORIGINAL_CONTRACT_SUM_CENTS": 10000000,
    "BASE_SCD": "2026-09-30",
    "DAILY_EXTENSION_RATE_CENTS": 120000,
    "MONTHLY_EXTENSION_RATE_CENTS": 3000000,
    "BILLING_METHOD": "PER_DIEM_PRORATED",
    "RETAINAGE_MODE": "TIERED_MARGINAL",
    "SPEC_SECTION": "03 30 00",
    "REQUIRED_ON_SITE_DATE": "2026-08-25",
    "VISIT_DATE": "2026-08-20",
    "VISIT_PURPOSE": "PAYMENT_VERIFICATION",
    "VISIT_PERFORMER": "user-arch-2",
    "REPORT_ISSUER": "user-arch-lead",
    "CONFORMANCE_SUMMARY": "CONFORMING",
    "RFI_QUESTION": "Confirm anchor bolt embedment",
    "DRAWING_REF": "SK-12",
    "PERIOD_ENDING_DATE": "2026-08-31",
    "CO_TITLE": "Change order",
    "NET_COST_CHANGE_CENTS": 1000000,
    "PUNCH_DESCRIPTION": "Paint touch-up",
    "PUNCH_LOCATION": "Level 1 lobby",
    "DOC_TYPE": "AS_BUILT",
    "INVOICE_PERIOD_START": "2026-10-01",
    "INVOICE_PERIOD_END": "2026-10-31",
    "REJECTION_REASON": "arithmetic error",
    "REOPEN_REASON": "work not acceptable",
    "REVIEW_NOTES": "reviewed",
    "ANSWER_TEXT": "Per specification",
}


def _sov_lines_single(amount=10000000):
    return [{"line_code": "A", "description": "Concrete", "scheduled_value_cents": amount}]


def _sov_lines_two(a=6000000, b=4000000):
    return [
        {"line_code": "A", "description": "Concrete", "scheduled_value_cents": a},
        {"line_code": "B", "description": "Metals", "scheduled_value_cents": b},
    ]


def create_project_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PROJECT_NAME"],
        "owner_user_id": DEFAULTS["OWNER_USER_ID"],
        "contractor_user_id": DEFAULTS["CONTRACTOR_USER_ID"],
        "original_contract_sum_cents": DEFAULTS["ORIGINAL_CONTRACT_SUM_CENTS"],
        "sov_lines": _sov_lines_two(),
        "base_substantial_completion_date": DEFAULTS["BASE_SCD"],
        "daily_extension_rate_cents": DEFAULTS["DAILY_EXTENSION_RATE_CENTS"],
        "monthly_extension_rate_cents": DEFAULTS["MONTHLY_EXTENSION_RATE_CENTS"],
        "billing_method": DEFAULTS["BILLING_METHOD"],
        "retainage_mode": DEFAULTS["RETAINAGE_MODE"],
    }
    defaults.update(overrides)
    return defaults


def create_submittal_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "spec_section": DEFAULTS["SPEC_SECTION"],
        "required_on_site_date": DEFAULTS["REQUIRED_ON_SITE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def submittal_review_payload(**overrides) -> dict:
    defaults = {"outcome": "APPROVED"}
    defaults.update(overrides)
    return defaults


def create_site_visit_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "visit_date": DEFAULTS["VISIT_DATE"],
        "purpose": DEFAULTS["VISIT_PURPOSE"],
        "performed_by_user_id": DEFAULTS["VISIT_PERFORMER"],
    }
    defaults.update(overrides)
    return defaults


def create_field_report_payload(site_visit_id, **overrides) -> dict:
    defaults = {
        "site_visit_id": site_visit_id,
        "issued_by_user_id": DEFAULTS["REPORT_ISSUER"],
        "conformance_summary": DEFAULTS["CONFORMANCE_SUMMARY"],
        "nonconforming_work_flag": False,
    }
    defaults.update(overrides)
    return defaults


def clear_nonconformance_payload(clearing_visit_id, **overrides) -> dict:
    defaults = {"clearing_visit_id": clearing_visit_id}
    defaults.update(overrides)
    return defaults


def create_rfi_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "question": DEFAULTS["RFI_QUESTION"],
    }
    defaults.update(overrides)
    return defaults


def rfi_answer_payload(**overrides) -> dict:
    defaults = {
        "answer_text": DEFAULTS["ANSWER_TEXT"],
        "requires_clarification_drawing": False,
    }
    defaults.update(overrides)
    return defaults


def create_clarification_drawing_payload(rfi_id, expected_rfi_version, **overrides) -> dict:
    defaults = {
        "rfi_id": rfi_id,
        "drawing_ref": DEFAULTS["DRAWING_REF"],
        "expected_rfi_version": expected_rfi_version,
    }
    defaults.update(overrides)
    return defaults


def payment_application_lines_single(sov_line_code="A", work=1000000, stored=0):
    return [{
        "sov_line_code": sov_line_code,
        "work_completed_this_period_cents": work,
        "stored_materials_cents": stored,
    }]


def create_payment_application_payload(project_id, verification_visit_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "period_ending_date": DEFAULTS["PERIOD_ENDING_DATE"],
        "verification_visit_id": verification_visit_id,
        "lines": payment_application_lines_single(),
    }
    defaults.update(overrides)
    return defaults


def reject_payment_application_payload(**overrides) -> dict:
    defaults = {"reason": DEFAULTS["REJECTION_REASON"]}
    defaults.update(overrides)
    return defaults


def resubmit_payment_application_payload(verification_visit_id, **overrides) -> dict:
    defaults = {
        "period_ending_date": DEFAULTS["PERIOD_ENDING_DATE"],
        "verification_visit_id": verification_visit_id,
        "lines": payment_application_lines_single(),
    }
    defaults.update(overrides)
    return defaults


def create_change_order_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "title": DEFAULTS["CO_TITLE"],
        "net_cost_change_cents": DEFAULTS["NET_COST_CHANGE_CENTS"],
        "time_extension_days": 0,
    }
    defaults.update(overrides)
    return defaults


def recommend_change_order_payload(**overrides) -> dict:
    defaults = {"recommendation": "ACCEPT"}
    defaults.update(overrides)
    return defaults


def owner_decision_payload(**overrides) -> dict:
    defaults = {"decision": "ACCEPT"}
    defaults.update(overrides)
    return defaults


def incorporate_change_order_payload(expected_project_version, **overrides) -> dict:
    defaults = {"expected_project_version": expected_project_version}
    defaults.update(overrides)
    return defaults


def create_punch_list_item_payload(project_id, raised_visit_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "raised_visit_id": raised_visit_id,
        "description": DEFAULTS["PUNCH_DESCRIPTION"],
        "location": DEFAULTS["PUNCH_LOCATION"],
    }
    defaults.update(overrides)
    return defaults


def reopen_punch_item_payload(**overrides) -> dict:
    defaults = {"reason": DEFAULTS["REOPEN_REASON"]}
    defaults.update(overrides)
    return defaults


def create_record_document_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "doc_type": DEFAULTS["DOC_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def review_record_document_payload(**overrides) -> dict:
    defaults = {"outcome": "ACCEPT"}
    defaults.update(overrides)
    return defaults


def create_additional_service_invoice_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "period_start": DEFAULTS["INVOICE_PERIOD_START"],
        "period_end": DEFAULTS["INVOICE_PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def invoice_owner_decision_payload(**overrides) -> dict:
    defaults = {"decision": "APPROVE"}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601="2026-08-01T00:00:00Z") -> dict:
    return {"to_iso8601": to_iso8601}
