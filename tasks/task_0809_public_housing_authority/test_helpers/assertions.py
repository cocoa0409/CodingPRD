"""Entity assertions for the PHA API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_applicant(data: dict):
    _common(data)
    assert isinstance(data["household_name"], str) and data["household_name"]
    assert data["status"] in ("APPLIED", "WAITLISTED", "HOUSED", "WITHDRAWN")
    assert isinstance(data["annual_gross_income_cents"], int)
    assert isinstance(data["household_size"], int)
    assert is_iso8601_timestamp(data["application_date"])


def assert_member(data: dict):
    _common(data)
    assert data["relationship"] in ("HEAD", "SPOUSE", "DEPENDENT", "OTHER_ADULT")
    assert data["annual_income_cents"] >= 0
    assert data["nonrecurring_income_cents"] >= 0


def assert_preference_claim(data: dict):
    _common(data)
    assert data["status"] in ("CLAIMED", "VERIFIED", "DENIED")
    assert isinstance(data["points_awarded"], int)


def assert_waitlist(data: dict):
    _common(data)
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["lottery_drawn"], bool)
    assert 0 <= data["bedroom_size"] <= 6


def assert_waitlist_entry(data: dict):
    _common(data)
    assert data["status"] in ("PENDING", "ACTIVE", "OFFERED", "HOUSED", "PURGED", "WITHDRAWN")
    assert isinstance(data["total_points"], int)
    assert isinstance(data["refusal_count"], int)


def assert_unit(data: dict):
    _common(data)
    assert data["status"] in ("AVAILABLE", "OFFERED", "OCCUPIED")
    assert data["income_limit_cents"] > 0
    assert data["utility_allowance_cents"] >= 0


def assert_offer(data: dict):
    _common(data)
    assert data["status"] in ("PENDING", "ACCEPTED", "REFUSED")
    assert is_iso8601_timestamp(data["offered_at"])
    assert is_iso8601_timestamp(data["expires_at"])


def assert_tenancy(data: dict):
    _common(data)
    assert data["status"] in ("ACTIVE", "TERMINATED")
    assert isinstance(data["monthly_tenant_rent_cents"], int)
    assert isinstance(data["utility_reimbursement_cents"], int)


def assert_certification(data: dict):
    _common(data)
    assert data["cert_type"] in ("INITIAL", "ANNUAL", "INTERIM")
    assert data["status"] in ("DRAFT", "EFFECTIVE", "SUPERSEDED")
    assert data["hud_status"] in ("NOT_SUBMITTED", "SUBMITTED", "ACCEPTED", "REJECTED")


def assert_interim_change(data: dict):
    _common(data)
    assert data["change_type"] in ("INCOME_DECREASE", "INCOME_INCREASE", "COMPOSITION")
    assert data["status"] in ("REPORTED", "PROCESSED", "DENIED")


def assert_grievance(data: dict):
    _common(data)
    assert data["grievance_type"] in ("GRIEVANCE", "EVICTION")
    assert data["status"] in ("FILED", "SUSTAINED", "OVERRULED")
