"""Entity assertions and domain invariant checkers.

Structural checks only assert what the PRD promises on every resource
(PRD §2.5: id, created_at, updated_at, version) plus fields the PRD
narratives name for each resource (PRD §3).
"""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_clock_instant(actual: str, expected_iso: str):
    """Assert a clock-stamped field records the expected instant.

    Clock-stamped fields (`submitted_at`, `filed_at`,
    `expedited_cert_entered_at`) are "stamped from the logical clock"
    (PRD §3.5, §3.8, §3.9): the PRD pins the instant, not the string
    representation — §2.5's three-fractional-digit format rule is scoped
    to the common resource properties (id, created_at, updated_at,
    version). Compare parsed instants so either ISO 8601 rendering
    ("...T00:00:00Z" or "...T00:00:00.000Z") satisfies the rule.
    """
    def _parse(s: str) -> datetime:
        return datetime.fromisoformat(s.strip().replace("Z", "+00:00"))

    assert is_iso8601_timestamp(actual), (
        f"not an ISO 8601 UTC timestamp: {actual!r}"
    )
    assert _parse(actual) == _parse(expected_iso), (
        f"clock instant mismatch: {actual!r} != {expected_iso!r}"
    )


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')}"
    )


def assert_game_title(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title_code"], str) and data["title_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["platform_codes"], list) and len(data["platform_codes"]) >= 1
    for code in data["platform_codes"]:
        assert code in ("PS5", "XSX", "SWITCH2", "PC")
    for field in ("cert_budget_total_cents", "cert_budget_available_cents",
                  "cert_budget_escrow_cents", "cert_budget_spent_cents",
                  "open_blocker_count", "hotfix_rollback_count"):
        assert isinstance(data[field], int), f"{field} must be int"
    assert isinstance(data["embargoed"], bool)
    assert data["status"] in (
        "CONCEPT", "IN_DEVELOPMENT", "CERTIFICATION", "CERT_APPROVED",
        "LAUNCHED", "SUNSET",
    )


def assert_qa_vendor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["weekly_capacity_hours"], int)
    assert isinstance(data["cost_rate_cents_per_hour"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")


def assert_test_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title_id"], str)
    assert data["platform_code"] in ("PS5", "XSX", "SWITCH2", "PC")
    assert data["status"] in ("DRAFT", "IN_REVIEW", "APPROVED", "LOCKED", "ARCHIVED")
    assert isinstance(data["entries"], list)
    assert isinstance(data["required_entries_total"], int)
    assert isinstance(data["covered_required_count"], int)


def assert_test_assignment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["vendor_id"], str)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["feature_area"], str)
    assert isinstance(data["reserved_hours"], int)
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "DONE", "CANCELLED")


def assert_build(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title_id"], str)
    assert data["platform_code"] in ("PS5", "XSX", "SWITCH2", "PC")
    assert isinstance(data["version_string"], str) and data["version_string"]
    assert data["status"] in (
        "RECEIVED", "IN_TEST", "TEST_PASSED", "TEST_FAILED",
        "CANDIDATE", "CONSUMED", "RETIRED",
    )


def assert_bug_report(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title_id"], str)
    assert isinstance(data["build_id"], str)
    assert data["severity"] in ("BLOCKER", "CRITICAL", "MAJOR", "MINOR", "TRIVIAL")
    assert data["category"] in (
        "GAMEPLAY", "AUDIO", "GRAPHICS", "NETWORK",
        "COMPLIANCE", "LOCALIZATION", "PERFORMANCE",
    )
    assert isinstance(data["is_regression"], bool)
    assert isinstance(data["sla_breached"], bool)
    assert isinstance(data["reopened_count"], int)
    assert data["status"] in (
        "OPEN", "TRIAGED", "IN_PROGRESS", "RESOLVED", "VERIFIED",
        "CLOSED", "REOPENED", "WONT_FIX", "DUPLICATE",
    )


def assert_submission_package(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title_id"], str)
    assert data["platform_code"] in ("PS5", "XSX", "SWITCH2", "PC")
    assert isinstance(data["build_id"], str)
    assert isinstance(data["test_plan_id"], str)
    assert isinstance(data["round"], int) and data["round"] >= 1
    assert data["status"] in (
        "ASSEMBLING", "SUBMITTED", "IN_REVIEW", "APPROVED",
        "REJECTED", "CLOSED", "WITHDRAWN", "SUPERSEDED",
    )


def assert_compliance_checklist(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["submission_package_id"], str)
    assert data["platform_code"] in ("PS5", "XSX", "SWITCH2", "PC")
    assert isinstance(data["items"], list)
    for counter in ("total_items", "passed_count", "waived_count",
                    "na_count", "failed_count", "unverified_count"):
        assert isinstance(data[counter], int), f"{counter} must be int"
    assert data["total_items"] == len(data["items"]), "total_items tracks items"


def assert_cert_finding(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["submission_package_id"], str)
    assert data["severity"] in ("CATEGORY_A", "CATEGORY_B")
    assert isinstance(data["requirement_code"], str)
    assert isinstance(data["reopen_count"], int)
    assert data["status"] in ("OPEN", "FIXED_IN_BUILD", "VERIFIED")


def assert_age_rating_filing(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title_id"], str)
    assert data["territory"] in ("ESRB", "PEGI", "CERO", "USK")
    assert isinstance(data["content_descriptors"], list)
    assert data["status"] in ("DRAFT", "FILED", "GRANTED", "CHALLENGED")


def assert_localization_pack(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title_id"], str)
    assert isinstance(data["locale"], str) and data["locale"]
    assert isinstance(data["is_required"], bool)
    assert data["translation_status"] in ("DRAFT", "TRANSLATING", "LQA", "LOCKED")
    assert data["signoff_status"] in ("UNSIGNED", "SIGNED")


def assert_release_window(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title_id"], str)
    assert data["platform_code"] in ("PS5", "XSX", "SWITCH2", "PC")
    assert data["kind"] in ("LAUNCH", "DAY_ONE_PATCH", "HOTFIX_DEPLOY")
    assert data["status"] in (
        "RESERVED", "CONFIRMED", "CONSUMED", "RELEASED", "EXPIRED",
    )


def assert_cert_blackout_window(data: dict):
    _assert_common_fields(data)
    assert data["platform_code"] in ("PS5", "XSX", "SWITCH2", "PC")
    assert isinstance(data["buffer_hours"], int)


def assert_hotfix(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title_id"], str)
    assert data["platform_code"] in ("PS5", "XSX", "SWITCH2", "PC")
    assert isinstance(data["build_id"], str)
    assert data["severity"] in ("S1", "S2")
    assert data["status"] in (
        "DECLARED", "IN_DEV", "READY_FOR_CERT",
        "EXPEDITED_CERT", "DEPLOYED", "ROLLED_BACK",
    )


def assert_budget_invariant(title: dict):
    """Budget conservation invariant (PRD §2.7): available + escrow + spent
    always sums exactly to cert_budget_total_cents."""
    total = title["cert_budget_available_cents"] + \
        title["cert_budget_escrow_cents"] + title["cert_budget_spent_cents"]
    assert total == title["cert_budget_total_cents"], (
        f"available+escrow+spent == {total}, "
        f"expected {title['cert_budget_total_cents']}"
    )


def assert_vendor_hours_invariant(vendor: dict):
    """Weekly ledger conservation (PRD §3.3): committed + available always
    equals weekly_capacity_hours."""
    committed = vendor["committed_hours_current_week"]
    available = vendor["available_hours_current_week"]
    assert committed + available == vendor["weekly_capacity_hours"], (
        f"committed {committed} + available {available} != "
        f"capacity {vendor['weekly_capacity_hours']}"
    )
