"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the response shape against the PRD contract,
using the framework's generic UUID / timestamp checkers internally.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id/created_at/updated_at/version property set carried by mutable entities."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_applicant(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["entity_type"] in ("INDIVIDUAL", "CORPORATION", "PARTNERSHIP", "LLC")
    assert isinstance(data["country_code"], str)
    assert isinstance(data["is_foreign_domiciled"], bool)
    assert isinstance(data["open_application_count"], int)
    assert data["open_application_count"] >= 0


def assert_attorney(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["bar_number"], str) and len(data["bar_number"]) > 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_nice_class(data: dict):
    """NiceClass is immutable: id + created_at only, no updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["class_number"], int)
    assert 1 <= data["class_number"] <= 45
    assert isinstance(data["is_service_class"], bool)


def assert_application(data: dict):
    _assert_common(data)
    assert isinstance(data["mark_text"], str) and len(data["mark_text"]) > 0
    assert data["filing_basis"] in ("USE", "INTENT")
    assert data["filing_tier"] in ("TEAS_PLUS", "TEAS_STANDARD")
    assert data["status"] in (
        "DRAFT", "FILED", "UNDER_EXAMINATION", "OFFICE_ACTION_ISSUED",
        "PUBLISHED", "ALLOWED", "ABANDONED", "REGISTERED",
    )
    assert isinstance(data["class_count"], int) and data["class_count"] >= 0
    assert isinstance(data["filing_fee_cents"], int) and data["filing_fee_cents"] >= 0
    assert isinstance(data["office_action_round"], int) and data["office_action_round"] >= 0


def assert_goods_services_item(data: dict):
    _assert_common(data)
    assert isinstance(data["description"], str) and len(data["description"]) > 0
    assert isinstance(data["pre_approved"], bool)
    assert data["use_status"] in ("NOT_IN_USE", "IN_USE")


def assert_office_action(data: dict):
    _assert_common(data)
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert isinstance(data["is_final"], bool)
    assert data["ground"] in (
        "LIKELIHOOD_OF_CONFUSION", "MERELY_DESCRIPTIVE",
        "SPECIMEN_DEFECT", "IDENTIFICATION_INDEFINITE",
    )
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["response_deadline"])
    assert data["status"] in ("OUTSTANDING", "RESPONDED", "EXPIRED")


def assert_office_action_response(data: dict):
    _assert_common(data)
    assert isinstance(data["argument_text"], str) and len(data["argument_text"]) > 0
    assert isinstance(data["days_late"], int) and data["days_late"] >= 0


def assert_statement_of_use(data: dict):
    _assert_common(data)
    assert isinstance(data["specimen_url"], str) and len(data["specimen_url"]) > 0
    assert isinstance(data["extension_number"], int)
    assert 0 <= data["extension_number"] <= 5
    assert data["status"] in ("SUBMITTED", "ACCEPTED")


def assert_ttab_proceeding(data: dict):
    _assert_common(data)
    assert data["proceeding_type"] in ("OPPOSITION", "CANCELLATION")
    assert data["claim_status"] in ("PLEADED", "TRIAL", "SUSTAINED", "DISMISSED", "WITHDRAWN")
    assert data["defense_status"] in ("AWAITING_ANSWER", "ANSWERED", "DEFAULTED")
    assert is_iso8601_timestamp(data["filed_at"])
    assert is_iso8601_timestamp(data["answer_deadline"])


def assert_registration(data: dict):
    _assert_common(data)
    assert isinstance(data["registration_number"], str) and len(data["registration_number"]) > 0
    assert is_iso8601_timestamp(data["registered_at"])
    assert data["status"] in ("ACTIVE", "GRACE", "CANCELLED", "EXPIRED")
    assert isinstance(data["maintenance_cycle"], int) and data["maintenance_cycle"] >= 0


def assert_maintenance_filing(data: dict):
    _assert_common(data)
    assert data["filing_type"] in ("SECTION_8", "SECTION_8_AND_9")
    assert isinstance(data["in_grace_period"], bool)
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert data["status"] in ("SUBMITTED", "ACCEPTED")


def assert_madrid_application(data: dict):
    _assert_common(data)
    assert isinstance(data["designated_countries"], list)
    assert data["status"] in (
        "PENDING_CERTIFICATION", "CERTIFIED", "FORWARDED_TO_WIPO", "CEASED",
    )
    assert is_iso8601_timestamp(data["dependency_end_at"])
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0


def assert_docket_deadline(data: dict):
    _assert_common(data)
    assert data["subject_type"] in (
        "OFFICE_ACTION", "OPPOSITION_ANSWER", "SOU", "MAINTENANCE", "OPPOSITION_WINDOW",
    )
    assert is_iso8601_timestamp(data["due_at"])
    assert data["status"] in ("PENDING", "MET", "MISSED", "CANCELLED")
