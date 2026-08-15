"""Entity assertions and domain invariant checkers (PRD §2.5, §2.10, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_calendar_date(actual, expected_yyyy_mm_dd: str):
    """Compare an ISO 8601 calendar-date field against YYYY-MM-DD (PRD §2.4)."""
    assert isinstance(actual, str), f"Expected a calendar-date string, got {actual!r}"
    assert actual[:10] == expected_yyyy_mm_dd, (
        f"Expected calendar date {expected_yyyy_mm_dd}, got {actual!r}"
    )


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_farm(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["certification_program"] in ("CONVENTIONAL", "CAGE_FREE", "PASTURE")
    assert isinstance(data["daily_overhead_cents"], int)
    assert data["compliance_posture"] in ("CLEAR", "WATCH", "SUSPENDED")
    assert isinstance(data["active_flock_count"], int)


def assert_house(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("EMPTY", "OCCUPIED", "DEPOPULATING", "CLEANING", "RESTING")
    assert isinstance(data["capacity_hens"], int)


def assert_flock(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "PLACED",
        "GROWING",
        "LAYING",
        "MOLT_REST",
        "DEPOPULATING",
        "DEPLETED",
    )
    assert data["quarantine_status"] in ("CLEAR", "QUARANTINED")
    assert data["lay_cycle"] in ("FIRST", "SECOND")
    assert isinstance(data["age_weeks"], int)
    assert isinstance(data["current_hen_count"], int)
    assert isinstance(data["cumulative_eggs"], int)
    assert isinstance(data["ungraded_egg_pool"], int)
    assert isinstance(data["loose_egg_pool"], int)


def assert_feed_delivery(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "DEPLETED")
    assert isinstance(data["quantity_kg"], int)
    assert isinstance(data["remaining_kg"], int)


def assert_production_day(data: dict):
    """Production days are immutable events: id + created_at only (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 UTC timestamp"
    )
    assert "version" not in data, "a production day carries no version field"
    assert "updated_at" not in data, "a production day carries no updated_at field"
    assert isinstance(data["eggs_collected"], int)
    assert isinstance(data["rejected_eggs"], int)
    assert isinstance(data["feed_issued_kg"], int)
    assert isinstance(data["mortality_count"], int)
    assert isinstance(data["hens_at_start"], int)
    assert isinstance(data["feed_cost_cents"], int)


def assert_grading_run(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "CONFIRMED", "VOIDED")
    assert data["grade"] in ("AA", "A", "B")
    assert isinstance(data["eggs_to_grade"], int)


def assert_egg_lot(data: dict):
    _assert_common_fields(data)
    assert data["lifecycle_status"] in (
        "FRESH",
        "RELEASED",
        "ALLOCATED",
        "SHIPPED",
        "CLOSED",
        "EXPIRED",
        "RECALLED",
    )
    assert data["hold_status"] in ("CLEAR", "HELD")
    assert data["size_class"] in (
        "PEEWEE",
        "SMALL",
        "MEDIUM",
        "LARGE",
        "XLARGE",
        "JUMBO",
    )
    assert data["grade"] in ("AA", "A", "B")
    assert data["claim_program"] in ("CONVENTIONAL", "CAGE_FREE", "PASTURE")
    assert isinstance(data["dozen_count"], int)


def assert_contract(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "EXPIRED")
    assert data["pricing_model"] in ("MARKET_INDEX", "COST_PLUS")
    assert data["claim_required"] in ("NONE", "CAGE_FREE", "PASTURE")
    assert isinstance(data["allocated_dozen"], int)
    assert isinstance(data["shipped_dozen"], int)
    assert isinstance(data["held_allocated_dozen"], int)


def assert_settlement(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("DRAFT", "FINALIZED", "VOIDED")


def assert_salmonella_test(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("SCHEDULED", "COLLECTED", "RESULTED", "CLEARED", "RESOLVED")
    assert data["test_type"] in ("ENVIRONMENTAL", "EGG_POOL")


def assert_compliance_audit(data: dict):
    _assert_common_fields(data)
    assert data["status"] in (
        "SCHEDULED",
        "IN_PROGRESS",
        "FINDINGS_RECORDED",
        "CLOSED_PASSED",
        "CLOSED_FAILED",
    )
    assert data["standard"] in ("USDA_CAGE_FREE", "PASTURE_RAISED", "FDA_EGG_SAFETY")


def assert_recall(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("INITIATED", "SCOPED", "CLOSED")
    assert data["reason"] in ("SALMONELLA", "QUALITY", "LABELING")


def assert_disposition(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("PLANNED", "COMPLETED", "VOIDED")
    assert data["method"] in ("RENDERING", "COMPOST", "LIVE_SALE", "EUTHANIZED")
    assert isinstance(data["hen_count"], int)


def assert_hen_ledger(flock: dict, completed_disposition_hens: int):
    """Hen ledger of PRD §2.10: initial == current + mortality + disposed."""
    lhs = flock["initial_hen_count"]
    rhs = (
        flock["current_hen_count"]
        + flock["cumulative_mortality"]
        + completed_disposition_hens
    )
    assert lhs == rhs, (
        f"Hen ledger drift: initial {lhs} != current {flock['current_hen_count']} "
        f"+ mortality {flock['cumulative_mortality']} + disposed "
        f"{completed_disposition_hens}"
    )
