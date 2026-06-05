"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def assert_payer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["allowed_rate_cents"], int)
    assert 0 <= data["coinsurance_pct"] <= 1
    assert 0 < data["supervision_ratio_pct"] <= 1


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["status"] in ("INTAKE", "ACTIVE", "DISCHARGED")


def assert_provider(data: dict):
    _assert_common(data)
    assert data["credential"] in ("BCBA", "RBT")
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_evaluation(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "FINALIZED", "REJECTED")
    assert 0 <= data["assessment_score"] <= 180


def assert_treatment_plan(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "APPROVED", "REVISION_REQUESTED", "RETIRED"
    )


def assert_authorization(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "EXHAUSTED", "EXPIRED", "RENEWED")
    assert data["supervision_status"] in ("COMPLIANT", "DEFICIENT")


def assert_session(data: dict):
    _assert_common(data)
    assert data["service_line"] in (
        "DIRECT_THERAPY", "SUPERVISION", "PARENT_TRAINING"
    )
    assert data["status"] in ("SCHEDULED", "DELIVERED", "NO_SHOW", "CANCELLED")


def assert_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "PAID", "DENIED")


def assert_direct_pool_invariant(auth: dict):
    """PRD §2.7: reserved + delivered + remaining == authorized for the direct line."""
    total = (
        auth["reserved_direct_units"]
        + auth["delivered_direct_units"]
        + auth["remaining_direct_units"]
    )
    assert total == auth["authorized_direct_units"], (
        f"Direct-pool invariant broken: "
        f"reserved({auth['reserved_direct_units']}) + "
        f"delivered({auth['delivered_direct_units']}) + "
        f"remaining({auth['remaining_direct_units']}) "
        f"!= authorized({auth['authorized_direct_units']})"
    )
