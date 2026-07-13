"""Entity assertions and domain invariant checkers for the Identity Theft Protection API."""

from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import CREDIT_SCORE_MAX, CREDIT_SCORE_MIN


# ─── Shared helpers ───────────────────────────────────────────────────────────

def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant (with or without fractional seconds)."""
    assert isinstance(value, str) and value, f"Expected an ISO 8601 instant, got {value!r}"
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected: str, label: str = "instant") -> None:
    """Assert two ISO 8601 UTC timestamps denote the same instant."""
    assert is_iso8601_timestamp(actual), f"{label} must be an ISO 8601 UTC timestamp: {actual!r}"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def _assert_common_fields(data: dict, entity: str) -> None:
    """id / created_at / updated_at / version, carried by every persisted resource."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601: {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


# ─── Entity assertions ────────────────────────────────────────────────────────

def assert_plan(data: dict) -> None:
    _assert_common_fields(data, "Plan")
    assert data["tier"] in ("STANDARD", "ADVANTAGE", "ULTIMATE")
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    assert isinstance(data["insurance_limit_cents"], int) and data["insurance_limit_cents"] > 0
    assert isinstance(data["max_family_members"], int) and data["max_family_members"] >= 0
    assert isinstance(data["child_monitoring_included"], bool)
    assert data["bureau_scope"] in ("SINGLE", "TRI")
    assert data["min_specialist_tier"] in ("TIER1", "TIER2", "TIER3")


def assert_subscriber(data: dict) -> None:
    _assert_common_fields(data, "Subscriber")
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["ssn_last4"], str) and len(data["ssn_last4"]) == 4
    assert is_valid_uuid(data.get("plan_id", "")), "Subscriber.plan_id must be a UUID"
    assert data["enrollment_status"] in ("PENDING_VERIFICATION", "ACTIVE", "SUSPENDED")
    assert data["monitoring_status"] in ("NOT_ENROLLED", "PENDING_DATA", "MONITORED", "PAUSED")
    assert data["insurance_status"] in ("AVAILABLE", "EXHAUSTED")
    assert isinstance(data["insurance_remaining_cents"], int)
    for field in ("risk_score", "underwriting_risk_score"):
        value = data[field]
        if value is None:
            # PRD §3.1: at enrollment "nothing else exists: no bureau profiles, no insurance
            # budget ..., no scores"; the risk variants are only "computed for the first time"
            # on verification. So an unverified subscriber legitimately carries no risk numbers.
            assert data["enrollment_status"] == "PENDING_VERIFICATION", (
                f"Subscriber.{field} may only be absent before verification"
            )
            continue
        assert isinstance(value, int), f"Subscriber.{field} must be an integer"
        assert 0 <= value <= 100, f"Subscriber.{field} must be clamped into 0..100"
    if data.get("composite_credit_score") is not None:
        assert CREDIT_SCORE_MIN <= data["composite_credit_score"] <= CREDIT_SCORE_MAX


def assert_family_member(data: dict) -> None:
    _assert_common_fields(data, "FamilyMember")
    assert is_valid_uuid(data.get("subscriber_id", ""))
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["ssn_last4"], str) and len(data["ssn_last4"]) == 4
    assert data["relationship"] in ("ADULT", "CHILD")
    assert data["monitoring_status"] in ("MONITORED", "NOT_COVERED")


def assert_bureau_profile(data: dict) -> None:
    _assert_common_fields(data, "BureauProfile")
    assert is_valid_uuid(data.get("subscriber_id", ""))
    assert data["bureau"] in ("EQUIFAX", "EXPERIAN", "TRANSUNION")
    assert data["freeze_status"] in ("UNFROZEN", "FREEZE_PENDING", "FROZEN", "THAW_PENDING")
    if data.get("credit_score") is not None:
        assert CREDIT_SCORE_MIN <= data["credit_score"] <= CREDIT_SCORE_MAX
        assert is_iso8601_timestamp(data.get("score_pulled_at", ""))


def assert_thaw_window(data: dict) -> None:
    _assert_common_fields(data, "ThawWindow")
    assert is_valid_uuid(data.get("bureau_profile_id", ""))
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert parse_instant(data["window_end"]) > parse_instant(data["window_start"])
    assert isinstance(data["purpose"], str)
    assert isinstance(data["is_currently_open"], bool)


def assert_alert(data: dict) -> None:
    _assert_common_fields(data, "Alert")
    assert is_valid_uuid(data.get("subscriber_id", ""))
    assert data["alert_type"] in ("DARK_WEB", "SSN_TRACE", "ACCOUNT_TAKEOVER", "CREDIT_INQUIRY")
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert isinstance(data["source_detail"], str)
    assert data["status"] in (
        "NEW",
        "ACKNOWLEDGED",
        "CONFIRMED_FRAUD",
        "DISMISSED",
        "ESCALATED",
        "RESOLVED",
    )
    if data.get("escalation_tier") is not None:
        assert data["escalation_tier"] in ("TIER1", "TIER2", "TIER3")


def assert_specialist(data: dict) -> None:
    _assert_common_fields(data, "Specialist")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["tier"] in ("TIER1", "TIER2", "TIER3")
    assert isinstance(data["max_caseload"], int) and data["max_caseload"] >= 1
    assert isinstance(data["max_concurrent_engagements"], int)
    assert data["max_concurrent_engagements"] >= 1
    assert isinstance(data["active_case_count"], int) and data["active_case_count"] >= 0
    assert data["status"] in ("AVAILABLE", "AT_CAPACITY")
    assert_specialist_status_invariant(data)


def assert_restoration_case(data: dict) -> None:
    _assert_common_fields(data, "RestorationCase")
    assert is_valid_uuid(data.get("subscriber_id", ""))
    assert is_valid_uuid(data.get("origin_alert_id", ""))
    assert data["status"] in ("OPEN", "ASSIGNED", "IN_PROGRESS", "PENDING_SUBSCRIBER", "RESOLVED")
    assert data["required_specialist_tier"] in ("TIER1", "TIER2", "TIER3")
    if data["status"] == "OPEN":
        assert data.get("specialist_id") is None, "an OPEN case carries no specialist"


def assert_specialist_engagement(data: dict) -> None:
    _assert_common_fields(data, "SpecialistEngagement")
    assert is_valid_uuid(data.get("specialist_id", ""))
    assert is_valid_uuid(data.get("case_id", ""))
    assert parse_instant(data["window_end"]) > parse_instant(data["window_start"])


def assert_insurance_claim(data: dict) -> None:
    _assert_common_fields(data, "InsuranceClaim")
    assert is_valid_uuid(data.get("case_id", ""))
    assert is_valid_uuid(data.get("subscriber_id", ""))
    assert isinstance(data["expenses"], list) and len(data["expenses"]) >= 1
    for line in data["expenses"]:
        assert line["category"] in (
            "LEGAL_FEES",
            "LOST_WAGES",
            "TRAVEL",
            "CHILDCARE",
            "NOTARY",
            "POSTAGE",
        )
        assert isinstance(line["amount_cents"], int) and line["amount_cents"] > 0
        assert isinstance(line["documented"], bool)
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "APPROVED",
        "DENIED",
        "PAID",
        "REVERSED",
        "SUPERSEDED",
    )
    for field in ("provisional_amount_cents", "approved_cents"):
        if data.get(field) is not None:
            assert isinstance(data[field], int) and data[field] >= 0


def assert_wallet_item(data: dict) -> None:
    _assert_common_fields(data, "WalletItem")
    assert is_valid_uuid(data.get("subscriber_id", ""))
    assert data["item_type"] in (
        "CREDIT_CARD",
        "DEBIT_CARD",
        "DRIVERS_LICENSE",
        "PASSPORT",
        "SSN_CARD",
        "INSURANCE_CARD",
    )
    assert data["status"] in ("ACTIVE", "REPORTED_LOST")
    if data["status"] == "ACTIVE":
        assert data.get("reported_lost_at") is None


# ─── Domain invariants ────────────────────────────────────────────────────────

def assert_specialist_status_invariant(specialist: dict) -> None:
    """`status` is AT_CAPACITY exactly when active_case_count >= max_caseload (PRD §3.6)."""
    expected = (
        "AT_CAPACITY"
        if specialist["active_case_count"] >= specialist["max_caseload"]
        else "AVAILABLE"
    )
    assert specialist["status"] == expected, (
        f"Specialist with active_case_count {specialist['active_case_count']} and "
        f"max_caseload {specialist['max_caseload']} must be {expected}, "
        f"got {specialist['status']}"
    )


def assert_insurance_budget_conserved(
    subscriber: dict, plan_limit_cents: int, paid_claims: list
) -> None:
    """Reimbursement-budget conservation (PRD §2.8)."""
    paid_sum = sum(c["approved_cents"] for c in paid_claims if c["status"] == "PAID")
    assert plan_limit_cents == subscriber["insurance_remaining_cents"] + paid_sum, (
        f"Budget conservation broken: limit {plan_limit_cents} != remaining "
        f"{subscriber['insurance_remaining_cents']} + paid {paid_sum}"
    )
    expected_status = (
        "EXHAUSTED" if subscriber["insurance_remaining_cents"] <= 0 else "AVAILABLE"
    )
    assert subscriber["insurance_status"] == expected_status, (
        f"insurance_status must be {expected_status} at remaining "
        f"{subscriber['insurance_remaining_cents']}"
    )


def assert_open_caseload_conserved(specialists: list, cases: list) -> None:
    """Open-caseload conservation (PRD §2.8)."""
    working = {"ASSIGNED", "IN_PROGRESS", "PENDING_SUBSCRIBER"}
    counted = sum(
        1 for c in cases if c.get("specialist_id") is not None and c["status"] in working
    )
    total = sum(sp["active_case_count"] for sp in specialists)
    assert total == counted, (
        f"Caseload conservation broken: sum(active_case_count) == {total} but "
        f"{counted} cases sit in a working state with a specialist attached"
    )