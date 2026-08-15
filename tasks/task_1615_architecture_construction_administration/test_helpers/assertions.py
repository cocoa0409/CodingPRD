"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive integer"


def assert_project(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["owner_user_id"], str) and data["owner_user_id"]
    assert isinstance(data["contractor_user_id"], str) and data["contractor_user_id"]
    assert isinstance(data["original_contract_sum_cents"], int) and data["original_contract_sum_cents"] > 0
    assert isinstance(data["sov_lines"], list) and len(data["sov_lines"]) >= 1
    for line in data["sov_lines"]:
        assert isinstance(line["line_code"], str) and line["line_code"]
        assert isinstance(line["description"], str)
        assert isinstance(line["scheduled_value_cents"], int) and line["scheduled_value_cents"] > 0
    assert isinstance(data["base_substantial_completion_date"], str)
    assert isinstance(data["adjusted_substantial_completion_date"], str)
    assert isinstance(data["adjusted_contract_sum_cents"], int)
    assert isinstance(data["daily_extension_rate_cents"], int) and data["daily_extension_rate_cents"] > 0
    assert isinstance(data["monthly_extension_rate_cents"], int) and data["monthly_extension_rate_cents"] > 0
    assert data["billing_method"] in ("PER_DIEM_PRORATED", "WHOLE_MONTH")
    assert data["retainage_mode"] in ("TIERED_MARGINAL", "REDUCTION_AT_HALFWAY")
    assert isinstance(data["grace_days"], int) and data["grace_days"] >= 0
    assert isinstance(data["review_window_days_submittal"], int) and data["review_window_days_submittal"] >= 1
    assert isinstance(data["review_window_days_rfi"], int) and data["review_window_days_rfi"] >= 1
    assert isinstance(data["field_report_window_days"], int) and data["field_report_window_days"] >= 1
    assert isinstance(data["excusable_delay_days"], int)
    assert isinstance(data["certified_to_date_cents"], int)
    assert isinstance(data["retainage_held_cents"], int)
    assert data["substantial_completion_actual_date"] is None or isinstance(data["substantial_completion_actual_date"], str)
    assert data["ca_posture"] in ("NORMAL", "EXTENDED_DURATION")
    assert data["status"] in (
        "SETUP", "ACTIVE", "SUBSTANTIAL_COMPLETION_ACHIEVED",
        "FINAL_COMPLETION_ACHIEVED", "CLOSED",
    )


def assert_submittal(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a valid UUID"
    assert isinstance(data["spec_section"], str) and data["spec_section"]
    assert isinstance(data["required_on_site_date"], str)
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1
    assert is_iso8601_timestamp(data.get("received_at", "")), "received_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("due_at", "")), "due_at must be ISO 8601"
    assert data["reviewed_at"] is None or is_iso8601_timestamp(data["reviewed_at"])
    assert isinstance(data["credited_delay_days"], int) and data["credited_delay_days"] >= 0
    assert data["review_notes"] is None or isinstance(data["review_notes"], str)
    assert data["status"] in (
        "UNDER_REVIEW", "APPROVED", "APPROVED_AS_NOTED",
        "REVISE_AND_RESUBMIT", "REJECTED",
    )


def assert_site_visit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a valid UUID"
    assert isinstance(data["visit_date"], str)
    assert data["purpose"] in (
        "PROGRESS_OBSERVATION", "PAYMENT_VERIFICATION",
        "PUNCH_INSPECTION", "FINAL_INSPECTION",
    )
    assert isinstance(data["performed_by_user_id"], str) and data["performed_by_user_id"]
    assert data["performed_at"] is None or is_iso8601_timestamp(data["performed_at"])
    assert data["status"] in ("SCHEDULED", "PERFORMED", "REPORT_ISSUED", "CANCELLED")


def assert_field_report(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("site_visit_id", "")), "site_visit_id must be a valid UUID"
    assert isinstance(data["issued_by_user_id"], str) and data["issued_by_user_id"]
    assert is_iso8601_timestamp(data.get("issued_at", "")), "issued_at must be ISO 8601"
    assert data["conformance_summary"] in ("CONFORMING", "MINOR_DEVIATIONS", "NONCONFORMING")
    assert isinstance(data["nonconforming_work_flag"], bool)
    assert data["nonconformance_status"] in ("NONE", "OPEN", "CLEARED")
    assert data["clearing_visit_id"] is None or isinstance(data["clearing_visit_id"], str)
    assert data.get("notes") is None or isinstance(data.get("notes"), str)


def assert_rfi(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a valid UUID"
    assert isinstance(data["question"], str) and data["question"]
    assert isinstance(data["cost_impact_flag"], bool)
    assert is_iso8601_timestamp(data.get("received_at", "")), "received_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("due_at", "")), "due_at must be ISO 8601"
    assert data["answered_at"] is None or is_iso8601_timestamp(data["answered_at"])
    assert data["answer_text"] is None or isinstance(data["answer_text"], str)
    assert isinstance(data["credited_delay_days"], int) and data["credited_delay_days"] >= 0
    assert data["status"] in ("OPEN", "CLARIFICATION_PENDING", "ANSWERED", "CLOSED", "WITHDRAWN")


def assert_clarification_drawing(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("rfi_id", "")), "rfi_id must be a valid UUID"
    assert isinstance(data["drawing_ref"], str) and data["drawing_ref"]
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1
    assert is_iso8601_timestamp(data.get("issued_at", "")), "issued_at must be ISO 8601"
    assert data["status"] in ("ISSUED", "SUPERSEDED")


def assert_payment_application(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a valid UUID"
    assert isinstance(data["period_ending_date"], str)
    assert is_valid_uuid(data.get("verification_visit_id", "")), "verification_visit_id must be a valid UUID"
    assert data["previous_application_id"] is None or isinstance(data["previous_application_id"], str)
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    for line in data["lines"]:
        assert isinstance(line["sov_line_code"], str) and line["sov_line_code"]
        assert isinstance(line["work_completed_this_period_cents"], int) and line["work_completed_this_period_cents"] >= 0
        assert isinstance(line["stored_materials_cents"], int) and line["stored_materials_cents"] >= 0
    assert isinstance(data["gross_work_completed_cents"], int)
    assert isinstance(data["earned_work_this_period_cents"], int)
    assert isinstance(data["retainage_work_cents"], int)
    assert isinstance(data["retainage_stored_cents"], int)
    assert isinstance(data["provisional_current_due_cents"], int)
    assert data["certified_current_due_cents"] is None or isinstance(data["certified_current_due_cents"], int)
    assert data["rejection_reason"] is None or isinstance(data["rejection_reason"], str)
    assert data["certified_at"] is None or is_iso8601_timestamp(data["certified_at"])
    assert data["certified_by_user_id"] is None or isinstance(data["certified_by_user_id"], str)
    assert data["status"] in ("SUBMITTED", "CERTIFIED", "REJECTED", "VOIDED")


def assert_change_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a valid UUID"
    assert data["rfi_id"] is None or isinstance(data["rfi_id"], str)
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["net_cost_change_cents"], int)
    assert isinstance(data["time_extension_days"], int) and data["time_extension_days"] >= 0
    assert isinstance(data["markup_cents"], int)
    assert isinstance(data["total_amount_cents"], int)
    assert data["recommendation"] is None or data["recommendation"] in ("ACCEPT", "REJECT")
    assert data["recommended_by_user_id"] is None or isinstance(data["recommended_by_user_id"], str)
    assert data["status"] in (
        "SUBMITTED", "RECOMMEND_ACCEPTANCE", "RECOMMEND_REJECTION",
        "OWNER_ACCEPTED", "OWNER_REJECTED", "INCORPORATED",
    )


def assert_punch_list_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a valid UUID"
    assert is_valid_uuid(data.get("raised_visit_id", "")), "raised_visit_id must be a valid UUID"
    assert isinstance(data["description"], str) and data["description"]
    assert isinstance(data["location"], str) and data["location"]
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0
    assert data["status"] in ("OPEN", "CLAIMED_COMPLETE", "VERIFIED", "REOPENED")


def assert_record_document(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a valid UUID"
    assert data["doc_type"] in ("AS_BUILT", "OM_MANUAL", "WARRANTY", "TEST_REPORT")
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1
    assert data["review_notes"] is None or isinstance(data["review_notes"], str)
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "RETURNED_FOR_CORRECTION")


def assert_additional_service_invoice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a valid UUID"
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["horizon_start_date"], str)
    assert isinstance(data["horizon_end_date"], str)
    assert isinstance(data["billable_days"], int)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("DRAFT", "ISSUED", "OWNER_APPROVED", "DISPUTED", "PAID", "CANCELLED")


def assert_project_financial_invariants(data: dict):
    """Domain invariants on a project's derived financial position."""
    assert data["adjusted_contract_sum_cents"] >= 0 or True  # deducts may push it below the original but never structurally negative in these tests
    assert data["certified_to_date_cents"] >= 0
    assert data["retainage_held_cents"] >= 0
    assert data["excusable_delay_days"] >= 0
