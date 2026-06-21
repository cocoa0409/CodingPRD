"""Entity assertions and domain invariant checkers (PRD-driven).

These verify response shape and the conserved-ledger invariants that the PRD
guarantees (Section 2.8). Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_CASE_STATUSES = {
    "FILED", "AWAITING_RESPONSE", "DEFAULT_PENDING", "CONTESTED", "DISCOVERY",
    "MEDIATION", "AWAITING_JUDGMENT", "JUDGMENT_ENTERED", "DISMISSED",
}


def _assert_common(data: dict):
    """id + created_at present and well-formed (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"


def _assert_versioned(data: dict):
    """updated_at + version present (entities with common_fields:true)."""
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive int, got {data.get('version')!r}"


def assert_guideline_schedule(data: dict):
    """GuidelineSchedule is immutable config: id + created_at, no updated_at/version."""
    _assert_common(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["basic_obligation_tiers"], list)
    assert "updated_at" not in data, "GuidelineSchedule must NOT carry updated_at (immutable config)"
    assert "version" not in data, "GuidelineSchedule must NOT carry version (immutable config)"


def assert_case(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert data["status"] in _CASE_STATUSES, f"unexpected case status {data['status']!r}"
    assert isinstance(data["state_code"], str)
    assert isinstance(data["active_support_total_cents"], int)
    assert isinstance(data["net_fees_collected_cents"], int)
    assert isinstance(data["petitioner_disclosure_verified"], bool)
    assert isinstance(data["respondent_disclosure_verified"], bool)


def assert_party(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert data["role"] in ("PETITIONER", "RESPONDENT")
    assert isinstance(data["gross_monthly_income_cents"], int)


def assert_pleading(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert data["pleading_type"] in ("PETITION", "ANSWER")
    assert data["status"] in ("DRAFT", "SERVED", "ANSWERED")


def assert_financial_disclosure(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "VERIFIED", "RETURNED")


def assert_parenting_plan(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert data["status"] in ("PROPOSED", "DISPUTED", "REVISED", "AGREED", "ADOPTED")


def assert_mediation_session(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert data["status"] in (
        "SCHEDULED", "IN_SESSION", "PARTIAL_AGREEMENT", "FULL_AGREEMENT", "IMPASSE")


def assert_support_order(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert data["support_type"] in ("CHILD", "SPOUSAL")
    assert data["variant"] in ("TEMPORARY", "FINAL")
    assert data["status"] in ("CALCULATED", "ACTIVE", "VACATED")
    assert isinstance(data["monthly_amount_cents"], int) and data["monthly_amount_cents"] >= 0


def assert_court_order(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert data["order_kind"] in ("TEMPORARY", "FINAL_JUDGMENT")
    assert data["status"] in ("DRAFT", "ENTERED", "SUPERSEDED")


def assert_hearing(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert data["status"] in ("SCHEDULED", "HELD", "CANCELLED")


def assert_ledger_equals_active_orders(case: dict, active_orders: list):
    """PRD §2.8: active_support_total_cents is the sum of monthly_amount_cents across
    every SupportOrder belonging to the case whose status is ACTIVE."""
    expected = sum(o["monthly_amount_cents"] for o in active_orders if o["status"] == "ACTIVE")
    assert case["active_support_total_cents"] == expected, (
        f"ledger drift: active_support_total_cents={case['active_support_total_cents']} "
        f"but sum of ACTIVE orders={expected}"
    )
