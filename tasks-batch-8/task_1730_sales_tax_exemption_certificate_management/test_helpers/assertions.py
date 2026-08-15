"""Entity assertions and domain invariant checkers (PRD §2.5 common fields,
§3 entity field definitions)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_tenant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["home_state_code"], str) and len(data["home_state_code"]) == 2
    assert isinstance(data["audit_clock_day_index"], int) and data["audit_clock_day_index"] >= 0
    assert data["audit_posture"] in ("CLEAR", "UNDER_SAMPLING", "IN_REMEDIATION", "DEFENSE_ASSEMBLY")
    assert isinstance(data["open_exposure_cents"], int) and data["open_exposure_cents"] >= 0


def assert_jurisdiction_rule(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["accepted_form_types"], list)
    assert isinstance(data["validity_window_days"], int) and data["validity_window_days"] >= 0
    assert data["anchor_rule"] in ("EFFECTIVE_DATE", "SIGNED_DATE")
    assert isinstance(data["allows_drop_ship_resale"], bool)
    assert isinstance(data["requires_state_registration_number"], bool)
    assert isinstance(data["blanket_cert_allowed"], bool)


def assert_exemption_reason(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["tax_engine_code"], str) and data["tax_engine_code"]
    assert isinstance(data["requires_certificate"], bool)
    assert isinstance(data["allowed_form_types"], list)


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["external_ref"], str) and data["external_ref"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["primary_ship_to_state"], str)
    assert data["cert_standing"] in ("MISSING", "PARTIAL", "COMPLIANT")
    assert data["audit_standing"] in ("NOT_UNDER_AUDIT", "SAMPLED", "FAILED_SAMPLING", "REMEDIATED")
    assert data["collection_standing"] in ("CURRENT", "RENEWAL_DUE", "LAPSED")
    assert "onboarding_completed_at" in data
    assert isinstance(data["blocked_exposure_cents"], int) and data["blocked_exposure_cents"] >= 0


def assert_certificate(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["ship_to_state"], str) and len(data["ship_to_state"]) == 2
    assert data["form_type"] in (
        "RESALE", "EXEMPT_ORG", "AGRICULTURAL", "MANUFACTURING", "DIRECT_PAY", "MULTI_JURISDICTION",
    )
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED",
        "SUSPENDED", "EXPIRED", "SUPERSEDED", "REVOKED",
    )
    assert "expiration_date" in data


def assert_certificate_version(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["certificate_id"], str)
    assert isinstance(data["version_index"], int) and data["version_index"] >= 1
    assert isinstance(data["file_uri"], str) and data["file_uri"]
    assert isinstance(data["uploaded_by_user_id"], str) and data["uploaded_by_user_id"]


def assert_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["order_ref"], str) and data["order_ref"]
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "HELD_FOR_CERT", "READY_TO_SHIP", "SHIPPED", "INVOICED", "CANCELLED",
    )
    for field in ("subtotal_cents", "exempt_amount_cents", "covered_amount_cents", "uncovered_amount_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert_order_amount_invariants(data)


def assert_order_amount_invariants(data: dict):
    """PRD §3.5: uncovered = exempt - covered; amounts are integer cents."""
    assert data["covered_amount_cents"] >= 0
    assert data["uncovered_amount_cents"] >= 0
    assert data["uncovered_amount_cents"] == data["exempt_amount_cents"] - data["covered_amount_cents"], (
        f"uncovered ({data['uncovered_amount_cents']}) != exempt ({data['exempt_amount_cents']}) "
        f"- covered ({data['covered_amount_cents']})"
    )


def assert_order_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["quantity"], int)
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["extended_cents"], int)
    assert data["extended_cents"] == data["quantity"] * data["unit_price_cents"], (
        "extended_cents must be the exact integer product of quantity and unit_price_cents"
    )
    assert isinstance(data["is_exempt_claimed"], bool)


def assert_drop_ship_link(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["retailer_customer_id"], str)
    assert isinstance(data["resale_certificate_id"], str)
    assert data["status"] in ("PENDING_VERIFICATION", "VERIFIED", "REJECTED")


def assert_audit_campaign(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["population_state_filter"], list)
    assert data["sampling_method"] in ("STATISTICAL", "FIXED_FLOOR")
    assert data["status"] in (
        "DRAFT", "SAMPLING", "FIELDWORK", "REMEDIATION", "DEFENSE_ASSEMBLY", "CLOSED", "CANCELLED",
    )


def assert_audit_sample(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["campaign_id"], str)
    assert isinstance(data["certificate_id"], str)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["sampled_at_day_index"], int)
    assert data["outcome"] in (
        "PENDING", "DOC_REQUESTED", "DOC_RECEIVED", "PASSED", "FAILED", "WAIVED", "EXPIRED_NO_RESPONSE",
    )


def assert_remediation_action(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sample_id"], str)
    assert data["action_type"] in ("COLLECT_NEW_CERT", "OBTAIN_LETTER", "ASSESS_TAX", "WAIVE_SAMPLE")
    assert isinstance(data["assigned_to_user_id"], str) and data["assigned_to_user_id"]
    assert data["status"] in ("OPEN", "IN_PROGRESS", "RESOLVED", "ESCALATED")


def assert_outreach_campaign(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["target_state_filter"], list)
    assert isinstance(data["days_before_expiration"], int)
    assert isinstance(data["scheduled_send_day_index"], int)
    assert isinstance(data["sent_count"], int) and data["sent_count"] >= 0
    assert data["status"] in ("DRAFT", "SCHEDULED", "SENDING", "DONE", "CANCELLED")


def assert_outreach_notice(data: dict):
    """PRD §2.5: OutreachNotice carries only id + created_at from the common set."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "OutreachNotice must not expose updated_at"
    assert "version" not in data, "OutreachNotice must not expose version"
    assert isinstance(data["campaign_id"], str)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["certificate_id"], str)
    assert isinstance(data["scheduled_send_day_index"], int)
    assert isinstance(data["sent_at_day_index"], int)


def assert_defense_packet(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["campaign_id"], str)
    assert isinstance(data["included_certificate_ids"], list)
    assert isinstance(data["missing_certificate_ids"], list)
    assert isinstance(data["completeness_score_pct"], int)
    assert 0 <= data["completeness_score_pct"] <= 100
    assert data["status"] in ("DRAFT", "ASSEMBLED", "DELIVERED")
