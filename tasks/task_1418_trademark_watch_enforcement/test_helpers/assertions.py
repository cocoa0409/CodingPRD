"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating 'Z' and fractional digits."""
    assert isinstance(value, str), f"expected ISO string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_instant_equal(actual: str, expected_iso: str, label: str = "instant"):
    """Two ISO strings denote the same instant, regardless of serialization."""
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["enforcement_budget_cents"], int)
    assert isinstance(data["budget_spent_cents"], int)
    assert isinstance(data["budget_remaining_cents"], int)
    assert isinstance(data["exposure_index"], (int, float))
    assert data["watch_posture"] in ("STANDARD", "ELEVATED")


def assert_budget_ledger_invariant(client: dict):
    """PRD ledger invariant: spent + remaining == enforcement budget, exactly."""
    assert client["budget_spent_cents"] + client["budget_remaining_cents"] == client[
        "enforcement_budget_cents"
    ], (
        f"ledger drift: {client['budget_spent_cents']} + "
        f"{client['budget_remaining_cents']} != {client['enforcement_budget_cents']}"
    )


def assert_trademark_record(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "APPLICATION_PENDING", "PUBLISHED", "REGISTERED",
        "UNDER_CHALLENGE", "MAINTENANCE_DUE", "CANCELLED",
    )
    assert isinstance(data["nice_classes"], list) and len(data["nice_classes"]) >= 1
    assert isinstance(data["verified_evidence_count"], int)


def assert_watch_alert(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "NEW", "TRIAGED", "UNDER_ASSESSMENT", "MONITORING", "ESCALATED", "DISMISSED",
    )
    assert isinstance(data["provisional_score"], (int, float))
    assert data["provisional_tier"] in ("LOW", "MEDIUM", "HIGH")
    assert isinstance(data["assessment_round"], int)
    assert isinstance(data["confirmed_counterfeit_count"], int)
    assert data["escalation_level"] in ("STANDARD", "URGENT")


def assert_enforcement_matter(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "RESOLVED")
    assert data["matter_type"] in ("OPPOSITION", "CANCELLATION", "INFRINGEMENT", "COUNTERFEIT")
    assert data["posture"] in ("NORMAL", "JEOPARDY")
    assert isinstance(data["accrued_fees_cents"], int)
    assert isinstance(data["open_deadline_count"], int)


def assert_deadline(data: dict):
    _assert_common(data)
    assert data["status"] in ("DOCKETED", "PENDING", "EXTENDED", "SATISFIED", "MISSED")
    assert data["deadline_type"] in (
        "OPPOSITION_WINDOW", "RESPONSE_DUE", "OFFICE_ACTION", "RENEWAL", "CUSTOM",
    )
    assert data["computation_variant"] in ("CALENDAR_ROLL_FORWARD", "BUSINESS_DAY_COUNT")
    assert isinstance(data["extension_count"], int)


def assert_cease_desist_letter(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "PENDING_REVIEW", "APPROVED", "ISSUED", "NEGOTIATING",
        "COMPLIED", "REFUSED", "ESCALATED_LITIGATION", "VOID",
    )
    assert isinstance(data["reissue_count"], int)


def assert_takedown_filing(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "FILED", "REJECTED", "APPEALED", "REMOVED", "REINSTATED")
    assert data["platform"] in ("AMAZON", "EBAY", "ALIBABA", "META", "DOMAIN_REGISTRAR")
    assert data["basis"] in ("TRADEMARK", "COUNTERFEIT")
    assert isinstance(data["fee_cents"], int)
    assert isinstance(data["appeal_count"], int)


def assert_coexistence_agreement(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "PROPOSED", "COUNTERED", "EXECUTED", "MONITORING",
        "BREACH_ALLEGED", "CURE_PERIOD", "TERMINATED", "EXPIRED",
    )
    assert isinstance(data["round_count"], int)
    assert isinstance(data["territory_codes"], list)


def assert_use_evidence_item(data: dict):
    _assert_common(data)
    assert data["status"] in ("COLLECTED", "VERIFIED", "REJECTED")
    assert 1 <= data["nice_class"] <= 45


def assert_maintenance_filing(data: dict):
    _assert_common(data)
    assert data["status"] in ("PREPARED", "SUBMITTED", "LATE_FILED", "ACCEPTED", "REJECTED_OFFICE")
    assert isinstance(data["fee_base_cents"], int)
    assert isinstance(data["fee_surcharge_cents"], int)
    assert isinstance(data["late_fee_cents"], int)
    assert isinstance(data["fee_total_cents"], int)


def assert_clearance_search(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "CLEARED", "BLOCKED")
    assert isinstance(data["conflict_hits"], list)
    assert isinstance(data["unresolved_hit_count"], int)
    assert data["risk_rating"] in ("LOW", "MEDIUM", "HIGH")


def assert_customs_recordation(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "EXPIRED", "RENEWED", "REVOKED")
    assert data["customs_authority"] in ("US_CBP", "EU_TAXUD", "CN_GACC")


def assert_counterfeit_referral(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "REFERRED", "ACKNOWLEDGED")
    assert data["referral_channel"] in ("LAW_ENFORCEMENT", "CUSTOMS_SEIZE", "PLATFORM_ESCROW")
    assert isinstance(data["estimated_damages_cents"], int)
    assert isinstance(data["auto_created"], bool)
