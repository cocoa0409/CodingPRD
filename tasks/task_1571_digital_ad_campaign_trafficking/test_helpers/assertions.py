"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_IO_STATUSES = ["DRAFT", "APPROVED", "ACTIVE", "COMPLETED", "CLOSED", "CANCELLED"]
_LI_STATUSES = ["DRAFT", "TRAFFICKED", "LIVE", "PAUSED", "COMPLETED", "CANCELLED"]
_CR_STATUSES = [
    "UPLOADED", "IN_QA", "QA_PASSED", "QA_FAILED", "TAGGED", "LIVE", "PAUSED",
    "ARCHIVED",
]
_SNAP_STATUSES = ["POSTED", "VOIDED"]
_MG_STATUSES = ["PROPOSED", "APPROVED", "APPLIED", "REJECTED", "REVERSED"]
_REC_STATUSES = ["OPEN", "RECONCILED", "LOCKED"]
_WRAP_STATUSES = ["DRAFT", "FINALIZED"]


def _assert_common_fields(data: dict):
    """Primary-resource system fields per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_ledger_fields(data: dict):
    """Append-only ledger records carry only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, \
        "updated_at must be absent from append-only ledger records"
    assert "version" not in data, \
        "version must be absent from append-only ledger records"


def assert_insertion_order(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _IO_STATUSES
    assert isinstance(data["advertiser_name"], str)
    assert isinstance(data["total_budget_cents"], int)
    assert data["total_budget_cents"] > 0
    assert data["billing_basis"] in ["AGENCY_PLATFORM", "THIRD_PARTY_TAG", "LOWER_OF"]
    assert isinstance(data["booked_budget_cents"], int)
    assert isinstance(data["total_applied_credit_cents"], int)


def assert_line_item(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _LI_STATUSES
    assert data["fraud_posture"] in ["CLEAR", "BREACH"]
    assert data["pacing_mode"] in ["EVEN", "ASAP"]
    assert isinstance(data["goal_impressions"], int)
    assert data["goal_impressions"] > 0
    assert isinstance(data["cpm_rate_cents"], int)
    assert data["cpm_rate_cents"] > 0
    assert isinstance(data["budget_cents"], int)
    assert isinstance(data["delivered_impressions"], int)
    assert isinstance(data["delivered_clicks"], int)
    assert isinstance(data["delivered_spend_cents"], int)
    assert isinstance(data["pacing_projection_impressions"], int)
    assert isinstance(data["pacing_projection_trailing_impressions"], int)
    assert isinstance(data["pacing_alert"], bool)


def assert_creative(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _CR_STATUSES
    assert isinstance(data["name"], str)
    assert isinstance(data["width"], int) and data["width"] > 0
    assert isinstance(data["height"], int) and data["height"] > 0


def assert_delivery_snapshot(data: dict):
    _assert_ledger_fields(data)
    assert data["status"] in _SNAP_STATUSES
    assert isinstance(data["impressions"], int) and data["impressions"] >= 0
    assert isinstance(data["clicks"], int) and data["clicks"] >= 0
    assert isinstance(data["spend_cents"], int) and data["spend_cents"] >= 0


def assert_impression_event(data: dict):
    _assert_ledger_fields(data)
    assert isinstance(data["user_key"], str)


def assert_verification_report(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["OPEN", "CLOSED"]
    assert data["vendor"] in ["MOAT", "IAS", "DOUBLEVERIFY"]
    assert data["assessment"] in ["PASS", "BREACH"]
    assert isinstance(data["measured_impressions"], int)
    assert data["measured_impressions"] > 0
    assert isinstance(data["make_good_max_credit_cents"], int)


def assert_make_good(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _MG_STATUSES
    assert data["kind"] in ["CREDIT", "BONUS_IMPRESSIONS"]


def assert_reconciliation(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _REC_STATUSES
    assert isinstance(data["third_party_impressions"], int)
    assert data["third_party_impressions"] >= 0
    assert isinstance(data["agency_impressions"], int)


def assert_wrap_report(data: dict):
    _assert_common_fields(data)
    assert data["status"] in _WRAP_STATUSES
    assert data["attribution_model"] in ["LINEAR_CLICKS", "VIEW_WEIGHTED"]
    assert isinstance(data["total_conversions"], int)
    assert isinstance(data["total_delivered_impressions"], int)
    assert isinstance(data["total_spend_cents"], int)
    assert isinstance(data["total_billable_cents"], int)
    assert isinstance(data["total_applied_credit_cents"], int)
    assert isinstance(data["net_billable_cents"], int)
    assert data["net_billable_cents"] >= 0
    assert isinstance(data["attribution"], list)


def assert_attribution_sums_to_total(wrap: dict):
    """Attributed conversions must sum exactly to total_conversions (PRD §3.7)."""
    total = sum(entry["attributed_conversions"] for entry in wrap["attribution"])
    assert total == wrap["total_conversions"], (
        f"attributed conversions {total} != total_conversions "
        f"{wrap['total_conversions']}"
    )
