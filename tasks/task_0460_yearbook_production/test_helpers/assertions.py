"""Entity assertions for the Yearbook Production API.

Each assert_{entity}() validates the response structure against the PRD contract:
UUID id, ISO-8601 timestamps, integer version, and the entity-specific fields.
All entities are mutable and carry id, created_at, updated_at, version (PRD §2.4).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1"


def assert_yearbook(data: dict):
    _assert_common(data)
    assert isinstance(data["school_name"], str)
    assert isinstance(data["academic_year"], str)
    assert isinstance(data["target_page_count"], int)
    assert isinstance(data["unit_cost_cents"], int)
    assert data["production_phase"] in [
        "LADDER_BUILD", "CONTENT", "PROOFING", "PLANT", "PRINTING", "DELIVERED",
    ]
    assert isinstance(data["ladder_filled_count"], int)
    assert isinstance(data["ladder_complete"], bool)
    assert isinstance(data["ad_revenue_cents"], int)
    assert isinstance(data["presale_revenue_cents"], int)
    assert isinstance(data["production_cost_cents"], int)


def assert_ladder_page(data: dict):
    _assert_common(data)
    assert isinstance(data["yearbook_id"], str)
    assert isinstance(data["page_number"], int)
    assert data["section"] in [
        "STUDENT_LIFE", "ACADEMICS", "SPORTS", "CLUBS", "ADS", "SIGNATURE",
    ]
    assert isinstance(data["template_code"], str)
    assert data["spread_span"] in (1, 2)
    assert isinstance(data["required_submission_count"], int)
    assert isinstance(data["approved_submission_count"], int)
    assert data["status"] in [
        "DRAFT", "IN_REVIEW", "CHANGES_REQUESTED", "APPROVED", "LOCKED",
    ]


def assert_submission(data: dict):
    _assert_common(data)
    assert isinstance(data["ladder_page_id"], str)
    assert data["kind"] in ("PHOTO", "QUOTE")
    assert isinstance(data["contributor_id"], str)
    assert isinstance(data["asset_ref"], str)
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED")


def assert_staff_assignment(data: dict):
    _assert_common(data)
    assert isinstance(data["yearbook_id"], str)
    assert isinstance(data["staff_user_id"], str)
    assert data["role_title"] in [
        "EDITOR", "PHOTOGRAPHER", "SECTION_LEAD", "SIGNATURE_COORDINATOR",
    ]
    assert isinstance(data["assigned_page_count"], int)
    assert data["status"] in ("ACTIVE", "RELEASED")


def assert_ad_contract(data: dict):
    _assert_common(data)
    assert isinstance(data["yearbook_id"], str)
    assert isinstance(data["ladder_page_id"], str)
    assert isinstance(data["sponsor_name"], str)
    assert data["size"] in ("FULL", "HALF", "QUARTER")
    assert isinstance(data["list_price_cents"], int)
    assert isinstance(data["net_price_cents"], int)
    assert data["status"] in ("DRAFT", "SIGNED", "PLACED", "VOIDED")


def assert_proof(data: dict):
    _assert_common(data)
    assert isinstance(data["yearbook_id"], str)
    assert isinstance(data["round_number"], int)
    assert data["status"] in (
        "OPEN", "CHANGES_REQUESTED", "PLANT_SUBMITTED", "PLANT_APPROVED",
    )


def assert_presale_order(data: dict):
    _assert_common(data)
    assert isinstance(data["yearbook_id"], str)
    assert isinstance(data["buyer_name"], str)
    assert isinstance(data["quantity"], int)
    assert data["price_tier"] in ("EARLY", "STANDARD")
    assert isinstance(data["total_price_cents"], int)
    assert data["status"] in ("PLACED", "PAID", "FULFILLED", "CANCELLED")


def assert_print_run(data: dict):
    _assert_common(data)
    assert isinstance(data["yearbook_id"], str)
    assert isinstance(data["quantity"], int)
    assert isinstance(data["delivery_address"], str)
    assert isinstance(data["cost_cents"], int)
    assert data["status"] in ("COMMITTED", "SHIPPED", "DELIVERED")


def assert_distribution_record(data: dict):
    _assert_common(data)
    assert isinstance(data["yearbook_id"], str)
    assert isinstance(data["presale_order_id"], str)
    assert isinstance(data["recipient_name"], str)
    assert isinstance(data["copies_handed"], int)
    assert data["status"] == "HANDED_OUT"
