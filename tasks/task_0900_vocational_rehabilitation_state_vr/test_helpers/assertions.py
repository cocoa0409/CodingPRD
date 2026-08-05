"""Entity assertions and domain invariant checkers for the VR API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

CASE_STATUSES = [
    "REFERRED", "APPLICATION", "WAITLISTED", "PLAN_DEVELOPMENT", "SERVICES_ACTIVE",
    "EMPLOYED", "INELIGIBLE", "CLOSED_REHABILITATED", "CLOSED_OTHER",
]


def _assert_common_full(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID with no prefix, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def _assert_common_light(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID with no prefix, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "lightweight records must not carry version"
    assert "updated_at" not in data, "lightweight records must not carry updated_at"


def assert_counselor(data: dict):
    _assert_common_light(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["email"], str) and data["email"]


def assert_supervisor(data: dict):
    _assert_common_light(data)
    assert isinstance(data["name"], str) and data["name"]


def assert_progress_review(data: dict):
    _assert_common_light(data)
    assert isinstance(data["reported_weekly_wage_cents"], int)


def assert_provider(data: dict):
    _assert_common_full(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["service_categories"], list)
    assert isinstance(data["max_concurrent_authorizations"], int)
    assert isinstance(data["pending_disbursement_cents"], int)
    assert isinstance(data["ledger_paid_cents"], int)


def assert_priority_category(data: dict):
    _assert_common_full(data)
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["slot_capacity"], int)
    assert isinstance(data["slots_used"], int) and data["slots_used"] >= 0
    assert isinstance(data["available_slots"], int) and data["available_slots"] >= 0
    assert data["available_slots"] == data["slot_capacity"] - data["slots_used"]


def assert_case(data: dict):
    _assert_common_full(data)
    assert data["status"] in CASE_STATUSES, f"unexpected case status {data['status']!r}"
    assert isinstance(data["funds_committed_cents"], int)
    assert isinstance(data["funds_paid_cents"], int)
    assert isinstance(data["funds_available_cents"], int)


def assert_case_ledger_invariant(data: dict):
    """funds_available == budget - committed - paid (PRD §2.8)."""
    assert data["funds_available_cents"] == (
        data["budget_allocated_cents"] - data["funds_committed_cents"] - data["funds_paid_cents"]
    ), "case ledger must reconcile: available == budget - committed - paid"
    assert data["funds_committed_cents"] >= 0
    assert data["funds_paid_cents"] >= 0


def assert_ipe(data: dict):
    _assert_common_full(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "AMENDING", "CLOSED")


def assert_authorization(data: dict):
    _assert_common_full(data)
    assert data["status"] in ("REQUESTED", "APPROVED", "COMPLETED", "CANCELLED")
    assert isinstance(data["consumer_share_cents"], int)
    assert isinstance(data["agency_share_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)


def assert_payment(data: dict):
    _assert_common_full(data)
    assert data["status"] in ("PENDING", "ISSUED", "VOIDED")
    assert isinstance(data["amount_cents"], int)


def assert_placement(data: dict):
    _assert_common_full(data)
    assert data["status"] in ("PLACED", "STABILIZING", "DESTABILIZED", "STABLE", "CLOSED")
