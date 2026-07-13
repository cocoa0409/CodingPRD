"""Entity assertions and domain invariant checkers for the DNA genealogy API."""

from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .constants import KIT_PRICE_CENTS


# ─── Timestamp helpers ──────────────────────────────────────────────────────

def parse_instant(value: str) -> datetime:
    """Parse a server ISO 8601 UTC timestamp into an aware datetime."""
    assert isinstance(value, str) and value, f"Expected an ISO 8601 timestamp, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected_iso: str, field: str = "timestamp") -> None:
    """Assert a server-written instant equals the expected instant (formatting-agnostic)."""
    assert actual is not None, f"{field} must not be null (expected {expected_iso})"
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"Expected {field} == {expected_iso}, got {actual}"
    )


def _assert_common_fields(data: dict, entity: str) -> None:
    """PRD §2.4: every persisted resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1"
    )


# ─── Entity assertions ──────────────────────────────────────────────────────

def assert_customer(data: dict) -> None:
    _assert_common_fields(data, "Customer")
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["display_name"], str)
    assert data["account_status"] in ("ACTIVE", "PURGED")
    assert data["dna_status"] in ("NO_SAMPLE", "PROCESSING", "DNA_READY", "PURGED")
    assert isinstance(data["wallet_credit_cents"], int)
    assert data["wallet_credit_cents"] >= 0, "wallet_credit_cents may never go negative"
    assert isinstance(data["matching_opt_in"], bool)
    assert isinstance(data["research_opt_in"], bool)
    assert isinstance(data["health_opt_in"], bool)
    assert isinstance(data["visible_match_count"], int)
    assert data["visible_match_count"] >= 0, "visible_match_count never goes below zero"


def assert_subscription(data: dict) -> None:
    _assert_common_fields(data, "Subscription")
    assert is_valid_uuid(data["customer_id"])
    assert data["tier"] in ("FREE", "PLUS", "PRO")
    assert data["pending_tier"] in (None, "FREE", "PLUS", "PRO")
    assert data["billing_status"] in ("CURRENT", "PAST_DUE", "CLOSED")
    assert data["access_status"] in ("ACTIVE", "GRACE", "LOCKED", "CANCELLED")
    assert is_iso8601_timestamp(data["current_period_start"])
    assert is_iso8601_timestamp(data["current_period_end"])
    assert isinstance(data["lifetime_charged_cents"], int)
    assert isinstance(data["published_report_count"], int)


def assert_kit(data: dict) -> None:
    _assert_common_fields(data, "Kit")
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["barcode"], str) and data["barcode"], "Kit.barcode is server-minted"
    assert data["chip_version"] in ("V4", "V5")
    assert data["price_cents"] == KIT_PRICE_CENTS, "Kit.price_cents is fixed at 9900"
    assert data["status"] in ("ORDERED", "ACTIVATED", "RECEIVED", "PROCESSED", "VOID")


def assert_sample(data: dict) -> None:
    _assert_common_fields(data, "Sample")
    assert is_valid_uuid(data["kit_id"])
    assert data["status"] in (
        "RECEIVED", "EXTRACTED", "QC_FAILED", "QUEUED",
        "GENOTYPING", "GENOTYPED", "FAILED_TERMINAL",
    )
    assert isinstance(data["extraction_attempts"], int) and data["extraction_attempts"] >= 0
    assert isinstance(data["population_scores"], list)
    assert isinstance(data["genotype_markers"], list)


def assert_lab_instrument(data: dict) -> None:
    _assert_common_fields(data, "LabInstrument")
    assert isinstance(data["name"], str) and data["name"]
    assert data["chip_version"] in ("V4", "V5")
    assert data["status"] in ("ONLINE", "MAINTENANCE")


def assert_lab_batch(data: dict) -> None:
    _assert_common_fields(data, "LabBatch")
    assert is_valid_uuid(data["instrument_id"])
    assert is_iso8601_timestamp(data["run_start_at"])
    assert is_iso8601_timestamp(data["run_end_at"])
    assert data["status"] in ("OPEN", "RUNNING", "FINALIZED", "ABORTED")
    assert isinstance(data["member_count"], int) and data["member_count"] >= 0


def assert_consent_grant(data: dict) -> None:
    _assert_common_fields(data, "ConsentGrant")
    assert is_valid_uuid(data["customer_id"])
    assert data["scope"] in ("HEALTH_TRAITS", "RELATIVE_MATCHING", "RESEARCH")
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_until"])
    assert data["status"] in ("ACTIVE", "WITHDRAWN")


def assert_report(data: dict) -> None:
    _assert_common_fields(data, "Report")
    assert is_valid_uuid(data["customer_id"])
    assert data["report_type"] in ("ETHNICITY", "HEALTH_TRAIT")
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED", "REVOKED")
    assert isinstance(data["composition"], list)
    assert isinstance(data["trait_count"], int)


def assert_relative_match(data: dict) -> None:
    _assert_common_fields(data, "RelativeMatch")
    assert is_valid_uuid(data["customer_a_id"])
    assert is_valid_uuid(data["customer_b_id"])
    assert isinstance(data["shared_cm"], (int, float))
    assert isinstance(data["segment_count"], int)
    assert data["predicted_relationship"] in (
        "PARENT_CHILD", "SIBLING", "CLOSE_COUSIN", "DISTANT_COUSIN",
    )
    assert isinstance(data["confidence_score"], (int, float))
    assert data["confidence_score"] >= 0.0, "confidence_score is floored at 0.0000"
    assert data["status"] in ("ACTIVE", "SUPPRESSED", "PURGED")


def assert_family_tree(data: dict) -> None:
    _assert_common_fields(data, "FamilyTree")
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["name"], str)
    assert data["status"] in ("ACTIVE", "ARCHIVED")
    assert isinstance(data["person_count"], int) and data["person_count"] >= 0


def assert_tree_person(data: dict) -> None:
    _assert_common_fields(data, "TreePerson")
    assert is_valid_uuid(data["tree_id"])
    assert isinstance(data["given_name"], str)
    assert isinstance(data["surname"], str)
    assert data["status"] in ("ACTIVE", "REMOVED")
    assert isinstance(data["hint_count"], int) and data["hint_count"] >= 0


def assert_record_hint(data: dict) -> None:
    _assert_common_fields(data, "RecordHint")
    assert is_valid_uuid(data["person_id"])
    assert data["hint_type"] in ("DNA_TREE", "CENSUS")
    assert data["status"] in ("PENDING", "ACCEPTED", "WITHDRAWN")


def assert_data_request(data: dict) -> None:
    _assert_common_fields(data, "DataRequest")
    assert is_valid_uuid(data["customer_id"])
    assert data["request_type"] in ("EXPORT", "DELETE")
    assert data["status"] in (
        "PENDING", "APPROVED", "SCHEDULED", "COMPLETED", "REJECTED", "CANCELLED",
    )


# ─── Domain invariant checkers ──────────────────────────────────────────────

def assert_composition(actual, expected) -> None:
    """Compare a Report.composition array against the expected [{population, share_pct}] list.

    The composition is sorted by population code ascending and its shares sum to exactly
    100.00 (PRD §3.7).
    """
    assert isinstance(actual, list), f"composition must be an array, got {actual!r}"
    assert len(actual) == len(expected), (
        f"Expected {len(expected)} composition entries, got {len(actual)}: {actual!r}"
    )
    populations = [e["population"] for e in actual]
    assert populations == sorted(populations), (
        f"composition must be sorted by population code ascending, got {populations}"
    )
    for got, want in zip(actual, expected):
        assert got["population"] == want["population"], (
            f"Expected population {want['population']}, got {got['population']}"
        )
        assert got["share_pct"] == pytest.approx(want["share_pct"], abs=0.001), (
            f"Expected {want['population']} share_pct == {want['share_pct']}, "
            f"got {got['share_pct']}"
        )
    total = sum(e["share_pct"] for e in actual)
    assert total == pytest.approx(100.00, abs=0.001), (
        f"composition shares must sum to exactly 100.00, got {total}"
    )


def assert_q1_conserved(customer: dict, subscription: dict, expected_total: int) -> None:
    """Conserved quantity Q1 (PRD §2.10): wallet_credit_cents + lifetime_charged_cents
    is unchanged across a tier change followed by a revert of that change."""
    total = customer["wallet_credit_cents"] + subscription["lifetime_charged_cents"]
    assert total == expected_total, (
        f"Q1 drifted: wallet_credit_cents ({customer['wallet_credit_cents']}) + "
        f"lifetime_charged_cents ({subscription['lifetime_charged_cents']}) == {total}, "
        f"expected {expected_total}"
    )


def assert_q2_conserved(customers: list, active_match_count: int) -> None:
    """Conserved quantity Q2 (PRD §2.10): summing visible_match_count over every customer
    always yields exactly twice the number of ACTIVE relative matches."""
    total = sum(c["visible_match_count"] for c in customers)
    assert total == 2 * active_match_count, (
        f"Q2 drifted: SUM(visible_match_count) == {total}, expected "
        f"2 * {active_match_count} == {2 * active_match_count}"
    )
