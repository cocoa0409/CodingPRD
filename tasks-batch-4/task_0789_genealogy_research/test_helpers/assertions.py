"""Entity assertions and domain invariant checkers for the Genealogy Research API."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an int >= 1, got {data.get('version')!r}"


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["tier"] in ("STANDARD", "PREMIUM"), f"unexpected tier {data.get('tier')!r}"
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_researcher(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] >= 0


def assert_repository(data: dict):
    _assert_common(data)
    assert isinstance(data["concurrent_capacity"], int) and data["concurrent_capacity"] >= 1


def assert_project(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "CLOSED")
    assert data["research_status"] in ("IN_PROGRESS", "RESEARCH_COMPLETE")
    assert data["package_type"] in ("HOURLY", "BASIC_PACKAGE", "PREMIUM_PACKAGE")
    assert data["priority"] in ("STANDARD", "RUSH")


def assert_project_ledger_invariants(data: dict):
    """The outstanding balance is defined as invoiced - paid - credited (§3.9)."""
    expected = (data["invoiced_total_cents"]
                - data["paid_total_cents"]
                - data["credited_total_cents"])
    assert data["outstanding_balance_cents"] == expected, (
        f"outstanding_balance_cents {data['outstanding_balance_cents']} != "
        f"invoiced {data['invoiced_total_cents']} - paid {data['paid_total_cents']} "
        f"- credited {data['credited_total_cents']}")


def assert_record_search(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "COMPLETED", "NO_RESULTS", "CANCELLED")


def assert_citation(data: dict):
    _assert_common(data)
    assert data["verification_status"] in ("UNVERIFIED", "VERIFIED", "DISPUTED")
    assert data["source_type"] in ("VITAL_RECORD", "CENSUS", "CHURCH", "DNA", "OTHER")
    assert data["quality"] in ("PRIMARY", "SECONDARY", "INDIRECT")


def assert_person(data: dict):
    _assert_common(data)
    assert data["verification_status"] in ("DRAFT", "UNDER_REVIEW", "VERIFIED")
    assert isinstance(data["citation_count"], int)
    assert isinstance(data["verified_citation_count"], int)


def assert_dna_interpretation(data: dict):
    _assert_common(data)
    assert data["status"] in ("ORDERED", "INTERPRETED", "CANCELLED")


def assert_document_request(data: dict):
    _assert_common(data)
    assert data["retrieval_status"] in ("REQUESTED", "RETRIEVED", "UNAVAILABLE")
    assert data["translation_status"] in ("NOT_NEEDED", "PENDING", "TRANSLATED")


def assert_heirloom(data: dict):
    _assert_common(data)
    assert data["archive_status"] in ("RECEIVED", "CATALOGUED", "DIGITIZED", "RETURNED")


def assert_deliverable(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "REVISION_REQUESTED")


def assert_milestone(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "READY", "INVOICED", "PAID", "CANCELLED")


def assert_time_entry(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "VOIDED")


def assert_appointment(data: dict):
    _assert_common(data)
    assert data["status"] in ("BOOKED", "CANCELLED", "COMPLETED")
